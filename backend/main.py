from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional, Dict
import re
import threading
import logging
from database.db import get_db, engine, Base, SessionLocal
from database.models import DimLead, FactLeadActivity, RawConversation
from backend.schemas import LeadMetricsSummary, TrendResponse, TrendDataPoint, LeadListResponse, LeadResponse
from backend.lead_metrics import classify_leads, resolve_period, normalize_text
from etl.utils import parse_pancake_date, extract_customer_phone

logger = logging.getLogger(__name__)

# Khởi tạo DB Schema (Tự động tạo bảng nếu chưa có, hữu ích cho môi trường dev/Free Tier)
Base.metadata.create_all(bind=engine)

# create_all không thêm index cho bảng đã tồn tại → tạo thủ công các index phục vụ lọc theo kỳ
INDEX_DDL = [
    "CREATE INDEX IF NOT EXISTS ix_dim_leads_first_created_at ON dim_leads (first_created_at)",
    "CREATE INDEX IF NOT EXISTS ix_fact_lead_activities_lead_id ON fact_lead_activities (lead_id)",
    "CREATE INDEX IF NOT EXISTS ix_fact_lead_activities_contacted_at ON fact_lead_activities (contacted_at)",
]
try:
    with engine.begin() as conn:
        for ddl in INDEX_DDL:
            conn.execute(text(ddl))
except Exception as e:
    logger.error(f"Create index error: {e}")

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

def auto_repair_contacted_dates():
    """Đồng bộ lại contacted_dates, contacted_at, first_created_at, phone_number và chuẩn hoá page_id về tên Fanpage."""
    db = SessionLocal()
    try:
        all_leads = db.query(DimLead).all()
        # 1. Tìm tên Page chữ chuẩn trong database (ưu tiên tên đã có như 'Anh Kế toán làm Data')
        text_pages = [l.page_id.strip() for l in all_leads if l.page_id and not l.page_id.strip().isdigit()]
        canonical_page_name = text_pages[0] if text_pages else "Anh Kế toán làm Data"

        has_changes = False

        # 2. Chuẩn hoá DimLead: Đổi tất cả ID dạng số hoặc trống về tên Fanpage chuẩn
        for lead in all_leads:
            if not lead.page_id or lead.page_id.strip().isdigit():
                lead.page_id = canonical_page_name
                has_changes = True

        raws = db.query(RawConversation).order_by(RawConversation.id).all()
        if not raws:
            if has_changes:
                db.commit()
            return

        # Preload all activities and leads into memory in 2 fast queries
        all_acts = {act.conversation_id: act for act in db.query(FactLeadActivity).all()}
        lead_dict = {l.id: l for l in all_leads}
        lead_phones: Dict[int, Optional[str]] = {}

        for r in raws:
            # Chuẩn hoá RawConversation.page_id
            if not r.page_id or r.page_id.strip().isdigit():
                r.page_id = canonical_page_name
                has_changes = True

            if not r.payload or not isinstance(r.payload, dict):
                continue
            act = all_acts.get(r.pancake_id)
            if not act:
                continue

            msgs = r.payload.get('messages') or []
            msg_times = [dt for dt in (parse_pancake_date(m.get('inserted_at')) for m in msgs if isinstance(m, dict)) if dt]
            conv_updated = parse_pancake_date(r.payload.get('updated_at'))
            if conv_updated:
                msg_times.append(conv_updated)
            contacted_dates_str = ",".join(sorted({dt.strftime("%Y-%m-%d") for dt in msg_times})) or None
            if act.contacted_dates != contacted_dates_str:
                act.contacted_dates = contacted_dates_str
                has_changes = True
            # contacted_at (tin nhắn gần nhất) dùng để prefilter theo kỳ → phải khớp contacted_dates
            contacted_at = max(msg_times) if msg_times else None
            if contacted_at and act.contacted_at != contacted_at:
                act.contacted_at = contacted_at
                has_changes = True

            lead = lead_dict.get(act.lead_id)
            if not lead:
                continue

            conv_inserted = parse_pancake_date(r.payload.get('inserted_at'))
            if conv_inserted and (not lead.first_created_at or lead.first_created_at > conv_inserted):
                lead.first_created_at = conv_inserted
                has_changes = True

            # SĐT: ưu tiên phone_number trong payload, sau đó SĐT trong tin nhắn của khách (bỏ hotline của Admin)
            phone = r.payload.get('phone_number') or extract_customer_phone(msgs)
            if not lead_phones.get(lead.id):
                lead_phones[lead.id] = phone

        for lead_id, phone in lead_phones.items():
            lead = lead_dict[lead_id]
            if lead.phone_number != phone:
                lead.phone_number = phone
                has_changes = True

        if has_changes:
            db.commit()
        logger.info(f"Auto repair completed successfully. Standardized page_id to '{canonical_page_name}'.")
    except Exception as e:
        db.rollback()
        logger.error(f"Auto repair error: {e}")
    finally:
        db.close()

@app.on_event("startup")
def startup_event():
    # Chạy làm sạch dữ liệu trong background thread để không chặn port binding của Render
    threading.Thread(target=auto_repair_contacted_dates, daemon=True).start()

TAG_CATEGORIES = [
    ("Lead Other", ("lead other", "other")),
    ("Đào tạo", ("đào tạo", "dao tao", "daotao")),
]

