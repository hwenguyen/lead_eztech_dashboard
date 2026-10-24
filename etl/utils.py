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
    # 2. Anh Kế toán làm Data (TikTok)
    "7196601676597871618": "Anh Kế toán làm Data (TikTok)",
    "tt_7196601676597871618": "Anh Kế toán làm Data (TikTok)",
    "Anh Kế toán làm Data": "Anh Kế toán làm Data (TikTok)",
    "Anh Kế toán làm Data (TikTok)": "Anh Kế toán làm Data (TikTok)",
    # 3. Anh Kế toán làm Data (Facebook)
    "514400205095512": "Anh Kế toán làm Data (Facebook)",
    "fb_514400205095512": "Anh Kế toán làm Data (Facebook)",
    "Anh Kế toán làm Data (Facebook)": "Anh Kế toán làm Data (Facebook)",
    # 4. Hành trang cho kế toán (Chuẩn hoá về 1 page Hành trang cho kế toán)
    "7456003523327919120": "Hành trang cho kế toán",
    "tt_7456003523327919120": "Hành trang cho kế toán",
    "Anh Gà Kế Toán": "Hành trang cho kế toán",
    # 5. Hiền Minh Eztech
    "131986891507252646": "Hiền Minh Eztech",
    "pzl_131986891507252646": "Hiền Minh Eztech",
    # 6. Tuấn Anh Data
    "788602135347404973": "Tuấn Anh Data",
    "pzl_788602135347404973": "Tuấn Anh Data",
    # 7. Chị Kế Toán GenZ
    "7661860189083943944": "Chị Kế Toán GenZ",
    "tt_7661860189083943944": "Chị Kế Toán GenZ",
    # 8. Học Kế toán cùng EzTech (TikTok)
    "7657393326631863314": "Học Kế toán cùng EzTech",
    "tt_7657393326631863314": "Học Kế toán cùng EzTech",
    # 9. Anh kế toán Daily (TikTok)
    "7602128557942293512": "Anh kế toán Daily",
    "tt_7602128557942293512": "Anh kế toán Daily",
}

# Bản đồ ánh xạ từ Tên/ID Page sang Page Slug hiển thị trên Pancake URL (https://pancake.vn/[slug]?c_id=[conversation_id])
PAGE_NAME_TO_PANCAKE_ID: Dict[str, str] = {
    # 1. Eztech Phân Tích Dữ Liệu: Zalo cá nhân SĐT +84377024368
    "Eztech Phân Tích Dữ Liệu": "pzl_84377024368",
    "629476615535063343": "pzl_84377024368",
    "pzl_629476615535063343": "pzl_84377024368",

    # 2. Anh Kế toán làm Data (TikTok): Kênh TikTok @tuananhdata
    "Anh Kế toán làm Data (TikTok)": "tt_tuananhdata",
    "Anh Kế toán làm Data": "tt_tuananhdata",
    "7196601676597871618": "tt_tuananhdata",
    "tt_7196601676597871618": "tt_tuananhdata",

    # 3. Anh Kế toán làm Data (Facebook): Kênh Facebook Fanpage
    "Anh Kế toán làm Data (Facebook)": "514400205095512",
    "514400205095512": "514400205095512",
    "fb_514400205095512": "514400205095512",

    # 4. Hiền Minh Eztech: Zalo cá nhân SĐT +84898276368
    "Hiền Minh Eztech": "pzl_84898276368",
    "131986891507252646": "pzl_84898276368",
    "pzl_131986891507252646": "pzl_84898276368",

    # 5. Hành trang cho kế toán / Anh Gà Kế Toán: Kênh TikTok @anhgadata
    "Hành trang cho kế toán": "tt_anhgadata",
    "Anh Gà Kế Toán": "tt_anhgadata",
    "7456003523327919120": "tt_anhgadata",
    "tt_7456003523327919120": "tt_anhgadata",

    # 6. Tuấn Anh Data: Zalo cá nhân SĐT +84389528224
    "Tuấn Anh Data": "pzl_84389528224",
    "788602135347404973": "pzl_84389528224",
    "pzl_788602135347404973": "pzl_84389528224",

    # 7. Chị Kế Toán GenZ: Kênh TikTok @chiketoangenz
    "Chị Kế Toán GenZ": "tt_chiketoangenz",
    "7661860189083943944": "tt_chiketoangenz",
    "tt_7661860189083943944": "tt_chiketoangenz",
}


