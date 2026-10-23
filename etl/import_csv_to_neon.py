"""Script nạp dữ liệu từ file Excel / CSV hoặc Google Sheet trực tiếp vào Neon Postgres."""
import os
import re
import csv
import io
import unicodedata
from datetime import datetime
from database.db import SessionLocal, engine
from database.models import DealWin
from database.deal_sync import find_lead_info_by_phone
from database.schema import ensure_schema
from etl.utils import normalize_phone, parse_pancake_date, VN_TZ

def normalize_text(s):
    return unicodedata.normalize("NFC", str(s)).strip().lower()

def extract_field(row, candidates):
    norm_row = {normalize_text(k): v for k, v in row.items()}
    for c in candidates:
        nc = normalize_text(c)
        if nc in norm_row and norm_row[nc] is not None:
            v = norm_row[nc]
            if isinstance(v, str) and not v.strip():
                continue
            return v
    for c in candidates:
        nc = normalize_text(c)
        for k, v in norm_row.items():
            if nc in k and v is not None:
                if isinstance(v, str) and not v.strip():
                    continue
                return v
    return None

def import_rows_to_neon(rows):
    ensure_schema()
    db = SessionLocal()
    inserted = 0
    updated = 0

    print(f"Bắt đầu nạp {len(rows)} dòng vào Neon Postgres ({engine.url.host})...")
    try:
        for idx, row in enumerate(rows, start=2):
            submitted_raw = extract_field(row, ["timestamp", "dấu thời gian", "thời gian", "ngày", "created_at"])
            if isinstance(submitted_raw, datetime):
                submitted_at = submitted_raw
            else:
                submitted_at = parse_pancake_date(submitted_raw) if submitted_raw else datetime.now(VN_TZ).replace(tzinfo=None)

            email = extract_field(row, ["email", "mail", "thư điện tử"])
            full_name = extract_field(row, ["họ và tên", "họ tên", "tên học viên", "tên", "khách hàng", "full_name", "customer_name"])
            raw_phone = extract_field(row, ["sđt", "số điện thoại", "số điện thoạt", "phone_number", "phone", "mobile"])
            phone = normalize_phone(raw_phone) if raw_phone else None

            birth_year = extract_field(row, ["năm sinh", "birth_year"])
            birth_year_str = str(int(float(birth_year))) if birth_year and str(birth_year).replace('.', '', 1).isdigit() else (str(birth_year).strip() if birth_year else None)

            address = extract_field(row, ["địa chỉ (tỉnh / thành phố)", "nơi ở", "địa chỉ", "address", "tỉnh", "thành phố"])
            industry = extract_field(row, ["lĩnh vực hoạt động", "lĩnh vực", "industry"])
            job_title = extract_field(row, ["vị trí/ ngành nghề (ví dụ: kế toán trưởng - thời trang)", "vị trí", "ngành nghề", "job_title"])
            expectation = extract_field(row, ["mục đích/ kì vọng tham gia khoá học", "mục đích", "kì vọng", "expectation"])
            raw_care_by = extract_field(row, ["chăm sóc", "sale", "nhân viên chốt", "nhân viên", "care_by", "sales_person"])
            
            # Map với DimLead và Pancake qua SĐT
            dim_lead_id, is_student, pancake_care, lead_tag = find_lead_info_by_phone(phone, db)
            care_by = pancake_care or (str(raw_care_by).strip() if raw_care_by else "Chưa phân công")
            sheet_row_id = f"row_{idx}"

            existing = None
            if phone:
                existing = db.query(DealWin).filter(DealWin.phone_number == phone).first()
            if not existing:
                existing = db.query(DealWin).filter_by(sheet_row_id=sheet_row_id).first()

            # Chuyển đổi row thành dict JSON-serializable
            serializable_row = {}
            for k, v in row.items():
                if isinstance(v, datetime):
                    serializable_row[k] = v.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    serializable_row[k] = v

            if existing:
                existing.timestamp = submitted_at
                existing.email = str(email).strip() if email else existing.email
                existing.full_name = str(full_name).strip() if full_name else existing.full_name
                existing.phone_number = phone or existing.phone_number
                existing.birth_year = birth_year_str or existing.birth_year
                existing.address = str(address).strip() if address else existing.address
                existing.industry = str(industry).strip() if industry else existing.industry
                existing.job_title = str(job_title).strip() if job_title else existing.job_title
                existing.expectation = str(expectation).strip() if expectation else existing.expectation
                existing.care_by = care_by or existing.care_by
                existing.is_student = is_student
                existing.dim_lead_id = dim_lead_id or existing.dim_lead_id
                existing.lead_tag = lead_tag or existing.lead_tag
                existing.raw_data = serializable_row
                updated += 1
            else:
                deal = DealWin(
                    sheet_row_id=sheet_row_id,
                    timestamp=submitted_at,
                    email=str(email).strip() if email else None,
                    full_name=str(full_name).strip() if full_name else "Học viên",
                    phone_number=phone,
                    birth_year=birth_year_str,
                    address=str(address).strip() if address else None,
                    industry=str(industry).strip() if industry else None,
                    job_title=str(job_title).strip() if job_title else None,
                    expectation=str(expectation).strip() if expectation else None,
                    care_by=care_by,
                    dim_lead_id=dim_lead_id,
                    is_student=is_student,
                    lead_tag=lead_tag,
                    raw_data=serializable_row
                )
                db.add(deal)
                inserted += 1

        db.commit()

        # Đồng bộ tag "Đã là học viên" và nhân viên chăm sóc từ DimLead
        sync_all_deals_with_dim_leads(db)

        # Xoá cache Render API nếu đang chạy online
        try:
            import requests
            secret = os.getenv("ADMIN_SECRET_KEY") or os.getenv("WEBHOOK_SECRET")
            headers = {"X-Admin-Secret": secret} if secret else {}
            requests.post("https://pancake-lead-api.onrender.com/api/admin/clear-cache", headers=headers, timeout=5)
        except Exception:
            pass

        print(f"✅ ĐÃ LƯU THÀNH CÔNG VÀO NEON POSTGRES!")
        print(f"   - Thêm mới: {inserted} học viên")
        print(f"   - Cập nhật: {updated} học viên")
        print(f"   - Tổng xử lý: {len(rows)} học viên")
    finally:
        db.close()

