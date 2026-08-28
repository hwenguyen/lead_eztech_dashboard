from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, desc, cast, Date, String
from datetime import datetime, timedelta, timezone
from typing import Optional
import threading
import logging
from database.db import get_db, engine, Base, SessionLocal
from database.models import DimLead, FactLeadActivity, RawConversation
from backend.schemas import LeadMetricsSummary, TrendResponse, TrendDataPoint, LeadListResponse, LeadResponse
import dateutil.parser

logger = logging.getLogger(__name__)

# Khởi tạo DB Schema (Tự động tạo bảng nếu chưa có, hữu ích cho môi trường dev/Free Tier)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Pancake Lead Reporting API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "ok", "service": "Pancake Lead API"}

@app.get("/health")
def health():
    return {"status": "healthy"}

def _strip_tz(dt: datetime) -> datetime:
    """Đảm bảo datetime luôn là naive (không timezone) để so sánh nhất quán."""
    if dt is None:
        return None
    if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt

def _date_to_dt(d_str: str) -> datetime:
    """Parse YYYY-MM-DD thành datetime tại 00:00:00."""
    return datetime.strptime(d_str.strip(), "%Y-%m-%d")

def parse_pancake_date(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        dt = dateutil.parser.parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        vn_tz = timezone(timedelta(hours=7))
        dt_vn = dt.astimezone(vn_tz)
        return dt_vn.replace(tzinfo=None)
    except Exception:
        return None

def auto_repair_contacted_dates():
    """Tự động làm sạch và đồng bộ lại chính xác contacted_dates từ raw_conversations payload theo cách batch siêu nhanh."""
    try:
        db = SessionLocal()
        raws = db.query(RawConversation).all()
        if not raws:
            db.close()
            return
            
        # Preload all activities and leads into memory in 2 fast queries instead of 10,000 queries
        all_acts = {act.conversation_id: act for act in db.query(FactLeadActivity).all()}
        all_leads = {l.id: l for l in db.query(DimLead).all()}
        
        has_changes = False
        for r in raws:
            if not r.payload or not isinstance(r.payload, dict):
                continue
            msgs = r.payload.get('messages', [])
            c_dates = set()
            for m in msgs:
                if isinstance(m, dict) and m.get('inserted_at'):
                    dt = parse_pancake_date(m.get('inserted_at'))
                    if dt:
                        c_dates.add(dt.strftime("%Y-%m-%d"))
            
            contacted_dates_str = ",".join(sorted(list(c_dates))) if c_dates else None
            
            act = all_acts.get(r.pancake_id)
            if act and act.contacted_dates != contacted_dates_str:
                act.contacted_dates = contacted_dates_str
                has_changes = True
                
            conv_inserted = parse_pancake_date(r.payload.get('inserted_at'))
            if conv_inserted and act and act.lead_id:
                lead = all_leads.get(act.lead_id)
                if lead and (not lead.first_created_at or lead.first_created_at > conv_inserted):
                    lead.first_created_at = conv_inserted
                    has_changes = True
                    
        if has_changes:
            db.commit()
        db.close()
        logger.info("Auto repair completed successfully.")
    except Exception as e:
        logger.error(f"Auto repair error: {e}")

@app.on_event("startup")
def startup_event():
    # Chạy làm sạch dữ liệu trong background thread để không chặn port binding của Render
    threading.Thread(target=auto_repair_contacted_dates, daemon=True).start()

@app.get("/api/metrics/summary", response_model=LeadMetricsSummary)
def get_summary(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    page_id: Optional[str] = None,
    employee: Optional[str] = None,
    db: Session = Depends(get_db)
):
    if not start_date:
        start_date = datetime.utcnow() - timedelta(days=30)
    if not end_date:
        end_date = datetime.utcnow()

    # Chuẩn hóa: strip timezone + set end_date cuối ngày
    start_date = _strip_tz(start_date).replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = _strip_tz(end_date).replace(hour=23, minute=59, second=59, microsecond=0)

    query = db.query(
        DimLead.id,
        DimLead.phone_number,
        DimLead.first_created_at,
        FactLeadActivity.status_tag,
        FactLeadActivity.assigned_users,
        FactLeadActivity.contacted_dates
    ).outerjoin(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)

    if page_id:
        query = query.filter(DimLead.page_id == page_id)
    if employee:
        query = query.filter(FactLeadActivity.assigned_users.ilike(f"%{employee}%"))

    results = query.all()
    
    new_leads_set = set()
    phone_leads_set = set()
    new_phone_leads_set = set()
    recontact_phone_leads_set = set()
    contacted_leads_set = set()
    uncontacted_new_leads_set = set()
    
    new_leads_employee_stats_sets = {}
    phone_leads_employee_stats_sets = {}
    tag_stats_sets = {"HV Khác": set(), "HV TCKT": set()}
    
    for lead_id, phone_number, first_created_at, status_tag, assigned_users, contacted_dates in results:
        # Bỏ qua lead chưa được phân cho nhân viên nào
        if not assigned_users:
            continue

        created_at = _strip_tz(first_created_at)

        is_new = False
        if created_at and start_date <= created_at <= end_date:
            is_new = True
            new_leads_set.add(lead_id)
                
        is_contacted = False
        if contacted_dates:
            for d_str in contacted_dates.split(','):
                d_date = _date_to_dt(d_str)
                if start_date <= d_date <= end_date:
                    is_contacted = True
                    contacted_leads_set.add(lead_id)
                    break
            
        has_phone = False
        if phone_number:
            has_phone = True
        elif status_tag and "đã add" in status_tag.lower():
            has_phone = True
            
        if (is_new or is_contacted) and has_phone:
            phone_leads_set.add(lead_id)
            if is_new:
                new_phone_leads_set.add(lead_id)
            else:
                recontact_phone_leads_set.add(lead_id)

        if is_new and not is_contacted:
            uncontacted_new_leads_set.add(lead_id)

        if is_new or is_contacted:
            # Thống kê nhân viên
            emps = [e.strip() for e in assigned_users.split(',') if e.strip()]
            
            if not employee:
                # Tránh lặp số lượng trên Pie Chart: Chỉ gán Lead cho nhân viên ĐẦU TIÊN (nhân viên chính)
                emps = emps[:1] if emps else []
            else:
                # Nếu đang lọc nhân viên, chỉ lấy nhân viên đó
                emps = [e for e in emps if employee.lower() in e.lower()]
                
            for emp in emps:
                if is_new:
                    if emp not in new_leads_employee_stats_sets:
                        new_leads_employee_stats_sets[emp] = set()
                    new_leads_employee_stats_sets[emp].add(lead_id)
                    
                if has_phone:
                    if emp not in phone_leads_employee_stats_sets:
                        phone_leads_employee_stats_sets[emp] = set()
                    phone_leads_employee_stats_sets[emp].add(lead_id)
                    
            # Thống kê tag
            if status_tag:
                tags = [t.strip().lower() for t in status_tag.split(',')]
                for t in tags:
                    if "hv khác" in t or "hv khac" in t:
                        tag_stats_sets["HV Khác"].add(lead_id)
                    elif "hv tckt" in t:
                        tag_stats_sets["HV TCKT"].add(lead_id)

    new_leads_employee_stats = {k: len(v) for k, v in new_leads_employee_stats_sets.items()}
    phone_leads_employee_stats = {k: len(v) for k, v in phone_leads_employee_stats_sets.items()}
    tag_stats = {k: len(v) for k, v in tag_stats_sets.items() if len(v) > 0}

    return LeadMetricsSummary(
        new_leads=len(new_leads_set),
        contacted_leads=len(contacted_leads_set),
        phone_leads=len(phone_leads_set),
        new_phone_leads=len(new_phone_leads_set),
        recontact_phone_leads=len(recontact_phone_leads_set),
        uncontacted_new_leads=len(uncontacted_new_leads_set),
        new_leads_employee_stats=new_leads_employee_stats,
        phone_leads_employee_stats=phone_leads_employee_stats,
        tag_stats=tag_stats
    )

@app.get("/api/metrics/trend", response_model=TrendResponse)
def get_trend(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    page_id: Optional[str] = None,
    employee: Optional[str] = None,
    db: Session = Depends(get_db)
):
    # Chuẩn hóa: strip timezone + set end_date cuối ngày
    start_date = _strip_tz(start_date).replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = _strip_tz(end_date).replace(hour=23, minute=59, second=59, microsecond=0)

    query = db.query(
        DimLead.id,
        DimLead.phone_number,
        DimLead.first_created_at,
        FactLeadActivity.status_tag,
        FactLeadActivity.assigned_users,
        FactLeadActivity.contacted_dates
    ).outerjoin(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)

    if page_id:
        query = query.filter(DimLead.page_id == page_id)
    if employee:
        query = query.filter(FactLeadActivity.assigned_users.ilike(f"%{employee}%"))

    results = query.all()
    trend_dict = {}

    for lead_id, phone_number, first_created_at, status_tag, assigned_users, contacted_dates in results:
        # Bỏ qua lead chưa được phân cho nhân viên nào
        if not assigned_users:
            continue

        has_phone = False
        if phone_number:
            has_phone = True
        elif status_tag and "đã add" in status_tag.lower():
            has_phone = True

        created_at = _strip_tz(first_created_at)
        if created_at and start_date <= created_at <= end_date:
            dt_str = created_at.strftime("%Y-%m-%d")
            if dt_str not in trend_dict:
                trend_dict[dt_str] = {"date": dt_str, "new_leads": set(), "phone_leads": set(), "contacted_leads": set()}
            trend_dict[dt_str]["new_leads"].add(lead_id)
            if has_phone:
                trend_dict[dt_str]["phone_leads"].add(lead_id)

        if contacted_dates:
            for d_str in contacted_dates.split(','):
                d_date = _date_to_dt(d_str)
                if start_date <= d_date <= end_date:
                    if d_str not in trend_dict:
                        trend_dict[d_str] = {"date": d_str, "new_leads": set(), "phone_leads": set(), "contacted_leads": set()}
                    trend_dict[d_str]["contacted_leads"].add(lead_id)
                    if has_phone:
                        trend_dict[d_str]["phone_leads"].add(lead_id)

    # Convert sets to length
    final_trend = []
    for dt_str, data in trend_dict.items():
        final_trend.append({
            "date": dt_str,
            "new_leads": len(data["new_leads"]),
            "phone_leads": len(data["phone_leads"]),
            "contacted_leads": len(data["contacted_leads"]),
        })

    sorted_trend = sorted(final_trend, key=lambda x: x["date"])
    return TrendResponse(data=[TrendDataPoint(**item) for item in sorted_trend])

@app.get("/api/employees/list")
def get_employees(db: Session = Depends(get_db)):
    results = db.query(FactLeadActivity.assigned_users).distinct().all()
    employees = set()
    for (users_str,) in results:
        if users_str:
            for u in users_str.split(","):
                u = u.strip()
                if u:
                    employees.add(u)
    return {"data": sorted(list(employees))}

@app.get("/api/pages/list")
def get_pages(db: Session = Depends(get_db)):
    results = db.query(DimLead.page_id).distinct().all()
    pages = set()
    for (page,) in results:
        if page:
            pages.add(page.strip())
    return {"data": sorted(list(pages))}

@app.get("/api/leads/list", response_model=LeadListResponse)
def list_leads(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    page_id: Optional[str] = None,
    employee: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db)
):
    # Chuẩn hóa dates - luôn có filter ngày, mặc định 30 ngày gần nhất
    if not start_date:
        start_date = datetime.utcnow() - timedelta(days=30)
    if not end_date:
        end_date = datetime.utcnow()

    start_date = _strip_tz(start_date).replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = _strip_tz(end_date).replace(hour=23, minute=59, second=59, microsecond=0)

    query = db.query(
        DimLead.id,
        DimLead.customer_id,
        DimLead.name,
        DimLead.phone_number,
        DimLead.page_id,
        DimLead.first_created_at,
        FactLeadActivity.status_tag,
        FactLeadActivity.assigned_users,
        FactLeadActivity.contacted_dates,
        FactLeadActivity.conversation_id
    ).outerjoin(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)

    if page_id:
        query = query.filter(DimLead.page_id == page_id)
    if employee:
        query = query.filter(FactLeadActivity.assigned_users.ilike(f"%{employee}%"))
        
    query = query.order_by(desc(DimLead.first_created_at))
    results = query.all()

    # Nhóm theo Customer (lọc trước khi lấy JSON raw)
    grouped = {}
    for lid, customer_id, name, phone_number, pg_id, first_created_at, status_tag, assigned_users, contacted_dates, conversation_id in results:
        # Bỏ qua lead chưa được phân cho nhân viên nào
        if not assigned_users:
            continue

        created_at = _strip_tz(first_created_at)
        is_new_in_period = bool(created_at and start_date <= created_at <= end_date)

        is_contacted_in_period = False
        if contacted_dates:
            for d_str in contacted_dates.split(','):
                d_date = _date_to_dt(d_str)
                if start_date <= d_date <= end_date:
                    is_contacted_in_period = True
                    break
                        
        if not is_new_in_period and not is_contacted_in_period:
            continue

        if lid not in grouped:
            grouped[lid] = {
                "id": lid,
                "customer_id": customer_id,
                "name": name,
                "phone_number": phone_number,
                "page_id": pg_id,
                "first_created_at": first_created_at,
                "assigned_users": set(),
                "conversation_ids": [],
                "is_contacted": is_contacted_in_period,
                "is_new": is_new_in_period,
                "tags": set()
            }
        
        if assigned_users:
            grouped[lid]["assigned_users"].update([u.strip() for u in assigned_users.split(",") if u.strip()])
        if status_tag:
            grouped[lid]["tags"].update([t.strip() for t in status_tag.split(",") if t.strip()])
        if conversation_id:
            grouped[lid]["conversation_ids"].append(conversation_id)

    final_list = list(grouped.values())
    total = len(final_list)
    
    paginated = final_list[(page - 1) * size : page * size]
    
    # Chỉ query JSON Raw cho page hiện tại
    conv_ids = []
    for item in paginated:
        conv_ids.extend(item["conversation_ids"])
        
    raw_results = []
    if conv_ids:
        raw_results = db.query(RawConversation).filter(RawConversation.pancake_id.in_(conv_ids)).all()
        
    raw_dict = {r.pancake_id: r for r in raw_results}
    
    data = []
    for item in paginated:
        messages = []
        for cid in item["conversation_ids"]:
            raw = raw_dict.get(cid)
            if raw and raw.payload:
                msgs = raw.payload.get("messages", [])
                for m in msgs:
                    if m.get("message"):
                        sender = m.get("sender_name", m.get("role", "Unknown"))
                        raw_msg = m.get('message', '')
                        import re
                        clean_msg = re.sub(r'<[^>]+>', '', raw_msg)
                        messages.append(f"[{sender}]: {clean_msg}")
                        
        data.append(LeadResponse(
            id=item["id"],
            customer_id=item["customer_id"],
            name=item["name"],
            phone_number=item["phone_number"],
            page_id=item["page_id"],
            first_created_at=item["first_created_at"],
            status_tag=", ".join(item["tags"]) if item.get("tags") else None,
            assigned_users=", ".join(item["assigned_users"]) if item["assigned_users"] else None,
            messages="\n".join(messages) if messages else None,
            is_contacted=item["is_contacted"],
            is_new=item["is_new"]
        ))
        
    return LeadListResponse(total=total, page=page, size=size, data=data)
