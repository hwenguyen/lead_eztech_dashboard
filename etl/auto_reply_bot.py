"""
================================================================================
BOT TỰ ĐỘNG GỬI TIN NHẮN PHẢN HỒI THEO KỊCH BẢN (AUTO-REPLY BOT)
================================================================================
Cơ chế hoạt động:
1. Đọc tin nhắn mới nhất từ các kênh Lead nguồn (Facebook, TikTok).
2. Kiểm tra nếu tin nhắn cuối cùng của khách khớp với kịch bản (xin file, cộng đồng, tư vấn...).
3. Chốt chặn an toàn:
   - Nếu Admin/Nhân viên đã trả lời sau tin nhắn đó -> BỎ QUA (không nhắn đè).
   - Nếu Bot đã từng gửi kịch bản đó cho khách -> BỎ QUA (không spam lặp lại).
4. Gửi tin nhắn tự động qua Pancake Public API v1.
5. Hỗ trợ chế độ DRY_RUN (mặc định) để kiểm tra log an toàn trước khi gửi thật.
================================================================================
"""

import os
import sys
import time
import re
import unicodedata
import logging
import argparse
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

from dotenv import load_dotenv
load_dotenv(".env.local")
load_dotenv(".env")

from database.db import SessionLocal
from database.models import BotAutoReplyLog, RawConversation
from database.schema import ensure_schema
from etl.pancake_client import PancakeClient
from etl.utils import VN_TZ, is_page_id, resolve_canonical_page_name
from etl.auto_reply_rules import AUTO_REPLY_RULES, ALLOWED_SOURCE_PAGES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def strip_accents(text: str) -> str:
    """Loại bỏ dấu tiếng Việt để so khớp từ khóa chính xác cả khi khách gõ không dấu."""
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", text).lower().strip()


def normalize_message(text: str) -> Tuple[str, str]:
    """Loại bỏ thẻ HTML và trả về cả text gốc chữ thường và text đã bỏ dấu."""
    # Bóc tách và loại bỏ các thẻ HTML như <div>, <span>, <Copy>...
    clean_text = re.sub(r"<[^>]+>", " ", text or "")
    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    lower = clean_text.lower()
    no_accents = strip_accents(clean_text)
    return lower, no_accents


