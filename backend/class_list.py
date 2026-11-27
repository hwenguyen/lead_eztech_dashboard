"""
API Danh sách lớp học (Class List).
Chỉ dành cho Quản lý lớp học và Admin (chặn qua dependency `require_tab_access("class_list")`).
Đọc trực tiếp từ RAM cache của `backend.deal_entry` (0 Neon Egress phát sinh).
"""

from typing import Any, Dict, List, Optional
import re
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import AppUser
from backend.auth import require_tab_access
from backend.deal_entry import (
    clean_phone,
    get_cached_deals,
    merge_classes,
    read_lists,
    _is_valid_pancake_conv_url,
)
from backend.rbac_config import strip_vn_accents

router = APIRouter(prefix="/api/class-list", tags=["Class List"])


def _aggregate_students_from_deals(deals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Gộp trùng học viên theo SĐT đã chuẩn hóa (tránh lặp dòng khi học viên có nhiều đợt thu tiền / thu nợ).
    Chỉ giữ các bản ghi là học viên hoặc đã được xếp lớp.
    """
    by_key: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []

    for d in deals:
        lop_list = [str(c).strip() for c in (d.get("lop") or []) if str(c).strip()]
        if d.get("isStudent") is False and not lop_list:
            continue

        phone = clean_phone(d.get("sdt")) or str(d.get("sdt") or "").strip()
        key = phone or str(d.get("id") or "")
        if not key:
            continue

        ho_ten = str(d.get("hoTen") or "").strip()
        link_pancake = str(d.get("zalo") or "").strip()
        link_support = str(d.get("nhomCS") or "").strip()
        nv_cs = str(d.get("nvCS") or "").strip()

        existing = by_key.get(key)
        d_date = (str(d.get("ngayThu") or ""), int(d.get("_sort_id") or 0))
        if existing is None:
            by_key[key] = {
                "id": key,
                "hoTen": ho_ten or "Học viên",
                "sdt": phone,
                "linkPancake": link_pancake,
                "linkSupport": link_support,
                "lop": list(lop_list),
                "nvCS": nv_cs,
                "_earliest_date": d_date,
            }
            order.append(key)
        else:
            if ho_ten and (not existing["hoTen"] or existing["hoTen"] == "Học viên"):
                existing["hoTen"] = ho_ten
            if link_pancake and (
                not existing["linkPancake"]
                or (_is_valid_pancake_conv_url(link_pancake) and not _is_valid_pancake_conv_url(existing["linkPancake"]))
            ):
                existing["linkPancake"] = link_pancake
            if link_support and not existing["linkSupport"]:
                existing["linkSupport"] = link_support
            if lop_list:
                if d_date < existing["_earliest_date"]:
                    existing["lop"] = merge_classes(lop_list, existing["lop"])
                    existing["_earliest_date"] = d_date
                else:
                    existing["lop"] = merge_classes(existing["lop"], lop_list)
            if nv_cs and not existing["nvCS"]:
                existing["nvCS"] = nv_cs

    for item in by_key.values():
        item.pop("_earliest_date", None)
    return [by_key[k] for k in order]


def _split_staff_names(raw: str) -> List[str]:
    if not raw:
        return []
    return [p.strip() for p in re.split(r"[,;/]+", raw) if p.strip()]


@router.get("/students")
def list_class_students(
    class_name: Optional[str] = Query(None, description="Tên lớp cần lọc (hoặc '__NONE__' cho chưa xếp lớp)"),
    staff: Optional[str] = Query(None, description="Lọc theo Nhân viên chăm sóc"),
    search: Optional[str] = Query(None, description="Tìm theo Tên học viên hoặc SĐT"),
    force: bool = Query(False, description="Làm mới cache từ DB"),
    _: AppUser = Depends(require_tab_access("class_list")),
    db: Session = Depends(get_db),
):
    """Lấy danh sách lớp học và học viên theo lớp (chỉ Quản lý lớp học & Admin)."""
    lists = read_lists(db, use_cache=not force)
    all_deals = get_cached_deals(db, force_refresh=force)
    students = _aggregate_students_from_deals(all_deals)

    # Tổng hợp danh sách lớp học & sĩ số từng lớp
    class_counts: Dict[str, int] = {}
    for cls in (lists.get("lop") or []):
        clean_cls = str(cls).strip()
        if clean_cls:
            class_counts.setdefault(clean_cls, 0)

    unassigned_class_count = 0
    staff_set = set()
    has_unassigned_staff = False

    for st in students:
        if not st["lop"]:
            unassigned_class_count += 1
        else:
            for c in st["lop"]:
                class_counts[c] = class_counts.get(c, 0) + 1

        staff_parts = _split_staff_names(st["nvCS"])
        if not staff_parts:
            has_unassigned_staff = True
        else:
            for p in staff_parts:
                if p.lower() == "chưa phân công":
                    has_unassigned_staff = True
                else:
                    staff_set.add(p)

    classes = sorted(class_counts.keys(), key=lambda x: strip_vn_accents(x))
    staff_list = sorted(staff_set, key=lambda x: strip_vn_accents(x))
    if has_unassigned_staff:
        staff_list.append("Chưa phân công")

    # Áp dụng bộ lọc (nếu có truyền query params)
    filtered = students
    if class_name:
        cls_clean = class_name.strip()
        if cls_clean == "__NONE__":
            filtered = [s for s in filtered if not s["lop"]]
        else:
            filtered = [s for s in filtered if cls_clean in s["lop"]]

    if staff:
        staff_clean = staff.strip()
        if staff_clean.lower() == "chưa phân công":
            filtered = [
                s for s in filtered
                if not s["nvCS"].strip() or s["nvCS"].strip().lower() == "chưa phân công"
            ]
        else:
            target_ascii = strip_vn_accents(staff_clean)
            filtered = [
                s for s in filtered
                if any(strip_vn_accents(p) == target_ascii for p in _split_staff_names(s["nvCS"]))
            ]

    if search and search.strip():
        q = strip_vn_accents(search.strip())
        q_digits = re.sub(r"\D", "", search.strip())
        filtered = [
            s for s in filtered
            if q in strip_vn_accents(s["hoTen"])
            or (q_digits and q_digits in re.sub(r"\D", "", s["sdt"]))
            or q in strip_vn_accents(s["nvCS"])
        ]

    return {
        "ok": True,
        "classes": classes,
        "class_counts": class_counts,
        "unassigned_class_count": unassigned_class_count,
        "staff_list": staff_list,
        "total": len(filtered),
        "students": filtered,
    }
