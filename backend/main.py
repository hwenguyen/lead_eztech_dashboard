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

    query = db.query(DimLead, FactLeadActivity)\
        .outerjoin(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)

    if page_id:
        query = query.filter(DimLead.page_id == page_id)
    if employee:
        query = query.filter(FactLeadActivity.assigned_users.ilike(f"%{employee}%"))

    results = query.all()
    
    new_leads = 0
    phone_leads = 0
    contacted_leads = 0
    
    for lead, act in results:
        is_new = False
        if start_date <= lead.first_created_at <= end_date:
            is_new = True
            new_leads += 1
                
        is_contacted = False
        if act and act.contacted_dates:
            for d_str in act.contacted_dates.split(','):
                d_date = datetime.strptime(d_str.strip(), "%Y-%m-%d")
                if start_date <= d_date <= end_date:
                    is_contacted = True
                    break
        if is_contacted:
            contacted_leads += 1
            
        has_phone = False
        if lead.phone_number:
            has_phone = True
        elif act and act.status_tag and "Đã add" in act.status_tag:
            has_phone = True
            
        if (is_new or is_contacted) and has_phone:
            phone_leads += 1

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

    query = db.query(DimLead, FactLeadActivity)\
        .outerjoin(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)

    if page_id:
        query = query.filter(DimLead.page_id == page_id)
    if employee:
        query = query.filter(FactLeadActivity.assigned_users.ilike(f"%{employee}%"))

    results = query.all()
    trend_dict = {}

    for lead, act in results:
        has_phone = False
        if lead.phone_number:
            has_phone = True
        elif act and act.status_tag and "Đã add" in act.status_tag:
            has_phone = True

        if start_date <= lead.first_created_at <= end_date:
            dt_str = lead.first_created_at.strftime("%Y-%m-%d")
            if dt_str not in trend_dict:
                trend_dict[dt_str] = {"date": dt_str, "new_leads": 0, "phone_leads": 0, "contacted_leads": 0}
            trend_dict[dt_str]["new_leads"] += 1
            if has_phone:
                trend_dict[dt_str]["phone_leads"] += 1

        if act and act.contacted_dates:
            for d_str in act.contacted_dates.split(','):
                d_date = datetime.strptime(d_str.strip(), "%Y-%m-%d")
                if start_date <= d_date <= end_date:
                    if d_str not in trend_dict:
                        trend_dict[d_str] = {"date": d_str, "new_leads": 0, "phone_leads": 0, "contacted_leads": 0}
                    trend_dict[d_str]["contacted_leads"] += 1
                    if has_phone:
                        trend_dict[d_str]["phone_leads"] += 1

    sorted_trend = sorted(trend_dict.values(), key=lambda x: x["date"])
    return TrendResponse(data=[TrendDataPoint(**item) for item in sorted_trend])

@app.get("/api/employees/list")
def get_employees(db: Session = Depends(get_db)):
    results = db.query(FactLeadActivity.assigned_users).distinct().all()
    employees = set()
    for (users_str,) in results:
        if users_str:
            employees.update([u.strip() for u in users_str.split(",") if u.strip()])
    return {"data": sorted(list(employees))}

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
        is_new_in_period = True
        is_contacted_in_period = False
        
        if start_date and end_date:
            is_new_in_period = start_date <= lead.first_created_at <= end_date
            if act and act.contacted_dates:
                for d_str in act.contacted_dates.split(','):
                    d_date = datetime.strptime(d_str.strip(), "%Y-%m-%d")
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
            status_tag=", ".join(item["tags"]) if item.get("tags") else None,
            assigned_users=", ".join(item["assigned_users"]),
            messages="\n".join(messages) if messages else None,
            is_contacted=item["is_contacted"]
        ))
        
    return LeadListResponse(total=total, page=page, size=size, data=data)
