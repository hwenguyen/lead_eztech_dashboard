"""
================================================================================
ROUTER QUẢN LÝ KẾT BẠN ZALO TỰ ĐỘNG QUA PANCAKE (AUTO ADD FRIEND)
Được thiết kế dựa trên workflow chuẩn từ `pancake_addfr_backup/bot.py`:
1. Import hàng loạt số điện thoại (dán trực tiếp, CSV/TSV từ Excel/Google Sheet,
   hoặc lấy từ kho Leads có SĐT của hệ thống).
2. Tự động chuẩn hóa SĐT Việt Nam (84... -> 0..., thêm số 0 bị mất từ Excel,
   lọc trùng lặp, lọc nguồn loại trừ SKIP_SOURCES).
3. Chọn Page Zalo cá nhân trên Pancake (Eztech Consultant, Eztech Phân Tích Dữ Liệu,
   Hiền Minh Eztech, Tuấn Anh Data, Ann...).
4. Soạn lời mời kết bạn + Tin nhắn chào hộp thoại + Ghi chú khách hàng theo mẫu
   (MESSAGE_TEMPLATES từ bot.py) kèm Spintax & cá nhân hóa {name}, {page}, {source}, {nhu_cau}.
5. Gắn thẻ Tag tự động (Web, Đào tạo, Lead Other, Đã add...) sau khi kết bạn.
6. Cơ chế chống chặn Rate Limit chuyên sâu cho Zalo (Random Jitter Delay,
   Batch Cooldown nghỉ theo chặng, Retry khi lag, Circuit Breaker tự ngắt khi lỗi
   liên tiếp hoặc Pancake 502/504, giới hạn số lượng an toàn mỗi đợt).
================================================================================
"""

import os
import sys
import subprocess
import re
import json
import time
import random
import logging
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from database.db import get_db, SessionLocal
from database.models import DimLead, FactLeadActivity, BotAutoReplyLog, AppConfig
from etl.utils import (
    VN_TZ,
    ZALO_PAGE_NAMES,
    KNOWN_PAGE_NAMES,
    resolve_canonical_page_name,
)
from backend.broadcast import (
    infer_vietnamese_gender,
    get_gender_title,
    resolve_spintax,
)

logger = logging.getLogger("AutoAddFriendAPI")

router = APIRouter()

# Khóa và bộ nhớ quản lý các tiến trình Kết bạn tự động đang chạy
_ADD_FRIEND_LOCK = threading.Lock()
_ADD_FRIEND_TASKS: Dict[str, Dict[str, Any]] = {}

# Đường dẫn lưu file phiên đăng nhập Pancake cho Playwright
PANCAKE_STATE_FILE = os.path.join(os.getcwd(), "pancake_state.json")
PANCAKE_STATE_CONFIG_KEY = "pancake_storage_state"


def get_vn_now() -> datetime:
    return datetime.now(VN_TZ).replace(tzinfo=None)


# ==============================================================================
# 1. CẤU HÌNH MẶC ĐỊNH TỪ `pancake_addfr_backup/bot.py`
# ==============================================================================

DEFAULT_ZALO_PAGES: List[Dict[str, str]] = [
    {"id": "Eztech Consultant", "name": "Eztech Consultant", "badge": "Mặc định (bot.py)"},
    {"id": "Eztech Phân Tích Dữ Liệu", "name": "Eztech Phân Tích Dữ Liệu", "badge": "Zalo Personal"},
    {"id": "Hiền Minh Eztech", "name": "Hiền Minh Eztech", "badge": "Zalo Personal"},
    {"id": "Tuấn Anh Data", "name": "Tuấn Anh Data", "badge": "Zalo Personal"},
    {"id": "Ann", "name": "Ann", "badge": "Zalo Personal"},
]

DEFAULT_SKIP_SOURCES: List[str] = [
    "ezexcel-dung-thu",
    "test-case-123",
]

# Bộ kịch bản tin nhắn theo nguồn (port nguyên bản từ `bot.py` MESSAGE_TEMPLATES)
BOT_MESSAGE_TEMPLATES: Dict[str, Dict[str, str]] = {
    "default": {
        "label": "Mặc định (Tư vấn chung)",
        "source_key": "default",
        "message": "Chào bạn, mình là {page}. Mình xin phép kết bạn để trao đổi chi tiết hơn về dịch vụ bên mình nhé ạ!",
    },
    "contact-page": {
        "label": "Website Contact Page (contact-page)",
        "source_key": "contact-page",
        "message": "Chào bạn, mình là {page}. Mình thấy bạn để lại thông tin qua website, không biết EzTech có thể hỗ trợ gì cho bạn!",
    },
    "report:quan-tri-pl": {
        "label": "Báo cáo Quản trị P&L (report:quan-tri-pl)",
        "source_key": "report:quan-tri-pl",
        "message": "Chào bạn, cảm ơn bạn đã quan tâm đến báo cáo Quản trị PL. Kết bạn với mình để nhận tư vấn file chi tiết nhé!",
    },
    "report:cong-no-phai-thu-tr": {
        "label": "Báo cáo Công nợ phải thu (report:cong-no-phai-thu-tr)",
        "source_key": "report:cong-no-phai-thu-tr",
        "message": "Chào bạn, cảm ơn bạn đã quan tâm đến báo cáo Công nợ phải thu. Kết bạn với mình để nhận tư vấn file chi tiết nhé!",
    },
    "course:data-finance": {
        "label": "Khóa học Data Finance (course:data-finance)",
        "source_key": "course:data-finance",
        "message": "Chào bạn, cảm ơn bạn đã quan tâm đến khóa học Data Finance của EzTech. Mình xin phép kết bạn để gửi bạn thông tin chi tiết nhé!",
    },
    "course:data-business": {
        "label": "Khóa học Data in Business (course:data-business)",
        "source_key": "course:data-business",
        "message": "Chào bạn, cảm ơn bạn đã quan tâm đến khóa học Data in Business của EzTech. Mình xin phép kết bạn để gửi bạn thông tin chi tiết nhé!",
    },
    "data-talk-20": {
        "label": "Sự kiện Data Talk 20 (data-talk-20)",
        "source_key": "data-talk-20",
        "message": "Chào bạn, cảm ơn bạn đã đăng ký tham gia sự kiện Data Talk 20. Kết bạn với mình để nhận thông tin sự kiện nhé!",
    },
    "service:dao-tao": {
        "label": "Dịch vụ Đào tạo (service:dao-tao)",
        "source_key": "service:dao-tao",
        "message": "Chào bạn, cảm ơn bạn đã quan tâm đến dịch vụ đào tạo của Eztech. Mình xin phép kết bạn để gửi bạn thông tin chi tiết nhé!",
    },
    "qua-tang-file-aio": {
        "label": "Quà tặng Bộ file AIO (qua-tang-file-aio)",
        "source_key": "qua-tang-file-aio",
        "message": "Chào bạn, mình là {page}. Mình xin phép kết bạn để gửi bạn thông tin về bộ file AIO miễn phí bên mình nhé!",
    },
    "qua-tang-prompt-ai": {
        "label": "Quà tặng Prompt AI (qua-tang-prompt-ai)",
        "source_key": "qua-tang-prompt-ai",
        "message": "Chào bạn, mình là {page}. Mình xin phép kết bạn để gửi bạn thông tin về bộ file prompt AI miễn phí bên mình nhé!",
    },
    "Landing khóa AI cho Kế toán": {
        "label": "Landing khóa AI cho Kế toán",
        "source_key": "Landing khóa AI cho Kế toán",
        "message": "Chào bạn, mình là {page}. Mình xin phép kết bạn để gửi bạn thông tin về khoá học AI dành riêng cho kế toán bên mình nhé!",
    },
}

DEFAULT_AVAILABLE_TAGS: List[str] = [
    "Web",
    "Đào tạo",
    "Lead Other",
    "Đã add",
    "Đang tư vấn",
    "Xin file",
    "Tham gia nhóm",
    "Khách tiềm năng",
    "Gọi lại sau",
]


# ==============================================================================
# 2. HÀM CHUẨN HÓA SỐ ĐIỆN THOẠI & RENDER TIN NHẮN (THEO LOGIC `bot.py`)
# ==============================================================================

