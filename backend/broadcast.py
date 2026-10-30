"""
================================================================================
ROUTER QUẢN LÝ GỬI TIN NHẮN HÀNG LOẠT (BROADCAST / AUTO-MESSENGER)
Hỗ trợ:
1. Bộ lọc chuẩn xác 100% (Kênh Nguồn/Zalo, Nhân viên, Giới tính, Tags, SĐT,
   Thời gian tương tác cuối / Remind, Tìm kiếm Tên/SĐT không dấu).
2. Cơ chế chống Rate Limit & Bảo vệ khóa nick chuyên biệt cho Zalo Cá Nhân
   (Random Jitter Delay, Batch Cooldown nghỉ theo chặng, Spintax đa dạng nội dung,
   Adaptive Backoff & Circuit Breaker).
3. Quản lý & đồng bộ Pancake Token trực tiếp trên giao diện Web + Neon DB.
================================================================================
"""

import os
import re
import json
import time
import random
import logging
import threading
import unicodedata
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple, Set, Iterable, Union
from collections import defaultdict

from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc, func

from database.db import get_db, SessionLocal
from database.models import DimLead, FactLeadActivity, BotAutoReplyLog, AppConfig
from etl.pancake_client import PancakeClient, _PAGE_TOKEN_CACHE, _TOKEN_CACHE_LOCK
from etl.pipeline import (
    load_pancake_pages_config,
    get_token_for_page,
    sync_tokens_to_db,
    load_tokens_from_db,
)
from etl.utils import (
    VN_TZ,
    is_page_id,
    resolve_canonical_page_name,
    KNOWN_PAGE_NAMES,
    ZALO_PAGE_NAMES,
    PAGE_NAME_TO_API_ID,
    resolve_api_page_id,
    is_zalo_channel,
    zalo_page_keys,
    build_pancake_url,
)

logger = logging.getLogger("BroadcastAPI")

router = APIRouter()


def get_vn_now() -> datetime:
    return datetime.now(VN_TZ).replace(tzinfo=None)


def normalize_nfc(text: Optional[str]) -> str:
    """Chuẩn hóa Unicode NFC và chuyển về chữ thường."""
    if not text:
        return ""
    return unicodedata.normalize("NFC", str(text)).strip().lower()


def strip_accents(text: Optional[str]) -> str:
    """Khử dấu tiếng Việt phục vụ tìm kiếm tên khách không dấu."""
    if not text:
        return ""
    s = unicodedata.normalize("NFD", str(text))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D")
    return unicodedata.normalize("NFC", s).lower().strip()


# ==============================================================================
# 1. BỘ SUY LUẬN GIỚI TÍNH TỰ ĐỘNG THEO TÊN TIẾNG VIỆT & SPINTAX ENGINE
# ==============================================================================
FEMALE_KEYWORDS = {
    "thị", "thi", "hương", "huong", "mai", "ngọc", "ngoc", "lan", "hằng", "hang",
    "hà", "ha", "trang", "thảo", "thao", "quỳnh", "quynh", "nhi", "phương", "phuong",
    "linh", "nhung", "yến", "yen", "dung", "hạnh", "hanh", "loan", "trâm", "tram",
    "hiền", "hien", "nga", "tuyết", "tuyet", "hoa", "liên", "lien", "diệu", "dieu",
    "huyền", "huyen", "châu", "chau", "vi", "thủy", "thuy", "nhài", "nhai", "bích",
    "bich", "thoa", "thu", "vân", "van", "uyên", "uyen", "oanh", "mơ", "ly", "vy",
    "hồng", "hong", "thắm", "tham", "mỹ", "my", "khánh", "giang", "ngân", "ngan",
    "thúy", "thuy", "tâm", "nhàn", "nhan", "diễm", "diem", "kiều", "kieu", "phượng"
}

MALE_KEYWORDS = {
    "văn", "van", "đức", "duc", "minh", "hùng", "hung", "dũng", "dung", "tuấn", "tuan",
    "hoàng", "hoang", "trọng", "trong", "hải", "hai", "long", "quân", "quan", "bảo",
    "bao", "thành", "thanh", "cường", "cuong", "nam", "thắng", "thang", "sơn", "son",
    "tùng", "tung", "phúc", "phuc", "tiến", "tien", "nguyên", "nguyen",
    "trung", "kiên", "kien", "việt", "viet", "quang", "khoa", "trường", "truong", "đăng",
    "dang", "huy", "đạt", "dat", "khôi", "khoi", "bách", "bach", "bình", "binh", "bắc",
    "bac", "chí", "chi", "hiếu", "hieu", "trí", "tri", "lâm", "lam", "thịnh", "thinh",
    "khải", "khai", "phong", "phát", "phat", "vũ", "vu", "hào", "hao", "toàn", "toan"
}


def infer_vietnamese_gender(name: Optional[str]) -> str:
    """
    Suy luận giới tính từ họ và tên tiếng Việt:
    - 'female': Nữ
    - 'male': Nam
    - 'unknown': Chưa rõ
    """
    if not name or not name.strip():
        return "unknown"

    words = [w.lower().strip() for w in re.split(r"[\s_\-.,()]+", name.strip()) if w.strip()]
    if not words:
        return "unknown"

    # Ưu tiên từ đệm
    if len(words) >= 2:
        middle = words[-2]
        if middle in ("thị", "thi", "ngọc", "bích", "diệu", "thúy", "mỹ"):
            return "female"
        if middle in ("văn", "van", "đức", "duc", "hữu", "huu", "đình", "dinh", "mạnh", "manh"):
            return "male"

    # Kiểm tra tên chính (từ cuối cùng)
    last_word = words[-1]
    if last_word in (
        "hương", "ngọc", "lan", "hằng", "thảo", "quỳnh", "nhi", "linh", "yến",
        "loan", "trâm", "nga", "tuyết", "hoa", "trang", "mai", "huyền", "nhung",
        "hạnh", "hiền", "liên", "diệu", "thủy", "bích", "vân", "uyên", "oanh", "vy", "ly"
    ):
        return "female"
    if last_word in (
        "hùng", "dũng", "tuấn", "cường", "thắng", "sơn", "tùng", "kiên", "đăng",
        "huy", "đạt", "khôi", "bách", "nam", "long", "quân", "thành", "tiến",
        "trung", "quang", "khoa", "trường", "hiếu", "thịnh", "phong", "phát"
    ):
        return "male"

    for w in reversed(words):
        if w in FEMALE_KEYWORDS and w not in MALE_KEYWORDS:
            return "female"
        if w in MALE_KEYWORDS and w not in FEMALE_KEYWORDS:
            return "male"

    return "unknown"


def get_gender_title(gender: str) -> Tuple[str, str]:
    """Trả về (Title viết hoa, Title viết thường)."""
    if gender == "male":
        return "Anh", "anh"
    elif gender == "female":
        return "Chị", "chị"
    return "Anh/Chị", "anh/chị"


SPINTAX_PATTERN = re.compile(r"\{([^{}]*\|[^{}]*)\}")

ZALO_SAFE_SUFFIXES = ["", " ạ", " nhé ạ", ".", "!", " ạ!", " nha"]


def process_spintax(text: str) -> str:
    """Xử lý cú pháp Spintax {Chào|Xin chào|Dạ chào} ngẫu nhiên."""
    if not text:
        return ""

    def _replace(match):
        options = [opt.strip() for opt in match.group(1).split("|") if opt.strip()]
        return random.choice(options) if options else ""

    # Hỗ trợ lồng nhau tối đa 3 cấp
    result = text
    for _ in range(3):
        if not SPINTAX_PATTERN.search(result):
            break
        result = SPINTAX_PATTERN.sub(_replace, result)
    return result


