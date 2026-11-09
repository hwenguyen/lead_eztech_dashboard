"""
Script cào vét dữ liệu lịch sử cũ (Backfill) từ Pancake API vào Database.
Cơ chế tự động:
- Tự động tìm hội thoại CŨ NHẤT hiện có trong DB của từng Page làm điểm xuất phát.
- Sử dụng last_conversation_id để lùi dần về quá khứ mà KHÔNG bị tải lại dữ liệu đã có trong DB.
- Tải kèm tin nhắn mới, lưu DimLead, FactLeadActivity và RawConversation theo batch an toàn.
- Có thể dừng bất cứ lúc nào (Ctrl+C) và chạy lại tiếp tục từ mốc cũ nhất vừa lưu (Resumable).
"""

import os
import sys

# Đảm bảo đường dẫn gốc của project có trong sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import argparse
import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import or_
from database.db import SessionLocal
from database.models import RawConversation, DimLead, FactLeadActivity
from database.schema import ensure_schema
from database.deal_sync import sync_all_deals_with_dim_leads
from etl.pancake_client import PancakeClient
from etl.pipeline import load_pancake_pages_config, prefetch_records, upsert_lead_data
from etl.utils import resolve_canonical_page_name, resolve_phone, parse_pancake_date

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("backfill")


def get_earliest_conv_info(db, page_id: str, canonical_name: str):
    """Tìm hội thoại cũ nhất trong DB của page."""
    row = db.query(
        FactLeadActivity.conversation_id,
        FactLeadActivity.contacted_at
    ).join(
        DimLead, DimLead.id == FactLeadActivity.lead_id
    ).filter(
        or_(
            DimLead.page_id == page_id,
            DimLead.page_id == canonical_name
        )
    ).order_by(FactLeadActivity.contacted_at.asc()).first()

    if row and row[0]:
        return row[0], row[1]
    return None, None


def backfill_page(
    page_info: dict,
    max_convs_per_page: int = 5000,
    chunk_size: int = 180,
    stop_date_str: str = "2024-01-01"
) -> int:
    pid = page_info["page_id"]
    preset_name = page_info.get("page_name")
    cname = preset_name or resolve_canonical_page_name(pid, fallback=pid)
    token = page_info.get("token")

    stop_dt = datetime.strptime(stop_date_str, "%Y-%m-%d")

    db = SessionLocal()
    earliest_id, earliest_dt = get_earliest_conv_info(db, pid, cname)
    db.close()

    logger.info(f"\n{'='*70}")
    logger.info(f"▶ BẮT ĐẦU CÀO LỊCH SỬ CHO PAGE: {cname} ({pid})")
    if earliest_dt:
        logger.info(f"  Mốc cũ nhất hiện có trong DB: {earliest_dt} (ID: {earliest_id})")
        logger.info(f"  Hệ thống sẽ lùi tiếp về trước mốc này...")
    else:
        logger.info(f"  Chưa có dữ liệu nào trong DB -> Bắt đầu cào từ mới nhất về cũ nhất...")
    logger.info(f"{'='*70}")

    client = PancakeClient(api_token=token)
    current_last_id = earliest_id
    total_added_page = 0
    all_page_changed_phones = set()

    while total_added_page < max_convs_per_page:
        step_limit = min(chunk_size, max_convs_per_page - total_added_page)
        client.limit = step_limit

        t_fetch = time.perf_counter()
        convs = client.get_conversations(
            page_id=pid,
            days_back=None,
            start_after_id=current_last_id
        )
        fetch_secs = time.perf_counter() - t_fetch

        if not convs:
            logger.info(f"✅ Page '{cname}': Pancake API báo không còn hội thoại cũ hơn. Đã quét đến mốc đầu tiên!")
            break

        db = SessionLocal()
        try:
            prefetched = prefetch_records(db, convs)
            for c in convs:
                p_ph, _ = resolve_phone(c)
                if p_ph:
                    all_page_changed_phones.add(p_ph)
                upsert_lead_data(db, c, cname, commit=False, prefetched=prefetched)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"❌ Lỗi ghi DB khi lưu batch của Page {cname}: {e}")
            break
        finally:
            db.close()

        total_added_page += len(convs)
        new_last_id = convs[-1].get("id")
        oldest_dt_in_batch = parse_pancake_date(convs[-1].get("updated_at") or convs[-1].get("inserted_at"))
        dt_str = oldest_dt_in_batch.strftime("%d/%m/%Y %H:%M") if oldest_dt_in_batch else "N/A"

        logger.info(
            f"  [+ {len(convs)} hội thoại ({fetch_secs:.1f}s)] "
            f"Lùi đến ngày: {dt_str} | "
            f"Tổng đã cào thêm cho page này: {total_added_page}"
        )

        if new_last_id == current_last_id:
            logger.info("Không có ID cũ hơn để phân trang tiếp. Dừng.")
            break
        current_last_id = new_last_id

        if oldest_dt_in_batch and oldest_dt_in_batch.replace(tzinfo=None) < stop_dt:
            logger.info(f"⚡ Đã đạt mốc thời gian yêu cầu ({stop_date_str}). Hoàn tất cào page {cname}!")
            break

        time.sleep(0.5)

    # Đồng bộ Deal Win cho các SĐT vừa cào được
    if all_page_changed_phones:
        try:
            db_sync = SessionLocal()
            deals_sync, students_sync, _ = sync_all_deals_with_dim_leads(db_sync, target_phones=all_page_changed_phones)
            logger.info(f"  Đồng bộ Deal Win cho SĐT mới cào: {deals_sync} deals, {students_sync} học viên.")
            db_sync.close()
        except Exception as e:
            logger.warning(f"  Không thể đồng bộ Deal Win: {e}")

    return total_added_page


