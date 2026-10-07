"""Logic phân loại Lead dùng chung cho summary / trend / list.

Định nghĩa theo kỳ [start, end] (giờ Việt Nam):
- Lead Mới: first_created_at nằm trong kỳ.
- Lead Contact Lại: tạo TRƯỚC kỳ và có tin nhắn (khách hoặc nhân viên) trong kỳ.
- Tổng Lead: Mới + Contact Lại (hai nhóm không trùng nhau).
- SĐT thu được trong kỳ: mỗi số chỉ tính 1 lần, vào thời điểm khách gửi số lần đầu (phone_at; không rõ thì
  dùng ngày tạo lead), gộp trùng giữa các page đang chọn. SĐT Mới = số thu từ lead tạo trong kỳ,
  SĐT Contact Lại = số thu từ lead cũ.
- Phạm vi page: không chọn page → mọi page TRỪ page Zalo (kênh chăm sóc sau khi đã có SĐT, không phải nguồn lead).
Hội thoại chưa phân nhân viên được tính cho "Chưa phân công". Mọi cờ được gộp theo LEAD (không theo từng hội thoại).
"""
import unicodedata
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Set, Tuple, Any

from sqlalchemy import select, or_, and_
from sqlalchemy.orm import Session

from database.models import DimLead, FactLeadActivity
from etl.utils import VN_TZ, resolve_canonical_page_name, KNOWN_PAGE_NAMES, normalize_phone, zalo_page_keys

PHONE_TAG = "đã add"

# In-memory TTL Cache cho classify_leads: tránh việc frontend gọi cùng lúc 4 API (summary, trend, leads, employees)
# đều phải tính toán lại và query DB 4 lần giống hệt nhau
_CACHE_LOCK = threading.Lock()
_CLASSIFY_CACHE: Dict[Tuple[str, str, Optional[str], Optional[str]], Tuple[float, Dict[int, Any]]] = {}
CACHE_TTL = 45.0  # 45 giây

def clear_metrics_cache():
    """Xoá cache số liệu phân loại lead."""
    with _CACHE_LOCK:
        _CLASSIFY_CACHE.clear()



@dataclass
class LeadAgg:
    id: int
    customer_id: str
    name: Optional[str]
    phone_number: Optional[str]
    page_id: str
    first_created_at: Optional[datetime]
    is_new: bool
    has_phone: bool  # Có SĐT (bất kỳ lúc nào): phone_number hoặc tag "Đã add"
    phone_at: Optional[datetime] = None  # Thời điểm khách gửi SĐT lần đầu (None = không rõ)
    phone_event_at: Optional[datetime] = None  # Thời điểm thu SĐT, chỉ có khi số này được TÍNH trong kỳ
    contact_days: Set[str] = field(default_factory=set)  # Các ngày "YYYY-MM-DD" có tin nhắn trong kỳ
    tags: Set[str] = field(default_factory=set)
    tag_timeline: List[dict] = field(default_factory=list)
    employees: Set[str] = field(default_factory=set)
    primary_employee: Optional[str] = None  # NV của hội thoại có tin nhắn gần nhất, dùng cho Pie Chart
    primary_contacted_at: Optional[datetime] = None
    conversation_ids: List[str] = field(default_factory=list)

    @property
    def is_contacted(self) -> bool:
        return bool(self.contact_days)

    @property
    def is_recontact(self) -> bool:
        # Lead cũ gửi SĐT trong kỳ cũng là có tương tác → luôn có SĐT Contact Lại ≤ Lead Contact Lại
        return not self.is_new and (self.is_contacted or self.phone_event_at is not None)


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


def _page_scope(page_id: Optional[str]):
    """Điều kiện lọc theo page. Không chọn page → mọi page trừ Zalo."""
    if not page_id:
        return DimLead.page_id.notin_(sorted(zalo_page_keys()))
    clean_pid = page_id.strip()
    canonical_name = resolve_canonical_page_name(clean_pid, fallback=clean_pid)
    possible_pids = {clean_pid, canonical_name}
    for k, v in KNOWN_PAGE_NAMES.items():
        if v == canonical_name or k == clean_pid:
            possible_pids.add(k)
            possible_pids.add(v)
    return DimLead.page_id.in_(list(possible_pids))


def _phone_owner_ids(db: Session, start: datetime, end: datetime, scope) -> Set[int]:
    """ID các lead là "chủ" của một SĐT thu được trong kỳ.

    Mỗi số chỉ tính cho lead có thời điểm thu sớm nhất trong phạm vi page (xét mọi thời gian, không phụ thuộc
    lọc nhân viên) → số đã có từ kỳ trước hoặc trùng với lead khác không bị đếm lại.
    """
    obtained_in_period = or_(
        DimLead.phone_at.between(start, end),
        and_(DimLead.phone_at.is_(None), DimLead.first_created_at.between(start, end)),
    )
    period_phones = select(DimLead.phone_number).where(
        DimLead.phone_number.isnot(None), DimLead.phone_number != "", obtained_in_period, scope
    ).correlate(None)
    rows = db.query(DimLead.id, DimLead.phone_number, DimLead.phone_at, DimLead.first_created_at).filter(
        DimLead.phone_number.in_(period_phones), scope
    ).all()

    first_seen: Dict[str, Tuple[datetime, int]] = {}
    for lid, phone, phone_at, created_at in rows:
        obtained_at = _strip_tz(phone_at or created_at)
        if not obtained_at:
            continue
        key = normalize_phone(phone) or phone
        if key not in first_seen or (obtained_at, lid) < first_seen[key]:
            first_seen[key] = (obtained_at, lid)
    return {lid for obtained_at, lid in first_seen.values() if start <= obtained_at <= end}


