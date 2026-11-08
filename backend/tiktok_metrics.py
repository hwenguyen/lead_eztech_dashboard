"""
Module Backend Phân tích & Chỉ số chuyên sâu TikTok (TikTok Analytics).
Tổng hợp dữ liệu từ Video/Post (posts), Bình luận (comments), Khách hàng tiềm năng (dim_leads),
Hành vi liên hệ (fact_lead_activities) và Học viên chốt (deal_wins) thuộc các kênh TikTok.
"""

import time
import threading
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Set
from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, defer
from sqlalchemy import or_, desc, func

from database.db import get_db
from database.models import Post, Comment, DealWin, FactLeadActivity
from backend.lead_metrics import classify_leads, resolve_period
from etl.utils import (
    resolve_canonical_page_name,
    build_post_url,
    normalize_phone,
)

logger = logging.getLogger("TikTokMetricsService")

router = APIRouter(prefix="/api/tiktok", tags=["TikTok Analytics"])

# In-memory TTL Cache (5 phút) để tối ưu băng thông
_TT_CACHE: Dict[str, Any] = {}
_TT_CACHE_LOCK = threading.Lock()
TT_CACHE_TTL = 900  # 15 phút cache tiết kiệm egress

TIKTOK_KNOWN_PAGES = [
    {"id": "tt_7196601676597871618", "name": "Anh Kế toán làm Data (TikTok)"},
    {"id": "tt_7456003523327919120", "name": "Hành trang cho kế toán"},
    {"id": "tt_7661860189083943944", "name": "Chị Kế Toán GenZ"},
    {"id": "tt_7602128557942293512", "name": "Anh kế toán Daily"},
]

TIKTOK_PAGE_NAMES = [p["name"] for p in TIKTOK_KNOWN_PAGES]
TIKTOK_PAGE_IDS = [p["id"] for p in TIKTOK_KNOWN_PAGES]


def clear_tiktok_cache():
    """Xóa bộ nhớ đệm metrics TikTok."""
    with _TT_CACHE_LOCK:
        _TT_CACHE.clear()


@router.get("/pages")
def get_tiktok_pages(db: Session = Depends(get_db)):
    """API trả về danh sách các Kênh TikTok phục vụ bộ lọc."""
    return {"pages": TIKTOK_KNOWN_PAGES}