def main():
    parser = argparse.ArgumentParser(description="Backfill Pancake Historical Conversations")
    parser.add_argument("--page", type=str, default="", help="Chỉ định Page ID hoặc tên Page cần cào (để trống để cào tất cả)")
    parser.add_argument("--limit", type=int, default=3000, help="Số hội thoại tối đa cào thêm cho mỗi page (mặc định: 3000)")
    parser.add_argument("--chunk", type=int, default=180, help="Số hội thoại mỗi lượt cào và lưu DB (mặc định: 180)")
    parser.add_argument("--stop-date", type=str, default="2024-01-01", help="Mốc ngày dừng cào YYYY-MM-DD (mặc định: 2024-01-01)")
    args = parser.parse_args()

    ensure_schema()
    all_pages = load_pancake_pages_config()
    if not all_pages:
        logger.error("Không tìm thấy cấu hình page trong env!")
        return

    targets = []
    if args.page.strip():
        term = args.page.strip().lower()
        for p in all_pages:
            cname = resolve_canonical_page_name(p["page_id"], fallback=p.get("page_name") or "")
            if term in p["page_id"].lower() or term in cname.lower():
                targets.append(p)
        if not targets:
            logger.error(f"Không tìm thấy page nào khớp với '{args.page}'")
            return
    else:
        # Ưu tiên cào các page thiếu nhiều dữ liệu trước
        priority_order = [
            "Eztech Phân Tích Dữ Liệu",
            "Tuấn Anh Data",
            "Anh Kế toán làm Data (TikTok)",
            "Chị Kế Toán GenZ",
            "Hiền Minh Eztech",
            "Anh Kế toán làm Data (Facebook)",
            "Eztech Consultant",
            "Hành trang cho kế toán",
            "Học Kế toán cùng EzTech",
            "Anh kế toán Daily",
        ]
        def sort_key(p):
            cname = resolve_canonical_page_name(p["page_id"], fallback=p.get("page_name") or "")
            for idx, item in enumerate(priority_order):
                if item.lower() in cname.lower():
                    return idx
            return 99
        targets = sorted(all_pages, key=sort_key)

    logger.info(f"Bắt đầu Backfill cho {len(targets)} page. Giới hạn: {args.limit} hội thoại/page, Dừng trước mốc: {args.stop_date}")
    start_total = time.perf_counter()
    grand_total = 0

    for idx, p in enumerate(targets, 1):
        cname = resolve_canonical_page_name(p["page_id"], fallback=p.get("page_name") or "")
        logger.info(f"\n[Page {idx}/{len(targets)}] {cname}")
        added = backfill_page(
            page_info=p,
            max_convs_per_page=args.limit,
            chunk_size=args.chunk,
            stop_date_str=args.stop_date
        )
        grand_total += added

    # Xóa cache trên Render API
    try:
        import requests
        secret = os.getenv("ADMIN_SECRET_KEY") or os.getenv("WEBHOOK_SECRET")
        headers = {"X-Admin-Secret": secret} if secret else {}
        requests.post("https://pancake-lead-api.onrender.com/api/admin/clear-cache", headers=headers, timeout=5)
        logger.info("Đã xóa cache trên Dashboard Render!")
    except Exception:
        pass

    logger.info(f"\n🎉 HOÀN TẤT TOÀN BỘ QUÁ TRÌNH BACKFILL!")
    logger.info(f"Tổng số hội thoại lịch sử đã cào thêm vào DB: {grand_total} hội thoại.")
    logger.info(f"Thời gian thực thi: {time.perf_counter() - start_total:.1f}s.")


if __name__ == "__main__":
    main()