def build_pancake_url(
    conversation_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    page_name_or_id: Optional[str] = None,
) -> Optional[str]:
    """Sinh link trực tiếp mở hội thoại Pancake: https://pancake.vn/[id page]?c_id=[conversation id]"""
    # Trên Pancake Web UI, tham số c_id nhận mã hội thoại (conversation_id) để tự cuộn vào tin nhắn
    target_cid = conversation_id or customer_id
    if not target_cid:
        return None

    pid = None

    # 1. Tra cứu slug theo Tên hoặc ID page
    if page_name_or_id:
        clean_p = str(page_name_or_id).strip()
        pid = PAGE_NAME_TO_PANCAKE_ID.get(clean_p)
        if not pid and clean_p in KNOWN_PAGE_NAMES:
            cname = KNOWN_PAGE_NAMES[clean_p]
            pid = PAGE_NAME_TO_PANCAKE_ID.get(cname)

    # 2. Nếu chưa có slug từ tên page, tra cứu qua ID bóc tách từ conversation_id
    if not pid and conversation_id:
        if conversation_id.startswith("pzl_"):
            parts = conversation_id.split("_")
            if len(parts) >= 4:
                pid = PAGE_NAME_TO_PANCAKE_ID.get(parts[2]) or PAGE_NAME_TO_PANCAKE_ID.get(f"pzl_{parts[2]}") or f"pzl_{parts[2]}"
        elif conversation_id.startswith("tt_"):
            parts = conversation_id.split(":")
            for p in parts[2:]:
                cand = PAGE_NAME_TO_PANCAKE_ID.get(p) or PAGE_NAME_TO_PANCAKE_ID.get(f"tt_{p}")
                if cand:
                    pid = cand
                    break
            if not pid:
                for p in parts[2:]:
                    if f"tt_{p}" in KNOWN_PAGE_NAMES or p in KNOWN_PAGE_NAMES:
                        p_name = KNOWN_PAGE_NAMES.get(f"tt_{p}") or KNOWN_PAGE_NAMES.get(p)
                        pid = PAGE_NAME_TO_PANCAKE_ID.get(p_name) or f"tt_{p}"
                        break
            if not pid and len(parts) >= 3:
                pid = PAGE_NAME_TO_PANCAKE_ID.get(parts[2]) or PAGE_NAME_TO_PANCAKE_ID.get(f"tt_{parts[2]}") or f"tt_{parts[2]}"
        elif conversation_id.startswith("fb_"):
            parts = conversation_id.split("_")
            if len(parts) >= 2:
                pid = PAGE_NAME_TO_PANCAKE_ID.get(parts[1]) or PAGE_NAME_TO_PANCAKE_ID.get(parts[-1]) or parts[1]
        elif "_" in conversation_id and not conversation_id.startswith(("pzl_", "tt_")):
            parts = conversation_id.split("_")
            if len(parts) >= 2 and parts[0].isdigit():
                pid = PAGE_NAME_TO_PANCAKE_ID.get(parts[0]) or parts[0]

    # 3. Fallback lấy chính page_name_or_id
    if not pid and page_name_or_id:
        pid = str(page_name_or_id).strip()

    if not pid:
        return None

    return f"https://pancake.vn/{pid}?c_id={target_cid}"


def build_post_url(post_id: Optional[str], page_id: Optional[str] = None, raw_url: Optional[str] = None) -> Optional[str]:
    """Tạo link chuẩn trực tiếp tới video TikTok hoặc bài viết Facebook."""
    if raw_url and str(raw_url).startswith("http"):
        return str(raw_url).strip()

    if not post_id:
        return None

    pid_str = str(post_id).strip()
    page_str = str(page_id or "").strip()
    is_tiktok = page_str.startswith("tt_") or "tiktok" in resolve_canonical_page_name(page_str).lower() or pid_str.startswith("tt_")

    if is_tiktok:
        clean_vid = pid_str.split(":")[-1] if ":" in pid_str else pid_str
        slug = PAGE_NAME_TO_PANCAKE_ID.get(page_str) or PAGE_NAME_TO_PANCAKE_ID.get(resolve_canonical_page_name(page_str)) or ""
        handle = slug.replace("tt_", "") if slug.startswith("tt_") else ""
        if handle:
            return f"https://www.tiktok.com/@{handle}/video/{clean_vid}"
        return f"https://www.tiktok.com/video/{clean_vid}"
    else:
        # Facebook Fanpage
        clean_fbid = pid_str.split("_")[-1] if "_" in pid_str else pid_str
        clean_page = re.sub(r"^(fb_)", "", page_str)
        if clean_page and clean_page.isdigit():
            return f"https://facebook.com/{clean_page}/posts/{clean_fbid}"
        return f"https://facebook.com/{clean_fbid}"


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


