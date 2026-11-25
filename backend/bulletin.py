"""
Router FastAPI cho Trang Bản Tin Nội Bộ (EzTech - Data & Finance Service),
Đánh dấu đã đọc, Nhắc hẹn công việc (có lặp lại & snooze), Checklist hàng ngày (có rollover),
AI tách đầu việc từ bản tin (Gemini), và Bot nhắc Zalo (11h, 15h & đúng giờ).

Quyền riêng tư:
- Toàn bộ nhân sự xem được Bảng tin chung của 3 sếp (Ann, TRẦN HÀ TUẤN ANH, Hiền Minhh).
- Nhắc hẹn & Checklist công việc là RIÊNG TƯ theo từng nhân sự; chỉ Admin mới xem toàn bộ và phân việc.
"""

import hmac
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import case, desc, exists, func, or_
from sqlalchemy.orm import Session, joinedload, load_only

from backend.auth import require_admin, require_tab_access
from backend.bulletin_notifier import (
    dispatch_daily_digest,
    dispatch_due_exact_reminders,
    ensure_recurring_checklists_for_date,
    invalidate_exact_reminder_cache,
    send_test_zalo_to_staff,
)
from backend.rbac_config import get_user_permissions, strip_vn_accents
from database.db import get_db
from database.models import (
    AppUser,
    BulletinPost,
    BulletinRead,
    DailyChecklist,
    DailyChecklistItem,
    EztechStaff,
    WorkReminder,
    ZaloReminderLog,
    get_vn_now,
)
from etl.bulletin_sync import (
    get_bulletin_source_config,
    list_consultant_zalo_contacts,
    save_bulletin_source_config,
    sync_bulletin_from_group,
)
from etl.utils import normalize_phone

logger = logging.getLogger("BulletinAPI")

router = APIRouter(prefix="/api/bulletin", tags=["Bulletin"])

_SYNC_LOCK = threading.Lock()
_LAST_SYNC_AT = 0.0
_SYNC_COOLDOWN_SEC = 20.0

# In-memory TTL cache tối ưu Neon Egress cho thống kê tổng quan bản tin (5 phút)
_META_CACHE_LOCK = threading.Lock()
_POST_STATS_CACHE: Optional[Tuple[float, Dict[str, Any]]] = None
_POST_STATS_TTL = 300.0
_USER_READ_COUNT_CACHE: Dict[int, Tuple[float, int]] = {}
_USER_READ_COUNT_TTL = 60.0


def clear_bulletin_meta_cache():
    global _POST_STATS_CACHE
    with _META_CACHE_LOCK:
        _POST_STATS_CACHE = None
        _USER_READ_COUNT_CACHE.clear()


def _invalidate_user_read_count(user_id: int):
    with _META_CACHE_LOCK:
        _USER_READ_COUNT_CACHE.pop(user_id, None)


def _get_cached_user_read_count(db: Session, user_id: int) -> int:
    now_ts = time.time()
    with _META_CACHE_LOCK:
        cached = _USER_READ_COUNT_CACHE.get(user_id)
        if cached and (now_ts - cached[0] < _USER_READ_COUNT_TTL):
            return cached[1]
    cnt = int(db.query(func.count(BulletinRead.id)).filter(BulletinRead.user_id == user_id).scalar() or 0)
    with _META_CACHE_LOCK:
        if len(_USER_READ_COUNT_CACHE) > 200:
            _USER_READ_COUNT_CACHE.clear()
        _USER_READ_COUNT_CACHE[user_id] = (now_ts, cnt)
    return cnt


def _get_cached_post_stats(db: Session) -> Dict[str, Any]:
    global _POST_STATS_CACHE
    now_ts = time.time()
    with _META_CACHE_LOCK:
        if _POST_STATS_CACHE and (now_ts - _POST_STATS_CACHE[0] < _POST_STATS_TTL):
            return _POST_STATS_CACHE[1]

    rows = (
        db.query(BulletinPost.boss_key, func.count(BulletinPost.id))
        .group_by(BulletinPost.boss_key)
        .all()
    )
    boss_counts = {bk: int(c) for bk, c in rows}
    total_all = sum(boss_counts.values())
    data = {"total_all": total_all, "boss_counts": boss_counts}
    with _META_CACHE_LOCK:
        _POST_STATS_CACHE = (now_ts, data)
    return data


def _is_admin(user: AppUser) -> bool:
    return bool(get_user_permissions(user).get("is_admin"))


def _verify_cron_secret(request: Request):
    """Fail-closed: bắt buộc cấu hình WEBHOOK_SECRET hoặc ADMIN_SECRET_KEY trên production."""
    secret = os.getenv("WEBHOOK_SECRET", "").strip() or os.getenv("ADMIN_SECRET_KEY", "").strip()
    if not secret:
        if os.getenv("ALLOW_UNAUTHENTICATED_CRON", "").strip().lower() in ("true", "1", "yes"):
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cron endpoint bị khóa do chưa cấu hình WEBHOOK_SECRET trên server.",
        )
    token = (
        request.headers.get("X-Webhook-Secret")
        or request.headers.get("X-Admin-Secret")
        or request.query_params.get("secret")
        or ""
    ).strip()
    if not token or not hmac.compare_digest(token, secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Thiếu hoặc sai X-Webhook-Secret.",
        )


def _parse_dt(val: str) -> datetime:
    raw = (val or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Thời gian không được để trống.")
    cleaned = raw.replace("Z", "").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "")).replace(tzinfo=None)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Định dạng thời gian không hợp lệ: '{val}'.")


def _compute_next_recurrence(dt: datetime, rule: str) -> Optional[datetime]:
    if rule == "daily":
        return dt + timedelta(days=1)
    if rule == "weekly":
        return dt + timedelta(weeks=1)
    if rule == "monthly":
        return dt + relativedelta(months=1)
    return None


def _resolve_target_owner_ids(
    current_user: AppUser,
    is_adm: bool,
    owner_user_id: Optional[int],
    owner_user_ids: Optional[List[int]],
) -> List[int]:
    """Xác định danh sách owner_user_id hợp lệ (Nhân viên thường luôn bị khóa vào chính mình; Admin giao được 1 hoặc nhiều người)."""
    if not is_adm:
        return [current_user.id]
    ids: List[int] = []
    if owner_user_ids:
        for uid in owner_user_ids:
            if uid and int(uid) not in ids:
                ids.append(int(uid))
    if owner_user_id and int(owner_user_id) not in ids:
        ids.append(int(owner_user_id))
    return ids or [current_user.id]


# ==============================================================================
# PYDANTIC SCHEMAS
# ==============================================================================
class ReminderCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = None
    remind_at: str = Field(..., description="YYYY-MM-DDTHH:MM hoặc YYYY-MM-DD HH:MM")
    priority: str = Field(default="normal")  # low, normal, high, urgent
    recurrence_rule: str = Field(default="none")  # none, daily, weekly, monthly
    source_post_id: Optional[int] = None
    owner_user_id: Optional[int] = None  # Admin giao cho 1 nhân sự
    owner_user_ids: Optional[List[int]] = None  # Admin giao hàng loạt cho nhiều nhân sự
    notify_11h: bool = True
    notify_15h: bool = True
    notify_exact_time: bool = True


class ReminderUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=300)
    description: Optional[str] = None
    remind_at: Optional[str] = None
    priority: Optional[str] = None
    recurrence_rule: Optional[str] = None
    status: Optional[str] = None  # pending, completed, snoozed, cancelled
    notify_11h: Optional[bool] = None
    notify_15h: Optional[bool] = None
    notify_exact_time: Optional[bool] = None


class ChecklistCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    checklist_date: Optional[str] = None  # YYYY-MM-DD, mặc định hôm nay
    items: List[str] = Field(default_factory=list)
    source_post_id: Optional[int] = None
    owner_user_id: Optional[int] = None  # Admin giao cho 1 nhân sự
    owner_user_ids: Optional[List[int]] = None  # Admin giao hàng loạt cho nhiều nhân sự
    is_recurring_daily: bool = False


class ChecklistUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=300)
    is_recurring_daily: Optional[bool] = None


class ChecklistItemCreateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=1000)
    note: Optional[str] = None


class ChecklistItemUpdateRequest(BaseModel):
    content: Optional[str] = Field(default=None, max_length=1000)
    is_done: Optional[bool] = None
    note: Optional[str] = None


class RolloverChecklistRequest(BaseModel):
    target_date: Optional[str] = None
    item_ids: Optional[List[int]] = None  # Rỗng = chuyển toàn bộ việc chưa xong 3 ngày gần nhất
    title: Optional[str] = None


class StaffZaloUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    zalo_conversation_id: Optional[str] = None
    zalo_display_name: Optional[str] = None
    receive_daily_digest: bool = True
    is_active: bool = True


class SyncZaloContactsRequest(BaseModel):
    auto_apply: bool = True
    max_convs: int = Field(default=300, ge=20, le=1000)


class DispatchRequest(BaseModel):
    slot: str = Field(default="11h")  # 11h, 15h, exact, manual
    target_date: Optional[str] = None
    user_id: Optional[int] = None
    dry_run: bool = False
    force: bool = False


class BulletinConfigUpdateRequest(BaseModel):
    group_name: Optional[str] = None
    group_conversation_id: Optional[str] = None
    fetch_page_id: Optional[str] = None
    dashboard_url: Optional[str] = None
    active_weekdays: Optional[List[int]] = None
    group_merge_window_sec: Optional[int] = None
    boss_rules: Optional[Dict[str, Any]] = None


class TestZaloRequest(BaseModel):
    message: Optional[str] = None


