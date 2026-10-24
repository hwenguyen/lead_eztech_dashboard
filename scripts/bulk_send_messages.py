"""
================================================================================
SCRIPT GỬI TIN NHẮN HÀNG LOẠT TỰ ĐỘNG QUA PANCAKE API
(DỰA TRÊN TÀI LIỆU PANCAKE API DOC & DATABASE HỆ THỐNG)
================================================================================

1. TÀI LIỆU PANCAKE API (PancakeAPIDoc.yaml):
   - Endpoint gửi tin:
     POST https://pages.fm/api/public_api/v1/pages/{page_id}/conversations/{conversation_id}/messages
   - Xác thực:
     Query parameter `page_access_token` (không dùng Authorization header).
     Có thể sinh tự động từ User Access Token qua:
     POST https://pages.fm/api/v1/pages/{page_id}/generate_page_access_token?access_token=...
   - Quy tắc Body (InboxMessage):
     {
       "action": "reply_inbox",
       "message": "Nội dung tin nhắn..."
     }
     * QUAN TRỌNG: `message` và `content_ids` là MUTUALLY EXCLUSIVE (loại trừ lẫn nhau).
       Gửi text thì chỉ gửi `message`, không đính kèm `content_ids`.
   - Rate Limit:
     Tối đa 5 requests / giây / page. Vượt quá sẽ nhận HTTP 429 Too Many Requests.
     Code này thiết lập tốc độ gửi an toàn (1 request / 1.0s - 1.5s có jitter ngẫu nhiên).
   - Kiểm tra kết quả:
     HTTP 200 không đảm bảo gửi thành công! Luôn phải kiểm tra `body.get("success") is True`.
     Nếu `False`, kiểm tra `message_code` hoặc `message` (ví dụ: quá 24h chính sách Facebook).

2. KẾT NỐI DATABASE (Neon PostgreSQL / SQLite):
   - Kéo thông tin khách hàng từ `dim_leads` kết hợp `fact_lead_activities`.
   - Lọc theo:
     + `page_id`: ID của Fanpage / TikTok / Zalo OA
     + `status_tag`: Thẻ trạng thái lead (ví dụ: "Đang tư vấn", "Chưa liên hệ",...)
     + `days_ago`: Khoảng thời gian tương tác gần nhất (tránh gửi tin nhắn quá hạn 24h của FB)
     + `is_contacted`: Đã liên hệ hay chưa
   - Chống spam / Gửi trùng lặp (Anti-Spam Idempotency):
     + Kiểm tra bảng `bot_auto_replies`. Nếu khách hàng / conversation_id đã nhận chiến dịch này,
       hệ thống sẽ tự động BỎ QUA.
   - Ghi log trạng thái:
     + Lưu lịch sử gửi (SENT, FAILED, DRY_RUN) vào bảng `bot_auto_replies` kèm lỗi chi tiết.
   - Chế độ DRY-RUN an toàn:
     + Mặc định có thể chạy mô phỏng (preview danh sách và nội dung cá nhân hóa) trước khi gửi thật.
================================================================================
"""

import os
import sys
import time
import json
import random
import logging
import argparse
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple

# Thiết lập encoding utf-8 cho terminal Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Nạp cấu hình môi trường (.env.local, .env)
def load_env_file(filepath: str):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass

try:
    from dotenv import load_dotenv
    load_dotenv(".env.local")
    load_dotenv(".env")
except ImportError:
    load_env_file(".env.local")
    load_env_file(".env")

# Đảm bảo đường dẫn gốc project có trong sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Thử nạp requests, nếu chưa cài thì fallback sang thư viện chuẩn urllib
try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