def normalize_vn_phone(raw_phone: Optional[str]) -> Tuple[str, bool, str]:
    """
    Chuẩn hóa số điện thoại theo đúng logic của `pancake_addfr_backup/bot.py`:
    - Lọc chỉ giữ chữ số: `''.join(filter(str.isdigit, raw_phone))`
    - Nếu bắt đầu bằng `84` và độ dài >= 10 -> đổi `84` ở đầu thành `0`.
    - Nếu độ dài == 9 và bắt đầu bằng đầu số nhà mạng VN (3, 5, 7, 8, 9) do Excel mất số 0 -> thêm `0` vào đầu.
    Trả về: (clean_phone, is_valid, validation_note)
    """
    if not raw_phone:
        return "", False, "Trống"

    clean_phone = "".join(filter(str.isdigit, str(raw_phone).strip()))
    if not clean_phone:
        return "", False, "Không chứa chữ số"

    # Đổi 84 đầu thành 0 (theo đúng bot.py: if clean_phone.startswith("84") and len(clean_phone) >= 10)
    if clean_phone.startswith("84") and len(clean_phone) >= 10:
        clean_phone = "0" + clean_phone[2:]
    elif len(clean_phone) == 9 and clean_phone[0] in ("3", "5", "7", "8", "9"):
        clean_phone = "0" + clean_phone

    if len(clean_phone) < 9:
        return clean_phone, False, f"Quá ngắn ({len(clean_phone)} số)"
    if len(clean_phone) > 11:
        return clean_phone, False, f"Quá dài ({len(clean_phone)} số)"
    if not clean_phone.startswith("0"):
        return clean_phone, False, "Không bắt đầu bằng số 0"

    return clean_phone, True, "Hợp lệ"


def render_add_friend_message(
    template_str: str,
    page_name: str,
    phone: str,
    name: str = "",
    source: str = "",
    nhu_cau: str = "",
    use_source_template: bool = True,
    enable_spintax: bool = True,
) -> str:
    """
    Kết xuất nội dung lời mời kết bạn / tin nhắn chào:
    - Nếu `use_source_template=True` và `source` khớp với `BOT_MESSAGE_TEMPLATES`, ưu tiên mẫu theo nguồn (nếu người dùng chưa sửa tay khác mẫu).
    - Thay thế các biến `{page}`, `{name}`, `{gender_title}`, `{gender_title_lower}`, `{phone}`, `{source}`, `{nhu_cau}`.
    - Giải mã Spintax `{Chào|Xin chào|Dạ chào}`.
    """
    base_text = (template_str or "").strip()
    clean_source = (source or "").strip()

    if use_source_template and clean_source and clean_source in BOT_MESSAGE_TEMPLATES:
        base_text = BOT_MESSAGE_TEMPLATES[clean_source]["message"]

    if not base_text:
        base_text = BOT_MESSAGE_TEMPLATES["default"]["message"]

    if enable_spintax:
        base_text = resolve_spintax(base_text)

    gender = infer_vietnamese_gender(name)
    title_cap, title_low = get_gender_title(gender)
    display_name = (name or "").strip() or "bạn"

    msg = base_text
    msg = msg.replace("{page}", page_name or "Eztech Consultant")
    msg = msg.replace("{name}", display_name)
    msg = msg.replace("{gender_title}", title_cap)
    msg = msg.replace("{gender_title_lower}", title_low)
    msg = msg.replace("{phone}", phone or "")
    msg = msg.replace("{source}", clean_source or "Website")
    msg = msg.replace("{nhu_cau}", (nhu_cau or "").strip() or "Tư vấn")

    msg = re.sub(r"[ \t]{2,}", " ", msg).strip()
    return msg


def render_customer_note(
    note_template: str,
    name: str = "",
    source: str = "",
    nhu_cau: str = "",
    page_name: str = "",
) -> str:
    """Kết xuất nội dung ghi chú khách hàng (mặc định: `Nguồn: {source} | Nhu cầu: {nhu_cau}`)."""
    tpl = (note_template or "Nguồn: {source} | Nhu cầu: {nhu_cau}").strip()
    res = tpl.replace("{source}", (source or "").strip() or "Direct")
    res = res.replace("{nhu_cau}", (nhu_cau or "").strip() or "Tư vấn")
    res = res.replace("{name}", (name or "").strip())
    res = res.replace("{page}", (page_name or "").strip())
    return res.strip()


# ==============================================================================
# 3. QUẢN LÝ PHIÊN ĐĂNG NHẬP PLAYWRIGHT (`pancake_state.json`) TRONG APP_CONFIGS
# ==============================================================================

PANCAKE_STATE_CONFIG_KEYS = [
    "PANCAKE_STORAGE_STATE",
    "pancake_storage_state",
    "PANCAKE_STATE",
    "pancake_state",
]


def load_pancake_state_from_db(db: Optional[Session] = None) -> Tuple[Optional[str], Optional[datetime], Optional[str]]:
    """Đọc cấu hình pancake_state.json từ bảng app_configs trong Neon DB."""
    own_session = False
    if db is None:
        db = SessionLocal()
        own_session = True
    try:
        for k in PANCAKE_STATE_CONFIG_KEYS:
            rec = db.query(AppConfig).filter(AppConfig.config_key == k).first()
            if rec and rec.config_value and rec.config_value.strip():
                return rec.config_value.strip(), rec.updated_at, k
        return None, None, None
    except Exception as e:
        logger.warning(f"Lỗi khi đọc pancake_state từ app_configs: {e}")
        return None, None, None
    finally:
        if own_session and db:
            db.close()