def render_personalized_template(
    template: str,
    recipient: Dict[str, Any],
    enable_spintax: bool = True,
    anti_spam_variation: bool = False,
) -> str:
    """Thay thế các biến động và Spintax vào mẫu tin nhắn."""
    gender = recipient.get("gender") or infer_vietnamese_gender(recipient.get("name"))
    title_cap, title_lower = get_gender_title(gender)

    raw_name = (recipient.get("name") or "").strip()
    cust_name = raw_name if raw_name and raw_name.lower() != "unknown" else title_lower

    canonical_page = resolve_canonical_page_name(recipient.get("page_id"), fallback=str(recipient.get("page_id") or ""))

    msg = template.replace("{name}", cust_name)
    msg = msg.replace("{gender_title}", title_cap)
    msg = msg.replace("{gender_title_lower}", title_lower)
    msg = msg.replace("{phone}", recipient.get("phone_number") or "")
    msg = msg.replace("{customer_id}", str(recipient.get("customer_id") or ""))
    msg = msg.replace("{page_id}", canonical_page)
    msg = msg.replace("{staff}", str(recipient.get("assigned_users") or "Chăm sóc khách hàng"))

    if enable_spintax:
        msg = process_spintax(msg)

    msg = msg.strip()

    # Nếu gửi trên Zalo cá nhân và bật chống trùng lặp chữ ký tin nhắn (anti_spam_variation):
    # thêm khoảng trắng vô hình / biến thiên nhẹ cuối câu để mỗi tin nhắn có hash khác nhau
    if anti_spam_variation and msg:
        zwsp = "\u200b" * random.randint(0, 3)
        msg = f"{msg}{zwsp}"

    return msg


# ==============================================================================
# 2. PYDANTIC SCHEMAS CHO SETTINGS, TOKEN VÀ LỊCH SỬ
# ==============================================================================
class BroadcastOptionsResponse(BaseModel):
    pages: List[str]
    source_pages: List[str]
    zalo_pages: List[str]
    employees: List[str]
    employees_by_page: Dict[str, List[str]] = Field(default_factory=dict)
    tags: List[str]
    tags_by_page: Dict[str, List[str]] = Field(default_factory=dict)
    gender_options: List[Dict[str, str]]
    has_token_configured: bool = False
    configured_pages_count: int = 0


class BroadcastPreviewRequest(BaseModel):
    page_id: Optional[str] = "all"
    name_filter: Optional[str] = None
    employee: Optional[str] = "all"
    gender: Optional[str] = "all"  # 'all', 'male', 'female', 'unknown'
    tag: Optional[Union[List[str], str]] = "all"
    tags: Optional[List[str]] = None
    time_filter: Optional[str] = "all"  # 'all', '1', '3', '7', '30', 'remind_1_3', 'remind_4_7', 'remind_over_7'
    days_ago: Optional[int] = None      # Tương thích ngược
    phone_filter: Optional[str] = "all"  # 'all', 'has_phone', 'no_phone'
    limit: int = 50
    template: str = "{Chào|Xin chào|Dạ chào} {gender_title} {name}, bên em gửi {gender_title_lower} thông tin ưu đãi mới nhất ạ!"
    exclude_already_sent: bool = True
    exclude_students: bool = True
    campaign_name: Optional[str] = None


class BroadcastRecipientItem(BaseModel):
    lead_id: int
    customer_id: str
    conversation_id: str
    name: str
    gender: str
    gender_title: str
    phone_number: Optional[str] = None
    page_id: str
    api_page_id: Optional[str] = None
    is_zalo: bool = False
    status_tag: Optional[str] = None
    assigned_users: Optional[str] = None
    rendered_message: str
    first_created_at: Optional[str] = None
    last_contacted_at: Optional[str] = None
    days_since_contact: Optional[float] = None
    pancake_url: Optional[str] = None


class BroadcastPreviewResponse(BaseModel):
    total_matching: int
    limit: int
    zalo_count: int = 0
    recipients: List[BroadcastRecipientItem]


class BroadcastStartRequest(BaseModel):
    campaign_name: str
    template: str
    page_id: Optional[str] = "all"
    name_filter: Optional[str] = None
    employee: Optional[str] = "all"
    gender: Optional[str] = "all"
    tag: Optional[Union[List[str], str]] = "all"
    tags: Optional[List[str]] = None
    time_filter: Optional[str] = "all"
    days_ago: Optional[int] = None
    phone_filter: Optional[str] = "all"
    limit: int = 50
    delay: float = 1.5
    dry_run: bool = True
    exclude_already_sent: bool = True
    exclude_students: bool = True
    target_conversation_ids: Optional[List[str]] = None
    # Cấu hình chuyên biệt chống Rate Limit & khóa tài khoản Zalo cá nhân
    zalo_protection: bool = True
    zalo_min_delay: float = 8.0
    zalo_max_delay: float = 15.0
    zalo_batch_size: int = 10
    zalo_batch_pause: float = 45.0
    enable_spintax: bool = True
    max_consecutive_errors: int = 5
    custom_token: Optional[str] = None


class BroadcastStatusResponse(BaseModel):
    task_id: str
    campaign_name: str
    is_running: bool
    total: int
    processed: int
    success: int
    failed: int
    dry_run: bool
    current_recipient: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    logs: List[Dict[str, Any]] = []


class BroadcastHistoryItem(BaseModel):
    id: int
    campaign_name: str
    conversation_id: str
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    phone_number: Optional[str] = None
    page_id: str
    message: str
    status: str
    error_message: Optional[str] = None
    sent_at: str
    pancake_url: Optional[str] = None


class BroadcastCampaignSummary(BaseModel):
    campaign_name: str
    page_id: Optional[str] = None
    total_messages: int
    success_count: int
    failed_count: int
    dry_run_count: int
    first_sent_at: Optional[str] = None
    last_sent_at: Optional[str] = None
    status: str


_CANDIDATES_CACHE_LOCK = threading.RLock()
_CANDIDATES_CACHE_DATA: Optional[List[Any]] = None
_CANDIDATES_CACHE_TIME: float = 0.0
_CANDIDATES_CACHE_TTL: float = 900.0  # Cache in-memory 15 phút (tiết kiệm 99% băng thông Neon Egress)

def clear_broadcast_cache():
    """Xoá cache dữ liệu Broadcast."""
    global _CANDIDATES_CACHE_DATA, _CANDIDATES_CACHE_TIME, _OPTIONS_CACHE_DATA, _OPTIONS_CACHE_TIME
    with _CANDIDATES_CACHE_LOCK:
        _CANDIDATES_CACHE_DATA = None
        _CANDIDATES_CACHE_TIME = 0.0
    with _OPTIONS_CACHE_LOCK:
        _OPTIONS_CACHE_DATA = None
        _OPTIONS_CACHE_TIME = 0.0


class TokenConfigRequest(BaseModel):
    default_token: Optional[str] = None
    pages_json: Optional[str] = None


