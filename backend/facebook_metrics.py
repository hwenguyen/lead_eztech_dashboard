"""
Module Backend Phân tích & Chỉ số chuyên sâu Facebook (Facebook Analytics).
Tổng hợp dữ liệu từ Bài viết (posts), Bình luận (comments), Khách hàng tiềm năng (dim_leads),
Hành vi liên hệ (fact_lead_activities) và Học viên chốt (deal_wins) thuộc các kênh Facebook.
"""

import time
import threading
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Set, Tuple
from collections import Counter

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, desc

from database.db import get_db
from database.models import Post, Comment, DimLead, FactLeadActivity, DealWin
from backend.lead_metrics import classify_leads, resolve_period, normalize_text
from etl.utils import (
    VN_TZ,
    KNOWN_PAGE_NAMES,
    ZALO_PAGE_NAMES,
    resolve_canonical_page_name,
    build_post_url,
    normalize_phone,
)

logger = logging.getLogger("FacebookMetricsService")

router = APIRouter(prefix="/api/facebook", tags=["Facebook Analytics"])

# In-memory TTL Cache (5 phút) để tối ưu băng thông Neon
_FB_CACHE_LOCK = threading.RLock()
_FB_CACHE: Dict[Tuple[str, str, Optional[str]], Tuple[float, Dict[str, Any]]] = {}
FB_CACHE_TTL = 300.0  # 5 phút


def clear_facebook_cache():
    """Xóa bộ nhớ đệm metrics Facebook."""
    with _FB_CACHE_LOCK:
        _FB_CACHE.clear()


def is_fb_page(page_id_or_name: Optional[str]) -> bool:
    """Xác định xem một page_id hoặc page_name có phải là Fanpage Facebook hay không."""
    if not page_id_or_name:
        return False
    s = str(page_id_or_name).strip()
    if s.startswith("tt_") or s.startswith("pzl_"):
        return False
    canonical = resolve_canonical_page_name(s, fallback=s)
    if canonical in ZALO_PAGE_NAMES or "tiktok" in canonical.lower() or "zalo" in canonical.lower():
        return False
    if "facebook" in canonical.lower() or s == "514400205095512" or s.startswith("fb_"):
        return True
    return False


def get_facebook_page_names() -> List[Dict[str, str]]:
    """Lấy danh sách các trang Facebook đã cấu hình trong hệ sinh thái."""
    pages = []
    seen = set()
    for pid, name in KNOWN_PAGE_NAMES.items():
        if is_fb_page(pid) or is_fb_page(name):
            canonical = resolve_canonical_page_name(name, fallback=name)
            if canonical not in seen:
                seen.add(canonical)
                pages.append({"id": pid, "name": canonical})
    return pages


@router.get("/pages")
def get_facebook_pages(db: Session = Depends(get_db)):
    """API trả về danh sách các Fanpage Facebook phục vụ bộ lọc."""
    # Lấy từ cấu hình cố định
    configured = get_facebook_page_names()
    # Lấy thêm từ dữ liệu thực tế trong bảng posts nếu có
    db_pages = db.query(Post.page_id, Post.page_name).filter(Post.platform == "facebook").distinct().all()
    seen = {p["name"] for p in configured}
    for pid, pname in db_pages:
        cname = resolve_canonical_page_name(pname or pid, fallback=pname or pid)
        if cname not in seen:
            seen.add(cname)
            configured.append({"id": pid, "name": cname})
    return {"pages": configured}