def save_pancake_state_to_db(state_json: str, db: Optional[Session] = None) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Lưu bền vững nội dung pancake_state.json vào bảng app_configs trong Neon DB
    và đồng bộ ra file pancake_state.json trên đĩa.
    """
    raw = (state_json or "").strip()
    if not raw:
        return False, "Nội dung JSON đang để trống.", {}

    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or ("cookies" not in parsed and "origins" not in parsed):
            return False, "JSON không đúng định dạng Playwright storage_state (cần chứa 'cookies' hoặc 'origins').", {}
    except Exception as e:
        return False, f"JSON không hợp lệ: {str(e)}", {}

    own_session = False
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        now_vn = get_vn_now()
        # Lưu vào key chuẩn PANCAKE_STORAGE_STATE
        primary_key = "PANCAKE_STORAGE_STATE"
        rec = db.query(AppConfig).filter(AppConfig.config_key == primary_key).first()
        if rec:
            rec.config_value = raw
            rec.updated_at = now_vn
        else:
            rec = AppConfig(
                config_key=primary_key,
                config_value=raw,
                updated_at=now_vn,
            )
            db.add(rec)

        # Cập nhật thêm key phụ pancake_storage_state để tương thích ngược 100%
        for legacy_key in ("pancake_storage_state", "PANCAKE_STATE"):
            l_rec = db.query(AppConfig).filter(AppConfig.config_key == legacy_key).first()
            if l_rec:
                l_rec.config_value = raw
                l_rec.updated_at = now_vn

        db.commit()

        # Đồng bộ ra file pancake_state.json trên đĩa
        try:
            with open(PANCAKE_STATE_FILE, "w", encoding="utf-8") as f:
                f.write(raw)
        except Exception as f_err:
            logger.warning(f"Không thể ghi ra file pancake_state.json: {f_err}")

        cookies = parsed.get("cookies", [])
        origins = parsed.get("origins", [])
        info = {
            "has_state": True,
            "source": "database",
            "storage_key": primary_key,
            "cookies_count": len(cookies),
            "origins_count": len(origins),
            "updated_at": now_vn.strftime("%Y-%m-%d %H:%M:%S"),
        }
        return True, "Đã lưu bền vững pancake_state.json vào bảng app_configs thành công!", info
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi lưu pancake_state vào app_configs: {e}")
        return False, f"Lỗi cơ sở dữ liệu: {str(e)}", {}
    finally:
        if own_session and db:
            db.close()


def delete_pancake_state_from_db(db: Optional[Session] = None) -> Tuple[bool, str]:
    """Xóa cấu hình phiên đăng nhập Pancake khỏi bảng app_configs và xóa file trên đĩa."""
    own_session = False
    if db is None:
        db = SessionLocal()
        own_session = True
    try:
        deleted = (
            db.query(AppConfig)
            .filter(AppConfig.config_key.in_(PANCAKE_STATE_CONFIG_KEYS))
            .delete(synchronize_session=False)
        )
        db.commit()

        if os.path.exists(PANCAKE_STATE_FILE):
            try:
                os.remove(PANCAKE_STATE_FILE)
            except Exception:
                pass

        return True, f"Đã xóa phiên đăng nhập Pancake ({deleted} bản ghi trong app_configs)."
    except Exception as e:
        db.rollback()
        return False, f"Lỗi khi xóa phiên đăng nhập: {str(e)}"
    finally:
        if own_session and db:
            db.close()


def get_pancake_state_info(db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Kiểm tra trạng thái cấu hình pancake_state.json:
    - Ưu tiên kiểm tra trong bảng app_configs (nguồn lưu trữ bền vững nhất).
    - Nếu trong DB chưa có nhưng file trên đĩa hoặc biến môi trường PANCAKE_STATE có,
      tự động nạp và lưu bền vững vào bảng app_configs!
    - Nếu trong DB có nhưng file trên đĩa chưa có, tự động ghi ra file pancake_state.json.
    """
    state_raw, updated_at, found_key = load_pancake_state_from_db(db)
    source = "database" if state_raw else None
    updated_at_str = updated_at.strftime("%Y-%m-%d %H:%M:%S") if updated_at else None

    # Nếu DB chưa có, kiểm tra file trên đĩa hoặc biến môi trường
    if not state_raw:
        if os.path.exists(PANCAKE_STATE_FILE):
            try:
                with open(PANCAKE_STATE_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        state_raw = content
                        # Tự động lưu bền vững vào app_configs
                        ok, _, _ = save_pancake_state_to_db(content, db)
                        if ok:
                            source = "database (tự động đồng bộ từ file)"
            except Exception as e:
                logger.warning(f"Không thể đọc file pancake_state.json: {e}")

        if not state_raw and os.environ.get("PANCAKE_STATE"):
            env_val = os.environ["PANCAKE_STATE"].strip()
            if env_val:
                state_raw = env_val
                # Tự động lưu bền vững vào app_configs
                ok, _, _ = save_pancake_state_to_db(env_val, db)
                if ok:
                    source = "database (tự động đồng bộ từ env PANCAKE_STATE)"

    # Nếu DB có mà đĩa chưa có file -> ghi ra đĩa
    if state_raw and not os.path.exists(PANCAKE_STATE_FILE):
        try:
            with open(PANCAKE_STATE_FILE, "w", encoding="utf-8") as f:
                f.write(state_raw)
        except Exception:
            pass

    if not state_raw:
        return {
            "has_state": False,
            "source": None,
            "storage_key": None,
            "cookies_count": 0,
            "origins_count": 0,
            "updated_at": None,
        }

    try:
        parsed = json.loads(state_raw)
        cookies = parsed.get("cookies", []) if isinstance(parsed, dict) else []
        origins = parsed.get("origins", []) if isinstance(parsed, dict) else []
        return {
            "has_state": True,
            "source": source or "database",
            "storage_key": found_key or "PANCAKE_STORAGE_STATE",
            "cookies_count": len(cookies),
            "origins_count": len(origins),
            "updated_at": updated_at_str or get_vn_now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception:
        return {
            "has_state": False,
            "source": source,
            "storage_key": found_key,
            "cookies_count": 0,
            "origins_count": 0,
            "updated_at": updated_at_str,
        }


def ensure_pancake_state_file() -> Optional[str]:
    """Đảm bảo file `pancake_state.json` tồn tại trên đĩa trước khi Playwright khởi chạy."""
    if os.path.exists(PANCAKE_STATE_FILE) and os.path.getsize(PANCAKE_STATE_FILE) > 10:
        return PANCAKE_STATE_FILE

    # Lấy từ bảng app_configs
    state_raw, _, _ = load_pancake_state_from_db()
    if not state_raw and os.environ.get("PANCAKE_STATE"):
        state_raw = os.environ["PANCAKE_STATE"].strip()

    if state_raw and state_raw.strip():
        try:
            with open(PANCAKE_STATE_FILE, "w", encoding="utf-8") as f:
                f.write(state_raw.strip())
            return PANCAKE_STATE_FILE
        except Exception as e:
            logger.error(f"Lỗi khi ghi file pancake_state.json: {e}")

    return None


# ==============================================================================
# 4. SCHEMAS (PYDANTIC MODELS)
# ==============================================================================

class PhoneImportItem(BaseModel):
    raw_phone: str
    phone: str
    is_valid: bool = True
    validation_note: str = "Hợp lệ"
    name: str = ""
    source: str = ""
    nhu_cau: str = ""
    is_duplicate: bool = False
    is_skipped_source: bool = False
    already_added: bool = False
    rendered_message: str = ""
    rendered_note: str = ""


class ParsePhonesRequest(BaseModel):
    raw_text: str = Field(..., description="Danh sách SĐT hoặc bảng copy từ Excel/Google Sheet")
    page_name: str = Field("Eztech Consultant", description="Tên Page Zalo thực hiện kết bạn")
    message_template: str = Field(
        BOT_MESSAGE_TEMPLATES["default"]["message"],
        description="Nội dung lời mời kết bạn / tin nhắn chào",
    )
    note_template: str = Field(
        "Nguồn: {source} | Nhu cầu: {nhu_cau}",
        description="Mẫu ghi chú tự động",
    )
    use_source_template: bool = Field(
        True,
        description="Tự động chọn mẫu câu chào theo cột Nguồn (giống bot.py)",
    )
    enable_spintax: bool = Field(True, description="Xoay vòng từ ngữ Spintax")
    skip_sources: List[str] = Field(default_factory=lambda: list(DEFAULT_SKIP_SOURCES))
    exclude_already_added: bool = Field(True, description="Đánh dấu các SĐT đã từng kết bạn thành công")


class ParsePhonesResponse(BaseModel):
    total_lines: int
    valid_count: int
    invalid_count: int
    duplicate_count: int
    skipped_source_count: int
    already_added_count: int
    ready_count: int
    items: List[PhoneImportItem]


class RateLimitSettings(BaseModel):
    preset: str = Field("recommended", description="fast | recommended | ultra | custom")
    delay_min: float = Field(8.0, ge=1.0, le=300.0, description="Thời gian nghỉ tối thiểu giữa 2 SĐT (giây)")
    delay_max: float = Field(16.0, ge=1.0, le=300.0, description="Thời gian nghỉ tối đa giữa 2 SĐT (giây)")
    batch_size: int = Field(10, ge=1, le=200, description="Số SĐT mỗi chặng trước khi nghỉ dài")
    batch_pause_sec: float = Field(45.0, ge=0.0, le=1800.0, description="Thời gian nghỉ giải lao giữa các chặng (giây)")
    max_retries: int = Field(2, ge=1, le=5, description="Số lần thử lại tối đa khi lag (giống MAX_RETRIES=2 trong bot.py)")
    max_consecutive_errors: int = Field(3, ge=1, le=20, description="Tự ngắt khi lỗi liên tiếp N lần (Circuit Breaker)")
    daily_limit: int = Field(50, ge=1, le=500, description="Giới hạn số lượng SĐT tối đa trong 1 chiến dịch")
    enable_spintax: bool = Field(True, description="Tự động biến thiên nội dung bằng Spintax")
    exclude_already_added: bool = Field(True, description="Bỏ qua SĐT đã gửi kết bạn thành công trước đó")


class AddFriendTargetItem(BaseModel):
    phone: str
    name: str = ""
    source: str = ""
    nhu_cau: str = ""
    custom_message: Optional[str] = None
    custom_note: Optional[str] = None


class StartAddFriendRequest(BaseModel):
    campaign_name: str = Field(..., description="Tên chiến dịch kết bạn")
    page_name: str = Field("Eztech Consultant", description="Tên Page Zalo cá nhân trên Pancake")
    items: List[AddFriendTargetItem] = Field(..., description="Danh sách SĐT cần kết bạn")
    message_template: str = Field(
        BOT_MESSAGE_TEMPLATES["default"]["message"],
        description="Nội dung lời mời kết bạn",
    )
    inbox_message_template: Optional[str] = Field(
        None,
        description="Nội dung tin nhắn gửi vào hộp thoại sau khi kết bạn (nếu để trống sẽ dùng message_template)",
    )
    use_source_template: bool = Field(True, description="Tự động đổi mẫu câu chào theo cột Nguồn")
    send_inbox_message: bool = Field(True, description="Bấm 'Nhắn tin' và gửi lời chào vào hộp thoại (#replyBoxComposer)")
    add_note: bool = Field(True, description="Tự động điền ghi chú khách hàng (Nguồn | Nhu cầu)")
    note_template: str = Field("Nguồn: {source} | Nhu cầu: {nhu_cau}", description="Mẫu ghi chú khách hàng")
    tags: List[str] = Field(default_factory=lambda: ["Web"], description="Danh sách thẻ Tag cần gắn (vd: ['Web'])")
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    dry_run: bool = Field(True, description="True = Chạy mô phỏng an toàn, False = Chạy thật qua Playwright Pancake")


class SavePancakeStateRequest(BaseModel):
    state_json: str = Field(..., description="Nội dung file pancake_state.json (Playwright storage state)")


# ==============================================================================
# 5. PARSER DANH SÁCH SỐ ĐIỆN THOẠI HÀNG LOẠT (TEXT / CSV / EXCEL TSV)
# ==============================================================================

PHONE_CANDIDATE_REGEX = re.compile(r"(?:\+?84|0)[\d\s.\-]{7,13}\d|\b[35789][\d\s.\-]{7,10}\d\b")


def _extract_columns_from_line(line: str) -> Tuple[str, str, str, str]:
    """
    Tách thông minh 1 dòng dữ liệu (có thể là 1 SĐT đơn lẻ, hoặc 1 dòng copy từ Excel/Google Sheet
    ngăn cách bởi Tab `\t`, dấu chấm phẩy `;`, dấu gạch đứng `|`, hoặc dấu phẩy `,`).
    Trả về: `(raw_phone, name, source, nhu_cau)`
    """
    stripped = line.strip()
    if not stripped:
        return "", "", "", ""

    # Xác định ký tự phân cách cột
    if "\t" in stripped:
        parts = [p.strip() for p in stripped.split("\t")]
    elif "|" in stripped:
        parts = [p.strip() for p in stripped.split("|")]
    elif ";" in stripped:
        parts = [p.strip() for p in stripped.split(";")]
    elif "," in stripped:
        parts = [p.strip() for p in stripped.split(",")]
    else:
        parts = [stripped]

    if len(parts) == 1:
        return parts[0], "", "", ""

    # Tìm cột nào là SĐT trong các cột
    phone_idx = -1
    for idx, col in enumerate(parts):
        digits = "".join(filter(str.isdigit, col))
        if 9 <= len(digits) <= 12:
            phone_idx = idx
            break

    if phone_idx == -1:
        # Mặc định cột đầu tiên là SĐT
        phone_idx = 0

    raw_phone = parts[phone_idx]
    remaining = [p for i, p in enumerate(parts) if i != phone_idx]

    name = remaining[0] if len(remaining) >= 1 else ""
    source = remaining[1] if len(remaining) >= 2 else ""
    nhu_cau = remaining[2] if len(remaining) >= 3 else ""

    return raw_phone, name, source, nhu_cau


def _get_already_added_phones(db: Session) -> set:
    """Lấy tập hợp các SĐT đã từng được kết bạn thành công (status='SENT' hoặc 'ADDED') trong bảng bot_auto_replies."""
    try:
        rows = (
            db.query(BotAutoReplyLog.customer_id, BotAutoReplyLog.conversation_id)
            .filter(
                BotAutoReplyLog.case_id.like("addfriend_%"),
                BotAutoReplyLog.status.in_(["SENT", "ADDED"]),
            )
            .all()
        )
        added = set()
        for cid, conv_id in rows:
            for val in (cid, conv_id):
                if val:
                    clean, ok, _ = normalize_vn_phone(val)
                    if ok:
                        added.add(clean)
        return added
    except Exception:
        return set()


# ==============================================================================
# 6. PLAYWRIGHT AUTOMATION ENGINE (PORT TỪ `pancake_addfr_backup/bot.py`)
# ==============================================================================

def _mem_mb() -> str:
    for p in ("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory/memory.usage_in_bytes"):
        if os.path.exists(p):
            try:
                with open(p) as f:
                    return f"{int(f.read().strip()) // (1024 * 1024)}MB"
            except Exception:
                pass
    return ""


def _execute_pancake_add_friend_single(
    page: Any,
    target_dashboard: str,
    phone: str,
    friend_request_msg: str,
    inbox_msg: str,
    note_text: str,
    tags: List[str],
    send_inbox_message: bool = True,
    add_note: bool = True,
    step_cb: Any = None,
) -> Tuple[str, str]:
    """
    Thực thi quy trình kết bạn trên Pancake cho 1 số điện thoại (port nguyên bản từ `process_via_pancake` trong `bot.py`).
    Trả về `(status_code, detail_message)`:
    - `("ADDED", "Đã gửi lời mời kết bạn + nhắn tin + gắn tag thành công")`
    - `("NOT_FOUND", "Không tìm thấy Zalo / Đã kết bạn trước đó")`
    - `("SERVER_ERROR", "Pancake 502/504 Bad Gateway")`
    - `("AUTH_EXPIRED", "Phiên đăng nhập pancake_state.json đã hết hạn")`
    - `("FAILED", "Chi tiết lỗi...")`
    """
    try:
        def _report(msg: str):
            if step_cb:
                ram = _mem_mb()
                step_cb(f"{msg} {f'[{ram}]' if ram else ''}".strip())

        search_icon_btn = page.locator("button.conversation-menu-item.create-conversation-button").first
        need_open_dashboard = True
        try:
            if "pages.fm" in (page.url or "") and search_icon_btn.is_visible():
                page.keyboard.press("Escape")
                time.sleep(0.5)
                need_open_dashboard = False
        except Exception:
            need_open_dashboard = True

        if need_open_dashboard:
            _report(f"Đang mở pages.fm cho SĐT {phone}...")
            page.goto("https://pages.fm/", timeout=60000, wait_until="domcontentloaded")
            time.sleep(2.5)

            # Kiểm tra sập server 502 / 504 (từ bot.py)
            title_text = page.title() or ""
            if "502 Bad Gateway" in title_text or "504 Gateway Time-out" in title_text:
                return "SERVER_ERROR", f"Pancake trả về lỗi máy chủ: {title_text}"
            if page.locator("text='502 Bad Gateway'").is_visible():
                return "SERVER_ERROR", "Pancake đang bị lỗi 502 Bad Gateway"

            # Kiểm tra hết hạn đăng nhập
            if page.locator("text='Đăng nhập'").is_visible():
                return "AUTH_EXPIRED", "Phiên đăng nhập Pancake (pancake_state.json) đã hết hạn!"

            # Bước 1: Chọn Page Dashboard (vd: "Eztech Consultant")
            _report(f"Đang chọn Page '{target_dashboard}'...")
            dashboard_item = page.locator("div.dashboard-page-item", has_text=target_dashboard).first
            dashboard_item.wait_for(state="visible", timeout=25000)
            dashboard_item.click()
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2.5)

        # Bước 2: Bấm nút Tạo hội thoại / Tìm số điện thoại
        _report(f"Đang mở ô tìm kiếm SĐT {phone}...")
        search_icon_btn.wait_for(state="visible", timeout=20000)
        search_icon_btn.click()

        # Bước 3: Điền SĐT và nhấn Enter
        _report(f"Đang tra cứu Zalo SĐT {phone}...")
        phone_input = page.get_by_placeholder("Nhập số điện thoại")
        phone_input.wait_for(state="visible", timeout=10000)
        phone_input.fill(phone)
        phone_input.press("Enter")

        # Chờ phản hồi từ Zalo / Pancake
        time.sleep(2.5)
        error_notif = page.locator(".ant-notification-notice-description")
        if error_notif.is_visible():
            err_text = error_notif.inner_text()
            if "Không tìm thấy" in err_text:
                return "NOT_FOUND", f"Zalo báo không tìm thấy SĐT {phone}"

        # Bước 4: Tìm nút "Kết bạn"
        add_friend_btn = page.get_by_role("button", name="Kết bạn").first
        has_add_friend_btn = True
        try:
            add_friend_btn.wait_for(state="visible", timeout=5000)
        except Exception:
            has_add_friend_btn = False

        if not has_add_friend_btn:
            # Kiểm tra xem có nút "Nhắn tin" không (trường hợp đã là bạn bè sẵn)
            msg_btn_check = page.locator(".item-actions button, button").filter(has_text="Nhắn tin").first
            if not msg_btn_check.is_visible():
                return "NOT_FOUND", f"Không tìm thấy tài khoản Zalo hoặc nút Kết bạn cho SĐT {phone}"

        if has_add_friend_btn:
            add_friend_btn.click()

            # Bước 5: Điền lời chào kết bạn trong Modal và xác nhận
            greeting_input = page.locator("textarea.ant-input, input.ant-input, textarea").first
            greeting_input.wait_for(state="visible", timeout=10000)
            greeting_input.fill(friend_request_msg[:150])
            time.sleep(1)

            confirm_btn = (
                page.locator(".send-friend-request-modal .ant-modal-footer button.color-primary")
                .filter(has_text="Kết bạn")
                .first
            )
            confirm_btn.wait_for(state="visible", timeout=10000)
            confirm_btn.click()
            time.sleep(2)

        # Bước 6: Mở hộp thoại để Thêm ghi chú / Nhắn tin chào / Gắn Tag (nếu được bật)
        actions_done = ["Đã gửi lời mời kết bạn"] if has_add_friend_btn else ["Đã là bạn bè sẵn"]
        if send_inbox_message or add_note or (tags and len(tags) > 0):
            msg_btn = page.locator(".item-actions button, button").filter(has_text="Nhắn tin").first
            try:
                msg_btn.wait_for(state="visible", timeout=10000)
                msg_btn.click()
                time.sleep(3)

                # 6a. Thêm ghi chú khách hàng
                if add_note and note_text:
                    try:
                        note_input = page.locator('textarea[placeholder*="ghi chú"]').first
                        note_input.wait_for(state="visible", timeout=8000)
                        note_input.click()
                        note_input.fill(note_text)
                        time.sleep(0.8)
                        note_input.press("Enter")
                        actions_done.append("đã lưu ghi chú")
                        time.sleep(1.5)
                    except Exception as note_err:
                        logger.warning(f"[{phone}] Không thể điền ghi chú: {note_err}")

                # 6b. Gửi tin nhắn trực tiếp vào hộp thoại
                if send_inbox_message and inbox_msg:
                    try:
                        chat_input = page.locator('#replyBoxComposer, textarea[placeholder*="Trả lời từ"]').first
                        chat_input.wait_for(state="visible", timeout=10000)
                        chat_input.click()
                        chat_input.fill(inbox_msg)
                        time.sleep(1)
                        chat_input.press("Enter")
                        actions_done.append("đã nhắn tin chào")
                        time.sleep(2)
                    except Exception as chat_err:
                        logger.warning(f"[{phone}] Không thể gửi tin nhắn hộp thoại: {chat_err}")

                # 6c. Gắn thẻ Tag (vd: "Web", "Đào tạo"...)
                if tags:
                    attached_tags = []
                    for tag_name in tags:
                        t_clean = (tag_name or "").strip()
                        if not t_clean:
                            continue
                        try:
                            tag_btn = page.locator("button.btn-tag-item").filter(has_text=t_clean).first
                            tag_btn.wait_for(state="visible", timeout=6000)
                            tag_btn.click()
                            attached_tags.append(t_clean)
                            time.sleep(1)
                        except Exception as tag_err:
                            logger.warning(f"[{phone}] Không tìm thấy/gắn được tag '{t_clean}': {tag_err}")
                    if attached_tags:
                        actions_done.append(f"gắn tag [{', '.join(attached_tags)}]")
            except Exception as post_err:
                logger.warning(f"[{phone}] Không mở được màn hình Nhắn tin sau khi kết bạn: {post_err}")

        time.sleep(2)
        return "ADDED", ", ".join(actions_done)

    except Exception as e:
        err_str = str(e)
        if "502 Bad Gateway" in err_str or "504 Gateway Time-out" in err_str:
            return "SERVER_ERROR", f"Lỗi máy chủ Pancake: {err_str[:120]}"
        return "FAILED", err_str[:200]


def _run_add_friend_worker(task_id: str, req_data: Dict[str, Any]):
    """
    Luồng chạy ngầm (Background Worker) thực thi chiến dịch Kết bạn tự động:
    - Tuân thủ đầy đủ cấu hình Chống chặn Rate Limit (Random Jitter Delay,
      Batch Cooldown nghỉ theo chặng, Retry tối đa `max_retries` lần mỗi SĐT,
      Circuit Breaker tự ngắt khi lỗi liên tiếp hoặc gặp 502/504 / hết hạn đăng nhập).
    - Ghi nhận tiến trình thời gian thực và lưu lịch sử vào bảng `bot_auto_replies`.
    """
    campaign_name = req_data.get("campaign_name", "addfriend_campaign")
    case_id = campaign_name if campaign_name.startswith("addfriend_") else f"addfriend_{campaign_name}"
    page_name = req_data.get("page_name", "Eztech Consultant")
    raw_items: List[Dict[str, Any]] = req_data.get("items", [])
    message_template = req_data.get("message_template", "")
    inbox_message_template = req_data.get("inbox_message_template") or message_template
    use_source_template = bool(req_data.get("use_source_template", True))
    send_inbox_message = bool(req_data.get("send_inbox_message", True))
    add_note = bool(req_data.get("add_note", True))
    note_template = req_data.get("note_template", "Nguồn: {source} | Nhu cầu: {nhu_cau}")
    tags: List[str] = req_data.get("tags", [])
    dry_run = bool(req_data.get("dry_run", True))

    rl = req_data.get("rate_limit", {}) or {}
    delay_min = float(rl.get("delay_min", 8.0))
    delay_max = max(delay_min, float(rl.get("delay_max", 16.0)))
    batch_size = max(1, int(rl.get("batch_size", 10)))
    batch_pause_sec = max(0.0, float(rl.get("batch_pause_sec", 45.0)))
    max_retries = max(1, int(rl.get("max_retries", 2)))
    max_consecutive_errors = max(1, int(rl.get("max_consecutive_errors", 3)))
    daily_limit = max(1, int(rl.get("daily_limit", 50)))
    enable_spintax = bool(rl.get("enable_spintax", True))

    target_items = raw_items[:daily_limit]

    with _ADD_FRIEND_LOCK:
        task = _ADD_FRIEND_TASKS.get(task_id)
        if not task:
            return
        task["total"] = len(target_items)
        task["current_action"] = (
            f"Chuẩn bị xử lý {len(target_items)} số điện thoại trên Page '{page_name}'..."
        )

    db = SessionLocal()
    playwright_ctx = None
    browser = None
    context = None
    pw_page = None

    try:
        # Nếu chạy thật (Live mode), khởi tạo trình duyệt Playwright với pancake_state.json
        if not dry_run:
            state_path = ensure_pancake_state_file()
            if not state_path:
                with _ADD_FRIEND_LOCK:
                    task = _ADD_FRIEND_TASKS.get(task_id)
                    if task:
                        task["is_running"] = False
                        task["current_action"] = (
                            "Dừng: Chưa có cấu hình phiên đăng nhập pancake_state.json!"
                        )
                        task["finished_at"] = get_vn_now().strftime("%Y-%m-%d %H:%M:%S")
                return

            try:
                import gc
                gc.collect()
                from playwright.sync_api import sync_playwright
                playwright_ctx = sync_playwright().start()
                launch_args = [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--disable-sync",
                    "--disable-translate",
                    "--mute-audio",
                    "--no-first-run",
                    "--blink-settings=imagesEnabled=false",
                    "--js-flags=--max-old-space-size=192",
                ]
                try:
                    with _ADD_FRIEND_LOCK:
                        task = _ADD_FRIEND_TASKS.get(task_id)
                        if task:
                            task["current_action"] = f"⏳ Đang khởi chạy trình duyệt Chromium... [{_mem_mb()}]"
                    browser = playwright_ctx.chromium.launch(headless=True, args=launch_args)
                except Exception as launch_err:
                    if "Executable doesn't exist" in str(launch_err):
                        with _ADD_FRIEND_LOCK:
                            task = _ADD_FRIEND_TASKS.get(task_id)
                            if task:
                                task["current_action"] = (
                                    "⏳ [1/2] Đang tải trình duyệt Chromium rút gọn (headless-shell)..."
                                )
                        subprocess.run(
                            [sys.executable, "-m", "playwright", "install", "--only-shell", "chromium"],
                            check=True,
                        )
                        with _ADD_FRIEND_LOCK:
                            task = _ADD_FRIEND_TASKS.get(task_id)
                            if task:
                                task["current_action"] = (
                                    "⏳ [2/2] Đã tải xong! Đang khởi chạy trình duyệt Chromium..."
                                )
                        browser = playwright_ctx.chromium.launch(headless=True, args=launch_args)
                    else:
                        raise launch_err
                context = browser.new_context(
                    storage_state=state_path,
                    viewport={"width": 1024, "height": 640},
                )
                context.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in ("image", "media", "font")
                    else route.continue_(),
                )
                pw_page = context.new_page()
            except Exception as pw_err:
                with _ADD_FRIEND_LOCK:
                    task = _ADD_FRIEND_TASKS.get(task_id)
                    if task:
                        task["is_running"] = False
                        task["current_action"] = (
                            f"Không thể khởi chạy trình duyệt tự động Playwright: {str(pw_err)[:300]}"
                        )
                        task["finished_at"] = get_vn_now().strftime("%Y-%m-%d %H:%M:%S")
                return

        consecutive_errors = 0

        for idx, item in enumerate(target_items, start=1):
            with _ADD_FRIEND_LOCK:
                task = _ADD_FRIEND_TASKS.get(task_id)
                if not task or not task.get("is_running"):
                    logger.info(f"Chiến dịch kết bạn {task_id} đã được yêu cầu dừng.")
                    break

            phone = item.get("phone", "").strip()
            name = item.get("name", "").strip()
            source = item.get("source", "").strip()
            nhu_cau = item.get("nhu_cau", "").strip()

            friend_msg = item.get("custom_message") or render_add_friend_message(
                template_str=message_template,
                page_name=page_name,
                phone=phone,
                name=name,
                source=source,
                nhu_cau=nhu_cau,
                use_source_template=use_source_template,
                enable_spintax=enable_spintax,
            )
            inbox_msg = render_add_friend_message(
                template_str=inbox_message_template,
                page_name=page_name,
                phone=phone,
                name=name,
                source=source,
                nhu_cau=nhu_cau,
                use_source_template=use_source_template,
                enable_spintax=enable_spintax,
            )
            note_text = item.get("custom_note") or render_customer_note(
                note_template=note_template,
                name=name,
                source=source,
                nhu_cau=nhu_cau,
                page_name=page_name,
            )

            with _ADD_FRIEND_LOCK:
                task = _ADD_FRIEND_TASKS.get(task_id)
                if task:
                    task["current_phone"] = phone
                    task["current_action"] = (
                        f"Đang xử lý [{idx}/{len(target_items)}]: {phone}"
                        + (f" ({name})" if name else "")
                    )

            status_result = "FAILED"
            detail_msg = ""
            attempts_used = 0

            if dry_run:
                # Mô phỏng thời gian phản hồi thực tế
                time.sleep(0.6)
                attempts_used = 1
                status_result = "DRY_RUN"
                tag_label = f" | Tag: {', '.join(tags)}" if tags else ""
                note_label = f" | Note: '{note_text}'" if add_note else ""
                detail_msg = (
                    f"[Chạy thử] Sẽ gửi lời mời kết bạn tới {phone} trên '{page_name}'"
                    f"{note_label}{tag_label}"
                )
            else:
                # Chạy thật qua Playwright với cơ chế Retry (MAX_RETRIES từ bot.py)
                def _update_step(msg_txt: str):
                    with _ADD_FRIEND_LOCK:
                        t_obj = _ADD_FRIEND_TASKS.get(task_id)
                        if t_obj:
                            t_obj["current_action"] = f"[{idx}/{len(target_items)}] {msg_txt}"

                for attempt in range(1, max_retries + 1):
                    attempts_used = attempt
                    status_code, detail = _execute_pancake_add_friend_single(
                        page=pw_page,
                        target_dashboard=page_name,
                        phone=phone,
                        friend_request_msg=friend_msg,
                        inbox_msg=inbox_msg,
                        note_text=note_text,
                        tags=tags,
                        send_inbox_message=send_inbox_message,
                        add_note=add_note,
                        step_cb=_update_step,
                    )
                    status_result = status_code
                    detail_msg = detail

                    if status_code in ("ADDED", "NOT_FOUND", "SERVER_ERROR", "AUTH_EXPIRED"):
                        break

                    # Nếu FAILED và còn lượt thử lại -> nghỉ 5s giống bot.py rồi thử lại
                    if attempt < max_retries:
                        with _ADD_FRIEND_LOCK:
                            task = _ADD_FRIEND_TASKS.get(task_id)
                            if task:
                                task["current_action"] = (
                                    f"⚠️ Lỗi tạm thời ở SĐT {phone} (lần {attempt}/{max_retries}). "
                                    f"Đang nghỉ 5s trước khi thử lại..."
                                )
                        time.sleep(5.0)

            # Lưu nhật ký vào bảng BotAutoReplyLog để theo dõi lịch sử lâu dài
            db_status = (
                "SENT"
                if status_result == "ADDED"
                else ("DRY_RUN" if status_result == "DRY_RUN" else status_result)
            )
            try:
                log_row = BotAutoReplyLog(
                    conversation_id=f"addfriend_{page_name}_{phone}",
                    customer_id=phone,
                    page_id=page_name,
                    case_id=case_id,
                    customer_message=f"Tên: {name or 'N/A'} | Nguồn: {source or 'N/A'} | Nhu cầu: {nhu_cau or 'N/A'} | Tags: {', '.join(tags)}",
                    reply_message=friend_msg,
                    sent_at=get_vn_now(),
                    status=db_status,
                    error_message=detail_msg if status_result != "ADDED" else detail_msg,
                )
                db.add(log_row)
                db.commit()
            except Exception as db_err:
                db.rollback()
                logger.warning(f"Không thể ghi log add_friend vào DB: {db_err}")

            # Cập nhật bộ đếm tiến trình
            with _ADD_FRIEND_LOCK:
                task = _ADD_FRIEND_TASKS.get(task_id)
                if task:
                    task["processed"] += 1
                    if status_result in ("ADDED", "DRY_RUN"):
                        task["added_count"] += 1
                        consecutive_errors = 0
                    elif status_result == "NOT_FOUND":
                        task["not_found_count"] += 1
                        consecutive_errors = 0
                    else:
                        task["failed_count"] += 1
                        consecutive_errors += 1

                    task["logs"].insert(
                        0,
                        {
                            "index": idx,
                            "phone": phone,
                            "name": name or "Khách hàng",
                            "source": source or "-",
                            "nhu_cau": nhu_cau or "-",
                            "page_name": page_name,
                            "message": friend_msg,
                            "note": note_text if add_note else "",
                            "tags": tags,
                            "status": status_result,
                            "detail": detail_msg,
                            "attempts": attempts_used,
                            "time": get_vn_now().strftime("%H:%M:%S"),
                        },
                    )

            # Kiểm tra Circuit Breaker (Ngắt khẩn cấp khi Pancake 502/504, hết hạn token, hoặc lỗi liên tiếp)
            if status_result in ("SERVER_ERROR", "AUTH_EXPIRED"):
                with _ADD_FRIEND_LOCK:
                    task = _ADD_FRIEND_TASKS.get(task_id)
                    if task:
                        task["is_running"] = False
                        task["current_action"] = (
                            f"🛑 Đã tự động dừng khẩn cấp (Circuit Breaker): {detail_msg}"
                        )
                break

            if consecutive_errors >= max_consecutive_errors:
                with _ADD_FRIEND_LOCK:
                    task = _ADD_FRIEND_TASKS.get(task_id)
                    if task:
                        task["is_running"] = False
                        task["current_action"] = (
                            f"🛑 Tự động ngắt bảo vệ tài khoản do gặp {consecutive_errors} lỗi liên tiếp."
                        )
                break

            # Nghỉ chống chặn Rate Limit nếu chưa phải SĐT cuối cùng
            if idx < len(target_items) and not dry_run:
                if batch_size > 0 and (idx % batch_size == 0) and batch_pause_sec > 0:
                    with _ADD_FRIEND_LOCK:
                        task = _ADD_FRIEND_TASKS.get(task_id)
                        if task:
                            task["current_action"] = (
                                f"⏳ Đã chạy xong chặng {idx} số. Đang nghỉ giải lao {int(batch_pause_sec)}s "
                                f"để chống Zalo chặn tìm kiếm SĐT..."
                            )
                    # Chia nhỏ sleep để có thể bấm nút Dừng ngay lập tức
                    slept = 0.0
                    while slept < batch_pause_sec:
                        with _ADD_FRIEND_LOCK:
                            t_check = _ADD_FRIEND_TASKS.get(task_id)
                            if not t_check or not t_check.get("is_running"):
                                break
                        time.sleep(min(1.0, batch_pause_sec - slept))
                        slept += 1.0
                else:
                    jitter_wait = round(random.uniform(delay_min, delay_max), 1)
                    with _ADD_FRIEND_LOCK:
                        task = _ADD_FRIEND_TASKS.get(task_id)
                        if task:
                            task["current_action"] = (
                                f"⏳ Đang nghỉ ngẫu nhiên {jitter_wait}s trước khi kết bạn SĐT tiếp theo..."
                            )
                    slept = 0.0
                    while slept < jitter_wait:
                        with _ADD_FRIEND_LOCK:
                            t_check = _ADD_FRIEND_TASKS.get(task_id)
                            if not t_check or not t_check.get("is_running"):
                                break
                        time.sleep(min(0.5, jitter_wait - slept))
                        slept += 0.5

        with _ADD_FRIEND_LOCK:
            task = _ADD_FRIEND_TASKS.get(task_id)
            if task:
                task["is_running"] = False
                task["finished_at"] = get_vn_now().strftime("%Y-%m-%d %H:%M:%S")
                if not str(task.get("current_action", "")).startswith("🛑"):
                    task["current_action"] = (
                        f"✅ Hoàn tất chiến dịch! Đã xử lý {task['processed']}/{task['total']} số "
                        f"(Thành công: {task['added_count']}, Không tìm thấy Zalo: {task['not_found_count']}, Lỗi: {task['failed_count']})."
                    )

    finally:
        try:
            if context:
                context.close()
        except Exception:
            pass
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        try:
            if playwright_ctx:
                playwright_ctx.stop()
        except Exception:
            pass
        db.close()


