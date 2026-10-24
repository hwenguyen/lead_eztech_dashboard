from fastapi import FastAPI, Depends, Query, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, defer
from sqlalchemy import or_, desc, func
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any, Union
import os
import time
import re
import threading
import logging
from database.db import get_db, SessionLocal
from database.models import DimLead, FactLeadActivity, RawConversation, DealWin
from database.deal_sync import find_lead_info_by_phone, sync_all_deals_with_dim_leads
from database.schema import ensure_schema
from backend.schemas import (
    LeadMetricsSummary,
    TrendResponse,
    TrendDataPoint,
    LeadListResponse,
    LeadResponse,
    RemindLeadResponse,
    RemindLeadItem,
    RemindSummary,
    DealWinItem,
    DealWinListResponse,
    DealWinSummary,
    DealWinOptions,
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

from backend.broadcast import router as broadcast_router
from backend.auth import router as auth_router

app = FastAPI(title="Pancake Lead Reporting API")
app.include_router(auth_router)
app.include_router(broadcast_router, prefix="/api/broadcast", tags=["Broadcast"])

# Cấu hình CORS: Ưu tiên danh sách ALLOWED_ORIGINS từ biến môi trường
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "").strip()
if allowed_origins_env:
    allowed_origins = [orig.strip() for orig in allowed_origins_env.split(",") if orig.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

def verify_webhook_secret(request: Request):
    """Xác thực Webhook Secret từ Header X-Webhook-Secret hoặc query param ?secret=."""
    webhook_secret = os.getenv("WEBHOOK_SECRET", "").strip()
    if not webhook_secret:
        return
    token = request.headers.get("X-Webhook-Secret") or request.query_params.get("secret")
    if not token or token.strip() != webhook_secret:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Sai hoặc thiếu mã bí mật Webhook (Header X-Webhook-Secret hoặc ?secret=)"
        )

def verify_admin_secret(request: Request):
    """Xác thực Admin Secret cho các tác vụ quản trị (clear cache, repair)."""
    admin_secret = os.getenv("ADMIN_SECRET_KEY", "").strip() or os.getenv("WEBHOOK_SECRET", "").strip()
    if not admin_secret:
        return
    token = (
        request.headers.get("X-Admin-Secret")
        or request.headers.get("X-Webhook-Secret")
        or request.query_params.get("secret")
    )
    if not token or token.strip() != admin_secret:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Cần cung cấp mã Admin Secret (Header X-Admin-Secret hoặc ?secret=)"
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
            if r.pancake_id and r.pancake_id.startswith("pzl_g_"):
                continue
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
            if r.pancake_id and r.pancake_id.startswith("pzl_g_"):
                continue
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
        from backend.auth import init_default_admin
        with SessionLocal() as db_session:
            init_default_admin(db_session)
    except Exception as e:
        logger.error(f"Error ensuring database schema on startup: {e}")

    # Ngăn chặn tự động tải toàn bộ bảng raw_conversations khi Render khởi động lại (bảo vệ băng thông Neon).
    # Chỉ chạy khi đặt RUN_AUTO_REPAIR="force" hoặc gọi trực tiếp qua API /api/admin/repair
    if os.getenv("RUN_AUTO_REPAIR", "false").lower() == "force":
        logger.info("RUN_AUTO_REPAIR is force, starting auto_repair_contacted_dates thread...")
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
    tag_stats: Counter = Counter({"Lead Other": 0, "Đào tạo": 0, "Other": 0})
    phone_tag_stats: Counter = Counter({"Lead Other": 0, "Đào tạo": 0, "Other": 0})
    new_phone_tag_stats: Counter = Counter({"Lead Other": 0, "Đào tạo": 0, "Other": 0})
    recontact_phone_tag_stats: Counter = Counter({"Lead Other": 0, "Đào tạo": 0, "Other": 0})

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

        cats = {_categorize_tag(t) for t in lead.tags} - {None}
        if "Lead Other" in cats and "Đào tạo" in cats:
            # Nếu có cả 2 nhóm tag, chọn nhóm có tag gắn gần nhất trong timeline
            latest_cat = None
            latest_time = None
            for item in lead.tag_timeline:
                cat = _categorize_tag(item.get("tag", ""))
                if cat in ("Lead Other", "Đào tạo"):
                    t_str = item.get("tagged_at")
                    if t_str and (latest_time is None or t_str > latest_time):
                        latest_time = t_str
                        latest_cat = cat
            chosen_cat = latest_cat or "Đào tạo"
        elif "Lead Other" in cats:
            chosen_cat = "Lead Other"
        elif "Đào tạo" in cats:
            chosen_cat = "Đào tạo"
        else:
            chosen_cat = "Other"

        tag_stats[chosen_cat] += 1
        if lead.has_phone:
            phone_tag_stats[chosen_cat] += 1
            if lead.is_new:
                new_phone_tag_stats[chosen_cat] += 1
            else:
                recontact_phone_tag_stats[chosen_cat] += 1

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
        phone_tag_stats=dict(phone_tag_stats),
        new_phone_tag_stats=dict(new_phone_tag_stats),
        recontact_phone_tag_stats=dict(recontact_phone_tag_stats),
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
_PAGES_CACHE_TTL = 3600.0  # 60 phút cache cho danh sách page
_PAGES_LOCK = threading.Lock()