def clean_html(text: Any) -> str:
    """Loại bỏ các thẻ HTML như <div>, <span>, <CopyText>... giữ lại text thuần."""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", str(text))
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def is_source_page(page_id_or_name: Any) -> bool:
    """Kiểm tra xem page có phải kênh nguồn (Facebook, TikTok...) hay không (không phải kênh Zalo cá nhân)."""
    if not page_id_or_name:
        return False
    s = str(page_id_or_name).strip()
    return not (s.startswith("pzl_") or s in zalo_page_keys())


# Bản đồ ánh xạ ngược từ Tên hiển thị / ID sang đúng Page ID chuẩn gọi Pancake API
PAGE_NAME_TO_API_ID: Dict[str, str] = {
    # 1. Eztech Phân Tích Dữ Liệu (Zalo cá nhân)
    "Eztech Phân Tích Dữ Liệu": "pzl_629476615535063343",
    "629476615535063343": "pzl_629476615535063343",
    "pzl_629476615535063343": "pzl_629476615535063343",
    "pzl_84377024368": "pzl_629476615535063343",

    # 2. Anh Kế toán làm Data (TikTok)
    "Anh Kế toán làm Data (TikTok)": "tt_7196601676597871618",
    "Anh Kế toán làm Data": "tt_7196601676597871618",
    "7196601676597871618": "tt_7196601676597871618",
    "tt_7196601676597871618": "tt_7196601676597871618",
    "tt_tuananhdata": "tt_7196601676597871618",

    # 3. Anh Kế toán làm Data (Facebook)
    "Anh Kế toán làm Data (Facebook)": "514400205095512",
    "514400205095512": "514400205095512",
    "fb_514400205095512": "514400205095512",

    # 4. Hành trang cho kế toán (TikTok)
    "Hành trang cho kế toán": "tt_7456003523327919120",
    "Anh Gà Kế Toán": "tt_7456003523327919120",
    "7456003523327919120": "tt_7456003523327919120",
    "tt_7456003523327919120": "tt_7456003523327919120",
    "tt_anhgadata": "tt_7456003523327919120",

    # 5. Hiền Minh Eztech (Zalo cá nhân)
    "Hiền Minh Eztech": "pzl_131986891507252646",
    "131986891507252646": "pzl_131986891507252646",
    "pzl_131986891507252646": "pzl_131986891507252646",
    "pzl_84898276368": "pzl_131986891507252646",

    # 6. Tuấn Anh Data (Zalo cá nhân)
    "Tuấn Anh Data": "pzl_788602135347404973",
    "788602135347404973": "pzl_788602135347404973",
    "pzl_788602135347404973": "pzl_788602135347404973",
    "pzl_84389528224": "pzl_788602135347404973",

    # 7. Chị Kế Toán GenZ (TikTok)
    "Chị Kế Toán GenZ": "tt_7661860189083943944",
    "7661860189083943944": "tt_7661860189083943944",
    "tt_7661860189083943944": "tt_7661860189083943944",
    "tt_chiketoangenz": "tt_7661860189083943944",

    # 8. Học Kế toán cùng EzTech (TikTok)
    "Học Kế toán cùng EzTech": "tt_7657393326631863314",
    "7657393326631863314": "tt_7657393326631863314",
    "tt_7657393326631863314": "tt_7657393326631863314",

    # 9. Anh kế toán Daily (TikTok)
    "Anh kế toán Daily": "tt_7602128557942293512",
    "7602128557942293512": "tt_7602128557942293512",
    "tt_7602128557942293512": "tt_7602128557942293512",
}


