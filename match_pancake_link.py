#!/usr/bin/env python3
"""
Tool nối Link Pancake từ SĐT trong file Excel / CSV với Database Postgres.
Sử dụng:
    python match_pancake_link.py [duong_dan_file_excel] [--sheet SHEET] [--phone-col TEN_COT]

Ví dụ:
    python match_pancake_link.py danh_sach_sdt.xlsx
"""

import os
import sys
import re
import argparse
from typing import Optional, List, Dict, Any
from datetime import datetime

# Đảm bảo in tiếng Việt / emoji an toàn trên Windows cmd / powershell
try:
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    if sys.stderr.encoding.lower() != 'utf-8':
        sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# Đảm bảo import được các module trong project
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from sqlalchemy import or_
from database.db import SessionLocal
from database.models import DimLead, FactLeadActivity
from etl.utils import build_pancake_url, resolve_canonical_page_name


def clean_phone(val: Any) -> Optional[str]:
    """Chuẩn hóa SĐT Việt Nam về định dạng 10 số (bắt đầu bằng 0)."""
    if val is None or pd.isna(val):
        return None
    
    # Ép kiểu string và bỏ các ký tự phân cách
    raw = str(val).strip()
    # Nếu là float dạng 912345678.0
    if raw.endswith('.0'):
        raw = raw[:-2]
    
    digits = re.sub(r'\D', '', raw)
    if not digits:
        return None
    
    # Xử lý đầu số Việt Nam
    if digits.startswith('84') and len(digits) >= 11:
        digits = '0' + digits[2:]
    elif not digits.startswith('0') and len(digits) == 9:
        digits = '0' + digits
    
    # SĐT hợp lệ ở VN hiện tại thường là 10 số
    if len(digits) == 10 and digits.startswith('0'):
        return digits
    elif 9 <= len(digits) <= 11:
        return digits
        
    return None


def detect_phone_column(df: pd.DataFrame) -> Optional[str]:
    """Tự động phát hiện cột chứa Số Điện Thoại trong DataFrame."""
    candidates = ['sdt', 'phone', 'dien_thoai', 'so_dien_thoai', 'mobile', 'tel', 'phone_number', 'contact']
    
    # 1. Tìm theo tên cột
    for col in df.columns:
        clean_col = re.sub(r'[^a-z0-9_]', '', str(col).lower().replace(' ', '_'))
        for cand in candidates:
            if cand in clean_col:
                return col
                
    # 2. Quét qua dữ liệu của từng cột để tìm cột có định dạng giống SĐT nhất
    best_col = None
    max_valid = 0
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(50)
        valid_cnt = sum(1 for v in sample if clean_phone(v) is not None)
        if valid_cnt > max_valid and valid_cnt >= 3:
            max_valid = valid_cnt
            best_col = col
            
    return best_col


