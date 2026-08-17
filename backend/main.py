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

def parse_msg_date(date_str):
    if not date_str: return None
    try:
        return dateutil.parser.isoparse(str(date_str)).replace(tzinfo=None)
    except:
        return None

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
    else:
        end_date = end_date.replace(hour=23, minute=59, second=59)

    query = db.query(DimLead, FactLeadActivity, RawConversation)\
        .outerjoin(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)\
        .outerjoin(RawConversation, FactLeadActivity.conversation_id == RawConversation.pancake_id)

    if page_id:
        query = query.filter(DimLead.page_id == page_id)
    if employee:
        query = query.filter(FactLeadActivity.assigned_users.ilike(f"%{employee}%"))

    results = query.all()
    
    new_leads = 0
    phone_leads = 0
    contacted_leads = 0
    
    for lead, act, raw in results:
        if start_date <= lead.first_created_at <= end_date:
            new_leads += 1
            if lead.phone_number:
                phone_leads += 1
                
        is_contacted = False
        if raw and raw.payload:
            for m in raw.payload.get("messages", []):
                if m.get("role") == "Admin":
                    m_date = parse_msg_date(m.get("inserted_at"))
                    if m_date and start_date <= m_date <= end_date:
                        is_contacted = True
                        break
        if is_contacted:
            contacted_leads += 1

    return LeadMetricsSummary(
        new_leads=new_leads,
        contacted_leads=contacted_leads,
        phone_leads=phone_leads
    )

@app.get("/api/metrics/trend", response_model=TrendResponse)
def get_trend(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    page_id: Optional[str] = None,
    employee: Optional[str] = None,
    db: Session = Depends(get_db)
):
    if not start_date:
        start_date = datetime.utcnow() - timedelta(days=7)
    if not end_date:
        end_date = datetime.utcnow()
    else:
        end_date = end_date.replace(hour=23, minute=59, second=59)

    query = db.query(DimLead, FactLeadActivity, RawConversation)\
        .outerjoin(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)\
        .outerjoin(RawConversation, FactLeadActivity.conversation_id == RawConversation.pancake_id)

    if page_id:
        query = query.filter(DimLead.page_id == page_id)
    if employee:
        query = query.filter(FactLeadActivity.assigned_users.ilike(f"%{employee}%"))

    results = query.all()
    trend_dict = {}

    for lead, act, raw in results:
        if start_date <= lead.first_created_at <= end_date:
            dt_str = lead.first_created_at.strftime("%Y-%m-%d")
            if dt_str not in trend_dict:
                trend_dict[dt_str] = {"date": dt_str, "new_leads": 0, "phone_leads": 0, "contacted_leads": 0}
            trend_dict[dt_str]["new_leads"] += 1
            if lead.phone_number:
                trend_dict[dt_str]["phone_leads"] += 1

        if raw and raw.payload:
            contacted_dates = set()
            for m in raw.payload.get("messages", []):
                if m.get("role") == "Admin":
                    m_date = parse_msg_date(m.get("inserted_at"))
                    if m_date and start_date <= m_date <= end_date:
                        dt_str = m_date.strftime("%Y-%m-%d")
                        contacted_dates.add(dt_str)
            for dt_str in contacted_dates:
                if dt_str not in trend_dict:
                    trend_dict[dt_str] = {"date": dt_str, "new_leads": 0, "phone_leads": 0, "contacted_leads": 0}
                trend_dict[dt_str]["contacted_leads"] += 1

    sorted_trend = sorted(trend_dict.values(), key=lambda x: x["date"])
    return TrendResponse(data=[TrendDataPoint(**item) for item in sorted_trend])

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
    if end_date:
        end_date = end_date.replace(hour=23, minute=59, second=59)

    query = db.query(DimLead, FactLeadActivity, RawConversation)\
        .outerjoin(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)\
        .outerjoin(RawConversation, FactLeadActivity.conversation_id == RawConversation.pancake_id)

    if page_id:
        query = query.filter(DimLead.page_id == page_id)
    if employee:
        query = query.filter(FactLeadActivity.assigned_users.ilike(f"%{employee}%"))
        
    query = query.order_by(desc(DimLead.first_created_at))
    results = query.all()

    # Nhóm theo Customer
    grouped = {}
    for lead, act, raw in results:
        is_new_in_period = True
        is_contacted_in_period = False
        
        if start_date and end_date:
            is_new_in_period = start_date <= lead.first_created_at <= end_date
            
            if raw and raw.payload:
                for m in raw.payload.get("messages", []):
                    if m.get("role") == "Admin":
                        m_date = parse_msg_date(m.get("inserted_at"))
                        if m_date and start_date <= m_date <= end_date:
                            is_contacted_in_period = True
                            break
                            
            if not is_new_in_period and not is_contacted_in_period:
                continue

        lid = lead.id
        if lid not in grouped:
            grouped[lid] = {
                "lead": lead,
                "assigned_users": set(),
                "messages": [],
                "is_contacted": is_contacted_in_period
            }
        
        if act and act.assigned_users:
            grouped[lid]["assigned_users"].update([u.strip() for u in act.assigned_users.split(",") if u.strip()])
            
        if raw and raw.payload:
            msgs = raw.payload.get("messages", [])
            for m in msgs:
                if m.get("message"):
                    sender = m.get("sender_name", m.get("role", "Unknown"))
                    grouped[lid]["messages"].append(f"[{sender}]: {m.get('message')}")

    final_list = list(grouped.values())
    total = len(final_list)
    
    paginated = final_list[(page - 1) * size : page * size]
    
    data = []
    for item in paginated:
        lead = item["lead"]
        data.append(LeadResponse(
            id=lead.id,
            customer_id=lead.customer_id,
            name=lead.name,
            phone_number=lead.phone_number,
            page_id=lead.page_id,
            first_created_at=lead.first_created_at,
            status_tag=None,
            assigned_users=", ".join(item["assigned_users"]),
            messages="\n".join(item["messages"]) if item["messages"] else None,
            is_contacted=item["is_contacted"]
        ))
        
    return LeadListResponse(total=total, page=page, size=size, data=data)