# ==============================================================================
# 7. API ENDPOINTS (`/api/add-friend/...`)
# ==============================================================================

@router.get("/config")
def get_add_friend_config(db: Session = Depends(get_db)):
    """
    Trả về toàn bộ cấu hình khởi tạo cho trang Kết Bạn Tự Động:
    - Danh sách các Page Zalo trên Pancake (`pages`)
    - Bộ mẫu tin nhắn chào theo nguồn từ `bot.py` (`templates`)
    - Danh sách thẻ Tag gợi ý + các Tag thực tế từ DB (`tags`)
    - Danh sách nguồn mặc định bỏ qua (`skip_sources`)
    - Trạng thái cấu hình phiên đăng nhập `pancake_state.json` (`state_info`)
    """
    # Lấy thêm các tag thực tế đang có trong DB để gợi ý đầy đủ
    db_tags_set = set(DEFAULT_AVAILABLE_TAGS)
    try:
        rows = (
            db.query(FactLeadActivity.status_tag)
            .filter(FactLeadActivity.status_tag.isnot(None), FactLeadActivity.status_tag != "")
            .distinct()
            .limit(200)
            .all()
        )
        for (raw_tag,) in rows:
            for part in str(raw_tag).split(","):
                t = part.strip()
                if t and len(t) <= 35:
                    db_tags_set.add(t)
    except Exception:
        pass

    # Đưa các tag quan trọng trong bot.py lên đầu
    priority_tags = ["Web", "Đào tạo", "Lead Other", "Đã add", "Đang tư vấn", "Xin file", "Tham gia nhóm"]
    other_tags = sorted([t for t in db_tags_set if t not in priority_tags])
    all_tags = priority_tags + other_tags

    templates_list = [
        {
            "key": k,
            "label": v["label"],
            "source_key": v["source_key"],
            "message": v["message"],
        }
        for k, v in BOT_MESSAGE_TEMPLATES.items()
    ]

    import importlib.util
    return {
        "pages": DEFAULT_ZALO_PAGES,
        "templates": templates_list,
        "tags": all_tags,
        "skip_sources": DEFAULT_SKIP_SOURCES,
        "state_info": get_pancake_state_info(db),
        "playwright_installed": importlib.util.find_spec("playwright") is not None,
        "build_version": "v3_low_mem",
    }


