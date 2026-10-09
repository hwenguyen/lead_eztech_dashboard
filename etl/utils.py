"""Hàm tiện ích dùng chung cho ETL và Backend (không import PancakeClient)."""
import re
from typing import Optional, List, Dict, Any, Tuple, Set
from datetime import datetime, timedelta, timezone
from dateutil.parser import parse

VN_TZ = timezone(timedelta(hours=7))

# Ứng viên SĐT: bắt đầu bằng 0 / 84 / +84, theo sau 9 chữ số (cho phép dấu cách, chấm, gạch ngang xen giữa)
PHONE_CANDIDATE_REGEX = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.\-]?\d){9}(?!\d)")
# Đầu số di động Việt Nam hợp lệ (sau khi chuẩn hoá về dạng 0xxxxxxxxx)
VN_MOBILE_REGEX = re.compile(r"^0(3[2-9]|5[689]|7[06-9]|8[1-9]|9\d)\d{7}$")
# Ngày giờ kiểu "09-10-2026 08:30" cũng đủ 10 chữ số → không được nhận nhầm là SĐT
DATE_LIKE_REGEX = re.compile(r"^\d{1,2}[.\-]\d{1,2}[.\-](19|20)\d{2}")


def parse_pancake_date(date_val: Any) -> Optional[datetime]:
    """Parse thời gian Pancake, đổi sang giờ Việt Nam (UTC+7) và trả về naive datetime."""
    if not date_val:
        return None
    try:
        if isinstance(date_val, datetime):
            if date_val.tzinfo is None:
                return date_val
            return date_val.astimezone(VN_TZ).replace(tzinfo=None)
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
        if DATE_LIKE_REGEX.match(match.group(0)):
            continue
        digits = re.sub(r"\D", "", match.group(0))
        if digits.startswith("84"):
            digits = "0" + digits[2:]
        if VN_MOBILE_REGEX.match(digits):
            return digits
    return None


def normalize_phone(raw: Any) -> Optional[str]:
    """Chuẩn hoá SĐT về chuỗi chỉ gồm chữ số, đầu số quốc tế 84 → 0 (vd +84912345678 → 0912345678)."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("84") and len(digits) in (11, 12):
        rest = digits[2:]
        digits = rest if rest.startswith("0") else "0" + rest
    return digits if 8 <= len(digits) <= 15 else None


def customer_phone_hits(messages: Optional[List[Dict[str, Any]]]) -> List[Tuple[Optional[datetime], str]]:
    """(thời điểm, SĐT) của các tin nhắn do KHÁCH gửi có chứa SĐT, sắp theo thời gian.
    Bỏ qua tin của Admin để không dính hotline công ty."""
    hits = []
    for msg in messages or []:
        if not isinstance(msg, dict) or msg.get("role") == "Admin":
            continue
        phone = extract_phone_number(str(msg.get("message") or ""))
        if phone:
            hits.append((parse_pancake_date(msg.get("inserted_at")), phone))
    hits.sort(key=lambda hit: hit[0] or datetime.max)
    return hits


def resolve_phone(raw_data: Dict[str, Any]) -> Tuple[Optional[str], Optional[datetime]]:
    """Trả về (SĐT đã chuẩn hoá, thời điểm thu được số) của một hội thoại.

    1. Ưu tiên Mốc 1: thời điểm khách gửi số lần đầu trong tin nhắn.
    2. Nếu không có mốc 1 (khách không nhắn số trong chat), lấy Mốc 2: thời điểm gắn tag "Đã add" từ tag_timeline.
    """
    hits = customer_phone_hits(raw_data.get("messages"))
    phone = normalize_phone(raw_data.get("phone_number"))
    phone_at = None
    if phone:
        dates = [dt for dt, hit_phone in hits if hit_phone == phone and dt]
        phone_at = dates[0] if dates else None
    elif hits:
        phone, phone_at = hits[0][1], hits[0][0]

    # Nếu không có mốc 1 (khách không chat số), lấy mốc 2 nếu có tag "Đã add"
    if not phone_at and raw_data.get("tag_timeline"):
        import unicodedata
        add_tag_times = []
        for t_item in raw_data.get("tag_timeline") or []:
            if isinstance(t_item, dict):
                t_name = unicodedata.normalize("NFC", str(t_item.get("tag") or "")).strip().lower()
                if ("đã add" in t_name or "da add" in t_name) and t_item.get("action") == "add":
                    dt = parse_pancake_date(t_item.get("tagged_at"))
                    if dt:
                        add_tag_times.append(dt)
        if add_tag_times:
            phone_at = min(add_tag_times)

    return phone, phone_at


# Bản đồ tên Fanpage chuẩn hóa dùng chung toàn hệ thống
KNOWN_PAGE_NAMES: Dict[str, str] = {
    # 1. Eztech Phân Tích Dữ Liệu
    "629476615535063343": "Eztech Phân Tích Dữ Liệu",
    "pzl_629476615535063343": "Eztech Phân Tích Dữ Liệu",
    # 2. Anh Kế toán làm Data
    "7196601676597871618": "Anh Kế toán làm Data",
    "tt_7196601676597871618": "Anh Kế toán làm Data",
    # 3. Anh Gà Kế Toán
    "7456003523327919120": "Anh Gà Kế Toán",
    "tt_7456003523327919120": "Anh Gà Kế Toán",
    # 4. Hiền Minh Eztech
    "131986891507252646": "Hiền Minh Eztech",
    "pzl_131986891507252646": "Hiền Minh Eztech",
    # 5. Tuấn Anh Data
    "788602135347404973": "Tuấn Anh Data",
    "pzl_788602135347404973": "Tuấn Anh Data",
}

# Page Zalo cá nhân (ID prefix pzl_) là kênh chăm sóc sau khi đã có SĐT → không cộng vào "Tất cả Page".
# Page Zalo mới PHẢI được khai báo trong KNOWN_PAGE_NAMES với prefix pzl_ để được nhận diện.
ZALO_PAGE_NAMES: Set[str] = {name for pid, name in KNOWN_PAGE_NAMES.items() if pid.startswith("pzl_")}


def zalo_page_keys() -> Set[str]:
    """Mọi giá trị page_id có thể đang lưu trong DB của các page Zalo (tên hiển thị + ID số + ID pzl_)."""
    return ZALO_PAGE_NAMES | {pid for pid, name in KNOWN_PAGE_NAMES.items() if name in ZALO_PAGE_NAMES}


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

