"""Đồng bộ lượt xem (view_count), lượt thích & chia sẻ thật cho video TikTok qua TikWM / RapidAPI.

Pancake Public API cho kênh TikTok luôn trả về `view_count = 0`. Module này dùng API ngoài
(mặc định TikWM công khai không cần OAuth; hỗ trợ nâng cấp qua RAPIDAPI_TIKTOK_KEY nếu có)
để cập nhật `posts.view_count`, `posts.share_count`, `posts.like_count`, `posts.reactions_total`.
"""

import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import requests
from sqlalchemy import case, desc, or_
from sqlalchemy.orm import Session, defer

from database.models import Post
from etl.utils import VN_TZ, resolve_canonical_page_name

logger = logging.getLogger("TikTokViewsSync")

DEFAULT_TIKWM_API_URL = "https://www.tikwm.com/api/"
_VIDEO_ID_RE = re.compile(r"(\d{15,25})")


def extract_tiktok_video_id(post_id: Optional[str], post_url: Optional[str] = None) -> Optional[str]:
    """Bóc tách video_id dạng số của TikTok từ post_id (vd: tt_7196..._7712...) hoặc post_url."""
    if post_id:
        raw = str(post_id).strip()
        tail = raw.split("_")[-1] if "_" in raw else raw
        if tail.isdigit() and len(tail) >= 15:
            return tail
    if post_url:
        m = _VIDEO_ID_RE.search(str(post_url))
        if m:
            return m.group(1)
    return None


def fetch_tiktok_video_stats(
    video_id: str,
    post_url: Optional[str] = None,
    timeout: int = 12,
) -> Optional[Dict[str, int]]:
    """Gọi TikWM / RapidAPI lấy play_count (lượt view), digg_count (tim), comment_count, share_count."""
    target_url = f"https://www.tiktok.com/video/{video_id}" if video_id else (post_url or "").strip()
    if not target_url:
        return None

    rapid_key = os.getenv("RAPIDAPI_TIKTOK_KEY", "").strip()
    rapid_host = os.getenv("RAPIDAPI_TIKTOK_HOST", "tiktok-scraper7.p.rapidapi.com").strip()
    custom_url = os.getenv("TIKWM_API_URL", DEFAULT_TIKWM_API_URL).strip() or DEFAULT_TIKWM_API_URL

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; EzTechAnalytics/1.0)",
        "Accept": "application/json",
    }
    if rapid_key:
        endpoint = f"https://{rapid_host}/"
        headers["X-RapidAPI-Key"] = rapid_key
        headers["X-RapidAPI-Host"] = rapid_host
    else:
        endpoint = custom_url

    try:
        resp = requests.get(endpoint, params={"url": target_url}, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            logger.debug("TikTok API HTTP %s cho video %s", resp.status_code, video_id)
            return None
        payload = resp.json()
        if not isinstance(payload, dict) or payload.get("code") not in (0, None):
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None

        play_cnt = int(data.get("play_count") or data.get("view_count") or 0)
        digg_cnt = int(data.get("digg_count") or data.get("like_count") or 0)
        cmt_cnt = int(data.get("comment_count") or 0)
        share_cnt = int(data.get("share_count") or 0)
        title = str(data.get("title") or "").strip()
        return {
            "view_count": max(0, play_cnt),
            "like_count": max(0, digg_cnt),
            "comment_count": max(0, cmt_cnt),
            "share_count": max(0, share_cnt),
            "message": title,
        }
    except Exception as exc:
        logger.debug("Lỗi gọi TikTok views API cho video %s: %s", video_id, exc)
        return None


def sync_tiktok_video_views(
    db: Session,
    days_back: int = 30,
    max_videos: int = 30,
    delay_sec: float = 1.1,
    page_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Cập nhật view_count (và like/share thật) cho các video TikTok gần đây trong bảng `posts`.

    Ưu tiên cào trước các video chưa có view (`view_count = 0` / NULL), sau đó mới refresh
    các video cũ `updated_at` nhất để tránh tốn quota / rate-limit.
    """
    now_vn = datetime.now(VN_TZ).replace(tzinfo=None)
    cutoff = now_vn - timedelta(days=max(1, int(days_back)))

    query = db.query(Post).options(defer(Post.payload)).filter(
        Post.platform == "tiktok",
        Post.inserted_at >= cutoff,
        or_(Post.type.is_(None), Post.type != "livestream"),
    )
    if page_id and page_id.strip():
        clean_pid = page_id.strip()
        canonical = resolve_canonical_page_name(clean_pid, fallback=clean_pid)
        query = query.filter(
            or_(
                Post.page_id == clean_pid,
                Post.page_id == canonical,
                Post.page_name == canonical,
            )
        )

    # Ưu tiên video chưa có view hoặc chưa có mô tả (message), ưu tiên bài nhiều comment & mới nhất
    needs_sync_first = case(
        (
            or_(
                Post.view_count.is_(None),
                Post.view_count == 0,
                Post.message.is_(None),
                Post.message == "",
            ),
            0,
        ),
        else_=1,
    )
    candidates = (
        query.order_by(needs_sync_first.asc(), desc(Post.comment_count), desc(Post.inserted_at))
        .limit(max(1, min(int(max_videos), 100)))
        .all()
    )

    checked = 0
    updated = 0
    failed = 0

    for idx, post in enumerate(candidates):
        vid = extract_tiktok_video_id(post.post_id, post.post_url)
        if not vid:
            continue
        if idx > 0 and delay_sec > 0:
            time.sleep(delay_sec)

        checked += 1
        stats = fetch_tiktok_video_stats(vid, post.post_url)
        if not stats:
            failed += 1
            continue

        changed = False
        if stats["view_count"] > 0 and (post.view_count or 0) != stats["view_count"]:
            post.view_count = stats["view_count"]
            changed = True
        if stats["share_count"] > (post.share_count or 0):
            post.share_count = stats["share_count"]
            changed = True
        if stats["like_count"] > (post.like_count or 0):
            post.like_count = stats["like_count"]
            changed = True
        if stats["like_count"] > (post.reactions_total or 0):
            post.reactions_total = stats["like_count"]
            changed = True
        if stats.get("message") and not (post.message or "").strip():
            post.message = stats["message"]
            changed = True

        post.updated_at = now_vn
        if changed:
            updated += 1

    if checked > 0:
        db.commit()

    return {
        "checked": checked,
        "updated": updated,
        "failed": failed,
        "message": f"Đã kiểm tra {checked} video TikTok, cập nhật lượt xem cho {updated} video.",
    }
