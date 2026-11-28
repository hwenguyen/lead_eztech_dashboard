"""
Module Backend Phân tích & Chỉ số chuyên sâu Facebook (Facebook Analytics).
Tổng hợp dữ liệu từ Bài viết (posts), Bình luận (comments), Khách hàng tiềm năng (dim_leads),
Hành vi liên hệ (fact_lead_activities) và Học viên chốt (deal_wins) thuộc các kênh Facebook.
"""

import json
import time
import threading
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Set, Tuple
from collections import Counter

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, defer
from sqlalchemy import func, or_, desc

from database.db import get_db
from database.models import Post, Comment, DimLead, FactLeadActivity, DealWin, AppConfig
from backend.lead_metrics import classify_leads, resolve_period, normalize_text, split_csv
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

# In-memory TTL Cache (30 phút; xóa tự động sau mỗi lần ETL) để tối ưu băng thông Neon
_FB_CACHE_LOCK = threading.RLock()
_FB_CACHE: Dict[Tuple[str, str, Optional[str]], Tuple[float, Dict[str, Any]]] = {}
_FB_PAGES_CACHE: Tuple[float, Any] = (0.0, None)
_ADS_META_CACHE: Dict[str, Dict[str, str]] = {}
FB_CACHE_TTL = 1800


def _resolve_ads_metadata(db: Session, ad_ids: Set[str]) -> Dict[str, Dict[str, str]]:
    """Tra cứu tên Chiến dịch (campaign_name) và tên Mẫu Ads (name) từ AppConfig hoặc Pancake API."""
    global _ADS_META_CACHE
    if not ad_ids:
        return {}

    with _FB_CACHE_LOCK:
        if not _ADS_META_CACHE:
            try:
                cfg = db.query(AppConfig).filter_by(config_key="FACEBOOK_ADS_METADATA").first()
                if cfg and cfg.config_value:
                    loaded = json.loads(cfg.config_value)
                    if isinstance(loaded, dict):
                        _ADS_META_CACHE.update(loaded)
            except Exception as e:
                logger.warning("Không thể đọc FACEBOOK_ADS_METADATA từ DB: %s", e)

        missing = [aid for aid in ad_ids if aid and aid not in _ADS_META_CACHE]

    if missing:
        try:
            from etl.pancake_client import PancakeClient
            client = PancakeClient()
            ptoken, pid, _ = client._get_page_access_token("514400205095512")
            if ptoken and pid:
                newly_fetched = {}
                for i in range(0, len(missing), 20):
                    chunk = missing[i:i + 20]
                    url = f"https://pages.fm/api/public_api/v1/pages/{pid}/ads"
                    resp = client.session.get(
                        url,
                        params={"page_access_token": ptoken, "ad_ids": ",".join(chunk)},
                        timeout=6,
                    )
                    if resp.status_code == 200:
                        for item in resp.json().get("data", []):
                            if isinstance(item, dict) and item.get("id"):
                                k = str(item["id"]).strip()
                                newly_fetched[k] = {
                                    "ad_id": k,
                                    "name": item.get("name") or "",
                                    "campaign_id": str(item.get("campaign_id") or ""),
                                    "campaign_name": item.get("campaign_name") or "",
                                    "image_url": item.get("image_url") or "",
                                }
                with _FB_CACHE_LOCK:
                    for k in missing:
                        _ADS_META_CACHE[k] = newly_fetched.get(k, {"ad_id": k, "name": "", "campaign_id": "", "campaign_name": ""})
                    if newly_fetched:
                        try:
                            cfg = db.query(AppConfig).filter_by(config_key="FACEBOOK_ADS_METADATA").first()
                            if cfg:
                                cfg.config_value = json.dumps(_ADS_META_CACHE, ensure_ascii=False)
                            else:
                                db.add(AppConfig(config_key="FACEBOOK_ADS_METADATA", config_value=json.dumps(_ADS_META_CACHE, ensure_ascii=False)))
                            db.commit()
                        except Exception:
                            db.rollback()
        except Exception as e:
            logger.warning("Không thể đồng bộ thêm metadata Ads từ Pancake API: %s", e)

    with _FB_CACHE_LOCK:
        return {aid: _ADS_META_CACHE.get(aid, {}) for aid in ad_ids}