@app.get("/api/pages/list")
def get_pages(db: Session = Depends(get_db)):
    with _PAGES_LOCK:
        now = time.time()
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
        _PAGES_CACHE["data"] = result
        _PAGES_CACHE["time"] = now
        return result

_REMIND_CACHE: Dict[str, Tuple[float, Any]] = {}
_REMIND_LOCK = threading.Lock()
_REMIND_TTL = 900.0  # 15 phút TTL cache để tiết kiệm băng thông Neon

_LAST_MSG_CACHE: Dict[str, Tuple[float, Optional[str]]] = {}
_LAST_MSG_LOCK = threading.Lock()
_LAST_MSG_TTL = 900.0  # 15 phút cache tin nhắn cuối

_TAG_TL_CACHE: Dict[str, Tuple[float, List[dict]]] = {}
_TAG_TL_LOCK = threading.Lock()
_TAG_TL_TTL = 900.0  # 15 phút cache tag_timeline theo từng hội thoại

_DEAL_CACHE: Dict[str, Tuple[float, Any]] = {}
_DEAL_CACHE_LOCK = threading.Lock()
_DEAL_CACHE_TTL = 300.0  # 5 phút cache cho Deal Win

def _fetch_tag_timelines(db: Session, conv_ids: List[str]) -> Dict[str, List[dict]]:
    """Chỉ tải cột JSON tag_timeline cho đúng 15-20 hội thoại hiển thị trên trang hiện tại (tiết kiệm 99.9% Egress)."""
    if not conv_ids:
        return {}
    now_ts = time.time()
    tl_map: Dict[str, List[dict]] = {}
    missing_cids: List[str] = []

    with _TAG_TL_LOCK:
        for cid in conv_ids:
            if cid in _TAG_TL_CACHE and (now_ts - _TAG_TL_CACHE[cid][0] < _TAG_TL_TTL):
                tl_map[cid] = _TAG_TL_CACHE[cid][1]
            else:
                missing_cids.append(cid)

    if missing_cids:
        rows = db.query(
            FactLeadActivity.conversation_id,
            FactLeadActivity.tag_timeline
        ).filter(FactLeadActivity.conversation_id.in_(missing_cids)).all()
        fetched_tl = {cid: (tl if isinstance(tl, list) else []) for cid, tl in rows}

        with _TAG_TL_LOCK:
            if len(_TAG_TL_CACHE) > 2000:
                expired = [k for k, (t, _) in _TAG_TL_CACHE.items() if now_ts - t > _TAG_TL_TTL]
                for k in expired:
                    _TAG_TL_CACHE.pop(k, None)
            for cid in missing_cids:
                val = fetched_tl.get(cid, [])
                _TAG_TL_CACHE[cid] = (now_ts, val)
                tl_map[cid] = val

    return tl_map