@router.get("/state")
def get_pancake_state(db: Session = Depends(get_db)):
    """Lấy thông tin và nội dung phiên đăng nhập pancake_state.json lưu trong bảng app_configs."""
    raw_val, updated_at, found_key = load_pancake_state_from_db(db)
    info = get_pancake_state_info(db)
    return {
        "status": "OK",
        "state_info": info,
        "has_state": bool(raw_val),
        "storage_key": found_key,
        "state_json": raw_val,
    }


@router.post("/state")
def save_pancake_state(req: SavePancakeStateRequest, db: Session = Depends(get_db)):
    """
    Lưu bền vững nội dung `pancake_state.json` (Playwright storage_state) vào bảng `app_configs`
    trong Neon DB và đồng bộ đồng thời ra file `pancake_state.json` trên đĩa.
    """
    ok, msg, info = save_pancake_state_to_db(req.state_json, db)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    return {
        "status": "OK",
        "message": msg,
        "state_info": info,
    }


@router.delete("/state")
def delete_pancake_state(db: Session = Depends(get_db)):
    """Xóa phiên đăng nhập Pancake khỏi bảng app_configs và xóa file trên đĩa."""
    ok, msg = delete_pancake_state_from_db(db)
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {
        "status": "OK",
        "message": msg,
        "state_info": get_pancake_state_info(db),
    }