# ==============================================================================
# 3. ENGINE BỘ LỌC TRUNG TÂM (CHUẨN XÁC 100% CHO PREVIEW & WORKER)
# ==============================================================================
def _filter_broadcast_candidates(
    db: Session,
    page_id: Optional[str] = "all",
    name_filter: Optional[str] = None,
    employee: Optional[str] = "all",
    gender: Optional[str] = "all",
    tag: Optional[Union[List[str], str]] = "all",
    tags: Optional[List[str]] = None,
    time_filter: Optional[str] = "all",
    days_ago: Optional[int] = None,
    phone_filter: Optional[str] = "all",
    exclude_already_sent: bool = True,
    exclude_students: bool = True,
    campaign_name: Optional[str] = None,
    target_conversation_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Truy vấn và lọc danh sách khách hàng thỏa mãn điều kiện.
    Loại bỏ hoàn toàn nhóm chat Zalo (pzl_g_%), chuẩn hóa Unicode NFC,
    hỗ trợ lọc Kênh nguồn / Zalo, Tag, Nhân viên, SĐT, Thời gian tương tác cuối, và Giới tính.
    """
    now_vn = get_vn_now()

    query = db.query(
        DimLead.id.label("lead_id"),
        DimLead.customer_id,
        DimLead.name,
        DimLead.phone_number,
        DimLead.page_id,
        DimLead.first_created_at,
        FactLeadActivity.conversation_id,
        FactLeadActivity.status_tag,
        FactLeadActivity.assigned_users,
        FactLeadActivity.contacted_at,
    ).join(
        FactLeadActivity, DimLead.id == FactLeadActivity.lead_id
    ).filter(
        ~FactLeadActivity.conversation_id.like("pzl_g_%")
    )

    # 1. Nếu có danh sách target_conversation_ids (Custom List do người dùng chọn)
    if target_conversation_ids:
        clean_cids = [str(cid).strip() for cid in target_conversation_ids if cid and str(cid).strip()]
        if clean_cids:
            rows = query.filter(FactLeadActivity.conversation_id.in_(clean_cids)).all()
            row_by_conv = {}
            for r in rows:
                cid = str(r.conversation_id) if r.conversation_id else None
                if cid and cid not in row_by_conv:
                    row_by_conv[cid] = r

            custom_results = []
            for cid in clean_cids:
                r = row_by_conv.get(cid)
                if not r:
                    continue
                raw_tags = (r.status_tag or "").strip()
                raw_tags_lower = raw_tags.lower()
                if exclude_students and any(s in raw_tags_lower for s in ("đã là học viên", "da la hoc vien")):
                    continue
                inferred_gen = infer_vietnamese_gender(r.name)
                canonical_pg = resolve_canonical_page_name(r.page_id, fallback=str(r.page_id or ""))
                api_pid = resolve_api_page_id(r.page_id, cid)
                is_zalo = is_zalo_channel(r.page_id, cid)
                last_dt = r.contacted_at or r.first_created_at or now_vn
                diff_days = round(max(0.0, (now_vn - last_dt).total_seconds()) / 86400.0, 1)

                custom_results.append({
                    "lead_id": r.lead_id,
                    "customer_id": r.customer_id,
                    "conversation_id": cid,
                    "name": r.name or "Khách hàng",
                    "gender": inferred_gen,
                    "phone_number": r.phone_number or "",
                    "page_id": canonical_pg,
                    "api_page_id": api_pid,
                    "is_zalo": is_zalo,
                    "status_tag": r.status_tag or "",
                    "assigned_users": r.assigned_users or "Chưa phân công",
                    "first_created_at": r.first_created_at,
                    "contacted_at": last_dt,
                    "days_since_contact": diff_days,
                })
            return custom_results

    # 2. Sắp xếp ưu tiên khách tương tác gần nhất lên đầu
    global _CANDIDATES_CACHE_DATA, _CANDIDATES_CACHE_TIME
    now_ts = time.time()
    with _CANDIDATES_CACHE_LOCK:
        if _CANDIDATES_CACHE_DATA is not None and (now_ts - _CANDIDATES_CACHE_TIME < _CANDIDATES_CACHE_TTL):
            all_rows = _CANDIDATES_CACHE_DATA
        else:
            all_rows = query.order_by(
                func.coalesce(FactLeadActivity.contacted_at, DimLead.first_created_at).desc()
            ).all()
            _CANDIDATES_CACHE_DATA = all_rows
            _CANDIDATES_CACHE_TIME = now_ts

    # Tập hợp các conversation_id đã gửi thành công trong chiến dịch này
    already_sent_convs: Set[str] = set()
    if exclude_already_sent and campaign_name and campaign_name.strip():
        sent_logs = db.query(BotAutoReplyLog.conversation_id).filter(
            BotAutoReplyLog.case_id == campaign_name.strip(),
            BotAutoReplyLog.status == "SENT"
        ).all()
        already_sent_convs = {str(r[0]) for r in sent_logs if r[0]}

    # Chuẩn bị tham số lọc
    clean_page_filter = (page_id or "all").strip()
    target_canonical_page = None
    target_api_page_id = None
    target_clean_num = None
    possible_pids_lower: Set[str] = set()

    if clean_page_filter not in ("all", "all_zalo", "all_source", ""):
        target_canonical_page = resolve_canonical_page_name(clean_page_filter, fallback=clean_page_filter)
        target_api_page_id = resolve_api_page_id(clean_page_filter)
        raw_pids = {clean_page_filter, target_canonical_page}
        if target_api_page_id:
            raw_pids.add(target_api_page_id)
            cnum = re.sub(r"^(pzl_|tt_|fb_)", "", target_api_page_id)
            if cnum:
                raw_pids.add(cnum)
                target_clean_num = cnum.lower()
        for k, v in KNOWN_PAGE_NAMES.items():
            if v == target_canonical_page or k == clean_page_filter:
                raw_pids.add(k)
                raw_pids.add(v)
        possible_pids_lower = {str(p).strip().lower() for p in raw_pids if p}

    emp_norm = normalize_nfc(employee) if (employee and employee.strip() and employee.strip() != "all") else None
    # Chuẩn hóa danh sách thẻ lọc (hỗ trợ chọn 1 hoặc nhiều tag)
    active_tags: List[str] = []
    if tags:
        active_tags = [str(t).strip() for t in tags if t and str(t).strip() and str(t).strip() != "all"]
    elif isinstance(tag, list):
        active_tags = [str(t).strip() for t in tag if t and str(t).strip() and str(t).strip() != "all"]
    elif isinstance(tag, str) and tag.strip() and tag.strip() != "all":
        active_tags = [t.strip() for t in tag.split(",") if t.strip() and t.strip() != "all"]

    tag_clean_lowers: List[str] = [normalize_nfc(t).strip().lower() for t in active_tags]
    allow_no_tag = any(t in ("no_tag", "chưa gắn thẻ", "chưa gắn tag", "chua gan tag", "không có tag") for t in tag_clean_lowers)
    target_tags_lower = [t for t in tag_clean_lowers if t not in ("no_tag", "chưa gắn thẻ", "chưa gắn tag", "chua gan tag", "không có tag")]
    gender_clean = (gender or "all").strip().lower()
    phone_clean = (phone_filter or "all").strip().lower()

    # Xác định bộ lọc thời gian (ưu tiên time_filter, fallback sang days_ago nếu truyền số)
    tf = (time_filter or "").strip().lower()
    if (not tf or tf == "all") and days_ago is not None and days_ago > 0:
        tf = str(days_ago)

    search_norm = normalize_nfc(name_filter) if (name_filter and name_filter.strip()) else None
    search_no_accents = strip_accents(name_filter) if search_norm else None

    seen_convs: Set[str] = set()
    matched_results: List[Dict[str, Any]] = []

    for r in all_rows:
        conv_id = str(r.conversation_id or "").strip()
        if not conv_id or conv_id.startswith("pzl_g_") or conv_id in seen_convs:
            continue

        if exclude_already_sent and conv_id in already_sent_convs:
            continue

        is_zalo = is_zalo_channel(r.page_id, conv_id)
        canonical_pg = resolve_canonical_page_name(r.page_id, fallback=str(r.page_id or ""))
        api_pid = resolve_api_page_id(r.page_id, conv_id)

        # 2.1. Lọc theo Kênh (Page)
        if clean_page_filter == "all_zalo":
            if not is_zalo:
                continue
        elif clean_page_filter == "all_source":
            if is_zalo:
                continue
        elif clean_page_filter not in ("all", ""):
            r_page_str = str(r.page_id or "").strip().lower()
            canon_lower = canonical_pg.lower()
            api_pid_lower = (api_pid or "").lower()

            page_matched = (
                r_page_str in possible_pids_lower
                or canon_lower in possible_pids_lower
                or (api_pid_lower and api_pid_lower in possible_pids_lower)
            )
            # Nếu DimLead.page_id lưu tên kênh nguồn ban đầu nhưng hội thoại thực tế thuộc kênh Zalo này
            if not page_matched and target_clean_num and target_clean_num in conv_id.lower():
                page_matched = True

            if not page_matched:
                continue

        # 2.2. Lọc theo Nhân viên (Employee - Không phân biệt hoa thường)
        raw_assigned = (r.assigned_users or "").strip()
        if emp_norm:
            emp_clean_lower = emp_norm.strip().lower()
            if emp_clean_lower in ("chưa phân công", "chua phan cong", "unassigned", "chua_phan_cong"):
                if raw_assigned and raw_assigned.lower() not in ("chưa phân công", "chua phan cong", "unassigned"):
                    continue
            else:
                raw_assigned_lower = raw_assigned.lower()
                emp_list = [normalize_nfc(u).strip().lower() for u in raw_assigned.split(",") if u.strip()]
                matched_emp = (
                    emp_clean_lower in raw_assigned_lower
                    or any(emp_clean_lower == u or emp_clean_lower in u for u in emp_list)
                    or any(u in emp_clean_lower for u in emp_list if len(u) >= 3)
                )
                if not matched_emp:
                    continue

        raw_tags = (r.status_tag or "").strip()
        raw_tags_lower = raw_tags.lower()

        # 2.25. Chốt chặn Bỏ qua học viên nếu bật exclude_students
        if exclude_students:
            if any(s in raw_tags_lower for s in ("đã là học viên", "da la hoc vien")):
                continue

        # 2.3. Lọc theo Thẻ (Tag - Không phân biệt hoa thường, hỗ trợ chọn nhiều tag, khớp bất kỳ)
        if tag_clean_lowers:
            matched_tag = False
            if allow_no_tag and (not raw_tags or raw_tags_lower in ("no_tag", "chưa gắn thẻ", "không có tag")):
                matched_tag = True
            elif target_tags_lower and raw_tags:
                tag_list = [normalize_nfc(t).strip().lower() for t in raw_tags.split(",") if t.strip()]
                for target_t in target_tags_lower:
                    if (
                        target_t in raw_tags_lower
                        or any(target_t == t or target_t in t for t in tag_list)
                        or any(t in target_t for t in tag_list if len(t) >= 3)
                    ):
                        matched_tag = True
                        break
            if not matched_tag:
                continue

        # 2.4. Lọc theo SĐT (Phone Filter)
        has_phone_val = bool(
            (r.phone_number and str(r.phone_number).strip())
            or ("đã add" in raw_tags.lower() or "da add" in raw_tags.lower())
        )
        if phone_clean == "has_phone" and not has_phone_val:
            continue
        elif phone_clean == "no_phone" and has_phone_val:
            continue

        # 2.5. Lọc theo Thời gian tương tác gần nhất (Time Filter)
        last_dt = r.contacted_at or r.first_created_at or now_vn
        if hasattr(last_dt, "tzinfo") and last_dt.tzinfo is not None:
            last_dt = last_dt.astimezone(VN_TZ).replace(tzinfo=None)

        diff_sec = max(0.0, (now_vn - last_dt).total_seconds())
        days_float = round(diff_sec / 86400.0, 1)
        days_int = int(diff_sec // 86400.0)

        if tf and tf != "all":
            if tf in ("today", "0"):
                if days_int != 0:
                    continue
            elif tf in ("remind_1_3", "1_to_3", "1_3"):
                if not (1 <= days_int <= 3):
                    continue
            elif tf in ("remind_4_7", "3_to_7", "4_to_7", "4_7"):
                if not (4 <= days_int <= 7):
                    continue
            elif tf in ("remind_over_7", "over_7", ">7"):
                if days_int <= 7:
                    continue
            elif tf == "7":
                if diff_sec > 7 * 86400.0:
                    continue
            elif tf == "30":
                if diff_sec > 30 * 86400.0:
                    continue
            elif tf == "60":
                if diff_sec > 60 * 86400.0:
                    continue
            elif tf == "90":
                if diff_sec > 90 * 86400.0:
                    continue
            elif tf.isdigit():
                max_days = int(tf)
                if diff_sec > max_days * 86400.0:
                    continue

        # 2.6. Lọc theo Tìm kiếm Tên khách / SĐT / Mã hội thoại (Hỗ trợ cả có dấu & không dấu)
        if search_norm:
            cust_name_norm = normalize_nfc(r.name)
            cust_name_no_acc = strip_accents(r.name)
            cust_phone = str(r.phone_number or "").strip().lower()
            if not (
                search_norm in cust_name_norm
                or (search_no_accents and search_no_accents in cust_name_no_acc)
                or search_norm in cust_phone
                or search_norm in conv_id.lower()
            ):
                continue

        # 2.7. Lọc theo Giới tính
        inferred_gen = infer_vietnamese_gender(r.name)
        if gender_clean != "all" and inferred_gen != gender_clean:
            continue

        seen_convs.add(conv_id)
        matched_results.append({
            "lead_id": r.lead_id,
            "customer_id": r.customer_id,
            "conversation_id": conv_id,
            "name": r.name or "Khách hàng",
            "gender": inferred_gen,
            "phone_number": r.phone_number or "",
            "page_id": canonical_pg,
            "api_page_id": api_pid,
            "is_zalo": is_zalo,
            "status_tag": raw_tags,
            "assigned_users": raw_assigned or "Chưa phân công",
            "first_created_at": r.first_created_at,
            "contacted_at": last_dt,
            "days_since_contact": days_float,
        })

    return matched_results


# ==============================================================================
# 4. QUẢN LÝ TÁC VỤ BACKGROUND BROADCAST & CHỐNG RATE LIMIT ZALO CÁ NHÂN
# ==============================================================================
_BROADCAST_TASKS: Dict[str, Dict[str, Any]] = {}
_BROADCAST_LOCK = threading.Lock()


def _sleep_with_cancel_check(task_id: str, seconds: float, status_prefix: Optional[str] = None) -> bool:
    """
    Nghỉ an toàn theo từng nhịp 0.5s để vừa cập nhật countdown lên giao diện,
    vừa cho phép người dùng bấm 'Dừng khẩn cấp' bất kỳ lúc nào mà không bị treo.
    Trả về False nếu tác vụ bị hủy.
    """
    remaining = max(0.0, float(seconds))
    while remaining > 0:
        with _BROADCAST_LOCK:
            task = _BROADCAST_TASKS.get(task_id)
            if not task or not task.get("is_running"):
                return False
            if status_prefix:
                task["current_recipient"] = f"{status_prefix} (còn {int(remaining)}s)"
        step = min(0.5, remaining)
        time.sleep(step)
        remaining -= step
    return True


def _run_broadcast_worker(task_id: str, req_data: Dict[str, Any]):
    """Luồng worker thực thi gửi tin hàng loạt với cơ chế bảo vệ chống khóa Zalo cá nhân."""
    db = SessionLocal()
    clients_by_token: Dict[str, PancakeClient] = {}

    try:
        campaign_name = req_data["campaign_name"].strip()
        template = req_data["template"]
        limit = int(req_data.get("limit", 50))
        base_delay = max(0.5, float(req_data.get("delay", 1.5)))
        dry_run = bool(req_data.get("dry_run", True))
        exclude_already_sent = bool(req_data.get("exclude_already_sent", True))

        # Cấu hình bảo vệ Zalo cá nhân
        zalo_protection = bool(req_data.get("zalo_protection", True))
        zalo_min_delay = max(2.0, float(req_data.get("zalo_min_delay", 8.0)))
        zalo_max_delay = max(zalo_min_delay + 1.0, float(req_data.get("zalo_max_delay", 15.0)))
        zalo_batch_size = max(3, int(req_data.get("zalo_batch_size", 10)))
        zalo_batch_pause = max(10.0, float(req_data.get("zalo_batch_pause", 45.0)))
        enable_spintax = bool(req_data.get("enable_spintax", True))
        max_consecutive_errors = max(2, int(req_data.get("max_consecutive_errors", 5)))
        custom_token = (req_data.get("custom_token") or "").strip() or None

        # 1. Lấy danh sách khách hàng qua bộ lọc chuẩn
        all_matched = _filter_broadcast_candidates(
            db=db,
            page_id=req_data.get("page_id"),
            name_filter=req_data.get("name_filter"),
            employee=req_data.get("employee"),
            gender=req_data.get("gender"),
            tag=req_data.get("tag"),
            tags=req_data.get("tags"),
            time_filter=req_data.get("time_filter"),
            days_ago=req_data.get("days_ago"),
            phone_filter=req_data.get("phone_filter"),
            exclude_already_sent=exclude_already_sent,
            exclude_students=bool(req_data.get("exclude_students", True)),
            campaign_name=campaign_name,
            target_conversation_ids=req_data.get("target_conversation_ids"),
        )

        recipients = all_matched[:limit] if not req_data.get("target_conversation_ids") else all_matched

        with _BROADCAST_LOCK:
            if task_id in _BROADCAST_TASKS:
                _BROADCAST_TASKS[task_id]["total"] = len(recipients)

        zalo_sent_count = 0
        consecutive_failures = 0

        # 2. Duyệt gửi từng tin nhắn
        for index, rec in enumerate(recipients, 1):
            with _BROADCAST_LOCK:
                task = _BROADCAST_TASKS.get(task_id)
                if not task or not task.get("is_running"):
                    logger.info(f"Broadcast task {task_id} đã dừng theo yêu cầu người dùng.")
                    break
                channel_badge = "Zalo" if rec.get("is_zalo") else "Fanpage"
                task["current_recipient"] = f"[{index}/{len(recipients)}] Đang gửi ({channel_badge}): {rec.get('name')} ({rec['conversation_id']})"

            is_zalo = bool(rec.get("is_zalo"))
            personalized_msg = render_personalized_template(
                template=template,
                recipient=rec,
                enable_spintax=enable_spintax,
                anti_spam_variation=(is_zalo and zalo_protection),
            )
            conv_id = rec["conversation_id"]
            display_page = rec["page_id"]
            api_page_id = rec.get("api_page_id") or resolve_api_page_id(display_page, conv_id)

            log_status = "SENT"
            err_msg = None

            if dry_run:
                log_status = "DRY_RUN"
                res = {"success": True, "message": "[DRY-RUN] Giả lập gửi thành công"}
                time.sleep(0.15)
            else:
                # Tra cứu đúng Token cho Page hiện tại
                page_tok = custom_token or get_token_for_page(api_page_id, conv_id)
                if not page_tok:
                    log_status = "FAILED"
                    err_msg = (
                        f"Chưa cấu hình Pancake Token cho kênh '{display_page}' ({api_page_id}). "
                        f"Hãy bấm nút 'Cấu hình Token Pancake' ở góc trên để nhập Token."
                    )
                else:
                    if page_tok not in clients_by_token:
                        clients_by_token[page_tok] = PancakeClient(api_token=page_tok)
                    client = clients_by_token[page_tok]

                    res = client.send_message(
                        page_id=api_page_id,
                        conversation_id=conv_id,
                        message=personalized_msg,
                        action="reply_inbox",
                    )
                    if not res.get("success"):
                        log_status = "FAILED"
                        err_msg = res.get("message") or res.get("message_code") or "Lỗi gửi tin qua Pancake API"

            # Lưu lịch sử vào bảng bot_auto_replies
            try:
                log_entry = BotAutoReplyLog(
                    conversation_id=conv_id,
                    customer_id=rec.get("customer_id"),
                    page_id=display_page,
                    case_id=campaign_name,
                    customer_message=f"[BROADCAST] {rec.get('status_tag') or ''}",
                    reply_message=personalized_msg,
                    sent_at=get_vn_now(),
                    status=log_status,
                    error_message=err_msg,
                )
                db.add(log_entry)
                db.commit()
            except Exception as dbe:
                db.rollback()
                logger.warning(f"Lỗi khi lưu log broadcast vào DB: {dbe}")

            # Cập nhật tiến trình task
            with _BROADCAST_LOCK:
                if task_id in _BROADCAST_TASKS:
                    t = _BROADCAST_TASKS[task_id]
                    t["processed"] += 1
                    if log_status in ("SENT", "DRY_RUN"):
                        t["success"] += 1
                    else:
                        t["failed"] += 1

                    t["logs"].append({
                        "index": index,
                        "customer_name": rec.get("name") or "N/A",
                        "phone_number": rec.get("phone_number") or "N/A",
                        "conversation_id": conv_id,
                        "page_id": display_page,
                        "status": log_status,
                        "error_message": err_msg,
                        "time": get_vn_now().strftime("%H:%M:%S"),
                    })
                    if len(t["logs"]) > 100:
                        t["logs"] = t["logs"][-100:]

            # 3. Xử lý chống Rate Limit & Bảo vệ tài khoản sau mỗi tin gửi thật
            if not dry_run:
                if log_status == "SENT":
                    consecutive_failures = 0
                    if is_zalo:
                        zalo_sent_count += 1
                else:
                    consecutive_failures += 1
                    # Kiểm tra Circuit Breaker (ngắt tự động nếu lỗi liên tiếp vượt ngưỡng)
                    if consecutive_failures >= max_consecutive_errors:
                        logger.warning(
                            f"[CIRCUIT BREAKER] Dừng chiến dịch '{campaign_name}' do lỗi liên tiếp {consecutive_failures} lần: {err_msg}"
                        )
                        with _BROADCAST_LOCK:
                            if task_id in _BROADCAST_TASKS:
                                _BROADCAST_TASKS[task_id]["logs"].append({
                                    "index": index,
                                    "customer_name": "HỆ THỐNG BẢO VỆ",
                                    "phone_number": "-",
                                    "conversation_id": "CIRCUIT_BREAKER",
                                    "page_id": display_page,
                                    "status": "FAILED",
                                    "error_message": f"Đã tự động ngắt an toàn sau {consecutive_failures} lần lỗi liên tiếp để bảo vệ tài khoản ({err_msg})",
                                    "time": get_vn_now().strftime("%H:%M:%S"),
                                })
                        break

                    # Nếu lỗi liên quan đến Rate Limit / Spam (429), nghỉ hạ nhiệt 45s
                    if err_msg and any(w in err_msg.lower() for w in ("429", "rate limit", "too many", "spam", "block", "hạn chế")):
                        if index < len(recipients):
                            if not _sleep_with_cancel_check(task_id, 45.0, "⚠️ Phát hiện cảnh báo Rate Limit - Đang nghỉ hạ nhiệt"):
                                break

                # Giãn cách trước khi gửi khách tiếp theo
                if index < len(recipients):
                    if is_zalo and zalo_protection:
                        # Kiểm tra nghỉ giải lao theo chặng (Batch Cooldown)
                        if zalo_sent_count > 0 and zalo_sent_count % zalo_batch_size == 0:
                            cooldown_sec = random.uniform(zalo_batch_pause, zalo_batch_pause * 1.25)
                            logger.info(f"[ZALO ANTI-BAN] Đã gửi {zalo_sent_count} tin Zalo. Nghỉ giải lao {cooldown_sec:.0f}s...")
                            if not _sleep_with_cancel_check(
                                task_id,
                                cooldown_sec,
                                f"☕ Nghỉ giải lao bảo vệ Zalo sau {zalo_sent_count} tin"
                            ):
                                break
                        else:
                            jitter_sec = random.uniform(zalo_min_delay, zalo_max_delay)
                            if not _sleep_with_cancel_check(
                                task_id,
                                jitter_sec,
                                f"🛡️ Giãn cách an toàn Zalo ({jitter_sec:.1f}s)"
                            ):
                                break
                    else:
                        # Kênh Fanpage thông thường (Rate limit <= 5 req/s)
                        normal_wait = base_delay + random.uniform(0.2, 0.6)
                        if not _sleep_with_cancel_check(task_id, normal_wait, "⏳ Đang chờ gửi tin tiếp theo"):
                            break

    except Exception as e:
        logger.error(f"Lỗi ngoại lệ trong broadcast worker: {e}", exc_info=True)
    finally:
        with _BROADCAST_LOCK:
            if task_id in _BROADCAST_TASKS:
                t = _BROADCAST_TASKS[task_id]
                t["is_running"] = False
                t["current_recipient"] = None
                t["finished_at"] = get_vn_now().strftime("%Y-%m-%d %H:%M:%S")
        db.close()


# ==============================================================================
# 5. CÁC API ENDPOINTS
# ==============================================================================

# Bộ nhớ đệm in-memory cho options (giảm tối đa network transfer và query tới Neon)
_OPTIONS_CACHE_LOCK = threading.Lock()
_OPTIONS_CACHE_DATA: Optional[Dict[str, Any]] = None
_OPTIONS_CACHE_TIME: float = 0.0
_OPTIONS_CACHE_TTL: float = 300.0  # Tự động cache 5 phút


@router.get("/options", response_model=BroadcastOptionsResponse)
def get_broadcast_options(
    page_id: Optional[str] = Query(None, description="Lọc danh sách thẻ và nhân viên theo Kênh cụ thể"),
    refresh: bool = Query(False, description="Bắt buộc làm mới dữ liệu từ DB"),
    db: Session = Depends(get_db)
):
    """Lấy danh sách Kênh (tách rõ Nguồn & Zalo), Nhân viên, Tags (phân tách theo Kênh), Giới tính và trạng thái Token."""
    global _OPTIONS_CACHE_DATA, _OPTIONS_CACHE_TIME

    now_ts = time.time()
    with _OPTIONS_CACHE_LOCK:
        if not refresh and _OPTIONS_CACHE_DATA and (now_ts - _OPTIONS_CACHE_TIME < _OPTIONS_CACHE_TTL):
            cached = _OPTIONS_CACHE_DATA
            target_pg = (page_id or "all").strip()
            tags_by_page = cached["tags_by_page"]
            employees_by_page = cached["employees_by_page"]
            if target_pg in tags_by_page:
                sorted_tags = tags_by_page[target_pg]
                selected_employees = employees_by_page.get(target_pg, cached["employees"])
            else:
                c_target = resolve_canonical_page_name(target_pg, fallback=None)
                if c_target and c_target in tags_by_page:
                    sorted_tags = tags_by_page[c_target]
                    selected_employees = employees_by_page.get(c_target, cached["employees"])
                else:
                    sorted_tags = tags_by_page.get("all", cached["tags"])
                    selected_employees = employees_by_page.get("all", cached["employees"])

            return BroadcastOptionsResponse(
                pages=cached["pages"],
                source_pages=cached["source_pages"],
                zalo_pages=cached["zalo_pages"],
                employees=selected_employees,
                employees_by_page=employees_by_page,
                tags=sorted_tags,
                tags_by_page=tags_by_page,
                gender_options=cached["gender_options"],
                has_token_configured=cached["has_token_configured"],
                configured_pages_count=cached["configured_pages_count"],
            )

    # 1. Danh sách Pages
    page_results = db.query(DimLead.page_id).distinct().all()
    pages_set: Set[str] = set()
    for (pg,) in page_results:
        if pg:
            p_name = resolve_canonical_page_name(pg.strip(), fallback=None)
            if p_name and not is_page_id(p_name):
                pages_set.add(p_name)
    for known in set(KNOWN_PAGE_NAMES.values()):
        pages_set.add(known)

    sorted_pages = sorted(list(pages_set))
    zalo_pages = sorted([p for p in sorted_pages if p in ZALO_PAGE_NAMES])
    source_pages = sorted([p for p in sorted_pages if p not in ZALO_PAGE_NAMES])

    # 2. Danh sách Nhân viên (toàn bộ & phân bổ theo Kênh)
    # Lưu ý: Không select conversation_id để Postgres thực hiện DISTINCT gọn gàng, giảm 99% network transfer từ Neon
    emp_rows = db.query(
        DimLead.page_id,
        FactLeadActivity.assigned_users
    ).join(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id).filter(
        FactLeadActivity.assigned_users.isnot(None),
        FactLeadActivity.assigned_users != "",
    ).distinct().all()

    emp_map: Dict[str, Set[str]] = defaultdict(set)
    all_emp_set: Set[str] = set()
    zalo_emp_set: Set[str] = set()
    source_emp_set: Set[str] = set()

    for raw_pg, users in emp_rows:
        if not users:
            continue
        c_page = resolve_canonical_page_name(raw_pg, fallback=str(raw_pg or "").strip())
        is_zalo = is_zalo_channel(raw_pg)

        for u in users.split(","):
            u_clean = u.strip()
            if u_clean and u_clean != "Chưa phân công":
                all_emp_set.add(u_clean)
                if is_zalo:
                    zalo_emp_set.add(u_clean)
                else:
                    source_emp_set.add(u_clean)
                if c_page:
                    emp_map[c_page].add(u_clean)

    employees_by_page: Dict[str, List[str]] = {
        "all": ["Chưa phân công"] + sorted(list(all_emp_set)),
        "all_zalo": ["Chưa phân công"] + sorted(list(zalo_emp_set)),
        "all_source": ["Chưa phân công"] + sorted(list(source_emp_set)),
    }
    for pg in sorted_pages:
        employees_by_page[pg] = ["Chưa phân công"] + sorted(list(emp_map.get(pg, set())))
    sorted_employees = employees_by_page["all"]

    # 3. Danh sách Tags (toàn bộ & phân bổ chính xác theo từng Kênh)
    # Lưu ý: Bỏ conversation_id khỏi SELECT để Postgres trả về kết quả gom nhóm siêu nhẹ (~vài KB thay vì vài MB)
    tag_rows = db.query(
        DimLead.page_id,
        FactLeadActivity.status_tag
    ).join(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id).filter(
        FactLeadActivity.status_tag.isnot(None),
        FactLeadActivity.status_tag != "",
    ).distinct().all()

    priority_tags = ["Remind", "Đào tạo", "Lead Other", "Đã add", "Đã là học viên", "Có thông tin", "Quan tâm sâu"]

    def _sort_tags(tags: Iterable[str]) -> List[str]:
        t_set = set(tags)
        ordered = [pt for pt in priority_tags if pt in t_set]
        remaining = sorted([t for t in t_set if t not in ordered])
        return ordered + remaining

    tags_map: Dict[str, Set[str]] = defaultdict(set)
    all_tags_set: Set[str] = set()
    zalo_tags_set: Set[str] = set()
    source_tags_set: Set[str] = set()

    for raw_pg, t_str in tag_rows:
        if not t_str:
            continue
        c_page = resolve_canonical_page_name(raw_pg, fallback=str(raw_pg or "").strip())
        is_zalo = is_zalo_channel(raw_pg)

        for t in t_str.split(","):
            t_clean = t.strip()
            if t_clean:
                all_tags_set.add(t_clean)
                if is_zalo:
                    zalo_tags_set.add(t_clean)
                else:
                    source_tags_set.add(t_clean)
                if c_page:
                    tags_map[c_page].add(t_clean)

    tags_by_page: Dict[str, List[str]] = {
        "all": _sort_tags(all_tags_set),
        "all_zalo": _sort_tags(zalo_tags_set),
        "all_source": _sort_tags(source_tags_set),
    }
    for pg in sorted_pages:
        tags_by_page[pg] = _sort_tags(tags_map.get(pg, set()))

    gender_options = [
        {"value": "all", "label": "Tất cả giới tính"},
        {"value": "female", "label": "Nữ (Chào Chị)"},
        {"value": "male", "label": "Nam (Chào Anh)"},
        {"value": "unknown", "label": "Chưa rõ (Chào Anh/Chị)"},
    ]

    # Kiểm tra trạng thái Token Pancake
    pages_cfg = load_pancake_pages_config(sync_db=False)
    def_tok = get_token_for_page()
    has_tok = bool(def_tok or any(p.get("token") for p in pages_cfg))
    cfg_cnt = len([p for p in pages_cfg if p.get("token")]) or (7 if def_tok else 0)

    # Lưu vào bộ nhớ cache in-memory
    with _OPTIONS_CACHE_LOCK:
        _OPTIONS_CACHE_DATA = {
            "pages": sorted_pages,
            "source_pages": source_pages,
            "zalo_pages": zalo_pages,
            "employees": sorted_employees,
            "employees_by_page": employees_by_page,
            "tags": tags_by_page["all"],
            "tags_by_page": tags_by_page,
            "gender_options": gender_options,
            "has_token_configured": has_tok,
            "configured_pages_count": cfg_cnt,
        }
        _OPTIONS_CACHE_TIME = now_ts

    # Xác định danh sách tags và nhân viên được chọn (nếu có truyền query page_id)
    target_pg = (page_id or "all").strip()
    if target_pg and target_pg in tags_by_page:
        sorted_tags = tags_by_page[target_pg]
        selected_employees = employees_by_page.get(target_pg, sorted_employees)
    else:
        c_target = resolve_canonical_page_name(target_pg, fallback=None)
        if c_target and c_target in tags_by_page:
            sorted_tags = tags_by_page[c_target]
            selected_employees = employees_by_page.get(c_target, sorted_employees)
        else:
            sorted_tags = tags_by_page["all"]
            selected_employees = sorted_employees

    return BroadcastOptionsResponse(
        pages=sorted_pages,
        source_pages=source_pages,
        zalo_pages=zalo_pages,
        employees=selected_employees,
        employees_by_page=employees_by_page,
        tags=sorted_tags,
        tags_by_page=tags_by_page,
        gender_options=gender_options,
        has_token_configured=has_tok,
        configured_pages_count=cfg_cnt,
    )


@router.get("/token-status")
def get_token_status():
    """Kiểm tra trạng thái cấu hình Pancake API Token cho từng kênh."""
    pages_cfg = load_pancake_pages_config(sync_db=False)
    def_tok = get_token_for_page()

    channel_status = []
    for canonical_name in sorted(set(KNOWN_PAGE_NAMES.values())):
        api_pid = resolve_api_page_id(canonical_name)
        tok = get_token_for_page(canonical_name)
        masked = f"{tok[:6]}...{tok[-4:]}" if (tok and len(tok) > 12) else ("Đã có" if tok else None)
        channel_status.append({
            "page_name": canonical_name,
            "api_page_id": api_pid,
            "is_zalo": is_zalo_channel(canonical_name),
            "has_token": bool(tok),
            "masked_token": masked,
        })

    return {
        "has_token": bool(def_tok or any(c["has_token"] for c in channel_status)),
        "channels": channel_status,
    }


@router.post("/token-config")
def save_token_config(req: TokenConfigRequest):
    """Lưu Pancake API Token (hoặc JSON cấu hình các page) vào Database (app_configs) và xóa cache token."""
    default_tok = (req.default_token or "").strip() or None
    pages_json = (req.pages_json or "").strip() or None

    if not default_tok and not pages_json:
        raise HTTPException(status_code=400, detail="Vui lòng nhập Pancake Token hoặc cấu hình JSON.")

    pages_list = []
    if pages_json:
        from etl.pipeline import _parse_pages_config_raw
        pages_list = _parse_pages_config_raw(pages_json)
        if not pages_list and not pages_json.startswith(("{", "[")):
            # Nếu người dùng dán trực tiếp 1 chuỗi token vào ô JSON
            default_tok = pages_json

    if default_tok:
        os.environ["PANCAKE_API_TOKEN"] = default_tok

    sync_tokens_to_db(pages_list, default_tok)

    # Xóa cache token cũ để áp dụng ngay lập tức
    with _TOKEN_CACHE_LOCK:
        _PAGE_TOKEN_CACHE.clear()

    return {
        "status": "OK",
        "message": "Đã lưu cấu hình Pancake Token thành công vào hệ thống!",
        "token_status": get_token_status(),
    }


@router.post("/clear-failed")
def clear_failed_logs(campaign_name: Optional[str] = None, db: Session = Depends(get_db)):
    """Xóa các bản ghi gửi lỗi (FAILED) trong bảng bot_auto_replies để làm sạch lịch sử và gửi lại."""
    query = db.query(BotAutoReplyLog).filter(BotAutoReplyLog.status == "FAILED")
    if campaign_name and campaign_name != "all":
        query = query.filter(BotAutoReplyLog.case_id == campaign_name)
    deleted_count = query.delete(synchronize_session=False)
    db.commit()
    return {
        "status": "OK",
        "deleted_count": deleted_count,
        "message": f"Đã xóa {deleted_count} bản ghi lỗi (FAILED).",
    }


@router.post("/preview", response_model=BroadcastPreviewResponse)
def preview_broadcast(req: BroadcastPreviewRequest, db: Session = Depends(get_db)):
    """Xem trước danh sách khách hàng thỏa mãn bộ lọc và nội dung tin nhắn sau khi cá nhân hóa."""
    all_matched = _filter_broadcast_candidates(
        db=db,
        page_id=req.page_id,
        name_filter=req.name_filter,
        employee=req.employee,
        gender=req.gender,
        tag=req.tag,
        tags=req.tags,
        time_filter=req.time_filter,
        days_ago=req.days_ago,
        phone_filter=req.phone_filter,
        exclude_already_sent=req.exclude_already_sent,
        exclude_students=req.exclude_students,
        campaign_name=req.campaign_name,
    )

    total_matching = len(all_matched)
    selected_slice = all_matched[: req.limit]
    zalo_count = sum(1 for item in selected_slice if item.get("is_zalo"))

    recipients: List[BroadcastRecipientItem] = []
    for item in selected_slice:
        title_cap, _ = get_gender_title(item["gender"])
        rendered = render_personalized_template(req.template, item, enable_spintax=True)
        p_url = build_pancake_url(
            conversation_id=item["conversation_id"],
            customer_id=item["customer_id"],
            page_name_or_id=item["page_id"],
        )

        recipients.append(BroadcastRecipientItem(
            lead_id=item["lead_id"],
            customer_id=item["customer_id"],
            conversation_id=item["conversation_id"],
            name=item["name"],
            gender=item["gender"],
            gender_title=title_cap,
            phone_number=item["phone_number"] or None,
            page_id=item["page_id"],
            api_page_id=item["api_page_id"],
            is_zalo=item["is_zalo"],
            status_tag=item["status_tag"] or None,
            assigned_users=item["assigned_users"],
            rendered_message=rendered,
            first_created_at=item["first_created_at"].strftime("%Y-%m-%d %H:%M") if item.get("first_created_at") else None,
            last_contacted_at=item["contacted_at"].strftime("%Y-%m-%d %H:%M") if item.get("contacted_at") else None,
            days_since_contact=item.get("days_since_contact"),
            pancake_url=p_url,
        ))

    return BroadcastPreviewResponse(
        total_matching=total_matching,
        limit=req.limit,
        zalo_count=zalo_count,
        recipients=recipients,
    )


@router.post("/start")
def start_broadcast(req: BroadcastStartRequest, background_tasks: BackgroundTasks):
    """Bắt đầu chạy chiến dịch gửi tin hàng loạt trong nền (hỗ trợ cả Live và Dry-run)."""
    if not req.campaign_name or not req.campaign_name.strip():
        raise HTTPException(status_code=400, detail="Vui lòng đặt Tên chiến dịch.")
    if not req.template or not req.template.strip():
        raise HTTPException(status_code=400, detail="Vui lòng nhập Nội dung tin nhắn.")

    # Nếu gửi thật (dry_run=False), kiểm tra trước xem đã có Token chưa để báo lỗi ngay lập tức
    if not req.dry_run:
        has_any_token = bool(
            (req.custom_token and req.custom_token.strip())
            or get_token_for_page(req.page_id if req.page_id not in ("all", "all_zalo", "all_source") else None)
        )
        if not has_any_token:
            raise HTTPException(
                status_code=400,
                detail="Chưa có Pancake API Token trên hệ thống! Vui lòng bấm nút 'Cấu hình Token Pancake' trên giao diện để nhập Token trước khi Gửi thật."
            )

    task_id = f"task_{int(time.time())}_{random.randint(100, 999)}"

    task_state = {
        "task_id": task_id,
        "campaign_name": req.campaign_name.strip(),
        "is_running": True,
        "total": 0,
        "processed": 0,
        "success": 0,
        "failed": 0,
        "dry_run": req.dry_run,
        "current_recipient": "Đang khởi tạo danh sách người nhận...",
        "started_at": get_vn_now().strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": None,
        "logs": [],
    }

    with _BROADCAST_LOCK:
        _BROADCAST_TASKS[task_id] = task_state

    req_dict = req.dict() if hasattr(req, "dict") else req.model_dump()

    worker_thread = threading.Thread(
        target=_run_broadcast_worker,
        args=(task_id, req_dict),
        daemon=True,
    )
    worker_thread.start()

    logger.info(f"Đã khởi động Broadcast Task '{task_id}' (Chiến dịch: {req.campaign_name}, Dry-run: {req.dry_run})")
    return {"status": "STARTED", "task_id": task_id, "campaign_name": req.campaign_name}


@router.get("/status/{task_id}", response_model=BroadcastStatusResponse)
def get_broadcast_status(task_id: str):
    """Lấy tiến độ gửi tin real-time của một tác vụ đang chạy."""
    with _BROADCAST_LOCK:
        task = _BROADCAST_TASKS.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ gửi tin này.")
        return BroadcastStatusResponse(**task)


@router.post("/stop/{task_id}")
def stop_broadcast(task_id: str):
    """Dừng khẩn cấp tác vụ gửi tin đang chạy."""
    with _BROADCAST_LOCK:
        task = _BROADCAST_TASKS.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ.")
        task["is_running"] = False
    return {"status": "STOPPING", "task_id": task_id}


@router.get("/history")
def get_broadcast_history(
    campaign_name: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """
    Lấy lịch sử các chiến dịch đã chạy và chi tiết từng tin nhắn.
    """
    summary_rows = db.query(
        BotAutoReplyLog.case_id.label("campaign_name"),
        BotAutoReplyLog.page_id,
        BotAutoReplyLog.status,
        func.count(BotAutoReplyLog.id).label("cnt"),
        func.min(BotAutoReplyLog.sent_at).label("first_sent"),
        func.max(BotAutoReplyLog.sent_at).label("last_sent"),
    ).group_by(
        BotAutoReplyLog.case_id,
        BotAutoReplyLog.page_id,
        BotAutoReplyLog.status,
    ).order_by(desc(func.max(BotAutoReplyLog.sent_at))).all()

    campaigns_map: Dict[str, Dict[str, Any]] = {}
    for row in summary_rows:
        c_name = row.campaign_name or "unknown"
        if c_name not in campaigns_map:
            campaigns_map[c_name] = {
                "campaign_name": c_name,
                "pages": set(),
                "total_messages": 0,
                "success_count": 0,
                "failed_count": 0,
                "dry_run_count": 0,
                "first_sent_at": row.first_sent,
                "last_sent_at": row.last_sent,
            }
        item = campaigns_map[c_name]
        if row.page_id:
            item["pages"].add(resolve_canonical_page_name(str(row.page_id), fallback=str(row.page_id)))
        item["total_messages"] += row.cnt
        if row.status == "SENT":
            item["success_count"] += row.cnt
        elif row.status == "FAILED":
            item["failed_count"] += row.cnt
        elif row.status == "DRY_RUN":
            item["dry_run_count"] += row.cnt

        if row.first_sent and (not item["first_sent_at"] or row.first_sent < item["first_sent_at"]):
            item["first_sent_at"] = row.first_sent
        if row.last_sent and (not item["last_sent_at"] or row.last_sent > item["last_sent_at"]):
            item["last_sent_at"] = row.last_sent

    campaign_summaries: List[BroadcastCampaignSummary] = []
    for c_name, data in sorted(
        campaigns_map.items(),
        key=lambda x: x[1]["last_sent_at"] or datetime.min,
        reverse=True,
    ):
        pages_list = sorted(list(data["pages"]))
        page_label = ", ".join(pages_list[:2]) + (f" (+{len(pages_list)-2})" if len(pages_list) > 2 else "")

        overall_status = "COMPLETED"
        if data["dry_run_count"] == data["total_messages"]:
            overall_status = "DRY_RUN"
        elif data["failed_count"] > 0 and data["success_count"] == 0:
            overall_status = "FAILED"
        elif data["failed_count"] > 0:
            overall_status = "PARTIAL"

        campaign_summaries.append(BroadcastCampaignSummary(
            campaign_name=c_name,
            page_id=page_label or "Nhiều kênh",
            total_messages=data["total_messages"],
            success_count=data["success_count"],
            failed_count=data["failed_count"],
            dry_run_count=data["dry_run_count"],
            first_sent_at=data["first_sent_at"].strftime("%Y-%m-%d %H:%M:%S") if data["first_sent_at"] else None,
            last_sent_at=data["last_sent_at"].strftime("%Y-%m-%d %H:%M:%S") if data["last_sent_at"] else None,
            status=overall_status,
        ))

    log_query = db.query(
        BotAutoReplyLog,
        DimLead.name.label("lead_name"),
        DimLead.phone_number.label("lead_phone"),
    ).outerjoin(
        DimLead, BotAutoReplyLog.customer_id == DimLead.customer_id
    )

    if campaign_name and campaign_name != "all":
        log_query = log_query.filter(BotAutoReplyLog.case_id == campaign_name)

    recent_logs = log_query.order_by(BotAutoReplyLog.sent_at.desc()).limit(limit).all()

    history_items: List[BroadcastHistoryItem] = []
    for log_obj, l_name, l_phone in recent_logs:
        canonical_pg = resolve_canonical_page_name(log_obj.page_id, fallback=log_obj.page_id)
        p_url = build_pancake_url(
            conversation_id=log_obj.conversation_id,
            customer_id=log_obj.customer_id,
            page_name_or_id=log_obj.page_id,
        )
        history_items.append(BroadcastHistoryItem(
            id=log_obj.id,
            campaign_name=log_obj.case_id,
            conversation_id=log_obj.conversation_id,
            customer_id=log_obj.customer_id,
            customer_name=l_name or "Khách hàng",
            phone_number=l_phone,
            page_id=canonical_pg,
            message=log_obj.reply_message,
            status=log_obj.status,
            error_message=log_obj.error_message,
            sent_at=log_obj.sent_at.strftime("%Y-%m-%d %H:%M:%S") if log_obj.sent_at else "",
            pancake_url=p_url,
        ))

    return {
        "campaigns": campaign_summaries,
        "logs": history_items,
    }