def clear_facebook_cache():
    """Xóa bộ nhớ đệm metrics Facebook."""
    global _FB_PAGES_CACHE
    with _FB_CACHE_LOCK:
        _FB_CACHE.clear()
        _FB_PAGES_CACHE = (0.0, None)


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
    """API trả về danh sách các Fanpage Facebook phục vụ bộ lọc (cache 1 giờ)."""
    global _FB_PAGES_CACHE
    now_ts = time.time()
    with _FB_CACHE_LOCK:
        if _FB_PAGES_CACHE[1] is not None and (now_ts - _FB_PAGES_CACHE[0] < 3600.0):
            return _FB_PAGES_CACHE[1]

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
    res = {"pages": configured}
    with _FB_CACHE_LOCK:
        _FB_PAGES_CACHE = (now_ts, res)
    return res


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
            today_start = datetime.now(VN_TZ).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
            effective_ttl = 86400.0 if end < today_start else FB_CACHE_TTL
            if now_ts - cached_time < effective_ttl:
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

    # 2. Truy vấn Bài viết (Post) - Bỏ qua payload JSON nặng để tiết kiệm băng thông Neon
    post_query = db.query(Post).options(defer(Post.payload)).filter(
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
    post_phone_leads_set: Dict[str, Set[str]] = {}
    post_deal_phones_set: Dict[str, Set[str]] = {}
    fbid_to_posts: Dict[str, Set[str]] = {}

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
                post_phone_leads_set[clean_pid] = set()
                post_deal_phones_set[clean_pid] = set()

            if has_phone:
                p_norm = normalize_phone(c.phone_number) or c.phone_number.strip()
                post_deal_phones_set[clean_pid].add(p_norm)

            # Thu thập FB PSID của người comment để map với cuộc trò chuyện Inbox (lấy trực tiếp từ from_id)
            fid = str(c.from_id or "").strip()
            if fid:
                if fid not in fbid_to_posts:
                    fbid_to_posts[fid] = set()
                fbid_to_posts[fid].add(clean_pid)

    # 4. Phân loại Lead từ Facebook (qua classify_leads — đồng nhất 100% với Tổng quan & Chỉ số)
    leads = {}
    if target_page_name:
        leads = classify_leads(db, start, end, page_id=target_page_name)
    else:
        page_list = fb_page_names or ["Anh Kế toán làm Data (Facebook)"]
        for p_name in page_list:
            leads.update(classify_leads(db, start, end, page_id=p_name))

    fb_leads_total = len(leads)
    fb_new_leads = sum(1 for l in leads.values() if l.is_new)
    fb_recontact_leads = sum(1 for l in leads.values() if not l.is_new)
    fb_phone_leads = sum(1 for l in leads.values() if l.has_phone)

    # Đếm số Lead và SĐT của từng bài viết từ Leads có post_id sẵn
    for l_id, l in leads.items():
        if l.post_id:
            raw_pid = str(l.post_id).strip()
            clean_pid = raw_pid.split("_")[-1] if "_" in raw_pid else raw_pid
            if clean_pid not in post_leads_set:
                post_leads_set[clean_pid] = set()
                post_phone_leads_set[clean_pid] = set()
                post_deal_phones_set[clean_pid] = set()

            post_leads_set[clean_pid].add(str(l_id))
            if l.has_phone:
                post_phone_leads_set[clean_pid].add(str(l_id))
            if l.phone_number:
                p_norm = normalize_phone(l.phone_number) or l.phone_number.strip()
                post_deal_phones_set[clean_pid].add(p_norm)

    # Ánh xạ qua Facebook PSID:
    # Khách bình luận vào Bài viết (có PSID và post_id) -> sau đó vào Inbox nhắn tin (conversation_id dạng <page_id>_<psid>)
    lead_ids = list(leads.keys())
    if lead_ids and fbid_to_posts:
        lead_convs = db.query(FactLeadActivity.lead_id, FactLeadActivity.conversation_id).filter(
            FactLeadActivity.lead_id.in_(lead_ids)
        ).all()
        for l_id, conv_id in lead_convs:
            if conv_id and "_" in conv_id and not conv_id.startswith(("tt_", "pzl_")):
                parts = conv_id.split("_")
                if len(parts) >= 2:
                    psid = parts[1].strip()
                    pids = fbid_to_posts.get(psid)
                    if pids:
                        lead_obj = leads.get(l_id)
                        p_norm = normalize_phone(lead_obj.phone_number) if lead_obj and lead_obj.phone_number else None
                        for clean_pid in pids:
                            if clean_pid not in post_leads_set:
                                post_leads_set[clean_pid] = set()
                                post_phone_leads_set[clean_pid] = set()
                                post_deal_phones_set[clean_pid] = set()
                            post_leads_set[clean_pid].add(str(l_id))
                            if lead_obj and lead_obj.has_phone:
                                post_phone_leads_set[clean_pid].add(str(l_id))
                            if p_norm:
                                post_deal_phones_set[clean_pid].add(p_norm)

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
                DealWin.source_page == target_page_id,
                DealWin.source_page == target_page_name,
                DealWin.page_id == target_page_id,
                DealWin.page_id == target_page_name,
            )
        )
    else:
        deal_query = deal_query.filter(
            or_(
                DealWin.source_page.in_(fb_page_names),
                DealWin.source_page.in_(fb_page_ids),
                DealWin.source_page.ilike("%Facebook%"),
                DealWin.page_id.in_(fb_page_names),
                DealWin.page_id.in_(fb_page_ids),
                DealWin.page_id.ilike("%Facebook%"),
            )
        )
    deals = deal_query.with_entities(DealWin.phone_number).all()
    fb_deal_wins = len(deals)

    # Khớp chính xác Deal Win với từng bài viết dựa trên SĐT thu được từ bài đó
    post_deals_map: Dict[str, int] = Counter()
    for (d_phone,) in deals:
        if d_phone:
            dp = normalize_phone(d_phone) or d_phone.strip()
            for clean_pid, pset in post_deal_phones_set.items():
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

    # 7. Phân loại 3 nguồn Lead: Quảng cáo (Ads), Bài viết (Post), Tự nhiên (Organic)
    # Lấy danh sách ID lead từ bài viết
    post_lead_ids = set()
    for cset in post_leads_set.values():
        post_lead_ids.update(cset)

    # Nhóm theo Ads (Khách bấm nhiều Ads thì tính đầy đủ cho từng mẫu Ads)
    ad_leads_map: Dict[str, Set[str]] = {}
    ad_phones_map: Dict[str, Set[str]] = {}
    ad_all_phones_map: Dict[str, Set[str]] = {}
    ad_post_counter: Dict[str, Counter] = {}

    for l_id, l in leads.items():
        if l.ad_id:
            p_norm = (normalize_phone(l.phone_number) or l.phone_number.strip()) if l.phone_number else None
            for aid in split_csv(l.ad_id):
                if aid not in ad_leads_map:
                    ad_leads_map[aid] = set()
                    ad_phones_map[aid] = set()
                    ad_all_phones_map[aid] = set()
                    ad_post_counter[aid] = Counter()
                ad_leads_map[aid].add(str(l_id))
                if p_norm:
                    ad_all_phones_map[aid].add(p_norm)
                if l.has_phone:
                    ad_phones_map[aid].add(str(l_id))
                if l.post_id:
                    ad_post_counter[aid][str(l.post_id).strip()] += 1

    # Khớp Deal Win cho từng Ad (bao gồm cả khách cho SĐT ở kỳ trước và chốt trong kỳ này)
    deal_norm_list = []
    for (d_phone,) in deals:
        if d_phone:
            dp = normalize_phone(d_phone) or d_phone.strip()
            if dp:
                deal_norm_list.append(dp)

    if deal_norm_list and ad_all_phones_map:
        unique_deal_phones = list(set(deal_norm_list))
        for row_ph, row_ad in db.query(DimLead.phone_number, DimLead.ad_id).filter(
            DimLead.phone_number.in_(unique_deal_phones),
            DimLead.ad_id.isnot(None),
        ).all():
            p_clean = normalize_phone(row_ph) or row_ph.strip()
            for aid in split_csv(row_ad):
                if aid in ad_all_phones_map:
                    ad_all_phones_map[aid].add(p_clean)

    ad_deals_map: Dict[str, int] = Counter()
    for dp in deal_norm_list:
        for aid, pset in ad_all_phones_map.items():
            if dp in pset:
                ad_deals_map[aid] += 1

    # Tính tổng số liệu 3 nguồn phân hoạch 100% khớp Tổng Lead & Tổng SĐT (giống Tổng quan & Chỉ số)
    total_ads_leads = 0
    total_ads_phones = 0
    total_post_cust = 0
    total_post_phones = 0
    organic_lead_count = 0
    organic_phone_count = 0

    for l_id, l in leads.items():
        lid_str = str(l_id)
        if l.ad_id:
            total_ads_leads += 1
            if l.has_phone:
                total_ads_phones += 1
        elif lid_str in post_lead_ids or bool(l.post_id):
            total_post_cust += 1
            if l.has_phone:
                total_post_phones += 1
        else:
            organic_lead_count += 1
            if l.has_phone:
                organic_phone_count += 1

    ads_phone_rate = round((total_ads_phones / total_ads_leads * 100), 1) if total_ads_leads > 0 else 0.0
    post_phone_rate = round((total_post_phones / total_post_cust * 100), 1) if total_post_cust > 0 else 0.0
    organic_phone_rate = round((organic_phone_count / organic_lead_count * 100), 1) if organic_lead_count > 0 else 0.0

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

    # Nhóm leads & SĐT theo ngày (khớp logic get_trend của Tổng quan & Chỉ số)
    leads_by_date: Dict[str, int] = Counter()
    phones_by_date: Dict[str, int] = Counter()
    ads_leads_by_date: Dict[str, int] = Counter()
    ads_phones_by_date: Dict[str, int] = Counter()
    post_leads_by_date: Dict[str, int] = Counter()
    post_phones_by_date: Dict[str, int] = Counter()
    organic_leads_by_date: Dict[str, int] = Counter()
    organic_phones_by_date: Dict[str, int] = Counter()

    for l_id, l in leads.items():
        lid_str = str(l_id)
        is_ad = bool(l.ad_id)
        is_post = (not is_ad) and (lid_str in post_lead_ids or bool(l.post_id))

        active_days: Set[str] = set()
        if l.is_new and l.first_created_at:
            active_days.add(l.first_created_at.strftime("%Y-%m-%d"))
        else:
            active_days.update(l.contact_days)
            if not active_days and l.phone_event_at:
                active_days.add(l.phone_event_at.strftime("%Y-%m-%d"))

        for d_str in active_days:
            leads_by_date[d_str] += 1
            if l.has_phone:
                phones_by_date[d_str] += 1
            if is_ad:
                ads_leads_by_date[d_str] += 1
                if l.has_phone:
                    ads_phones_by_date[d_str] += 1
            elif is_post:
                post_leads_by_date[d_str] += 1
                if l.has_phone:
                    post_phones_by_date[d_str] += 1
            else:
                organic_leads_by_date[d_str] += 1
                if l.has_phone:
                    organic_phones_by_date[d_str] += 1

    while day <= end:
        d_str = day.strftime("%Y-%m-%d")
        trend_data.append({
            "date": d_str,
            "posts": posts_by_date.get(d_str, 0),
            "reactions": reactions_by_date.get(d_str, 0),
            "comments": comments_by_date.get(d_str, 0),
            "leads": leads_by_date.get(d_str, 0),
            "phones": phones_by_date.get(d_str, 0),
            "ads_leads": ads_leads_by_date.get(d_str, 0),
            "ads_phones": ads_phones_by_date.get(d_str, 0),
            "post_leads": post_leads_by_date.get(d_str, 0),
            "post_phones": post_phones_by_date.get(d_str, 0),
            "organic_leads": organic_leads_by_date.get(d_str, 0),
            "organic_phones": organic_phones_by_date.get(d_str, 0),
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
        phones_c = len(post_phone_leads_set.get(clean_pid, set()))
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

    # 8.2 Danh sách Top Mẫu Ads hiệu quả (Lấy bài viết từ toàn bộ DB và đồng bộ Tên Chiến dịch từ Pancake)
    post_by_id_map = {p.post_id: p for p in posts}
    all_candidate_pids = set()
    for cnt in ad_post_counter.values():
        all_candidate_pids.update(cnt.keys())
    missing_pids = [pid for pid in all_candidate_pids if pid and pid not in post_by_id_map]
    if missing_pids:
        extra_posts = db.query(Post).options(defer(Post.payload)).filter(Post.post_id.in_(missing_pids)).all()
        for ep in extra_posts:
            post_by_id_map[ep.post_id] = ep

    ad_post_map: Dict[str, str] = {}
    for aid, cnt in ad_post_counter.items():
        if not cnt:
            continue
        best_pid = max(
            cnt.keys(),
            key=lambda k: (
                1 if (post_by_id_map.get(k) and (post_by_id_map[k].message or "").strip()) else 0,
                cnt[k],
            ),
        )
        ad_post_map[aid] = best_pid

    ads_meta = _resolve_ads_metadata(db, set(ad_leads_map.keys()))

    top_ads_data = []
    for aid, lset in ad_leads_map.items():
        c_leads = len(lset)
        c_phones = len(ad_phones_map.get(aid, set()))
        c_rate = round((c_phones / c_leads * 100), 1) if c_leads > 0 else 0.0
        c_deals = ad_deals_map.get(aid, 0)
        pid = ad_post_map.get(aid)
        post_obj = post_by_id_map.get(pid) if pid else None
        p_msg = post_obj.message if post_obj and post_obj.message else ""
        p_url = post_obj.post_url if post_obj and post_obj.post_url else (build_post_url(pid, target_page_id) if pid else None)
        meta = ads_meta.get(aid, {})
        top_ads_data.append({
            "ad_id": aid,
            "ad_name": meta.get("name") or "",
            "campaign_id": meta.get("campaign_id") or "",
            "campaign_name": meta.get("campaign_name") or "",
            "image_url": meta.get("image_url") or "",
            "post_id": pid,
            "post_url": p_url,
            "post_message": p_msg,
            "lead_count": c_leads,
            "phone_count": c_phones,
            "phone_rate": c_rate,
            "deal_count": c_deals,
        })
    top_ads_data.sort(key=lambda x: (x["phone_count"], x["lead_count"]), reverse=True)

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
            "ads_leads": total_ads_leads,
            "ads_phones": total_ads_phones,
            "ads_phone_rate": ads_phone_rate,
            "post_leads": total_post_cust,
            "post_phones": total_post_phones,
            "post_phone_rate": post_phone_rate,
            "organic_leads": organic_lead_count,
            "organic_phones": organic_phone_count,
            "organic_phone_rate": organic_phone_rate,
        },
        "channel_breakdown": {
            "ads": {
                "name": "Quảng cáo (Facebook Ads)",
                "leads": total_ads_leads,
                "phones": total_ads_phones,
                "conversion_rate": ads_phone_rate,
            },
            "post": {
                "name": "Bài viết (Post / Comment)",
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
        "top_ads": top_ads_data,
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