def resolve_api_page_id(page_id_or_name: Any, conversation_id: Optional[str] = None) -> str:
    """
    Phân giải Tên Fanpage (vd 'Eztech Phân Tích Dữ Liệu') hoặc conversation_id
    về đúng mã page_id thực tế để gọi Pancake Public API (/pages/{page_id}/...).
    """
    # 1. Nếu page_id_or_name đã truyền vào và là một Page hợp lệ đã biết, ưu tiên dùng ngay
    if page_id_or_name:
        s = str(page_id_or_name).strip()
        if s in PAGE_NAME_TO_API_ID:
            return PAGE_NAME_TO_API_ID[s]
        canonical = resolve_canonical_page_name(s, fallback=None)
        if canonical and canonical in PAGE_NAME_TO_API_ID:
            return PAGE_NAME_TO_API_ID[canonical]
        for k, v in KNOWN_PAGE_NAMES.items():
            if v == s or v == canonical:
                if k.startswith(("pzl_", "tt_")):
                    return k
        for k, v in KNOWN_PAGE_NAMES.items():
            if v == s or v == canonical:
                if is_page_id(k):
                    return k
        clean_s = re.sub(r"^(pzl_|tt_|fb_)", "", s)
        if clean_s in KNOWN_PAGE_NAMES or f"tt_{clean_s}" in KNOWN_PAGE_NAMES or f"pzl_{clean_s}" in KNOWN_PAGE_NAMES:
            if s.startswith(("tt_", "pzl_")):
                return s
            if f"tt_{clean_s}" in KNOWN_PAGE_NAMES:
                return f"tt_{clean_s}"
            if f"pzl_{clean_s}" in KNOWN_PAGE_NAMES:
                return f"pzl_{clean_s}"

    # 2. Bóc tách từ conversation_id nếu chưa xác định được từ page_id_or_name
    if conversation_id:
        cid = str(conversation_id).strip()
        if cid.startswith("pzl_"):
            parts = cid.split("_")
            # Định dạng chuẩn: pzl_u_629476615535063343_...
            if len(parts) >= 3 and parts[2].isdigit():
                return f"pzl_{parts[2]}"
            if len(parts) >= 2 and parts[1].isdigit():
                return f"pzl_{parts[1]}"
        elif cid.startswith("tt_"):
            parts = cid.split(":")
            # Định dạng: tt_0:1:{ID_A}:{ID_B} trong đó một trong hai ID là Page ID và ID còn lại là Customer ID
            for p in parts[2:]:
                if f"tt_{p}" in KNOWN_PAGE_NAMES or p in KNOWN_PAGE_NAMES or f"tt_{p}" in PAGE_NAME_TO_API_ID.values():
                    return f"tt_{p}"
            # Fallback nếu không có trong danh mục biết trước:
            if len(parts) >= 3 and parts[2].isdigit():
                return f"tt_{parts[2]}"
            if len(parts) >= 2 and parts[-1].isdigit():
                return f"tt_{parts[-1]}"
        elif cid.startswith("fb_"):
            parts = cid.split("_")
            if len(parts) >= 2 and parts[1].isdigit():
                return parts[1]
        elif "_" in cid and not cid.startswith(("pzl_", "tt_")):
            parts = cid.split("_")
            if parts[0].isdigit() and len(parts[0]) >= 10:
                # Kiểm tra xem ID số này có phải Zalo/TikTok trong KNOWN_PAGE_NAMES không
                if f"pzl_{parts[0]}" in KNOWN_PAGE_NAMES:
                    return f"pzl_{parts[0]}"
                if f"tt_{parts[0]}" in KNOWN_PAGE_NAMES:
                    return f"tt_{parts[0]}"
                return parts[0]

    # 3. Fallback lấy chính page_id_or_name
    if page_id_or_name:
        return str(page_id_or_name).strip()

    return ""


def get_candidate_api_page_ids(page_id_or_name: Any, conversation_id: Optional[str] = None) -> List[str]:
    """Trả về danh sách các biến thể page_id (có prefix và không prefix) để fallback khi gọi Pancake API."""
    primary = resolve_api_page_id(page_id_or_name, conversation_id)
    if not primary:
        return []
    candidates = [primary]
    # Với Facebook Page có tiền tố fb_, thêm biến thể ID số thuần túy (Pancake FB yêu cầu ID số)
    if primary.startswith("fb_"):
        clean_num = primary[3:]
        if clean_num and clean_num not in candidates:
            candidates.append(clean_num)
    # Nếu ID truyền vào là số thuần nhưng thuộc Zalo (pzl_) hoặc TikTok (tt_), ưu tiên tiền tố chuẩn lên đầu
    elif primary.isdigit():
        if f"pzl_{primary}" in KNOWN_PAGE_NAMES and f"pzl_{primary}" not in candidates:
            candidates.insert(0, f"pzl_{primary}")
        elif f"tt_{primary}" in KNOWN_PAGE_NAMES and f"tt_{primary}" not in candidates:
            candidates.insert(0, f"tt_{primary}")
    return candidates


def is_zalo_channel(page_id_or_name: Any, conversation_id: Optional[str] = None) -> bool:
    """Kiểm tra xem hội thoại hoặc Page có phải là kênh Zalo cá nhân (pzl_) hay không."""
    if conversation_id and str(conversation_id).strip().startswith("pzl_"):
        return True
    api_pid = resolve_api_page_id(page_id_or_name, conversation_id)
    if api_pid.startswith("pzl_"):
        return True
    if page_id_or_name:
        s = str(page_id_or_name).strip()
        if s.startswith("pzl_") or s in zalo_page_keys():
            return True
        canonical = resolve_canonical_page_name(s, fallback="")
        if canonical in ZALO_PAGE_NAMES:
            return True
    return False