@router.get("/metrics")
def get_tiktok_metrics(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    page_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    API tổng hợp toàn diện chỉ số TikTok:
    - Video đăng tải, lượt tim, lượt chia sẻ
    - Bình luận (Comments) & SĐT thu được từ bình luận
    - Lead TikTok (Lead Mới vs Lead Contact Lại, SĐT thu được)
    - Học viên chốt (Deal Win từ TikTok)
    - Phân tích Nguồn Lead: Video (Post) vs Tự nhiên (Organic Inbox)
    - Danh sách Top Video TikTok hiệu quả nhất
    """
    start, end = resolve_period(start_date, end_date)
    start_str = start.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end.strftime("%Y-%m-%d %H:%M:%S")
    page_key = page_id.strip() if page_id else ""

    cache_key = f"{start_str}_{end_str}_{page_key}"
    now_ts = time.time()

    with _TT_CACHE_LOCK:
        if cache_key in _TT_CACHE:
            cached_time, cached_data = _TT_CACHE[cache_key]
            if now_ts - cached_time < TT_CACHE_TTL:
                return cached_data

    # 1. Xác định phạm vi Kênh TikTok
    target_page_name = None
    target_page_id = None
    if page_key:
        target_page_name = resolve_canonical_page_name(page_key, fallback=page_key)
        target_page_id = page_key

    # 2. Truy vấn Video (Post) - Bỏ qua payload JSON nặng để tiết kiệm băng thông Neon
    post_query = db.query(Post).options(defer(Post.payload)).filter(
        Post.platform == "tiktok",
        Post.inserted_at.between(start, end),
    )
    if target_page_name or target_page_id:
        post_query = post_query.filter(
            or_(
                Post.page_id == target_page_id,
                Post.page_id == target_page_name,
                Post.page_name == target_page_name,
            )
        )
    posts: List[Post] = post_query.order_by(desc(Post.inserted_at)).all()

    # 3. Truy vấn Bình luận (Comment) - Trích xuất trực tiếp from.id từ JSON trong SQL để giảm 99% Egress
    comment_query = db.query(
        Comment.comment_id,
        Comment.customer_id,
        Comment.post_id,
        Comment.phone_number,
        Comment.inserted_at,
        Comment.page_id,
        Comment.page_name,
        func.json_extract_path_text(Comment.payload, "from", "id").label("from_id"),
    ).filter(
        Comment.inserted_at.between(start, end),
    )
    if target_page_name or target_page_id:
        comment_query = comment_query.filter(
            or_(
                Comment.page_id == target_page_id,
                Comment.page_id == target_page_name,
                Comment.page_name == target_page_name,
            )
        )
    else:
        comment_query = comment_query.filter(
            or_(
                Comment.page_id.like("tt_%"),
                Comment.page_name.in_(TIKTOK_PAGE_NAMES),
            )
        )
    comments = comment_query.all()

    # Thống kê bình luận & SĐT từ bình luận
    total_comments_received = len(comments)
    comments_with_phone = 0
    comments_by_date: Dict[str, int] = Counter()
    comment_phones_by_date: Dict[str, int] = Counter()
    comments_by_post: Dict[str, int] = Counter()

    post_leads_set: Dict[str, Set[str]] = {}
    post_phones_set: Dict[str, Set[str]] = {}
    uid_to_posts: Dict[str, Set[str]] = {}

    for c in comments:
        c_ins = c.inserted_at
        d_str = c_ins.strftime("%Y-%m-%d") if c_ins else None
        if d_str:
            comments_by_date[d_str] += 1
        has_phone = bool(c.phone_number and c.phone_number.strip())
        if has_phone:
            comments_with_phone += 1
            if d_str:
                comment_phones_by_date[d_str] += 1

        if c.post_id:
            raw_pid = str(c.post_id).strip()
            clean_pid = raw_pid.split("_")[-1] if "_" in raw_pid else raw_pid
            comments_by_post[clean_pid] += 1

            if clean_pid not in post_leads_set:
                post_leads_set[clean_pid] = set()
                post_phones_set[clean_pid] = set()

            # Chỉ lưu SĐT nếu khách để lại trực tiếp trên bình luận
            if has_phone:
                p_norm = normalize_phone(c.phone_number) or c.phone_number.strip()
                post_phones_set[clean_pid].add(p_norm)

            # Thu thập TikTok User ID của người comment để map với cuộc trò chuyện Inbox (lấy trực tiếp từ from_id)
            tt_uid = str(c.from_id or "").replace("tt_", "").strip()
            if tt_uid:
                if tt_uid not in uid_to_posts:
                    uid_to_posts[tt_uid] = set()
                uid_to_posts[tt_uid].add(clean_pid)

    # 4. Phân loại Lead từ TikTok (qua classify_leads)
    leads = {}
    if target_page_name:
        leads = classify_leads(db, start, end, page_id=target_page_name)
    else:
        for p_name in TIKTOK_PAGE_NAMES:
            p_leads = classify_leads(db, start, end, page_id=p_name)
            leads.update(p_leads)

    tt_leads_total = len(leads)
    tt_new_leads = sum(1 for l in leads.values() if l.is_new)
    tt_recontact_leads = sum(1 for l in leads.values() if l.is_recontact)
    tt_phone_leads = sum(1 for l in leads.values() if l.has_phone and l.phone_event_at)

    # Đếm số Lead và SĐT của từng video từ Leads có post_id sẵn
    for l_id, l in leads.items():
        if l.post_id:
            raw_pid = str(l.post_id).strip()
            clean_pid = raw_pid.split("_")[-1] if "_" in raw_pid else raw_pid
            if clean_pid not in post_leads_set:
                post_leads_set[clean_pid] = set()
                post_phones_set[clean_pid] = set()

            post_leads_set[clean_pid].add(str(l_id))
            if l.phone_number:
                p_norm = normalize_phone(l.phone_number) or l.phone_number.strip()
                post_phones_set[clean_pid].add(p_norm)

    # Ánh xạ thông minh qua TikTok UID:
    # Khách bình luận vào Video (có UID và post_id) -> sau đó vào Inbox nhắn tin để lại SĐT (conversation_id dạng tt_0:1:<uid>:<page_id>)
    lead_ids = list(leads.keys())
    if lead_ids and uid_to_posts:
        lead_convs = db.query(FactLeadActivity.lead_id, FactLeadActivity.conversation_id).filter(
            FactLeadActivity.lead_id.in_(lead_ids)
        ).all()
        for l_id, conv_id in lead_convs:
            if conv_id and conv_id.startswith("tt_"):
                parts = conv_id.split(":")
                if len(parts) >= 4:
                    tt_uid = parts[2].strip()
                    pids = uid_to_posts.get(tt_uid)
                    if pids:
                        lead_obj = leads.get(l_id)
                        p_norm = normalize_phone(lead_obj.phone_number) if lead_obj and lead_obj.phone_number else None
                        has_phone_ev = bool(lead_obj and lead_obj.has_phone and lead_obj.phone_event_at and p_norm)
                        for clean_pid in pids:
                            if clean_pid not in post_leads_set:
                                post_leads_set[clean_pid] = set()
                                post_phones_set[clean_pid] = set()
                            post_leads_set[clean_pid].add(str(l_id))
                            if has_phone_ev and p_norm:
                                post_phones_set[clean_pid].add(p_norm)

    # 5. Truy vấn Deal Win (Học viên chốt từ TikTok)
    deal_query = db.query(DealWin).filter(
        DealWin.timestamp.between(start, end),
    )
    if target_page_name or target_page_id:
        deal_query = deal_query.filter(
            or_(
                DealWin.page_id == target_page_id,
                DealWin.page_id == target_page_name,
            )
        )
    else:
        deal_query = deal_query.filter(
            or_(
                DealWin.page_id.in_(TIKTOK_PAGE_NAMES),
                DealWin.page_id.like("tt_%"),
            )
        )
    deals: List[DealWin] = deal_query.all()
    tt_deal_wins = len(deals)

    # Khớp chính xác Deal Win với từng video dựa trên SĐT thu được từ video đó
    post_deals_map: Dict[str, int] = Counter()
    for d in deals:
        if d.phone_number:
            dp = normalize_phone(d.phone_number) or d.phone_number.strip()
            for clean_pid, pset in post_phones_set.items():
                if dp in pset:
                    post_deals_map[clean_pid] += 1

    # 6. Thống kê bài viết, cảm xúc & loại bài
    total_posts = len(posts)
    total_reactions = sum(p.reactions_total or p.like_count or 0 for p in posts)
    total_post_comments = sum(p.comment_count or 0 for p in posts)
    total_shares = sum(p.share_count or 0 for p in posts)

    reaction_breakdown = {
        "like": total_reactions,
        "love": 0,
        "haha": 0,
        "care": 0,
        "wow": 0,
        "sad": 0,
        "angry": 0,
    }

    type_counter: Dict[str, int] = Counter()
    for p in posts:
        t_name = (p.type or "video").lower()
        if t_name in ("post", "status"):
            t_name = "video"
        type_counter[t_name] += 1

    # 7. Xây dựng chuỗi xu hướng theo từng ngày trong kỳ
    # Phân loại tổng thể nguồn: Video (Post) vs Tự nhiên (Organic Inbox)
    post_lead_ids = set()
    for cset in post_leads_set.values():
        post_lead_ids.update(cset)
    total_post_cust = len(post_lead_ids)

    post_phone_set = set()
    for pset in post_phones_set.values():
        post_phone_set.update(pset)
    total_post_phones = len(post_phone_set)

    organic_lead_count = sum(
        1 for l_id, l in leads.items()
        if str(l_id) not in post_lead_ids and str(l.customer_id) not in post_lead_ids and not l.post_id
    )
    organic_phone_count = sum(
        1 for l_id, l in leads.items()
        if (str(l_id) not in post_lead_ids and str(l.customer_id) not in post_lead_ids and not l.post_id)
        and l.has_phone and l.phone_event_at
    )

    post_phone_rate = round((total_post_phones / total_post_cust * 100), 1) if total_post_cust > 0 else 0.0
    organic_phone_rate = round((organic_phone_count / organic_lead_count * 100), 1) if organic_lead_count > 0 else 0.0

    trend_data = []
    day = start
    posts_by_date: Dict[str, int] = Counter()
    reactions_by_date: Dict[str, int] = Counter()
    for p in posts:
        if p.inserted_at:
            pd_str = p.inserted_at.strftime("%Y-%m-%d")
            posts_by_date[pd_str] += 1
            reactions_by_date[pd_str] += (p.reactions_total or p.like_count or 0)

    leads_by_date: Dict[str, int] = Counter()
    phones_by_date: Dict[str, int] = Counter()
    post_leads_by_date: Dict[str, int] = Counter()
    organic_leads_by_date: Dict[str, int] = Counter()
    organic_phones_by_date: Dict[str, int] = Counter()

    for c in comments:
        if c.inserted_at:
            cd_str = c.inserted_at.strftime("%Y-%m-%d")
            post_leads_by_date[cd_str] += 1

    for l_id, l in leads.items():
        if l.is_new and l.first_created_at:
            ld_str = l.first_created_at.strftime("%Y-%m-%d")
            leads_by_date[ld_str] += 1
        elif l.is_recontact:
            for cday in l.contact_days:
                leads_by_date[cday] += 1
        if l.phone_event_at:
            ph_str = l.phone_event_at.strftime("%Y-%m-%d")
            phones_by_date[ph_str] += 1

        is_post = (str(l_id) in post_lead_ids) or (str(l.customer_id) in post_lead_ids) or bool(l.post_id)
        if not is_post:
            if l.is_new and l.first_created_at:
                ld_str = l.first_created_at.strftime("%Y-%m-%d")
                organic_leads_by_date[ld_str] += 1
            elif l.is_recontact:
                for cday in l.contact_days:
                    organic_leads_by_date[cday] += 1
            if l.phone_event_at:
                ph_str = l.phone_event_at.strftime("%Y-%m-%d")
                organic_phones_by_date[ph_str] += 1

    while day <= end:
        d_str = day.strftime("%Y-%m-%d")
        trend_data.append({
            "date": d_str,
            "posts": posts_by_date.get(d_str, 0),
            "reactions": reactions_by_date.get(d_str, 0),
            "comments": comments_by_date.get(d_str, 0),
            "leads": leads_by_date.get(d_str, 0),
            "phones": phones_by_date.get(d_str, 0),
            "post_leads": post_leads_by_date.get(d_str, 0),
            "organic_leads": organic_leads_by_date.get(d_str, 0),
            "post_phones": comment_phones_by_date.get(d_str, 0),
            "organic_phones": organic_phones_by_date.get(d_str, 0),
        })
        day += timedelta(days=1)

    # 8. Danh sách video TikTok kèm thống kê Lead, SĐT, Deal Win thu được
    top_posts_data = []
    for p in posts:
        clean_msg = p.message or ""
        p_url = p.post_url or build_post_url(p.post_id, p.page_id)
        raw_pid = str(p.post_id).strip()
        clean_pid = raw_pid.split("_")[-1] if "_" in raw_pid else raw_pid

        leads_c = len(post_leads_set.get(clean_pid, set()))
        phones_c = len(post_phones_set.get(clean_pid, set()))
        deals_c = post_deals_map.get(clean_pid, 0)
        c_count = comments_by_post.get(clean_pid, p.comment_count or 0)

        top_posts_data.append({
            "post_id": raw_pid,
            "page_id": p.page_id,
            "page_name": p.page_name or "TikTok",
            "type": (p.type or "video").lower(),
            "message": clean_msg,
            "post_url": p_url,
            "inserted_at": p.inserted_at.strftime("%Y-%m-%d %H:%M") if p.inserted_at else None,
            "reactions_total": p.reactions_total or p.like_count or 0,
            "like_count": p.like_count or 0,
            "love_count": 0,
            "comment_count": c_count,
            "lead_count": leads_c,
            "phone_count": phones_c,
            "deal_count": deals_c,
        })

    # Tỷ lệ chuyển đổi
    phone_conv_rate = round((tt_phone_leads / tt_leads_total * 100), 1) if tt_leads_total > 0 else 0.0
    deal_conv_rate = round((tt_deal_wins / tt_phone_leads * 100), 1) if tt_phone_leads > 0 else 0.0
    avg_reactions_per_post = round(total_reactions / total_posts, 1) if total_posts > 0 else 0.0
    avg_comments_per_post = round(total_comments_received / total_posts, 1) if total_posts > 0 else 0.0

    result = {
        "summary": {
            "total_posts": total_posts,
            "total_reactions": total_reactions,
            "total_comments": total_comments_received,
            "total_post_comments": total_post_comments,
            "total_shares": total_shares,
            "total_leads": tt_leads_total,
            "new_leads": tt_new_leads,
            "recontact_leads": tt_recontact_leads,
            "phone_leads": tt_phone_leads,
            "comment_phones": comments_with_phone,
            "deal_wins": tt_deal_wins,
            "phone_conversion_rate": phone_conv_rate,
            "deal_conversion_rate": deal_conv_rate,
            "avg_reactions_per_post": avg_reactions_per_post,
            "avg_comments_per_post": avg_comments_per_post,
            "post_leads": total_post_cust,
            "post_phones": total_post_phones,
            "post_phone_rate": post_phone_rate,
            "organic_leads": organic_lead_count,
            "organic_phones": organic_phone_count,
            "organic_phone_rate": organic_phone_rate,
        },
        "channel_breakdown": {
            "post": {
                "name": "Từ Video (TikTok)",
                "leads": total_post_cust,
                "phones": total_post_phones,
                "conversion_rate": post_phone_rate,
            },
            "organic": {
                "name": "Tự nhiên (Organic Inbox)",
                "leads": organic_lead_count,
                "phones": organic_phone_count,
                "conversion_rate": organic_phone_rate,
            }
        },
        "reaction_breakdown": reaction_breakdown,
        "post_type_stats": dict(type_counter),
        "trend": trend_data,
        "top_posts": top_posts_data,
        "employee_stats": {},
        "tag_stats": {},
    }

    # Lưu cache
    with _TT_CACHE_LOCK:
        if len(_TT_CACHE) > 30:
            expired_keys = [k for k, (t, _) in _TT_CACHE.items() if now_ts - t > TT_CACHE_TTL]
            for k in expired_keys:
                _TT_CACHE.pop(k, None)
        _TT_CACHE[cache_key] = (now_ts, result)

    return result