def process_file(file_path: str, sheet_name: Optional[str] = None, phone_col: Optional[str] = None):
    if not os.path.exists(file_path):
        print(f"❌ Không tìm thấy file: {file_path}")
        return

    print(f"\n📂 Đang đọc file: {file_path}")
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext in ['.xlsx', '.xls']:
        df = pd.read_excel(file_path, sheet_name=sheet_name or 0)
    elif ext == '.csv':
        # Thử các encoding phổ biến
        try:
            df = pd.read_csv(file_path, encoding='utf-8')
        except UnicodeDecodeError:
            df = pd.read_csv(file_path, encoding='cp1258')
    else:
        print(f"❌ Định dạng file '{ext}' không được hỗ trợ (chỉ nhận .xlsx, .xls, .csv).")
        return

    print(f"   Tổng số dòng dữ liệu: {len(df):,}")

    # Xác định cột SĐT
    target_col = phone_col or detect_phone_column(df)
    if not target_col or target_col not in df.columns:
        print(f"❌ Không tìm thấy cột SĐT tự động. Các cột hiện có: {list(df.columns)}")
        print("👉 Vui lòng chạy lại với tham số: --phone-col \"TÊN_CỘT\"")
        return

    print(f"   Đã chọn cột SĐT: '{target_col}'")

    # Chuẩn hóa danh sách SĐT cần tra cứu
    df['_clean_sdt'] = df[target_col].apply(clean_phone)
    unique_phones = [p for p in df['_clean_sdt'].dropna().unique() if p]
    print(f"   Số lượng SĐT hợp lệ cần tra cứu: {len(unique_phones):,} số.")

    if not unique_phones:
        print("⚠️ Không có SĐT hợp lệ nào để tra cứu.")
        df.drop(columns=['_clean_sdt'], inplace=True, errors='ignore')
        return

    # Truy vấn Database
    print("\n🔍 Đang tra cứu thông tin và link Pancake từ DB Postgres...")
    db = SessionLocal()
    matched_data: Dict[str, List[Dict[str, Any]]] = {}

    try:
        # Chia batch nếu danh sách quá lớn
        batch_size = 1000
        for i in range(0, len(unique_phones), batch_size):
            batch = unique_phones[i:i + batch_size]
            rows = (
                db.query(DimLead, FactLeadActivity)
                .join(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)
                .filter(DimLead.phone_number.in_(batch))
                .order_by(DimLead.first_created_at.desc())
                .all()
            )
            for lead, act in rows:
                p = lead.phone_number
                if not p:
                    continue
                url = build_pancake_url(act.conversation_id, lead.customer_id, lead.page_id)
                page_name = resolve_canonical_page_name(lead.page_id)
                date_str = lead.first_created_at.strftime('%d/%m/%Y %H:%M') if lead.first_created_at else ''
                
                item = {
                    'link_pancake': url,
                    'ten_khach': lead.name or '',
                    'page': page_name,
                    'ngay_tao': date_str,
                    'tag': act.status_tag or '',
                    'conversation_id': act.conversation_id,
                }
                if p not in matched_data:
                    matched_data[p] = []
                matched_data[p].append(item)
    finally:
        db.close()

    matched_count = len(matched_data)
    match_rate = (matched_count / len(unique_phones) * 100) if unique_phones else 0
    print(f"✅ Tra cứu hoàn tất: Khớp {matched_count:,} / {len(unique_phones):,} SĐT ({match_rate:.1f}%).")

    # Điền kết quả vào DataFrame
    def get_info(sdt, key, fallback=''):
        if not sdt or sdt not in matched_data:
            return fallback
        items = matched_data[sdt]
        return items[0].get(key, fallback)

    def get_all_links(sdt):
        if not sdt or sdt not in matched_data:
            return ''
        links = [it['link_pancake'] for it in matched_data[sdt] if it.get('link_pancake')]
        # Loại trùng lặp link
        unique_links = list(dict.fromkeys(links))
        return "\n".join(unique_links)

    def get_conv_count(sdt):
        if not sdt or sdt not in matched_data:
            return 0
        return len(matched_data[sdt])

    df['Link_Pancake'] = df['_clean_sdt'].apply(lambda s: get_info(s, 'link_pancake'))
    df['Ten_Pancake'] = df['_clean_sdt'].apply(lambda s: get_info(s, 'ten_khach'))
    df['Page_Pancake'] = df['_clean_sdt'].apply(lambda s: get_info(s, 'page'))
    df['Ngay_Pancake'] = df['_clean_sdt'].apply(lambda s: get_info(s, 'ngay_tao'))
    df['Trang_Thai_Tag'] = df['_clean_sdt'].apply(lambda s: get_info(s, 'tag'))
    df['So_Hoi_Thoai_DB'] = df['_clean_sdt'].apply(get_conv_count)
    df['Tat_Ca_Link_Pancake'] = df['_clean_sdt'].apply(get_all_links)

    # Xóa cột phụ
    df.drop(columns=['_clean_sdt'], inplace=True, errors='ignore')

    # Xuất file kết quả
    base_name, _ = os.path.splitext(file_path)
    output_path = f"{base_name}_kem_link_pancake.xlsx"
    df.to_excel(output_path, index=False, engine='openpyxl')
    print(f"\n🎉 Đã xuất kết quả thành công ra file:")
    print(f"👉 {os.path.abspath(output_path)}\n")


def main():
    parser = argparse.ArgumentParser(description="Nối link Pancake từ danh sách SĐT trong file Excel/CSV")
    parser.add_argument("file", nargs="?", default="", help="Đường dẫn tới file Excel (.xlsx) hoặc CSV chứa SĐT")
    parser.add_argument("--sheet", type=str, default=None, help="Tên sheet trong file Excel (mặc định lấy sheet đầu tiên)")
    parser.add_argument("--phone-col", type=str, default=None, help="Tên cột SĐT nếu script không tự nhận diện được")
    args = parser.parse_args()

    file_target = args.file.strip()
    if not file_target:
        # Tự tìm file excel hoặc csv trong thư mục hiện tại
        candidates = [f for f in os.listdir('.') if f.endswith(('.xlsx', '.csv')) and not f.endswith('_kem_link_pancake.xlsx')]
        if candidates:
            print("Tìm thấy các file trong thư mục:")
            for idx, c in enumerate(candidates, 1):
                print(f"  [{idx}] {c}")
            choice = input("\nNhập số thứ tự file muốn xử lý (hoặc kéo thả đường dẫn file vào đây): ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                file_target = candidates[int(choice) - 1]
            elif choice:
                file_target = choice.strip('"').strip("'")
            else:
                print("Chưa chọn file.")
                return
        else:
            file_target = input("Nhập hoặc kéo thả đường dẫn file Excel vào đây: ").strip().strip('"').strip("'")

    process_file(file_target, sheet_name=args.sheet, phone_col=args.phone_col)


if __name__ == "__main__":
    main()
