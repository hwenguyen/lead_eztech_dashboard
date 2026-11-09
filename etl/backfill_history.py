"""
Script cào vét dữ liệu lịch sử cũ (Backfill) từ Pancake API vào Database.
Cơ chế tự động:
- Tự động tìm hội thoại CŨ NHẤT hiện có trong DB của từng Page làm điểm xuất phát.
- Sử dụng last_conversation_id để lùi dần về quá khứ mà KHÔNG bị tải lại dữ liệu đã có trong DB.
- Tải kèm tin nhắn mới, lưu DimLead, FactLeadActivity và RawConversation theo batch an toàn.
- Có thể dừng bất cứ lúc nào (Ctrl+C hoặc qua API) và chạy lại tiếp tục từ mốc cũ nhất vừa lưu (Resumable).
"""

import os
import sys

# Đảm bảo đường dẫn gốc của project có trong sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import argparse
import logging
import threading
from datetime import datetime
from typing import List, Optional, Dict, Any

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


class BackfillManager:
    """Quản lý trạng thái tiến trình Backfill để giao tiếp với API & UI."""

    def __init__(self):
        self.lock = threading.Lock()
        self.is_running: bool = False
        self.stop_requested: bool = False
        self.current_page: str = ""
        self.current_page_idx: int = 0
        self.total_pages: int = 0
        self.total_added: int = 0
        self.current_date: str = ""
        self.logs: List[str] = []
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.error: Optional[str] = None
        self._thread: Optional[threading.Thread] = None

    def log(self, msg: str):
        logger.info(msg)
        with self.lock:
            ts = datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{ts}] {msg}")
            if len(self.logs) > 60:
                self.logs = self.logs[-60:]

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "isRunning": self.is_running,
                "currentPage": self.current_page,
                "currentPageIdx": self.current_page_idx,
                "totalPages": self.total_pages,
                "totalAdded": self.total_added,
                "currentDate": self.current_date,
                "startedAt": self.started_at,
                "finishedAt": self.finished_at,
                "error": self.error,
                "logs": list(self.logs),
            }

    def stop(self):
        with self.lock:
            if self.is_running:
                self.stop_requested = True
                self.log("⚠️ Đã gửi yêu cầu dừng cào dữ liệu...")
                return True, "Đang dừng tiến trình cào..."
            return False, "Không có tiến trình nào đang chạy."

    def start_async(
        self,
        page_term: str = "",
        limit: int = 2000,
        chunk: int = 120,
        stop_date: str = "2024-01-01"
    ):
        with self.lock:
            if self.is_running:
                return False, f"Tiến trình đang chạy ({self.current_page}). Không thể bắt đầu lượt mới!"
            self.is_running = True
            self.stop_requested = False
            self.total_added = 0
            self.current_page = "Khởi tạo..."
            self.current_date = ""
            self.error = None
            self.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.finished_at = None
            self.logs.clear()

        def worker():
            try:
                run_backfill_process(
                    manager=self,
                    page_term=page_term,
                    limit=limit,
                    chunk=chunk,
                    stop_date_str=stop_date
                )
            except Exception as e:
                with self.lock:
                    self.error = str(e)
                self.log(f"❌ Lỗi tiến trình Backfill: {e}")
            finally:
                with self.lock:
                    self.is_running = False
                    self.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.log("🏁 Tiến trình cào lịch sử đã kết thúc.")

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()
        return True, "Đã khởi động tiến trình cào lịch sử thành công."


backfill_manager = BackfillManager()


