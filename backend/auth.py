"""
================================================================================
HỆ THỐNG XÁC THỰC, QUẢN LÝ NHÂN VIÊN VÀ PHÂN QUYỀN (AUTH & RBAC MODULE)
- Mã hóa mật khẩu chuẩn NIST: Salted PBKDF2-HMAC-SHA256 (100,000 vòng lặp)
- Token chuẩn JWT HS256 độc lập, ký số HMAC-SHA256 chống giả mạo
- Chống tấn công dò mật khẩu (Brute-Force & Rate Limiting)
- Tự động quét & khởi tạo tài khoản nhân viên thực tế từ DB (mật khẩu mặc định "1")
- Quản trị viên (Admin) full quyền, hỗ trợ thêm / sửa phòng ban / reset pass / xóa nhân viên
================================================================================
"""

import os
import re
import time
import json
import base64
import hmac
import hashlib
import secrets
import logging
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import AppUser, AppConfig, FactLeadActivity, DealWin, SalesDeal
from backend.rbac_config import (
    DEPT_ADMIN,
    DEPT_CONSULTANT,
    DEPT_MARKETING,
    DEPT_CLASS_MANAGER,
    VALID_DEPARTMENTS,
    canonicalize_department,
    get_user_permissions,
    has_tab_access,
    strip_vn_accents,
    TAB_DISPLAY_NAMES,
)

logger = logging.getLogger("AuthService")

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

VN_TZ = timezone(timedelta(hours=7))


def get_vn_now():
    return datetime.now(VN_TZ).replace(tzinfo=None)


# Khóa bí mật JWT (Ưu tiên lấy từ biến môi trường JWT_SECRET_KEY)
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "eztech_lead_dashboard_jwt_secret_key_2026_super_secure_salt")
JWT_ALGORITHM = "HS256"
DEFAULT_ACCESS_TOKEN_EXPIRE_HOURS = 24
REMEMBER_ME_EXPIRE_DAYS = 30
DEFAULT_STAFF_PASSWORD = "1"
INITIAL_SEED_CONFIG_KEY = "RBAC_INITIAL_SEED_V1"

# Tài khoản Admin mặc định cấu hình qua env
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "eztech@2026").strip()

# Cache RAM cho danh sách nhân viên trên màn hình Login (0 Neon Egress khi mở trang Login)
_EMP_LIST_LOCK = threading.Lock()
_EMP_LIST_CACHE: Optional[Tuple[float, List[Dict[str, Any]]]] = None
_EMP_LIST_TTL = 600.0  # 10 phút


def invalidate_employees_auth_cache():
    global _EMP_LIST_CACHE
    with _EMP_LIST_LOCK:
        _EMP_LIST_CACHE = None


