import os
import json
import logging
import asyncio
import re
import requests
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import nest_asyncio

nest_asyncio.apply()
logger = logging.getLogger(__name__)

class PancakeClient:
    def __init__(self, api_token: str = None):
        self.api_token = api_token or os.getenv("PANCAKE_API_TOKEN")
        self.username = os.getenv("PANCAKE_EMAIL")
        self.password = os.getenv("PANCAKE_PASSWORD")
        self.auth_file = "pancake_auth.json"
        self.limit = int(os.getenv("CRAWL_LIMIT", "300")) 
        self.base_url = "https://pages.fm/api/v1"

    def _fetch_via_api(self, page_id_or_name: str) -> List[Dict[str, Any]]:
        if not self.api_token:
            logger.warning("Không có PANCAKE_API_TOKEN, chuyển thẳng sang Playwright.")
            return []
            
        headers = {"Authorization": f"Bearer {self.api_token}", "User-Agent": "Pancake-Python-Client/1.0", "Accept": "application/json"}
        
        logger.info("Đang kiểm tra quyền truy cập qua API chính thức...")
        try:
            res = requests.get(f"{self.base_url}/pages", params={"access_token": self.api_token}, headers=headers, timeout=10)
            data = res.json()
            pages = data.get("data", [])
            if not pages and "categorized" in data:
                pages = data["categorized"].get("activated", [])
                
            page_id = None
            for p in pages:
                if str(p.get("id")) == str(page_id_or_name) or p.get("name") == page_id_or_name:
                    page_id = p.get("id")
                    break
                    
            if not page_id:
                page_id = page_id_or_name
                
            res_token = requests.post(
                f"{self.base_url}/pages/{page_id}/generate_page_access_token", 
                params={"access_token": self.api_token},
                timeout=10
            )
            token_data = res_token.json()
            
            if not token_data.get("success"):
                logger.warning(f"API từ chối quyền truy cập Page '{page_id_or_name}': {token_data.get('message')}")
                return []
                
            ptoken = token_data['page_access_token']
            logger.info(f"Thành công cấp quyền API. Đang kéo hội thoại siêu tốc...")
            
            url_convs = f"https://pages.fm/api/public_api/v2/pages/{page_id}/conversations"
            now_ts = datetime.utcnow().timestamp()
            since_ts = (datetime.utcnow() - timedelta(days=365*2)).timestamp()
            
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
                    "current_count": 60
                }
                clean_params = {k: v for k, v in params.items() if v is not None}
                
                resp = requests.get(url_convs, params=clean_params, timeout=30)
                if resp.status_code == 200:
                    retry_count = 0
                    convs = resp.json().get('conversations', [])
                    if not convs:
                        break
                    all_convs.extend(convs)
                    last_id = convs[-1].get('id')
                    time.sleep(0.5)
                elif resp.status_code == 429:
                    logger.warning("Lỗi 429: Quá nhanh! Nghỉ 15s...")
                    time.sleep(15)
                    continue
                elif resp.status_code >= 500:
                    retry_count += 1
                    if retry_count <= max_retries:
                        time.sleep(5 * retry_count)
                        continue
                    else:
                        break
                else:
                    break

            all_convs = all_convs[:self.limit]
            
            logger.info(f"Kéo xong {len(all_convs)} hội thoại. Bắt đầu tải messages (đa luồng)...")
            
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            messages_by_conv = {}
            def fetch_conversation_messages(cid):
                url = f"https://pages.fm/api/public_api/v1/pages/{page_id}/conversations/{cid}/messages"
                current_count = 0
                rc = 0
                local_msgs = []
                while True:
                    try:
                        resp = requests.get(url, params={"page_access_token": ptoken, "current_count": current_count}, timeout=10)
                        if resp.status_code == 200:
                            rc = 0
                            msgs = resp.json().get('messages', [])
                            if not msgs: break
                            local_msgs.extend(msgs)
                            current_count += len(msgs)
                            time.sleep(0.1)
                        elif resp.status_code == 429:
                            time.sleep(15)
                            continue
                        elif resp.status_code == 500:
                            rc += 1
                            if rc <= max_retries: time.sleep(2 * rc); continue
                            else: break
                        else: break
                    except Exception:
                        time.sleep(2)
                        continue
                return cid, local_msgs

            with ThreadPoolExecutor(max_workers=50) as executor:
                future_to_conv = {executor.submit(fetch_conversation_messages, conv.get('id')): conv.get('id') for conv in all_convs}
                for future in as_completed(future_to_conv):
                    try:
                        cid, msgs = future.result()
                        messages_by_conv[cid] = msgs
                    except Exception as e:
                        logger.error(f"Lỗi messages cid: {e}")

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
                        # Capture role (admin/customer) and timestamp
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
                
            logger.info(f"API hoàn tất! Trả về {len(results)} kết quả.")
            return results
            
        except Exception as e:
            logger.error(f"Lỗi khi chạy API: {e}")
            return []

    async def _scrape_logic_playwright(self, page_id_or_name: str) -> List[Dict[str, Any]]:
        logger.warning(f"Không có quyền API. Đang khởi động Playwright Fallback cho: {page_id_or_name}")
        urls_data = []
        processed_ids = set()
        consecutive_no_new_items = 0
        MAX_STAGNANT_ATTEMPTS = 50
        
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
                )
                
                if os.path.exists(self.auth_file):
                    context = await browser.new_context(storage_state=self.auth_file)
                    
                page = await context.new_page()

                if not os.path.exists(self.auth_file):
                    if not self.username or not self.password:
                        logger.error("Thiếu PANCAKE_EMAIL hoặc PANCAKE_PASSWORD")
                        return []
                        
                    login_url = 'https://account.pancake.vn/oauth2/authorize?grant_type=code&client_id=53e2d5e33a8940f4a30ba22a4011e52a&redirect_uri=https%3A%2F%2Fpancake.vn%2Fapi%2Fv1%2Fusers%2Fpancake_id_login_success&scope=avatar%2Cemail%2Csubscriptions&verification_method=email&locale=vi&fb_permission=public_profile%2Cemail%2Cpages_manage_metadata%2Cpages_read_engagement%2Cpages_show_list%2Cpages_read_user_content%2Cpages_manage_posts%2Cpages_manage_engagement%2Cpages_messaging%2Cads_read%2Cads_management%2Cpage_events%2Cpages_manage_ads%2Ccatalog_management%2Leads_retrieval%2Cbusiness_management%2Cpages_utility_messaging&fb_required_permission=email%2Cpublic_profile%2Cpages_manage_metadata%2Cpages_read_engagement%2Cpages_show_list%2Cpages_read_user_content%2Cpages_manage_posts%2Cpages_manage_engagement%2Cpages_messaging%2Cpages_utility_messaging&is_mobile_fb=false&state=eyJsb2NhbGUiOiJ2aSIsImNvdW50cnkiOiJWTiIsImJyb3dzZXIiOjEsIm9zIjozLCJkZXZpY2VfdHlwZSI6MywiY2xpZW50X3ZlcnNpb24iOjEsImFwcGxpY2F0aW9uIjoxLCJob3N0bmFtZSI6InBhbmNha2Uudm4ifQ%3D%3D'
                    await page.goto(login_url)

                    await page.locator('input[name="identity"]').fill(self.username)
                    await page.locator('input[name="password"]').fill(self.password)
                    await page.locator('button[type="submit"]').click()

                    try:
                        await page.wait_for_selector('button.approve-btn', timeout=5000)
                        await page.click('button.approve-btn')
                    except:
                        pass
                    
                    await page.wait_for_url("**/dashboard**", timeout=30000)
                    await context.storage_state(path=self.auth_file)
                    logger.info("Đã đăng nhập thành công và lưu session auth.")

                try:
                    dashboard_item = page.locator('.dashboard-page-item', has_text=page_id_or_name).first
                    await dashboard_item.wait_for(state="visible", timeout=40000)
                    await dashboard_item.click(force=True)
                except Exception as e:
                    if not page.is_closed():
                        logger.error(f"- Không tìm thấy Dashboard cho {page_id_or_name}: {e}")
                        await browser.close()
                    return []

                logger.info("Đã vào Dashboard. Đợi UI load...")
                await page.wait_for_load_state('domcontentloaded')
                
                try:
                    svg_icon = page.locator('svg:has(path[d*="m40 15.8"])').first
                    await svg_icon.wait_for(state="visible", timeout=15000)
                    await svg_icon.hover()
                    
                    target_text = page.get_by_text("Tin nhắn cá nhân").first
                    await target_text.wait_for(state="visible", timeout=10000)
                    await target_text.click(force=True)
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.warning(f"Không thể đặt filter 'Tin nhắn cá nhân'. Bỏ qua... Lỗi: {e}")

                item_selector = ".conversation-list-item"
                
                while len(urls_data) < self.limit:
                    conversations = page.locator(item_selector)
                    count = await conversations.count()
                    found_new = False

                    for i in range(count):
                        if len(urls_data) >= self.limit: break

                        conv = conversations.nth(i)
                        try:
                            internal_id = await conv.get_attribute("id", timeout=1000)
                            
                            if not internal_id or internal_id in processed_ids or internal_id.startswith("pzl_g"):
                                continue

                            async with page.expect_request(re.compile(r".*/api/v1/.*/conversations/.*"), timeout=10000) as first_request:
                                await conv.click(force=True)
                                request = await first_request.value
                                
                            request_url = request.url
                            parsed_url = urlparse(request_url)
                            params = parse_qs(parsed_url.query)
                            url_parts = parsed_url.path.split('/')

                            p_idx = url_parts.index('pages') if 'pages' in url_parts else -1
                            c_idx = url_parts.index('conversations') if 'conversations' in url_parts else -1
                            
                            p_id = url_parts[p_idx + 1] if p_idx != -1 else page_id_or_name
                            conv_id = url_parts[c_idx + 1] if c_idx != -1 else "unknown"
                            customer_id = params.get('customer_id', [''])[0]

                            await page.wait_for_selector('#crm-media-record', timeout=10000)
                            await asyncio.sleep(2) 

                            html = await page.inner_html('#crm-media-record')
                            soup = BeautifulSoup(html, 'html.parser')
                            
                            tags = [t.get_text(strip=True) for t in soup.select('.ant-tag.crm-select-option-tag')]
                            
                            phone = None
                            phone_elem = soup.find('div', class_='crm-customer-phone')
                            if phone_elem:
                                phone = phone_elem.get_text(strip=True)

                            data_point = {
                                "id": conv_id,
                                "pancake_id": conv_id,
                                "customer_id": customer_id,
                                "customer_name": "Khách từ CRM", 
                                "phone_number": phone,
                                "message_count": 2, 
                                "tags": tags,
                                "messages": [{"message": soup.get_text()}],
                                "inserted_at": None, 
                                "updated_at": None
                            }

                            urls_data.append(data_point)
                            processed_ids.add(internal_id)
                            logger.info(f"Playwright đã cào ({len(urls_data)}/{self.limit}): {conv_id}")
                            found_new = True

                            await conv.hover(timeout=2000)
                            await page.mouse.wheel(0, 50)
                            
                            break 

                        except Exception as e:
                            continue

                    if not found_new:
                        consecutive_no_new_items += 1
                        await page.mouse.wheel(0, 200)
                    else:
                        consecutive_no_new_items = 0 

                    if consecutive_no_new_items >= MAX_STAGNANT_ATTEMPTS:
                        logger.info("Đã đến cuối danh sách hoặc bị kẹt.")
                        break
                    
                    await asyncio.sleep(1.5)

            except Exception as e:
                logger.error(f"Lỗi Playwright tổng: {e}")
            finally:
                await browser.close()
                
        return urls_data

    def get_conversations(self, page_id: str) -> List[Dict[str, Any]]:
        """Hàm chính: Thử API trước, nếu lỗi hoặc rỗng thì dùng Playwright"""
        logger.info(f"--- BẮT ĐẦU CÀO DỮ LIỆU CHO PAGE: {page_id} ---")
        
        # 1. Thử API
        results = self._fetch_via_api(page_id)
        if results:
            return results
            
        # 2. Nếu API trả về rỗng (hoặc lỗi phân quyền), Fallback Playwright
        if os.name == 'nt':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._scrape_logic_playwright(page_id))
        finally:
            loop.close()
