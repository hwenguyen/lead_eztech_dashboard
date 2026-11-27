import os
import re
import json
import base64
import logging
import requests
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import threading
from etl.utils import (
    is_page_id,
    resolve_canonical_page_name,
    KNOWN_PAGE_NAMES,
    parse_pancake_date,
    VN_TZ,
    clean_html,
    normalize_phone,
    extract_phone_number,
    is_company_phone,
    build_post_url,
    resolve_api_page_id,
    get_candidate_api_page_ids,
    is_zalo_channel,
)

_TOKEN_CACHE_LOCK = threading.Lock()
_PAGE_TOKEN_CACHE: Dict[str, tuple] = {}  # key -> (timestamp, ptoken, resolved_page_id, resolved_page_name)
_USER_PAGES_CACHE: Dict[str, tuple] = {}  # user_token_key -> (timestamp, pages_list)
_PAGE_TOKEN_TTL = 1800.0


logger = logging.getLogger(__name__)


def create_http_session() -> requests.Session:
    """Tạo requests.Session có connection pooling và keep-alive để tái sử dụng TLS connection."""
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=25,
        pool_maxsize=25,
        max_retries=Retry(
            total=3,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            respect_retry_after_header=True,
            raise_on_status=False
        )
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


DEFAULT_FALLBACK_PANCAKE_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJuYW1lIjoiSGnhu4FuIE1pbmggTMO9IiwiZXhwIjoxODAyMjQ3MjQ1LCJhcHBsaWNhdGlvbiI6MSwidWlkIjoiOTg1NWYzNTQtN2E0Ni00OTUyLTlhNGEtYzk0YWVhZGYzOGQ2Iiwic2Vzc2lvbl9pZCI6IjY1ZTFmNzFjLTI4NTgtNGNjYi1hYzQyLWY2MDQzOTU4NzYxOCIsImlhdCI6MTc5NDQ3MTI0NSwicGFuY2FrZV9pZCI6IjUzYjAwNWNiLWY1YTYtNDhkNy1iNjk0LWM3YTg3MGE4MjgzOCIsImZiX2lkIjoiMTkwMDQyNDQ4MzUxODE0MCIsImxvZ2luX3Nlc3Npb24iOm51bGwsImZiX25hbWUiOiJIaeG7gW4gTWluaCBMw70ifQ.o-MmULfSo154E_VRW6D6kB-Nk7FfSW24XtZEp8pmhDc"


def _is_user_jwt(token: Optional[str]) -> bool:
    """Nhận diện JWT cấp User (chứa uid / pancake_id / session_id) để tránh gọi thừa /v1/pages bằng Page Token."""
    if not token or token.count(".") != 2:
        return False
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        return isinstance(payload, dict) and any(k in payload for k in ("uid", "pancake_id", "session_id"))
    except Exception:
        return False


def _is_token_error(data: Any) -> bool:
    """Kiểm tra phản hồi lỗi token từ Pancake API (102: Invalid, 105: Renewed, 190: Expired)."""
    if not isinstance(data, dict) or data.get("success") is not False:
        return False
    err_code = data.get("error_code")
    if err_code in (102, 105, 190, "102", "105", "190"):
        return True
    msg = str(data.get("message") or "").lower()
    return any(k in msg for k in ("invalid access_token", "access_token renewed", "access_token expired", "invalid token"))