def classify_leads(
    db: Session,
    start: datetime,
    end: datetime,
    page_id: Optional[str] = None,
    employee: Optional[str] = None,
    bypass_cache: bool = False,
) -> Dict[int, LeadAgg]:
    """Trả về các lead thuộc Tổng Lead (Mới hoặc Contact Lại) trong kỳ, key = lead id."""
    start_day, end_day = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    page_key = page_id.strip() if page_id else None
    emp_key = employee.strip() if employee else None
    cache_key = (start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), page_key, emp_key)

    # 1. Trả ngay từ Cache nếu còn hạn (giảm tải 100% cho các request đồng thời từ frontend)
    if not bypass_cache:
        now = time.time()
        with _CACHE_LOCK:
            if cache_key in _CLASSIFY_CACHE:
                cached_time, cached_data = _CLASSIFY_CACHE[cache_key]
                if now - cached_time < CACHE_TTL:
                    return cached_data

    scope = _page_scope(page_id)

    # Prefilter theo LEAD: chỉ lấy lead tạo trong kỳ, gửi SĐT trong kỳ, hoặc có hội thoại nhắn tin từ start trở đi.
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
        DimLead.phone_at,
        DimLead.page_id,
        DimLead.first_created_at,
        FactLeadActivity.conversation_id,
        FactLeadActivity.status_tag,
        FactLeadActivity.assigned_users,
        FactLeadActivity.contacted_dates,
        FactLeadActivity.contacted_at,
        FactLeadActivity.tag_timeline,
    ).join(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id).filter(
        scope,
        or_(
            DimLead.first_created_at.between(start, end),
            DimLead.phone_at.between(start, end),
            DimLead.id.in_(active_lead_ids),
        ),
    )
    if employee:
        emp_clean = employee.strip()
        if normalize_text(emp_clean) in ("chua phan cong", "chưa phân công"):
            query = query.filter(or_(FactLeadActivity.assigned_users.is_(None), FactLeadActivity.assigned_users == ""))
        else:
            # Lọc thô ở SQL, so khớp chính xác tên ở dưới (tránh "An" dính "Lan Anh")
            query = query.filter(FactLeadActivity.assigned_users.ilike(f"%{emp_clean}%"))

    employee_key = normalize_text(employee) if employee else None
    leads: Dict[int, LeadAgg] = {}

    for (lid, customer_id, name, phone_number, phone_at, pg_id, first_created_at,
         conversation_id, status_tag, assigned_users, contacted_dates, contacted_at, tag_timeline) in query.all():
        emps = split_csv(assigned_users)
        if not emps:
            emps = ["Chưa phân công"]

        if employee_key:
            emps = [e for e in emps if normalize_text(e) == employee_key]
            # Nếu đang lọc theo 1 nhân viên cụ thể mà hội thoại không thuộc NV này thì bỏ qua
            if not emps:
                continue

        agg = leads.get(lid)
        if agg is None:
            created_at = _strip_tz(first_created_at)
            canonical_pg = resolve_canonical_page_name(pg_id, fallback=pg_id)
            agg = leads[lid] = LeadAgg(
                id=lid,
                customer_id=customer_id,
                name=name,
                phone_number=phone_number,
                page_id=canonical_pg,
                first_created_at=created_at,
                is_new=bool(created_at and start <= created_at <= end),
                has_phone=bool(phone_number),
                phone_at=_strip_tz(phone_at),
            )

        agg.conversation_ids.append(conversation_id)
        agg.employees.update(emps)
        if status_tag:
            agg.tags.update(split_csv(status_tag))
            if PHONE_TAG in normalize_text(status_tag):
                agg.has_phone = True
        if tag_timeline and isinstance(tag_timeline, list):
            for t_item in tag_timeline:
                if t_item not in agg.tag_timeline:
                    agg.tag_timeline.append(t_item)
        # contacted_dates là chuỗi "YYYY-MM-DD,..." nên so sánh chuỗi là đủ
        agg.contact_days.update(d for d in split_csv(contacted_dates) if start_day <= d <= end_day)
        if contacted_at and start <= contacted_at <= end:
            agg.contact_days.add(contacted_at.strftime("%Y-%m-%d"))

        if agg.primary_employee is None or (
            contacted_at and (agg.primary_contacted_at is None or contacted_at > agg.primary_contacted_at)
        ):
            agg.primary_employee = emps[0]
            agg.primary_contacted_at = contacted_at

    # SĐT thu được trong kỳ: thời điểm thu nằm trong kỳ và lead là chủ của số đó
    owner_ids = _phone_owner_ids(db, start, end, scope)
    for agg in leads.values():
        obtained_at = agg.phone_at or agg.first_created_at
        if not agg.has_phone or not obtained_at or not (start <= obtained_at <= end):
            continue
        # Lead chỉ có tag "Đã add" (không có số) thì không gộp trùng được → tính theo ngày tạo lead
        if not agg.phone_number or agg.id in owner_ids:
            agg.phone_event_at = obtained_at

    result = {lid: agg for lid, agg in leads.items() if agg.is_new or agg.is_recontact}

    # 2. Lưu vào Cache và dọn dẹp các cache quá hạn
    now = time.time()
    with _CACHE_LOCK:
        if len(_CLASSIFY_CACHE) > 50:
            expired = [k for k, (t, _) in _CLASSIFY_CACHE.items() if now - t > CACHE_TTL]
            for k in expired:
                _CLASSIFY_CACHE.pop(k, None)
        _CLASSIFY_CACHE[cache_key] = (now, result)

    return result
