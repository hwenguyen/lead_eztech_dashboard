"""Script đồng bộ danh sách Bài viết / Video (Posts) từ các kênh TikTok & Facebook vào bảng posts trên Database."""
import os
import sys
import time
import argparse
import logging
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv(".env.local")
load_dotenv(".env")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.db import SessionLocal
from database.models import Post, Comment
from database.schema import ensure_schema
from etl.pancake_client import PancakeClient
from etl.pipeline import load_pancake_pages_config, upsert_post_data, prefetch_posts, DB_BATCH
from etl.utils import resolve_canonical_page_name, build_post_url
from etl.auto_reply_rules import ALLOWED_SOURCE_PAGES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def sync_posts_from_comments(db: SessionLocal, target_page_id: Optional[str] = None) -> int:
    """
    Trích xuất toàn bộ Video TikTok / Post từ các bình luận đã có sẵn trong bảng comments.
    Đảm bảo 100% video TikTok có tương tác đều xuất hiện trong bảng posts với URL TikTok chuẩn.
    """
    logger.info("\n--- [ĐỒNG BỘ TỪ COMMENTS] Quét các bài viết/video TikTok từ bảng comments hiện có ---")
    query = db.query(
        Comment.post_id,
        Comment.page_id,
        Comment.page_name,
        Comment.post_url,
        Comment.inserted_at,
        Comment.payload
    ).filter(Comment.post_id.isnot(None))

    if target_page_id:
        clean_target = str(target_page_id).replace("tt_", "").replace("fb_", "")
        query = query.filter(
            (Comment.page_id == str(target_page_id)) |
            (Comment.page_id == clean_target) |
            (Comment.page_id == f"tt_{clean_target}")
        )

    rows = query.order_by(Comment.inserted_at.desc()).all()
    if not rows:
        logger.info("Không tìm thấy comment nào có post_id trong database.")
        return 0

    unique_posts: Dict[str, dict] = {}
    for r in rows:
        pid = str(r.post_id).strip()
        if not pid or pid in unique_posts:
            continue

        page_id = str(r.page_id or "")
        p_name = r.page_name or resolve_canonical_page_name(page_id)
        is_tiktok = page_id.startswith("tt_") or "tiktok" in p_name.lower() or pid.startswith("tt_")
        platform = "tiktok" if is_tiktok else "facebook"

        payload = r.payload if isinstance(r.payload, dict) else {}
        p_obj = payload.get("post") if isinstance(payload.get("post"), dict) else {}

        raw_url = r.post_url or p_obj.get("permalink_url") or p_obj.get("url")
        final_url = build_post_url(pid, page_id, raw_url)
        message = p_obj.get("message") or p_obj.get("title") or payload.get("snippet")
        ins_at = p_obj.get("inserted_at") or r.inserted_at

        unique_posts[pid] = {
            "post_id": pid,
            "page_id": page_id,
            "page_name": p_name,
            "platform": platform,
            "type": "video" if is_tiktok else "post",
            "message": message,
            "post_url": final_url,
            "inserted_at": ins_at,
            "payload": p_obj if p_obj else {"post_id": pid, "from_comments": True}
        }

    logger.info(f"Tìm thấy {len(unique_posts)} bài viết/video duy nhất từ bảng comments. Đang lưu vào bảng posts...")
    saved = 0
    post_list = list(unique_posts.values())
    for start in range(0, len(post_list), DB_BATCH):
        batch = post_list[start:start + DB_BATCH]
        prefetched = {"post": prefetch_posts(db, batch)}
        for p_item in batch:
            upsert_post_data(db, p_item, p_item.get("page_name", ""), commit=False, prefetched=prefetched)
        db.commit()
        saved += len(batch)

    logger.info(f"✅ Đã lưu thành công {saved} bài viết/video từ comments vào bảng posts!")
    return saved


