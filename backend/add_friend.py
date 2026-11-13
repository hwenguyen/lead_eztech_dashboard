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
from sqlalchemy import desc, func, or_

from database.db import get_db, SessionLocal
from database.models import DimLead, FactLeadActivity, BotAutoReplyLog, AppConfig
from database.deal_sync import normalize_sale_name
from etl.utils import (
    VN_TZ,
    ZALO_PAGE_NAMES,
    KNOWN_PAGE_NAMES,
    resolve_canonical_page_name,
    is_zalo_channel,
    resolve_api_page_id,
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
_LATEST_TASK_ID: Optional[str] = None


def _serialize_task_snapshot(task: Dict[str, Any]) -> Dict[str, Any]:
    return {**task, "logs": list(task.get("logs") or [])}

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
    """Lấy tập hợp các SĐT đã từng được kết bạn/xử lý thành công trong bảng bot_auto_replies."""
    try:
        rows = (
            db.query(BotAutoReplyLog.customer_id, BotAutoReplyLog.conversation_id)
            .filter(
                BotAutoReplyLog.case_id.like("addfriend_%"),
                BotAutoReplyLog.status.in_(["SENT", "ADDED", "ALREADY_FRIEND", "PARTIAL"]),
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

import requests as http_requests

ZALO_PAGE_IDS_MAP = {
    "Eztech Consultant": "pzl_764881945463506349",
    "Eztech Phân Tích Dữ Liệu": "pzl_629476615535063343",
    "Hiền Minh Eztech": "pzl_131986891507252646",
    "Tuấn Anh Data": "pzl_788602135347404973",
    "Ann": "pzl_1800700961123909439",
}

_PAGE_TAGS_CACHE: Dict[str, Any] = {"ts": 0.0, "pages": None, "tags_by_page": None}


def _has_added_tag(raw_tags: Optional[str]) -> bool:
    if not raw_tags:
        return False
    low = str(raw_tags).lower()
    return ("đã add" in low) or ("da add" in low)


def _fetch_pancake_pages_and_tags(
    db: Session, force_refresh: bool = False
) -> Tuple[List[Dict[str, str]], Dict[str, List[str]]]:
    """Lấy danh sách Page Zalo và thẻ Tag hiện có của từng Page Zalo từ Pancake (kèm cache 5 phút)."""
    now_ts = time.time()
    if (
        not force_refresh
        and _PAGE_TAGS_CACHE["tags_by_page"] is not None
        and (now_ts - float(_PAGE_TAGS_CACHE["ts"])) < 300.0
    ):
        return _PAGE_TAGS_CACHE["pages"], _PAGE_TAGS_CACHE["tags_by_page"]

    pages_list = [dict(p) for p in DEFAULT_ZALO_PAGES]
    known_names_lower = {p["name"].lower() for p in pages_list}
    tags_by_page: Dict[str, List[str]] = {p["name"]: [] for p in pages_list}

    state_path = ensure_pancake_state_file()
    if state_path and os.path.exists(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                st = json.load(f)
            cookies = [
                f"{c['name']}={c['value']}"
                for c in (st.get("cookies") or [])
                if c.get("domain") in (".pancake.vn", "pancake.vn") and c.get("name") and c.get("value") is not None
            ]
            if cookies:
                s = http_requests.Session()
                s.headers.update({
                    "Cookie": "; ".join(cookies),
                    "Referer": "https://pancake.vn/",
                    "Accept": "application/json",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                    ),
                })
                rp = s.get(
                    "https://pancake.vn/api/v1/pages?version=v1&include_inactivated=false",
                    timeout=12,
                )
                if rp.status_code == 200:
                    acts = ((rp.json().get("categorized") or {}).get("activated")) or rp.json().get("data") or []
                    for p in acts:
                        if not isinstance(p, dict):
                            continue
                        pid = str(p.get("id") or "").strip()
                        pname = str(p.get("name") or "").strip()
                        if not pid.startswith("pzl_") or not pname:
                            continue
                        ZALO_PAGE_IDS_MAP[pname] = pid
                        if pname.lower() not in known_names_lower:
                            known_names_lower.add(pname.lower())
                            pages_list.append({"id": pname, "name": pname, "badge": "Zalo Personal"})
                            tags_by_page.setdefault(pname, [])

                        try:
                            rs = s.get(
                                f"https://pancake.vn/api/v1/pages/{pid}/settings?separate_pos=true&separate_qr=true",
                                timeout=10,
                            )
                            if rs.status_code == 200:
                                raw_tags = ((rs.json().get("settings") or {}).get("tags")) or []
                                page_tags: List[str] = []
                                seen_t = set()
                                for t in raw_tags:
                                    if isinstance(t, dict) and t.get("text"):
                                        txt = str(t["text"]).strip()
                                        if txt and txt.lower() not in seen_t:
                                            seen_t.add(txt.lower())
                                            page_tags.append(txt)
                                tags_by_page[pname] = page_tags
                        except Exception as tag_err:
                            logger.warning(f"Không tải được tag từ Pancake cho Page {pname}: {tag_err}")
        except Exception as err:
            logger.warning(f"Không tải được danh sách Page/Tag từ Pancake: {err}")

    # Bổ sung fallback từ DB nếu Page chưa lấy được tag từ Pancake (vd chưa cài pancake_state)
    empty_pages = [pname for pname, tlist in tags_by_page.items() if not tlist]
    if empty_pages:
        try:
            rows = (
                db.query(DimLead.page_id, FactLeadActivity.conversation_id, FactLeadActivity.status_tag)
                .join(FactLeadActivity, FactLeadActivity.lead_id == DimLead.id)
                .filter(
                    FactLeadActivity.status_tag.isnot(None),
                    FactLeadActivity.status_tag != "",
                    ~FactLeadActivity.conversation_id.like("pzl_g_%"),
                )
                .distinct()
                .limit(500)
                .all()
            )
            db_map: Dict[str, List[str]] = {}
            for pg, conv_id, raw_tag in rows:
                if not is_zalo_channel(pg, conv_id):
                    continue
                canon = resolve_canonical_page_name(pg, fallback=str(pg or ""))
                if not canon:
                    continue
                bucket = db_map.setdefault(canon, [])
                for part in str(raw_tag).split(","):
                    t = part.strip()
                    if t and len(t) <= 35 and t not in bucket:
                        bucket.append(t)
            for pname in empty_pages:
                for k, v in db_map.items():
                    if k.lower() == pname.lower() and v:
                        tags_by_page[pname] = sorted(v)
                        break
        except Exception:
            pass

    _PAGE_TAGS_CACHE["ts"] = now_ts
    _PAGE_TAGS_CACHE["pages"] = pages_list
    _PAGE_TAGS_CACHE["tags_by_page"] = tags_by_page
    return pages_list, tags_by_page


def _init_pancake_http_context(state_path: str, target_dashboard: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Khởi tạo phiên HTTP trực tiếp tới Pancake từ `pancake_state.json` (tốn <1MB RAM,
    thay thế hoàn toàn việc bật trình duyệt Chromium nặng 350MB trên Render 512MB).
    """
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            st = json.load(f)
        cookies = [
            f"{c['name']}={c['value']}"
            for c in (st.get("cookies") or [])
            if c.get("domain") in (".pancake.vn", "pancake.vn") and c.get("name") and c.get("value") is not None
        ]
        if not cookies:
            return None, "File pancake_state.json không chứa cookie đăng nhập pancake.vn!"

        session = http_requests.Session()
        session.headers.update({
            "Cookie": "; ".join(cookies),
            "Referer": "https://pancake.vn/",
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        })

        r_pages = session.get(
            "https://pancake.vn/api/v1/pages?version=v1&include_inactivated=false",
            timeout=20,
        )
        if r_pages.status_code in (502, 504):
            return None, f"Pancake đang bị lỗi máy chủ ({r_pages.status_code} Bad Gateway)"
        p_data = r_pages.json()
        if r_pages.status_code == 401 or p_data.get("error_code") == 102 or p_data.get("success") is False:
            return None, "Phiên đăng nhập Pancake (pancake_state.json) đã hết hạn!"

        activated = (p_data.get("categorized") or {}).get("activated") or p_data.get("data") or []
        page_id = None
        target_lower = target_dashboard.strip().lower()
        for p in activated:
            if not isinstance(p, dict):
                continue
            pname = str(p.get("name") or "").strip().lower()
            pid = str(p.get("id") or "").strip()
            if (pname == target_lower or pid.lower() == target_lower) and pid.startswith("pzl_"):
                page_id = pid
                break
        if not page_id:
            for p in activated:
                if isinstance(p, dict) and str(p.get("name") or "").strip().lower() == target_lower:
                    page_id = str(p.get("id") or "").strip()
                    break
        if not page_id:
            page_id = ZALO_PAGE_IDS_MAP.get(target_dashboard)
        if not page_id:
            return None, f"Không tìm thấy Page '{target_dashboard}' trong tài khoản Pancake!"

        tags_map: Dict[str, Dict[str, Any]] = {}
        try:
            r_set = session.get(
                f"https://pancake.vn/api/v1/pages/{page_id}/settings?separate_pos=true&separate_qr=true",
                timeout=15,
            )
            if r_set.status_code == 200:
                raw_tags = ((r_set.json().get("settings") or {}).get("tags")) or []
                for t in raw_tags:
                    if isinstance(t, dict) and t.get("text"):
                        tags_map[str(t["text"]).strip().lower()] = t
        except Exception as e:
            logger.warning(f"Không tải được danh sách tag cho Page {page_id}: {e}")

        return {"session": session, "page_id": page_id, "tags_map": tags_map}, ""
    except Exception as e:
        return None, f"Lỗi khởi tạo phiên Pancake: {str(e)[:200]}"


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
    Thực thi quy trình kết bạn Zalo trên Pancake cho 1 số điện thoại thông qua
    Pancake Web API (`session` từ `pancake_state.json`), giữ nguyên 100% nghiệp vụ:
    Tra cứu SĐT -> Gửi kết bạn -> Lưu ghi chú -> Nhắn tin hộp thoại -> Gắn thẻ Tag.
    """
    try:
        session: http_requests.Session = page["session"]
        page_id: str = page["page_id"]
        tags_map: Dict[str, Dict[str, Any]] = page.get("tags_map") or {}

        intl_phone = "+84" + phone[1:] if phone.startswith("0") else (phone if phone.startswith("+") else "+" + phone)

        if step_cb:
            step_cb(f"Đang tra cứu Zalo SĐT {phone}...")

        # Bước 1: Tìm tài khoản Zalo theo SĐT
        r_search = session.get(
            f"https://pancake.vn/api/v1/personal_zalo/{page_id}/search_zalo_users",
            params={"phone_number": intl_phone},
            timeout=20,
        )
        if r_search.status_code in (502, 504):
            return "SERVER_ERROR", f"Pancake trả về lỗi máy chủ: {r_search.status_code}"

        s_data = r_search.json()
        if r_search.status_code == 401 or s_data.get("error_code") == 102:
            return "AUTH_EXPIRED", "Phiên đăng nhập Pancake (pancake_state.json) đã hết hạn!"

        if s_data.get("success") is False:
            err_msg = str(s_data.get("message") or "Không tìm thấy tài khoản Zalo")
            if "không tìm thấy" in err_msg.lower() or "not found" in err_msg.lower():
                return "NOT_FOUND", f"Zalo báo không tìm thấy SĐT {phone}"
            return "FAILED", f"Zalo báo: {err_msg}"

        users = s_data.get("users") or []
        if not users:
            return "NOT_FOUND", f"Zalo báo không tìm thấy SĐT {phone}"

        user = users[0]
        uid = str(user.get("uid") or "").strip()
        if not uid:
            return "NOT_FOUND", f"Không tìm thấy Zalo UID cho SĐT {phone}"

        zalo_display = user.get("display_name") or user.get("zalo_name") or phone

        # Bước 2: Kiểm tra hội thoại & trạng thái bạn bè trên Pancake
        raw_page_num = page_id.replace("pzl_", "")
        conv_id = f"pzl_u_{raw_page_num}_{uid}"
        r_conv = session.get(
            f"https://pancake.vn/api/v1/pages/{page_id}/conversations/{conv_id}",
            params={"personal_zalo_check_conv_existed": "true"},
            timeout=20,
        )
        conv_data = r_conv.json() if r_conv.status_code == 200 else {}
        from_obj = conv_data.get("from") or {}
        is_already_friend = (from_obj.get("is_stranger") is False) and bool(from_obj.get("id"))

        # Bước 3: Gửi lời mời kết bạn (nếu chưa là bạn bè)
        if not is_already_friend:
            if step_cb:
                step_cb(f"Đang gửi lời mời kết bạn tới {zalo_display} ({phone})...")
            biz = user.get("bizPkg") or {}
            biz_label = biz.get("label") or {}
            form_fields = [
                ("user_id", uid),
                ("friend[avatar]", str(user.get("avatar") or "")),
                ("friend[bizPkg][label][EN]", str(biz_label.get("EN") or "")),
                ("friend[bizPkg][label][VI]", str(biz_label.get("VI") or "")),
                ("friend[bizPkg][label][bg_color]", str(biz_label.get("bg_color") or "")),
                ("friend[bizPkg][label][title_color]", str(biz_label.get("title_color") or "")),
                ("friend[bizPkg][pkgId]", str(biz.get("pkgId") if biz.get("pkgId") is not None else 0)),
                ("friend[cover]", str(user.get("cover") or "")),
                ("friend[display_name]", str(user.get("display_name") or "")),
                ("friend[dob]", str(user.get("dob") if user.get("dob") is not None else 0)),
                ("friend[gender]", str(user.get("gender") if user.get("gender") is not None else 0)),
                ("friend[globalId]", str(user.get("globalId") or "")),
                ("friend[isEnterpriseAccount]", str(user.get("isEnterpriseAccount") if user.get("isEnterpriseAccount") is not None else 0)),
                ("friend[pc_uploaded_avatar]", str(user.get("pc_uploaded_avatar") or "")),
                ("friend[phone_number]", str(user.get("phone_number") or intl_phone)),
                ("friend[sdob]", str(user.get("sdob") or "")),
                ("friend[status]", str(user.get("status") or "")),
                ("friend[uid]", uid),
                ("friend[zalo_name]", str(user.get("zalo_name") or "")),
                ("greeting", friend_request_msg[:150]),
            ]
            r_fr = session.post(
                f"https://pancake.vn/api/v1/personal_zalo/{page_id}/send_request_friend?",
                files=[(k, (None, v)) for k, v in form_fields],
                timeout=20,
            )
            if r_fr.status_code in (502, 504):
                return "SERVER_ERROR", f"Pancake trả về lỗi máy chủ khi gửi kết bạn: {r_fr.status_code}"
            fr_data = r_fr.json() if r_fr.status_code == 200 else {}
            if r_fr.status_code != 200 or fr_data.get("success") is False:
                fr_msg = str(fr_data.get("message") or r_fr.text[:120])
                if "bạn bè" in fr_msg.lower() or "friend" in fr_msg.lower():
                    is_already_friend = True
                    actions_done = [f"Đã là bạn bè sẵn ({zalo_display})"]
                else:
                    return "FAILED", f"Không gửi được kết bạn: {fr_msg}"
            else:
                actions_done = [f"Đã gửi lời mời kết bạn ({zalo_display})"]
        else:
            actions_done = [f"Đã là bạn bè sẵn ({zalo_display})"]

        sub_step_failed = False

        # Bước 4: Lưu ghi chú / Nhắn tin chào / Gắn Tag
        if send_inbox_message or add_note or (tags and len(tags) > 0):
            customers = conv_data.get("customers") or []
            # Nếu hội thoại mới tạo sau khi gửi kết bạn, tải lại để có customer_id và tags mới nhất
            if not is_already_friend and (not customers or add_note or tags):
                try:
                    time.sleep(0.5)
                    r_conv2 = session.get(
                        f"https://pancake.vn/api/v1/pages/{page_id}/conversations/{conv_id}",
                        params={"personal_zalo_check_conv_existed": "true"},
                        timeout=15,
                    )
                    if r_conv2.status_code == 200:
                        conv_data = r_conv2.json() or conv_data
                        customers = conv_data.get("customers") or customers
                except Exception:
                    pass
            customer_id = customers[0].get("id") if (customers and isinstance(customers[0], dict)) else None

            # 4a. Thêm ghi chú khách hàng
            if add_note and note_text and customer_id:
                try:
                    r_note = session.post(
                        f"https://pancake.vn/api/v1/pages/{page_id}/customers/{customer_id}/notes?",
                        files=[
                            ("message", (None, note_text)),
                            ("conversation_id", (None, conv_id)),
                            ("images", (None, "[]")),
                            ("links", (None, "[]")),
                        ],
                        timeout=15,
                    )
                    if r_note.status_code == 200:
                        actions_done.append("đã lưu ghi chú")
                except Exception as note_err:
                    logger.warning(f"[{phone}] Không thể điền ghi chú: {note_err}")

            # 4b. Gửi tin nhắn trực tiếp vào hộp thoại
            if send_inbox_message and inbox_msg:
                try:
                    if step_cb:
                        step_cb(f"Đang gửi tin nhắn chào tới {zalo_display} ({phone})...")
                    r_msg = session.post(
                        f"https://pancake.vn/api/v1/pages/{page_id}/conversations/{conv_id}/messages?",
                        files=[
                            ("action", (None, "reply_inbox")),
                            ("message", (None, inbox_msg)),
                            ("send_by_platform", (None, "web")),
                        ],
                        timeout=20,
                    )
                    msg_json = {}
                    try:
                        msg_json = r_msg.json()
                    except Exception:
                        pass
                    if r_msg.status_code == 200 and msg_json.get("success") is not False:
                        actions_done.append("đã nhắn tin chào")
                    else:
                        err_reason = str(msg_json.get("message") or f"HTTP {r_msg.status_code}")[:100]
                        logger.warning(f"[{phone}] Gửi tin nhắn chào thất bại: {err_reason}")
                        actions_done.append(f"lỗi nhắn tin ({err_reason})")
                        sub_step_failed = True
                except Exception as chat_err:
                    logger.warning(f"[{phone}] Không thể gửi tin nhắn hộp thoại: {chat_err}")
                    actions_done.append(f"lỗi nhắn tin ({str(chat_err)[:80]})")
                    sub_step_failed = True

            # 4c. Gắn thẻ Tag (khớp với tag hiện có trên Page Zalo đã chọn)
            if tags:
                existing_tag_ids = {
                    str(t.get("id") if isinstance(t, dict) else t)
                    for t in (conv_data.get("tags") or [])
                }
                norm_tags_map = {re.sub(r"\s+", " ", k).strip(): v for k, v in tags_map.items()}
                attached_tags = []
                failed_tags = []
                for tag_name in tags:
                    t_clean = (tag_name or "").strip()
                    if not t_clean:
                        continue
                    t_low = t_clean.lower()
                    t_obj = tags_map.get(t_low) or norm_tags_map.get(re.sub(r"\s+", " ", t_low))
                    if not t_obj:
                        failed_tags.append(f"{t_clean} (không có trên Page)")
                        continue
                    tid_str = str(t_obj.get("id"))
                    try:
                        if tid_str not in existing_tag_ids:
                            r_tag = session.post(
                                f"https://pancake.vn/api/v1/pages/{page_id}/conversations/{conv_id}/toggle_tag?",
                                files=[
                                    ("tag_id", (None, tid_str)),
                                    ("value", (None, "1")),
                                    ("psid", (None, "undefined")),
                                    ("tag[color]", (None, str(t_obj.get("color") or ""))),
                                    ("tag[id]", (None, tid_str)),
                                    ("tag[is_lead_event]", (None, str(t_obj.get("is_lead_event", False)).lower())),
                                    ("tag[lighten_color]", (None, str(t_obj.get("lighten_color") or ""))),
                                    ("tag[text]", (None, str(t_obj.get("text") or t_clean))),
                                ],
                                timeout=15,
                            )
                            tag_ok = r_tag.status_code == 200
                            if tag_ok:
                                try:
                                    tag_ok = r_tag.json().get("success") is not False
                                except Exception:
                                    pass
                            if not tag_ok:
                                failed_tags.append(f"{t_clean} (HTTP {r_tag.status_code})")
                                continue
                        attached_tags.append(t_clean)
                    except Exception as tag_err:
                        logger.warning(f"[{phone}] Không gắn được tag '{t_clean}': {tag_err}")
                        failed_tags.append(t_clean)
                if attached_tags:
                    actions_done.append(f"gắn tag [{', '.join(attached_tags)}]")
                if failed_tags:
                    actions_done.append(f"lỗi tag [{', '.join(failed_tags)}]")
                    sub_step_failed = True

        if sub_step_failed:
            return "PARTIAL", ", ".join(actions_done)
        return ("ALREADY_FRIEND" if is_already_friend else "ADDED"), ", ".join(actions_done)

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
        # Nếu chạy thật (Live mode), khởi tạo phiên HTTP trực tiếp tới Pancake từ pancake_state.json
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

            with _ADD_FRIEND_LOCK:
                task = _ADD_FRIEND_TASKS.get(task_id)
                if task:
                    task["current_action"] = f"⏳ Đang kết nối phiên Pancake cho Page '{page_name}'..."

            pw_page, init_err = _init_pancake_http_context(state_path, page_name)
            if not pw_page:
                with _ADD_FRIEND_LOCK:
                    task = _ADD_FRIEND_TASKS.get(task_id)
                    if task:
                        task["is_running"] = False
                        task["current_action"] = f"🛑 Dừng: {init_err}"
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

                    if status_code in (
                        "ADDED",
                        "ALREADY_FRIEND",
                        "PARTIAL",
                        "NOT_FOUND",
                        "SERVER_ERROR",
                        "AUTH_EXPIRED",
                    ):
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
                if status_result in ("ADDED", "ALREADY_FRIEND")
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
                    error_message=detail_msg,
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
                    elif status_result == "ALREADY_FRIEND":
                        task["already_friend_count"] = task.get("already_friend_count", 0) + 1
                        consecutive_errors = 0
                    elif status_result == "PARTIAL":
                        task["partial_count"] = task.get("partial_count", 0) + 1
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
                    summary_parts = [f"Gửi kết bạn: {task['added_count']}"]
                    if task.get("already_friend_count", 0) > 0:
                        summary_parts.append(f"Đã là bạn: {task['already_friend_count']}")
                    if task.get("partial_count", 0) > 0:
                        summary_parts.append(f"Thiếu bước: {task['partial_count']}")
                    summary_parts.append(f"Không có Zalo: {task['not_found_count']}")
                    summary_parts.append(f"Lỗi: {task['failed_count']}")
                    task["current_action"] = (
                        f"✅ Hoàn tất chiến dịch! Đã xử lý {task['processed']}/{task['total']} số "
                        f"({', '.join(summary_parts)})."
                    )

    finally:
        try:
            if pw_page and isinstance(pw_page, dict) and pw_page.get("session"):
                pw_page["session"].close()
        except Exception:
            pass
        db.close()


# ==============================================================================
# 7. API ENDPOINTS (`/api/add-friend/...`)
# ==============================================================================

@router.get("/config")
def get_add_friend_config(refresh_tags: bool = Query(False), db: Session = Depends(get_db)):
    """
    Trả về toàn bộ cấu hình khởi tạo cho trang Kết Bạn Tự Động:
    - Danh sách các Page Zalo trên Pancake (`pages`)
    - Danh sách Tag thực tế theo từng Page Zalo (`tags_by_page`)
    - Bộ lọc danh sách SĐT từ kho Leads (`lead_filters`: employees, source_pages, lead_tags)
    - Bộ mẫu tin nhắn chào theo nguồn từ `bot.py` (`templates`)
    - Danh sách nguồn mặc định bỏ qua (`skip_sources`)
    - Trạng thái cấu hình phiên đăng nhập `pancake_state.json` (`state_info`)
    """
    pages_list, tags_by_page = _fetch_pancake_pages_and_tags(db, force_refresh=refresh_tags)

    all_tags_set = set()
    for ptags in tags_by_page.values():
        for t in ptags:
            all_tags_set.add(t)
    all_tags = sorted(all_tags_set) if all_tags_set else list(DEFAULT_AVAILABLE_TAGS)

    # Bộ lọc danh sách khách hàng từ DB (Nhân viên, Page Nguồn, Tag)
    employees_set = set()
    lead_tags_set = set()
    source_pages_set = set()
    try:
        emp_rows = (
            db.query(FactLeadActivity.assigned_users)
            .filter(FactLeadActivity.assigned_users.isnot(None), FactLeadActivity.assigned_users != "")
            .distinct()
            .limit(300)
            .all()
        )
        for (raw_emp,) in emp_rows:
            for part in str(raw_emp).split(","):
                name = normalize_sale_name(part.strip())
                if name:
                    employees_set.add(name)

        tag_rows = (
            db.query(FactLeadActivity.status_tag)
            .filter(FactLeadActivity.status_tag.isnot(None), FactLeadActivity.status_tag != "")
            .distinct()
            .limit(300)
            .all()
        )
        for (raw_tag,) in tag_rows:
            for part in str(raw_tag).split(","):
                t = part.strip()
                if t and len(t) <= 50:
                    lead_tags_set.add(t)

        pg_rows = (
            db.query(DimLead.page_id)
            .filter(DimLead.page_id.isnot(None), DimLead.page_id != "", DimLead.phone_number.isnot(None), DimLead.phone_number != "")
            .distinct()
            .limit(200)
            .all()
        )
        for (raw_pg,) in pg_rows:
            canon = resolve_canonical_page_name(raw_pg, fallback=str(raw_pg or ""))
            if canon and not is_zalo_channel(raw_pg):
                source_pages_set.add(canon)
    except Exception as filter_err:
        logger.warning(f"Không lấy được bộ lọc Leads: {filter_err}")

    templates_list = [
        {
            "key": k,
            "label": v["label"],
            "source_key": v["source_key"],
            "message": v["message"],
        }
        for k, v in BOT_MESSAGE_TEMPLATES.items()
    ]

    return {
        "pages": pages_list,
        "templates": templates_list,
        "tags": all_tags,
        "tags_by_page": tags_by_page,
        "lead_filters": {
            "employees": sorted(employees_set),
            "source_pages": sorted(source_pages_set),
            "lead_tags": sorted(lead_tags_set),
        },
        "skip_sources": DEFAULT_SKIP_SOURCES,
        "state_info": get_pancake_state_info(db),
        "playwright_installed": True,
        "build_version": "v6_page_tags_filters",
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
    _PAGE_TAGS_CACHE["ts"] = 0.0

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
    _PAGE_TAGS_CACHE["ts"] = 0.0
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
    employee: Optional[str] = Query(None, description="Lọc theo tên Nhân viên phụ trách"),
    source_page: Optional[str] = Query(None, description="Lọc theo tên Page Nguồn"),
    tag: Optional[str] = Query(None, description="Lọc theo tên Tag (hoặc __no_tag__)"),
    exclude_added_tag: bool = Query(True, description="Loại bỏ các SĐT đã có tag 'Đã add'"),
    exclude_already_added: bool = Query(True, description="Loại bỏ các SĐT đã chạy kết bạn trong hệ thống"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """
    Lấy danh sách khách hàng có SĐT từ Database theo bộ lọc (Nhân viên, Page Nguồn, Tag)
    và tự động loại bỏ SĐT đã có tag 'Đã add' hoặc đã chạy kết bạn trước đó.
    """
    skip_phones = _get_already_added_phones(db) if exclude_already_added else set()
    if exclude_added_tag:
        try:
            tagged_rows = (
                db.query(DimLead.phone_number, FactLeadActivity.status_tag)
                .join(FactLeadActivity, FactLeadActivity.lead_id == DimLead.id)
                .filter(
                    DimLead.phone_number.isnot(None),
                    DimLead.phone_number != "",
                    FactLeadActivity.status_tag.ilike("%add%"),
                )
                .distinct()
                .all()
            )
            for raw_p, raw_tag in tagged_rows:
                if _has_added_tag(raw_tag):
                    cp, ok, _ = normalize_vn_phone(raw_p)
                    if ok and cp:
                        skip_phones.add(cp)
        except Exception as err:
            logger.warning(f"Không kiểm tra được tag 'Đã add' trong DB: {err}")

    emp_filter = normalize_sale_name(employee.strip()) if employee and employee.strip() else ""
    src_filter = source_page.strip().lower() if source_page and source_page.strip() else ""
    tag_filter = tag.strip().lower() if tag and tag.strip() else ""

    query = (
        db.query(
            DimLead.phone_number,
            DimLead.name,
            DimLead.page_id,
            DimLead.first_created_at,
            FactLeadActivity.assigned_users,
            FactLeadActivity.status_tag,
            FactLeadActivity.conversation_id,
        )
        .outerjoin(FactLeadActivity, FactLeadActivity.lead_id == DimLead.id)
        .filter(
            DimLead.phone_number.isnot(None),
            DimLead.phone_number != "",
            or_(
                FactLeadActivity.conversation_id.is_(None),
                ~FactLeadActivity.conversation_id.like("pzl_g_%"),
            ),
        )
    )
    if tag_filter and tag_filter != "__no_tag__":
        query = query.filter(FactLeadActivity.status_tag.ilike(f"%{tag.strip()}%"))

    scan_limit = 4000 if (emp_filter or src_filter or tag_filter) else max(limit * 8, 500)
    rows = query.order_by(DimLead.first_created_at.desc()).limit(scan_limit).all()

    result_lines = []
    seen = set()
    for raw_phone, lead_name, lead_page_id, _created_at, assigned_users, status_tag, _conv_id in rows:
        clean_p, ok, _ = normalize_vn_phone(raw_phone)
        if not ok or clean_p in seen or clean_p in skip_phones:
            continue

        pg_canonical = resolve_canonical_page_name(lead_page_id, fallback=lead_page_id or "")
        is_tt = "tiktok" in pg_canonical.lower() or str(lead_page_id).startswith("tt_")
        if src_filter:
            if pg_canonical.lower() != src_filter:
                continue
        else:
            if source_channel == "tiktok" and not is_tt:
                continue
            if source_channel == "facebook" and is_tt:
                continue

        emp_names = [
            normalize_sale_name(p.strip())
            for p in str(assigned_users or "").split(",")
            if p.strip()
        ]
        if emp_filter:
            if emp_filter.lower() == "__unassigned__":
                if emp_names:
                    continue
            elif not any(en.lower() == emp_filter.lower() for en in emp_names):
                continue

        row_tags = [t.strip() for t in str(status_tag or "").split(",") if t.strip()]
        if tag_filter:
            if tag_filter == "__no_tag__":
                if row_tags:
                    continue
            elif not any(rt.lower() == tag_filter for rt in row_tags):
                continue

        seen.add(clean_p)
        clean_name = (lead_name or "").replace("\t", " ").replace("|", " ").strip()
        emp_label = ", ".join(dict.fromkeys(emp_names)) if emp_names else ""
        nhu_cau_text = "Tư vấn từ " + ("TikTok" if is_tt else "Fanpage")
        result_lines.append({
            "phone": clean_p,
            "name": clean_name,
            "source": pg_canonical,
            "employee": emp_label,
            "tags": row_tags,
            "nhu_cau": nhu_cau_text,
            "line": f"{clean_p}\t{clean_name}\t{pg_canonical}\t{nhu_cau_text}",
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
    global _LATEST_TASK_ID
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
        "already_friend_count": 0,
        "partial_count": 0,
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
        _LATEST_TASK_ID = task_id

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


@router.get("/active")
def get_active_add_friend_task():
    """Trả về tiến trình đang chạy (hoặc vừa hoàn tất gần nhất) để UI tự khôi phục khi đổi tab/refresh."""
    with _ADD_FRIEND_LOCK:
        for t in reversed(list(_ADD_FRIEND_TASKS.values())):
            if t.get("is_running"):
                return {"active": _serialize_task_snapshot(t)}
        if _LATEST_TASK_ID and _LATEST_TASK_ID in _ADD_FRIEND_TASKS:
            return {"active": _serialize_task_snapshot(_ADD_FRIEND_TASKS[_LATEST_TASK_ID])}
        return {"active": None}


@router.get("/status/{task_id}")
def get_add_friend_status(task_id: str):
    """Lấy tiến độ thời gian thực của chiến dịch kết bạn tự động."""
    with _ADD_FRIEND_LOCK:
        task = _ADD_FRIEND_TASKS.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Không tìm thấy tiến trình kết bạn này.")
        return _serialize_task_snapshot(task)


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
