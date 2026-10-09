from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
import os
import time
import re
import threading
import logging
from database.db import get_db, SessionLocal
from database.models import DimLead, FactLeadActivity, RawConversation
from database.schema import ensure_schema
from backend.schemas import (
    LeadMetricsSummary,
    TrendResponse,
    TrendDataPoint,
    LeadListResponse,
    LeadResponse,
    RemindLeadResponse,
    RemindLeadItem,
    RemindSummary
)
from backend.lead_metrics import classify_leads, resolve_period, normalize_text, clear_metrics_cache
from etl.utils import (
    parse_pancake_date,
    resolve_phone,
    normalize_phone,
    is_page_id,
    resolve_canonical_page_name,
    KNOWN_PAGE_NAMES,
    ZALO_PAGE_NAMES,
    VN_TZ,
    build_pancake_url,
)

logger = logging.getLogger(__name__)

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
    """Đồng bộ lại contacted_dates, contacted_at, first_created_at, SĐT (phone_number, phone_at) và chuẩn hoá page_id cho từng Fanpage riêng biệt."""
    db = SessionLocal()
    try:
        raws = db.query(RawConversation).order_by(RawConversation.id).all()
        all_leads = db.query(DimLead).all()
        if not all_leads and not raws:
            return

        all_acts = {act.conversation_id: act for act in db.query(FactLeadActivity).all()}
        lead_dict = {l.id: l for l in all_leads}
        # lead id -> [(SĐT, thời điểm khách gửi số)] tìm thấy trong payload các hội thoại của lead
        lead_phones: Dict[int, List[Tuple[str, Optional[datetime]]]] = {}

        # 1. Khởi tạo và xây dựng bản đồ ánh xạ (Mapping) từ Page ID (số / pzl_) sang Page Name (chữ) cho TỪNG PAGE
        id_to_name_map: Dict[str, str] = KNOWN_PAGE_NAMES.copy()
        for r in raws:
            payload = r.payload if isinstance(r.payload, dict) else {}
            pid = str(payload.get('page_id') or (r.page_id if r.page_id and is_page_id(r.page_id) else '') or '')

            # Nếu r.page_id là tên chữ và pid là ID -> map pid -> tên chữ đó
            if r.page_id and not is_page_id(r.page_id) and pid:
                id_to_name_map[pid] = r.page_id.strip()

            # Tìm tên Fanpage từ tin nhắn do Page gửi đi (m_from.id == pid)
            if pid and pid not in id_to_name_map:
                for m in payload.get('messages', []):
                    if isinstance(m, dict):
                        m_from = m.get('from') or {}
                        sender_id = str(m_from.get('id') or '')
                        sender_name = str(m_from.get('name') or '').strip()
                        if sender_id and sender_id in (pid, pid.replace("pzl_", "")) and sender_name and not is_page_id(sender_name):
                            id_to_name_map[pid] = sender_name
                            break

        has_changes = False

        # 2. Cập nhật RawConversation.page_id nếu đang là ID số sang tên chữ tương ứng của page đó
        conv_to_page: Dict[str, str] = {}
        for r in raws:
            payload = r.payload if isinstance(r.payload, dict) else {}
            pid = str(payload.get('page_id') or (r.page_id if r.page_id and is_page_id(r.page_id) else '') or '')

            target_name = (
                id_to_name_map.get(pid)
                or resolve_canonical_page_name(pid, fallback=None)
                or (r.page_id if r.page_id and not is_page_id(r.page_id) else None)
                or resolve_canonical_page_name(r.page_id, fallback=None)
            )

            if target_name:
                conv_to_page[r.pancake_id] = target_name
                if r.page_id != target_name:
                    r.page_id = target_name
                    has_changes = True

            act = all_acts.get(r.pancake_id)
            if not act:
                continue

            msgs = payload.get('messages') or []
            msg_times = [dt for dt in (parse_pancake_date(m.get('inserted_at')) for m in msgs if isinstance(m, dict)) if dt]
            conv_updated = parse_pancake_date(payload.get('updated_at'))
            if conv_updated:
                msg_times.append(conv_updated)
            contacted_dates_str = ",".join(sorted({dt.strftime("%Y-%m-%d") for dt in msg_times})) or None
            if act.contacted_dates != contacted_dates_str:
                act.contacted_dates = contacted_dates_str
                has_changes = True
            contacted_at = max(msg_times) if msg_times else None
            if contacted_at and act.contacted_at != contacted_at:
                act.contacted_at = contacted_at
                has_changes = True

            # Chuẩn hoá thời gian gắn tag (tag_timeline) sang giờ Việt Nam
            tl = act.tag_timeline or payload.get('tag_timeline')
            if tl and isinstance(tl, list):
                tl_updated = False
                new_tl = []
                for item in tl:
                    if isinstance(item, dict):
                        tagged_at = item.get('tagged_at')
                        if tagged_at and isinstance(tagged_at, str) and 'T' in tagged_at:
                            dt = parse_pancake_date(tagged_at)
                            if dt:
                                item = dict(item)
                                item['tagged_at'] = dt.strftime("%Y-%m-%d %H:%M:%S")
                                tl_updated = True
                        new_tl.append(item)
                if tl_updated or (not act.tag_timeline and new_tl):
                    act.tag_timeline = new_tl
                    has_changes = True

            lead = lead_dict.get(act.lead_id)
            if not lead:
                continue

            conv_inserted = parse_pancake_date(payload.get('inserted_at'))
            if conv_inserted and (not lead.first_created_at or lead.first_created_at > conv_inserted):
                lead.first_created_at = conv_inserted
                has_changes = True

            phone, phone_at = resolve_phone(payload)
            if phone:
                lead_phones.setdefault(lead.id, []).append((phone, phone_at))

        # 3. Chuẩn hoá DimLead.page_id theo đúng page của hội thoại của lead đó
        for act in all_acts.values():
            lead = lead_dict.get(act.lead_id)
            if not lead:
                continue
            # Nếu lead.page_id là ID số / pzl_ hoặc rỗng, gán theo tên page của hội thoại thuộc lead đó
            if not lead.page_id or is_page_id(lead.page_id):
                page_for_lead = (
                    conv_to_page.get(act.conversation_id)
                    or resolve_canonical_page_name(lead.page_id, fallback=None)
                    or id_to_name_map.get(str(lead.page_id or ''))
                )
                if page_for_lead:
                    lead.page_id = page_for_lead
                    has_changes = True

        # 4. SĐT: chỉ chuẩn hoá, điền số còn thiếu và lùi phone_at về thời điểm sớm nhất tìm thấy.
        # Không xoá / ghi đè số đã lưu vì payload chỉ còn 30 tin gần nhất của mỗi hội thoại.
        for lead in all_leads:
            found = lead_phones.get(lead.id, [])
            phone = normalize_phone(lead.phone_number) or lead.phone_number
            if not phone and found:
                phone = min(found, key=lambda item: item[1] or datetime.max)[0]
            if phone != lead.phone_number:
                lead.phone_number = phone
                has_changes = True
            dates = [at for found_phone, at in found if found_phone == phone and at]
            if dates and (not lead.phone_at or min(dates) < lead.phone_at):
                lead.phone_at = min(dates)
                has_changes = True

        if has_changes:
            db.commit()
        logger.info(f"Auto repair completed successfully. Page mappings: {id_to_name_map}")
    except Exception as e:
        db.rollback()
        logger.error(f"Auto repair error: {e}")
    finally:
        db.close()