def sync_page_posts(
    client: PancakeClient,
    page_id: str,
    page_name: str,
    days_back: int = 90,
    limit: int = 100
) -> int:
    """Lấy posts/videos của một page từ Pancake Public API và upsert vào database."""
    is_tiktok = page_id.startswith("tt_") or "tiktok" in page_name.lower()
    platform_label = "TIKTOK" if is_tiktok else "FACEBOOK"

    logger.info(f"\n=======================================================")
    logger.info(f"[{platform_label}] ĐỒNG BỘ CHO: {page_name} (ID: {page_id})")
    logger.info(f"Giới hạn: {limit} bài/video | Quét trong: {days_back} ngày gần nhất")
    logger.info(f"=======================================================")

    posts_data = client.get_posts(
        page_id=page_id,
        days_back=days_back,
        limit=limit
    )

    if not posts_data:
        logger.info(f"API Pancake không trả về bài viết nào cho Page {page_id} ({platform_label}).")
        return 0

    db = SessionLocal()
    total_saved = 0
    try:
        for start in range(0, len(posts_data), DB_BATCH):
            batch = posts_data[start:start + DB_BATCH]
            prefetched = {"post": prefetch_posts(db, batch)}
            for p_item in batch:
                upsert_post_data(db, p_item, page_name, commit=False, prefetched=prefetched)
            db.commit()
            total_saved += len(batch)
        logger.info(f"✅ Đã lưu {total_saved} {platform_label.lower()} posts vào bảng posts cho {page_name}!")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Lỗi khi lưu bài viết Page {page_id}: {e}")
        return 0
    finally:
        db.close()

    return total_saved


def main():
    parser = argparse.ArgumentParser(description="Đồng bộ Bài viết / Video (Posts) TikTok & Facebook vào bảng posts")
    parser.add_argument("--days", type=int, default=90, help="Số ngày quét bài viết gần nhất (Mặc định: 90)")
    parser.add_argument("--limit", type=int, default=100, help="Số bài viết tối đa mỗi page (Mặc định: 100)")
    parser.add_argument("--page", type=str, default=None, help="Chỉ quét cho Page ID cụ thể (vd: tt_7196601676597871618)")
    parser.add_argument("--from-comments", action="store_true", help="Chỉ trích xuất bài viết/video từ các comments đã có trong DB")
    args = parser.parse_args()

    logger.info("🚀 KHỞI ĐỘNG ĐỒNG BỘ BÀI VIẾT / VIDEO (POSTS)...")
    ensure_schema()
    db = SessionLocal()

    if args.from_comments:
        try:
            sync_posts_from_comments(db, target_page_id=args.page)
        finally:
            db.close()
        return

    # Lấy danh sách Fanpage từ biến môi trường hoặc fallback về ALLOWED_SOURCE_PAGES (TikTok & Facebook)
    pages_to_process = load_pancake_pages_config()
    if not pages_to_process:
        logger.info(f"Không có secret PANCAKE_PAGES_JSON, tự động nạp từ ALLOWED_SOURCE_PAGES ({len(ALLOWED_SOURCE_PAGES)} kênh nguồn)...")
        pages_to_process = [
            {"page_id": pid, "page_name": resolve_canonical_page_name(pid)}
            for pid in ALLOWED_SOURCE_PAGES
        ]

    if args.page:
        pages_to_process = [
            p for p in pages_to_process
            if str(p.get("page_id")) == str(args.page) or str(args.page) in str(p.get("page_id"))
        ]
        if not pages_to_process:
            pages_to_process = [{"page_id": args.page, "page_name": resolve_canonical_page_name(args.page)}]

    logger.info(f"Danh sách các kênh cần đồng bộ ({len(pages_to_process)}):")
    for p in pages_to_process:
        pid = str(p.get("page_id"))
        pname = p.get("page_name") or resolve_canonical_page_name(pid)
        is_tt = pid.startswith("tt_") or "tiktok" in pname.lower()
        tag = "[TikTok]" if is_tt else "[Facebook]"
        logger.info(f"  • {tag} {pname} (ID: {pid})")

    client = PancakeClient()
    grand_total = 0
    t0 = time.perf_counter()

    for p_conf in pages_to_process:
        pid = str(p_conf.get("page_id"))
        pname = p_conf.get("page_name") or resolve_canonical_page_name(pid)
        try:
            saved = sync_page_posts(
                client=client,
                page_id=pid,
                page_name=pname,
                days_back=args.days,
                limit=args.limit
            )
            grand_total += saved
        except Exception as err:
            logger.error(f"Lỗi khi đồng bộ posts qua API cho {pname} ({pid}): {err}")

    # Đồng bộ thêm các video từ comment threads để không bỏ sót video nào
    try:
        cmt_saved = sync_posts_from_comments(db, target_page_id=args.page)
        grand_total += cmt_saved
    except Exception as e_cmt:
        logger.warning(f"Lỗi khi trích xuất video từ comments: {e_cmt}")
    finally:
        db.close()

    logger.info(f"\n🎉 HOÀN TẤT ĐỒNG BỘ! Tổng cộng đã lưu/cập nhật bài viết/video trong {time.perf_counter() - t0:.1f}s.")


if __name__ == "__main__":
    main()