def _categorize_tag(tag: str) -> Optional[str]:
    t = normalize_text(tag)
    for label, keywords in TAG_CATEGORIES:
        if any(k in t for k in keywords):
            return label
    return None

@app.get("/api/metrics/summary", response_model=LeadMetricsSummary)
def get_summary(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    page_id: Optional[str] = None,
    employee: Optional[str] = None,
    db: Session = Depends(get_db)
):
    start, end = resolve_period(start_date, end_date)
    leads = classify_leads(db, start, end, page_id, employee)

    new_leads = recontact_leads = new_phone_leads = recontact_phone_leads = 0
    new_leads_employee_stats: Counter = Counter()
    phone_leads_employee_stats: Counter = Counter()
    tag_stats: Counter = Counter()

    for lead in leads.values():
        # Pie Chart: mỗi lead chỉ gán cho 1 nhân viên chính để tổng không bị lặp
        emp = lead.primary_employee
        if lead.is_new:
            new_leads += 1
            new_leads_employee_stats[emp] += 1
            if lead.has_phone:
                new_phone_leads += 1
        else:
            recontact_leads += 1
            if lead.has_phone:
                recontact_phone_leads += 1
        if lead.has_phone:
            phone_leads_employee_stats[emp] += 1

        for label in {_categorize_tag(t) for t in lead.tags} - {None}:
            tag_stats[label] += 1

    return LeadMetricsSummary(
        new_leads=new_leads,
        recontact_leads=recontact_leads,
        total_leads=new_leads + recontact_leads,
        phone_leads=new_phone_leads + recontact_phone_leads,
        new_phone_leads=new_phone_leads,
        recontact_phone_leads=recontact_phone_leads,
        new_leads_employee_stats=dict(new_leads_employee_stats),
        phone_leads_employee_stats=dict(phone_leads_employee_stats),
        tag_stats=dict(tag_stats),
    )

@app.get("/api/metrics/trend", response_model=TrendResponse)
def get_trend(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    page_id: Optional[str] = None,
    employee: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Theo ngày. Mới/Contact Lại được phân loại theo CẢ KỲ để cộng dồn khớp KPI:
    lead tạo trong kỳ chỉ được tính ở ngày tạo, kể cả khi nhắn lại vào ngày sau."""
    start, end = resolve_period(start_date, end_date)
    leads = classify_leads(db, start, end, page_id, employee)

    trend: Dict[str, Dict[str, int]] = {}
    day = start
    while day <= end:
        trend[day.strftime("%Y-%m-%d")] = {"new_leads": 0, "recontact_leads": 0, "phone_leads": 0}
        day += timedelta(days=1)

    for lead in leads.values():
        if lead.is_new:
            key, days = "new_leads", [lead.first_created_at.strftime("%Y-%m-%d")]
        else:
            key, days = "recontact_leads", lead.contact_days
        for d in days:
            trend[d][key] += 1
            if lead.has_phone:
                trend[d]["phone_leads"] += 1

    return TrendResponse(data=[TrendDataPoint(date=d, **counts) for d, counts in trend.items()])

@app.get("/api/employees/list")
def get_employees(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    page_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    start, end = resolve_period(start_date, end_date)
    leads = classify_leads(db, start, end, page_id=page_id)
    employees = set()
    for lead in leads.values():
        employees.update(lead.employees)
    return {"data": sorted(list(employees))}

@app.get("/api/pages/list")
def get_pages(db: Session = Depends(get_db)):
    results = db.query(DimLead.page_id).distinct().all()
    pages = set()
    for (page,) in results:
        if page and not page.strip().isdigit():
            pages.add(page.strip())
    if not pages:
        pages.add("Anh Kế toán làm Data")
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
    start, end = resolve_period(start_date, end_date)
    leads = sorted(
        classify_leads(db, start, end, page_id, employee).values(),
        key=lambda l: l.first_created_at or datetime.min,
        reverse=True,
    )
    total = len(leads)
    paginated = leads[(page - 1) * size : page * size]

    # Chỉ query JSON Raw cho page hiện tại
    conv_ids = [cid for lead in paginated for cid in lead.conversation_ids]
    raw_results = []
    if conv_ids:
        raw_results = db.query(RawConversation).filter(RawConversation.pancake_id.in_(conv_ids)).all()
    raw_dict = {r.pancake_id: r for r in raw_results}

    data = []
    for lead in paginated:
        messages = []
        for cid in lead.conversation_ids:
            raw = raw_dict.get(cid)
            if raw and raw.payload:
                for m in raw.payload.get("messages", []):
                    if m.get("message"):
                        sender = m.get("sender_name", m.get("role", "Unknown"))
                        clean_msg = re.sub(r'<[^>]+>', '', m.get('message', ''))
                        messages.append(f"[{sender}]: {clean_msg}")

        data.append(LeadResponse(
            id=lead.id,
            customer_id=lead.customer_id,
            name=lead.name,
            phone_number=lead.phone_number,
            page_id=lead.page_id,
            first_created_at=lead.first_created_at,
            status_tag=", ".join(sorted(lead.tags)) if lead.tags else None,
            assigned_users=", ".join(sorted(lead.employees)) if lead.employees else None,
            messages="\n".join(messages) if messages else None,
            is_contacted=lead.is_contacted,
            is_new=lead.is_new
        ))

    return LeadListResponse(total=total, page=page, size=size, data=data)