# ==============================================================================
# 1. BẢO MẬT MẬT KHẨU (PBKDF2-HMAC-SHA256)
# ==============================================================================
def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Băm mật khẩu bằng PBKDF2-HMAC-SHA256 với Salt ngẫu nhiên và 100.000 vòng lặp."""
    if not salt:
        salt = secrets.token_hex(16)

    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000,
    )
    return key.hex(), salt


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """So khớp mật khẩu với hàm constant-time hmac.compare_digest chống timing attack."""
    computed_hash, _ = hash_password(password, salt=salt)
    return hmac.compare_digest(computed_hash, expected_hash)


# ==============================================================================
# 2. XỬ LÝ JWT TOKEN (HMAC-SHA256 CHUẨN)
# ==============================================================================
def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _base64url_decode(s: str) -> bytes:
    padding = "=" * (4 - (len(s) % 4)) if len(s) % 4 != 0 else ""
    return base64.urlsafe_b64decode((s + padding).encode("utf-8"))


def create_jwt_token(payload_data: Dict[str, Any], expires_delta: timedelta) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now_ts = int(time.time())
    exp_ts = now_ts + int(expires_delta.total_seconds())

    payload = dict(payload_data)
    payload["iat"] = now_ts
    payload["exp"] = exp_ts

    header_b64 = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature = hmac.new(JWT_SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _base64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def verify_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        parts = token.strip().split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts

        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        expected_sig = hmac.new(JWT_SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
        actual_sig = _base64url_decode(sig_b64)

        if not hmac.compare_digest(expected_sig, actual_sig):
            logger.warning("Token signature mismatch.")
            return None

        payload = json.loads(_base64url_decode(payload_b64).decode("utf-8"))
        exp = payload.get("exp")
        if not exp or int(time.time()) > int(exp):
            logger.warning("Token expired.")
            return None

        return payload
    except Exception as e:
        logger.debug(f"Lỗi phân giải token: {e}")
        return None


# ==============================================================================
# 3. CHỐNG TẤN CÔNG DÒ MẬT KHẨU (BRUTE-FORCE & RATE LIMITING)
# ==============================================================================
_FAILED_ATTEMPTS: Dict[str, list] = {}


def check_rate_limit_lockout(key: str) -> Tuple[bool, int]:
    now = time.time()
    attempts = [t for t in _FAILED_ATTEMPTS.get(key, []) if now - t < 600]
    _FAILED_ATTEMPTS[key] = attempts

    if len(attempts) >= 8:
        remaining = int(600 - (now - attempts[-1]))
        return True, max(1, remaining)
    return False, 0


def record_failed_attempt(key: str):
    now = time.time()
    attempts = _FAILED_ATTEMPTS.get(key, [])
    attempts.append(now)
    _FAILED_ATTEMPTS[key] = attempts


def clear_failed_attempts(key: str):
    _FAILED_ATTEMPTS.pop(key, None)


# ==============================================================================
# 4. KHỞI TẠO ADMIN & QUÉT TỰ ĐỘNG NHÂN SỰ TỪ DB
# ==============================================================================
_JUNK_EMPLOYEE_TOKENS = {
    "chua phan cong",
    "admin",
    "bo qua",
    "chua dong tien",
    "khong hoc",
    "hoc t7",
    "dong trc",
    "data",
    "unknown",
    "none",
    "null",
    "test",
    "nguyen",
    "tran",
}


def _make_username_slug(full_name: str, existing_usernames: set) -> str:
    base = re.sub(r"[^a-z0-9]+", ".", strip_vn_accents(full_name)).strip(".")
    if not base:
        base = "nv"
    candidate = base
    idx = 2
    while candidate in existing_usernames:
        candidate = f"{base}.{idx}"
        idx += 1
    existing_usernames.add(candidate)
    return candidate


def _extract_clean_employee_names(db: Session) -> List[str]:
    """Quét danh sách tên nhân viên thực tế từ FactLeadActivity, DealWin và SalesDeal."""
    raw_values: List[str] = []
    for (v,) in db.query(FactLeadActivity.assigned_users).distinct().all():
        if v:
            raw_values.append(str(v))
    for (v,) in db.query(DealWin.care_by).distinct().all():
        if v:
            raw_values.append(str(v))
    for (v,) in db.query(SalesDeal.nv_cs).distinct().all():
        if v:
            raw_values.append(str(v))

    # Gom theo khóa không dấu + chữ thường để khử trùng các biến thể gõ lệch dấu / hoa thường
    # (VD: "Vượng nguyễn" vs "Vượng Nguyễn", "Nguyễn Quoc Anh" vs "Nguyễn Quốc Anh")
    by_ascii_key: Dict[str, str] = {}
    for raw in raw_values:
        for token in re.split(r"[,;/|]+", raw):
            clean = re.sub(r"\s+", " ", unicodedata.normalize("NFC", token).strip())
            if len(clean) < 2 or any(ch.isdigit() for ch in clean if len(clean) > 4 and clean.isdigit()):
                continue
            ascii_k = strip_vn_accents(clean)
            if not ascii_k or ascii_k in _JUNK_EMPLOYEE_TOKENS:
                continue
            if any(j in ascii_k for j in ("chua phan cong", "chua dong tien", "khong hoc", "bo qua")):
                continue

            prev = by_ascii_key.get(ascii_k)
            if prev is None:
                by_ascii_key[ascii_k] = clean
            else:
                # Ưu tiên bản có dấu tiếng Việt đầy đủ hơn và viết hoa chữ cái đầu đẹp hơn
                prev_non_ascii = sum(1 for c in prev if ord(c) > 127)
                cur_non_ascii = sum(1 for c in clean if ord(c) > 127)
                prev_caps = sum(1 for w in prev.split() if w[:1].isupper())
                cur_caps = sum(1 for w in clean.split() if w[:1].isupper())
                if (cur_non_ascii, cur_caps) > (prev_non_ascii, prev_caps):
                    by_ascii_key[ascii_k] = clean

    return sorted(by_ascii_key.values(), key=lambda s: strip_vn_accents(s))


def sync_employees_from_db(db: Session, include_demo_departments: bool = False) -> int:
    """Quét tên nhân sự thực tế từ DB và tạo tài khoản Consultant (pass '1') cho những ai chưa có."""
    existing_users = db.query(AppUser).all()
    existing_usernames = {u.username.strip().lower() for u in existing_users if u.username}
    existing_name_keys = {strip_vn_accents(u.full_name or u.username) for u in existing_users}

    discovered_names = _extract_clean_employee_names(db)
    added_count = 0
    now = get_vn_now()

    for emp_name in discovered_names:
        name_key = strip_vn_accents(emp_name)
        if not name_key or name_key in existing_name_keys:
            continue
        uname = _make_username_slug(emp_name, existing_usernames)
        pw_hash, salt = hash_password(DEFAULT_STAFF_PASSWORD)
        db.add(
            AppUser(
                username=uname,
                password_hash=pw_hash,
                salt=salt,
                full_name=emp_name,
                department=DEPT_CONSULTANT,
                role="staff",
                is_default_password=True,
                is_active=True,
                created_at=now,
            )
        )
        existing_name_keys.add(name_key)
        added_count += 1

    if include_demo_departments:
        # Đảm bảo mỗi phòng ban đều có sẵn ít nhất 1 tài khoản đại diện (pass "1") để kiểm thử đủ 3 luồng RBAC
        current_depts = {
            canonicalize_department(u.department, u.role)
            for u in existing_users
            if u.is_active
        }
        if added_count > 0:
            current_depts.add(DEPT_CONSULTANT)

        seed_representatives = [
            (DEPT_CONSULTANT, "Consultant Demo"),
            (DEPT_MARKETING, "Marketing EzTech"),
            (DEPT_CLASS_MANAGER, "Quản Lý Lớp Học"),
        ]
        for dept_name, display_name in seed_representatives:
            if dept_name not in current_depts and strip_vn_accents(display_name) not in existing_name_keys:
                uname = _make_username_slug(display_name, existing_usernames)
                pw_hash, salt = hash_password(DEFAULT_STAFF_PASSWORD)
                db.add(
                    AppUser(
                        username=uname,
                        password_hash=pw_hash,
                        salt=salt,
                        full_name=display_name,
                        department=dept_name,
                        role="staff",
                        is_default_password=True,
                        is_active=True,
                        created_at=now,
                    )
                )
                existing_name_keys.add(strip_vn_accents(display_name))
                current_depts.add(dept_name)
                added_count += 1

    if added_count > 0:
        db.commit()
        invalidate_employees_auth_cache()
    return added_count


def init_default_admin(db: Session):
    """Đảm bảo tài khoản Admin full quyền tồn tại (giữ nguyên mật khẩu hiện tại) & chạy seed nhân viên lần đầu."""
    try:
        admin_user = db.query(AppUser).filter(AppUser.username == ADMIN_USERNAME).first()
        if not admin_user:
            pw_hash, salt = hash_password(ADMIN_PASSWORD)
            admin_user = AppUser(
                username=ADMIN_USERNAME,
                password_hash=pw_hash,
                salt=salt,
                full_name="Admin EzTech",
                department=DEPT_ADMIN,
                role="admin",
                is_default_password=False,
                is_active=True,
                created_at=get_vn_now(),
            )
            db.add(admin_user)
            db.commit()
            invalidate_employees_auth_cache()
            logger.info(f"Đã khởi tạo tài khoản quản trị '{ADMIN_USERNAME}'.")
        else:
            changed = False
            if admin_user.role != "admin":
                admin_user.role = "admin"
                changed = True
            if admin_user.department != DEPT_ADMIN:
                admin_user.department = DEPT_ADMIN
                changed = True
            if admin_user.is_default_password:
                admin_user.is_default_password = False
                changed = True
            if not admin_user.full_name:
                admin_user.full_name = "Quản trị viên EzTech"
                changed = True
            if changed:
                db.commit()
                invalidate_employees_auth_cache()

        # Chỉ tự động quét seed lần đầu tiên để nếu Admin xóa bớt nhân viên thì không bị tự tạo lại khi restart
        seed_flag = db.query(AppConfig).filter(AppConfig.config_key == INITIAL_SEED_CONFIG_KEY).first()
        if not seed_flag:
            added = sync_employees_from_db(db, include_demo_departments=True)
            db.add(AppConfig(config_key=INITIAL_SEED_CONFIG_KEY, config_value="done"))
            db.commit()
            invalidate_employees_auth_cache()
            logger.info(f"Đã khởi tạo tự động {added} tài khoản nhân viên từ dữ liệu hệ thống.")
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi khởi tạo tài khoản mặc định & seed nhân sự: {e}")


# ==============================================================================
# 5. DEPENDENCIES XÁC THỰC & PHÂN QUYỀN (RBAC)
# ==============================================================================
security = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> AppUser:
    """FastAPI Dependency: Trích xuất và xác thực token Bearer từ Header."""
    token = None
    if credentials:
        token = credentials.credentials
    elif "token" in request.query_params:
        token = request.query_params["token"]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chưa đăng nhập. Vui lòng đăng nhập để tiếp tục.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_jwt_token(token)
    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Phiên đăng nhập đã hết hạn hoặc không hợp lệ.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = str(payload["sub"]).strip().lower()
    user = db.query(AppUser).filter(AppUser.username == username, AppUser.is_active == True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tài khoản không tồn tại hoặc đã bị ngừng kích hoạt.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_admin(current_user: AppUser = Depends(get_current_user)) -> AppUser:
    perms = get_user_permissions(current_user)
    if not perms["is_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ Quản trị viên (Admin) mới có quyền thực hiện thao tác này.",
        )
    return current_user


def require_tab_access(tab_id: str):
    """Dependency kiểm tra quyền truy cập vào module/trang cụ thể."""
    def _checker(current_user: AppUser = Depends(get_current_user)) -> AppUser:
        if not has_tab_access(current_user, tab_id):
            perms = get_user_permissions(current_user)
            tab_label = TAB_DISPLAY_NAMES.get(tab_id, tab_id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Tài khoản phòng '{perms['department']}' không có quyền truy cập trang '{tab_label}'.",
            )
        return current_user

    return _checker


# ==============================================================================
# 6. PYDANTIC SCHEMAS CHO AUTH & QUẢN LÝ NHÂN SỰ
# ==============================================================================
class LoginRequest(BaseModel):
    username: str = Field(..., description="Tên đăng nhập hoặc Họ tên nhân viên")
    password: str = Field(..., description="Mật khẩu")
    remember_me: bool = Field(True, description="Ghi nhớ phiên đăng nhập")


class UserInfoResponse(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    department: str
    is_default_password: bool = False
    allowed_tabs: List[str] = Field(default_factory=list)
    default_tab: str = "work_report"
    module_scopes: Dict[str, str] = Field(default_factory=dict)
    scope_summary: str = ""
    last_login_at: Optional[str] = None


class EmployeeLoginOption(BaseModel):
    id: int
    username: str
    full_name: str
    department: str
    role: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_hours: int
    user: UserInfoResponse


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str
    confirm_password: Optional[str] = None


class CreateEmployeeRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=120)
    department: str = Field(default=DEPT_CONSULTANT)
    password: Optional[str] = Field(default=DEFAULT_STAFF_PASSWORD)


class UpdateEmployeeRequest(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=120)
    department: Optional[str] = None
    reset_password: bool = False


def build_user_info_response(user: AppUser) -> UserInfoResponse:
    perms = get_user_permissions(user)
    return UserInfoResponse(
        id=user.id,
        username=user.username,
        full_name=(user.full_name or user.username).strip(),
        role="admin" if perms["is_admin"] else (user.role or "staff"),
        department=perms["department"],
        is_default_password=bool(getattr(user, "is_default_password", False)),
        allowed_tabs=perms["allowed_tabs"],
        default_tab=perms["default_tab"],
        module_scopes=perms["module_scopes"],
        scope_summary=perms["scope_summary"],
        last_login_at=user.last_login_at.strftime("%Y-%m-%d %H:%M:%S") if user.last_login_at else None,
    )


# ==============================================================================
# 7. ROUTER ENDPOINTS
# ==============================================================================
@router.get("/employees", response_model=List[EmployeeLoginOption])
def list_login_employees(db: Session = Depends(get_db)):
    """Danh sách nhân viên cho Searchable Combobox ở màn hình Login (có cache RAM 10 phút)."""
    global _EMP_LIST_CACHE
    now_ts = time.time()
    with _EMP_LIST_LOCK:
        if _EMP_LIST_CACHE and (now_ts - _EMP_LIST_CACHE[0] < _EMP_LIST_TTL):
            return _EMP_LIST_CACHE[1]

    init_default_admin(db)
    rows = db.query(AppUser).filter(AppUser.is_active == True).all()

    def _sort_key(u: AppUser):
        dept = canonicalize_department(u.department, u.role)
        # Đặt Admin lên đầu hoặc sắp xếp theo tên chữ cái tiếng Việt dễ tìm
        is_adm = 0 if dept == DEPT_ADMIN else 1
        return (is_adm, strip_vn_accents(u.full_name or u.username))

    rows.sort(key=_sort_key)
    out = [
        {
            "id": u.id,
            "username": u.username,
            "full_name": (u.full_name or u.username).strip(),
            "department": canonicalize_department(u.department, u.role),
            "role": "admin" if canonicalize_department(u.department, u.role) == DEPT_ADMIN else (u.role or "staff"),
        }
        for u in rows
    ]
    with _EMP_LIST_LOCK:
        _EMP_LIST_CACHE = (now_ts, out)
    return out


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Đăng nhập theo username hoặc họ tên nhân viên, có chống Brute-force."""
    init_default_admin(db)

    raw_ident = (req.username or "").strip()
    if not raw_ident or not req.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vui lòng chọn nhân viên và nhập mật khẩu.",
        )

    client_ip = request.client.host if request.client else "unknown"
    lock_key = f"{client_ip}:{raw_ident.lower()}"

    is_locked, remaining_sec = check_rate_limit_lockout(lock_key)
    if is_locked:
        mins = max(1, remaining_sec // 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Tài khoản tạm thời bị khóa do nhập sai nhiều lần. Vui lòng thử lại sau {mins} phút.",
        )

    clean_username = raw_ident.lower()
    user = db.query(AppUser).filter(AppUser.username == clean_username).first()
    if not user:
        # Hỗ trợ tìm theo full_name chính xác hoặc không dấu nếu người dùng gõ trực tiếp họ tên
        target_ascii = strip_vn_accents(raw_ident)
        candidates = db.query(AppUser).filter(AppUser.is_active == True).all()
        for cand in candidates:
            if (cand.full_name and cand.full_name.strip().lower() == clean_username) or (
                target_ascii and strip_vn_accents(cand.full_name) == target_ascii
            ):
                user = cand
                break

    if not user or not verify_password(req.password, user.salt, user.password_hash):
        record_failed_attempt(lock_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Mật khẩu không chính xác hoặc tài khoản không tồn tại.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản của bạn đã bị ngừng kích hoạt.",
        )

    clear_failed_attempts(lock_key)
    user.last_login_at = get_vn_now()
    db.commit()

    perms = get_user_permissions(user)
    expire_delta = (
        timedelta(days=REMEMBER_ME_EXPIRE_DAYS)
        if req.remember_me
        else timedelta(hours=DEFAULT_ACCESS_TOKEN_EXPIRE_HOURS)
    )
    token = create_jwt_token(
        payload_data={
            "sub": user.username,
            "uid": user.id,
            "role": "admin" if perms["is_admin"] else "staff",
            "dept": perms["department"],
            "name": (user.full_name or user.username).strip(),
        },
        expires_delta=expire_delta,
    )

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in_hours=REMEMBER_ME_EXPIRE_DAYS * 24 if req.remember_me else DEFAULT_ACCESS_TOKEN_EXPIRE_HOURS,
        user=build_user_info_response(user),
    )


