from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, desc, cast, Date, String
from datetime import datetime, timedelta
from typing import Optional
from database.db import get_db, engine, Base
from database.models import DimLead, FactLeadActivity
from backend.schemas import LeadMetricsSummary, TrendResponse, TrendDataPoint, LeadListResponse, LeadResponse

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

@app.get("/api/metrics/summary", response_model=LeadMetricsSummary)
def get_summary(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    page_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    if not start_date:
        start_date = datetime.utcnow() - timedelta(days=30)
    if not end_date:
        end_date = datetime.utcnow()
    else:
        end_date = end_date.replace(hour=23, minute=59, second=59)

    query_leads = db.query(DimLead).filter(
        DimLead.first_created_at >= start_date,
        DimLead.first_created_at <= end_date
    )
    if page_id:
        query_leads = query_leads.filter(DimLead.page_id == page_id)
        
    new_leads = query_leads.count()
    phone_leads = query_leads.filter(DimLead.phone_number != None).count()

    query_contacted = db.query(FactLeadActivity).join(DimLead).filter(
        FactLeadActivity.updated_at >= start_date,
        FactLeadActivity.updated_at <= end_date,
        FactLeadActivity.is_contacted == True
    )
    if page_id:
        query_contacted = query_contacted.filter(DimLead.page_id == page_id)
        
    contacted_leads = query_contacted.count()

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
    db: Session = Depends(get_db)
):
    if not start_date:
        start_date = datetime.utcnow() - timedelta(days=7)
    if not end_date:
        end_date = datetime.utcnow()
    else:
        end_date = end_date.replace(hour=23, minute=59, second=59)

    # Cast datetime to Date (works on Postgres & SQLite), then cast to string for API response
    date_func = cast(cast(DimLead.first_created_at, Date), String)
    
    # Query Leads (New & Phone)
    q_leads = db.query(
        date_func.label("date"),
        func.count(DimLead.id).label("new_leads"),
        func.count(func.nullif(DimLead.phone_number == None, True)).label("phone_leads")
    ).filter(
        DimLead.first_created_at >= start_date,
        DimLead.first_created_at <= end_date
    )
    if page_id:
        q_leads = q_leads.filter(DimLead.page_id == page_id)
        
    leads_grouped = q_leads.group_by(date_func).all()
    
    # Query Contacted
    act_date_func = cast(cast(FactLeadActivity.updated_at, Date), String)
    q_contacted = db.query(
        act_date_func.label("date"),
        func.count(FactLeadActivity.id).label("contacted_leads")
    ).join(DimLead).filter(
        FactLeadActivity.updated_at >= start_date,
        FactLeadActivity.updated_at <= end_date,
        FactLeadActivity.is_contacted == True
    )
    if page_id:
        q_contacted = q_contacted.filter(DimLead.page_id == page_id)
        
    contacted_grouped = q_contacted.group_by(act_date_func).all()

    # Merge results
    trend_dict = {}
    for r in leads_grouped:
        if r.date:
            trend_dict[r.date] = {"date": r.date, "new_leads": r.new_leads, "phone_leads": r.phone_leads or 0, "contacted_leads": 0}
            
    for r in contacted_grouped:
        if r.date:
            if r.date not in trend_dict:
                trend_dict[r.date] = {"date": r.date, "new_leads": 0, "phone_leads": 0, "contacted_leads": 0}
            trend_dict[r.date]["contacted_leads"] = r.contacted_leads

    # Sort by date
    sorted_trend = sorted(trend_dict.values(), key=lambda x: x["date"])
    
    return TrendResponse(data=[TrendDataPoint(**item) for item in sorted_trend])

@app.get("/api/leads/list", response_model=LeadListResponse)
def list_leads(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    page_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(DimLead, FactLeadActivity).outerjoin(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)
    if page_id:
        query = query.filter(DimLead.page_id == page_id)
        
    query = query.order_by(desc(DimLead.first_created_at))
    
    total = query.count()
    results = query.offset((page - 1) * size).limit(size).all()
    
    data = []
    for lead, activity in results:
        data.append(LeadResponse(
            id=lead.id,
            customer_id=lead.customer_id,
            name=lead.name,
            phone_number=lead.phone_number,
            page_id=lead.page_id,
            first_created_at=lead.first_created_at,
            status_tag=activity.status_tag if activity else None,
            is_contacted=activity.is_contacted if activity else False
        ))
        
    return LeadListResponse(total=total, page=page, size=size, data=data)