@router.get("/metrics")
def get_facebook_metrics(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    page_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    API tổng hợp toàn diện chỉ số Facebook:
    - Bài viết & Cảm xúc (Reactions: Like, Love, Haha, Care, Wow, Sad, Angry)
    - Bình luận (Comments) & Số SĐT thu được từ bình luận
    - Lead Facebook (Lead Mới vs Lead Contact Lại, SĐT thu được)
    - Học viên chốt (Deal Win) từ nguồn Facebook
    - Top bài viết hiệu quả nhất (Reactions, Comments, SĐT)
    - Biểu đồ xu hướng biến động theo ngày
    - Phân bổ nhân viên & Tag
    """
    start, end = resolve_period(start_date, end_date)
    start_str = start.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end.strftime("%Y-%m-%d %H:%M:%S")
    page_key = page_id.strip() if page_id else None
    cache_key = (start_str, end_str, page_key)

    with _FB_CACHE_LOCK:
        now_ts = time.time()
        if cache_key in _FB_CACHE:
            cached_time, cached_val = _FB_CACHE[cache_key]
            if now_ts - cached_time < FB_CACHE_TTL:
                return cached_val

    # 1. Xác định phạm vi Fanpage Facebook
    fb_pages = get_facebook_page_names()
    fb_page_names = [p["name"] for p in fb_pages]
    fb_page_ids = [p["id"] for p in fb_pages]

    target_page_name = None
    target_page_id = None
    if page_key:
        target_page_name = resolve_canonical_page_name(page_key, fallback=page_key)
        target_page_id = page_key

    # 2. Truy vấn Bài viết (Post)
    post_query = db.query(Post).filter(
        Post.platform == "facebook",
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

    # 3. Truy vấn Bình luận (Comment)
    comment_query = db.query(
        Comment.comment_id,
        Comment.customer_id,
        Comment.post_id,
        Comment.phone_number,
        Comment.inserted_at,
        Comment.page_id,
        Comment.page_name,
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
        # Lấy tất cả comment thuộc Facebook
        comment_query = comment_query.filter(
            or_(
                Comment.page_name.in_(fb_page_names),
                Comment.page_id.in_(fb_page_ids),
                Comment.page_name.ilike("%Facebook%"),
            )
        )
    comments = comment_query.all()

    # Thống kê bình luận & SĐT từ bình luận
    total_comments_received = len(comments)
    comments_with_phone = 0
    comments_by_date: Dict[str, int] = Counter()
    comment_phones_by_date: Dict[str, int] = Counter()

    # Ánh xạ bóc tách Lead, SĐT theo từng bài viết (hỗ trợ cả ID đầy đủ lẫn ID rút gọn sau dấu gạch dưới)
    post_leads_set: Dict[str, Set[str]] = {}
    post_phones_set: Dict[str, Set[str]] = {}

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
            if clean_pid not in post_leads_set:
                post_leads_set[clean_pid] = set()
                post_phones_set[clean_pid] = set()

            if c.customer_id:
                post_leads_set[clean_pid].add(str(c.customer_id))
            if has_phone:
                p_norm = normalize_phone(c.phone_number) or c.phone_number.strip()
                post_phones_set[clean_pid].add(p_norm)

    # 4. Phân loại Lead từ Facebook (qua classify_leads)
    lead_scope_page = target_page_name if target_page_name else "Anh Kế toán làm Data (Facebook)"
    leads = classify_leads(db, start, end, page_id=lead_scope_page)

    fb_leads_total = len(leads)
    fb_new_leads = sum(1 for l in leads.values() if l.is_new)
    fb_recontact_leads = sum(1 for l in leads.values() if l.is_recontact)
    fb_phone_leads = sum(1 for l in leads.values() if l.has_phone and l.phone_event_at)

    # Đếm số Lead và SĐT của từng bài viết từ Leads
    for l in leads.values():
        if l.post_id:
            raw_pid = str(l.post_id).strip()
            clean_pid = raw_pid.split("_")[-1] if "_" in raw_pid else raw_pid
            if clean_pid not in post_leads_set:
                post_leads_set[clean_pid] = set()
                post_phones_set[clean_pid] = set()

            if l.customer_id:
                post_leads_set[clean_pid].add(str(l.customer_id))
            if l.phone_number:
                p_norm = normalize_phone(l.phone_number) or l.phone_number.strip()
                post_phones_set[clean_pid].add(p_norm)

        # Bổ sung SĐT nếu khách từng comment vào post rồi để lại SĐT qua hội thoại/inbox
        if l.customer_id and l.phone_number:
            p_norm = normalize_phone(l.phone_number) or l.phone_number.strip()
            for pid, cset in post_leads_set.items():
                if str(l.customer_id) in cset:
                    post_phones_set[pid].add(p_norm)

    # Phân bổ nhân viên & Tag từ Facebook Leads
    employee_counter: Dict[str, int] = Counter()
    tag_counter: Dict[str, int] = Counter()
    for l in leads.values():
        emp = l.primary_employee or "Chưa phân công"
        employee_counter[emp] += 1
        for t in l.tags:
            tag_counter[t] += 1

    # 5. Truy vấn Deal Win (Học viên chốt từ Facebook)
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
                DealWin.page_id.in_(fb_page_names),
                DealWin.page_id.in_(fb_page_ids),
                DealWin.page_id.ilike("%Facebook%"),
            )
        )
    deals: List[DealWin] = deal_query.all()
    fb_deal_wins = len(deals)

    # Khớp chính xác Deal Win với từng bài viết dựa trên SĐT thu được từ bài đó
    post_deals_map: Dict[str, int] = Counter()
    for d in deals:
        if d.phone_number:
            dp = normalize_phone(d.phone_number) or d.phone_number.strip()
            for clean_pid, pset in post_phones_set.items():
                if dp in pset:
                    post_deals_map[clean_pid] += 1

    # 6. Thống kê bài viết, cảm xúc & loại bài
    total_posts = len(posts)
    total_reactions = sum(p.reactions_total or 0 for p in posts)
    total_post_comments = sum(p.comment_count or 0 for p in posts)
    total_shares = sum(p.share_count or 0 for p in posts)

    reaction_breakdown = {
        "like": sum(p.like_count or 0 for p in posts),
        "love": sum(p.love_count or 0 for p in posts),
        "haha": sum(p.haha_count or 0 for p in posts),
        "care": sum(p.care_count or 0 for p in posts),
        "wow": sum(p.wow_count or 0 for p in posts),
        "sad": sum(p.sad_count or 0 for p in posts),
        "angry": sum(p.angry_count or 0 for p in posts),
    }

    type_counter: Dict[str, int] = Counter()
    for p in posts:
        t_name = (p.type or "post").lower()
        if t_name == "status":
            t_name = "post"
        type_counter[t_name] += 1

    # 7. Xây dựng chuỗi xu hướng theo từng ngày trong kỳ
    trend_data = []
    day = start
    # Nhóm bài viết theo ngày
    posts_by_date: Dict[str, int] = Counter()
    reactions_by_date: Dict[str, int] = Counter()
    for p in posts:
        if p.inserted_at:
            pd_str = p.inserted_at.strftime("%Y-%m-%d")
            posts_by_date[pd_str] += 1
            reactions_by_date[pd_str] += (p.reactions_total or 0)

    # Nhóm leads theo ngày
    leads_by_date: Dict[str, int] = Counter()
    phones_by_date: Dict[str, int] = Counter()
    for l in leads.values():
        if l.is_new and l.first_created_at:
            ld_str = l.first_created_at.strftime("%Y-%m-%d")
            leads_by_date[ld_str] += 1
        elif l.is_recontact:
            for cday in l.contact_days:
                leads_by_date[cday] += 1
        if l.phone_event_at:
            ph_str = l.phone_event_at.strftime("%Y-%m-%d")
            phones_by_date[ph_str] += 1

    while day <= end:
        d_str = day.strftime("%Y-%m-%d")
        trend_data.append({
            "date": d_str,
            "posts": posts_by_date.get(d_str, 0),
            "reactions": reactions_by_date.get(d_str, 0),
            "comments": comments_by_date.get(d_str, 0),
            "leads": leads_by_date.get(d_str, 0),
            "phones": phones_by_date.get(d_str, 0),
        })
        day += timedelta(days=1)

    # 8. Danh sách bài viết Facebook kèm thống kê Lead, SĐT, Deal Win thu được
    top_posts_data = []
    for p in posts:
        clean_msg = p.message or ""
        p_url = p.post_url or build_post_url(p.post_id, p.page_id)
        raw_pid = str(p.post_id).strip()
        clean_pid = raw_pid.split("_")[-1] if "_" in raw_pid else raw_pid

        leads_c = len(post_leads_set.get(clean_pid, set()))
        phones_c = len(post_phones_set.get(clean_pid, set()))
        deals_c = post_deals_map.get(clean_pid, 0)

        top_posts_data.append({
            "post_id": raw_pid,
            "page_id": p.page_id,
            "page_name": p.page_name or "Facebook",
            "type": (p.type or "post").lower(),
            "message": clean_msg,
            "post_url": p_url,
            "inserted_at": p.inserted_at.strftime("%Y-%m-%d %H:%M") if p.inserted_at else None,
            "reactions_total": p.reactions_total or 0,
            "like_count": p.like_count or 0,
            "love_count": p.love_count or 0,
            "comment_count": p.comment_count or 0,
            "lead_count": leads_c,
            "phone_count": phones_c,
            "deal_count": deals_c,
        })

    # Tỷ lệ chuyển đổi
    phone_conv_rate = round((fb_phone_leads / fb_leads_total * 100), 1) if fb_leads_total > 0 else 0.0
    deal_conv_rate = round((fb_deal_wins / fb_phone_leads * 100), 1) if fb_phone_leads > 0 else 0.0
    avg_reactions_per_post = round(total_reactions / total_posts, 1) if total_posts > 0 else 0.0
    avg_comments_per_post = round(total_comments_received / total_posts, 1) if total_posts > 0 else 0.0

    result = {
        "summary": {
            "total_posts": total_posts,
            "total_reactions": total_reactions,
            "total_comments": total_comments_received,
            "total_post_comments": total_post_comments,
            "total_shares": total_shares,
            "total_leads": fb_leads_total,
            "new_leads": fb_new_leads,
            "recontact_leads": fb_recontact_leads,
            "phone_leads": fb_phone_leads,
            "comment_phones": comments_with_phone,
            "deal_wins": fb_deal_wins,
            "phone_conversion_rate": phone_conv_rate,
            "deal_conversion_rate": deal_conv_rate,
            "avg_reactions_per_post": avg_reactions_per_post,
            "avg_comments_per_post": avg_comments_per_post,
        },
        "reaction_breakdown": reaction_breakdown,
        "post_type_stats": dict(type_counter),
        "trend": trend_data,
        "top_posts": top_posts_data,
        "employee_stats": dict(employee_counter.most_common(10)),
        "tag_stats": dict(tag_counter.most_common(12)),
    }

    # Lưu cache
    with _FB_CACHE_LOCK:
        if len(_FB_CACHE) > 30:
            expired_keys = [k for k, (t, _) in _FB_CACHE.items() if now_ts - t > FB_CACHE_TTL]
            for k in expired_keys:
                _FB_CACHE.pop(k, None)
        _FB_CACHE[cache_key] = (now_ts, result)

    return result