@router.post("/parse-phones", response_model=ParsePhonesResponse)
def parse_bulk_phones(req: ParsePhonesRequest, db: Session = Depends(get_db)):
    """
    Phân tích, làm sạch và chuẩn hóa hàng loạt số điện thoại người dùng dán vào:
    - Tự động đổi `84...` -> `0...` và khôi phục số `0` đầu bị mất khi copy từ Excel.
    - Hỗ trợ cả định dạng 1 cột SĐT hoặc nhiều cột `SĐT | Tên | Nguồn | Nhu cầu` từ Google Sheet.
    - Kiểm tra trùng lặp, kiểm tra nguồn loại trừ (`skip_sources`), và đối chiếu lịch sử đã kết bạn.
    - Render sẵn lời mời kết bạn và ghi chú cho từng dòng để người dùng kiểm tra trước khi chạy.
    """
    lines = [ln.strip() for ln in (req.raw_text or "").splitlines() if ln.strip()]
    skip_set = {s.strip().lower() for s in (req.skip_sources or []) if s.strip()}
    already_added_set = _get_already_added_phones(db) if req.exclude_already_added else set()

    seen_phones = set()
    items: List[PhoneImportItem] = []

    valid_count = 0
    invalid_count = 0
    duplicate_count = 0
    skipped_source_count = 0
    already_added_count = 0
    ready_count = 0

    for idx, line in enumerate(lines):
        # Bỏ qua dòng tiêu đề (Header) nếu người dùng copy cả dòng đầu từ Excel/Google Sheet
        lower_line = line.lower()
        if idx == 0 and any(h in lower_line for h in ("sđt", "sdt", "số điện thoại", "phone", "họ tên")):
            digits_in_header = "".join(filter(str.isdigit, line))
            if len(digits_in_header) < 8:
                continue

        raw_phone, name, source, nhu_cau = _extract_columns_from_line(line)
        clean_phone, is_valid, val_note = normalize_vn_phone(raw_phone)

        is_dup = False
        if is_valid:
            if clean_phone in seen_phones:
                is_dup = True
                duplicate_count += 1
            else:
                seen_phones.add(clean_phone)
                valid_count += 1
        else:
            invalid_count += 1

        is_skipped_src = bool(source and source.strip().lower() in skip_set)
        if is_skipped_src:
            skipped_source_count += 1

        is_already_added = bool(is_valid and clean_phone in already_added_set)
        if is_already_added:
            already_added_count += 1

        is_ready = is_valid and not is_dup and not is_skipped_src and not is_already_added
        if is_ready:
            ready_count += 1

        rendered_msg = render_add_friend_message(
            template_str=req.message_template,
            page_name=req.page_name,
            phone=clean_phone or raw_phone,
            name=name,
            source=source,
            nhu_cau=nhu_cau,
            use_source_template=req.use_source_template,
            enable_spintax=req.enable_spintax,
        )
        rendered_note = render_customer_note(
            note_template=req.note_template,
            name=name,
            source=source,
            nhu_cau=nhu_cau,
            page_name=req.page_name,
        )

        items.append(
            PhoneImportItem(
                raw_phone=raw_phone,
                phone=clean_phone or raw_phone,
                is_valid=is_valid,
                validation_note=val_note,
                name=name,
                source=source,
                nhu_cau=nhu_cau,
                is_duplicate=is_dup,
                is_skipped_source=is_skipped_src,
                already_added=is_already_added,
                rendered_message=rendered_msg,
                rendered_note=rendered_note,
            )
        )

    return ParsePhonesResponse(
        total_lines=len(items),
        valid_count=valid_count,
        invalid_count=invalid_count,
        duplicate_count=duplicate_count,
        skipped_source_count=skipped_source_count,
        already_added_count=already_added_count,
        ready_count=ready_count,
        items=items,
    )


