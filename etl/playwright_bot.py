import os
import json
import logging
import asyncio
import re
from datetime import datetime
from playwright.async_api import async_playwright
import nest_asyncio

from database.db import SessionLocal
from etl.pipeline import upsert_lead_data

nest_asyncio.apply()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PlaywrightBot:
    def __init__(self):
        self.username = os.getenv("PANCAKE_EMAIL")
        self.password = os.getenv("PANCAKE_PASSWORD")
        self.auth_file = "pancake_auth.json"
        self.limit = int(os.getenv("CRAWL_LIMIT", "100"))

    async def scrape_page(self, page_id_or_name: str, db):
        logger.info(f"Khởi động Playwright Bot cho Page: {page_id_or_name}")
        processed_ids = set()
        
        async with async_playwright() as p:
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
                    await browser.close()
                    return
                    
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
                logger.error(f"Không tìm thấy Dashboard cho {page_id_or_name}")
                await browser.close()
                return

            logger.info("Đã vào Dashboard. Đợi UI load...")
            await page.wait_for_load_state('domcontentloaded')
            
            try:
                # Đổi sang tab Tin nhắn cá nhân
                svg_icon = page.locator('svg:has(path[d*="m40 15.8"])').first
                await svg_icon.wait_for(state="visible", timeout=15000)
                await svg_icon.hover()
                
                target_text = page.get_by_text("Tin nhắn cá nhân").first
                await target_text.wait_for(state="visible", timeout=10000)
                await target_text.click(force=True)
                await asyncio.sleep(2)
            except Exception as e:
                logger.warning(f"Không thể đặt filter 'Tin nhắn cá nhân'. Lỗi: {e}")

            item_selector = ".conversation-list-item"
            crawled_count = 0
            stagnant = 0
            
            while crawled_count < self.limit:
                conversations = page.locator(item_selector)
                count = await conversations.count()
                found_new = False

                for i in range(count):
                    if crawled_count >= self.limit: break

                    conv = conversations.nth(i)
                    try:
                        internal_id = await conv.get_attribute("id", timeout=1000)
                        if not internal_id or internal_id in processed_ids or internal_id.startswith("pzl_g"):
                            continue

                        # Chặn bắt API messages để lấy JSON xịn (giống y hệt API token)
                        async with page.expect_response(re.compile(r".*/api/v1/.*/conversations/.*/messages.*"), timeout=10000) as response_info:
                            await conv.click(force=True)
                            response = await response_info.value
                            msg_data = await response.json()
                            
                        # Chặn bắt thông tin conversation từ API (tags, users...)
                        async with page.expect_response(re.compile(r".*/api/v1/.*/conversations/[A-Za-z0-9_]+$"), timeout=10000) as conv_res_info:
                            # Trigger lại bằng cách click nhẹ
                            await conv.click(force=True)
                            c_res = await conv_res_info.value
                            c_data = await c_res.json()
                            
                        conv_info = c_data.get('conversation', {})
                        messages_list = msg_data.get('messages', [])
                        
                        customers = conv_info.get('customers', [])
                        
                        # Chuẩn bị payload y như API
                        raw_payload = {
                            "id": conv_info.get("id", internal_id),
                            "pancake_id": conv_info.get("id", internal_id),
                            "type": conv_info.get("type", "INBOX"),
                            "customer_id": customers[0].get('id') if customers else 'unknown',
                            "customer_name": customers[0].get('name') if customers else 'Khách hàng',
                            "phone_number": None,
                            "message_count": len(messages_list),
                            "tags": [t['text'] for t in conv_info.get('tags', []) if 'text' in t],
                            "assigned_users": ", ".join([u['name'] for u in conv_info.get('current_assign_users', []) if 'name' in u]),
                            "inserted_at": conv_info.get("inserted_at"),
                            "updated_at": conv_info.get("updated_at"),
                            "messages": []
                        }
                        
                        for m in messages_list:
                            if m.get("message"):
                                m_from = m.get('from', {})
                                role = "Admin" if m_from and ('admin' in str(m_from).lower() or m_from.get('admin_name')) else "Khách hàng"
                                raw_payload["messages"].append({
                                    "message": m.get("message"),
                                    "inserted_at": m.get("inserted_at"),
                                    "role": role,
                                    "sender_name": m_from.get('name') or m_from.get('username') or m_from.get('admin_name') or "Unknown"
                                })

                        # Bắn thẳng vào DB
                        upsert_lead_data(db, raw_payload, page_id_or_name)
                        
                        processed_ids.add(internal_id)
                        crawled_count += 1
                        found_new = True
                        logger.info(f"Bot đã cào ({crawled_count}/{self.limit}) và lưu DB: {conv_info.get('id', internal_id)}")

                        await conv.hover(timeout=2000)
                        await page.mouse.wheel(0, 50)
                        
                        break 

                    except Exception as e:
                        continue

                if not found_new:
                    stagnant += 1
                    await page.mouse.wheel(0, 200)
                else:
                    stagnant = 0 

                if stagnant >= 50:
                    logger.info("Bot bị kẹt hoặc đã cào hết danh sách.")
                    break
                
                await asyncio.sleep(1.5)

            await browser.close()

def run_playwright_bot():
    logger.info("Bắt đầu chạy Playwright Bot (Song song với ETL)")
    page_ids = os.getenv("PLAYWRIGHT_PAGE_IDS", "").split(",")
    page_ids = [p.strip() for p in page_ids if p.strip()]
    
    if not page_ids:
        logger.warning("Không có PLAYWRIGHT_PAGE_IDS trong biến môi trường. Tạm dừng.")
        return

    bot = PlaywrightBot()
    db = SessionLocal()
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        for pid in page_ids:
            loop.run_until_complete(bot.scrape_page(pid, db))
    finally:
        db.close()
        
if __name__ == "__main__":
    run_playwright_bot()
