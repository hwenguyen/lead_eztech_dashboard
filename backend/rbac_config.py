"""
Cấu hình tập trung Phân quyền truy cập trang (RBAC) & Phạm vi dữ liệu (Data Scoping).
Mọi thay đổi về phòng ban, danh sách trang được phép truy cập hoặc phạm vi dữ liệu
chỉ cần chỉnh sửa tại file này.
"""

import re
import unicodedata
from typing import Dict, List, Optional, Set, Any
from fastapi import HTTPException, status

DEPT_ADMIN = "Admin"
DEPT_CONSULTANT = "Consultant"
DEPT_MARKETING = "Marketing"
DEPT_CLASS_MANAGER = "Quản lý lớp học"

VALID_DEPARTMENTS: List[str] = [
    DEPT_CONSULTANT,
    DEPT_MARKETING,
    DEPT_CLASS_MANAGER,
    DEPT_ADMIN,
]

ALL_TABS: List[str] = [
    "overview",
    "facebook",
    "tiktok",
    "bulletin",
    "work_report",
    "remind",
    "deals",
    "gas_tool",
    "class_list",
    "invoice",
    "bot",
    "data_export",
    "add_friend",
    "ai_assistant",
    "btvn_grader",
]

CONSULTANT_TABS: List[str] = [
    "bulletin",
    "work_report",
    "remind",
    "deals",
    "gas_tool",
    "ai_assistant",
    "invoice",
]

MARKETING_ONLY_TABS: List[str] = [
    "overview",
    "facebook",
    "tiktok",
]

MARKETING_TABS: List[str] = [
    *MARKETING_ONLY_TABS,
    *CONSULTANT_TABS,
]

CLASS_MANAGER_TABS: List[str] = [
    *CONSULTANT_TABS,
    "class_list",
    "btvn_grader",
]

TAB_DISPLAY_NAMES: Dict[str, str] = {
    "overview": "Tổng quan & Chỉ số",
    "facebook": "Facebook Analytics",
    "tiktok": "TikTok Analytics",
    "work_report": "Báo cáo công việc",
    "bulletin": "Bảng Tin & Công Việc",
    "remind": "Chăm sóc Lead",
    "deals": "Deal Win",
    "gas_tool": "Nhập Deal & Công Nợ",
    "class_list": "Danh sách lớp học",
    "invoice": "Xuất hoá đơn",
    "bot": "Bot Gửi Tin",
    "data_export": "Query & Xuất Excel",
    "add_friend": "Kết Bạn Tự Động",
    "ai_assistant": "Trợ Lý AI",
    "btvn_grader": "Chấm BTVN (AI)",
}

# Ma trận phân quyền chuẩn theo từng Phòng ban
DEPARTMENT_MATRIX: Dict[str, Dict[str, Any]] = {
    DEPT_ADMIN: {
        "allowed_tabs": ALL_TABS,
        "default_tab": "overview",
        "module_scopes": {tab: "all" for tab in ALL_TABS},
        "scope_summary": "Toàn quyền hệ thống (Admin): Truy cập đầy đủ các chức năng và xem toàn bộ dữ liệu tất cả nhân viên.",
    },
    DEPT_CONSULTANT: {
        "allowed_tabs": CONSULTANT_TABS,
        "default_tab": "bulletin",
        "module_scopes": {
            **{tab: "personal" for tab in CONSULTANT_TABS},
            "deals": "all",
        },
        "scope_summary": "Xem toàn bộ danh sách Deal Win; xem & thao tác dữ liệu cá nhân tại các trang nghiệp vụ khác.",
    },
    DEPT_MARKETING: {
        "allowed_tabs": MARKETING_TABS,
        "default_tab": "bulletin",
        "module_scopes": {
            "overview": "all",
            "facebook": "all",
            "tiktok": "all",
            **{tab: "personal" for tab in CONSULTANT_TABS},
            "deals": "all",
        },
        "scope_summary": "Xem toàn bộ dữ liệu tại các trang Marketing & Deal Win; chỉ xem dữ liệu cá nhân tại các trang Consultant còn lại.",
    },
    DEPT_CLASS_MANAGER: {
        "allowed_tabs": CLASS_MANAGER_TABS,
        "default_tab": "bulletin",
        "module_scopes": {
            **{tab: "all" for tab in CLASS_MANAGER_TABS},
            "work_report": "personal",
            "gas_tool": "personal",
        },
        "scope_summary": "Xem toàn bộ dữ liệu trên các trang nghiệp vụ được phân quyền (bao gồm Danh sách lớp học & Chấm BTVN AI); riêng Báo cáo công việc và Nhập Deal & Công nợ chỉ xem & thao tác dữ liệu cá nhân.",
    },
}