@router.get("/leads-phones")
def get_leads_with_phones(
    source_channel: str = Query("all", description="all | tiktok | facebook"),
    limit: int = Query(50, ge=1, le=300),
    db: Session = Depends(get_db),
):
    """
    Lấy nhanh danh sách khách hàng có để lại SĐT từ các kênh nguồn (TikTok, Facebook...)
    trong Database để người dùng có thể bấm 1 nút nạp thẳng vào ô Import SĐT kết bạn Zalo.
    """
    already_added = _get_already_added_phones(db)

    query = db.query(DimLead).filter(
        DimLead.phone_number.isnot(None),
        DimLead.phone_number != "",
    )
    rows = query.order_by(DimLead.first_created_at.desc()).limit(limit * 3).all()

    result_lines = []
    seen = set()
    for lead in rows:
        clean_p, ok, _ = normalize_vn_phone(lead.phone_number)
        if not ok or clean_p in seen or clean_p in already_added:
            continue

        pg_canonical = resolve_canonical_page_name(lead.page_id, fallback=lead.page_id or "")
        is_tt = "tiktok" in pg_canonical.lower() or str(lead.page_id).startswith("tt_")
        if source_channel == "tiktok" and not is_tt:
            continue
        if source_channel == "facebook" and is_tt:
            continue

        seen.add(clean_p)
        clean_name = (lead.name or "").replace("\t", " ").replace("|", " ").strip()
        result_lines.append({
            "phone": clean_p,
            "name": clean_name,
            "source": pg_canonical,
            "nhu_cau": "Tư vấn từ " + ("TikTok" if is_tt else "Fanpage"),
            "line": f"{clean_p}\t{clean_name}\t{pg_canonical}\tTư vấn khóa học",
        })
        if len(result_lines) >= limit:
            break

    return {
        "count": len(result_lines),
        "items": result_lines,
        "formatted_text": "\n".join(item["line"] for item in result_lines),
    }


