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
    assigned_users: Optional[str] = None
    messages: Optional[str] = None
    is_contacted: bool
    is_new: bool

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
