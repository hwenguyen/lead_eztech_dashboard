"""Script đồng bộ danh sách Bài viết (Posts) từ các Page vào bảng posts trên Database."""
import os
import sys
import time
import argparse
import logging
from dotenv import load_dotenv

load_dotenv(".env.local")
load_dotenv(".env")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.db import SessionLocal
from database.models import Post
from database.schema import ensure_schema
from etl.pancake_client import PancakeClient
from etl.pipeline import load_pancake_pages_config, upsert_post_data, prefetch_posts, DB_BATCH
from etl.utils import resolve_canonical_page_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def sync_page_posts(
    client: PancakeClient,
    page_id: str,
    page_name: str,
    days_back: int = 90,
    limit: int = 100
) -> int:
    """Lấy posts của một page và upsert vào database."""
    logger.info(f"\n=======================================================")
    logger.info(f"ĐỒNG BỘ POSTS CHO PAGE: {page_name} (ID: {page_id})")
    logger.info(f"Giới hạn: {limit} posts | Quét trong: {days_back} ngày gần nhất")
    logger.info(f"=======================================================")

    posts_data = client.get_posts(
        page_id=page_id,
        days_back=days_back,
        limit=limit
    )

    if not posts_data:
        logger.info(f"Không có bài viết nào được tải về từ Page {page_id}.")
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
        logger.info(f"✅ Đã lưu thành công {total_saved} bài viết vào bảng posts cho Page {page_name}!")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Lỗi khi lưu bài viết Page {page_id}: {e}")
        return 0
    finally:
        db.close()

    return total_saved


def main():
    parser = argparse.ArgumentParser(description="Đồng bộ Posts từ Pancake vào bảng posts")
    parser.add_argument("--days", type=int, default=90, help="Số ngày quét bài viết gần nhất (Mặc định: 90)")
    parser.add_argument("--limit", type=int, default=100, help="Số bài viết tối đa mỗi page (Mặc định: 100)")
    parser.add_argument("--page", type=str, default=None, help="Chỉ quét cho Page ID cụ thể")
    args = parser.parse_args()

    logger.info("Khởi động quá trình đồng bộ Bài viết (Posts)...")
    ensure_schema()

    client = PancakeClient()
    pages_to_process = load_pancake_pages_config()

    if args.page:
        pages_to_process = [p for p in pages_to_process if str(p.get("page_id")) == str(args.page) or str(args.page) in str(p.get("page_id"))]
        if not pages_to_process:
            pages_to_process = [{"page_id": args.page, "page_name": resolve_canonical_page_name(args.page)}]

    if not pages_to_process:
        logger.warning("Không tìm thấy cấu hình Fanpage nào để đồng bộ posts.")
        return

    logger.info(f"Tổng số Page cần quét posts: {len(pages_to_process)}")
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
            logger.error(f"Lỗi khi đồng bộ posts cho {pname} ({pid}): {err}")

    logger.info(f"\n🎉 HOÀN TẤT ĐỒNG BỘ POSTS! Tổng cộng đã lưu/cập nhật {grand_total} bài viết trong {time.perf_counter() - t0:.1f}s.")


if __name__ == "__main__":
    main()
