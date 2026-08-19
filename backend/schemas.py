from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class LeadMetricsSummary(BaseModel):
    new_leads: int
    contacted_leads: int
    phone_leads: int
    employee_stats: dict
    tag_stats: dict

class LeadResponse(BaseModel):
    id: int
    customer_id: str
    name: Optional[str] = None
    phone_number: Optional[str] = None
    page_id: str
    first_created_at: datetime
    status_tag: Optional[str] = None
    assigned_users: Optional[str] = None
    messages: Optional[str] = None
    is_contacted: bool

    class Config:
        from_attributes = True

class TrendDataPoint(BaseModel):
    date: str
    new_leads: int
    contacted_leads: int
    phone_leads: int

class TrendResponse(BaseModel):
    data: List[TrendDataPoint]

class LeadListResponse(BaseModel):
    total: int
    page: int
    size: int
    data: List[LeadResponse]
