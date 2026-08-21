from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, desc, cast, Date, String
from datetime import datetime, timedelta
from typing import Optional
from database.db import get_db, engine, Base
from database.models import DimLead, FactLeadActivity, RawConversation
from backend.schemas import LeadMetricsSummary, TrendResponse, TrendDataPoint, LeadListResponse, LeadResponse
import dateutil.parser

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

    query = db.query(DimLead, FactLeadActivity)\
        .outerjoin(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)

    if page_id:
        query = query.filter(DimLead.page_id == page_id)
    if employee:
        query = query.filter(FactLeadActivity.assigned_users.ilike(f"%{employee}%"))

    results = query.all()
    
    new_leads_set = set()
    phone_leads_set = set()
    contacted_leads_set = set()
    
    new_leads_employee_stats_sets = {}
    phone_leads_employee_stats_sets = {}
    tag_stats_sets = {"HV Khác": set(), "HV TCKT": set()}
    
    for lead, act in results:
        # Bỏ qua lead chưa được phân cho nhân viên nào
        if not act or not act.assigned_users:
            continue

        created_at = _strip_tz(lead.first_created_at)

        is_new = False
        if created_at and start_date <= created_at <= end_date:
            is_new = True
            new_leads_set.add(lead.id)
                
        is_contacted = False
        if act.contacted_dates:
            for d_str in act.contacted_dates.split(','):
                d_date = _date_to_dt(d_str)
                if start_date <= d_date <= end_date:
                    is_contacted = True
                    contacted_leads_set.add(lead.id)
                    break
            
        has_phone = False
        if lead.phone_number:
            has_phone = True
        elif act.status_tag and "đã add" in act.status_tag.lower():
            has_phone = True
            
        if (is_new or is_contacted) and has_phone:
            phone_leads_set.add(lead.id)

        if is_new or is_contacted:
            # Thống kê nhân viên
            emps = [e.strip() for e in act.assigned_users.split(',') if e.strip()]
            
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
                    new_leads_employee_stats_sets[emp].add(lead.id)
                    
                if has_phone:
                    if emp not in phone_leads_employee_stats_sets:
                        phone_leads_employee_stats_sets[emp] = set()
                    phone_leads_employee_stats_sets[emp].add(lead.id)
                    
            # Thống kê tag
            if act.status_tag:
                tags = [t.strip().lower() for t in act.status_tag.split(',')]
                for t in tags:
                    if "hv khác" in t or "hv khac" in t:
                        tag_stats_sets["HV Khác"].add(lead.id)
                    elif "hv tckt" in t:
                        tag_stats_sets["HV TCKT"].add(lead.id)

    new_leads_employee_stats = {k: len(v) for k, v in new_leads_employee_stats_sets.items()}
    phone_leads_employee_stats = {k: len(v) for k, v in phone_leads_employee_stats_sets.items()}
    tag_stats = {k: len(v) for k, v in tag_stats_sets.items() if len(v) > 0}

    return LeadMetricsSummary(
        new_leads=len(new_leads_set),
        contacted_leads=len(contacted_leads_set),
        phone_leads=len(phone_leads_set),
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

    query = db.query(DimLead, FactLeadActivity)\
        .outerjoin(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)

    if page_id:
        query = query.filter(DimLead.page_id == page_id)
    if employee:
        query = query.filter(FactLeadActivity.assigned_users.ilike(f"%{employee}%"))

    results = query.all()
    trend_dict = {}

    for lead, act in results:
        # Bỏ qua lead chưa được phân cho nhân viên nào
        if not act or not act.assigned_users:
            continue

        has_phone = False
        if lead.phone_number:
            has_phone = True
        elif act.status_tag and "đã add" in act.status_tag.lower():
            has_phone = True

        created_at = _strip_tz(lead.first_created_at)
        if created_at and start_date <= created_at <= end_date:
            dt_str = created_at.strftime("%Y-%m-%d")
            if dt_str not in trend_dict:
                trend_dict[dt_str] = {"date": dt_str, "new_leads": set(), "phone_leads": set(), "contacted_leads": set()}
            trend_dict[dt_str]["new_leads"].add(lead.id)
            if has_phone:
                trend_dict[dt_str]["phone_leads"].add(lead.id)

        if act.contacted_dates:
            for d_str in act.contacted_dates.split(','):
                d_date = _date_to_dt(d_str)
                if start_date <= d_date <= end_date:
                    if d_str not in trend_dict:
                        trend_dict[d_str] = {"date": d_str, "new_leads": set(), "phone_leads": set(), "contacted_leads": set()}
                    trend_dict[d_str]["contacted_leads"].add(lead.id)
                    if has_phone:
                        trend_dict[d_str]["phone_leads"].add(lead.id)

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

    query = db.query(DimLead, FactLeadActivity)\
        .outerjoin(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)

    if page_id:
        query = query.filter(DimLead.page_id == page_id)
    if employee:
        query = query.filter(FactLeadActivity.assigned_users.ilike(f"%{employee}%"))
        
    query = query.order_by(desc(DimLead.first_created_at))
    results = query.all()

    # Nhóm theo Customer (lọc trước khi lấy JSON raw)
    grouped = {}
    for lead, act in results:
        # Bỏ qua lead chưa được phân cho nhân viên nào
        if not act or not act.assigned_users:
            continue

        created_at = _strip_tz(lead.first_created_at)
        is_new_in_period = created_at and start_date <= created_at <= end_date

        is_contacted_in_period = False
        if act.contacted_dates:
            for d_str in act.contacted_dates.split(','):
                d_date = _date_to_dt(d_str)
                if start_date <= d_date <= end_date:
                    is_contacted_in_period = True
                    break
                        
        if not is_new_in_period and not is_contacted_in_period:
            continue

        lid = lead.id
        if lid not in grouped:
            grouped[lid] = {
                "lead": lead,
                "assigned_users": set(),
                "conversation_ids": [],
                "is_contacted": is_contacted_in_period,
                "is_new": is_new_in_period,
                "tags": set()
            }
        
        if act:
            if act.assigned_users:
                grouped[lid]["assigned_users"].update([u.strip() for u in act.assigned_users.split(",") if u.strip()])
            if act.status_tag:
                grouped[lid]["tags"].update([t.strip() for t in act.status_tag.split(",") if t.strip()])
            if act.conversation_id:
                grouped[lid]["conversation_ids"].append(act.conversation_id)

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
        lead = item["lead"]
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
            id=lead.id,
            customer_id=lead.customer_id,
            name=lead.name,
            phone_number=lead.phone_number,
            page_id=lead.page_id,
            first_created_at=lead.first_created_at,
            status_tag=status_tag,
            assigned_users=", ".join(item["assigned_users"]) if item["assigned_users"] else None,
            messages=msg_str,
            is_contacted=item["is_contacted"],
            is_new=item["is_new"]
        ))
        
    return LeadListResponse(total=total, page=page, size=size, data=data)