# ==============================================================================
# 1. BẢNG TIN NHÓM EZTECH - DATA & FINANCE SERVICE
# ==============================================================================
@router.get("/unread-count")
def get_unread_count(
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    """Đếm nhanh số bản tin chưa đọc (tận dụng cache RAM stats + user_read_count)."""
    stats = _get_cached_post_stats(db)
    total_read = _get_cached_user_read_count(db, current_user.id)
    unread = max(0, int(stats["total_all"]) - int(total_read))
    return {"unread_count": int(unread), "total_posts": int(stats["total_all"])}


@router.get("/posts")
def list_bulletin_posts(
    boss_key: Optional[str] = Query(default="all", description="all | ann | tuan_anh | hien_minh"),
    read_status: Optional[str] = Query(default="all", description="all | unread | read"),
    search: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    """Lấy danh sách bản tin từ nhóm EzTech - Data & Finance Service (Column Projection, tối ưu Neon Egress)."""
    is_adm = _is_admin(current_user)
    query = db.query(BulletinPost).options(
        load_only(
            BulletinPost.id,
            BulletinPost.pancake_message_id,
            BulletinPost.group_name,
            BulletinPost.boss_key,
            BulletinPost.boss_display_name,
            BulletinPost.sender_name,
            BulletinPost.title,
            BulletinPost.content,
            BulletinPost.attachments,
            BulletinPost.posted_at,
            BulletinPost.is_pinned,
        )
    )

    if boss_key and boss_key.strip().lower() not in ("all", ""):
        query = query.filter(BulletinPost.boss_key == boss_key.strip().lower())

    if start_date and start_date.strip():
        s_dt = _parse_dt(f"{start_date.strip()} 00:00:00")
        query = query.filter(BulletinPost.posted_at >= s_dt)
    if end_date and end_date.strip():
        e_dt = _parse_dt(f"{end_date.strip()} 23:59:59")
        query = query.filter(BulletinPost.posted_at <= e_dt)

    if search and search.strip():
        kw = f"%{search.strip()}%"
        query = query.filter(
            or_(
                BulletinPost.title.ilike(kw),
                BulletinPost.content.ilike(kw),
                BulletinPost.boss_display_name.ilike(kw),
                BulletinPost.sender_name.ilike(kw),
            )
        )

    read_exists = exists().where(
        (BulletinRead.post_id == BulletinPost.id)
        & (BulletinRead.user_id == current_user.id)
    )
    if read_status == "read":
        query = query.filter(read_exists)
    elif read_status == "unread":
        query = query.filter(~read_exists)

    total = query.with_entities(func.count(BulletinPost.id)).scalar() or 0
    posts = (
        query.order_by(desc(BulletinPost.is_pinned), desc(BulletinPost.posted_at), desc(BulletinPost.id))
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    post_ids = [p.id for p in posts]
    my_reads_map: Dict[int, datetime] = {}
    read_counts_map: Dict[int, int] = {}
    my_rem_counts: Dict[int, int] = {}
    my_cl_counts: Dict[int, int] = {}

    if post_ids:
        for r_pid, cnt, my_at in (
            db.query(
                BulletinRead.post_id,
                func.count(BulletinRead.id),
                func.max(case((BulletinRead.user_id == current_user.id, BulletinRead.read_at), else_=None)),
            )
            .filter(BulletinRead.post_id.in_(post_ids))
            .group_by(BulletinRead.post_id)
            .all()
        ):
            read_counts_map[r_pid] = int(cnt)
            if my_at is not None:
                my_reads_map[r_pid] = my_at

        for sp_id, cnt in (
            db.query(WorkReminder.source_post_id, func.count(WorkReminder.id))
            .filter(
                WorkReminder.source_post_id.in_(post_ids),
                WorkReminder.owner_user_id == current_user.id,
            )
            .group_by(WorkReminder.source_post_id)
            .all()
        ):
            if sp_id:
                my_rem_counts[sp_id] = int(cnt)

        for sp_id, cnt in (
            db.query(DailyChecklist.source_post_id, func.count(DailyChecklist.id))
            .filter(
                DailyChecklist.source_post_id.in_(post_ids),
                DailyChecklist.owner_user_id == current_user.id,
                DailyChecklist.is_deleted == False,
            )
            .group_by(DailyChecklist.source_post_id)
            .all()
        ):
            if sp_id:
                my_cl_counts[sp_id] = int(cnt)

    # Dùng in-memory TTL cache cho total_all, boss_counts & user_read_count
    stats = _get_cached_post_stats(db)
    total_read = _get_cached_user_read_count(db, current_user.id)

    items = []
    for p in posts:
        read_at = my_reads_map.get(p.id)
        items.append({
            "id": p.id,
            "pancake_message_id": p.pancake_message_id,
            "group_name": p.group_name,
            "boss_key": p.boss_key,
            "boss_display_name": p.boss_display_name,
            "sender_name": p.sender_name,
            "title": p.title,
            "content": p.content,
            "attachments": p.attachments or [],
            "posted_at": p.posted_at.strftime("%Y-%m-%d %H:%M:%S") if p.posted_at else None,
            "is_pinned": bool(p.is_pinned),
            "is_read": read_at is not None,
            "read_at": read_at.strftime("%Y-%m-%d %H:%M:%S") if read_at else None,
            "read_count": read_counts_map.get(p.id, 0),
            "my_reminder_count": my_rem_counts.get(p.id, 0),
            "my_checklist_count": my_cl_counts.get(p.id, 0),
            "readers": None,
        })

    return {
        "total": int(total),
        "page": page,
        "size": size,
        "total_pages": max(1, (int(total) + size - 1) // size),
        "summary": {
            "total_all": int(stats["total_all"]),
            "unread_count": max(0, int(stats["total_all"]) - int(total_read)),
            "boss_counts": stats["boss_counts"],
        },
        "items": items,
    }


@router.post("/posts/{post_id}/read")
def mark_post_read(
    post_id: int,
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    post = db.query(BulletinPost.id).filter(BulletinPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản tin.")

    existing = (
        db.query(BulletinRead)
        .filter(BulletinRead.post_id == post_id, BulletinRead.user_id == current_user.id)
        .first()
    )
    if not existing:
        existing = BulletinRead(post_id=post_id, user_id=current_user.id, read_at=get_vn_now())
        db.add(existing)
        db.commit()
        db.refresh(existing)
        _invalidate_user_read_count(current_user.id)

    return {
        "status": "ok",
        "post_id": post_id,
        "is_read": True,
        "read_at": existing.read_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


@router.get("/posts/{post_id}/readers")
def get_post_readers(
    post_id: int,
    _: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Tải danh sách nhân sự đã đọc của 1 bản tin cụ thể khi Admin bấm mở (tối ưu tốc độ trang đầu)."""
    rows = (
        db.query(BulletinRead.user_id, AppUser.full_name, AppUser.username, BulletinRead.read_at)
        .join(AppUser, BulletinRead.user_id == AppUser.id)
        .filter(BulletinRead.post_id == post_id)
        .order_by(desc(BulletinRead.read_at))
        .all()
    )
    return {
        "post_id": post_id,
        "items": [
            {
                "user_id": r_uid,
                "full_name": (r_name or r_uname).strip(),
                "read_at": r_at.strftime("%Y-%m-%d %H:%M:%S") if r_at else None,
            }
            for r_uid, r_name, r_uname, r_at in rows
        ],
    }


@router.delete("/posts/{post_id}/read")
def unmark_post_read(
    post_id: int,
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    existing = (
        db.query(BulletinRead)
        .filter(BulletinRead.post_id == post_id, BulletinRead.user_id == current_user.id)
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()
        _invalidate_user_read_count(current_user.id)
    return {"status": "ok", "post_id": post_id, "is_read": False}


@router.post("/posts/{post_id}/pin")
def toggle_pin_post(
    post_id: int,
    _: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    post = db.query(BulletinPost).filter(BulletinPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản tin.")
    post.is_pinned = not bool(post.is_pinned)
    db.commit()
    clear_bulletin_meta_cache()
    return {"status": "ok", "post_id": post_id, "is_pinned": bool(post.is_pinned)}


@router.post("/posts/{post_id}/ai-extract")
def ai_extract_tasks_from_post(
    post_id: int,
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    """
    A2: Dùng Gemini AI bóc tách bản tin của sếp thành Checklist đầu việc & Gợi ý Nhắc hẹn.
    """
    post = (
        db.query(BulletinPost)
        .options(
            load_only(
                BulletinPost.id,
                BulletinPost.boss_display_name,
                BulletinPost.sender_name,
                BulletinPost.title,
                BulletinPost.content,
                BulletinPost.posted_at,
            )
        )
        .filter(BulletinPost.id == post_id)
        .first()
    )
    if not post:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản tin.")

    from backend.ai_rag import call_gemini_generate, get_gemini_api_key

    api_key = get_gemini_api_key(db)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="Chưa cấu hình GEMINI_API_KEY (hãy nhập ở tab Trợ Lý AI hoặc biến môi trường).",
        )

    now_vn = get_vn_now()
    system_prompt = (
        "Bạn là trợ lý phân tích chỉ đạo công việc nội bộ của EzTech.\n"
        "Hãy đọc bản tin của sếp và trả về DUY NHẤT một JSON object hợp lệ (không bọc markdown, không giải thích thêm) với cấu trúc:\n"
        "{\n"
        '  "summary": "Tóm tắt ngắn gọn 1 câu ý chính của bản tin",\n'
        '  "checklist_title": "Tiêu đề checklist ngắn gọn (<= 60 ký tự)",\n'
        '  "checklist_items": ["Đầu việc 1 cụ thể, bắt đầu bằng động từ", "Đầu việc 2..."],\n'
        '  "suggested_reminder": {\n'
        '    "title": "Tiêu đề nhắc hẹn",\n'
        '    "description": "Ghi chú ngắn",\n'
        '    "remind_at": "YYYY-MM-DDTHH:MM",\n'
        '    "priority": "low|normal|high|urgent"\n'
        "  } // hoặc null nếu bản tin hoàn toàn không có mốc giờ/deadline\n"
        "}\n"
        "Quy tắc:\n"
        "- Tách tối đa 8 đầu việc ngắn gọn, rõ ràng, hành động được ngay.\n"
        "- Nếu bản tin có mốc thời gian/deadline (vd: 'trước 17h hôm nay', 'thứ 6 tuần này', 'sáng mai'), "
        "tính chính xác thời điểm nhắc (trước deadline 30-60 phút nếu hợp lý) theo giờ Việt Nam (UTC+7).\n"
        "- Trả về tiếng Việt tự nhiên."
    )
    user_prompt = (
        f"Thời điểm hiện tại (giờ VN): {now_vn.strftime('%Y-%m-%d %H:%M')} (Thứ {now_vn.weekday() + 2 if now_vn.weekday() < 6 else 'CN'})\n"
        f"Người gửi: {post.sender_name or post.boss_display_name}\n"
        f"Thời điểm đăng: {post.posted_at.strftime('%Y-%m-%d %H:%M') if post.posted_at else ''}\n"
        f"Nội dung bản tin:\n{post.content[:3500]}"
    )

    raw_text, model_used, _ = call_gemini_generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        history=[],
        api_key=api_key,
        temperature=0.2,
        enable_search=False,
    )

    # Parse JSON an toàn (gỡ ```json ... ``` nếu model có bọc)
    cleaned = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    else:
        brace_match = re.search(r"(\{.*\})", cleaned, flags=re.DOTALL)
        if brace_match:
            cleaned = brace_match.group(1).strip()

    try:
        parsed = json.loads(cleaned)
    except Exception:
        parsed = {
            "summary": post.title or "Tóm tắt bản tin",
            "checklist_title": f"Việc từ {post.boss_display_name}",
            "checklist_items": [line.strip("- •").strip() for line in post.content.splitlines() if line.strip()][:5],
            "suggested_reminder": None,
        }

    items = [str(x).strip() for x in (parsed.get("checklist_items") or []) if str(x).strip()][:10]
    if not items and post.title:
        items = [post.title]

    sug_rem = parsed.get("suggested_reminder")
    clean_rem = None
    if isinstance(sug_rem, dict) and sug_rem.get("title"):
        rem_at_raw = str(sug_rem.get("remind_at") or "").strip()
        valid_rem_at = None
        if rem_at_raw:
            try:
                valid_rem_at = _parse_dt(rem_at_raw).strftime("%Y-%m-%dT%H:%M")
            except Exception:
                valid_rem_at = (now_vn + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        else:
            valid_rem_at = (now_vn + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        prio = str(sug_rem.get("priority") or "normal").lower()
        clean_rem = {
            "title": str(sug_rem["title"]).strip()[:280],
            "description": str(sug_rem.get("description") or "").strip()[:500],
            "remind_at": valid_rem_at,
            "priority": prio if prio in ("low", "normal", "high", "urgent") else "normal",
        }

    return {
        "post_id": post.id,
        "model": model_used,
        "summary": str(parsed.get("summary") or post.title or "").strip(),
        "checklist_title": str(parsed.get("checklist_title") or f"Việc từ {post.boss_display_name}").strip()[:120],
        "checklist_items": items,
        "suggested_reminder": clean_rem,
    }


@router.post("/sync")
def trigger_bulletin_sync(
    max_pages: int = Query(default=3, ge=1, le=20),
    force: bool = Query(default=False),
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    """Đồng bộ tin nhắn mới từ nhóm EzTech - Data & Finance Service qua Page Eztech Consultant."""
    global _LAST_SYNC_AT
    now_ts = time.time()
    is_adm = _is_admin(current_user)

    with _SYNC_LOCK:
        if not (force and is_adm) and (now_ts - _LAST_SYNC_AT < _SYNC_COOLDOWN_SEC):
            wait_sec = int(_SYNC_COOLDOWN_SEC - (now_ts - _LAST_SYNC_AT)) + 1
            return {
                "success": True,
                "throttled": True,
                "inserted": 0,
                "merged": 0,
                "message": f"Vừa đồng bộ xong, vui lòng đợi {wait_sec}s trước khi đồng bộ lại.",
            }
        _LAST_SYNC_AT = now_ts

    res = sync_bulletin_from_group(
        db=db,
        max_pages=max_pages if is_adm else min(max_pages, 3),
        force_full=bool(force and is_adm),
    )
    if res.get("inserted") or res.get("merged"):
        clear_bulletin_meta_cache()
    return res


# ==============================================================================
# 2. NHẮC HẸN CÔNG VIỆC (RIÊNG TƯ THEO NHÂN SỰ; ADMIN XEM & GIAO TOÀN BỘ)
# ==============================================================================
def _serialize_reminder(
    rem: WorkReminder,
    owner_name: Optional[str] = None,
    post_info: Optional[Tuple[str, str]] = None,
) -> Dict[str, Any]:
    return {
        "id": rem.id,
        "title": rem.title,
        "description": rem.description,
        "remind_at": rem.remind_at.strftime("%Y-%m-%dT%H:%M") if rem.remind_at else None,
        "remind_at_display": rem.remind_at.strftime("%d/%m/%Y %H:%M") if rem.remind_at else None,
        "due_date": rem.due_date,
        "priority": rem.priority,
        "recurrence_rule": rem.recurrence_rule or "none",
        "status": rem.status,
        "completed_at": rem.completed_at.strftime("%Y-%m-%d %H:%M:%S") if rem.completed_at else None,
        "source_post_id": rem.source_post_id,
        "source_post_title": post_info[0] if post_info else None,
        "source_post_boss": post_info[1] if post_info else None,
        "owner_user_id": rem.owner_user_id,
        "owner_name": owner_name,
        "notify_11h": bool(rem.notify_11h),
        "notify_15h": bool(rem.notify_15h),
        "notify_exact_time": bool(rem.notify_exact_time),
        "exact_notified_at": rem.exact_notified_at.strftime("%Y-%m-%d %H:%M:%S") if rem.exact_notified_at else None,
        "created_at": rem.created_at.strftime("%Y-%m-%d %H:%M:%S") if rem.created_at else None,
    }


@router.get("/reminders")
def list_reminders(
    status_filter: Optional[str] = Query(default="all", alias="status"),
    due_date: Optional[str] = None,
    source_post_id: Optional[int] = None,
    owner_user_id: Optional[int] = None,
    search: Optional[str] = None,
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    is_adm = _is_admin(current_user)
    query = db.query(WorkReminder, AppUser.full_name, AppUser.username).join(
        AppUser, WorkReminder.owner_user_id == AppUser.id
    )

    if not is_adm:
        query = query.filter(WorkReminder.owner_user_id == current_user.id)
    elif owner_user_id is not None:
        query = query.filter(WorkReminder.owner_user_id == owner_user_id)

    if status_filter and status_filter != "all":
        query = query.filter(WorkReminder.status == status_filter)
    if due_date and due_date.strip():
        query = query.filter(WorkReminder.due_date == due_date.strip())
    if source_post_id is not None:
        query = query.filter(WorkReminder.source_post_id == source_post_id)
    if search and search.strip():
        kw = f"%{search.strip()}%"
        query = query.filter(or_(WorkReminder.title.ilike(kw), WorkReminder.description.ilike(kw)))

    rows = query.order_by(
        WorkReminder.status.asc(),
        WorkReminder.remind_at.asc(),
        desc(WorkReminder.id),
    ).limit(300).all()

    post_ids = list({r.source_post_id for r, _, _ in rows if r.source_post_id})
    post_map: Dict[int, Tuple[str, str]] = {}
    if post_ids:
        for pid, ptitle, pboss in (
            db.query(BulletinPost.id, BulletinPost.title, BulletinPost.boss_display_name)
            .filter(BulletinPost.id.in_(post_ids))
            .all()
        ):
            post_map[pid] = (ptitle or "Bản tin", pboss or "")

    items = [
        _serialize_reminder(
            rem,
            owner_name=(u_name or u_uname or "").strip(),
            post_info=post_map.get(rem.source_post_id) if rem.source_post_id else None,
        )
        for rem, u_name, u_uname in rows
    ]
    return {"items": items, "total": len(items), "is_admin": is_adm}


@router.post("/reminders")
def create_reminder(
    req: ReminderCreateRequest,
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    is_adm = _is_admin(current_user)
    target_ids = _resolve_target_owner_ids(current_user, is_adm, req.owner_user_id, req.owner_user_ids)

    owners = (
        db.query(AppUser.id, AppUser.full_name, AppUser.username)
        .filter(AppUser.id.in_(target_ids), AppUser.is_active == True)
        .all()
    )
    owner_map = {oid: (fn or un).strip() for oid, fn, un in owners}
    if not owner_map:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhân sự được gán nhắc hẹn.")

    post_info = None
    if req.source_post_id:
        p = db.query(BulletinPost.title, BulletinPost.boss_display_name).filter(BulletinPost.id == req.source_post_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Bản tin liên kết không tồn tại.")
        post_info = (p[0] or "Bản tin", p[1] or "")

    remind_dt = _parse_dt(req.remind_at)
    prio = req.priority if req.priority in ("low", "normal", "high", "urgent") else "normal"
    rec_rule = req.recurrence_rule if req.recurrence_rule in ("none", "daily", "weekly", "monthly") else "none"

    created_objs: List[WorkReminder] = []
    now_vn = get_vn_now()
    for oid in target_ids:
        if oid not in owner_map:
            continue
        rem = WorkReminder(
            title=req.title.strip(),
            description=req.description.strip() if req.description else None,
            remind_at=remind_dt,
            due_date=remind_dt.strftime("%Y-%m-%d"),
            priority=prio,
            recurrence_rule=rec_rule,
            status="pending",
            source_post_id=req.source_post_id,
            owner_user_id=oid,
            created_by_user_id=current_user.id,
            notify_11h=req.notify_11h,
            notify_15h=req.notify_15h,
            notify_exact_time=req.notify_exact_time,
            exact_retry_count=0,
            created_at=now_vn,
            updated_at=now_vn,
        )
        db.add(rem)
        created_objs.append(rem)

    db.commit()
    for r in created_objs:
        db.refresh(r)
    invalidate_exact_reminder_cache()

    first_ser = _serialize_reminder(created_objs[0], owner_name=owner_map.get(created_objs[0].owner_user_id), post_info=post_info)
    first_ser["created_count"] = len(created_objs)
    return first_ser


@router.patch("/reminders/{reminder_id}")
def update_reminder(
    reminder_id: int,
    req: ReminderUpdateRequest,
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    rem = db.query(WorkReminder).filter(WorkReminder.id == reminder_id).first()
    if not rem:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhắc hẹn.")
    if not _is_admin(current_user) and rem.owner_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Bạn không có quyền chỉnh sửa nhắc hẹn của người khác.")

    prev_status = rem.status
    if req.title is not None and req.title.strip():
        rem.title = req.title.strip()
    if req.description is not None:
        rem.description = req.description.strip() or None
    if req.remind_at is not None:
        new_dt = _parse_dt(req.remind_at)
        if new_dt != rem.remind_at:
            rem.remind_at = new_dt
            rem.due_date = new_dt.strftime("%Y-%m-%d")
            rem.exact_notified_at = None
            rem.exact_retry_count = 0
            rem.exact_last_error_at = None
    if req.priority is not None and req.priority in ("low", "normal", "high", "urgent"):
        rem.priority = req.priority
    if req.recurrence_rule is not None and req.recurrence_rule in ("none", "daily", "weekly", "monthly"):
        rem.recurrence_rule = req.recurrence_rule
    if req.status is not None and req.status in ("pending", "completed", "snoozed", "cancelled"):
        rem.status = req.status
        rem.completed_at = get_vn_now() if req.status == "completed" else None
    if req.notify_11h is not None:
        rem.notify_11h = req.notify_11h
    if req.notify_15h is not None:
        rem.notify_15h = req.notify_15h
    if req.notify_exact_time is not None:
        rem.notify_exact_time = req.notify_exact_time

    # A4: Tự sinh nhắc hẹn kỳ tiếp theo khi hoàn thành 1 nhắc hẹn lặp lại
    next_rem_obj: Optional[WorkReminder] = None
    if prev_status != "completed" and rem.status == "completed" and (rem.recurrence_rule or "none") != "none":
        next_dt = _compute_next_recurrence(rem.remind_at, rem.recurrence_rule)
        if next_dt:
            next_rem_obj = WorkReminder(
                title=rem.title,
                description=rem.description,
                remind_at=next_dt,
                due_date=next_dt.strftime("%Y-%m-%d"),
                priority=rem.priority,
                recurrence_rule=rem.recurrence_rule,
                status="pending",
                source_post_id=rem.source_post_id,
                owner_user_id=rem.owner_user_id,
                created_by_user_id=rem.created_by_user_id,
                notify_11h=rem.notify_11h,
                notify_15h=rem.notify_15h,
                notify_exact_time=rem.notify_exact_time,
                exact_retry_count=0,
                created_at=get_vn_now(),
                updated_at=get_vn_now(),
            )
            db.add(next_rem_obj)

    rem.updated_at = get_vn_now()
    db.commit()
    db.refresh(rem)
    if next_rem_obj is not None:
        db.refresh(next_rem_obj)
    invalidate_exact_reminder_cache()

    owner = db.query(AppUser.full_name, AppUser.username).filter(AppUser.id == rem.owner_user_id).first()
    owner_name = (owner[0] or owner[1]).strip() if owner else None
    out = _serialize_reminder(rem, owner_name=owner_name)
    if next_rem_obj is not None:
        out["next_reminder"] = _serialize_reminder(next_rem_obj, owner_name=owner_name)
    return out


@router.delete("/reminders/{reminder_id}")
def delete_reminder(
    reminder_id: int,
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    rem = db.query(WorkReminder).filter(WorkReminder.id == reminder_id).first()
    if not rem:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhắc hẹn.")
    if not _is_admin(current_user) and rem.owner_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Bạn không có quyền xóa nhắc hẹn của người khác.")
    db.delete(rem)
    db.commit()
    invalidate_exact_reminder_cache()
    return {"status": "ok", "deleted_id": reminder_id}


# ==============================================================================
# 3. CHECKLIST CÔNG VIỆC HÀNG NGÀY (RIÊNG TƯ + ROLLOVER + ADMIN PHÂN VIỆC)
# ==============================================================================
def _serialize_checklist(
    cl: DailyChecklist,
    owner_name: Optional[str] = None,
    post_info: Optional[Tuple[str, str]] = None,
) -> Dict[str, Any]:
    items = [
        {
            "id": it.id,
            "checklist_id": it.checklist_id,
            "content": it.content,
            "is_done": bool(it.is_done),
            "done_at": it.done_at.strftime("%Y-%m-%d %H:%M:%S") if it.done_at else None,
            "sort_order": it.sort_order,
            "note": it.note,
        }
        for it in (cl.items or [])
    ]
    done_cnt = sum(1 for it in items if it["is_done"])
    total_cnt = len(items)
    return {
        "id": cl.id,
        "checklist_date": cl.checklist_date,
        "title": cl.title,
        "owner_user_id": cl.owner_user_id,
        "owner_name": owner_name,
        "source_post_id": cl.source_post_id,
        "source_post_title": post_info[0] if post_info else None,
        "source_post_boss": post_info[1] if post_info else None,
        "is_recurring_daily": bool(cl.is_recurring_daily),
        "recurring_template_id": cl.recurring_template_id,
        "done_count": done_cnt,
        "total_count": total_cnt,
        "progress_pct": round(done_cnt / total_cnt * 100) if total_cnt > 0 else 0,
        "items": items,
        "created_at": cl.created_at.strftime("%Y-%m-%d %H:%M:%S") if cl.created_at else None,
    }


@router.get("/checklists/pending-rollover")
def get_pending_rollover_items(
    target_date: Optional[str] = None,
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    """A3: Tìm các đầu việc checklist chưa hoàn thành trong 3 ngày gần nhất trước target_date của user."""
    date_str = (target_date or "").strip() or get_vn_now().strftime("%Y-%m-%d")
    try:
        t_dt = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Định dạng ngày không hợp lệ (YYYY-MM-DD).")
    lookback_str = (t_dt - timedelta(days=3)).strftime("%Y-%m-%d")

    # Dùng alias rõ ràng để kiểm tra item đã từng được chuyển tiếp chưa
    from sqlalchemy.orm import aliased
    rolled_alias = aliased(DailyChecklistItem)
    not_already_rolled = ~exists().where(rolled_alias.rolled_over_from_item_id == DailyChecklistItem.id)

    rows = (
        db.query(DailyChecklistItem, DailyChecklist.checklist_date, DailyChecklist.title)
        .join(DailyChecklist, DailyChecklistItem.checklist_id == DailyChecklist.id)
        .filter(
            DailyChecklist.owner_user_id == current_user.id,
            DailyChecklist.is_deleted == False,
            DailyChecklist.checklist_date >= lookback_str,
            DailyChecklist.checklist_date < date_str,
            DailyChecklistItem.is_done == False,
            not_already_rolled,
        )
        .order_by(desc(DailyChecklist.checklist_date), DailyChecklistItem.sort_order.asc(), DailyChecklistItem.id.asc())
        .limit(50)
        .all()
    )

    items = [
        {
            "id": it.id,
            "content": it.content,
            "from_date": c_date,
            "from_checklist_title": c_title,
        }
        for it, c_date, c_title in rows
    ]
    return {"target_date": date_str, "count": len(items), "items": items}


@router.post("/checklists/rollover")
def rollover_pending_items(
    req: RolloverChecklistRequest,
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    """A3: Chuyển tiếp các việc chưa hoàn thành từ hôm trước sang checklist hôm nay."""
    date_str = (req.target_date or "").strip() or get_vn_now().strftime("%Y-%m-%d")
    try:
        t_dt = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Định dạng ngày không hợp lệ.")
    lookback_str = (t_dt - timedelta(days=3)).strftime("%Y-%m-%d")

    from sqlalchemy.orm import aliased
    rolled_alias = aliased(DailyChecklistItem)
    not_already_rolled = ~exists().where(rolled_alias.rolled_over_from_item_id == DailyChecklistItem.id)

    q = (
        db.query(DailyChecklistItem, DailyChecklist.checklist_date)
        .join(DailyChecklist, DailyChecklistItem.checklist_id == DailyChecklist.id)
        .filter(
            DailyChecklist.owner_user_id == current_user.id,
            DailyChecklist.is_deleted == False,
            DailyChecklist.checklist_date >= lookback_str,
            DailyChecklist.checklist_date < date_str,
            DailyChecklistItem.is_done == False,
            not_already_rolled,
        )
    )
    if req.item_ids:
        q = q.filter(DailyChecklistItem.id.in_(req.item_ids))

    rows = q.order_by(DailyChecklist.checklist_date.asc(), DailyChecklistItem.sort_order.asc()).limit(50).all()
    if not rows:
        return {"status": "ok", "moved_count": 0, "message": "Không có đầu việc tồn đọng nào cần chuyển tiếp."}

    cl_title = (req.title or "").strip() or f"Việc chuyển tiếp sang {t_dt.strftime('%d/%m')}"
    new_cl = DailyChecklist(
        checklist_date=date_str,
        title=cl_title,
        owner_user_id=current_user.id,
        created_by_user_id=current_user.id,
        is_recurring_daily=False,
        is_deleted=False,
        created_at=get_vn_now(),
        updated_at=get_vn_now(),
    )
    db.add(new_cl)
    db.flush()

    for idx, (orig_item, orig_date) in enumerate(rows):
        db.add(
            DailyChecklistItem(
                checklist_id=new_cl.id,
                content=orig_item.content,
                is_done=False,
                sort_order=idx,
                note=f"Chuyển từ {orig_date}",
                rolled_over_from_item_id=orig_item.id,
                created_at=get_vn_now(),
            )
        )
    db.commit()
    cl_loaded = db.query(DailyChecklist).options(joinedload(DailyChecklist.items)).filter(DailyChecklist.id == new_cl.id).first()
    return {
        "status": "ok",
        "moved_count": len(rows),
        "checklist": _serialize_checklist(cl_loaded, owner_name=(current_user.full_name or current_user.username).strip()),
        "message": f"Đã chuyển tiếp {len(rows)} việc chưa xong sang ngày {t_dt.strftime('%d/%m')}.",
    }


@router.get("/checklists")
def list_checklists(
    checklist_date: Optional[str] = None,
    owner_user_id: Optional[int] = None,
    source_post_id: Optional[int] = None,
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    is_adm = _is_admin(current_user)
    target_date = (checklist_date or "").strip() or get_vn_now().strftime("%Y-%m-%d")

    # Chỉ tự sinh checklist lặp hàng ngày cho hôm nay / ngày mai (không ghi DB khi duyệt ngày cũ/tương lai xa)
    ensure_recurring_checklists_for_date(
        db,
        target_date=target_date,
        owner_user_id=None if is_adm else current_user.id,
        allow_any_date=False,
    )

    query = (
        db.query(DailyChecklist, AppUser.full_name, AppUser.username)
        .options(joinedload(DailyChecklist.items))
        .join(AppUser, DailyChecklist.owner_user_id == AppUser.id)
        .filter(
            DailyChecklist.checklist_date == target_date,
            DailyChecklist.is_deleted == False,
        )
    )

    if not is_adm:
        query = query.filter(DailyChecklist.owner_user_id == current_user.id)
    elif owner_user_id is not None:
        query = query.filter(DailyChecklist.owner_user_id == owner_user_id)

    if source_post_id is not None:
        query = query.filter(DailyChecklist.source_post_id == source_post_id)

    rows = query.order_by(desc(DailyChecklist.id)).all()

    post_ids = list({cl.source_post_id for cl, _, _ in rows if cl.source_post_id})
    post_map: Dict[int, Tuple[str, str]] = {}
    if post_ids:
        for pid, ptitle, pboss in (
            db.query(BulletinPost.id, BulletinPost.title, BulletinPost.boss_display_name)
            .filter(BulletinPost.id.in_(post_ids))
            .all()
        ):
            post_map[pid] = (ptitle or "Bản tin", pboss or "")

    serialized = [
        _serialize_checklist(
            cl,
            owner_name=(u_name or u_uname or "").strip(),
            post_info=post_map.get(cl.source_post_id) if cl.source_post_id else None,
        )
        for cl, u_name, u_uname in rows
    ]
    total_items = sum(c["total_count"] for c in serialized)
    done_items = sum(c["done_count"] for c in serialized)
    return {
        "checklist_date": target_date,
        "is_admin": is_adm,
        "summary": {
            "total_checklists": len(serialized),
            "total_items": total_items,
            "done_items": done_items,
            "pending_items": max(0, total_items - done_items),
        },
        "items": serialized,
    }


@router.post("/checklists")
def create_checklist(
    req: ChecklistCreateRequest,
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    is_adm = _is_admin(current_user)
    target_ids = _resolve_target_owner_ids(current_user, is_adm, req.owner_user_id, req.owner_user_ids)

    owners = (
        db.query(AppUser.id, AppUser.full_name, AppUser.username)
        .filter(AppUser.id.in_(target_ids), AppUser.is_active == True)
        .all()
    )
    owner_map = {oid: (fn or un).strip() for oid, fn, un in owners}
    if not owner_map:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhân sự sở hữu checklist.")

    post_info = None
    if req.source_post_id:
        p = db.query(BulletinPost.title, BulletinPost.boss_display_name).filter(BulletinPost.id == req.source_post_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Bản tin liên kết không tồn tại.")
        post_info = (p[0] or "Bản tin", p[1] or "")

    date_str = (req.checklist_date or "").strip() or get_vn_now().strftime("%Y-%m-%d")
    clean_items = [str(x).strip() for x in (req.items or []) if str(x).strip()]
    now_vn = get_vn_now()

    created_ids: List[int] = []
    for oid in target_ids:
        if oid not in owner_map:
            continue
        cl = DailyChecklist(
            checklist_date=date_str,
            title=req.title.strip(),
            owner_user_id=oid,
            created_by_user_id=current_user.id,
            source_post_id=req.source_post_id,
            is_recurring_daily=req.is_recurring_daily,
            is_deleted=False,
            created_at=now_vn,
            updated_at=now_vn,
        )
        db.add(cl)
        db.flush()
        for idx, content in enumerate(clean_items):
            db.add(
                DailyChecklistItem(
                    checklist_id=cl.id,
                    content=content,
                    is_done=False,
                    sort_order=idx,
                    created_at=now_vn,
                )
            )
        created_ids.append(cl.id)

    db.commit()
    cl_loaded = db.query(DailyChecklist).options(joinedload(DailyChecklist.items)).filter(DailyChecklist.id == created_ids[0]).first()
    res = _serialize_checklist(cl_loaded, owner_name=owner_map.get(cl_loaded.owner_user_id), post_info=post_info)
    res["created_count"] = len(created_ids)
    return res


@router.patch("/checklists/{checklist_id}")
def update_checklist(
    checklist_id: int,
    req: ChecklistUpdateRequest,
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    cl = db.query(DailyChecklist).options(joinedload(DailyChecklist.items)).filter(DailyChecklist.id == checklist_id, DailyChecklist.is_deleted == False).first()
    if not cl:
        raise HTTPException(status_code=404, detail="Không tìm thấy checklist.")
    if not _is_admin(current_user) and cl.owner_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Bạn không có quyền sửa checklist của người khác.")

    if req.title is not None and req.title.strip():
        cl.title = req.title.strip()
    if req.is_recurring_daily is not None:
        cl.is_recurring_daily = req.is_recurring_daily
    cl.updated_at = get_vn_now()
    db.commit()
    db.refresh(cl)
    owner = db.query(AppUser.full_name, AppUser.username).filter(AppUser.id == cl.owner_user_id).first()
    owner_name = (owner[0] or owner[1]).strip() if owner else None
    post_info = None
    if cl.source_post_id:
        p = db.query(BulletinPost.title, BulletinPost.boss_display_name).filter(BulletinPost.id == cl.source_post_id).first()
        if p:
            post_info = (p[0] or "Bản tin", p[1] or "")
    return _serialize_checklist(cl, owner_name=owner_name, post_info=post_info)


@router.delete("/checklists/{checklist_id}")
def delete_checklist(
    checklist_id: int,
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    cl = db.query(DailyChecklist).filter(DailyChecklist.id == checklist_id).first()
    if not cl:
        raise HTTPException(status_code=404, detail="Không tìm thấy checklist.")
    if not _is_admin(current_user) and cl.owner_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Bạn không có quyền xóa checklist của người khác.")

    # Nếu là bản sao lặp hàng ngày -> soft-delete để không bị tự động sinh lại khi F5 trong cùng ngày
    if cl.recurring_template_id:
        cl.is_deleted = True
        cl.updated_at = get_vn_now()
    else:
        db.delete(cl)
    db.commit()
    return {"status": "ok", "deleted_id": checklist_id}


@router.post("/checklists/{checklist_id}/items")
def add_checklist_item(
    checklist_id: int,
    req: ChecklistItemCreateRequest,
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    cl = db.query(DailyChecklist).filter(DailyChecklist.id == checklist_id, DailyChecklist.is_deleted == False).first()
    if not cl:
        raise HTTPException(status_code=404, detail="Không tìm thấy checklist.")
    if not _is_admin(current_user) and cl.owner_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Bạn không có quyền thêm việc vào checklist của người khác.")

    max_order = db.query(func.max(DailyChecklistItem.sort_order)).filter(DailyChecklistItem.checklist_id == checklist_id).scalar() or 0
    item = DailyChecklistItem(
        checklist_id=checklist_id,
        content=req.content.strip(),
        is_done=False,
        sort_order=int(max_order) + 1,
        note=req.note.strip() if req.note else None,
        created_at=get_vn_now(),
    )
    db.add(item)
    cl.updated_at = get_vn_now()
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "checklist_id": item.checklist_id,
        "content": item.content,
        "is_done": bool(item.is_done),
        "done_at": None,
        "sort_order": item.sort_order,
        "note": item.note,
    }


@router.patch("/checklists/items/{item_id}")
def update_checklist_item(
    item_id: int,
    req: ChecklistItemUpdateRequest,
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    item = (
        db.query(DailyChecklistItem)
        .join(DailyChecklist, DailyChecklistItem.checklist_id == DailyChecklist.id)
        .filter(DailyChecklistItem.id == item_id, DailyChecklist.is_deleted == False)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy hạng mục checklist.")
    if not _is_admin(current_user) and item.checklist.owner_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Bạn không có quyền cập nhật hạng mục của người khác.")

    if req.content is not None and req.content.strip():
        item.content = req.content.strip()
    if req.note is not None:
        item.note = req.note.strip() or None
    if req.is_done is not None:
        item.is_done = req.is_done
        item.done_at = get_vn_now() if req.is_done else None
    item.checklist.updated_at = get_vn_now()
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "checklist_id": item.checklist_id,
        "content": item.content,
        "is_done": bool(item.is_done),
        "done_at": item.done_at.strftime("%Y-%m-%d %H:%M:%S") if item.done_at else None,
        "sort_order": item.sort_order,
        "note": item.note,
    }


@router.delete("/checklists/items/{item_id}")
def delete_checklist_item(
    item_id: int,
    current_user: AppUser = Depends(require_tab_access("bulletin")),
    db: Session = Depends(get_db),
):
    item = (
        db.query(DailyChecklistItem)
        .join(DailyChecklist, DailyChecklistItem.checklist_id == DailyChecklist.id)
        .filter(DailyChecklistItem.id == item_id, DailyChecklist.is_deleted == False)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy hạng mục checklist.")
    if not _is_admin(current_user) and item.checklist.owner_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Bạn không có quyền xóa hạng mục của người khác.")
    db.delete(item)
    db.commit()
    return {"status": "ok", "deleted_id": item_id}


# ==============================================================================
# 4. QUẢN TRỊ NHÂN SỰ ZALO (EZTECH CONSULTANT), CẤU HÌNH & NHẮC VIỆC (ADMIN ONLY)
# ==============================================================================
@router.get("/admin/staff")
def admin_list_staff_zalo(
    _: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Liệt kê toàn bộ tài khoản nhân sự đang hoạt động kèm cấu hình Zalo nhận nhắc việc (Column Projection)."""
    rows = (
        db.query(
            AppUser.id,
            AppUser.username,
            AppUser.full_name,
            AppUser.department,
            AppUser.role,
            EztechStaff.id.label("staff_id"),
            EztechStaff.full_name.label("staff_name"),
            EztechStaff.phone_number,
            EztechStaff.zalo_conversation_id,
            EztechStaff.zalo_display_name,
            EztechStaff.receive_daily_digest,
            EztechStaff.is_active.label("staff_active"),
        )
        .outerjoin(EztechStaff, EztechStaff.user_id == AppUser.id)
        .filter(AppUser.is_active == True)
        .all()
    )
    items = []
    for r in rows:
        items.append({
            "user_id": r.id,
            "username": r.username,
            "full_name": (r.staff_name or r.full_name or r.username).strip(),
            "department": r.department,
            "role": r.role,
            "staff_id": r.staff_id,
            "phone_number": r.phone_number,
            "zalo_conversation_id": r.zalo_conversation_id,
            "zalo_display_name": r.zalo_display_name,
            "receive_daily_digest": bool(r.receive_daily_digest) if r.staff_id else True,
            "is_active": bool(r.staff_active) if r.staff_id else True,
        })
    items.sort(key=lambda x: (0 if x["role"] == "admin" else 1, strip_vn_accents(x["full_name"])))
    return {"items": items}


@router.put("/admin/staff/{user_id}")
def admin_update_staff_zalo(
    user_id: int,
    req: StaffZaloUpdateRequest,
    _: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(AppUser).filter(AppUser.id == user_id, AppUser.is_active == True).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản nhân viên.")

    staff = db.query(EztechStaff).filter(EztechStaff.user_id == user_id).first()
    clean_phone = normalize_phone(req.phone_number) if req.phone_number else None
    display_name = (req.full_name or user.full_name or user.username).strip()

    if not staff:
        staff = EztechStaff(
            user_id=user.id,
            full_name=display_name,
            phone_number=clean_phone,
            zalo_conversation_id=req.zalo_conversation_id.strip() if req.zalo_conversation_id else None,
            zalo_display_name=req.zalo_display_name.strip() if req.zalo_display_name else None,
            receive_daily_digest=req.receive_daily_digest,
            is_active=req.is_active,
            created_at=get_vn_now(),
            updated_at=get_vn_now(),
        )
        db.add(staff)
    else:
        staff.full_name = display_name
        staff.phone_number = clean_phone
        staff.zalo_conversation_id = req.zalo_conversation_id.strip() if req.zalo_conversation_id else None
        staff.zalo_display_name = req.zalo_display_name.strip() if req.zalo_display_name else None
        staff.receive_daily_digest = req.receive_daily_digest
        staff.is_active = req.is_active
        staff.updated_at = get_vn_now()

    db.commit()
    db.refresh(staff)
    invalidate_exact_reminder_cache()
    return {
        "status": "ok",
        "user_id": user.id,
        "staff_id": staff.id,
        "zalo_conversation_id": staff.zalo_conversation_id,
    }


@router.post("/admin/staff/sync-zalo-contacts")
def admin_sync_zalo_contacts(
    req: SyncZaloContactsRequest,
    _: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Quét hội thoại 1-1 trên Zalo Eztech Consultant và tự động gợi ý/khớp với AppUser."""
    res = list_consultant_zalo_contacts(max_convs=req.max_convs)
    contacts = res.get("contacts") or []

    users_rows = (
        db.query(AppUser, EztechStaff)
        .outerjoin(EztechStaff, EztechStaff.user_id == AppUser.id)
        .filter(AppUser.is_active == True)
        .all()
    )

    matched_count = 0
    if req.auto_apply and contacts:
        by_phone = {}
        by_name = {}
        for c in contacts:
            if c.get("phone_number"):
                by_phone.setdefault(c["phone_number"], []).append(c)
            acc = strip_vn_accents(c.get("display_name"))
            if acc:
                by_name.setdefault(acc, []).append(c)

        for user, staff in users_rows:
            if staff and staff.zalo_conversation_id:
                continue
            cand = None
            u_phone = normalize_phone(staff.phone_number) if (staff and staff.phone_number) else None
            if u_phone and len(by_phone.get(u_phone, [])) == 1:
                cand = by_phone[u_phone][0]
            else:
                u_acc = strip_vn_accents(user.full_name or user.username)
                if u_acc and len(by_name.get(u_acc, [])) == 1:
                    cand = by_name[u_acc][0]

            if cand:
                if not staff:
                    staff = EztechStaff(
                        user_id=user.id,
                        full_name=(user.full_name or user.username).strip(),
                        phone_number=cand.get("phone_number"),
                        zalo_conversation_id=cand["conversation_id"],
                        zalo_display_name=cand["display_name"],
                        receive_daily_digest=True,
                        is_active=True,
                        created_at=get_vn_now(),
                        updated_at=get_vn_now(),
                    )
                    db.add(staff)
                else:
                    staff.zalo_conversation_id = cand["conversation_id"]
                    staff.zalo_display_name = cand["display_name"]
                    if not staff.phone_number and cand.get("phone_number"):
                        staff.phone_number = cand.get("phone_number")
                    staff.updated_at = get_vn_now()
                matched_count += 1

        if matched_count > 0:
            db.commit()
            invalidate_exact_reminder_cache()

    return {
        "success": True,
        "contacts": contacts,
        "total_contacts": len(contacts),
        "auto_matched": matched_count,
        "message": f"Đã quét {len(contacts)} hội thoại 1-1 trên Eztech Consultant (tự động khớp {matched_count} nhân sự).",
    }


@router.post("/admin/staff/{user_id}/test-zalo")
def admin_test_staff_zalo(
    user_id: int,
    req: Optional[TestZaloRequest] = None,
    _: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return send_test_zalo_to_staff(db=db, user_id=user_id, custom_message=(req.message if req else None))


@router.get("/admin/config")
def admin_get_bulletin_config(
    _: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return get_bulletin_source_config(db)


@router.put("/admin/config")
def admin_update_bulletin_config(
    req: BulletinConfigUpdateRequest,
    _: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    cfg = get_bulletin_source_config(db)
    if req.group_name is not None and req.group_name.strip():
        cfg["group_name"] = req.group_name.strip()
    if req.group_conversation_id is not None:
        cfg["group_conversation_id"] = req.group_conversation_id.strip()
    if req.fetch_page_id is not None and req.fetch_page_id.strip():
        cfg["fetch_page_id"] = req.fetch_page_id.strip()
    if req.dashboard_url is not None:
        cfg["dashboard_url"] = req.dashboard_url.strip()
    if req.active_weekdays is not None:
        cfg["active_weekdays"] = sorted({int(d) for d in req.active_weekdays if 0 <= int(d) <= 6})
    if req.group_merge_window_sec is not None:
        cfg["group_merge_window_sec"] = max(0, min(900, int(req.group_merge_window_sec)))
    if req.boss_rules is not None:
        cfg["boss_rules"] = req.boss_rules
    return save_bulletin_source_config(db, cfg)


@router.post("/admin/dispatch")
def admin_dispatch_reminders(
    req: DispatchRequest,
    _: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if req.slot == "exact":
        return dispatch_due_exact_reminders(db=db, dry_run=req.dry_run)
    return dispatch_daily_digest(
        db=db,
        slot=req.slot,
        target_date=req.target_date,
        user_id=req.user_id,
        dry_run=req.dry_run,
        force=req.force,
    )


@router.get("/admin/logs")
def admin_list_zalo_logs(
    limit: int = Query(default=50, ge=1, le=200),
    _: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(
            ZaloReminderLog.id,
            ZaloReminderLog.dispatch_date,
            ZaloReminderLog.slot,
            ZaloReminderLog.user_id,
            ZaloReminderLog.conversation_id,
            ZaloReminderLog.done_count,
            ZaloReminderLog.pending_count,
            ZaloReminderLog.status,
            ZaloReminderLog.error_message,
            ZaloReminderLog.sent_at,
            AppUser.full_name,
            AppUser.username,
        )
        .outerjoin(AppUser, ZaloReminderLog.user_id == AppUser.id)
        .order_by(desc(ZaloReminderLog.sent_at), desc(ZaloReminderLog.id))
        .limit(limit)
        .all()
    )
    items = []
    for r in rows:
        items.append({
            "id": r.id,
            "dispatch_date": r.dispatch_date,
            "slot": r.slot,
            "user_id": r.user_id,
            "staff_name": (r.full_name or r.username or "N/A").strip(),
            "conversation_id": r.conversation_id,
            "done_count": r.done_count,
            "pending_count": r.pending_count,
            "status": r.status,
            "error_message": r.error_message,
            "sent_at": r.sent_at.strftime("%Y-%m-%d %H:%M:%S") if r.sent_at else None,
        })
    return {"items": items}


# ==============================================================================
# 5. WEBHOOK CRON ENDPOINTS (11:00 / 15:00 & NHẮC HẸN ĐÚNG GIỜ)
# ==============================================================================
@router.post("/cron/dispatch", dependencies=[Depends(_verify_cron_secret)])
def cron_dispatch_digest(
    slot: str = Query(default="11h", description="11h hoặc 15h"),
    sync_first: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    """Endpoint để GitHub Actions / Cronjob ngoài gọi lúc 11:00 và 15:00 giờ VN."""
    sync_res = sync_bulletin_from_group(db=db, max_pages=2) if sync_first else None
    if sync_res and (sync_res.get("inserted") or sync_res.get("merged")):
        clear_bulletin_meta_cache()
    digest_res = dispatch_daily_digest(db=db, slot=slot, dry_run=False, force=False)
    exact_res = dispatch_due_exact_reminders(db=db, dry_run=False)
    return {
        "status": "ok",
        "sync": sync_res,
        "digest": digest_res,
        "exact": exact_res,
    }


@router.post("/cron/tick", dependencies=[Depends(_verify_cron_secret)])
def cron_tick_exact_reminders(
    sync_posts: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """Endpoint để cronjob định kỳ kiểm tra các nhắc hẹn đúng giờ (exact_time)."""
    sync_res = sync_bulletin_from_group(db=db, max_pages=2) if sync_posts else None
    if sync_res and (sync_res.get("inserted") or sync_res.get("merged")):
        clear_bulletin_meta_cache()
    exact_res = dispatch_due_exact_reminders(db=db, dry_run=False)
    return {
        "status": "ok",
        "sync": sync_res,
        "exact": exact_res,
    }