def strip_vn_accents(text: Optional[str]) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFC", str(text)).strip().lower()
    s = s.replace("đ", "d")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def normalize_emp_key(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(text)).strip().lower())


def canonicalize_department(raw_dept: Optional[str], role: Optional[str] = None) -> str:
    if role and str(role).strip().lower() == "admin":
        return DEPT_ADMIN
    if not raw_dept:
        return DEPT_CONSULTANT
    clean = strip_vn_accents(raw_dept)
    if clean == "admin":
        return DEPT_ADMIN
    if clean == "marketing":
        return DEPT_MARKETING
    if clean in ("quan ly lop hoc", "quan ly lop", "class manager", "qllh"):
        return DEPT_CLASS_MANAGER
    if clean in ("consultant", "sale", "sales", "tu van"):
        return DEPT_CONSULTANT
    return DEPT_CONSULTANT


def get_user_permissions(user: Any) -> Dict[str, Any]:
    dept = canonicalize_department(getattr(user, "department", None), getattr(user, "role", None))
    cfg = DEPARTMENT_MATRIX.get(dept, DEPARTMENT_MATRIX[DEPT_CONSULTANT])
    return {
        "department": dept,
        "is_admin": dept == DEPT_ADMIN,
        "allowed_tabs": list(cfg["allowed_tabs"]),
        "default_tab": cfg["default_tab"],
        "module_scopes": dict(cfg["module_scopes"]),
        "scope_summary": cfg["scope_summary"],
    }


def has_tab_access(user: Any, tab_id: str) -> bool:
    perms = get_user_permissions(user)
    return perms["is_admin"] or (tab_id in perms["allowed_tabs"])


def get_module_scope(user: Any, tab_id: str) -> str:
    """Trả về 'all' hoặc 'personal' cho trang tương ứng. Raise 403 nếu không có quyền vào trang."""
    perms = get_user_permissions(user)
    if perms["is_admin"]:
        return "all"
    if tab_id not in perms["allowed_tabs"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Phòng ban '{perms['department']}' không có quyền truy cập chức năng '{TAB_DISPLAY_NAMES.get(tab_id, tab_id)}'.",
        )
    return perms["module_scopes"].get(tab_id, "personal")


def resolve_scoped_employee(user: Any, tab_id: str, requested_employee: Optional[str] = None) -> Optional[str]:
    """
    Nếu user có scope 'personal' trên tab_id -> ép cứng filter theo full_name của user.
    Nếu user có scope 'all' -> giữ nguyên tham số requested_employee từ client.
    """
    scope = get_module_scope(user, tab_id)
    if scope == "personal":
        emp_name = (getattr(user, "full_name", None) or getattr(user, "username", "")).strip()
        return emp_name
    return requested_employee


def employee_matches_field(
    field_val: Optional[str],
    employee_name: Optional[str],
    extra_exact_keys: Optional[Set[str]] = None,
) -> bool:
    """
    Kiểm tra tên nhân viên `employee_name` có nằm trong chuỗi phụ trách `field_val`
    (hỗ trợ danh sách nhiều nhân viên ngăn cách bởi dấu phẩy, chấm phẩy, gạch chéo;
    không phân biệt hoa/thường và hỗ trợ khớp chuẩn bỏ dấu khi lệch dấu nhẹ).
    """
    if not employee_name:
        return False
    if not field_val or not str(field_val).strip():
        return False

    target_nfc = normalize_emp_key(employee_name)
    target_ascii = strip_vn_accents(employee_name)
    allowed_nfc = {target_nfc}
    if extra_exact_keys:
        allowed_nfc |= {normalize_emp_key(k) for k in extra_exact_keys if k}

    raw_str = str(field_val).strip()
    if normalize_emp_key(raw_str) in allowed_nfc:
        return True

    parts = [p.strip() for p in re.split(r"[,;/|]+", raw_str) if p.strip()]
    for part in parts:
        if normalize_emp_key(part) in allowed_nfc:
            return True
        if target_ascii and len(target_ascii) >= 4 and strip_vn_accents(part) == target_ascii:
            return True

    return False