def match_rule(customer_message: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    So khớp tin nhắn của khách hàng với danh sách AUTO_REPLY_RULES.
    Trả về (Rule khớp, Từ khóa đã khớp) hoặc (None, None).
    """
    if not customer_message:
        return None, None

    lower_msg, no_accents_msg = normalize_message(customer_message)

    # Sắp xếp các rule theo priority tăng dần
    sorted_rules = sorted(
        [r for r in AUTO_REPLY_RULES if r.get("enabled", True)],
        key=lambda x: x.get("priority", 99)
    )

    for rule in sorted_rules:
        for kw in rule.get("keywords", []):
            kw_lower = kw.lower().strip()
            kw_no_accents = strip_accents(kw)
            # Kiểm tra xem từ khóa có nằm trong tin nhắn (có dấu hoặc không dấu)
            if kw_lower in lower_msg or kw_no_accents in no_accents_msg:
                return rule, kw

    return None, None


def should_reply(
    conv: Dict[str, Any],
    page_id: str,
    db: SessionLocal
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str], Optional[str], str]:
    """
    Kiểm tra xem hội thoại có đủ điều kiện để Bot gửi tin nhắn tự động không.
    Trả về: (can_reply: bool, rule, matched_kw, customer_message, reason)
    """
    conv_id = str(conv.get("id") or conv.get("pancake_id") or "")
    if not conv_id:
        return False, None, None, None, "Không có conversation_id"

    # 1. Chốt chặn kênh: Chỉ áp dụng cho các kênh Lead nguồn đã cấu hình
    clean_pid = str(page_id).strip()
    clean_num = re.sub(r"^(pzl_|tt_|fb_)", "", clean_pid)
    is_allowed = False
    for allowed_p in ALLOWED_SOURCE_PAGES:
        if allowed_p in (clean_pid, clean_num):
            is_allowed = True
            break
    if not is_allowed:
        return False, None, None, None, f"Kênh {page_id} không thuộc danh sách lead nguồn cho phép"

    # 2. Kiểm tra danh sách tin nhắn
    messages = conv.get("messages", [])
    if not messages:
        return False, None, None, None, "Hội thoại không có tin nhắn nào"

    # Lọc ra các tin nhắn hợp lệ (bỏ qua tin cache dummy)
    valid_msgs = [m for m in messages if isinstance(m, dict) and m.get("message") and not m.get("is_cached")]
    if not valid_msgs:
        return False, None, None, None, "Không có tin nhắn thực tế để phân tích"

    # 3. Chốt chặn: Tin nhắn CUỐI CÙNG trong hội thoại phải là của KHÁCH HÀNG
    last_msg = valid_msgs[-1]
    if str(last_msg.get("role")).lower() == "admin":
        return False, None, None, None, "Admin / Nhân viên đã trả lời tin nhắn cuối cùng"

    # 4. Tìm tin nhắn gần nhất của khách hàng để so khớp
    last_cust_msg = None
    for m in reversed(valid_msgs):
        if str(m.get("role")).lower() in ("khách hàng", "customer", "user"):
            last_cust_msg = m
            break
    if not last_cust_msg:
        return False, None, None, None, "Không tìm thấy tin nhắn nào của khách hàng"

    cust_text = str(last_cust_msg.get("message") or "").strip()
    rule, matched_kw = match_rule(cust_text)
    if not rule:
        return False, None, None, cust_text, "Không khớp từ khóa của kịch bản nào"

    case_id = rule.get("case_id")

    # 5. Chốt chặn chống spam: Kiểm tra DB xem Bot đã từng gửi kịch bản này cho hội thoại này chưa
    existing_sent = db.query(BotAutoReplyLog.id).filter(
        BotAutoReplyLog.conversation_id == conv_id,
        BotAutoReplyLog.case_id == case_id,
        BotAutoReplyLog.status == "SENT"
    ).first()
    if existing_sent:
        return False, rule, matched_kw, cust_text, f"Đã từng gửi kịch bản [{case_id}] trước đây (chống spam)"

    return True, rule, matched_kw, cust_text, "Đủ điều kiện gửi"


def run_auto_reply_bot(
    dry_run: bool = True,
    days_back: int = 1,
    limit_per_page: int = 100,
    from_db: bool = False
):
    """
    Hàm thực thi chính của Bot:
    - dry_run=True: Chỉ quét và in ra log các khách đủ điều kiện (KHÔNG gửi thật).
    - dry_run=False: Gửi tin nhắn thật qua Pancake API.
    """
    mode_text = "DRY-RUN (CHẠY THỬ NGHIỆM - KHÔNG GỬI THẬT)" if dry_run else "LIVE (GỬI THẬT QUA PANCAKE API)"
    logger.info("=" * 80)
    logger.info(f"KHỞI ĐỘNG AUTO-REPLY BOT | CHẾ ĐỘ: {mode_text}")
    logger.info(f"Quét các hội thoại trong {days_back} ngày gần nhất (tối đa {limit_per_page}/page)")
    logger.info("=" * 80)

    # Đảm bảo bảng lưu lịch sử bot đã sẵn sàng
    ensure_schema()
    db = SessionLocal()

    # Nạp danh sách page cấu hình từ môi trường
    from etl.pipeline import load_pancake_pages_config
    configured_pages = load_pancake_pages_config()
    if not configured_pages:
        configured_pages = [{"page_id": pid} for pid in ALLOWED_SOURCE_PAGES]

    total_scanned = 0
    total_matched = 0
    total_sent = 0
    total_failed = 0

    try:
        for p_info in configured_pages:
            page_id = str(p_info.get("page_id", "")).strip()
            preset_name = p_info.get("name", "")
            page_token = p_info.get("token")

            # Chỉ xử lý các kênh Lead nguồn được phép
            clean_pid = page_id.strip()
            clean_num = re.sub(r"^(pzl_|tt_|fb_)", "", clean_pid)
            if not any(allowed in (clean_pid, clean_num) for allowed in ALLOWED_SOURCE_PAGES):
                continue

            canonical_name = resolve_canonical_page_name(page_id, fallback=preset_name or page_id)
            logger.info(f"\n--- Đang kiểm tra Page: {canonical_name} ({page_id}) ---")

            if from_db:
                # Quét trực tiếp từ RawConversation trong Database
                query = db.query(RawConversation).filter(
                    RawConversation.page_id.in_([page_id, canonical_name, clean_num])
                )
                if days_back and days_back > 0:
                    cutoff = datetime.now(VN_TZ).replace(tzinfo=None) - timedelta(days=days_back)
                    query = query.filter(RawConversation.created_at >= cutoff)
                raw_rows = query.order_by(RawConversation.created_at.desc()).limit(limit_per_page).all()
                conversations = [r.payload for r in raw_rows if isinstance(r.payload, dict)]
            else:
                client = PancakeClient(api_token=page_token)
                client.limit = limit_per_page

                conversations = client.get_conversations(
                    page_id=page_id,
                    days_back=days_back
                )

            for conv in conversations:
                total_scanned += 1
                cid = str(conv.get("id", ""))
                cust_name = conv.get("customer_name") or "Khách hàng"
                cust_phone = conv.get("phone_number") or "Chưa có SĐT"

                can_send, rule, matched_kw, cust_msg, reason = should_reply(conv, page_id, db)

                if not can_send:
                    continue

                total_matched += 1
                case_id = rule["case_id"]
                rule_name = rule["name"]
                reply_text = rule["message"]

                logger.info(f"\n[PHÁT HIỆN KHÁCH PHÙ HỢP]")
                logger.info(f"  • Khách hàng : {cust_name} (SĐT: {cust_phone})")
                logger.info(f"  • Hội thoại  : {cid}")
                logger.info(f"  • Khách nhắn : \"{cust_msg}\"")
                logger.info(f"  • Kịch bản   : [{rule_name}] (từ khóa: \"{matched_kw}\")")
                logger.info(f"  • Nội dung sẽ gửi:\n    \"{reply_text}\"")

                if dry_run:
                    logger.info("  => [DRY-RUN] Bỏ qua bước gửi thật.")
                    # Ghi log trạng thái DRY_RUN vào DB để theo dõi
                    log_entry = BotAutoReplyLog(
                        conversation_id=cid,
                        customer_id=str(conv.get("customer_id") or ""),
                        page_id=page_id,
                        case_id=case_id,
                        customer_message=cust_msg,
                        reply_message=reply_text,
                        status="DRY_RUN",
                    )
                    db.add(log_entry)
                    db.commit()
                else:
                    # GỬI THẬT QUA PANCAKE API
                    logger.info(f"  => 🚀 ĐANG GỬI TIN NHẮN QUA PANCAKE API...")
                    res = client.send_message(page_id, cid, reply_text)
                    success = res.get("success", False)

                    status = "SENT" if success else "FAILED"
                    err = None if success else str(res.get("message") or res)

                    log_entry = BotAutoReplyLog(
                        conversation_id=cid,
                        customer_id=str(conv.get("customer_id") or ""),
                        page_id=page_id,
                        case_id=case_id,
                        customer_message=cust_msg,
                        reply_message=reply_text,
                        status=status,
                        error_message=err
                    )
                    db.add(log_entry)
                    db.commit()

                    if success:
                        total_sent += 1
                        logger.info(f"  => ✅ GỬI THÀNH CÔNG!")
                    else:
                        total_failed += 1
                        logger.error(f"  => ❌ GỬI THẤT BẠI: {err}")

                    # Nghỉ 1.5 giây giữa các lần gửi để tránh bị đánh spam
                    time.sleep(1.5)

    finally:
        db.close()

    logger.info("\n" + "=" * 80)
    logger.info(f"KẾT QUẢ BOT HOÀN TẤT ({mode_text})")
    logger.info(f"  • Tổng hội thoại đã quét : {total_scanned}")
    logger.info(f"  • Tổng hội thoại khớp bot: {total_matched}")
    if not dry_run:
        logger.info(f"  • Đã gửi thành công      : {total_sent}")
        logger.info(f"  • Gửi thất bại           : {total_failed}")
    logger.info("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pancake Auto-Reply Bot")
    parser.add_argument("--send", action="store_true", help="Bật gửi thật qua Pancake API (Mặc định là DRY-RUN)")
    parser.add_argument("--days", type=int, default=1, help="Số ngày quét hội thoại gần nhất (Mặc định: 1)")
    parser.add_argument("--limit", type=int, default=50, help="Số hội thoại tối đa mỗi page (Mặc định: 50)")
    parser.add_argument("--from-db", action="store_true", help="Quét trực tiếp từ RawConversation trong Database (dùng để test/đối soát)")
    args = parser.parse_args()

    is_dry_run = not args.send
    run_auto_reply_bot(dry_run=is_dry_run, days_back=args.days, limit_per_page=args.limit, from_db=args.from_db)
