import os
import logging
import requests
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from etl.utils import is_page_id, resolve_canonical_page_name, KNOWN_PAGE_NAMES

logger = logging.getLogger(__name__)

def create_http_session() -> requests.Session:
    """Tạo requests.Session có connection pooling và keep-alive để tái sử dụng TLS connection."""
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=15,
        pool_maxsize=15,
        max_retries=Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False
        )
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

class PancakeClient:
    def __init__(self, api_token: Optional[str] = None):
        self.api_token = api_token or os.getenv("PANCAKE_API_TOKEN")
        self.limit = int(os.getenv("CRAWL_LIMIT", "300")) 
        self.base_url = "https://pages.fm/api/v1"
        self.session = create_http_session()

    def _get_page_access_token(self, page_id_or_name: str) -> tuple:
        """
        Lấy page_access_token và page_id chính xác.
        Hỗ trợ cả User Access Token (tự sinh page_access_token) và Page Access Token truyền trực tiếp.
        """
        if not self.api_token:
            logger.error(f"Không có PANCAKE_API_TOKEN để kết nối Pancake API cho Page '{page_id_or_name}'.")
            return None, None, None

        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "User-Agent": "Pancake-Python-Client/1.0",
            "Accept": "application/json"
        }

        # 1. Thử phân giải page_id và tên page
        resolved_page_id = str(page_id_or_name).strip()
        resolved_page_name = resolve_canonical_page_name(page_id_or_name, fallback=None)
        if resolved_page_name == resolved_page_id and is_page_id(resolved_page_id):
            resolved_page_name = None

        try:
            res = self.session.get(
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
                target = str(page_id_or_name).strip()
                target_num = re.sub(r"^(pzl_|tt_|fb_)", "", target)
                for p in pages:
                    p_id = str(p.get("id"))
                    p_name = p.get("name")
                    if p_id in (target, target_num) or (p_name and p_name in (target, resolved_page_name)):
                        resolved_page_id = p_id
                        resolved_page_name = p_name or resolved_page_name
                        break
        except Exception as e:
            logger.debug(f"Không thể tra cứu danh sách page qua /pages: {e}")

        # 2. Thử tạo page_access_token qua User Access Token
        try:
            res_token = self.session.post(
                f"{self.base_url}/pages/{resolved_page_id}/generate_page_access_token",
                params={"access_token": self.api_token},
                timeout=10
            )
            token_data = res_token.json()
            if token_data.get("success") and token_data.get("page_access_token"):
                return token_data["page_access_token"], resolved_page_id, resolved_page_name
            else:
                logger.info(f"API generate_page_access_token phản hồi: {token_data.get('message', 'Không thành công')}. Thử dùng token cấu hình làm Page Access Token trực tiếp...")
        except Exception as e:
            logger.debug(f"Lỗi khi gọi generate_page_access_token: {e}")

        # Fallback thử lấy thông tin page đơn lẻ nếu là Page Access Token
        if not resolved_page_name and is_page_id(resolved_page_id):
            clean_num = re.sub(r"^(pzl_|tt_|fb_)", "", str(resolved_page_id))
            for candidate_id in (resolved_page_id, clean_num):
                try:
                    res_single = self.session.get(
                        f"{self.base_url}/pages/{candidate_id}",
                        params={"access_token": self.api_token},
                        headers=headers,
                        timeout=5
                    )
                    if res_single.status_code == 200:
                        p_info = res_single.json()
                        p_data = p_info.get("data") or p_info.get("page") or p_info
                        if isinstance(p_data, dict) and p_data.get("name"):
                            resolved_page_name = p_data.get("name")
                            resolved_page_id = candidate_id
                            break
                except Exception as e:
                    logger.debug(f"Không thể tra cứu tên page từ /pages/{candidate_id}: {e}")

        # 3. Fallback: Bản thân token cấu hình có thể chính là Page Access Token
        resolved_page_name = resolved_page_name or resolve_canonical_page_name(resolved_page_id, fallback=None)
        return self.api_token, resolved_page_id, resolved_page_name

    def get_conversations(self, page_id: str, existing_cache: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Lấy danh sách hội thoại qua Pancake Public API v2 với cơ chế Incremental Caching:
        - Bỏ qua tải messages đối với các hội thoại đã có trong DB và không có thay đổi (updated_at trùng khớp).
        - Đối với hội thoại mới hoặc có cập nhật, chỉ lấy 1 trang tin nhắn mới nhất thay vì quét toàn bộ lịch sử.
        """
        logger.info(f"--- BẮT ĐẦU CÀO DỮ LIỆU QUA API CHO PAGE: {page_id} ---")
        existing_cache = existing_cache or {}
        
        ptoken, resolved_page_id, resolved_page_name = self._get_page_access_token(page_id)
        if not ptoken:
            logger.error(f"Không lấy được access token cho Page {page_id}. Dừng cào.")
            return []

        # Tên chuẩn hiển thị trên dashboard của Page này
        self.page_name = resolved_page_name or resolve_canonical_page_name(page_id, fallback=None)
        if not self.page_name and not is_page_id(page_id):
            self.page_name = page_id
        page_id = resolved_page_id
        url_convs = f"https://pages.fm/api/public_api/v2/pages/{page_id}/conversations"
        
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
                resp = self.session.get(url_convs, params=clean_params, timeout=30)
            except Exception as e:
                logger.error(f"Lỗi kết nối khi gọi /conversations: {e}")
                retry_count += 1
                if retry_count <= max_retries:
                    time.sleep(3 * retry_count)
                    continue
                else:
                    break

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("success") is False:
                    err_msg = data.get("message", "Không rõ nguyên nhân")
                    err_code = data.get("error_code", "N/A")
                    logger.error(
                        f"❌ Pancake API từ chối Page '{page_id}': {err_msg} (error_code: {err_code}). "
                        f"Vui lòng kiểm tra hoặc tạo lại Page Access Token mới trên Pancake!"
                    )
                    break

                retry_count = 0
                convs = data.get("conversations", []) if isinstance(data, dict) else []
                if not convs:
                    logger.info("Không còn hội thoại mới nào từ API.")
                    break
                all_convs.extend(convs)
                new_last_id = convs[-1].get('id')
                if new_last_id == last_id:
                    break
                last_id = new_last_id
                time.sleep(0.2)
            elif resp.status_code in (400, 404) and len(all_convs) == 0:
                alt_id = page_id.replace("pzl_", "") if page_id.startswith("pzl_") else f"pzl_{page_id}"
                if alt_id != page_id:
                    logger.info(f"API trả về HTTP {resp.status_code} với Page ID '{page_id}'. Thử lại với ID: '{alt_id}'...")
                    page_id = alt_id
                    url_convs = f"https://pages.fm/api/public_api/v2/pages/{page_id}/conversations"
                    continue
                else:
                    logger.error(f"Lỗi Pancake API (HTTP {resp.status_code}): {resp.text}")
                    break
            elif resp.status_code == 429:
                logger.warning("Pancake API Rate limit (429)! Nghỉ 10s...")
                time.sleep(10)
                continue
            elif resp.status_code >= 500:
                retry_count += 1
                logger.warning(f"Lỗi server Pancake (HTTP {resp.status_code}), thử lại lần {retry_count}/{max_retries}...")
                if retry_count <= max_retries:
                    time.sleep(3 * retry_count)
                    continue
                else:
                    break
            else:
                logger.error(f"Lỗi Pancake API (HTTP {resp.status_code}): {resp.text}")
                break

        all_convs = all_convs[:self.limit]
        
        # 1. Tận dụng Cache: Chỉ tải tin nhắn cho các hội thoại MỚI hoặc có updated_at THAY ĐỔI
        messages_by_conv: Dict[str, list] = {}
        convs_to_fetch = []

        for conv in all_convs:
            cid = str(conv.get('id', ''))
            conv_updated = conv.get('updated_at')
            cached_data = existing_cache.get(cid)

            # Nếu đã có trong DB, updated_at không đổi và đã có tin nhắn -> dùng lại cache, không tốn request
            if cached_data and cached_data.get('updated_at') == conv_updated and cached_data.get('messages'):
                messages_by_conv[cid] = cached_data.get('messages', [])
            else:
                convs_to_fetch.append(cid)

        cached_hits = len(all_convs) - len(convs_to_fetch)
        logger.info(f"Tổng số hội thoại: {len(all_convs)}. Dùng cache không cần tải lại: {cached_hits}, Cần tải tin nhắn mới: {len(convs_to_fetch)}.")

        # 2. Tải tin nhắn mới (chỉ lấy 30 tin nhắn mới nhất thay vì loop vô tận qua toàn bộ lịch sử)
        if convs_to_fetch:
            def fetch_single_conversation_messages(cid):
                url = f"https://pages.fm/api/public_api/v1/pages/{page_id}/conversations/{cid}/messages"
                try:
                    resp = self.session.get(
                        url,
                        params={"page_access_token": ptoken},
                        timeout=10
                    )
                    if resp.status_code == 200:
                        return cid, resp.json().get('messages', [])
                    elif resp.status_code == 429:
                        time.sleep(3)
                        resp2 = self.session.get(url, params={"page_access_token": ptoken}, timeout=10)
                        if resp2.status_code == 200:
                            return cid, resp2.json().get('messages', [])
                except Exception as e:
                    logger.debug(f"Lỗi khi tải messages cho conversation {cid}: {e}")
                return cid, []

            # Sử dụng 8 workers để tải song song cực nhanh
            with ThreadPoolExecutor(max_workers=8) as executor:
                future_to_conv = {executor.submit(fetch_single_conversation_messages, cid): cid for cid in convs_to_fetch}
                for future in as_completed(future_to_conv):
                    try:
                        cid, msgs = future.result()
                        messages_by_conv[cid] = msgs
                    except Exception as e:
                        logger.error(f"Lỗi future messages cid {cid}: {e}")

        # Trích xuất tên Page từ tin nhắn gửi đi nếu chưa có tên chữ
        if not self.page_name:
            for msgs in messages_by_conv.values():
                for m in msgs:
                    if isinstance(m, dict):
                        m_from = m.get('from') or {}
                        if str(m_from.get('id')) == str(page_id) and m_from.get('name') and not str(m_from.get('name')).strip().isdigit():
                            self.page_name = str(m_from.get('name')).strip()
                            break
                if self.page_name:
                    break
        if not self.page_name:
            self.page_name = str(page_id)

        # 3. Tổng hợp kết quả
        results = []
        for conv in all_convs:
            conv_id = str(conv.get('id', ''))
            customers = conv.get('customers', [])
            customer_id = str(customers[0].get('id')) if customers and customers[0].get('id') else 'unknown'
            customer_name = customers[0].get('name') if customers and customers[0].get('name') else 'Unknown'
            
            raw_tags = conv.get('tags', [])
            tags = [t['text'] for t in raw_tags if isinstance(t, dict) and 'text' in t]
            
            assignees_raw = conv.get('current_assign_users') or conv.get('assignees') or conv.get('assigned_users') or []
            if isinstance(assignees_raw, list):
                assigned_users = ", ".join([item['name'] for item in assignees_raw if isinstance(item, dict) and 'name' in item])
            elif isinstance(assignees_raw, str):
                assigned_users = assignees_raw
            else:
                assigned_users = None

            # Tìm SĐT trực tiếp từ đối tượng conversation nếu Pancake đã thu thập
            phone = None
            recent_phones = conv.get('recent_phone_numbers', [])
            if recent_phones and isinstance(recent_phones, list):
                phone = recent_phones[0].get('phone_number')
            if not phone and customers and isinstance(customers, list):
                phone = customers[0].get('phone_number')

            messages_data = messages_by_conv.get(conv_id, [])
            formatted_msgs = []
            for m in messages_data:
                if isinstance(m, dict) and m.get("message"):
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
            
            # Ưu tiên message_count có sẵn trong conversation
            msg_count = conv.get("message_count")
            if msg_count is None:
                msg_count = len(messages_data)

            results.append({
                "id": conv_id,
                "pancake_id": conv_id,
                "type": conv.get("type"),
                "customer_id": customer_id,
                "customer_name": customer_name,
                "phone_number": phone,
                "message_count": msg_count,
                "tags": tags,
                "assigned_users": assigned_users,
                "messages": formatted_msgs,
                "inserted_at": conv.get("inserted_at"),
                "updated_at": conv.get("updated_at")
            })
            
        logger.info(f"Hoàn tất lấy dữ liệu qua API! Tổng cộng: {len(results)} hội thoại.")
        return results
