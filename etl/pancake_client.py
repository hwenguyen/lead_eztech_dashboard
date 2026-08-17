import os
import json
import logging
import asyncio
import re
from typing import List, Dict, Any
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import nest_asyncio

nest_asyncio.apply()
logger = logging.getLogger(__name__)

class PancakeClient:
    def __init__(self):
        self.username = os.getenv("PANCAKE_EMAIL")
        self.password = os.getenv("PANCAKE_PASSWORD")
        self.auth_file = "pancake_auth.json"
        
        # Mặc định cào tối đa 100 khách mỗi lần chạy ngầm để tránh timeout
        self.limit = int(os.getenv("CRAWL_LIMIT", "100")) 

    async def _scrape_logic(self, page_id_or_name: str) -> List[Dict[str, Any]]:
        logger.info(f"Khởi động Playwright cho Kênh/Page: {page_id_or_name}")
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
                
                # Phục hồi phiên đăng nhập nếu có
                if os.path.exists(self.auth_file):
                    context = await browser.new_context(storage_state=self.auth_file)
                    
                page = await context.new_page()

                # 1. Quá trình Login (áp dụng URL Oauth từ file của bạn)
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
                    
                    # Chờ điều hướng xong và lưu cookie
                    await page.wait_for_url("**/dashboard**", timeout=30000)
                    await context.storage_state(path=self.auth_file)
                    logger.info("Đã đăng nhập thành công và lưu session auth.")

                # 2. Điều hướng tới Dashboard của Kênh/Page
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
                    # Lọc "Tin nhắn cá nhân" theo đúng logic file mẫu
                    svg_icon = page.locator('svg:has(path[d*="m40 15.8"])').first
                    await svg_icon.wait_for(state="visible", timeout=15000)
                    await svg_icon.hover()
                    
                    target_text = page.get_by_text("Tin nhắn cá nhân").first
                    await target_text.wait_for(state="visible", timeout=10000)
                    await target_text.click(force=True)
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.warning(f"Không thể đặt filter 'Tin nhắn cá nhân'. Bỏ qua... Lỗi: {e}")

                # 3. Vòng lặp Scraping (Bắt Request và DOM)
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

                            # Bắt request API để lấy chuẩn các tham số ngầm (token, id)
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
                            
                            # Lấy số điện thoại từ giao diện CRM nếu có
                            phone = None
                            phone_elem = soup.find('div', class_='crm-customer-phone')
                            if phone_elem:
                                phone = phone_elem.get_text(strip=True)

                            # Tái cấu trúc data point khớp với Pipeline của ta (giả lập giống API payload gốc)
                            data_point = {
                                "id": conv_id,
                                "pancake_id": conv_id,
                                "customer_id": customer_id,
                                "customer_name": "Khách từ CRM", 
                                "phone_number": phone,
                                "message_count": 2, # Mock tạm, hoặc đếm độ dài đoạn chat
                                "tags": tags,
                                # Ta chèn tạm một chuỗi message trống để Pipeline tự động gọi hàm Regex nếu chưa có sđt
                                "messages": [{"message": soup.get_text()}],
                                "inserted_at": None, # Sẽ được pipeline parse
                                "updated_at": None
                            }

                            urls_data.append(data_point)
                            processed_ids.add(internal_id)
                            logger.info(f"Đã cào ({len(urls_data)}/{self.limit}): {conv_id}")
                            found_new = True

                            await conv.hover(timeout=2000)
                            await page.mouse.wheel(0, 50)
                            
                            break # Chặn lại để refresh vòng lặp DOM

                        except Exception as e:
                            logger.debug(f"Bỏ qua 1 đoạn chat: {e}")
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
        """Hàm đồng bộ bọc hàm bất đồng bộ Playwright"""
        if os.name == 'nt':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._scrape_logic(page_id))
        finally:
            loop.close()