@router.get("/me", response_model=UserInfoResponse)
def get_me(current_user: AppUser = Depends(get_current_user)):
    """Lấy thông tin tài khoản, phòng ban và ma trận quyền hạn hiện tại."""
    return build_user_info_response(current_user)


@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Đổi mật khẩu tài khoản đang đăng nhập."""
    if not req.old_password or not req.new_password or not req.new_password.strip():
        raise HTTPException(status_code=400, detail="Mật khẩu hiện tại và mật khẩu mới không được để trống.")

    if req.confirm_password is not None and req.new_password != req.confirm_password:
        raise HTTPException(status_code=400, detail="Mật khẩu mới và xác nhận mật khẩu không trùng khớp.")

    if not verify_password(req.old_password, current_user.salt, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Mật khẩu hiện tại không chính xác.")

    new_hash, new_salt = hash_password(req.new_password)
    current_user.password_hash = new_hash
    current_user.salt = new_salt
    current_user.is_default_password = False
    db.commit()

    return {
        "status": "ok",
        "message": "Đổi mật khẩu thành công!",
        "user": build_user_info_response(current_user),
    }


@router.post("/logout")
def logout():
    """Đăng xuất phiên làm việc."""
    return {"status": "ok", "message": "Đã đăng xuất thành công."}


# ==============================================================================
# 8. QUẢN TRỊ NHÂN VIÊN DÀNH CHO ADMIN (THÊM / SỬA PHÒNG BAN / RESET PASS / XÓA)
# ==============================================================================
@router.get("/users", response_model=List[UserInfoResponse])
def admin_list_users(
    _: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.query(AppUser).filter(AppUser.is_active == True).all()
    rows.sort(key=lambda u: (0 if canonicalize_department(u.department, u.role) == DEPT_ADMIN else 1, strip_vn_accents(u.full_name or u.username)))
    return [build_user_info_response(u) for u in rows]


@router.post("/users", response_model=UserInfoResponse)
def admin_create_user(
    req: CreateEmployeeRequest,
    _: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    full_name = re.sub(r"\s+", " ", (req.full_name or "").strip())
    if not full_name:
        raise HTTPException(status_code=400, detail="Họ tên nhân viên không được để trống.")

    dept = canonicalize_department(req.department)
    if req.department.strip() not in VALID_DEPARTMENTS and strip_vn_accents(req.department) != "admin":
        if dept not in VALID_DEPARTMENTS:
            dept = DEPT_CONSULTANT

    # Kiểm tra trùng họ tên đang active
    target_ascii = strip_vn_accents(full_name)
    for existing in db.query(AppUser).filter(AppUser.is_active == True).all():
        if strip_vn_accents(existing.full_name or existing.username) == target_ascii:
            raise HTTPException(status_code=400, detail=f"Nhân viên '{full_name}' đã tồn tại trên hệ thống.")

    all_usernames = {u.username.strip().lower() for u in db.query(AppUser).all() if u.username}
    uname = _make_username_slug(full_name, all_usernames)
    raw_pw = req.password if (req.password and req.password.strip()) else DEFAULT_STAFF_PASSWORD
    pw_hash, salt = hash_password(raw_pw)

    new_user = AppUser(
        username=uname,
        password_hash=pw_hash,
        salt=salt,
        full_name=full_name,
        department=dept,
        role="admin" if dept == DEPT_ADMIN else "staff",
        is_default_password=(raw_pw == DEFAULT_STAFF_PASSWORD),
        is_active=True,
        created_at=get_vn_now(),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    invalidate_employees_auth_cache()
    return build_user_info_response(new_user)


@router.put("/users/{user_id}", response_model=UserInfoResponse)
def admin_update_user(
    user_id: int,
    req: UpdateEmployeeRequest,
    current_admin: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(AppUser).filter(AppUser.id == user_id, AppUser.is_active == True).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản nhân viên.")

    if req.full_name is not None and req.full_name.strip():
        user.full_name = re.sub(r"\s+", " ", req.full_name.strip())

    if req.department is not None and req.department.strip():
        new_dept = canonicalize_department(req.department)
        if user.id == current_admin.id and new_dept != DEPT_ADMIN:
            raise HTTPException(status_code=400, detail="Không thể tự hạ quyền Admin của chính tài khoản đang đăng nhập.")
        user.department = new_dept
        user.role = "admin" if new_dept == DEPT_ADMIN else "staff"

    if req.reset_password:
        pw_hash, salt = hash_password(DEFAULT_STAFF_PASSWORD)
        user.password_hash = pw_hash
        user.salt = salt
        user.is_default_password = True

    db.commit()
    db.refresh(user)
    invalidate_employees_auth_cache()
    return build_user_info_response(user)


@router.delete("/users/{user_id}")
def admin_delete_user(
    user_id: int,
    current_admin: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(AppUser).filter(AppUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản nhân viên.")
    if user.id == current_admin.id or user.username == ADMIN_USERNAME:
        raise HTTPException(status_code=400, detail="Không thể xóa tài khoản Quản trị viên gốc hoặc tài khoản đang đăng nhập.")

    emp_name = user.full_name or user.username
    db.delete(user)
    db.commit()
    invalidate_employees_auth_cache()
    return {"status": "ok", "message": f"Đã xóa tài khoản nhân viên '{emp_name}'."}


@router.post("/users/sync-from-db")
def admin_sync_users_from_db(
    _: AppUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    added = sync_employees_from_db(db, include_demo_departments=False)
    return {
        "status": "ok",
        "added_count": added,
        "message": f"Đã quét dữ liệu và thêm mới {added} nhân viên (mật khẩu mặc định '1')." if added > 0 else "Tất cả nhân sự trong DB đều đã có tài khoản.",
    }
