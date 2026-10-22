"""Script nạp dữ liệu từ file CSV / Excel hoặc link Google Sheet trực tiếp vào Neon Postgres."""
import os
import re
import csv
import io
import urllib.request
from datetime import datetime
from database.db import SessionLocal, engine
from database.models import DealWin
from database.schema import ensure_schema
from etl.utils import normalize_phone, parse_pancake_date, VN_TZ

def clean_revenue_val(val):
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return 0.0
    s_lower = s.lower().replace("vnđ", "").replace("vnd", "").replace("đ", "").strip()
    if "tr" in s_lower or "triệu" in s_lower:
        num_part = re.sub(r"[^\d.,]", "", s_lower).replace(",", ".")
        try:
            return float(num_part) * 1_000_000.0
        except Exception:
            pass
    if "k" in s_lower:
        num_part = re.sub(r"[^\d.,]", "", s_lower).replace(",", ".")
        try:
            return float(num_part) * 1_000.0
        except Exception:
            pass
    clean_digits = re.sub(r"[^\d]", "", s)
    if clean_digits:
        try:
            return float(clean_digits)
        except Exception:
            return 0.0
    return 0.0

def normalize_text(s):
    import unicodedata
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
    
    try:
        for idx, row in enumerate(rows, start=2):
            name = extract_field(row, ["customer_name", "họ và tên", "họ tên", "tên học viên", "tên", "khách hàng", "name"])
            raw_phone = extract_field(row, ["phone_number", "số điện thoại", "sdt", "điện thoại", "phone", "mobile"])
            phone = normalize_phone(raw_phone) if raw_phone else None
            
            revenue_raw = extract_field(row, ["revenue", "số tiền", "học phí", "doanh thu", "tiền", "giá trị", "amount", "price"])
            revenue = clean_revenue_val(revenue_raw)
            
            product = extract_field(row, ["product_name", "khóa học", "sản phẩm", "tên khóa", "gói học", "combo", "product"])
            sales = extract_field(row, ["sales_person", "nhân viên chốt", "sale", "tư vấn", "người phụ trách", "seller"])
            email = extract_field(row, ["email", "mail", "thư điện tử"])
            payment_method = extract_field(row, ["payment_method", "hình thức thanh toán", "phương thức thanh toán", "thanh toán", "chuyển khoản"])
            status = extract_field(row, ["status", "trạng thái"]) or "WIN"
            note = extract_field(row, ["note", "ghi chú", "lưu ý"])
            
            submitted_raw = extract_field(row, ["submitted_at", "dấu thời gian", "thời gian", "ngày", "timestamp", "created_at"])
            submitted_at = parse_pancake_date(submitted_raw) if submitted_raw else datetime.now(VN_TZ).replace(tzinfo=None)
            
            sheet_row_id = f"row_{idx}"
            
            existing = None
            if phone:
                existing = db.query(DealWin).filter(
                    DealWin.phone_number == phone,
                    DealWin.product_name == (str(product).strip() if product else DealWin.product_name)
                ).first()
            if not existing:
                existing = db.query(DealWin).filter_by(sheet_row_id=sheet_row_id).first()
                
            if existing:
                existing.customer_name = str(name).strip() if name else existing.customer_name
                existing.phone_number = phone or existing.phone_number
                existing.email = str(email).strip() if email else existing.email
                existing.product_name = str(product).strip() if product else existing.product_name
                existing.revenue = revenue if revenue > 0 else existing.revenue
                existing.sales_person = str(sales).strip() if sales else existing.sales_person
                existing.payment_method = str(payment_method).strip() if payment_method else existing.payment_method
                existing.status = str(status).strip() if status else existing.status
                existing.note = str(note).strip() if note else existing.note
                existing.raw_data = row
                existing.submitted_at = submitted_at
                updated += 1
            else:
                deal = DealWin(
                    sheet_row_id=sheet_row_id,
                    submitted_at=submitted_at,
                    customer_name=str(name).strip() if name else "Khách hàng",
                    phone_number=phone,
                    email=str(email).strip() if email else None,
                    product_name=str(product).strip() if product else "Khóa học",
                    revenue=revenue,
                    sales_person=str(sales).strip() if sales else "Chưa phân công",
                    payment_method=str(payment_method).strip() if payment_method else None,
                    status=str(status).strip() if status else "WIN",
                    note=str(note).strip() if note else None,
                    raw_data=row
                )
                db.add(deal)
                inserted += 1
                
        db.commit()
        print(f"Đã lưu thành công vào NEON Database! Thêm mới: {inserted}, Cập nhật: {updated}, Tổng xử lý: {len(rows)}")
    finally:
        db.close()

def import_from_csv_file(file_path):
    print(f"Đang đọc file: {file_path}")
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
        print("Không đọc được nội dung dòng nào từ file.")
        return
    import_rows_to_neon(rows)

def import_from_sheet_url(sheet_id="1GNbGSgQvPae2MXC1QdEUhjqr4iBy3h6RGX-VgQ4K6wk", gid="455251895"):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    print(f"Đang tải CSV từ Google Sheet: {url}")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode('utf-8')
            reader = csv.DictReader(io.StringIO(content))
            rows = list(reader)
            print(f"Đã tải {len(rows)} dòng từ Google Sheet.")
            import_rows_to_neon(rows)
    except Exception as e:
        print(f"Lỗi khi tải từ link: {e}")
        print("Gợi ý: Hãy mở quyền 'Bất kỳ ai có liên kết đều có thể xem' trên Sheet, hoặc tải file CSV về máy rồi chạy script.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        import_from_csv_file(sys.argv[1])
    else:
        # Tìm file CSV hoặc Excel có sẵn trong thư mục
        candidates = [f for f in os.listdir('.') if f.endswith(('.csv', '.xlsx', '.xls')) and not f.startswith('.')]
        if candidates:
            print(f"Tìm thấy file trong thư mục: {candidates[0]}")
            import_from_csv_file(candidates[0])
        else:
            print("Đang thử kéo trực tiếp từ link Google Sheet...")
            import_from_sheet_url()