class PancakeClient:
    def __init__(self, api_token: Optional[str] = None):
        self.api_token = api_token or os.getenv("PANCAKE_API_TOKEN") or DEFAULT_FALLBACK_PANCAKE_TOKEN
        self.limit = int(os.getenv("CRAWL_LIMIT", "300")) 
        self.base_url = "https://pages.fm/api/v1"
        self.session = create_http_session()

    def _fetch_pages_cached(self, user_token: str, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Lấy danh sách pages từ /api/v1/pages kèm cache dùng chung giữa các client để tránh 429."""
        if not user_token or not _is_user_jwt(user_token):
            return []
        u_key = user_token[:24]
        now_ts = time.time()
        with _TOKEN_CACHE_LOCK:
            if not force_refresh and u_key in _USER_PAGES_CACHE:
                ts, cached_pages = _USER_PAGES_CACHE[u_key]
                if now_ts - ts < _PAGE_TOKEN_TTL and cached_pages:
                    return cached_pages
            elif force_refresh:
                _USER_PAGES_CACHE.pop(u_key, None)

        headers = {
            "Authorization": f"Bearer {user_token}",
            "User-Agent": "Pancake-Python-Client/1.0",
            "Accept": "application/json",
        }
        for attempt in range(2):
            try:
                res = self.session.get(
                    f"{self.base_url}/pages",
                    params={"access_token": user_token},
                    headers=headers,
                    timeout=15,
                )
                if res.status_code == 200:
                    data = res.json()
                    pages = data.get("data", [])
                    if not pages and "categorized" in data:
                        pages = data["categorized"].get("activated", [])
                    if isinstance(pages, list) and pages:
                        with _TOKEN_CACHE_LOCK:
                            _USER_PAGES_CACHE[u_key] = (time.time(), pages)
                        return pages
                    return []
                if res.status_code == 429 and attempt == 0:
                    time.sleep(2.5)
                    continue
                break
            except Exception as e:
                logger.debug(f"Không thể tra cứu danh sách page qua /pages: {e}")
                break
        return []

    def _get_page_access_token(self, page_id_or_name: str, conversation_id: Optional[str] = None, force_refresh: bool = False) -> tuple:
        """
        Lấy page_access_token và page_id chính xác.
        Hỗ trợ cả User Access Token (tự sinh page_access_token) và Page Access Token truyền trực tiếp.
        Có bộ nhớ đệm (cache 30 phút) để không gọi lặp lại /pages và /generate_page_access_token cho mỗi tin nhắn.
        """
        # 1. Phân giải chuẩn xác page_id thực tế của Pancake API từ tên chữ hoặc conversation_id
        resolved_page_id = resolve_api_page_id(page_id_or_name, conversation_id) or str(page_id_or_name or "").strip()
        resolved_page_name = resolve_canonical_page_name(page_id_or_name or resolved_page_id, fallback=None)
        if resolved_page_name == resolved_page_id and is_page_id(resolved_page_id):
            resolved_page_name = None

        master_user_token = (os.getenv("PANCAKE_API_TOKEN") or "").strip()
        if not master_user_token:
            try:
                from etl.pipeline import load_tokens_from_db
                _, db_default_tok = load_tokens_from_db()
                if db_default_tok and _is_user_jwt(db_default_tok):
                    master_user_token = db_default_tok
            except Exception:
                pass
        if not master_user_token:
            master_user_token = DEFAULT_FALLBACK_PANCAKE_TOKEN

        # Nếu self.api_token chưa được truyền lúc khởi tạo, tự động tra cứu từ cấu hình hệ thống / DB theo từng Page
        active_token = self.api_token
        if not active_token:
            try:
                from etl.pipeline import get_token_for_page
                active_token = get_token_for_page(resolved_page_id, conversation_id)
            except Exception as e:
                logger.debug(f"Không thể tra cứu get_token_for_page: {e}")

        if not active_token:
            active_token = master_user_token

        if not active_token:
            logger.error(f"Không có PANCAKE_API_TOKEN để kết nối Pancake API cho Page '{page_id_or_name}' (resolved: '{resolved_page_id}').")
            return None, resolved_page_id, resolved_page_name

        cache_key = f"{active_token[:16]}:{resolved_page_id}"
        now_ts = time.time()
        with _TOKEN_CACHE_LOCK:
            if not force_refresh and cache_key in _PAGE_TOKEN_CACHE:
                ts, cached_ptoken, cached_pid, cached_pname = _PAGE_TOKEN_CACHE[cache_key]
                if now_ts - ts < _PAGE_TOKEN_TTL and cached_ptoken:
                    return cached_ptoken, cached_pid, cached_pname
            elif force_refresh:
                _PAGE_TOKEN_CACHE.pop(cache_key, None)

        # Khi force_refresh (token cũ báo lỗi 102/105), ưu tiên master_user_token để làm mới
        user_tokens_order: List[str] = []
        if force_refresh:
            for cand_u in (master_user_token, DEFAULT_FALLBACK_PANCAKE_TOKEN, active_token):
                if cand_u and _is_user_jwt(cand_u) and cand_u not in user_tokens_order:
                    user_tokens_order.append(cand_u)
        else:
            for cand_u in (active_token, master_user_token, DEFAULT_FALLBACK_PANCAKE_TOKEN):
                if cand_u and _is_user_jwt(cand_u) and cand_u not in user_tokens_order:
                    user_tokens_order.append(cand_u)

        # 2. Tra cứu page_access_token sẵn có từ /pages (cache chung)
        target = resolved_page_id
        target_num = re.sub(r"^(pzl_|tt_|fb_)", "", target)
        # Chỉ tra qua /pages khi active_token là User JWT HOẶC đang force_refresh do Page Token cũ bị hết hạn
        pages_lookup_tokens = user_tokens_order if (_is_user_jwt(active_token) or force_refresh) else []
        for idx_u, u_tok in enumerate(pages_lookup_tokens):
            pages = self._fetch_pages_cached(u_tok, force_refresh=(force_refresh and idx_u == 0))
            for p in pages:
                p_id = str(p.get("id"))
                p_name = p.get("name")
                if p_id in (target, target_num) or (p_name and p_name in (str(page_id_or_name).strip(), resolved_page_name)):
                    resolved_page_id = p_id
                    resolved_page_name = p_name or resolved_page_name
                    direct_ptoken = p.get("page_access_token") or (p.get("settings") or {}).get("page_access_token")
                    if direct_ptoken:
                        with _TOKEN_CACHE_LOCK:
                            _PAGE_TOKEN_CACHE[cache_key] = (now_ts, direct_ptoken, resolved_page_id, resolved_page_name)
                        return direct_ptoken, resolved_page_id, resolved_page_name
                    break

        # 3. Tạo page_access_token mới qua /generate_page_access_token nếu chưa có trong /pages hoặc đang refresh
        candidate_ids = get_candidate_api_page_ids(resolved_page_id, conversation_id) or [resolved_page_id]
        tokens_to_generate = user_tokens_order if (_is_user_jwt(active_token) or force_refresh) else [active_token] + [t for t in user_tokens_order if t != active_token]
        for u_tok in tokens_to_generate:
            for cand_id in candidate_ids:
                try:
                    res_token = self.session.post(
                        f"{self.base_url}/pages/{cand_id}/generate_page_access_token",
                        params={"access_token": u_tok},
                        timeout=15
                    )
                    if res_token.status_code == 200:
                        token_data = res_token.json()
                        if token_data.get("success") and token_data.get("page_access_token"):
                            ptoken = token_data["page_access_token"]
                            with _TOKEN_CACHE_LOCK:
                                _PAGE_TOKEN_CACHE[cache_key] = (now_ts, ptoken, cand_id, resolved_page_name)
                            return ptoken, cand_id, resolved_page_name
                except Exception as e:
                    logger.debug(f"Lỗi khi gọi generate_page_access_token cho {cand_id}: {e}")

        # 4. Fallback: Bản thân active_token chính là Page Access Token của Page đó
        resolved_page_name = resolved_page_name or resolve_canonical_page_name(resolved_page_id, fallback=None)
        with _TOKEN_CACHE_LOCK:
            _PAGE_TOKEN_CACHE[cache_key] = (now_ts, active_token, resolved_page_id, resolved_page_name)
        return active_token, resolved_page_id, resolved_page_name

    def get_conversations(
        self,
        page_id: str,
        existing_cache: Optional[Dict[str, Any]] = None,
        days_back: Optional[int] = None,
        cache_loader: Optional[Callable[[List[str]], Dict[str, Any]]] = None,
        start_after_id: Optional[str] = None
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
        since_ts = int((datetime.utcnow() - timedelta(days=365 * 3)).timestamp())
        if days_back and days_back > 0:
            cutoff_dt = datetime.now(VN_TZ).replace(tzinfo=None) - timedelta(days=days_back)
        else:
            cutoff_dt = None
        
        t_list = time.perf_counter()
        all_convs = []
        last_id = start_after_id
        retry_count = 0
        max_retries = 3

        raw_page_id = page_id
        token_refreshed = False

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
                    if not token_refreshed and _is_token_error(data):
                        logger.warning(f"Token Pancake Page '{page_id}' hết hạn/lỗi ({err_code}: {err_msg}), đang tự làm mới...")
                        fresh_ptok, fresh_pid, _ = self._get_page_access_token(raw_page_id, force_refresh=True)
                        token_refreshed = True
                        if fresh_ptok and fresh_ptok != ptoken:
                            ptoken = fresh_ptok
                            if fresh_pid:
                                page_id = fresh_pid
                                url_convs = f"https://pages.fm/api/public_api/v2/pages/{page_id}/conversations"
                            continue
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
        notes_by_conv: Dict[str, list] = {}
        if convs_to_fetch:
            t_msgs = time.perf_counter()

            def fetch_single_conversation_messages(cid):
                url = f"https://pages.fm/api/public_api/v1/pages/{page_id}/conversations/{cid}/messages"
                max_retries = 3
                for attempt in range(1, max_retries + 1):
                    try:
                        resp = self.session.get(
                            url,
                            params={"page_access_token": ptoken},
                            timeout=25
                        )
                        if resp.status_code == 200:
                            body = resp.json()
                            return cid, body.get('messages', []), body.get('notes', [])
                        elif resp.status_code == 429:
                            time.sleep(3.0 * attempt)
                            continue
                        elif resp.status_code in (500, 502, 503, 504):
                            time.sleep(2.0 * attempt)
                            continue
                        else:
                            break
                    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                        if attempt < max_retries:
                            time.sleep(2.0 * attempt)
                            continue
                        logger.debug(f"Timeout/lỗi kết nối khi tải messages conversation {cid}: {e}")
                    except Exception as e:
                        logger.debug(f"Lỗi khi tải messages cho conversation {cid}: {e}")
                        break
                return cid, None, None  # None = tải lỗi (khác với hội thoại thật sự không có tin)

            failed = 0
            # Sử dụng 4 workers để giảm áp lực lên server Pancake (chống lỗi 500 Server internal error & Read timed out)
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_conv = {executor.submit(fetch_single_conversation_messages, cid): cid for cid in convs_to_fetch}
                for future in as_completed(future_to_conv):
                    cid = future_to_conv[future]
                    try:
                        _, msgs, fetched_notes = future.result()
                    except Exception as e:
                        logger.error(f"Lỗi future messages cid {cid}: {e}")
                        msgs, fetched_notes = None, None
                    if msgs is None:
                        # Tải lỗi → giữ tin nhắn đã lưu thay vì ghi đè bằng danh sách rỗng
                        failed += 1
                        failed_msg_ids.add(cid)
                        msgs = (existing_cache.get(cid) or {}).get('messages', [])
                    messages_by_conv[cid] = msgs
                    if fetched_notes:
                        notes_by_conv[cid] = fetched_notes
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

            # Tìm SĐT trực tiếp từ đối tượng conversation / customer / page_customer (bỏ qua hotline nội bộ)
            phone = None
            phone_candidates = []
            recent_phones = conv.get('recent_phone_numbers', [])
            if isinstance(recent_phones, list):
                for rp in recent_phones:
                    if isinstance(rp, dict) and rp.get('phone_number'):
                        phone_candidates.append(rp.get('phone_number'))
                    elif isinstance(rp, str) and rp.strip():
                        phone_candidates.append(rp.strip())
            if isinstance(customers, list) and customers:
                c0 = customers[0] if isinstance(customers[0], dict) else {}
                if c0.get('phone_number'):
                    phone_candidates.append(c0.get('phone_number'))
                if isinstance(c0.get('phone_numbers'), list):
                    phone_candidates.extend(c0.get('phone_numbers'))
            page_cust = conv.get('page_customer') if isinstance(conv.get('page_customer'), dict) else {}
            if page_cust.get('phone_number'):
                phone_candidates.append(page_cust.get('phone_number'))
            if isinstance(page_cust.get('phone_numbers'), list):
                phone_candidates.extend(page_cust.get('phone_numbers'))
            for cand in phone_candidates:
                norm_cand = normalize_phone(cand)
                if norm_cand and not is_company_phone(norm_cand):
                    phone = cand
                    break

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
                        "sender_name": m_from.get('admin_name') or m.get('admin_name') or m_from.get('name') or m_from.get('username') or "Unknown"
                    })
            
            # Trích xuất ghi chú của Admin/Sale trên Pancake (từ page_customer.notes, conv.notes hoặc endpoint /messages)
            raw_notes_pool = (
                notes_by_conv.get(conv_id)
                or ((conv.get("page_customer") or {}).get("notes") if isinstance(conv.get("page_customer"), dict) else None)
                or conv.get("notes")
                or []
            )
            formatted_notes = []
            seen_note_msgs = set()
            if isinstance(raw_notes_pool, list):
                for nt in raw_notes_pool:
                    if not isinstance(nt, dict) or nt.get("removed_at"):
                        continue
                    nt_msg = clean_html(str(nt.get("message") or "")).strip()
                    if not nt_msg or nt_msg in seen_note_msgs:
                        continue
                    seen_note_msgs.add(nt_msg)
                    cb = nt.get("created_by") if isinstance(nt.get("created_by"), dict) else {}
                    author = cb.get("fb_name") or cb.get("name") or nt.get("author") or "Admin"
                    formatted_notes.append({
                        "message": nt_msg,
                        "author": str(author).strip(),
                        "created_at": nt.get("created_at"),
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
                "notes": formatted_notes,
                "inserted_at": conv.get("inserted_at"),
                "updated_at": updated_at,
                "ads": conv.get("ads"),
                "ad_ids": conv.get("ad_ids"),
                "post_id": conv.get("post_id"),
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

        raw_page_id = page_id
        page_id = resolved_page_id
        url_convs = f"https://pages.fm/api/public_api/v2/pages/{page_id}/conversations"

        now_ts = int(datetime.utcnow().timestamp())
        since_ts = int((datetime.utcnow() - timedelta(days=365 * 3)).timestamp())
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
        token_refreshed = False

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
                    if not token_refreshed and _is_token_error(data):
                        logger.warning(f"Token comment Page '{page_id}' lỗi ({data.get('message')}), đang làm mới...")
                        fresh_ptok, fresh_pid, _ = self._get_page_access_token(raw_page_id, force_refresh=True)
                        token_refreshed = True
                        if fresh_ptok and fresh_ptok != ptoken:
                            ptoken = fresh_ptok
                            if fresh_pid:
                                page_id = fresh_pid
                                url_convs = f"https://pages.fm/api/public_api/v2/pages/{page_id}/conversations"
                            api_page_count -= 1
                            continue
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
            conv_msg_count = conv.get('message_count', 1)
            cached_data = existing_cache.get(cid)
            is_unchanged = False
            if cached_data:
                cached_dt = cached_data.get('updated_at')
                parsed_dt = parse_pancake_date(conv_updated)
                if (cached_dt and parsed_dt and cached_dt == parsed_dt) or (str(cached_dt) == str(conv_updated)):
                    if cached_data.get('message_count') == conv_msg_count:
                        is_unchanged = True
            if is_unchanged:
                messages_by_conv[cid] = [{"is_cached": True}]
            else:
                convs_to_fetch.append(cid)

        if convs_to_fetch:
            t_msgs = time.perf_counter()

            def fetch_single_comment_messages(cid):
                url = f"https://pages.fm/api/public_api/v1/pages/{page_id}/conversations/{cid}/messages"
                max_retries = 3
                for attempt in range(1, max_retries + 1):
                    try:
                        resp = self.session.get(url, params={"page_access_token": ptoken}, timeout=25)
                        if resp.status_code == 200:
                            return cid, resp.json().get('messages', [])
                        elif resp.status_code == 429:
                            time.sleep(3.0 * attempt)
                            continue
                        elif resp.status_code in (500, 502, 503, 504):
                            time.sleep(2.0 * attempt)
                            continue
                        else:
                            break
                    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                        if attempt < max_retries:
                            time.sleep(2.0 * attempt)
                            continue
                    except Exception:
                        break
                return cid, []

            with ThreadPoolExecutor(max_workers=4) as executor:
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
                "is_cached": bool(msgs and msgs[0].get("is_cached")),
            })

        logger.info(f"Hoàn tất xử lý comment Page {page_id}! Tổng cộng: {len(results)} comments.")
        return results

    def get_posts(
        self,
        page_id: str,
        days_back: Optional[int] = None,
        limit: Optional[int] = None,
        post_type: Optional[str] = None,
        since_ts: Optional[int] = None,
        until_ts: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Lấy danh sách Bài viết (Posts) từ Page qua Pancake Public API v1.
        API: GET https://pages.fm/api/public_api/v1/pages/{page_id}/posts

        Args:
            page_id: ID của Page (hỗ trợ prefix fb_, tt_...)
            days_back: Số ngày quét ngược về trước (mặc định 365 ngày nếu không truyền since_ts)
            limit: Số lượng bài viết tối đa cần lấy (mặc định 100)
            post_type: Lọc theo loại bài viết ('video', 'photo', 'text', 'livestream')
            since_ts: Unix timestamp bắt đầu (UTC)
            until_ts: Unix timestamp kết thúc (UTC)
        """
        ptoken, resolved_page_id, resolved_page_name = self._get_page_access_token(page_id)
        if not ptoken:
            logger.warning(f"Không lấy được token cho Page {page_id} khi lấy Posts.")
            return []

        url = f"https://pages.fm/api/public_api/v1/pages/{resolved_page_id}/posts"
        now_dt = datetime.utcnow()
        if until_ts is None:
            until_ts = int(now_dt.timestamp())
        if since_ts is None:
            days = days_back if (days_back and days_back > 0) else 365
            since_ts = int((now_dt - timedelta(days=days)).timestamp())

        max_limit = limit or 100
        page_size = min(30, max_limit)
        page_number = 1
        all_posts: List[Dict[str, Any]] = []
        retry_count = 0
        max_retries = 3

        logger.info(f"--- BẮT ĐẦU CÀO POSTS QUA API CHO PAGE: {page_id} (Giới hạn: {max_limit}, Ngày quét: {days_back or '365 ngày'}) ---")
        t_start = time.perf_counter()
        token_refreshed = False

        while len(all_posts) < max_limit:
            params = {
                "page_access_token": ptoken,
                "since": since_ts,
                "until": until_ts,
                "page_number": page_number,
                "page_size": page_size,
            }
            if post_type:
                params["type"] = post_type

            try:
                resp = self.session.get(url, params=params, timeout=30)
            except Exception as e:
                logger.error(f"Lỗi kết nối khi gọi /posts trang {page_number} cho Page {page_id}: {e}")
                retry_count += 1
                if retry_count <= max_retries:
                    time.sleep(3 * retry_count)
                    continue
                else:
                    break

            if resp.status_code == 200:
                retry_count = 0
                try:
                    data = resp.json()
                except Exception:
                    data = {}

                if isinstance(data, dict) and data.get("success") is False:
                    if not token_refreshed and _is_token_error(data):
                        logger.warning(f"Token posts Page '{page_id}' lỗi ({data.get('message')}), đang làm mới...")
                        fresh_ptok, fresh_pid, _ = self._get_page_access_token(page_id, force_refresh=True)
                        token_refreshed = True
                        if fresh_ptok and fresh_ptok != ptoken:
                            ptoken = fresh_ptok
                            if fresh_pid:
                                url = f"https://pages.fm/api/public_api/v1/pages/{fresh_pid}/posts"
                            continue
                    logger.warning(f"Pancake API từ chối lấy posts cho Page '{page_id}': {data.get('message')}")
                    break

                raw_posts = data.get("posts") if isinstance(data, dict) else []
                if not raw_posts and isinstance(data, dict):
                    raw_posts = data.get("data", [])

                if not raw_posts:
                    break

                all_posts.extend(raw_posts)

                total = data.get("total") if isinstance(data, dict) else None
                if total and len(all_posts) >= total:
                    break
                if len(raw_posts) < page_size:
                    break

                page_number += 1
                time.sleep(0.2)
            elif resp.status_code == 429:
                logger.warning("Pancake API Rate limit (429) khi lấy posts! Nghỉ 10s...")
                time.sleep(10)
                continue
            elif resp.status_code == 500:
                retry_count += 1
                if retry_count <= max_retries:
                    time.sleep(3 * retry_count)
                    continue
                else:
                    logger.error(f"Pancake API trả status 500 khi lấy posts Page {page_id}: {resp.text[:200]}")
                    break
            else:
                logger.warning(f"Pancake API trả status {resp.status_code} khi lấy posts Page {page_id}: {resp.text[:200]}")
                break

        all_posts = all_posts[:max_limit]
        logger.info(f"Đã tải {len(all_posts)} bài viết (posts) trong {time.perf_counter() - t_start:.1f}s.")

        is_tiktok = str(page_id).startswith("tt_") or "tiktok" in resolve_canonical_page_name(page_id).lower()
        platform = "tiktok" if is_tiktok else "facebook"

        results = []
        for p in all_posts:
            pid = str(p.get("id") or "")
            if not pid:
                continue

            creator = p.get("from") or {}
            c_id = str(creator.get("id") or "") or None
            c_name = creator.get("name")
            cmt_cnt = p.get("comment_count", 0)
            reactions = p.get("reactions") or {}
            like_cnt = reactions.get("like_count") or p.get("digg_count") or p.get("like_count") or 0
            love_cnt = reactions.get("love_count", 0)
            haha_cnt = reactions.get("haha_count", 0)
            wow_cnt = reactions.get("wow_count", 0)
            sad_cnt = reactions.get("sad_count", 0)
            angry_cnt = reactions.get("angry_count", 0)
            care_cnt = reactions.get("care_count", 0)
            rx_total = sum([like_cnt, love_cnt, haha_cnt, wow_cnt, sad_cnt, angry_cnt, care_cnt])
            share_cnt = p.get("share_count", 0)
            view_cnt = p.get("play_count") or p.get("view_count") or 0
            phone_cnt = p.get("phone_number_count", 0)

            raw_url = p.get("permalink_url") or p.get("url") or p.get("post_url")
            final_url = build_post_url(pid, page_id, raw_url)

            results.append({
                "post_id": pid,
                "page_id": str(page_id),
                "platform": platform,
                "type": p.get("type") or ("video" if is_tiktok else "post"),
                "message": p.get("message") or p.get("title") or p.get("description"),
                "post_url": final_url,
                "creator_id": c_id,
                "creator_name": c_name,
                "comment_count": cmt_cnt,
                "like_count": like_cnt,
                "love_count": love_cnt,
                "haha_count": haha_cnt,
                "wow_count": wow_cnt,
                "sad_count": sad_cnt,
                "angry_count": angry_cnt,
                "care_count": care_cnt,
                "reactions_total": rx_total,
                "share_count": share_cnt,
                "view_count": view_cnt,
                "phone_number_count": phone_cnt,
                "inserted_at": p.get("inserted_at") or p.get("created_time"),
                "updated_at": p.get("updated_at"),
                "payload": p,
            })

        return results

    def _post_page_endpoint(
        self,
        page_id: str,
        endpoint_suffix: str,
        conversation_id: Optional[str] = None,
        json_payload: Optional[dict] = None,
        files: Optional[dict] = None,
        timeout: int = 30,
        action_label: str = "request",
    ) -> dict:
        """Gửi POST tới endpoint thuộc Page kèm retry, auto làm mới token và fallback candidate page IDs."""
        ptoken, resolved_page_id, _ = self._get_page_access_token(page_id, conversation_id=conversation_id)
        if not ptoken:
            return {
                "success": False,
                "message": f"Thiếu Pancake Token cho kênh '{page_id}'. Vui lòng bấm 'Cấu hình Token Pancake' trên giao diện để nhập Token."
            }

        resolved_page_id = resolve_api_page_id(resolved_page_id or page_id, conversation_id) or resolved_page_id
        candidate_page_ids = get_candidate_api_page_ids(resolved_page_id, conversation_id) or [resolved_page_id]
        params = {"page_access_token": ptoken}

        max_retries = 3
        last_error = None
        last_resp_data = None

        for pid_idx, cand_pid in enumerate(candidate_page_ids):
            target_url = f"https://pages.fm/api/public_api/v1/pages/{cand_pid}/{endpoint_suffix}"

            for attempt in range(1, max_retries + 1):
                try:
                    post_kwargs: Dict[str, Any] = {"params": params, "timeout": timeout}
                    if files is not None:
                        post_kwargs["files"] = files
                    if json_payload is not None:
                        post_kwargs["json"] = json_payload

                    resp = self.session.post(target_url, **post_kwargs)
                    if resp.status_code in (200, 201):
                        try:
                            data = resp.json()
                        except Exception:
                            data = {"text": resp.text}

                        if "success" not in data:
                            data["success"] = True if data.get("id") else False

                        if data.get("success"):
                            return data

                        details = []
                        if data.get("message"):
                            details.append(str(data.get("message")))
                        if data.get("message_code"):
                            details.append(f"code: {data.get('message_code')}")
                        if data.get("error_code"):
                            details.append(f"err: {data.get('error_code')}")
                        if data.get("description"):
                            details.append(str(data.get("description")))
                        err_str = " | ".join(details) if details else "Sending message failed"
                        last_error = err_str
                        last_resp_data = data

                        if attempt < max_retries and (
                            _is_token_error(data)
                            or any(k in err_str.lower() for k in ("invalid access_token", "access_token renewed", "102", "105", "190"))
                        ):
                            logger.info(f"[PANCAKE API] Token không hợp lệ ({err_str}). Đang tự động làm mới token cho Page '{cand_pid}'...")
                            fresh_ptoken, _, _ = self._get_page_access_token(cand_pid, conversation_id=conversation_id, force_refresh=True)
                            if fresh_ptoken and fresh_ptoken != params.get("page_access_token"):
                                params["page_access_token"] = fresh_ptoken
                                time.sleep(1.0)
                                continue

                        if pid_idx + 1 < len(candidate_page_ids) and any(
                            k in err_str.lower() for k in ("page", "not found", "invalid access_token", "invalid", "102", "190", "permission")
                        ):
                            logger.info(f"[PANCAKE API] Thử lại với biến thể Page ID '{candidate_page_ids[pid_idx + 1]}' (lỗi cũ: {err_str})")
                            break

                        if "server internal error" in err_str.lower() and attempt < max_retries:
                            time.sleep(2.0 * attempt)
                            continue

                        data["message"] = f"[{cand_pid}] {err_str}"
                        logger.warning(f"[PANCAKE API] Thất bại ({action_label}) [Page={cand_pid}, Conv={conversation_id}]: {data}")
                        return data

                    elif resp.status_code in (400, 404, 422):
                        last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                        if pid_idx + 1 < len(candidate_page_ids):
                            break
                        return {"success": False, "status_code": resp.status_code, "message": f"[{cand_pid}] {last_error}"}

                    elif resp.status_code in (500, 502, 503, 504):
                        last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                        if attempt < max_retries:
                            time.sleep(2.0 * attempt)
                            continue
                        if pid_idx + 1 < len(candidate_page_ids):
                            break
                        return {"success": False, "status_code": resp.status_code, "message": last_error}

                    elif resp.status_code == 429:
                        last_error = "HTTP 429: Quá giới hạn tốc độ gửi (Rate limit exceeded)"
                        if attempt < max_retries:
                            time.sleep(6.0 * attempt)
                            continue
                        return {"success": False, "status_code": 429, "message": last_error}

                    else:
                        last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                        return {"success": False, "status_code": resp.status_code, "message": last_error}

                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                    last_error = f"Lỗi kết nối mạng: {e}"
                    if attempt < max_retries:
                        time.sleep(2.5 * attempt)
                        continue
                    if pid_idx + 1 < len(candidate_page_ids):
                        break
                    return {"success": False, "message": f"[{cand_pid}] {last_error}"}
                except Exception as e:
                    logger.error(f"[PANCAKE API] Lỗi ngoại lệ khi gửi ({action_label}): {e}")
                    return {"success": False, "message": str(e)}

        return last_resp_data or {"success": False, "message": f"[{resolved_page_id}] {last_error or 'Thất bại sau các lần thử lại'}"}

    def upload_content(
        self,
        page_id: str,
        file_bytes: bytes,
        filename: str,
        content_type: str = "image/jpeg",
        conversation_id: Optional[str] = None,
    ) -> dict:
        """
        Upload ảnh/media lên Pancake Page để lấy content_id dùng trong send_message.
        API: POST https://pages.fm/api/public_api/v1/pages/{page_id}/upload_contents
        """
        if not file_bytes:
            return {"success": False, "message": "File rỗng, không thể upload lên Pancake."}

        res = self._post_page_endpoint(
            page_id=page_id,
            endpoint_suffix="upload_contents",
            conversation_id=conversation_id,
            files={"file": (filename or "image.jpg", file_bytes, content_type or "image/jpeg")},
            timeout=60,
            action_label="upload_contents",
        )
        if res.get("success") and not res.get("id"):
            return {**res, "success": False, "message": f"[{page_id}] Pancake không trả về attachment id sau khi upload."}
        return res

    def send_message(
        self,
        page_id: str,
        conversation_id: str,
        message: Optional[str] = "",
        action: str = "reply_inbox",
        **kwargs
    ) -> dict:
        """
        Gửi tin nhắn phản hồi vào hội thoại qua Pancake Public API v1.
        API: POST https://pages.fm/api/public_api/v1/pages/{page_id}/conversations/{conversation_id}/messages

        Lưu ý theo OpenAPI Pancake: Với InboxMessage, `message` và `content_ids` loại trừ lẫn nhau.
        """
        is_tiktok = str(page_id).startswith("tt_") or str(conversation_id).startswith("tt_")

        # === TIKTOK COMMENT: Giữ nguyên fallback 3 kiểu payload cho TikTok reply_comment ===
        if is_tiktok and action == "reply_comment":
            ptoken, resolved_page_id, _ = self._get_page_access_token(page_id, conversation_id=conversation_id)
            if not ptoken:
                return {
                    "success": False,
                    "message": f"Thiếu Pancake Token cho kênh '{page_id}'. Vui lòng bấm 'Cấu hình Token Pancake' trên giao diện để nhập Token."
                }
            resolved_page_id = resolve_api_page_id(resolved_page_id or page_id, conversation_id) or resolved_page_id
            url = f"https://pages.fm/api/public_api/v1/pages/{resolved_page_id}/conversations/{conversation_id}/messages"
            params = {"page_access_token": ptoken}
            target_msg_id = kwargs.get("message_id") or conversation_id
            tiktok_payloads = [
                {"message": message},
                {"action": "reply_comment", "message": message, "message_id": str(target_msg_id)},
                {"action": "reply_comment", "message": message, "message_id": str(target_msg_id), "content_ids": []},
            ]
            token_refreshed = False

            for idx, tk_payload in enumerate(tiktok_payloads, 1):
                logger.info(f"[PANCAKE API][TIKTOK] Thử payload #{idx}: {tk_payload}")
                try:
                    resp = self.session.post(url, params=params, json=tk_payload, timeout=30)
                    if resp.status_code in (200, 201):
                        try:
                            data = resp.json()
                        except Exception:
                            data = {"text": resp.text}
                        if "success" not in data:
                            data["success"] = True if data.get("id") else False
                        if data.get("success"):
                            return data
                        if not token_refreshed and _is_token_error(data):
                            fresh_ptoken, fresh_pid, _ = self._get_page_access_token(page_id, conversation_id=conversation_id, force_refresh=True)
                            token_refreshed = True
                            if fresh_ptoken and fresh_ptoken != params.get("page_access_token"):
                                params["page_access_token"] = fresh_ptoken
                                if fresh_pid:
                                    resolved_page_id = resolve_api_page_id(fresh_pid, conversation_id) or fresh_pid
                                    url = f"https://pages.fm/api/public_api/v1/pages/{resolved_page_id}/conversations/{conversation_id}/messages"
                                resp = self.session.post(url, params=params, json=tk_payload, timeout=30)
                                if resp.status_code in (200, 201):
                                    retry_data = resp.json()
                                    if retry_data.get("success"):
                                        return retry_data
                        err_msg = data.get("message") or data.get("description") or str(data)
                        if idx < len(tiktok_payloads):
                            time.sleep(1.5)
                            continue
                        data["message"] = str(err_msg)
                        return data
                    elif idx < len(tiktok_payloads):
                        time.sleep(1.5 if resp.status_code < 500 else 2.0)
                        continue
                    return {"success": False, "status_code": resp.status_code, "message": resp.text}
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                    if idx < len(tiktok_payloads):
                        time.sleep(2.0)
                        continue
                    return {"success": False, "message": str(e)}

            return {"success": False, "message": "Tất cả payload TikTok đều thất bại"}

        # === FACEBOOK / ZALO / KHÁC ===
        content_ids = kwargs.get("content_ids")
        payload: Dict[str, Any] = {
            "action": action or "reply_inbox",
        }

        # Pancake InboxMessage: message và content_ids loại trừ lẫn nhau (gửi đồng thời sẽ lỗi 500)
        if action != "reply_comment" and isinstance(content_ids, list) and len(content_ids) > 0:
            payload["content_ids"] = content_ids
        else:
            payload["message"] = message or ""
            if action == "reply_comment":
                payload["content_ids"] = content_ids if content_ids is not None else []
            elif isinstance(content_ids, list) and len(content_ids) > 0:
                payload["content_ids"] = content_ids

        target_msg_id = kwargs.get("message_id") or conversation_id
        if action in ("reply_comment", "private_replies"):
            payload["message_id"] = str(target_msg_id)
        if kwargs.get("sender_id"):
            payload["sender_id"] = kwargs["sender_id"]
        if kwargs.get("mentions") is not None:
            payload["mentions"] = kwargs["mentions"]

        for k, v in kwargs.items():
            if k not in payload and k != "content_ids" and v is not None:
                payload[k] = v

        return self._post_page_endpoint(
            page_id=page_id,
            endpoint_suffix=f"conversations/{conversation_id}/messages",
            conversation_id=conversation_id,
            json_payload=payload,
            timeout=30,
            action_label=action or "reply_inbox",
        )

    def list_page_conversations(
        self,
        page_id: str,
        max_convs: int = 300,
        include_groups: bool = True,
        only_groups: bool = False,
        only_personal_zalo: bool = False,
        max_api_pages: int = 15,
    ) -> List[Dict[str, Any]]:
        """Liệt kê hội thoại thô qua Pancake Public API v2 (hỗ trợ cả nhóm pzl_g_ và chat 1-1 pzl_u_)."""
        ptoken, resolved_page_id, _ = self._get_page_access_token(page_id)
        if not ptoken:
            logger.error(f"Không lấy được access token cho Page '{page_id}'.")
            return []

        active_page_id = resolved_page_id or str(page_id)
        url_convs = f"https://pages.fm/api/public_api/v2/pages/{active_page_id}/conversations"
        collected: List[Dict[str, Any]] = []
        last_id: Optional[str] = None
        token_refreshed = False
        api_pages = 0

        while len(collected) < max_convs and api_pages < max_api_pages:
            api_pages += 1
            params: Dict[str, Any] = {
                "page_access_token": ptoken,
                "order_by": "updated_at",
            }
            if last_id:
                params["last_conversation_id"] = last_id

            try:
                resp = self.session.get(url_convs, params=params, timeout=30)
            except Exception as e:
                logger.warning(f"Lỗi kết nối list_page_conversations ({active_page_id}): {e}")
                break

            if resp.status_code == 429:
                time.sleep(5)
                continue
            if resp.status_code != 200:
                logger.warning(f"list_page_conversations HTTP {resp.status_code}: {resp.text[:300]}")
                break

            data = resp.json()
            if isinstance(data, dict) and data.get("success") is False:
                if not token_refreshed and _is_token_error(data):
                    fresh_tok, fresh_pid, _ = self._get_page_access_token(page_id, force_refresh=True)
                    token_refreshed = True
                    if fresh_tok and fresh_tok != ptoken:
                        ptoken = fresh_tok
                        if fresh_pid:
                            active_page_id = fresh_pid
                            url_convs = f"https://pages.fm/api/public_api/v2/pages/{active_page_id}/conversations"
                        continue
                logger.warning(f"Pancake từ chối list_page_conversations ({active_page_id}): {data.get('message')}")
                break

            convs = data.get("conversations", []) if isinstance(data, dict) else []
            if not convs:
                break

            for conv in convs:
                cid = str(conv.get("id") or "")
                ctype = str(conv.get("type") or "").upper()
                if ctype == "COMMENT":
                    continue
                is_group = cid.startswith("pzl_g_")
                if only_groups and not is_group:
                    continue
                if not include_groups and is_group:
                    continue
                if only_personal_zalo and not cid.startswith("pzl_u_"):
                    continue
                collected.append(conv)
                if len(collected) >= max_convs:
                    break

            new_last_id = convs[-1].get("id")
            if not new_last_id or new_last_id == last_id:
                break
            last_id = str(new_last_id)
            time.sleep(0.2)

        return collected

    def fetch_conversation_messages_page(
        self,
        page_id: str,
        conversation_id: str,
        current_count: int = 0,
    ) -> Dict[str, Any]:
        """Lấy 1 trang (30 tin) của hội thoại từ Pancake Public API v1 (hỗ trợ current_count)."""
        ptoken, resolved_page_id, _ = self._get_page_access_token(page_id, conversation_id=conversation_id)
        if not ptoken:
            return {"success": False, "messages": [], "message": f"Thiếu Pancake token cho page '{page_id}'."}

        active_page_id = resolved_page_id or str(page_id)
        url = f"https://pages.fm/api/public_api/v1/pages/{active_page_id}/conversations/{conversation_id}/messages"
        token_refreshed = False

        for attempt in range(3):
            params: Dict[str, Any] = {"page_access_token": ptoken}
            if current_count > 0:
                params["current_count"] = current_count
            try:
                resp = self.session.get(url, params=params, timeout=30)
            except Exception as e:
                if attempt < 2:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                return {"success": False, "messages": [], "message": str(e)}

            if resp.status_code == 429:
                time.sleep(4.0 * (attempt + 1))
                continue
            if resp.status_code >= 500:
                if attempt < 2:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                return {"success": False, "messages": [], "message": f"HTTP {resp.status_code}"}
            if resp.status_code != 200:
                return {"success": False, "messages": [], "message": f"HTTP {resp.status_code}: {resp.text[:300]}"}

            body = resp.json()
            if isinstance(body, dict) and body.get("success") is False:
                if not token_refreshed and _is_token_error(body):
                    fresh_tok, fresh_pid, _ = self._get_page_access_token(
                        page_id, conversation_id=conversation_id, force_refresh=True
                    )
                    token_refreshed = True
                    if fresh_tok and fresh_tok != ptoken:
                        ptoken = fresh_tok
                        if fresh_pid:
                            active_page_id = fresh_pid
                            url = f"https://pages.fm/api/public_api/v1/pages/{active_page_id}/conversations/{conversation_id}/messages"
                        continue
                return {"success": False, "messages": [], "message": str(body.get("message") or "Pancake API error")}

            return {"success": True, **body} if isinstance(body, dict) else {"success": True, "messages": []}

        return {"success": False, "messages": [], "message": "Quá số lần thử lại khi tải tin nhắn."}


