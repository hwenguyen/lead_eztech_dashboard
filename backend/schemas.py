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
    phone_tag_stats: Optional[dict] = None

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

class DealWinItem(BaseModel):
    id: int
    sheet_row_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    email: Optional[str] = None
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    birth_year: Optional[str] = None
    address: Optional[str] = None
    industry: Optional[str] = None
    job_title: Optional[str] = None
    expectation: Optional[str] = None
    care_by: Optional[str] = None
    is_student: Optional[bool] = False
    lead_tag: Optional[str] = None
    dim_lead_id: Optional[int] = None
    raw_data: Optional[dict] = None
    created_at: Optional[datetime] = None

    # Tương thích ngược với UI
    @property
    def customer_name(self) -> Optional[str]:
        return self.full_name

    @property
    def sales_person(self) -> Optional[str]:
        return self.care_by

    @property
    def submitted_at(self) -> Optional[datetime]:
        return self.timestamp

    class Config:
        from_attributes = True


class DealWinSummary(BaseModel):
    total_deals: int = 0
    top_sales_person: Optional[str] = None
    sales_person_stats: dict = {}
    daily_trend: List[dict] = []

class DealWinOptions(BaseModel):
    sales_persons: List[str] = []

class DealWinListResponse(BaseModel):
    total: int
    page: int
    size: int
    total_pages: int
    data: List[DealWinItem]
    summary: Optional[DealWinSummary] = None
    sales_persons: Optional[List[str]] = None

