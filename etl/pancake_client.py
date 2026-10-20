import os
import re
import logging
import requests
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from etl.utils import is_page_id, resolve_canonical_page_name, KNOWN_PAGE_NAMES, parse_pancake_date, VN_TZ, clean_html, normalize_phone, extract_phone_number


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

    def get_conversations(
        self,
        page_id: str,
        existing_cache: Optional[Dict[str, Any]] = None,
        days_back: Optional[int] = None,
        cache_loader: Optional[Callable[[List[str]], Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Lấy danh sách hội thoại qua Pancake Public API v2 với cơ chế Incremental Caching & Early Stopping:
        - Nếu days_back được chỉ định (vd 3 ngày): chỉ cào dữ liệu mới cập nhật gần đây và dừng ngay (early break)
          khi gặp hội thoại cũ hơn, tránh duyệt thừa 500 bản ghi.
        - cache_loader(ids) -> {id: payload đã lưu}: chỉ nạp cache DB cho đúng các hội thoại vừa liệt kê.
        - Bỏ qua tải messages đối với các hội thoại đã có trong DB và không có thay đổi (updated_at trùng khớp).
        - Đối với hội thoại mới hoặc có cập nhật, chỉ lấy 1 trang tin nhắn mới nhất thay vì quét toàn bộ lịch sử.
        """
        logger.info(f"--- BẮT ĐẦU CÀO DỮ LIỆU QUA API CHO PAGE: {page_id} (Giới hạn: {self.limit}, Ngày quét: {days_back or 'Tất cả'}) ---")
        existing_cache = existing_cache if existing_cache is not None else {}
        failed_msg_ids: set = set()
        
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
        # Giữ since rộng: nếu Pancake lọc since theo ngày TẠO hội thoại thì thu hẹp sẽ mất lead cũ nhắn lại.
        # Việc cắt bớt do early stopping theo updated_at bên dưới đảm nhiệm.
        since_ts = int((datetime.utcnow() - timedelta(days=365 * 2)).timestamp())
        if days_back and days_back > 0:
            cutoff_dt = datetime.now(VN_TZ).replace(tzinfo=None) - timedelta(days=days_back)
        else:
            cutoff_dt = None
        
        t_list = time.perf_counter()
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

                reached_cutoff = False
                valid_convs = []
                for conv in convs:
                    # Bỏ qua Comment và Group chat Zalo ngay từ đầu — chỉ lấy tin nhắn khách hàng cá nhân (Message/Inbox)
                    conv_type = str(conv.get("type", "")).upper()
                    conv_id = str(conv.get("id", ""))
                    if conv_type == "COMMENT" or conv_id.startswith("pzl_g_"):
                        continue

                    if cutoff_dt:
                        conv_dt = parse_pancake_date(conv.get("updated_at") or conv.get("inserted_at"))
                        if conv_dt and conv_dt < cutoff_dt:
                            reached_cutoff = True
                            break
                    valid_convs.append(conv)

                all_convs.extend(valid_convs)

                if reached_cutoff:
                    logger.info(f"⚡ Đã quét đến mốc {days_back} ngày trước ({cutoff_dt.strftime('%d/%m/%Y %H:%M')}). Dừng cào sớm (Early Stopping) để tối ưu thời gian và quota!")
                    break

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
        logger.info(f"Đã liệt kê {len(all_convs)} hội thoại trong {time.perf_counter() - t_list:.1f}s.")

        # Chỉ nạp cache DB cho đúng các hội thoại vừa liệt kê
        if cache_loader and all_convs:
            t_cache = time.perf_counter()
            try:
                existing_cache.update(cache_loader([str(c.get('id')) for c in all_convs if c.get('id')]))
            except Exception as e:
                logger.warning(f"Không nạp được cache DB: {e}")
            logger.info(f"Nạp cache DB cho {len(existing_cache)} hội thoại trong {time.perf_counter() - t_cache:.1f}s.")
        
        # 1. Tận dụng Cache: Chỉ tải tin nhắn cho các hội thoại MỚI hoặc có updated_at THAY ĐỔI
        messages_by_conv: Dict[str, list] = {}
        convs_to_fetch = []

        for conv in all_convs:
            cid = str(conv.get('id', ''))
            conv_updated = conv.get('updated_at')
            cached_data = existing_cache.get(cid)

            # Nếu đã có trong DB, updated_at không đổi -> dùng lại cache, không tốn request tải lại
            if cached_data and cached_data.get('updated_at') == conv_updated:
                # Dummy list so it evaluates to True but produces empty formatted_msgs
                messages_by_conv[cid] = [{"is_cached": True}]
            else:
                convs_to_fetch.append(cid)

        cached_hits = len(all_convs) - len(convs_to_fetch)
        logger.info(f"Tổng số hội thoại: {len(all_convs)}. Dùng cache không cần tải lại: {cached_hits}, Cần tải tin nhắn mới: {len(convs_to_fetch)}.")

        # 2. Tải tin nhắn mới (chỉ lấy 30 tin nhắn mới nhất thay vì loop vô tận qua toàn bộ lịch sử)
        if convs_to_fetch:
            t_msgs = time.perf_counter()

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
                return cid, None  # None = tải lỗi (khác với hội thoại thật sự không có tin)

            failed = 0
            # Sử dụng 8 workers để tải song song cực nhanh
            with ThreadPoolExecutor(max_workers=8) as executor:
                future_to_conv = {executor.submit(fetch_single_conversation_messages, cid): cid for cid in convs_to_fetch}
                for future in as_completed(future_to_conv):
                    cid = future_to_conv[future]
                    try:
                        _, msgs = future.result()
                    except Exception as e:
                        logger.error(f"Lỗi future messages cid {cid}: {e}")
                        msgs = None
                    if msgs is None:
                        # Tải lỗi → giữ tin nhắn đã lưu thay vì ghi đè bằng danh sách rỗng
                        failed += 1
                        failed_msg_ids.add(cid)
                        msgs = (existing_cache.get(cid) or {}).get('messages', [])
                    messages_by_conv[cid] = msgs
            logger.info(
                f"Tải tin nhắn {len(convs_to_fetch)} hội thoại trong {time.perf_counter() - t_msgs:.1f}s "
                f"(lỗi: {failed})."
            )

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
            
            # Trích xuất lịch sử gắn/gỡ tag từ tag_histories của Pancake API
            tag_histories_raw = conv.get('tag_histories', [])
            tag_timeline = []
            if isinstance(tag_histories_raw, list):
                for th in tag_histories_raw:
                    if isinstance(th, dict):
                        p = th.get('payload', {})
                        t_obj = p.get('tag', {}) if isinstance(p, dict) else {}
                        t_text = t_obj.get('text') if isinstance(t_obj, dict) else None
                        if t_text:
                            tagged_dt = parse_pancake_date(th.get('inserted_at'))
                            tagged_at_str = tagged_dt.strftime("%Y-%m-%d %H:%M:%S") if tagged_dt else th.get('inserted_at')
                            tag_timeline.append({
                                "tag": t_text,
                                "action": p.get('action', 'add'),
                                "tagged_at": tagged_at_str,
                                "editor": p.get('editor_name')
                            })
            # Nếu có tag nhưng tag_histories không trả về, gán thời điểm hội thoại (chuẩn giờ VN)
            if not tag_timeline and tags:
                conv_ts_raw = conv.get('updated_at') or conv.get('inserted_at')
                conv_ts_dt = parse_pancake_date(conv_ts_raw)
                conv_ts_str = conv_ts_dt.strftime("%Y-%m-%d %H:%M:%S") if conv_ts_dt else conv_ts_raw
                for tag_name in tags:
                    tag_timeline.append({
                        "tag": tag_name,
                        "action": "add",
                        "tagged_at": conv_ts_str,
                        "editor": None
                    })
            
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
                    # Tin lấy lại từ cache đã được format sẵn (không còn 'from') → giữ nguyên role / sender_name,
                    # nếu format lại thì mọi tin sẽ thành "Khách hàng" và tin Admin bị quét SĐT như tin khách
                    if "role" in m and "from" not in m:
                        formatted_msgs.append(m)
                        continue
                    m_from = m.get('from') or {}
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

            updated_at = conv.get("updated_at")
            if conv_id in failed_msg_ids and existing_cache.get(conv_id):
                # Giữ updated_at cũ → lần chạy sau thấy lệch và tải lại tin nhắn
                updated_at = existing_cache[conv_id].get("updated_at") or updated_at

            results.append({
                "id": conv_id,
                "pancake_id": conv_id,
                "type": conv.get("type"),
                "customer_id": customer_id,
                "customer_name": customer_name,
                "phone_number": phone,
                "message_count": msg_count,
                "tags": tags,
                "tag_timeline": tag_timeline,
                "assigned_users": assigned_users,
                "messages": formatted_msgs,
                "inserted_at": conv.get("inserted_at"),
                "updated_at": updated_at
            })
            
        logger.info(f"Hoàn tất lấy dữ liệu qua API! Tổng cộng: {len(results)} hội thoại.")
        return results

    def get_comments(
        self,
        page_id: str,
        cache_loader: Optional[Callable[[List[str]], Dict[str, dict]]] = None,
        days_back: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Lấy danh sách Comment từ kênh nguồn (Facebook, TikTok) qua Pancake Public API v2.
        - Hỗ trợ Early Stopping theo days_back.
        - Tận dụng cache DB để không tải lại comment cũ chưa có cập nhật mới.
        """
        ptoken, resolved_page_id, resolved_page_name = self._get_page_access_token(page_id)
        if not ptoken:
            return []

        page_id = resolved_page_id
        url_convs = f"https://pages.fm/api/public_api/v2/pages/{page_id}/conversations"

        now_ts = int(datetime.utcnow().timestamp())
        since_ts = int((datetime.utcnow() - timedelta(days=365 * 2)).timestamp())
        cutoff_dt = None
        if days_back and days_back > 0:
            cutoff_dt = datetime.now(VN_TZ).replace(tzinfo=None) - timedelta(days=days_back)

        max_limit = limit or self.limit
        logger.info(f"--- BẮT ĐẦU CÀO COMMENT QUA API CHO PAGE: {page_id} (Giới hạn: {max_limit}, Ngày quét: {days_back or 'Tất cả'}) ---")

        all_comments = []
        last_id = None
        retry_count = 0
        max_retries = 3
        t_list = time.perf_counter()
        use_type_param = True
        api_page_count = 0
        max_api_pages = max(100, int(max_limit / 10))

        while len(all_comments) < max_limit and api_page_count < max_api_pages:
            api_page_count += 1
            params = {
                "page_access_token": ptoken,
                "since": since_ts,
                "until": now_ts,
                "order_by": "updated_at",
                "last_conversation_id": last_id,
            }
            if use_type_param:
                params["type"] = "COMMENT"
            clean_params = {k: v for k, v in params.items() if v is not None}

            try:
                resp = self.session.get(url_convs, params=clean_params, timeout=30)
            except Exception as e:
                logger.error(f"Lỗi kết nối khi gọi /conversations (comments) cho Page {page_id}: {e}")
                retry_count += 1
                if retry_count <= max_retries:
                    time.sleep(3 * retry_count)
                    continue
                else:
                    break

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("success") is False:
                    logger.warning(f"Pancake API từ chối cào comment cho Page '{page_id}': {data.get('message')}")
                    break

                retry_count = 0
                convs = data.get("conversations", []) if isinstance(data, dict) else []
                if not convs:
                    logger.info("Không còn comment mới nào từ API.")
                    break

                reached_cutoff = False
                valid_comments = []
                for conv in convs:
                    conv_type = str(conv.get("type", "")).upper()
                    # Chỉ lấy COMMENT hoặc COMMENT_LIVESTREAM
                    if "COMMENT" not in conv_type:
                        continue

                    if cutoff_dt:
                        conv_dt = parse_pancake_date(conv.get("updated_at") or conv.get("inserted_at"))
                        if conv_dt and conv_dt < cutoff_dt:
                            reached_cutoff = True
                            break
                    valid_comments.append(conv)

                all_comments.extend(valid_comments)

                if reached_cutoff:
                    logger.info(f"⚡ Đã quét comment đến mốc {days_back} ngày trước. Dừng cào sớm (Early Stopping)!")
                    break

                new_last_id = convs[-1].get('id')
                if new_last_id == last_id:
                    break
                last_id = new_last_id
                time.sleep(0.2)
            elif resp.status_code == 500 and use_type_param:
                logger.warning(
                    f"Pancake API trả 500 với filter 'type=COMMENT' cho Page '{page_id}'. "
                    f"Tự động chuyển sang chế độ fallback (không dùng type filter) và lọc comment trên client..."
                )
                use_type_param = False
                time.sleep(1)
                continue
            elif resp.status_code == 500:
                retry_count += 1
                if retry_count <= max_retries:
                    logger.warning(f"Pancake API trả status 500. Thử lại lần {retry_count}/{max_retries} sau {3 * retry_count}s...")
                    time.sleep(3 * retry_count)
                    continue
                else:
                    logger.error(f"Pancake API trả status 500 khi lấy comment: {resp.text[:200]}")
                    break
            elif resp.status_code == 429:
                logger.warning("Pancake API Rate limit (429)! Nghỉ 10s...")
                time.sleep(10)
                continue
            else:
                logger.warning(f"Pancake API trả status {resp.status_code} khi lấy comment: {resp.text[:200]}")
                break

        all_comments = all_comments[:max_limit]
        logger.info(f"Đã liệt kê {len(all_comments)} comments trong {time.perf_counter() - t_list:.1f}s.")

        existing_cache: Dict[str, dict] = {}
        if cache_loader and all_comments:
            try:
                existing_cache.update(cache_loader([str(c.get('id')) for c in all_comments if c.get('id')]))
            except Exception as e:
                logger.warning(f"Không nạp được cache DB cho comments: {e}")

        # Tận dụng cache để chỉ tải messages cho comment mới hoặc có cập nhật
        convs_to_fetch = []
        messages_by_conv: Dict[str, list] = {}
        for conv in all_comments:
            cid = str(conv.get('id', ''))
            conv_updated = conv.get('updated_at')
            cached_data = existing_cache.get(cid)
            if cached_data and str(cached_data.get('updated_at')) == str(conv_updated):
                messages_by_conv[cid] = [{"is_cached": True}]
            else:
                convs_to_fetch.append(cid)

        if convs_to_fetch:
            t_msgs = time.perf_counter()

            def fetch_single_comment_messages(cid):
                url = f"https://pages.fm/api/public_api/v1/pages/{page_id}/conversations/{cid}/messages"
                try:
                    resp = self.session.get(url, params={"page_access_token": ptoken}, timeout=10)
                    if resp.status_code == 200:
                        return cid, resp.json().get('messages', [])
                except Exception:
                    pass
                return cid, []

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = {executor.submit(fetch_single_comment_messages, cid): cid for cid in convs_to_fetch}
                for f in as_completed(futures):
                    cid, msgs = f.result()
                    messages_by_conv[cid] = msgs or []

            logger.info(f"Đã tải chi tiết tin nhắn {len(convs_to_fetch)} comments trong {time.perf_counter() - t_msgs:.1f}s.")

        results = []
        for conv in all_comments:
            cid = str(conv.get("id", ""))
            from_info = conv.get("from") or {}
            cust_id = str(conv.get("customer_id") or from_info.get("id") or "") or None
            cust_name = conv.get("customer_name") or from_info.get("name") or None
            
            # Trích xuất nội dung tin nhắn của khách
            msgs = messages_by_conv.get(cid, [])
            raw_msg = None
            clean_msg = None
            if msgs and not msgs[0].get("is_cached"):
                for m in msgs:
                    if isinstance(m, dict) and m.get("message"):
                        raw_msg = m.get("message")
                        break
            if not raw_msg:
                raw_msg = conv.get("snippet") or ""

            clean_msg = clean_html(raw_msg)

            phone = normalize_phone(conv.get("phone_number"))
            if not phone and clean_msg:
                phone = extract_phone_number(clean_msg)

            tags = conv.get("tags")
            if isinstance(tags, list):
                tag_texts = []
                for t in tags:
                    if isinstance(t, dict) and t.get("text"):
                        tag_texts.append(t.get("text"))
                    elif isinstance(t, str):
                        tag_texts.append(t)
                tags_str = ",".join(tag_texts) if tag_texts else None
            else:
                tags_str = str(tags) if tags else None

            assigned = conv.get("current_assign_users") or conv.get("assigned_users")
            if isinstance(assigned, list):
                assign_names = [u.get("name") for u in assigned if isinstance(u, dict) and u.get("name")]
                assigned_str = ",".join(assign_names) if assign_names else None
            else:
                assigned_str = str(assigned) if assigned else None

            post_url = conv.get("post_url") or conv.get("post_link") or conv.get("permalink_url")
            if not post_url and isinstance(conv.get("post"), dict):
                post_url = conv["post"].get("permalink_url") or conv["post"].get("url")

            results.append({
                "comment_id": cid,
                "page_id": str(page_id),
                "post_id": str(conv.get("post_id") or "") or None,
                "post_url": str(post_url) if post_url else None,
                "customer_id": cust_id,
                "customer_name": cust_name,
                "phone_number": phone,
                "message": clean_msg,
                "raw_message": raw_msg,
                "message_count": conv.get("message_count", 1),
                "tags": tags_str,
                "assigned_users": assigned_str,
                "inserted_at": conv.get("inserted_at"),
                "updated_at": conv.get("updated_at"),
                "payload": conv,
            })

        logger.info(f"Hoàn tất xử lý comment Page {page_id}! Tổng cộng: {len(results)} comments.")
        return results

    def send_message(
        self,
        page_id: str,
        conversation_id: str,
        message: str,
        action: str = "reply_inbox",
        **kwargs
    ) -> dict:
        """
        Gửi tin nhắn phản hồi vào hội thoại qua Pancake Public API v1.
        API: POST https://pages.fm/api/public_api/v1/pages/{page_id}/conversations/{conversation_id}/messages

        Args:
            page_id: ID của Page (có thể có prefix fb_, tt_, pzl_)
            conversation_id: ID hội thoại (pancake_id)
            message: Nội dung tin nhắn gửi cho khách
            action: Hành động gửi ('reply_inbox', 'reply_comment', 'private_replies'). Mặc định là 'reply_inbox'.
        """
        ptoken, resolved_page_id, _ = self._get_page_access_token(page_id)
        if not ptoken:
            return {"success": False, "message": f"Không lấy được token cho Page {page_id}"}

        url = f"https://pages.fm/api/public_api/v1/pages/{resolved_page_id}/conversations/{conversation_id}/messages"
        params = {"page_access_token": ptoken}
        payload = {
            "action": action or "reply_inbox",
            "message": message,
        }
        if action in ("reply_comment", "private_replies") and "message_id" not in kwargs:
            payload["message_id"] = conversation_id
        for k, v in kwargs.items():
            if v is not None:
                payload[k] = v

        try:
            resp = self.session.post(url, params=params, json=payload, timeout=10)
            if resp.status_code in (200, 201):
                try:
                    data = resp.json()
                except Exception:
                    data = {"text": resp.text}

                # Pancake API có thể trả 200 nhưng success=false hoặc trả message_code
                if "success" not in data:
                    data["success"] = True if data.get("id") else False
                elif not data.get("success"):
                    details = []
                    if data.get("message"):
                        details.append(str(data.get("message")))
                    if data.get("message_code"):
                        details.append(f"code: {data.get('message_code')}")
                    if data.get("error_code"):
                        details.append(f"err: {data.get('error_code')}")
                    if data.get("description"):
                        details.append(str(data.get("description")))
                    data["message"] = " | ".join(details) if details else "Sending message failed"
                return data
            else:
                return {"success": False, "status_code": resp.status_code, "message": resp.text}
        except Exception as e:
            return {"success": False, "message": str(e)}

