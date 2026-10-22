"""Script xóa các bản ghi FAILED trong bảng bot_auto_replies để Bot có thể quét và gửi lại."""
import os
import sys
import argparse
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv(".env.local")
load_dotenv(".env")

# Thêm thư mục gốc vào PYTHONPATH nếu cần
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.db import SessionLocal
from database.models import BotAutoReplyLog


def clean_failed_replies(dry_run: bool = False, days: int = None, page_id: str = None) -> int:
    db = SessionLocal()
    try:
        query = db.query(BotAutoReplyLog).filter(BotAutoReplyLog.status == "FAILED")
        
        if page_id:
            query = query.filter(BotAutoReplyLog.page_id == str(page_id))
            
        if days and days > 0:
            from datetime import datetime, timedelta
            from etl.utils import VN_TZ
            cutoff = datetime.now(VN_TZ).replace(tzinfo=None) - timedelta(days=days)
            query = query.filter(BotAutoReplyLog.sent_at >= cutoff)
            
        count = query.count()
        if count == 0:
            print(" Không có bản ghi FAILED nào trong bảng bot_auto_replies.")
            return 0

        print(f"🔍 Tìm thấy {count} bản ghi FAILED trong bảng bot_auto_replies:")
        sample_rows = query.order_by(BotAutoReplyLog.sent_at.desc()).limit(5).all()
        for r in sample_rows:
            sent_str = r.sent_at.strftime("%Y-%m-%d %H:%M:%S") if r.sent_at else "N/A"
            err_short = (r.error_message or "N/A")[:60]
            print(f"  • ID: {r.id} | Page: {r.page_id} | Case: {r.case_id} | Conv: {r.conversation_id} | Lúc: {sent_str}")
            print(f"    Lỗi: {err_short}")

        if dry_run:
            print(f"\n=> [DRY-RUN] Giữ nguyên dữ liệu, không thực hiện xóa {count} bản ghi.")
            return count

        deleted = query.delete(synchronize_session=False)
        db.commit()
        print(f"\n✅ ĐÃ XÓA THÀNH CÔNG {deleted} BẢN GHI FAILED KHỎI DATABASE!")
        print("💡 Giờ đây Bot có thể quét và tự động gửi lại phản hồi cho các comment/inbox này.")
        return deleted
    except Exception as e:
        db.rollback()
        print(f"❌ Lỗi khi xóa bản ghi FAILED: {e}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Xóa các bản ghi FAILED trong bảng bot_auto_replies")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ xem danh sách, không xóa thật")
    parser.add_argument("--days", type=int, default=None, help="Chỉ xóa các bản ghi FAILED trong N ngày gần nhất")
    parser.add_argument("--page", type=str, default=None, help="Chỉ xóa cho Page ID cụ thể")
    args = parser.parse_args()

    clean_failed_replies(dry_run=args.dry_run, days=args.days, page_id=args.page)
