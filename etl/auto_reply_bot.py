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
import random
import re
import unicodedata
import logging
import argparse
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple, Set

from dotenv import load_dotenv
load_dotenv(".env.local")
load_dotenv(".env")

from database.db import SessionLocal
from database.models import BotAutoReplyLog, RawConversation, Comment
from database.schema import ensure_schema
from etl.pancake_client import PancakeClient
from etl.utils import VN_TZ, is_page_id, resolve_canonical_page_name
from etl.auto_reply_rules import (
    AUTO_REPLY_RULES,
    ALLOWED_SOURCE_PAGES,
    COMMENT_REPLY_RULES,
    SKIP_IF_CUSTOMER_HAS_PRIOR_MESSAGES
)

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


def match_rule(
    customer_message: str,
    rules: Optional[List[Dict[str, Any]]] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    So khớp tin nhắn của khách hàng với danh sách rules (mặc định AUTO_REPLY_RULES).
    Trả về (Rule khớp, Từ khóa đã khớp) hoặc (None, None).
    """
    if not customer_message:
        return None, None

    lower_msg, no_accents_msg = normalize_message(customer_message)

    active_rules = rules if rules is not None else AUTO_REPLY_RULES
    # Sắp xếp các rule theo priority tăng dần
    sorted_rules = sorted(
        [r for r in active_rules if r.get("enabled", True)],
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

    # 6. Chốt chặn giới hạn retry: Nếu đã thử gửi 5 lần nhưng vẫn bị từ chối, tạm bỏ qua để không spam
    repeated_fails = db.query(BotAutoReplyLog.id).filter(
        BotAutoReplyLog.conversation_id == conv_id,
        BotAutoReplyLog.case_id == case_id,
        BotAutoReplyLog.status == "FAILED",
        BotAutoReplyLog.error_message.like("%Sending message failed%")
    ).count()
    if repeated_fails >= 5:
        return False, rule, matched_kw, cust_text, f"Đã thử gửi {repeated_fails} lần nhưng bị nền tảng từ chối (quyền riêng tư/chính sách người dùng), tạm bỏ qua"

    return True, rule, matched_kw, cust_text, "Đủ điều kiện gửi"


def extract_customer_identifiers(comment: Dict[str, Any]) -> List[str]:
    """
    Trích xuất toàn bộ các định danh có thể có của khách hàng từ dữ liệu comment
    để đối chiếu với danh sách khách cũ trong Inbox (ID, PSID, số điện thoại).
    """
    ids = []
    if comment.get("customer_id"):
        ids.append(str(comment["customer_id"]).strip().lower())
    if comment.get("phone_number"):
        ids.append(str(comment["phone_number"]).strip().lower())

    payload = comment.get("payload") or {}
    if isinstance(payload, dict):
        if payload.get("customer_id"):
            ids.append(str(payload["customer_id"]).strip().lower())

        from_info = payload.get("from") or {}
        if isinstance(from_info, dict) and from_info.get("id"):
            ids.append(str(from_info["id"]).strip().lower())

        customers = payload.get("customers") or []
        if isinstance(customers, list):
            for c in customers:
                if isinstance(c, dict):
                    if c.get("id"):
                        ids.append(str(c["id"]).strip().lower())
                    if c.get("fb_id"):
                        ids.append(str(c["fb_id"]).strip().lower())
                    if c.get("phone_number"):
                        ids.append(str(c["phone_number"]).strip().lower())

        page_cust = payload.get("page_customer") or {}
        if isinstance(page_cust, dict):
            if page_cust.get("id"):
                ids.append(str(page_cust["id"]).strip().lower())
            if page_cust.get("customer_id"):
                ids.append(str(page_cust["customer_id"]).strip().lower())
            if page_cust.get("psid"):
                ids.append(str(page_cust["psid"]).strip().lower())

    return [i for i in ids if i and i not in ('unknown', 'none', '')]


def get_existing_inbox_customer_ids(page_id: str, db: SessionLocal) -> Set[str]:
    """
    Lấy danh sách các định danh (customer_id, psid, phone_number...) của khách hàng
    ĐÃ CÓ TIN NHẮN trong Inbox của Page hoặc ĐÃ ĐƯỢC BOT GỬI TIN NHẮN THÀNH CÔNG.
    Dùng để chốt chặn không gửi tin nhắn / rep comment cho khách cũ.
    """
    existing_ids = set()
    canonical_name = resolve_canonical_page_name(page_id)

    # 1. Quét từ raw_conversations của Page
    try:
        from sqlalchemy import text
        sql_convs = """
            SELECT 
                payload ->> 'customer_id' as cust_id,
                payload -> 'customers' -> 0 ->> 'id' as p_cust_id,
                payload -> 'customers' -> 0 ->> 'fb_id' as fb_id,
                payload -> 'from' ->> 'id' as from_id,
                payload ->> 'phone_number' as phone
            FROM raw_conversations
            WHERE page_id = :pname
              AND (
                  COALESCE((payload ->> 'message_count')::int, 0) > 0
                  OR payload ->> 'messages' IS NOT NULL
              )
        """
        rows = db.execute(text(sql_convs), {"pname": canonical_name}).fetchall()
        for r in rows:
            for val in r:
                if val and str(val).strip() and str(val).strip().lower() not in ('unknown', 'none', ''):
                    existing_ids.add(str(val).strip().lower())
    except Exception as e:
        logger.warning(f"Lỗi khi nạp danh sách khách cũ từ raw_conversations Page {page_id}: {e}")

    # 2. Quét từ bot_auto_replies (các khách đã từng được Bot gửi tin nhắn thành công)
    try:
        clean_num = re.sub(r"^(pzl_|tt_|fb_)", "", str(page_id))
        bot_rows = db.query(BotAutoReplyLog.customer_id).filter(
            (BotAutoReplyLog.page_id.like(f"%{clean_num}%")) | (BotAutoReplyLog.page_id == canonical_name),
            BotAutoReplyLog.status == "SENT"
        ).all()
        for b in bot_rows:
            if b[0] and str(b[0]).strip().lower() not in ('unknown', 'none', ''):
                existing_ids.add(str(b[0]).strip().lower())
    except Exception as e:
        logger.warning(f"Lỗi khi nạp danh sách khách cũ từ bot_auto_replies Page {page_id}: {e}")

    return existing_ids


def should_reply_comment(
    comment: Dict[str, Any],
    page_id: str,
    db: SessionLocal,
    days_back: int = 1,
    existing_inbox_customer_ids: Optional[Set[str]] = None
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str], Optional[str], str]:
    """
    Kiểm tra xem một bình luận (comment) có đủ điều kiện để Bot gửi phản hồi tự động hay không.
    Trả về: (can_reply: bool, rule, matched_kw, clean_message, reason)
    """
    cid = str(comment.get("comment_id") or comment.get("id") or "")
    if not cid:
        return False, None, None, None, "Không có comment_id"

    # 1. Chốt chặn kênh: Chỉ áp dụng cho các kênh Lead nguồn được phép
    clean_pid = str(page_id).strip()
    clean_num = re.sub(r"^(pzl_|tt_|fb_)", "", clean_pid)
    if ALLOWED_SOURCE_PAGES and not any(allowed in (clean_pid, clean_num) for allowed in ALLOWED_SOURCE_PAGES):
        return False, None, None, None, f"Kênh {page_id} không thuộc danh sách lead nguồn cho phép"

    # 2. Chốt chặn thời gian: Chỉ reply các comment gần đây (trong vòng days_back ngày)
    inserted_at = comment.get("inserted_at")
    if inserted_at:
        from etl.utils import parse_pancake_date
        dt = parse_pancake_date(inserted_at)
        if dt:
            cutoff = datetime.now(VN_TZ).replace(tzinfo=None) - timedelta(days=days_back)
            if dt < cutoff:
                return False, None, None, None, f"Comment cũ trước mốc {days_back} ngày ({dt})"

    # 3. Chốt chặn số lượng tin trong thread (message_count)
    # Pancake comment: message_count=0 hoặc 1 là chỉ mới có comment của khách, chưa có reply
    msg_count = comment.get("message_count")
    try:
        if msg_count is not None and int(msg_count) > 1:
            return False, None, None, None, f"Thread comment đã có phản hồi (message_count={msg_count})"
    except (ValueError, TypeError):
        pass

    # 4. Kiểm tra tin nhắn Admin trong payload nếu có
    payload = comment.get("payload") or {}
    if isinstance(payload, dict):
        msgs = payload.get("messages", [])
        if any(('admin' in str(m.get('role', '')).lower() or 'admin' in str(m.get('from', '')).lower() or str((m.get('from') or {}).get('id')) == str(clean_num)) for m in msgs if isinstance(m, dict)):
            return False, None, None, None, "Admin đã trả lời trong comment thread"

    # 5. So khớp nội dung comment với rules (ưu tiên COMMENT_REPLY_RULES)
    clean_msg = comment.get("message") or comment.get("snippet") or ""
    if not clean_msg and isinstance(payload, dict):
        clean_msg = payload.get("snippet", "")

    rules_to_check = COMMENT_REPLY_RULES if COMMENT_REPLY_RULES else AUTO_REPLY_RULES
    rule, matched_kw = match_rule(clean_msg, rules=rules_to_check)
    if not rule:
        return False, None, None, clean_msg, "Không khớp từ khóa của kịch bản nào"

    case_id = rule.get("case_id")

    # 6. Chốt chặn chống spam: Kiểm tra DB xem Bot đã từng gửi kịch bản này cho comment này chưa
    existing_sent = db.query(BotAutoReplyLog.id).filter(
        BotAutoReplyLog.conversation_id == cid,
        BotAutoReplyLog.case_id == case_id,
        BotAutoReplyLog.status == "SENT"
    ).first()
    if existing_sent:
        return False, rule, matched_kw, clean_msg, f"Đã từng trả lời comment này với kịch bản [{case_id}] (chống spam)"

    # 7. Chốt chặn khách cũ: Nếu khách đã có tin nhắn từ trước trong Inbox -> Bỏ qua hoàn toàn
    if SKIP_IF_CUSTOMER_HAS_PRIOR_MESSAGES:
        inbox_ids = existing_inbox_customer_ids
        if inbox_ids is None:
            inbox_ids = get_existing_inbox_customer_ids(page_id, db)
        cust_idents = extract_customer_identifiers(comment)
        if any(ident in inbox_ids for ident in cust_idents):
            return False, rule, matched_kw, clean_msg, "Khách hàng đã có tin nhắn từ trước trong Inbox (bỏ qua không gửi lại)"

    # 8. Chốt chặn giới hạn retry nếu lỗi nền tảng
    repeated_fails = db.query(BotAutoReplyLog.id).filter(
        BotAutoReplyLog.conversation_id == cid,
        BotAutoReplyLog.case_id == case_id,
        BotAutoReplyLog.status == "FAILED"
    ).count()
    if repeated_fails >= 3:
        return False, rule, matched_kw, clean_msg, f"Đã thử gửi {repeated_fails} lần nhưng thất bại, tạm bỏ qua"

    return True, rule, matched_kw, clean_msg, "Đủ điều kiện gửi"


def process_page_comment_replies(
    client: PancakeClient,
    comments_data: List[Dict[str, Any]],
    page_id: str,
    db: SessionLocal,
    dry_run: bool = False,
    max_replies: int = 10,
    days_back: int = 1
) -> Dict[str, int]:
    """
    Quét danh sách comments vừa cào được và gửi phản hồi tự động nếu thỏa mãn điều kiện.
    """
    stats = {"scanned": 0, "matched": 0, "sent": 0, "failed": 0, "skipped": 0}
    if not comments_data:
        return stats

    mode_text = "DRY-RUN (CHẠY THỬ NGHIỆM)" if dry_run else "LIVE (GỬI THẬT QUA PANCAKE API)"
    logger.info(f"\n--- [AUTO-REPLY COMMENTS] Đang kiểm tra {len(comments_data)} comments cho Page {page_id} | Chế độ: {mode_text} ---")

    # Tải danh sách khách hàng đã có tin nhắn từ trước (để chốt chặn chống spam khách cũ)
    existing_inbox_customer_ids = None
    if SKIP_IF_CUSTOMER_HAS_PRIOR_MESSAGES:
        existing_inbox_customer_ids = get_existing_inbox_customer_ids(page_id, db)
        logger.info(f"[AUTO-REPLY COMMENTS] Đã nạp {len(existing_inbox_customer_ids)} định danh khách cũ đã có tin nhắn từ trước cho Page {page_id}.")

    replied_count = 0
    for c_item in comments_data:
        if replied_count >= max_replies:
            logger.info(f"[AUTO-REPLY COMMENTS] Đã đạt giới hạn tối đa {max_replies} reply cho Page {page_id} trong lượt chạy này.")
            break

        stats["scanned"] += 1
        cid = str(c_item.get("comment_id") or c_item.get("id") or "")
        cust_name = c_item.get("customer_name") or "Khách hàng"

        can_reply, rule, matched_kw, cust_msg, reason = should_reply_comment(
            comment=c_item,
            page_id=page_id,
            db=db,
            days_back=days_back,
            existing_inbox_customer_ids=existing_inbox_customer_ids
        )

        if not can_reply:
            stats["skipped"] += 1
            if rule:
                logger.info(f"  [Bỏ qua comment] {cid} | \"{(cust_msg or '')[:30]}\" | Lý do: {reason}")
            continue

        stats["matched"] += 1
        case_id = rule["case_id"]
        rule_name = rule["name"]

        logger.info(f"\n[PHÁT HIỆN COMMENT PHÙ HỢP]")
        logger.info(f"  • Khách hàng : {cust_name}")
        logger.info(f"  • Comment ID : {cid}")
        logger.info(f"  • Nội dung   : \"{cust_msg}\"")
        logger.info(f"  • Kịch bản   : [{rule_name}] (từ khóa: \"{matched_kw}\")")

        payload = c_item.get("payload") or {}
        post_id = c_item.get("post_id") or (payload.get("post_id") if isinstance(payload, dict) else None)
        from_id = (payload.get("from") or {}).get("id") if isinstance(payload, dict) else None
        if not from_id:
            from_id = c_item.get("customer_id")

        # TikTok không hỗ trợ API gửi tin nhắn riêng từ comment (chỉ Facebook/Instagram hỗ trợ theo Pancake OpenAPI)
        is_tiktok = str(page_id).startswith("tt_") or "tiktok" in resolve_canonical_page_name(page_id).lower()
        enable_private_reply = os.getenv("ENABLE_PRIVATE_REPLY", "true").strip().lower() not in ("false", "0", "off", "no")
        can_private_reply = enable_private_reply and not is_tiktok
        dm_success = False

        # BƯỚC 1: Thử gửi tin nhắn riêng (Private Reply / DM) vào Inbox (chỉ áp dụng Facebook)
        if is_tiktok:
            logger.info("  • Kênh TikTok: Nền tảng TikTok không hỗ trợ gửi DM từ comment qua API -> Bỏ qua DM, chuyển thẳng sang Rep Comment công khai.")
        elif can_private_reply:
            private_text = rule.get("private_message") or rule.get("message")
            logger.info(f"  • Sẽ thử gửi tin nhắn riêng (DM):\n    \"{private_text}\"")

            if dry_run:
                logger.info("  => [DRY-RUN] Giả lập thử gửi tin nhắn riêng vào Inbox...")
                dm_success = True
                log_entry_dm = BotAutoReplyLog(
                    conversation_id=cid,
                    customer_id=str(c_item.get("customer_id") or ""),
                    page_id=page_id,
                    case_id=f"{case_id}_dm",
                    customer_message=cust_msg,
                    reply_message=private_text,
                    status="DRY_RUN",
                )
                db.add(log_entry_dm)
                db.commit()
            else:
                logger.info("  => 🚀 ĐANG THỬ GỬI TIN NHẮN RIÊNG (DM) VÀO INBOX QUA PANCAKE API...")
                res_dm = client.send_message(
                    page_id=page_id,
                    conversation_id=cid,
                    message=private_text,
                    action="private_replies",
                    post_id=post_id,
                    message_id=cid,
                    from_id=from_id
                )
                dm_success = res_dm.get("success", False)
                dm_err = None if dm_success else str(res_dm.get("message") or res_dm)

                log_entry_dm = BotAutoReplyLog(
                    conversation_id=cid,
                    customer_id=str(c_item.get("customer_id") or ""),
                    page_id=page_id,
                    case_id=f"{case_id}_dm",
                    customer_message=cust_msg,
                    reply_message=private_text,
                    status="SENT" if dm_success else "FAILED",
                    error_message=dm_err
                )
                db.add(log_entry_dm)
                db.commit()

                if dm_success:
                    logger.info(f"  => ✅ GỬI TIN NHẮN RIÊNG THÀNH CÔNG! (Message ID: {res_dm.get('id', 'N/A')})")
                else:
                    logger.warning(f"  => ⚠️ KHÔNG THỂ GỬI DM: {dm_err}")

                time.sleep(random.uniform(2.0, 4.0))

        # BƯỚC 2: Rep comment công khai tương ứng với kết quả DM
        if dm_success or is_tiktok:
            msg_candidates = rule.get("comment_success_message") or "Chào bạn, bạn ib để mình gửi bạn thông tin nha!"
        else:
            msg_candidates = rule.get("comment_fallback_message") or rule.get("comment_message") or rule.get("message")

        if isinstance(msg_candidates, list) and msg_candidates:
            reply_comment_text = random.choice(msg_candidates)
        else:
            reply_comment_text = str(msg_candidates or "")

        logger.info(f"  • Sẽ rep comment công khai:\n    \"{reply_comment_text}\"")

        if dry_run:
            logger.info("  => [DRY-RUN] Bỏ qua bước rep comment thật.")
            log_entry_cmt = BotAutoReplyLog(
                conversation_id=cid,
                customer_id=str(c_item.get("customer_id") or ""),
                page_id=page_id,
                case_id=case_id,
                customer_message=cust_msg,
                reply_message=reply_comment_text,
                status="DRY_RUN",
            )
            db.add(log_entry_cmt)
            db.commit()
            replied_count += 1
        else:
            logger.info("  => 🚀 ĐANG REP COMMENT CÔNG KHAI QUA PANCAKE API...")
            res_cmt = client.send_message(
                page_id=page_id,
                conversation_id=cid,
                message=reply_comment_text,
                action="reply_comment",
                message_id=cid
            )
            cmt_success = res_cmt.get("success", False)
            cmt_err = None if cmt_success else str(res_cmt.get("message") or res_cmt)

            log_entry_cmt = BotAutoReplyLog(
                conversation_id=cid,
                customer_id=str(c_item.get("customer_id") or ""),
                page_id=page_id,
                case_id=case_id,
                customer_message=cust_msg,
                reply_message=reply_comment_text,
                status="SENT" if cmt_success else "FAILED",
                error_message=cmt_err
            )
            db.add(log_entry_cmt)
            db.commit()

            if cmt_success:
                stats["sent"] += 1
                replied_count += 1
                msg_id = res_cmt.get("id") or "N/A"
                logger.info(f"  => ✅ REP COMMENT THÀNH CÔNG! (Message ID: {msg_id})")
            else:
                stats["failed"] += 1
                logger.error(f"  => ❌ REP COMMENT THẤT BẠI: {cmt_err}")

            delay = random.uniform(12.0, 18.0)
            logger.info(f"  ⏳ Tạm nghỉ {delay:.1f}s trước lượt reply tiếp theo để chống spam...")
            time.sleep(delay)

    logger.info(
        f"[AUTO-REPLY COMMENTS] Hoàn tất Page {page_id}: "
        f"Đã duyệt {stats['scanned']}, Đủ điều kiện {stats['matched']}, Đã reply {stats['sent']}, "
        f"Thất bại {stats['failed']}, Bỏ qua {stats['skipped']}."
    )
    return stats


def run_auto_reply_bot(
    dry_run: bool = True,
    days_back: int = 1,
    limit_per_page: int = 100,
    from_db: bool = False,
    include_inbox: bool = True,
    include_comments: bool = True,
):
    """
    Hàm thực thi chính của Bot:
    - dry_run=True: Chỉ quét và in ra log các khách đủ điều kiện (KHÔNG gửi thật).
    - dry_run=False: Gửi tin nhắn thật qua Pancake API.
    """
    enable_env = os.getenv("ENABLE_AUTO_REPLY", "true").strip().lower()
    if enable_env in ("false", "0", "off", "no"):
        logger.info("Bot tự động phản hồi đang TẮT (ENABLE_AUTO_REPLY=false). Bỏ qua bước này.")
        return

    mode_text = "DRY-RUN (CHẠY THỬ NGHIỆM - KHÔNG GỬI THẬT)" if dry_run else "LIVE (GỬI THẬT QUA PANCAKE API)"
    logger.info("=" * 80)
    logger.info(f"KHỞI ĐỘNG AUTO-REPLY BOT | CHẾ ĐỘ: {mode_text}")
    logger.info(f"Quét các hội thoại trong {days_back} ngày gần nhất (tối đa {limit_per_page}/page) | Inbox: {include_inbox} | Comment: {include_comments}")
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

            client = PancakeClient(api_token=page_token)

            if include_inbox:
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
                            msg_id = res.get("id") or "N/A"
                            logger.info(f"  => ✅ GỬI THÀNH CÔNG! (Message ID: {msg_id})")
                        else:
                            total_failed += 1
                            logger.error(f"  => ❌ GỬI THẤT BẠI: {err}")

                        # Giãn cách ngẫu nhiên 6 - 12 giây giữa các lần gửi để tránh bị TikTok/Facebook gắn cờ spam
                        # Nếu vừa bị lỗi thì tạm nghỉ dài hơn (10 - 15 giây) để tài khoản hạ nhiệt
                        delay = random.uniform(10.0, 15.0) if not success else random.uniform(6.0, 12.0)
                        logger.info(f"  ⏳ Tạm nghỉ {delay:.1f}s trước lượt gửi tiếp theo để chống spam...")
                        time.sleep(delay)

            # Quét và trả lời bình luận (Comment)
            if include_comments:
                if from_db:
                    query_cmt = db.query(Comment).filter(
                        Comment.page_id.in_([page_id, canonical_name, clean_num])
                    )
                    if days_back and days_back > 0:
                        cutoff_cmt = datetime.now(VN_TZ).replace(tzinfo=None) - timedelta(days=days_back)
                        query_cmt = query_cmt.filter(Comment.inserted_at >= cutoff_cmt)
                    cmt_rows = query_cmt.order_by(Comment.inserted_at.desc()).limit(limit_per_page).all()
                    comments_to_process = [
                        {
                            "comment_id": r.comment_id,
                            "customer_id": r.customer_id,
                            "customer_name": r.customer_name,
                            "message": r.message,
                            "raw_message": r.raw_message,
                            "message_count": r.message_count,
                            "inserted_at": r.inserted_at,
                            "payload": r.payload
                        }
                        for r in cmt_rows
                    ]
                else:
                    comments_to_process = client.get_comments(
                        page_id=page_id,
                        days_back=days_back,
                        limit=limit_per_page
                    )

                cmt_stats = process_page_comment_replies(
                    client=client,
                    comments_data=comments_to_process,
                    page_id=page_id,
                    db=db,
                    dry_run=dry_run,
                    max_replies=min(limit_per_page, 20),
                    days_back=days_back
                )
                total_scanned += cmt_stats["scanned"]
                total_matched += cmt_stats["matched"]
                total_sent += cmt_stats["sent"]
                total_failed += cmt_stats["failed"]

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
    parser.add_argument("--from-db", action="store_true", help="Quét trực tiếp từ Database (dùng để test/đối soát)")
    parser.add_argument("--no-inbox", action="store_true", help="Bỏ qua quét Inbox")
    parser.add_argument("--no-comments", action="store_true", help="Bỏ qua quét Comment")
    parser.add_argument("--comments-only", action="store_true", help="Chỉ quét và trả lời Comment")
    args = parser.parse_args()

    send_env = os.getenv("AUTO_REPLY_SEND", "").strip().lower() in ("true", "1", "yes")
    is_dry_run = not (args.send or send_env)

    inc_inbox = not args.no_inbox and not args.comments_only
    inc_comments = not args.no_comments

    run_auto_reply_bot(
        dry_run=is_dry_run,
        days_back=args.days,
        limit_per_page=args.limit,
        from_db=args.from_db,
        include_inbox=inc_inbox,
        include_comments=inc_comments
    )