@router.post("/start")
def start_add_friend_campaign(req: StartAddFriendRequest):
    """Khởi chạy chiến dịch Kết bạn tự động trong nền (hỗ trợ cả Dry-Run và Chạy thật)."""
    if not req.items:
        raise HTTPException(status_code=400, detail="Danh sách số điện thoại cần kết bạn đang trống.")
    if not req.page_name or not req.page_name.strip():
        raise HTTPException(status_code=400, detail="Vui lòng chọn Page Zalo thực hiện kết bạn.")

    if not req.dry_run:
        state_file = ensure_pancake_state_file()
        if not state_file:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Chưa có phiên đăng nhập Pancake (pancake_state.json)! "
                    "Vui lòng bấm nút 'Cấu hình Phiên Pancake' để dán JSON phiên đăng nhập hoặc bật chế độ Chạy thử (Dry-Run)."
                ),
            )

    task_id = f"addfr_{int(time.time())}_{random.randint(100, 999)}"
    daily_cap = max(1, req.rate_limit.daily_limit)
    total_targets = min(len(req.items), daily_cap)

    task_state = {
        "task_id": task_id,
        "campaign_name": req.campaign_name.strip(),
        "page_name": req.page_name.strip(),
        "is_running": True,
        "dry_run": req.dry_run,
        "total": total_targets,
        "processed": 0,
        "added_count": 0,
        "not_found_count": 0,
        "failed_count": 0,
        "current_phone": "",
        "current_action": "Đang khởi tạo chiến dịch kết bạn tự động...",
        "started_at": get_vn_now().strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": None,
        "logs": [],
    }

    with _ADD_FRIEND_LOCK:
        _ADD_FRIEND_TASKS[task_id] = task_state

    req_dict = req.dict() if hasattr(req, "dict") else req.model_dump()
    worker = threading.Thread(
        target=_run_add_friend_worker,
        args=(task_id, req_dict),
        daemon=True,
    )
    worker.start()

    return {
        "status": "STARTED",
        "task_id": task_id,
        "campaign_name": req.campaign_name,
        "total": total_targets,
    }


@router.get("/status/{task_id}")
def get_add_friend_status(task_id: str):
    """Lấy tiến độ thời gian thực của chiến dịch kết bạn tự động."""
    with _ADD_FRIEND_LOCK:
        task = _ADD_FRIEND_TASKS.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Không tìm thấy tiến trình kết bạn này.")
        return task


@router.post("/stop/{task_id}")
def stop_add_friend_campaign(task_id: str):
    """Dừng khẩn cấp chiến dịch kết bạn đang chạy."""
    with _ADD_FRIEND_LOCK:
        task = _ADD_FRIEND_TASKS.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Không tìm thấy tiến trình kết bạn.")
        task["is_running"] = False
        task["current_action"] = "🛑 Đang dừng chiến dịch theo yêu cầu người dùng..."
    return {"status": "STOPPING", "task_id": task_id}


@router.get("/history")
def get_add_friend_history(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Lấy lịch sử các lượt kết bạn tự động đã thực hiện."""
    rows = (
        db.query(BotAutoReplyLog)
        .filter(BotAutoReplyLog.case_id.like("addfriend_%"))
        .order_by(desc(BotAutoReplyLog.sent_at))
        .limit(limit)
        .all()
    )

    items = []
    for r in rows:
        items.append({
            "id": r.id,
            "campaign_name": (r.case_id or "").replace("addfriend_", "", 1),
            "phone": r.customer_id or "",
            "page_name": r.page_id or "",
            "customer_info": r.customer_message or "",
            "message": r.reply_message or "",
            "status": r.status or "",
            "detail": r.error_message or "",
            "sent_at": r.sent_at.strftime("%Y-%m-%d %H:%M:%S") if r.sent_at else "",
        })

    return {"items": items}