def backfill_page(
    page_info: dict,
    max_convs_per_page: int = 3000,
    chunk_size: int = 120,
    stop_date_str: str = "2024-01-01",
    manager: Optional[BackfillManager] = None
) -> int:
    pid = page_info["page_id"]
    preset_name = page_info.get("page_name")
    cname = preset_name or resolve_canonical_page_name(pid, fallback=pid)
    token = page_info.get("token")

    stop_dt = datetime.strptime(stop_date_str, "%Y-%m-%d")

    db = SessionLocal()
    earliest_id, earliest_dt = get_earliest_conv_info(db, pid, cname)
    db.close()

    msg_start = f"▶ BẮT ĐẦU CÀO LỊCH SỬ CHO PAGE: {cname} ({pid})"
    if manager:
        manager.log(msg_start)
    else:
        logger.info(msg_start)

    if earliest_dt:
        earliest_info = f"  Mốc cũ nhất hiện có trong DB: {earliest_dt.strftime('%d/%m/%Y %H:%M')} (ID: {earliest_id})"
    else:
        earliest_info = "  Chưa có dữ liệu nào trong DB -> Cào từ mới nhất về cũ nhất..."
    
    if manager:
        manager.log(earliest_info)
    else:
        logger.info(earliest_info)

    client = PancakeClient(api_token=token)
    current_last_id = earliest_id
    total_added_page = 0
    all_page_changed_phones = set()

    while total_added_page < max_convs_per_page:
        if manager and manager.stop_requested:
            manager.log(f"⚠️ Nhận tín hiệu dừng: Tạm ngừng cào page {cname}.")
            break

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
            msg = f"✅ Page '{cname}': Đã quét đến mốc đầu tiên (không còn hội thoại cũ hơn trên Pancake)."
            if manager:
                manager.log(msg)
            else:
                logger.info(msg)
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
            err_msg = f"❌ Lỗi ghi DB khi lưu batch của Page {cname}: {e}"
            if manager:
                manager.log(err_msg)
            else:
                logger.error(err_msg)
            break
        finally:
            db.close()

        total_added_page += len(convs)
        new_last_id = convs[-1].get("id")
        oldest_dt_in_batch = parse_pancake_date(convs[-1].get("updated_at") or convs[-1].get("inserted_at"))
        dt_str = oldest_dt_in_batch.strftime("%d/%m/%Y %H:%M") if oldest_dt_in_batch else "N/A"

        progress_msg = (
            f"  [+ {len(convs)} hội thoại ({fetch_secs:.1f}s)] "
            f"Lùi đến ngày: {dt_str} | "
            f"Đã cào page này: {total_added_page}"
        )
        if manager:
            manager.current_date = dt_str
            with manager.lock:
                manager.total_added += len(convs)
            manager.log(progress_msg)
        else:
            logger.info(progress_msg)

        if new_last_id == current_last_id:
            logger.info("Không có ID cũ hơn để phân trang tiếp. Dừng.")
            break
        current_last_id = new_last_id

        if oldest_dt_in_batch and oldest_dt_in_batch.replace(tzinfo=None) < stop_dt:
            msg_stop = f"⚡ Đã đạt mốc thời gian yêu cầu ({stop_date_str}). Hoàn tất cào page {cname}!"
            if manager:
                manager.log(msg_stop)
            else:
                logger.info(msg_stop)
            break

        time.sleep(0.4)

    # Đồng bộ Deal Win cho các SĐT vừa cào được
    if all_page_changed_phones:
        try:
            db_sync = SessionLocal()
            deals_sync, students_sync, _ = sync_all_deals_with_dim_leads(db_sync, target_phones=all_page_changed_phones)
            sync_msg = f"  Đồng bộ Deal Win: {deals_sync} deals, {students_sync} học viên."
            if manager:
                manager.log(sync_msg)
            else:
                logger.info(sync_msg)
            db_sync.close()
        except Exception as e:
            logger.warning(f"  Không thể đồng bộ Deal Win: {e}")

    return total_added_page


def run_backfill_process(
    manager: Optional[BackfillManager] = None,
    page_term: str = "",
    limit: int = 3000,
    chunk: int = 120,
    stop_date_str: str = "2024-01-01"
) -> int:
    ensure_schema()
    all_pages = load_pancake_pages_config()
    if not all_pages:
        if manager:
            manager.log("❌ Không tìm thấy cấu hình page trong env!")
        return 0

    targets = []
    if page_term.strip():
        term = page_term.strip().lower()
        for p in all_pages:
            cname = resolve_canonical_page_name(p["page_id"], fallback=p.get("page_name") or "")
            if term in p["page_id"].lower() or term in cname.lower():
                targets.append(p)
        if not targets:
            if manager:
                manager.log(f"❌ Không tìm thấy page nào khớp với '{page_term}'")
            return 0
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

    if manager:
        with manager.lock:
            manager.total_pages = len(targets)
        manager.log(f"Bắt đầu Backfill cho {len(targets)} page. Giới hạn: {limit}/page, Dừng trước mốc: {stop_date_str}")

    start_total = time.perf_counter()
    grand_total = 0

    for idx, p in enumerate(targets, 1):
        if manager and manager.stop_requested:
            manager.log("⚠️ Quá trình Backfill dừng theo yêu cầu người dùng.")
            break

        cname = resolve_canonical_page_name(p["page_id"], fallback=p.get("page_name") or "")
        if manager:
            with manager.lock:
                manager.current_page = f"{cname} ({idx}/{len(targets)})"
                manager.current_page_idx = idx

        added = backfill_page(
            page_info=p,
            max_convs_per_page=limit,
            chunk_size=chunk,
            stop_date_str=stop_date_str,
            manager=manager
        )
        grand_total += added

    # Xóa cache trên Render API
    try:
        import requests
        secret = os.getenv("ADMIN_SECRET_KEY") or os.getenv("WEBHOOK_SECRET")
        headers = {"X-Admin-Secret": secret} if secret else {}
        requests.post("https://pancake-lead-api.onrender.com/api/admin/clear-cache", headers=headers, timeout=5)
        if manager:
            manager.log("✨ Đã xóa cache trên Dashboard Render!")
    except Exception:
        pass

    finish_msg = f"🎉 HOÀN TẤT BACKFILL! Tổng đã cào thêm vào DB: {grand_total} hội thoại ({time.perf_counter() - start_total:.1f}s)."
    if manager:
        manager.log(finish_msg)
    else:
        logger.info(finish_msg)

    return grand_total


def main():
    parser = argparse.ArgumentParser(description="Backfill Pancake Historical Conversations")
    parser.add_argument("--page", type=str, default="", help="Chỉ định Page ID hoặc tên Page cần cào (để trống để cào tất cả)")
    parser.add_argument("--limit", type=int, default=3000, help="Số hội thoại tối đa cào thêm cho mỗi page (mặc định: 3000)")
    parser.add_argument("--chunk", type=int, default=120, help="Số hội thoại mỗi lượt cào và lưu DB (mặc định: 120)")
    parser.add_argument("--stop-date", type=str, default="2024-01-01", help="Mốc ngày dừng cào YYYY-MM-DD (mặc định: 2024-01-01)")
    args = parser.parse_args()

    run_backfill_process(
        manager=None,
        page_term=args.page,
        limit=args.limit,
        chunk=args.chunk,
        stop_date_str=args.stop_date
    )


if __name__ == "__main__":
    main()
