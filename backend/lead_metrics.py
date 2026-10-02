"""Logic phân loại Lead dùng chung cho summary / trend / list.

Định nghĩa theo kỳ [start, end] (giờ Việt Nam):
- Lead Mới: first_created_at nằm trong kỳ.
- Lead Contact Lại: tạo TRƯỚC kỳ và có tin nhắn (khách hoặc nhân viên) trong kỳ.
- Tổng Lead: Mới + Contact Lại (hai nhóm không trùng nhau).
- Có SĐT: lead có phone_number hoặc bất kỳ hội thoại nào gắn tag "Đã add" (không phụ thuộc thời điểm có SĐT).
Chỉ xét hội thoại đã được phân cho nhân viên. Mọi cờ được gộp theo LEAD (không theo từng hội thoại).
"""
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Set, Tuple

from sqlalchemy import select, or_, and_
from sqlalchemy.orm import Session

from database.models import DimLead, FactLeadActivity
from etl.utils import VN_TZ

PHONE_TAG = "đã add"


@dataclass
class LeadAgg:
    id: int
    customer_id: str
    name: Optional[str]
    phone_number: Optional[str]
    page_id: str
    first_created_at: Optional[datetime]
    is_new: bool
    has_phone: bool
    contact_days: Set[str] = field(default_factory=set)  # Các ngày "YYYY-MM-DD" có tin nhắn trong kỳ
    tags: Set[str] = field(default_factory=set)
    employees: Set[str] = field(default_factory=set)
    primary_employee: Optional[str] = None  # NV của hội thoại có tin nhắn gần nhất, dùng cho Pie Chart
    primary_contacted_at: Optional[datetime] = None
    conversation_ids: List[str] = field(default_factory=list)

    @property
    def is_contacted(self) -> bool:
        return bool(self.contact_days)

    @property
    def is_recontact(self) -> bool:
        return not self.is_new and self.is_contacted


def normalize_text(s: str) -> str:
    """Chuẩn hoá Unicode (NFC) + lower để so sánh tiếng Việt ổn định."""
    return unicodedata.normalize("NFC", s).strip().lower()


def split_csv(s: Optional[str]) -> List[str]:
    return [x.strip() for x in s.split(",") if x.strip()] if s else []


def _strip_tz(dt: Optional[datetime]) -> Optional[datetime]:
    """Đảm bảo datetime luôn là naive (không timezone) để so sánh nhất quán."""
    if dt is not None and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def resolve_period(start_date: Optional[datetime], end_date: Optional[datetime]) -> Tuple[datetime, datetime]:
    """Mặc định 30 ngày gần nhất theo giờ VN; start về 00:00:00, end về cuối ngày."""
    if not end_date:
        end_date = datetime.now(VN_TZ).replace(tzinfo=None)
    if not start_date:
        start_date = _strip_tz(end_date) - timedelta(days=30)
    start = _strip_tz(start_date).replace(hour=0, minute=0, second=0, microsecond=0)
    end = _strip_tz(end_date).replace(hour=23, minute=59, second=59, microsecond=999999)
    return start, end


def classify_leads(
    db: Session,
    start: datetime,
    end: datetime,
    page_id: Optional[str] = None,
    employee: Optional[str] = None,
) -> Dict[int, LeadAgg]:
    """Trả về các lead thuộc Tổng Lead (Mới hoặc Contact Lại) trong kỳ, key = lead id."""
    start_day, end_day = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    # Prefilter theo LEAD: chỉ lấy lead tạo trong kỳ hoặc có hội thoại nhắn tin từ start trở đi.
    # Lấy mọi hội thoại của các lead đó để không mất tag "Đã add" nằm ở hội thoại cũ.
    active_lead_ids = select(FactLeadActivity.lead_id).where(or_(
        FactLeadActivity.contacted_at >= start,
        and_(FactLeadActivity.contacted_at.is_(None), FactLeadActivity.contacted_dates.isnot(None)),
    ))
    query = db.query(
        DimLead.id,
        DimLead.customer_id,
        DimLead.name,
        DimLead.phone_number,
        DimLead.page_id,
        DimLead.first_created_at,
        FactLeadActivity.conversation_id,
        FactLeadActivity.status_tag,
        FactLeadActivity.assigned_users,
        FactLeadActivity.contacted_dates,
        FactLeadActivity.contacted_at,
    ).join(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id).filter(
        FactLeadActivity.assigned_users.isnot(None),
        FactLeadActivity.assigned_users != "",
        or_(DimLead.first_created_at.between(start, end), DimLead.id.in_(active_lead_ids)),
    )
    if page_id:
        query = query.filter(DimLead.page_id == page_id)
    if employee:
        # Lọc thô ở SQL, so khớp chính xác tên ở dưới (tránh "An" dính "Lan Anh")
        query = query.filter(FactLeadActivity.assigned_users.ilike(f"%{employee.strip()}%"))

    employee_key = normalize_text(employee) if employee else None
    leads: Dict[int, LeadAgg] = {}

    for (lid, customer_id, name, phone_number, pg_id, first_created_at,
         conversation_id, status_tag, assigned_users, contacted_dates, contacted_at) in query.all():
        emps = split_csv(assigned_users)
        if employee_key:
            emps = [e for e in emps if normalize_text(e) == employee_key]
        # Bỏ qua hội thoại chưa được phân cho nhân viên (hoặc không thuộc NV đang lọc)
        if not emps:
            continue

        agg = leads.get(lid)
        if agg is None:
            created_at = _strip_tz(first_created_at)
            agg = leads[lid] = LeadAgg(
                id=lid,
                customer_id=customer_id,
                name=name,
                phone_number=phone_number,
                page_id=pg_id,
                first_created_at=created_at,
                is_new=bool(created_at and start <= created_at <= end),
                has_phone=bool(phone_number),
            )

        agg.conversation_ids.append(conversation_id)
        agg.employees.update(emps)
        if status_tag:
            agg.tags.update(split_csv(status_tag))
            if PHONE_TAG in normalize_text(status_tag):
                agg.has_phone = True
        # contacted_dates là chuỗi "YYYY-MM-DD,..." nên so sánh chuỗi là đủ
        agg.contact_days.update(d for d in split_csv(contacted_dates) if start_day <= d <= end_day)

        if agg.primary_employee is None or (
            contacted_at and (agg.primary_contacted_at is None or contacted_at > agg.primary_contacted_at)
        ):
            agg.primary_employee = emps[0]
            agg.primary_contacted_at = contacted_at

    return {lid: agg for lid, agg in leads.items() if agg.is_new or agg.is_recontact}
