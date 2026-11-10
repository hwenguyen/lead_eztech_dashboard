"""
==============================================================================
CÔNG CỤ ĐỒNG BỘ & LƯU BỀN VỮNG PANCAKE_STATE.JSON VÀO BẢNG APP_CONFIGS (PYTHON)
==============================================================================
Cách dùng:
  1. Kiểm tra trạng thái: python scripts/sync_pancake_state.py --status
  2. Lưu file vào DB:   python scripts/sync_pancake_state.py <duong_dan_file.json>
  3. Xuất file từ DB:   python scripts/sync_pancake_state.py --export [output_file.json]
==============================================================================
"""

import sys
import os
import json

# Thêm root vào sys.path để import được database module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.db import SessionLocal
from database.models import AppConfig
from backend.add_friend import (
    load_pancake_state_from_db,
    save_pancake_state_to_db,
    delete_pancake_state_from_db,
    PANCAKE_STATE_FILE,
)


def print_status():
    print("🔍 Đang kiểm tra cấu hình pancake_state.json trong bảng app_configs...")
    raw, updated_at, found_key = load_pancake_state_from_db()
    if not raw:
        print("⚠️  Chưa có bản ghi pancake_state.json nào trong bảng app_configs.")
        print("👉 Bạn có thể lưu bằng lệnh: python scripts/sync_pancake_state.py <duong_dan_file.json>")
        return False
    try:
        parsed = json.loads(raw)
        cookies = parsed.get("cookies", [])
        origins = parsed.get("origins", [])
        print(f"✅ Đã tìm thấy cấu hình phiên trong app_configs:")
        print(f"   • Khóa lưu trữ (Key): {found_key}")
        print(f"   • Số lượng cookies : {len(cookies)}")
        print(f"   • Số lượng origins : {len(origins)}")
        print(f"   • Cập nhật lần cuối : {updated_at}")
        return True
    except Exception as e:
        print(f"⚠️  Dữ liệu không phải JSON hợp lệ: {e}")
        return False


def save_file(file_path: str):
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        print(f"❌ File không tồn tại: {abs_path}")
        sys.exit(1)

    with open(abs_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    ok, msg, info = save_pancake_state_to_db(content)
    if ok:
        print(f"🎉 THÀNH CÔNG: {msg}")
        print(f"   • Đã lưu vào khóa: {info.get('storage_key')}")
        print(f"   • Cookies: {info.get('cookies_count')} | Origins: {info.get('origins_count')}")
    else:
        print(f"❌ LỖI: {msg}")
        sys.exit(1)


def export_file(output_path: str = None):
    target = os.path.abspath(output_path or PANCAKE_STATE_FILE)
    raw, _, found_key = load_pancake_state_from_db()
    if not raw:
        print("❌ Chưa có bản ghi pancake_state.json nào trong bảng app_configs để xuất.")
        sys.exit(1)

    with open(target, "w", encoding="utf-8") as f:
        f.write(raw)
    print(f"✅ Đã xuất cấu hình (từ key '{found_key}') ra file: {target}")


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "--status"

    if cmd in ("--status", "-s"):
        print_status()
    elif cmd in ("--export", "-e"):
        export_file(args[1] if len(args) > 1 else None)
    elif cmd in ("--delete", "-d"):
        ok, msg = delete_pancake_state_from_db()
        print(msg)
    else:
        save_file(cmd)