@app.post("/api/admin/clear-cache", dependencies=[Depends(verify_admin_secret)])
def clear_cache():
    """Xoá toàn bộ cache metrics, page list, tin nhắn cuối, remind leads & deal wins."""
    clear_metrics_cache()
    with _PAGES_LOCK:
        _PAGES_CACHE.clear()
    with _REMIND_LOCK:
        _REMIND_CACHE.clear()
    with _LAST_MSG_LOCK:
        _LAST_MSG_CACHE.clear()
    with _TAG_TL_LOCK:
        _TAG_TL_CACHE.clear()
    with _DEAL_CACHE_LOCK:
        _DEAL_CACHE.clear()
    return {"status": "ok", "message": "All metrics, pages, last messages, remind, and deal caches have been cleared."}

@app.post("/api/admin/repair", dependencies=[Depends(verify_admin_secret)])
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
    import json
    start, end = resolve_period(start_date, end_date)
    leads = sorted(
        classify_leads(db, start, end, page_id, employee).values(),
        key=lambda l: l.first_created_at or datetime.min,
        reverse=True,
    )
    total = len(leads)
    paginated = leads[(page - 1) * size : page * size]

    # Chỉ lấy tin nhắn cuối cùng cho page hiện tại và lưu cache 15 phút
    conv_ids = [cid for lead in paginated for cid in lead.conversation_ids if cid]
    now_ts = time.time()
    last_msg_map: Dict[str, Optional[str]] = {}
    missing_cids: List[str] = []

    with _LAST_MSG_LOCK:
        for cid in conv_ids:
            if cid in _LAST_MSG_CACHE and (now_ts - _LAST_MSG_CACHE[cid][0] < _LAST_MSG_TTL):
                last_msg_map[cid] = _LAST_MSG_CACHE[cid][1]
            else:
                missing_cids.append(cid)

    if missing_cids:
        is_pg = bool(db.bind and db.bind.dialect.name == "postgresql")
        if is_pg:
            # Trên Postgres (Neon): chỉ trích xuất phần tử tin nhắn cuối cùng (-1) ngay trong SQL (~100 bytes thay vì 25KB/hội thoại)
            rows = db.query(
                RawConversation.pancake_id,
                RawConversation.payload.op('->')('messages').op('->')(-1)
            ).filter(RawConversation.pancake_id.in_(missing_cids)).all()
            fetched_map = {}
            for cid, last_m in rows:
                if isinstance(last_m, str):
                    try:
                        last_m = json.loads(last_m)
                    except Exception:
                        last_m = None
                msg_str = None
                if isinstance(last_m, dict) and last_m.get("message"):
                    sender = last_m.get("sender_name", last_m.get("role", "Unknown"))
                    clean_msg = re.sub(r'<[^>]+>', '', str(last_m.get('message', '')))
                    msg_str = f"[{sender}]: {clean_msg}"
                fetched_map[cid] = msg_str
        else:
            raw_results = db.query(RawConversation).filter(RawConversation.pancake_id.in_(missing_cids)).all()
            fetched_map = {}
            for r in raw_results:
                msg_str = None
                if r.payload and isinstance(r.payload, dict):
                    for m in reversed(r.payload.get("messages", [])):
                        if isinstance(m, dict) and m.get("message"):
                            sender = m.get("sender_name", m.get("role", "Unknown"))
                            clean_msg = re.sub(r'<[^>]+>', '', str(m.get('message', '')))
                            msg_str = f"[{sender}]: {clean_msg}"
                            break
                fetched_map[r.pancake_id] = msg_str

        with _LAST_MSG_LOCK:
            if len(_LAST_MSG_CACHE) > 2000:
                expired_c = [k for k, (t, _) in _LAST_MSG_CACHE.items() if now_ts - t > _LAST_MSG_TTL]
                for k in expired_c:
                    _LAST_MSG_CACHE.pop(k, None)
            for cid in missing_cids:
                val = fetched_map.get(cid)
                _LAST_MSG_CACHE[cid] = (now_ts, val)
                last_msg_map[cid] = val

    # Chỉ tải tag_timeline cho đúng 15 lead hiển thị trên trang hiện tại
    tl_map = _fetch_tag_timelines(db, conv_ids)

    data = []
    for lead in paginated:
        messages = []
        lead_tl = []
        for cid in lead.conversation_ids:
            m_str = last_msg_map.get(cid)
            if m_str:
                messages.append(m_str)
            for t_item in tl_map.get(cid, []):
                if t_item not in lead_tl:
                    lead_tl.append(t_item)

        data.append(LeadResponse(
            id=lead.id,
            customer_id=lead.customer_id,
            name=lead.name,
            phone_number=lead.phone_number,
            page_id=lead.page_id,
            first_created_at=lead.first_created_at,
            status_tag=", ".join(sorted(lead.tags)) if lead.tags else None,
            tag_timeline=lead_tl if lead_tl else None,
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
    now_vn = datetime.now(VN_TZ).replace(tzinfo=None)

    # 1. Cache toàn bộ bảng hoạt động trong RAM (TTL 15 phút) với single-flight lock:
    # KHÔNG tải cột JSON tag_timeline (5.2 MB) ở đây để tiết kiệm >90% băng thông Neon; chỉ tải cho 20 dòng trang hiện tại.
    with _REMIND_LOCK:
        now_ts = time.time()
        all_rows = None
        if "ALL" in _REMIND_CACHE:
            ts, cached_rows = _REMIND_CACHE["ALL"]
            if now_ts - ts < _REMIND_TTL:
                all_rows = cached_rows

        if all_rows is None:
            all_rows = db.query(
                FactLeadActivity.id.label('activity_id'),
                FactLeadActivity.conversation_id,
                FactLeadActivity.status_tag,
                FactLeadActivity.assigned_users,
                FactLeadActivity.contacted_at,
                DimLead.id.label('lead_id'),
                DimLead.customer_id,
                DimLead.name,
                DimLead.phone_number,
                DimLead.page_id,
                DimLead.first_created_at
            ).join(DimLead, FactLeadActivity.lead_id == DimLead.id).filter(
                ~FactLeadActivity.conversation_id.like("pzl_g_%")
            ).all()
            _REMIND_CACHE["ALL"] = (now_ts, all_rows)

    rows = all_rows

    # Lọc theo Tag trong RAM nếu có và không phải 'all'
    if tag and tag.strip() and tag.strip().lower() != 'all':
        clean_tag = tag.strip().lower()
        rows = [r for r in rows if r.status_tag and clean_tag in r.status_tag.lower()]

    # Lọc theo Page trong RAM nếu có
    if page_id and page_id.strip():
        clean_pid = page_id.strip()
        canonical_name = resolve_canonical_page_name(clean_pid, fallback=clean_pid)
        possible_pids = {clean_pid, canonical_name}
        for k, v in KNOWN_PAGE_NAMES.items():
            if v == canonical_name or k == clean_pid:
                possible_pids.add(k)
                possible_pids.add(v)
        rows = [r for r in rows if r.page_id in possible_pids]

    # Lọc theo Nhân viên trong RAM nếu có
    if employee and employee.strip():
        emp_clean = employee.strip()
        if normalize_text(emp_clean) in ("chua phan cong", "chưa phân công"):
            rows = [r for r in rows if not r.assigned_users or not r.assigned_users.strip()]
        else:
            emp_lower = emp_clean.lower()
            rows = [r for r in rows if r.assigned_users and emp_lower in r.assigned_users.lower()]

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
                remind_tagged_at=None,
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

    # Chỉ tải tag_timeline cho 20 dòng của trang hiện tại để lấy remind_tagged_at
    page_cids = [it.conversation_id for it in paginated if it.conversation_id]
    tl_map = _fetch_tag_timelines(db, page_cids)
    target_check = (tag.strip().lower() if tag and tag.lower() != 'all' else 'remind')
    for it in paginated:
        for t_item in tl_map.get(it.conversation_id or "", []):
            if isinstance(t_item, dict):
                t_name = str(t_item.get('tag') or '').strip().lower()
                if target_check in t_name and t_item.get('action') == 'add':
                    it.remind_tagged_at = t_item.get('tagged_at')
                    break

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


# ==========================================
# DEAL WIN APIs (Google Sheet / Form Webhook)
# ==========================================

def _extract_field(row: Dict[str, Any], candidates: List[str]) -> Optional[Any]:
    """Tìm giá trị trường dữ liệu theo danh sách từ khóa ứng viên (không phân biệt hoa thường/dấu)."""
    normalized_row = {normalize_text(str(k)): v for k, v in row.items()}
    # 1. Tìm khớp chính xác
    for c in candidates:
        norm_c = normalize_text(c)
        if norm_c in normalized_row and normalized_row[norm_c] is not None:
            val = normalized_row[norm_c]
            if isinstance(val, str) and not val.strip():
                continue
            return val
    # 2. Tìm khớp chứa chuỗi con
    for c in candidates:
        norm_c = normalize_text(c)
        for k, v in normalized_row.items():
            if norm_c in k and v is not None:
                if isinstance(v, str) and not v.strip():
                    continue
                return v
    return None

@app.post("/api/deals/webhook", dependencies=[Depends(verify_webhook_secret)])
async def receive_deal_webhook(request: Request, db: Session = Depends(get_db)):
    """Nhận dữ liệu Deal Win được đẩy tự động từ Google Sheet / Google Form.
    Hỗ trợ nhận 1 dòng đơn lẻ (dict) hoặc nhiều dòng (list).
    Tự động chuẩn hóa tên cột tiếng Việt, SĐT, số tiền và loại bỏ trùng lặp.
    """
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {e}")

    # Chuẩn hoá đầu vào thành danh sách các dòng (rows)
    rows: List[Dict[str, Any]] = []
    if isinstance(body, list):
        rows = [r for r in body if isinstance(r, dict)]
    elif isinstance(body, dict):
        if "data" in body and isinstance(body["data"], list):
            rows = [r for r in body["data"] if isinstance(r, dict)]
        else:
            rows = [body]

    if not rows:
        return {"status": "ok", "synced_count": 0, "message": "No data rows provided."}

    synced_count = 0
    updated_count = 0

    for row in rows:
        # Bóc tách chính xác theo các cột Google Sheet 'THÔNG TIN HỌC VIÊN - EzTech'
        submitted_raw = _extract_field(row, ["timestamp", "dấu thời gian", "thời gian", "ngày", "created_at"])
        submitted_at = parse_pancake_date(submitted_raw) if submitted_raw else datetime.now(VN_TZ).replace(tzinfo=None)

        email = _extract_field(row, ["email", "mail", "thư điện tử"])
        full_name = _extract_field(row, ["họ và tên", "họ tên", "tên học viên", "tên", "khách hàng", "full_name", "customer_name"])
        raw_phone = _extract_field(row, ["sđt", "số điện thoại", "số điện thoạt", "phone_number", "phone", "mobile"])
        phone = normalize_phone(raw_phone) if raw_phone else None

        birth_year = _extract_field(row, ["năm sinh", "birth_year"])
        birth_year_str = str(int(float(birth_year))) if birth_year and str(birth_year).replace('.', '', 1).isdigit() else (str(birth_year).strip() if birth_year else None)

        address = _extract_field(row, ["địa chỉ (tỉnh / thành phố)", "nơi ở", "địa chỉ", "address", "tỉnh", "thành phố"])
        industry = _extract_field(row, ["lĩnh vực hoạt động", "lĩnh vực", "industry"])
        job_title = _extract_field(row, ["vị trí/ ngành nghề (ví dụ: kế toán trưởng - thời trang)", "vị trí", "ngành nghề", "job_title"])
        expectation = _extract_field(row, ["mục đích/ kì vọng tham gia khoá học", "mục đích", "kì vọng", "expectation"])
        care_by = _extract_field(row, ["chăm sóc", "sale", "nhân viên chốt", "nhân viên", "care_by", "sales_person"])

        # Định danh dòng trên Sheet
        sheet_row_id = _extract_field(row, ["sheet_row_id", "row_id", "row_number", "id"])
        if sheet_row_id:
            sheet_row_id = str(sheet_row_id).strip()

        # Map với DimLead và Pancake qua SĐT
        dim_lead_id, is_student, pancake_care, lead_tag = find_lead_info_by_phone(phone, db)
        from database.deal_sync import normalize_sale_name
        final_care_by = pancake_care or normalize_sale_name(care_by) or "Chưa phân công"

        # Kiểm tra trùng lặp theo sheet_row_id hoặc theo SĐT (defer raw_data để tiết kiệm băng thông)
        existing_deal = None
        if sheet_row_id:
            existing_deal = db.query(DealWin).options(defer(DealWin.raw_data)).filter_by(sheet_row_id=sheet_row_id).first()

        if not existing_deal and phone:
            existing_deal = db.query(DealWin).options(defer(DealWin.raw_data)).filter(DealWin.phone_number == phone).first()

        if existing_deal:
            existing_deal.timestamp = submitted_at
            existing_deal.email = str(email).strip() if email else existing_deal.email
            existing_deal.full_name = str(full_name).strip() if full_name else existing_deal.full_name
            existing_deal.phone_number = phone or existing_deal.phone_number
            existing_deal.birth_year = birth_year_str or existing_deal.birth_year
            existing_deal.address = str(address).strip() if address else existing_deal.address
            existing_deal.industry = str(industry).strip() if industry else existing_deal.industry
            existing_deal.job_title = str(job_title).strip() if job_title else existing_deal.job_title
            existing_deal.expectation = str(expectation).strip() if expectation else existing_deal.expectation
            existing_deal.care_by = final_care_by or existing_deal.care_by
            existing_deal.dim_lead_id = dim_lead_id or existing_deal.dim_lead_id
            existing_deal.is_student = is_student
            existing_deal.lead_tag = lead_tag or existing_deal.lead_tag
            existing_deal.raw_data = row
            updated_count += 1
        else:
            new_deal = DealWin(
                sheet_row_id=sheet_row_id,
                timestamp=submitted_at,
                email=str(email).strip() if email else None,
                full_name=str(full_name).strip() if full_name else "Học viên",
                phone_number=phone,
                birth_year=birth_year_str,
                address=str(address).strip() if address else None,
                industry=str(industry).strip() if industry else None,
                job_title=str(job_title).strip() if job_title else None,
                expectation=str(expectation).strip() if expectation else None,
                care_by=final_care_by,
                dim_lead_id=dim_lead_id,
                is_student=is_student,
                lead_tag=lead_tag,
                raw_data=row,
            )
            db.add(new_deal)
            synced_count += 1

    db.commit()

    # Xóa cache Deal Win để dashboard cập nhật số liệu mới ngay
    with _DEAL_CACHE_LOCK:
        _DEAL_CACHE.clear()

    return {
        "status": "ok",
        "synced_count": synced_count,
        "updated_count": updated_count,
        "total_processed": len(rows),
        "message": f"Đã lưu thành công {synced_count} học viên mới và cập nhật {updated_count} học viên."
    }

@app.post("/api/deals/sync-leads")
def trigger_deal_leads_sync(db: Session = Depends(get_db)):
    """Đồng bộ Deal Win với DimLead (map SĐT, kiểm tra tag Đã là học viên, cập nhật nhân viên chăm sóc từ Pancake)."""
    from database.deal_sync import sync_all_deals_with_dim_leads, normalize_sale_name
    total, students, updated = sync_all_deals_with_dim_leads(db)
    with _DEAL_CACHE_LOCK:
        _DEAL_CACHE.clear()
    return {
        "status": "ok",
        "total_deals": total,
        "students_count": students,
        "care_by_updated": updated,
        "message": f"Đã map thành công {total} deal: {students} học viên có tag 'Đã là học viên', {updated} lượt cập nhật nhân viên chăm sóc từ Pancake."
    }

@app.get("/api/deals/options", response_model=DealWinOptions)
def get_deals_options(
    only_student: bool = Query(True, description="Chỉ lấy danh sách sale có tag Đã là học viên"),
    db: Session = Depends(get_db)
):
    """Lấy danh sách các nhân viên sale từ Deal Win để render dropdown filters (có cache 10 phút).
    Luôn lấy logic chuẩn tương đương với 'Đã là học viên' (chỉ lấy các nhân viên chăm sóc từ hội thoại có tag học viên).
    """
    from database.deal_sync import normalize_sale_name
    cache_key = "deals_options_student"
    with _DEAL_CACHE_LOCK:
        if cache_key in _DEAL_CACHE:
            ts, val = _DEAL_CACHE[cache_key]
            if time.time() - ts < 600.0:
                return val

    # Luôn chỉ lấy danh sách nhân viên có học viên chốt (Đã là học viên)
    sales_query = db.query(DealWin.care_by).distinct().filter(
        DealWin.is_student == True,
        DealWin.care_by.isnot(None),
        func.trim(DealWin.care_by) != ""
    )

    raw_sales = [r[0] for r in sales_query.all() if r[0]]
    individual_sales = set()
    for s in raw_sales:
        norm = normalize_sale_name(s)
        if norm:
            for name in norm.split(","):
                clean_name = name.strip()
                if clean_name and clean_name != "Chưa phân công":
                    individual_sales.add(clean_name)
    sales = sorted(list(individual_sales))

    res = DealWinOptions(sales_persons=sales)
    with _DEAL_CACHE_LOCK:
        _DEAL_CACHE[cache_key] = (time.time(), res)
    return res

@app.get("/api/deals/summary", response_model=DealWinSummary)
def get_deals_summary(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    sales_person: Optional[str] = None,
    only_student: bool = Query(True, description="Chỉ tính những ai có tag Đã là học viên"),
    db: Session = Depends(get_db)
):
    """Thống kê tổng quan Deal Win theo khoảng thời gian - Tối ưu 100% bằng in-memory cache và thống kê sale chuẩn xác."""
    start, end = resolve_period(start_date, end_date)
    cache_key = f"deals_summary_{start}_{end}_{sales_person}_{only_student}"

    with _DEAL_CACHE_LOCK:
        if cache_key in _DEAL_CACHE:
            ts, val = _DEAL_CACHE[cache_key]
            if time.time() - ts < _DEAL_CACHE_TTL:
                return val

    filters = [DealWin.timestamp.between(start, end)]
    if only_student:
        filters.append(DealWin.is_student == True)
    if sales_person and sales_person.strip():
        filters.append(DealWin.care_by.ilike(f"%{sales_person.strip()}%"))

    # 1. Total deals count
    total_deals = db.query(func.count(DealWin.id)).filter(*filters).scalar() or 0

    # 2. Sales person stats (Tách các tên ghép phẩy để thống kê riêng từng nhân viên cho biểu đồ Top Sales)
    care_rows = db.query(DealWin.care_by).filter(*filters).all()
    sales_counts = {}
    for (care_val,) in care_rows:
        if not care_val or not str(care_val).strip():
            sales_counts["Chưa phân công"] = sales_counts.get("Chưa phân công", 0) + 1
        else:
            names = [n.strip() for n in str(care_val).split(",") if n.strip()]
            if not names:
                sales_counts["Chưa phân công"] = sales_counts.get("Chưa phân công", 0) + 1
            else:
                for n in names:
                    sales_counts[n] = sales_counts.get(n, 0) + 1
    sales_stats = dict(sorted(sales_counts.items(), key=lambda item: item[1], reverse=True))

    # 3. Daily trend (GROUP BY DATE(timestamp))
    trend_query = db.query(
        func.date(DealWin.timestamp).label("d"),
        func.count(DealWin.id).label("cnt")
    ).filter(*filters).group_by(func.date(DealWin.timestamp)).order_by("d").all()
    daily_trend = [{"date": str(r.d), "count": r.cnt} for r in trend_query if r.d]

    top_sale = next(iter(sales_stats.keys()), None)

    summary = DealWinSummary(
        total_deals=total_deals,
        top_sales_person=top_sale,
        sales_person_stats=sales_stats,
        daily_trend=daily_trend
    )

    with _DEAL_CACHE_LOCK:
        _DEAL_CACHE[cache_key] = (time.time(), summary)

    return summary

@app.get("/api/deals/list", response_model=DealWinListResponse)
def get_deals_list(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    sales_person: Optional[str] = None,
    search: Optional[str] = None,
    only_student: bool = Query(True, description="Chỉ hiển thị những ai có tag Đã là học viên"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Danh sách Deal Win có phân trang tối ưu - Chỉ fetch các cột cần thiết, KHÔNG tải raw_data JSON để tiết kiệm tối đa Network Transfer."""
    start, end = resolve_period(start_date, end_date)

    query = db.query(DealWin).filter(DealWin.timestamp.between(start, end))

    if only_student:
        query = query.filter(DealWin.is_student == True)

    if sales_person and sales_person.strip():
        query = query.filter(DealWin.care_by.ilike(f"%{sales_person.strip()}%"))

    if search and search.strip():
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                DealWin.full_name.ilike(s),
                DealWin.phone_number.ilike(s),
                DealWin.email.ilike(s),
                DealWin.care_by.ilike(s)
            )
        )

    # Đếm tổng số O(1) qua SQL count
    total = query.with_entities(func.count(DealWin.id)).scalar() or 0
    total_pages = (total + size - 1) // size if total > 0 else 1

    # Fetch các cột nhẹ với SQL LIMIT & OFFSET (bỏ qua raw_data)
    rows = query.with_entities(
        DealWin.id,
        DealWin.sheet_row_id,
        DealWin.timestamp,
        DealWin.email,
        DealWin.full_name,
        DealWin.phone_number,
        DealWin.birth_year,
        DealWin.address,
        DealWin.industry,
        DealWin.job_title,
        DealWin.expectation,
        DealWin.care_by,
        DealWin.is_student,
        DealWin.lead_tag,
        DealWin.dim_lead_id,
        DealWin.created_at
    ).order_by(desc(DealWin.timestamp)).offset((page - 1) * size).limit(size).all()

    items = [
        DealWinItem(
            id=r.id,
            sheet_row_id=r.sheet_row_id,
            timestamp=r.timestamp,
            email=r.email,
            full_name=r.full_name,
            phone_number=r.phone_number,
            birth_year=r.birth_year,
            address=r.address,
            industry=r.industry,
            job_title=r.job_title,
            expectation=r.expectation,
            care_by=r.care_by,
            is_student=r.is_student,
            lead_tag=r.lead_tag,
            dim_lead_id=r.dim_lead_id,
            raw_data=None,  # Tối ưu băng thông
            created_at=r.created_at
        )
        for r in rows
    ]

    return DealWinListResponse(
        total=total,
        page=page,
        size=size,
        total_pages=total_pages,
        data=items
    )

@app.get("/api/deals/{deal_id}", response_model=DealWinItem)
def get_deal_detail(deal_id: int, db: Session = Depends(get_db)):
    """Lấy chi tiết 1 Deal Win (bao gồm cả raw_data) chỉ khi người dùng click xem chi tiết modal."""
    deal = db.query(DealWin).filter(DealWin.id == deal_id).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal không tồn tại")
    return DealWinItem.from_orm(deal)