@app.on_event("startup")
def startup_event():
    # Khởi tạo DB Schema khi server khởi động (không chặn module import)
    try:
        ensure_schema()
        logger.info("Database schema verified on startup.")
    except Exception as e:
        logger.error(f"Error ensuring database schema on startup: {e}")

    # Chỉ chạy sửa dữ liệu nặng nếu được bật qua biến môi trường (tránh nghẽn RAM và CPU trên Render Free 512MB)
    if os.getenv("RUN_AUTO_REPAIR", "false").lower() == "true":
        logger.info("RUN_AUTO_REPAIR is true, starting auto_repair_contacted_dates thread...")
        threading.Thread(target=auto_repair_contacted_dates, daemon=True).start()

# Tag phân loại lead: khớp CHÍNH XÁC tên tag (không dùng chuỗi con, tránh dính "TikTok HV other"...).
# Gom cả bộ tag cũ đội sale dùng trước cuối tháng 9/2026.
TAG_CATEGORIES = {
    "Lead Other": ("Lead Other", "Support Other", "HV Khác"),
    "Đào tạo": ("Đào tạo", "HV TCKT"),
}

def _tag_key(tag: str) -> str:
    return " ".join(normalize_text(tag).split())

TAG_TO_CATEGORY = {_tag_key(tag): label for label, tags in TAG_CATEGORIES.items() for tag in tags}