def http_post_json(url: str, params: Optional[Dict[str, Any]] = None, json_data: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, timeout: int = 25) -> Tuple[int, Dict[str, Any], str]:
    """Hàm gửi HTTP POST JSON đa năng, tương thích cả khi có hoặc không có thư viện `requests`."""
    full_url = url
    if params:
        query_string = urllib.parse.urlencode(params)
        full_url = f"{url}?{query_string}" if "?" not in url else f"{url}&{query_string}"

    req_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Pancake-Bulk-Messenger/1.0"
    }
    if headers:
        req_headers.update(headers)

    body_bytes = json.dumps(json_data or {}).encode("utf-8")

    if HAS_REQUESTS:
        try:
            res = requests.post(full_url, json=json_data, headers=req_headers, timeout=timeout)
            try:
                data = res.json()
            except Exception:
                data = {"text": res.text}
            return res.status_code, data, res.text
        except Exception as e:
            return 0, {}, str(e)
    else:
        req = urllib.request.Request(full_url, data=body_bytes, headers=req_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status_code = response.getcode()
                raw_text = response.read().decode("utf-8")
                try:
                    data = json.loads(raw_text)
                except Exception:
                    data = {"text": raw_text}
                return status_code, data, raw_text
        except urllib.error.HTTPError as e:
            raw_text = e.read().decode("utf-8") if e.fp else ""
            try:
                data = json.loads(raw_text)
            except Exception:
                data = {"text": raw_text}
            return e.code, data, raw_text
        except Exception as e:
            return 0, {}, str(e)

# Import Database & Models
try:
    from database.db import SessionLocal, engine
    from database.models import DimLead, FactLeadActivity, BotAutoReplyLog, RawConversation
    from database.schema import ensure_schema
    HAS_LOCAL_DB_MODELS = True
except ImportError:
    HAS_LOCAL_DB_MODELS = False

# Múi giờ Việt Nam
VN_TZ = timezone(timedelta(hours=7))

def get_vn_now():
    return datetime.now(VN_TZ).replace(tzinfo=None)

# Thiết lập logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("PancakeBulkMessenger")


def create_resilient_session():
    """Tạo requests.Session có pool kết nối và cơ chế tự động thử lại nếu có thư viện requests."""
    if HAS_REQUESTS:
        session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=10,
            max_retries=Retry(
                total=3,
                backoff_factor=1.0,
                status_forcelist=[500, 502, 503, 504],
                raise_on_status=False
            )
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session
    return None


class PancakeBulkMessenger:
    def __init__(
        self,
        api_token: Optional[str] = None,
        page_id: Optional[str] = None,
        campaign_name: str = "broadcast_campaign"
    ):
        """
        Khởi tạo Pancake Bulk Messenger.
        :param api_token: User Access Token hoặc Page Access Token (mặc định lấy từ PANCAKE_API_TOKEN)
        :param page_id: ID trang gửi tin (Facebook Page ID, TikTok Page ID,...)
        :param campaign_name: Tên mã chiến dịch (được lưu vào case_id trong DB để tránh gửi lặp)
        """
        self.api_token = api_token or os.getenv("PANCAKE_API_TOKEN")
        self.page_id = str(page_id).strip() if page_id else os.getenv("DEFAULT_PAGE_ID", "")
        self.campaign_name = campaign_name
        self.base_url = "https://pages.fm/api/public_api/v1"
        self.user_api_url = "https://pages.fm/api/v1"
        self.session = create_resilient_session()
        self._page_tokens: Dict[str, str] = {}

    def get_page_access_token(self, target_page_id: str) -> Optional[str]:
        """
        Lấy Page Access Token chuẩn theo PancakeAPIDoc.
        Nếu truyền token là User Access Token -> gọi API sinh page_access_token.
        Nếu token vốn là Page Access Token -> dùng trực tiếp.
        """
        target_page_id = str(target_page_id).strip()
        if target_page_id in self._page_tokens:
            return self._page_tokens[target_page_id]

        if not self.api_token:
            logger.error("❌ Không tìm thấy PANCAKE_API_TOKEN trong môi trường hoặc tham số!")
            return None

        # 1. Thử gọi API sinh page_access_token qua User Access Token
        clean_page_id = target_page_id.replace("fb_", "").replace("tt_", "").replace("pzl_", "")
        token_url = f"{self.user_api_url}/pages/{clean_page_id}/generate_page_access_token"

        try:
            status_code, data, _ = http_post_json(
                token_url,
                params={"access_token": self.api_token},
                timeout=15
            )
            if status_code == 200:
                if data.get("success") and data.get("page_access_token"):
                    p_token = data["page_access_token"]
                    self._page_tokens[target_page_id] = p_token
                    logger.info(f"🔑 Đã cấp phát thành công page_access_token cho Page {target_page_id}")
                    return p_token
        except Exception as e:
            logger.debug(f"Không thể sinh token qua User Access Token: {e}")

        # 2. Fallback: coi self.api_token là Page Access Token dùng luôn
        self._page_tokens[target_page_id] = self.api_token
        return self.api_token

    def fetch_recipients_from_db(
        self,
        page_id: Optional[str] = None,
        status_tag: Optional[str] = None,
        days_ago: Optional[int] = None,
        uncontacted_only: bool = False,
        limit: int = 100,
        exclude_already_sent: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Kéo danh sách khách hàng mục tiêu từ Database.
        Truy vấn kết hợp giữa dim_leads, fact_lead_activities và bot_auto_replies.
        """
        if not HAS_LOCAL_DB_MODELS:
            # Fallback: Nếu môi trường chạy script chưa cài SQLAlchemy, thử truy vấn trực tiếp qua sqlite3
            import sqlite3
            db_path = "leads_data.db"
            if os.path.exists(db_path):
                try:
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT l.id, l.customer_id, l.name, l.phone_number, l.page_id, l.first_created_at,
                               a.conversation_id, a.status_tag
                        FROM dim_leads l
                        JOIN fact_lead_activities a ON l.id = a.lead_id
                        LIMIT ?
                    """, (limit,))
                    rows = cursor.fetchall()
                    conn.close()
                    recipients = []
                    for r in rows:
                        recipients.append({
                            "lead_id": r[0],
                            "customer_id": r[1],
                            "name": r[2] or "",
                            "phone_number": r[3] or "",
                            "page_id": str(r[4]),
                            "first_created_at": r[5],
                            "conversation_id": str(r[6]),
                            "status_tag": r[7] or ""
                        })
                    logger.info(f"📊 [SQLite Fallback] Đã lấy {len(recipients)} người nhận từ {db_path}.")
                    return recipients
                except Exception as ex:
                    logger.warning(f"Lỗi truy vấn sqlite3: {ex}")

            logger.error("❌ Không thể kết nối Database Models (chưa cài SQLAlchemy/psycopg2).")
            logger.info("💡 Bạn có thể cài đặt: pip install -r requirements.txt")
            return []

        recipients = []
        db = SessionLocal()
        try:
            query = db.query(
                DimLead.id.label("lead_id"),
                DimLead.customer_id,
                DimLead.name,
                DimLead.phone_number,
                DimLead.page_id,
                DimLead.first_created_at,
                FactLeadActivity.conversation_id,
                FactLeadActivity.status_tag,
                FactLeadActivity.is_contacted,
                FactLeadActivity.contacted_at,
                FactLeadActivity.message_count
            ).join(
                FactLeadActivity,
                DimLead.id == FactLeadActivity.lead_id
            )

            # Lọc theo page_id
            target_page = page_id or self.page_id
            if target_page:
                query = query.filter(DimLead.page_id == str(target_page))

            # Lọc theo thẻ tag trạng thái
            if status_tag:
                query = query.filter(FactLeadActivity.status_tag.ilike(f"%{status_tag}%"))

            # Lọc khách chưa liên hệ
            if uncontacted_only:
                query = query.filter(FactLeadActivity.is_contacted == False)

            # Lọc theo số ngày gần đây (rất quan trọng đối với Facebook 24h Policy)
            if days_ago and days_ago > 0:
                cutoff = get_vn_now() - timedelta(days=days_ago)
                query = query.filter(DimLead.first_created_at >= cutoff)

            # Sắp xếp lead mới nhất lên trước
            query = query.order_by(DimLead.first_created_at.desc())

            all_leads = query.limit(limit * 2).all()

            # Lấy danh sách conversation_id đã từng nhận chiến dịch này để loại trừ (Idempotency)
            already_sent_convs = set()
            if exclude_already_sent and self.campaign_name:
                sent_logs = db.query(BotAutoReplyLog.conversation_id).filter(
                    BotAutoReplyLog.case_id == self.campaign_name,
                    BotAutoReplyLog.status == "SENT"
                ).all()
                already_sent_convs = {str(r[0]) for r in sent_logs if r[0]}

            for row in all_leads:
                conv_id = str(row.conversation_id) if row.conversation_id else None
                if not conv_id:
                    continue

                if exclude_already_sent and conv_id in already_sent_convs:
                    continue

                recipients.append({
                    "lead_id": row.lead_id,
                    "customer_id": row.customer_id,
                    "conversation_id": conv_id,
                    "name": row.name or "",
                    "phone_number": row.phone_number or "",
                    "page_id": str(row.page_id),
                    "status_tag": row.status_tag or "",
                    "first_created_at": row.first_created_at
                })

                if len(recipients) >= limit:
                    break

            logger.info(f"📊 Đã kéo {len(recipients)} người nhận thỏa mãn điều kiện từ Database.")
            return recipients
        except Exception as e:
            logger.error(f"❌ Lỗi khi truy vấn dữ liệu từ Database: {e}", exc_info=True)
            return []
        finally:
            db.close()

    def render_template(self, template: str, recipient: Dict[str, Any]) -> str:
        """
        Cá nhân hóa nội dung tin nhắn dựa trên dữ liệu người nhận.
        Hỗ trợ các placeholder: {name}, {phone}, {customer_id}, {page_id}.
        Nếu tên rỗng, tự động xưng hô lịch sự 'anh/chị'.
        """
        raw_name = (recipient.get("name") or "").strip()
        display_name = raw_name if raw_name else "anh/chị"

        msg = template.replace("{name}", display_name)
        msg = msg.replace("{phone}", recipient.get("phone_number") or "")
        msg = msg.replace("{customer_id}", str(recipient.get("customer_id") or ""))
        msg = msg.replace("{page_id}", str(recipient.get("page_id") or ""))
        return msg.strip()

    def send_single_message(
        self,
        page_id: str,
        conversation_id: str,
        message_text: str,
        content_ids: Optional[List[str]] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Gửi 1 tin nhắn đến 1 conversation qua Pancake API:
        POST https://pages.fm/api/public_api/v1/pages/{page_id}/conversations/{conversation_id}/messages?page_access_token=...

        Tuân thủ tuyệt đối quy tắc của PancakeAPIDoc:
        - `message` và `content_ids` là MUTUALLY EXCLUSIVE.
        - Kiểm tra success trong json response.
        """
        if dry_run:
            return {
                "success": True,
                "status": "DRY_RUN",
                "message": "[DRY-RUN] Giả lập gửi thành công, không gọi API Pancake.",
                "id": f"mock_msg_{int(time.time()*1000)}"
            }

        ptoken = self.get_page_access_token(page_id)
        if not ptoken:
            return {
                "success": False,
                "status": "FAILED",
                "message": f"Không có page_access_token hợp lệ cho Page {page_id}"
            }

        # Theo tài liệu: API v1 sử dụng endpoint:
        url = f"{self.base_url}/pages/{page_id}/conversations/{conversation_id}/messages"
        params = {"page_access_token": ptoken}

        # Tạo payload tuân thủ PancakeAPIDoc.yaml:
        # Nếu gửi text -> dùng `message`, tuyệt đối KHÔNG đính kèm `content_ids`
        # Nếu gửi media -> dùng `content_ids`, tuyệt đối KHÔNG đính kèm `message`
        payload = {
            "action": "reply_inbox"
        }
        if content_ids:
            payload["content_ids"] = content_ids
        else:
            payload["message"] = message_text

        # Cơ chế retry nếu gặp Rate Limit (HTTP 429) hoặc mạng chập chờn
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                status_code, data, raw_text = http_post_json(
                    url,
                    params=params,
                    json_data=payload,
                    timeout=20
                )

                # Xử lý Rate Limit 429
                if status_code == 429:
                    wait_sec = attempt * 2.5
                    logger.warning(f"⚠️ Gặp Rate Limit (HTTP 429) từ Pancake. Đang tạm dừng {wait_sec}s rồi thử lại...")
                    time.sleep(wait_sec)
                    continue

                if status_code in (200, 201):
                    # Pancake có thể trả 200 nhưng body success = false (vd: quá hạn 24h nhắn tin FB)
                    is_success = data.get("success", False)
                    if is_success:
                        return {
                            "success": True,
                            "status": "SENT",
                            "id": data.get("id"),
                            "message": "Gửi thành công"
                        }
                    else:
                        error_code = data.get("message_code") or "UNKNOWN_ERROR"
                        error_msg = data.get("message") or str(data)
                        return {
                            "success": False,
                            "status": "FAILED",
                            "error_code": error_code,
                            "message": f"{error_code}: {error_msg}"
                        }
                else:
                    return {
                        "success": False,
                        "status": "FAILED",
                        "status_code": status_code,
                        "message": f"HTTP {status_code}: {raw_text[:200]}"
                    }

            except Exception as e:
                logger.warning(f"⚠️ Lỗi kết nối khi gửi tới conv {conversation_id} (thử lần {attempt}): {e}")
                if attempt < max_retries:
                    time.sleep(2.0)
                    continue
                return {
                    "success": False,
                    "status": "FAILED",
                    "message": f"Connection/Timeout Error: {str(e)}"
                }

        return {"success": False, "status": "FAILED", "message": "Quá số lần retry tối đa"}

    def log_result_to_db(
        self,
        recipient: Dict[str, Any],
        message_text: str,
        result: Dict[str, Any]
    ):
        """Ghi lại lịch sử gửi tin vào Database (bảng bot_auto_replies)."""
        if not HAS_LOCAL_DB_MODELS:
            return

        db = SessionLocal()
        try:
            status = result.get("status", "FAILED")
            err_msg = result.get("message") if not result.get("success") else None

            log_entry = BotAutoReplyLog(
                conversation_id=recipient["conversation_id"],
                customer_id=recipient.get("customer_id"),
                page_id=recipient["page_id"],
                case_id=self.campaign_name,
                customer_message=f"[BROADCAST TARGET] Tag: {recipient.get('status_tag')}",
                reply_message=message_text,
                sent_at=get_vn_now(),
                status=status,
                error_message=err_msg
            )
            db.add(log_entry)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"Không thể ghi log gửi tin vào DB: {e}")
        finally:
            db.close()

    def run_broadcast(
        self,
        template: str,
        recipients: List[Dict[str, Any]],
        delay_between_messages: float = 1.0,
        dry_run: bool = True
    ) -> Dict[str, Any]:
        """
        Thực thi chiến dịch gửi tin nhắn hàng loạt tự động.
        :param template: Mẫu tin nhắn có chứa biến {name}, {phone}...
        :param recipients: Danh sách người nhận kéo từ DB
        :param delay_between_messages: Khoảng nghỉ an toàn giữa mỗi tin (giây) để tránh rate limit Pancake
        :param dry_run: Chế độ chạy thử (không gọi API thật)
        """
        total = len(recipients)
        success_count = 0
        failed_count = 0

        mode_str = "🔍 [DRY-RUN MÔ PHỎNG]" if dry_run else "🚀 [CHẠY THẬT - GỬI LIVE]"
        logger.info("=" * 70)
        logger.info(f"{mode_str} Bắt đầu gửi hàng loạt tới {total} người nhận.")
        logger.info(f"Chiến dịch: '{self.campaign_name}'")
        logger.info(f"Thời gian nghỉ giữa các tin: {delay_between_messages}s (Tuân thủ Rate Limit <= 5 req/s)")
        logger.info("=" * 70)

        for index, rec in enumerate(recipients, 1):
            personalized_msg = self.render_template(template, rec)
            conv_id = rec["conversation_id"]
            cust_name = rec.get("name") or "Khách hàng"
            p_id = rec["page_id"]

            logger.info(f"[{index}/{total}] Gửi tới: '{cust_name}' (Page: {p_id}, Conv: {conv_id})...")

            # Gọi gửi tin nhắn
            result = self.send_single_message(
                page_id=p_id,
                conversation_id=conv_id,
                message_text=personalized_msg,
                dry_run=dry_run
            )

            # Ghi log kết quả vào database
            self.log_result_to_db(rec, personalized_msg, result)

            if result.get("success"):
                success_count += 1
                logger.info(f"  ✅ Thành công! {result.get('message', '')}")
            else:
                failed_count += 1
                logger.error(f"  ❌ Thất bại: {result.get('message', '')}")

            # Thêm jitter ngẫu nhiên 0.1s - 0.5s để hành vi tự nhiên, tránh bị Facebook / Pancake gắn cờ spam
            if index < total:
                sleep_time = max(0.5, delay_between_messages + random.uniform(0.1, 0.5))
                time.sleep(sleep_time)

        # Tổng kết báo cáo
        logger.info("=" * 70)
        logger.info(f"🎉 HOÀN THÀNH CHIẾN DỊCH: {self.campaign_name}")
        logger.info(f"  • Tổng số khách hàng: {total}")
        logger.info(f"  • Gửi thành công:     {success_count}")
        logger.info(f"  • Thất bại / Bỏ qua:  {failed_count}")
        if dry_run:
            logger.info("💡 Đây là chế độ DRY-RUN. Để gửi thật, hãy thêm cờ: --no-dry-run hoặc --send-live")
        logger.info("=" * 70)

        return {
            "total": total,
            "success": success_count,
            "failed": failed_count,
            "dry_run": dry_run
        }


def main():
    parser = argparse.ArgumentParser(description="Script gửi tin nhắn hàng loạt tự động qua Pancake API.")
    parser.add_argument("--page-id", type=str, default=None, help="ID của Fanpage / Page Pancake cần gửi.")
    parser.add_argument("--campaign", type=str, default="broadcast_marketing_01", help="Tên chiến dịch gửi tin.")
    parser.add_argument("--tag", type=str, default=None, help="Lọc khách hàng theo status_tag trong DB (vd: 'Đang tư vấn').")
    parser.add_argument("--days", type=int, default=1, help="Chỉ gửi cho khách nhắn trong N ngày gần đây (mặc định: 1 ngày để đảm bảo chính sách 24h FB).")
    parser.add_argument("--limit", type=int, default=20, help="Số lượng tin nhắn tối đa gửi trong một đợt.")
    parser.add_argument("--delay", type=float, default=1.2, help="Khoảng thời gian nghỉ giữa 2 tin nhắn (giây). Mặc định 1.2s.")
    parser.add_argument("--demo", action="store_true", help="Chạy với dữ liệu mẫu (mock data) để kiểm tra luồng hoạt động.")
    parser.add_argument("--template", type=str, default="Chào {name}, bên em gửi anh/chị thông tin ưu đãi mới nhất từ hệ thống ạ!", help="Mẫu tin nhắn gửi khách.")
    parser.add_argument("--no-dry-run", "--send-live", dest="dry_run", action="store_false", help="Thực hiện gửi thật (mặc định là Dry-run để an toàn).")
    parser.set_defaults(dry_run=True)

    args = parser.parse_args()

    messenger = PancakeBulkMessenger(
        page_id=args.page_id,
        campaign_name=args.campaign
    )

    if args.demo:
        print("\n🧪 [DEMO MODE] Khởi tạo danh sách khách hàng mẫu để kiểm tra...")
        recipients = [
            {"lead_id": 1, "customer_id": "cust_101", "name": "Nguyễn Văn An", "phone_number": "0987654321", "page_id": args.page_id or "514400205095512", "conversation_id": "conv_fb_101", "status_tag": "Đang tư vấn", "first_created_at": get_vn_now()},
            {"lead_id": 2, "customer_id": "cust_102", "name": "Trần Thị Mai", "phone_number": "0912345678", "page_id": args.page_id or "514400205095512", "conversation_id": "conv_fb_102", "status_tag": "Khách tiềm năng", "first_created_at": get_vn_now()},
            {"lead_id": 3, "customer_id": "cust_103", "name": "", "phone_number": "0909112233", "page_id": args.page_id or "514400205095512", "conversation_id": "conv_fb_103", "status_tag": "Chưa liên hệ", "first_created_at": get_vn_now()}
        ]
    else:
        print("\n🔍 ĐANG TRUY VẤN DANH SÁCH KHÁCH HÀNG TỪ DATABASE...")
        recipients = messenger.fetch_recipients_from_db(
            page_id=args.page_id,
            status_tag=args.tag,
            days_ago=args.days,
            limit=args.limit,
            exclude_already_sent=True
        )

    if not recipients:
        print("⚠️ Không tìm thấy người nhận nào phù hợp với bộ lọc trong Database.")
        print("💡 Hãy thử kiểm tra lại: Page ID, số ngày lọc (--days), hoặc tag (--tag).")
        return

    # In ra danh sách xem trước
    print(f"\n📋 XEM TRƯỚC {len(recipients)} NGƯỜI NHẬN ĐẦU TIÊN:")
    for idx, r in enumerate(recipients[:5], 1):
        sample_msg = messenger.render_template(args.template, r)
        print(f"  {idx}. [{r['page_id']}] {r['name'] or 'N/A'} (SĐT: {r['phone_number'] or 'N/A'}) - Conv: {r['conversation_id']}")
        print(f"     -> Tin nhắn: \"{sample_msg}\"")

    if args.dry_run:
        print("\n🛡️  ĐANG Ở CHẾ ĐỘ DRY-RUN (MÔ PHỎNG AN TOÀN).")
        print("   Không có tin nhắn nào thực sự được gửi tới khách hàng.")
        print("   Chạy với cờ '--no-dry-run' khi bạn đã sẵn sàng gửi thật.\n")
    else:
        print("\n⚠️ CẢNH BÁO: BẠN ĐANG CHẠY CHẾ ĐỘ GỬI THẬT!")
        confirm = input("👉 Bạn có chắc chắn muốn gửi tin nhắn hàng loạt này không? (y/N): ")
        if confirm.lower().strip() not in ("y", "yes"):
            print("Đã hủy thao tác.")
            return

    # Thực thi
    messenger.run_broadcast(
        template=args.template,
        recipients=recipients,
        delay_between_messages=args.delay,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()
