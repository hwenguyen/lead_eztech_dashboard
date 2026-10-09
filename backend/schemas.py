from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class LeadMetricsSummary(BaseModel):
    new_leads: int
    recontact_leads: int
    total_leads: int
    phone_leads: int
    new_phone_leads: int = 0
    recontact_phone_leads: int = 0
    new_leads_employee_stats: dict
    phone_leads_employee_stats: dict
    tag_stats: dict

class LeadResponse(BaseModel):
    id: int
    customer_id: str
    name: Optional[str] = None
    phone_number: Optional[str] = None
    page_id: str
    first_created_at: Optional[datetime] = None
    status_tag: Optional[str] = None
    tag_timeline: Optional[List[dict]] = None
    assigned_users: Optional[str] = None
    messages: Optional[str] = None
    is_contacted: bool
    is_new: bool
    pancake_url: Optional[str] = None

    class Config:
        from_attributes = True

class TrendDataPoint(BaseModel):
    date: str
    new_leads: int
    recontact_leads: int
    phone_leads: int

class TrendResponse(BaseModel):
    data: List[TrendDataPoint]

class LeadListResponse(BaseModel):
    total: int
    page: int
    size: int
    data: List[LeadResponse]

class RemindSummary(BaseModel):
    total: int
    under_1_day: int
    days_1_to_3: int
    days_3_to_7: int
    over_7_days: int

class RemindLeadItem(BaseModel):
    lead_id: int
    customer_id: str
    name: Optional[str] = None
    phone_number: Optional[str] = None
    page_id: str
    assigned_users: Optional[str] = None
    status_tag: Optional[str] = None
    remind_tag: str = "Remind"
    remind_tagged_at: Optional[str] = None
    contacted_at: Optional[datetime] = None
    days_since_last_contact: float
    days_int: int
    conversation_id: Optional[str] = None
    pancake_url: Optional[str] = None

class RemindLeadResponse(BaseModel):
    total: int
    page: int
    size: int
    total_pages: int
    summary: RemindSummary
    employees: List[str]
    tags: List[str] = []
    items: List[RemindLeadItem]