def import_from_excel_file(file_path):
    import openpyxl
    print(f"Đang đọc file Excel: {file_path}")
    wb = openpyxl.load_workbook(file_path, data_only=True)
    sheet_name = 'Form Responses 1' if 'Form Responses 1' in wb.sheetnames else wb.sheetnames[0]
    sheet = wb[sheet_name]
    print(f"Đang đọc sheet: [{sheet_name}], max_row: {sheet.max_row}")

    headers = [cell.value for cell in sheet[1]]
    rows = []
    for r in range(2, sheet.max_row + 1):
        row_dict = {}
        has_val = False
        for c in range(1, len(headers) + 1):
            h = headers[c - 1]
            if h is not None:
                val = sheet.cell(r, c).value
                if val is not None and str(val).strip():
                    has_val = True
                row_dict[str(h).strip()] = val
        if has_val:
            rows.append(row_dict)

    print(f"Đã đọc {len(rows)} dòng học viên từ Excel.")
    import_rows_to_neon(rows)

def import_from_csv_file(file_path):
    print(f"Đang đọc file CSV: {file_path}")
    encodings = ['utf-8-sig', 'utf-8', 'cp1258', 'latin1']
    rows = None
    for enc in encodings:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                if rows:
                    print(f"Đọc thành công với encoding {enc}! Số dòng: {len(rows)}")
                    break
        except Exception:
            continue
    if not rows:
        print("Không đọc được nội dung dòng nào từ file CSV.")
        return
    import_rows_to_neon(rows)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        path = sys.argv[1]
        if path.endswith('.xlsx'):
            import_from_excel_file(path)
        else:
            import_from_csv_file(path)
    else:
        # Tự động tìm file học viên trong Downloads hoặc thư mục hiện tại
        downloads_dir = os.path.expanduser(r'~\Downloads')
        candidates = []
        for d in [downloads_dir, '.']:
            if os.path.exists(d):
                for f in os.listdir(d):
                    if ('THONG TIN' in f.upper() or 'HỌC VIÊN' in f.upper() or 'HOC VIEN' in f.upper()) and f.endswith('.xlsx'):
                        candidates.append(os.path.join(d, f))

        if candidates:
            # Chọn file mới nhất
            candidates.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            chosen = candidates[0]
            print(f"Tự động chọn file học viên mới nhất: {chosen}")
            import_from_excel_file(chosen)
        else:
            print("Không tìm thấy file học viên. Vui lòng truyền đường dẫn file: python -m etl.import_csv_to_neon <path>")
