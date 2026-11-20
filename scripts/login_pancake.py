"""
Script hỗ trợ đăng nhập Pancake một lần để tự động trích xuất và lưu phiên
pancake_state.json vào Neon Database (bảng app_configs).
"""

import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from playwright.sync_api import sync_playwright
from backend.add_friend import save_pancake_state_to_db, PANCAKE_STATE_FILE


def login_and_save():
    print("=" * 60)
    print("🚀 ĐANG MỞ TRÌNH DUYỆT ĐỂ ĐĂNG NHẬP PANCAKE (pages.fm)...")
    print("=" * 60)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://pages.fm/")

        print("\n👉 Hãy đăng nhập tài khoản Pancake của bạn trên cửa sổ vừa mở.")
        print("👉 Sau khi đăng nhập thành công và vào màn hình chat/hội thoại Pancake:")
        input("\n⌨️  Nhấn phím [ENTER] tại cửa sổ dòng lệnh này để lưu phiên: ")

        # Lưu storage_state ra file
        context.storage_state(path=PANCAKE_STATE_FILE)
        browser.close()

    print(f"\n✅ Đã xuất phiên ra file: {PANCAKE_STATE_FILE}")

    # Đọc và lưu trực tiếp vào Database
    with open(PANCAKE_STATE_FILE, "r", encoding="utf-8") as f:
        content = f.read().strip()

    ok, msg, info = save_pancake_state_to_db(content)
    if ok:
        print(f"🎉 THÀNH CÔNG: {msg}")
        print(f"   • Cookies: {info.get('cookies_count')} | Origins: {info.get('origins_count')}")
        print("👉 Bạn chỉ cần F5 lại trang Dashboard trên trình duyệt là xong!\n")
    else:
        print(f"❌ LỖI: {msg}\n")


if __name__ == "__main__":
    login_and_save()
