import os
import logging
import requests
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

class PancakeClient:
    def __init__(self, api_token: Optional[str] = None):
        self.api_token = api_token or os.getenv("PANCAKE_API_TOKEN")
        self.limit = int(os.getenv("CRAWL_LIMIT", "300")) 
        self.base_url = "https://pages.fm/api/v1"

    def _get_page_access_token(self, page_id_or_name: str) -> Optional[tuple]:
        """
        Lấy page_access_token và page_id chính xác.
        Hỗ trợ cả User Access Token (tự sinh page_access_token) và Page Access Token truyền trực tiếp.
        """
        if not self.api_token:
            logger.error("Không có PANCAKE_API_TOKEN để kết nối Pancake API.")
            return None, None

        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "User-Agent": "Pancake-Python-Client/1.0",
            "Accept": "application/json"
        }

        # 1. Thử phân giải page_id nếu truyền vào tên hoặc ID
        resolved_page_id = page_id_or_name
        try:
            res = requests.get(
                f"{self.base_url}/pages",
                params={"access_token": self.api_token},
                headers=headers,
                timeout=10
            )
            if res.status_code == 200:
                data = res.json()
                pages = data.get("data", [])
                if not pages and "categorized" in data:
                    pages = data["categorized"].get("activated", [])
                for p in pages:
                    if str(p.get("id")) == str(page_id_or_name) or p.get("name") == page_id_or_name:
                        resolved_page_id = str(p.get("id"))
                        break
        except Exception as e:
            logger.debug(f"Không thể tra cứu danh sách page qua /pages (có thể do dùng Page Access Token): {e}")

        # 2. Thử tạo page_access_token qua User Access Token
        try:
            res_token = requests.post(
                f"{self.base_url}/pages/{resolved_page_id}/generate_page_access_token",
                params={"access_token": self.api_token},
                timeout=10
            )
            token_data = res_token.json()
            if token_data.get("success") and token_data.get("page_access_token"):
                return token_data["page_access_token"], resolved_page_id
            else:
                logger.info(f"API generate_page_access_token phản hồi: {token_data.get('message', 'Không thành công')}. Thử dùng token cấu hình làm Page Access Token trực tiếp...")
        except Exception as e:
            logger.debug(f"Lỗi khi gọi generate_page_access_token: {e}")

        # 3. Fallback: Bản thân token cấu hình có thể chính là Page Access Token
        return self.api_token, resolved_page_id

    def get_conversations(self, page_id: str) -> List[Dict[str, Any]]:
        """Lấy danh sách hội thoại và tin nhắn trực tiếp qua Pancake Public API v2."""
        logger.info(f"--- BẮT ĐẦU CÀO DỮ LIỆU QUA API CHO PAGE: {page_id} ---")
        
        ptoken, resolved_page_id = self._get_page_access_token(page_id)
        if not ptoken:
            logger.error(f"Không lấy được access token cho Page {page_id}. Dừng cào.")
            return []

        page_id = resolved_page_id
        url_convs = f"https://pages.fm/api/public_api/v2/pages/{page_id}/conversations"
        
        # Pancake API yêu cầu timestamp dạng số nguyên (integer Unix timestamp in seconds)
        now_ts = int(datetime.utcnow().timestamp())
        since_ts = int((datetime.utcnow() - timedelta(days=365 * 2)).timestamp())
        
        all_convs = []
        last_id = None
        retry_count = 0
        max_retries = 3

        while len(all_convs) < self.limit:
            params = {
                "page_access_token": ptoken,
                "since": since_ts,
                "until": now_ts,
                "order_by": "updated_at",
                "last_conversation_id": last_id,
            }
            clean_params = {k: v for k, v in params.items() if v is not None}
            
            try:
                resp = requests.get(url_convs, params=clean_params, timeout=30)
            except Exception as e:
                logger.error(f"Lỗi kết nối khi gọi /conversations: {e}")
                retry_count += 1
                if retry_count <= max_retries:
                    time.sleep(5 * retry_count)
                    continue
                else:
                    break

            if resp.status_code == 200:
                retry_count = 0
                convs = resp.json().get('conversations', [])
                if not convs:
                    logger.info("Không còn hội thoại mới nào từ API.")
                    break
                all_convs.extend(convs)
                last_id = convs[-1].get('id')
                time.sleep(0.5)
            elif resp.status_code == 429:
                logger.warning("Pancake API Rate limit (429)! Nghỉ 15s...")
                time.sleep(15)
                continue
            elif resp.status_code >= 500:
                retry_count += 1
                logger.warning(f"Lỗi server Pancake (HTTP {resp.status_code}), thử lại lần {retry_count}/{max_retries}...")
                if retry_count <= max_retries:
                    time.sleep(5 * retry_count)
                    continue
                else:
                    break
            else:
                logger.error(f"Lỗi Pancake API (HTTP {resp.status_code}): {resp.text}")
                break

        all_convs = all_convs[:self.limit]
        logger.info(f"Đã lấy {len(all_convs)} hội thoại. Bắt đầu tải tin nhắn chi tiết (đa luồng)...")
        
        messages_by_conv = {}

        def fetch_conversation_messages(cid):
            url = f"https://pages.fm/api/public_api/v1/pages/{page_id}/conversations/{cid}/messages"
            current_count = 0
            rc = 0
            local_msgs = []
            while True:
                try:
                    resp = requests.get(
                        url,
                        params={"page_access_token": ptoken, "current_count": current_count},
                        timeout=10
                    )
                    if resp.status_code == 200:
                        rc = 0
                        msgs = resp.json().get('messages', [])
                        if not msgs:
                            break
                        local_msgs.extend(msgs)
                        current_count += len(msgs)
                        time.sleep(0.1)
                    elif resp.status_code == 429:
                        time.sleep(3)
                        continue
                    elif resp.status_code >= 500:
                        rc += 1
                        if rc <= max_retries:
                            time.sleep(2 * rc)
                            continue
                        else:
                            break
                    else:
                        break
                except Exception:
                    time.sleep(2)
                    continue
            return cid, local_msgs

        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_conv = {executor.submit(fetch_conversation_messages, conv.get('id')): conv.get('id') for conv in all_convs}
            for future in as_completed(future_to_conv):
                try:
                    cid, msgs = future.result()
                    messages_by_conv[cid] = msgs
                except Exception as e:
                    logger.error(f"Lỗi khi tải messages cho conversation {cid}: {e}")

        results = []
        for conv in all_convs:
            conv_id = conv.get('id')
            customers = conv.get('customers', [])
            customer_id = customers[0].get('id') if customers else 'unknown'
            customer_name = customers[0].get('name') if customers else 'Unknown'
            
            raw_tags = conv.get('tags', [])
            tags = [t['text'] for t in raw_tags if isinstance(t, dict) and 'text' in t]
            
            assignees_raw = conv.get('current_assign_users', [])
            assigned_users = ", ".join([item['name'] for item in assignees_raw if isinstance(item, dict) and 'name' in item])

            messages_data = messages_by_conv.get(conv_id, [])
            formatted_msgs = []
            for m in messages_data:
                if m.get("message"):
                    m_from = m.get('from', {})
                    is_admin = False
                    if m_from:
                        if 'admin' in str(m_from).lower() or m_from.get('admin_name'):
                            is_admin = True
                        elif str(m_from.get('id')) == str(page_id):
                            is_admin = True
                    
                    role = "Admin" if is_admin else "Khách hàng"
                    
                    formatted_msgs.append({
                        "message": m.get("message"),
                        "inserted_at": m.get("inserted_at"),
                        "role": role,
                        "sender_name": m_from.get('name') or m_from.get('username') or m_from.get('admin_name') or "Unknown"
                    })
            
            results.append({
                "id": conv_id,
                "pancake_id": conv_id,
                "type": conv.get("type"),
                "customer_id": customer_id,
                "customer_name": customer_name,
                "phone_number": None,
                "message_count": len(messages_data),
                "tags": tags,
                "assigned_users": assigned_users,
                "messages": formatted_msgs,
                "inserted_at": conv.get("inserted_at"),
                "updated_at": conv.get("updated_at")
            })
            
        logger.info(f"Hoàn tất lấy dữ liệu qua API! Tổng cộng: {len(results)} hội thoại.")
        return results
