"""
================================================================================
HỆ THỐNG XÁC THỰC VÀ BẢO MẬT (AUTHENTICATION & SECURITY MODULE)
- Mã hóa mật khẩu chuẩn NIST: Salted PBKDF2-HMAC-SHA256 (100,000 vòng lặp)
- Token chuẩn JWT HS256 độc lập, ký số HMAC-SHA256 chống giả mạo
- Chống tấn công dò mật khẩu (Brute-Force & Rate Limiting): Khóa tạm sau 5 lần sai
- Chống tấn công Timing Attack qua hmac.compare_digest
- Khởi tạo tự động tài khoản Quản trị viên (Admin) ban đầu
================================================================================
"""

import os
import time
import json
import base64
import hmac
import hashlib
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.db import get_db, SessionLocal
from database.models import AppUser

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

# Tài khoản Admin mặc định cấu hình qua env
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "eztech@2026").strip()

# ==============================================================================
# 1. BẢO MẬT MẬT KHẨU (PBKDF2-HMAC-SHA256)
# ==============================================================================
def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """
    Băm mật khẩu bằng PBKDF2-HMAC-SHA256 với Salt ngẫu nhiên và 100.000 vòng lặp.
    Trả về (password_hash, salt).
    """
    if not salt:
        salt = secrets.token_hex(16)
    
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000
    )
    password_hash = key.hex()
    return password_hash, salt


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """So khớp mật khẩu với hàm so sánh constant-time hmac.compare_digest chống timing attack."""
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
    """Tạo JWT Token chuẩn HS256 được ký bằng secret key."""
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
    """Kiểm tra tính hợp lệ và thời hạn của JWT Token."""
    try:
        parts = token.strip().split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts

        # 1. Xác thực chữ ký số
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        expected_sig = hmac.new(JWT_SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
        actual_sig = _base64url_decode(sig_b64)

        if not hmac.compare_digest(expected_sig, actual_sig):
            logger.warning("Token signature mismatch.")
            return None

        # 2. Đọc payload và kiểm tra hạn sử dụng
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
_ATTEMPTS_LOCK = hmac.compare_digest  # Placeholder for atomic operations

def check_rate_limit_lockout(key: str) -> Tuple[bool, int]:
    """
    Kiểm tra xem IP / username có bị khóa do nhập sai mật khẩu nhiều lần không.
    Khóa 10 phút nếu sai 5 lần trong vòng 5 phút.
    """
    now = time.time()
    attempts = _FAILED_ATTEMPTS.get(key, [])
    # Loại bỏ các lần thử cũ hơn 10 phút
    attempts = [t for t in attempts if now - t < 600]
    _FAILED_ATTEMPTS[key] = attempts

    if len(attempts) >= 5:
        # Thời gian còn lại phải chờ (giây)
        remaining = int(600 - (now - attempts[-1]))
        return True, max(1, remaining)
    return False, 0

def record_failed_attempt(key: str):
    now = time.time()
    attempts = _FAILED_ATTEMPTS.get(key, [])
    attempts.append(now)
    _FAILED_ATTEMPTS[key] = attempts

def clear_failed_attempts(key: str):
    if key in _FAILED_ATTEMPTS:
        del _FAILED_ATTEMPTS[key]


# ==============================================================================
# 4. KHỞI TẠO TỰ ĐỘNG TÀI KHOẢN ADMIN
# ==============================================================================
def init_default_admin(db: Session):
    """Tự động tạo tài khoản Admin nếu bảng app_users chưa có tài khoản nào."""
    try:
        user_count = db.query(AppUser).count()
        if user_count == 0:
            pw_hash, salt = hash_password(ADMIN_PASSWORD)
            admin_user = AppUser(
                username=ADMIN_USERNAME,
                password_hash=pw_hash,
                salt=salt,
                full_name="Quản trị viên EzTech",
                role="admin",
                is_active=True,
                created_at=get_vn_now()
            )
            db.add(admin_user)
            db.commit()
            logger.info(f"Đã tự động khởi tạo tài khoản quản trị '{ADMIN_USERNAME}'.")
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi khởi tạo tài khoản Admin mặc định: {e}")


# ==============================================================================
# 5. DEPENDENCY XÁC THỰC NGƯỜI DÙNG HIỆN TẠI
# ==============================================================================
security = HTTPBearer(auto_error=False)

def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
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
            detail="Chưa đăng nhập. Vui lòng cung cấp Authorization token.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    payload = verify_jwt_token(token)
    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Phiên đăng nhập đã hết hạn hoặc token không hợp lệ.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    username = payload["sub"]
    user = db.query(AppUser).filter(AppUser.username == username, AppUser.is_active == True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tài khoản không tồn tại hoặc đã bị vô hiệu hóa.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return user


# ==============================================================================
# 6. PYDANTIC SCHEMAS CHO AUTH
# ==============================================================================
class LoginRequest(BaseModel):
    username: str = Field(..., description="Tên đăng nhập")
    password: str = Field(..., description="Mật khẩu")
    remember_me: bool = Field(False, description="Ghi nhớ đăng nhập 30 ngày")

class UserInfoResponse(BaseModel):
    id: int
    username: str
    full_name: Optional[str] = None
    role: str
    last_login_at: Optional[str] = None

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_hours: int
    user: UserInfoResponse

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


# ==============================================================================
# 7. ROUTER ENDPOINTS
# ==============================================================================
@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Đăng nhập hệ thống có bảo vệ chống Brute-force & Rate-limit."""
    # Đảm bảo có sẵn tài khoản admin nếu là lần đầu chạy
    init_default_admin(db)

    # Định danh client để tính số lần sai
    client_ip = request.client.host if request.client else "unknown"
    lock_key = f"{client_ip}:{req.username.strip().lower()}"

    is_locked, remaining_sec = check_rate_limit_lockout(lock_key)
    if is_locked:
        mins = max(1, remaining_sec // 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Tài khoản tạm thời bị khóa do nhập sai nhiều lần. Vui lòng thử lại sau {mins} phút."
        )

    clean_username = req.username.strip().lower()
    user = db.query(AppUser).filter(AppUser.username == clean_username).first()

    # Xác thực mật khẩu
    if not user or not verify_password(req.password, user.salt, user.password_hash):
        record_failed_attempt(lock_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tên đăng nhập hoặc mật khẩu không chính xác."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản của bạn đã bị vô hiệu hóa bởi quản trị viên."
        )

    # Đăng nhập thành công -> Xóa bộ nhớ đếm sai
    clear_failed_attempts(lock_key)

    # Cập nhật thời điểm đăng nhập
    user.last_login_at = get_vn_now()
    db.commit()

    # Sinh JWT Token
    expire_delta = timedelta(days=REMEMBER_ME_EXPIRE_DAYS) if req.remember_me else timedelta(hours=DEFAULT_ACCESS_TOKEN_EXPIRE_HOURS)
    token = create_jwt_token(
        payload_data={
            "sub": user.username,
            "role": user.role,
            "name": user.full_name or user.username
        },
        expires_delta=expire_delta
    )

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in_hours=REMEMBER_ME_EXPIRE_DAYS * 24 if req.remember_me else DEFAULT_ACCESS_TOKEN_EXPIRE_HOURS,
        user=UserInfoResponse(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            last_login_at=user.last_login_at.strftime("%Y-%m-%d %H:%M:%S") if user.last_login_at else None
        )
    )


@router.get("/me", response_model=UserInfoResponse)
def get_me(current_user: AppUser = Depends(get_current_user)):
    """Lấy thông tin tài khoản đang đăng nhập."""
    return UserInfoResponse(
        id=current_user.id,
        username=current_user.username,
        full_name=current_user.full_name,
        role=current_user.role,
        last_login_at=current_user.last_login_at.strftime("%Y-%m-%d %H:%M:%S") if current_user.last_login_at else None
    )


@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Đổi mật khẩu tài khoản hiện tại."""
    if not verify_password(req.old_password, current_user.salt, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Mật khẩu cũ không chính xác.")

    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Mật khẩu mới phải có ít nhất 6 ký tự.")

    new_hash, new_salt = hash_password(req.new_password)
    current_user.password_hash = new_hash
    current_user.salt = new_salt
    db.commit()

    return {"status": "ok", "message": "Đổi mật khẩu thành công!"}


@router.post("/logout")
def logout():
    """Đăng xuất phiên làm việc."""
    return {"status": "ok", "message": "Đã đăng xuất thành công."}