def _categorize_tag(tag: str) -> Optional[str]:
    return TAG_TO_CATEGORY.get(_tag_key(tag))

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
    lead tạo trong kỳ chỉ được tính ở ngày tạo, kể cả khi nhắn lại vào ngày sau.
    phone_leads = số Lead có SĐT thu được/tương tác trong ngày."""
    start, end = resolve_period(start_date, end_date)
    leads = classify_leads(db, start, end, page_id, employee)

    trend: Dict[str, Dict[str, int]] = {}
    day = start
    while day <= end:
        trend[day.strftime("%Y-%m-%d")] = {"new_leads": 0, "recontact_leads": 0, "phone_leads": 0}
        day += timedelta(days=1)

    for lead in leads.values():
        if lead.is_new:
            day_str = lead.first_created_at.strftime("%Y-%m-%d") if lead.first_created_at else None
            if day_str and day_str in trend:
                trend[day_str]["new_leads"] += 1
                if lead.has_phone:
                    trend[day_str]["phone_leads"] += 1
        else:
            days = set(lead.contact_days)
            if not days and lead.phone_event_at:
                days.add(lead.phone_event_at.strftime("%Y-%m-%d"))
            for d in days:
                if d in trend:
                    trend[d]["recontact_leads"] += 1
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

_PAGES_CACHE: Dict[str, Any] = {}
_PAGES_CACHE_TTL = 300.0  # 5 phút cache cho danh sách page
_PAGES_LOCK = threading.Lock()

@app.get("/api/pages/list")
def get_pages(db: Session = Depends(get_db)):
    now = time.time()
    with _PAGES_LOCK:
        if "data" in _PAGES_CACHE and (now - _PAGES_CACHE.get("time", 0) < _PAGES_CACHE_TTL):
            return _PAGES_CACHE["data"]

    results = db.query(DimLead.page_id).distinct().all()
    pages = set()
    for (page,) in results:
        if page:
            p_name = resolve_canonical_page_name(page.strip(), fallback=None)
            if p_name and not is_page_id(p_name):
                pages.add(p_name)
    # Luôn đưa các kênh đã cấu hình sẵn vào danh sách lựa chọn trên dashboard
    for known_name in set(KNOWN_PAGE_NAMES.values()):
        pages.add(known_name)
    # zalo_pages: các page không được cộng vào "Tất cả Page" (kênh chăm sóc), dashboard hiển thị thành nhóm riêng
    result = {"data": sorted(list(pages)), "zalo_pages": sorted(p for p in pages if p in ZALO_PAGE_NAMES)}
    with _PAGES_LOCK:
        _PAGES_CACHE["data"] = result
        _PAGES_CACHE["time"] = now
    return result

_REMIND_CACHE: Dict[str, Tuple[float, Any]] = {}
_REMIND_LOCK = threading.Lock()
_REMIND_TTL = 60  # 60 giây TTL cache

@app.post("/api/admin/clear-cache")
def clear_cache():
    """Xoá toàn bộ cache metrics, page list & remind leads."""
    clear_metrics_cache()
    with _PAGES_LOCK:
        _PAGES_CACHE.clear()
    with _REMIND_LOCK:
        _REMIND_CACHE.clear()
    return {"status": "ok", "message": "All metrics, pages, and remind caches have been cleared."}

@app.post("/api/admin/repair")
def trigger_manual_repair():
    """Kích hoạt chạy auto_repair_contacted_dates thủ công trong background."""
    threading.Thread(target=auto_repair_contacted_dates, daemon=True).start()
    return {"status": "ok", "message": "Auto repair background job has been triggered."}

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
            tag_timeline=lead.tag_timeline if lead.tag_timeline else None,
            assigned_users=", ".join(sorted(lead.employees)) if lead.employees else None,
            messages="\n".join(messages) if messages else None,
            is_contacted=lead.is_contacted,
            is_new=lead.is_new,
            pancake_url=build_pancake_url(
                conversation_id=lead.conversation_ids[0] if lead.conversation_ids else None,
                customer_id=lead.customer_id,
                page_name_or_id=lead.page_id,
            ),
        ))

    return LeadListResponse(total=total, page=page, size=size, data=data)


@app.get("/api/leads/remind", response_model=RemindLeadResponse)
def get_remind_leads(
    employee: Optional[str] = None,
    page_id: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    days_bucket: Optional[str] = None,
    sort_order: Optional[str] = "asc",
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Bảng Chăm sóc Lead: lấy lead theo tag (hoặc tất cả lead nếu tag='all'), tính khoảng cách ngày đến tin nhắn cuối và sắp xếp từ thấp nhất lên xa nhất."""
    from sqlalchemy import or_

    now_vn = datetime.now(VN_TZ).replace(tzinfo=None)

    # 1. Kiểm tra cache in-memory TTL (60s) theo bộ lọc chính
    cache_key = f"{page_id or ''}|{employee or ''}|{tag or ''}"
    now_ts = time.time()
    rows = None

    with _REMIND_LOCK:
        if cache_key in _REMIND_CACHE:
            ts, cached_rows = _REMIND_CACHE[cache_key]
            if now_ts - ts < _REMIND_TTL:
                rows = cached_rows

    if rows is None:
        query = db.query(
            FactLeadActivity.id.label('activity_id'),
            FactLeadActivity.conversation_id,
            FactLeadActivity.status_tag,
            FactLeadActivity.assigned_users,
            FactLeadActivity.contacted_at,
            FactLeadActivity.tag_timeline,
            DimLead.id.label('lead_id'),
            DimLead.customer_id,
            DimLead.name,
            DimLead.phone_number,
            DimLead.page_id,
            DimLead.first_created_at
        ).join(DimLead, FactLeadActivity.lead_id == DimLead.id)

        # Lọc theo Tag nếu có và không phải 'all'
        if tag and tag.strip() and tag.strip().lower() != 'all':
            clean_tag = tag.strip()
            query = query.filter(FactLeadActivity.status_tag.ilike(f"%{clean_tag}%"))

        # Lọc theo Page nếu có
        if page_id and page_id.strip():
            clean_pid = page_id.strip()
            canonical_name = resolve_canonical_page_name(clean_pid, fallback=clean_pid)
            possible_pids = {clean_pid, canonical_name}
            for k, v in KNOWN_PAGE_NAMES.items():
                if v == canonical_name or k == clean_pid:
                    possible_pids.add(k)
                    possible_pids.add(v)
            query = query.filter(DimLead.page_id.in_(list(possible_pids)))

        # Lọc theo Nhân viên nếu có
        if employee and employee.strip():
            emp_clean = employee.strip()
            if normalize_text(emp_clean) in ("chua phan cong", "chưa phân công"):
                query = query.filter(or_(FactLeadActivity.assigned_users.is_(None), FactLeadActivity.assigned_users == ""))
            else:
                query = query.filter(FactLeadActivity.assigned_users.ilike(f"%{emp_clean}%"))

        rows = query.all()
        with _REMIND_LOCK:
            _REMIND_CACHE[cache_key] = (now_ts, rows)

    # Thu thập danh sách nhân viên & toàn bộ thẻ (tags) có trong hệ thống
    all_remind_employees = set()
    all_system_tags = set()
    for r in rows:
        emps = [x.strip() for x in (r.assigned_users or '').split(',') if x.strip()]
        if not emps:
            all_remind_employees.add("Chưa phân công")
        else:
            all_remind_employees.update(emps)
        if r.status_tag:
            for t in r.status_tag.split(','):
                t_clean = t.strip()
                if t_clean:
                    all_system_tags.add(t_clean)

    sorted_tags = sorted(list(all_system_tags))
    if "Remind" in sorted_tags:
        sorted_tags.remove("Remind")
        sorted_tags = ["Remind"] + sorted_tags

    # Lọc tìm kiếm theo Tên khách / SĐT trong RAM
    filtered_rows = rows
    if search and search.strip():
        s_clean = search.strip().lower()
        filtered_rows = [
            r for r in rows
            if (r.name and s_clean in r.name.lower()) or (r.phone_number and s_clean in r.phone_number.lower())
        ]

    items = []
    summary_total = len(filtered_rows)
    cnt_under_1 = 0
    cnt_1_to_3 = 0
    cnt_3_to_7 = 0
    cnt_over_7 = 0

    for r in filtered_rows:
        last_contact = r.contacted_at or r.first_created_at or now_vn
        diff_sec = max(0.0, (now_vn - last_contact).total_seconds())
        days_float = round(diff_sec / 86400.0, 1)
        days_int = int(diff_sec // 86400.0)

        # Thống kê buckets
        if days_int == 0:
            cnt_under_1 += 1
        elif 1 <= days_int <= 3:
            cnt_1_to_3 += 1
        elif 4 <= days_int <= 7:
            cnt_3_to_7 += 1
        else:
            cnt_over_7 += 1

        # Lọc theo days_bucket nếu người dùng bấm chọn
        if days_bucket:
            if days_bucket == "today" and days_int != 0:
                continue
            elif days_bucket == "1_to_3" and not (1 <= days_int <= 3):
                continue
            elif days_bucket == "3_to_7" and not (4 <= days_int <= 7):
                continue
            elif days_bucket == "over_7" and days_int <= 7:
                continue

        # Tìm thời điểm gắn tag từ tag_timeline
        remind_tagged_at = None
        for t_item in r.tag_timeline or []:
            if isinstance(t_item, dict):
                t_name = str(t_item.get('tag') or '').strip().lower()
                target_check = (tag.strip().lower() if tag and tag.lower() != 'all' else 'remind')
                if target_check in t_name and t_item.get('action') == 'add':
                    remind_tagged_at = t_item.get('tagged_at')
                    break

        # Xác định thẻ chính hiển thị
        lead_tags = [t.strip() for t in (r.status_tag or '').split(',') if t.strip()]
        display_tag = "Remind" if any("remind" in t.lower() for t in lead_tags) else (lead_tags[0] if lead_tags else "Không có tag")

        canonical_pg = resolve_canonical_page_name(r.page_id, fallback=r.page_id)
        items.append(
            RemindLeadItem(
                lead_id=r.lead_id,
                customer_id=r.customer_id,
                name=r.name,
                phone_number=r.phone_number,
                page_id=canonical_pg,
                assigned_users=r.assigned_users or "Chưa phân công",
                status_tag=r.status_tag,
                remind_tag=display_tag,
                remind_tagged_at=remind_tagged_at,
                contacted_at=r.contacted_at,
                days_since_last_contact=days_float,
                days_int=days_int,
                conversation_id=r.conversation_id,
                pancake_url=build_pancake_url(
                    conversation_id=r.conversation_id,
                    customer_id=r.customer_id,
                    page_name_or_id=r.page_id,
                ),
            )
        )

    # Sort mặc định: từ thấp nhất lên xa nhất (0 ngày -> 1 ngày -> 2 ngày...)
    reverse_sort = (sort_order == "desc")
    items.sort(key=lambda x: x.days_since_last_contact, reverse=reverse_sort)

    total_filtered = len(items)
    total_pages = (total_filtered + size - 1) // size if total_filtered > 0 else 1
    paginated = items[(page - 1) * size : page * size]

    return RemindLeadResponse(
        total=total_filtered,
        page=page,
        size=size,
        total_pages=total_pages,
        summary=RemindSummary(
            total=summary_total,
            under_1_day=cnt_under_1,
            days_1_to_3=cnt_1_to_3,
            days_3_to_7=cnt_3_to_7,
            over_7_days=cnt_over_7
        ),
        employees=sorted(list(all_remind_employees)),
        tags=sorted_tags,
        items=paginated
    )

