"""Hàm tiện ích dùng chung cho ETL và Backend (không import playwright/PancakeClient)."""
import re
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from dateutil.parser import parse

VN_TZ = timezone(timedelta(hours=7))

# Ứng viên SĐT: bắt đầu bằng 0 / 84 / +84, theo sau 9 chữ số (cho phép dấu cách, chấm, gạch ngang xen giữa)
PHONE_CANDIDATE_REGEX = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.\-]?\d){9}(?!\d)")
# Đầu số di động Việt Nam hợp lệ (sau khi chuẩn hoá về dạng 0xxxxxxxxx)
VN_MOBILE_REGEX = re.compile(r"^0(3[2-9]|5[689]|7[06-9]|8[1-9]|9\d)\d{7}$")


def parse_pancake_date(date_str: str) -> Optional[datetime]:
    """Parse thời gian Pancake, đổi sang giờ Việt Nam (UTC+7) và trả về naive datetime."""
    if not date_str:
        return None
    try:
        dt = parse(date_str)
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
