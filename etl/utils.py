"""Hàm tiện ích dùng chung cho ETL và Backend (không import PancakeClient)."""
import re
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from dateutil.parser import parse

VN_TZ = timezone(timedelta(hours=7))

# Ứng viên SĐT: bắt đầu bằng 0 / 84 / +84, theo sau 9 chữ số (cho phép dấu cách, chấm, gạch ngang xen giữa)
PHONE_CANDIDATE_REGEX = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.\-]?\d){9}(?!\d)")
# Đầu số di động Việt Nam hợp lệ (sau khi chuẩn hoá về dạng 0xxxxxxxxx)
VN_MOBILE_REGEX = re.compile(r"^0(3[2-9]|5[689]|7[06-9]|8[1-9]|9\d)\d{7}$")


def parse_pancake_date(date_val: Any) -> Optional[datetime]:
    """Parse thời gian Pancake, đổi sang giờ Việt Nam (UTC+7) và trả về naive datetime."""
    if not date_val:
        return None
    try:
        if isinstance(date_val, (int, float)):
            ts = date_val / 1000 if date_val > 1e11 else date_val
            return datetime.fromtimestamp(ts, tz=VN_TZ).replace(tzinfo=None)
        val_str = str(date_val).strip()
        if val_str.isdigit():
            ts = float(val_str)
            ts = ts / 1000 if ts > 1e11 else ts
            return datetime.fromtimestamp(ts, tz=VN_TZ).replace(tzinfo=None)
        dt = parse(val_str)
        # Nếu Pancake trả về không có múi giờ, ta ngầm định đó là UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        # Lưu vào DB dưới dạng naive datetime (bỏ tz đi để so sánh cho dễ)
        return dt.astimezone(VN_TZ).replace(tzinfo=None)
    except Exception:
        return None


def extract_phone_number(text: str) -> Optional[str]:
    """Tìm SĐT di động VN trong text, trả về dạng chuẩn 0xxxxxxxxx."""
    if not text:
        return None
    for match in PHONE_CANDIDATE_REGEX.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if digits.startswith("84"):
            digits = "0" + digits[2:]
        if VN_MOBILE_REGEX.match(digits):
            return digits
    return None


def extract_customer_phone(messages: List[Dict[str, Any]]) -> Optional[str]:
    """SĐT đầu tiên (theo thời gian) trong tin nhắn của khách. Bỏ qua tin của Admin để không dính hotline công ty."""
    found = []
    for msg in messages or []:
        if not isinstance(msg, dict) or msg.get("role") == "Admin":
            continue
        phone = extract_phone_number(str(msg.get("message") or ""))
        if phone:
            found.append((msg.get("inserted_at"), phone))
    if not found:
        return None
    # Chỉ parse ngày để sắp xếp khi khách gửi nhiều SĐT khác nhau
    if len({phone for _, phone in found}) > 1:
        found.sort(key=lambda item: parse_pancake_date(item[0]) or datetime.max)
    return found[0][1]


# Bản đồ tên Fanpage chuẩn hóa dùng chung toàn hệ thống
KNOWN_PAGE_NAMES: Dict[str, str] = {
    "629476615535063343": "Eztech Phân Tích Dữ Liệu",
    "pzl_629476615535063343": "Eztech Phân Tích Dữ Liệu",
    "7196601676597871618": "Anh Kế toán làm Data",
    "788602135347404973": "Tuấn Anh Data",
    "pzl_788602135347404973": "Tuấn Anh Data",
}


def is_page_id(val: Any) -> bool:
    """Kiểm tra xem giá trị là ID của page (dạng số hoặc prefix pzl_/tt_/fb_) hay là tên hiển thị."""
    if not val:
        return False
    s = str(val).strip()
    return s.isdigit() or s.startswith("pzl_") or s.startswith("tt_") or s.startswith("fb_")


def resolve_canonical_page_name(page_id_or_name: Any, fallback: Optional[str] = None) -> str:
    """Chuẩn hoá ID / Tên Fanpage về tên hiển thị chuẩn (Ưu tiên KNOWN_PAGE_NAMES)."""
    if not page_id_or_name:
        return fallback or ""
    s = str(page_id_or_name).strip()
    if s in KNOWN_PAGE_NAMES:
        return KNOWN_PAGE_NAMES[s]
    clean_num = re.sub(r"^(pzl_|tt_|fb_)", "", s)
    if clean_num in KNOWN_PAGE_NAMES:
        return KNOWN_PAGE_NAMES[clean_num]
    if not is_page_id(s):
        return s
    return fallback or s

