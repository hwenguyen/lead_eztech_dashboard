"""
Router Query & Kết xuất Excel dữ liệu Lead từ Neon Postgres.
- Bảo mật: toàn bộ endpoint yêu cầu JWT Bearer (backend.auth.get_current_user).
- Tối ưu Egress:
  1. SQL Column Projection: chỉ SELECT đúng các cột DB phục vụ cột người dùng tích chọn.
  2. SQL Pushdown: mọi bộ lọc (page, nhân viên, tag, học viên, SĐT, ngày, gộp trùng, phân trang)
     chạy trực tiếp trong Postgres; không kéo bảng raw_conversations hay tag_timeline.
  3. TTL In-Memory Cache cho options (15 phút) và preview (3 phút).
  4. Xuất .xlsx nén DEFLATE dùng openpyxl write_only=True + yield_per(1000).
"""

import hashlib
import io
import json
import logging
import re
import threading
import time
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, exists, func, literal, or_, select
from sqlalchemy.orm import Session, aliased

from backend.auth import get_current_user
from database.db import get_db
from database.models import DealWin, DimLead, FactLeadActivity, SalesDeal
from etl.utils import (
    KNOWN_PAGE_NAMES,
    VN_TZ,
    ZALO_PAGE_NAMES,
    build_pancake_url,
    is_page_id,
    is_zalo_channel,
    resolve_canonical_page_name,
    zalo_page_keys,
)

logger = logging.getLogger("DataExportAPI")

router = APIRouter(
    prefix="/api/data-export",
    tags=["DataExport"],
    dependencies=[Depends(get_current_user)],
)

MAX_EXPORT_ROWS = 20_000
OPTIONS_CACHE_TTL = 900  # 15 phút
PREVIEW_CACHE_TTL = 180  # 3 phút
PREVIEW_CACHE_MAX_ITEMS = 48

_OPTIONS_LOCK = threading.Lock()
_OPTIONS_CACHE: Optional[Tuple[float, Dict[str, Any]]] = None

_PREVIEW_LOCK = threading.Lock()
_PREVIEW_CACHE: "OrderedDict[str, Tuple[float, Dict[str, Any]]]" = OrderedDict()

# Danh mục cột nguồn chuẩn duy nhất cho cả backend & frontend.
# db_fields quyết định chính xác cột nào được đưa vào câu SELECT (Column Projection).
EXPORT_COLUMNS: List[Dict[str, Any]] = [
    {
        "key": "name",
        "label": "Tên khách hàng",
        "default": True,
        "width": 26,
        "db_fields": ("name",),
    },
    {
        "key": "phone_number",
        "label": "Số điện thoại (SĐT)",
        "default": True,
        "width": 16,
        "db_fields": ("phone_number",),
    },
    {
        "key": "page_name",
        "label": "Tên kênh (Page)",
        "default": True,
        "width": 28,
        "db_fields": ("page_id",),
    },
    {
        "key": "assigned_users",
        "label": "Nhân viên phụ trách",
        "default": True,
        "width": 24,
        "db_fields": ("assigned_users",),
    },
    {
        "key": "pancake_link",
        "label": "Link Pancake",
        "default": True,
        "width": 52,
        "db_fields": ("conversation_id", "page_id"),
    },
    {
        "key": "status_tag",
        "label": "Tag trạng thái",
        "default": True,
        "width": 30,
        "db_fields": ("status_tag",),
    },
    {
        "key": "is_student",
        "label": "Trạng thái học viên",
        "default": False,
        "width": 20,
        "db_fields": ("is_student",),
    },
    {
        "key": "message_count",
        "label": "Số tin nhắn",
        "default": False,
        "width": 13,
        "db_fields": ("message_count",),
    },
    {
        "key": "first_created_at",
        "label": "Ngày tạo Lead",
        "default": True,
        "width": 19,
        "db_fields": ("first_created_at",),
    },
    {
        "key": "contacted_at",
        "label": "Tương tác gần nhất",
        "default": True,
        "width": 19,
        "db_fields": ("contacted_at",),
    },
    {
        "key": "phone_at",
        "label": "Thời điểm lấy SĐT",
        "default": False,
        "width": 19,
        "db_fields": ("phone_at",),
    },
    {
        "key": "channel_type",
        "label": "Loại kênh",
        "default": False,
        "width": 16,
        "db_fields": ("page_id", "conversation_id"),
    },
    {
        "key": "conversation_id",
        "label": "Mã hội thoại",
        "default": False,
        "width": 38,
        "db_fields": ("conversation_id",),
    },
    {
        "key": "customer_id",
        "label": "Mã khách hàng",
        "default": False,
        "width": 28,
        "db_fields": ("customer_id",),
    },
    {
        "key": "post_url",
        "label": "Link bài viết / Video",
        "default": False,
        "width": 44,
        "db_fields": ("post_url",),
    },
    {
        "key": "ad_id",
        "label": "Mã quảng cáo (Ad ID)",
        "default": False,
        "width": 22,
        "db_fields": ("ad_id",),
    },
]

EXPORT_COLUMN_MAP: Dict[str, Dict[str, Any]] = {c["key"]: c for c in EXPORT_COLUMNS}
DEFAULT_COLUMN_KEYS: List[str] = [c["key"] for c in EXPORT_COLUMNS if c["default"]]
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_UNTRUSTED_TEXT_COLUMNS = {"name", "status_tag", "assigned_users", "page_name", "ad_id"}


class DataExportFilterRequest(BaseModel):
    columns: List[str] = Field(default_factory=lambda: list(DEFAULT_COLUMN_KEYS))
    channel_group: Literal["all", "zalo", "source"] = "all"
    pages: List[str] = Field(default_factory=list)
    employees: List[str] = Field(default_factory=list)
    employee_match_mode: Literal["any", "exact"] = "any"
    student_filter: Literal["all", "non_student", "student"] = "all"
    tags: List[str] = Field(default_factory=list)
    phone_filter: Literal["all", "has_phone", "no_phone"] = "all"
    date_field: Literal["contacted_at", "first_created_at"] = "contacted_at"
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    search: Optional[str] = None
    exclude_zalo_groups: bool = True
    dedupe_phone: bool = False
    sort_by: Literal["contacted_at", "first_created_at", "message_count", "name"] = "contacted_at"
    sort_dir: Literal["desc", "asc"] = "desc"


class DataExportPreviewRequest(DataExportFilterRequest):
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=10, le=100)


class DataExportDownloadRequest(DataExportFilterRequest):
    max_rows: int = Field(MAX_EXPORT_ROWS, ge=1, le=MAX_EXPORT_ROWS)
    filename: Optional[str] = None


def clear_data_export_cache() -> None:
    global _OPTIONS_CACHE
    with _OPTIONS_LOCK:
        _OPTIONS_CACHE = None
    with _PREVIEW_LOCK:
        _PREVIEW_CACHE.clear()


def _validate_columns(requested: List[str]) -> List[str]:
    clean: List[str] = []
    for col in requested or []:
        if col in EXPORT_COLUMN_MAP and col not in clean:
            clean.append(col)
    if not clean:
        raise HTTPException(status_code=400, detail="Vui lòng chọn ít nhất 1 cột dữ liệu hợp lệ.")
    return clean


def _parse_iso_date(raw: Optional[str], end_of_day: bool = False) -> Optional[datetime]:
    if not raw or not str(raw).strip():
        return None
    try:
        dt = datetime.strptime(str(raw).strip()[:10], "%Y-%m-%d")
        if end_of_day:
            return dt + timedelta(days=1)
        return dt
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Định dạng ngày không hợp lệ: {raw} (cần YYYY-MM-DD).")


def _csv_token_match(column, value: str):
    """Khớp chính xác 1 phần tử trong chuỗi ngăn cách dấu phẩy (an toàn cho cả Postgres và SQLite)."""
    v = value.strip()
    return or_(
        column.ilike(v),
        column.ilike(f"{v},%"),
        column.ilike(f"%, {v}"),
        column.ilike(f"%, {v},%"),
        column.ilike(f"%,{v}"),
        column.ilike(f"%,{v},%"),
    )


def _student_sql_expr():
    """Biểu thức SQL kiểm tra chặt học viên: tag Đã là học viên trên hội thoại này,
    hội thoại khác cùng SĐT, hoặc SĐT có trong deal_wins / sales_deals."""
    lead_alias = aliased(DimLead)
    act_alias = aliased(FactLeadActivity)

    def _has_student_tag(col):
        c = func.coalesce(col, "")
        return or_(
            c.ilike("%Đã là học viên%"),
            c.ilike("%đã là học viên%"),
            c.ilike("%da la hoc vien%"),
        )

    has_phone = and_(DimLead.phone_number.isnot(None), DimLead.phone_number != "")

    other_conv_student = and_(
        has_phone,
        exists(
            select(1)
            .select_from(lead_alias)
            .join(act_alias, act_alias.lead_id == lead_alias.id)
            .where(
                lead_alias.phone_number == DimLead.phone_number,
                _has_student_tag(act_alias.status_tag),
            )
        ),
    )
    in_deal_wins = and_(
        has_phone,
        exists(select(1).where(DealWin.phone_number == DimLead.phone_number)),
    )
    in_sales_deals = and_(
        has_phone,
        exists(select(1).where(SalesDeal.sdt == DimLead.phone_number)),
    )
    return or_(_has_student_tag(FactLeadActivity.status_tag), other_conv_student, in_deal_wins, in_sales_deals)


def _expand_page_aliases(selected_pages: List[str]) -> Set[str]:
    expanded: Set[str] = set()
    for p in selected_pages:
        clean = str(p or "").strip()
        if not clean:
            continue
        canonical = resolve_canonical_page_name(clean, fallback=clean)
        expanded.add(clean)
        expanded.add(canonical)
        for k, v in KNOWN_PAGE_NAMES.items():
            if v == canonical or k == clean:
                expanded.add(k)
                expanded.add(v)
    return expanded


def _build_where_clauses(req: DataExportFilterRequest, student_expr) -> List[Any]:
    clauses: List[Any] = []

    if req.exclude_zalo_groups:
        clauses.append(~FactLeadActivity.conversation_id.like("pzl_g_%"))

    # Kênh Zalo / Nguồn
    z_keys = list(zalo_page_keys())
    if req.channel_group == "zalo":
        clauses.append(or_(FactLeadActivity.conversation_id.like("pzl_%"), DimLead.page_id.in_(z_keys)))
    elif req.channel_group == "source":
        clauses.append(and_(~FactLeadActivity.conversation_id.like("pzl_%"), ~DimLead.page_id.in_(z_keys)))

    # Lọc danh sách Page cụ thể
    clean_pages = [p.strip() for p in (req.pages or []) if p and p.strip()]
    if clean_pages:
        expanded = _expand_page_aliases(clean_pages)
        clauses.append(DimLead.page_id.in_(list(expanded)))

    # Lọc Nhân viên
    clean_emps = [e.strip() for e in (req.employees or []) if e and e.strip()]
    if clean_emps:
        emp_conds = []
        for emp in clean_emps:
            if emp.lower() in ("chưa phân công", "chua phan cong", "__unassigned__"):
                emp_conds.append(
                    or_(
                        FactLeadActivity.assigned_users.is_(None),
                        func.trim(FactLeadActivity.assigned_users) == "",
                    )
                )
            elif req.employee_match_mode == "exact":
                emp_conds.append(func.trim(FactLeadActivity.assigned_users).ilike(emp))
            else:
                emp_conds.append(_csv_token_match(FactLeadActivity.assigned_users, emp))
        clauses.append(or_(*emp_conds))

    # Lọc Tag
    clean_tags = [t.strip() for t in (req.tags or []) if t and t.strip()]
    if clean_tags:
        tag_conds = []
        for t in clean_tags:
            if t.lower() in ("no_tag", "chưa gắn tag", "chưa gắn thẻ", "chua gan tag"):
                tag_conds.append(
                    or_(
                        FactLeadActivity.status_tag.is_(None),
                        func.trim(FactLeadActivity.status_tag) == "",
                    )
                )
            else:
                tag_conds.append(_csv_token_match(FactLeadActivity.status_tag, t))
        clauses.append(or_(*tag_conds))

    # Lọc Học viên (chỉ thêm EXISTS khi người dùng thực sự lọc)
    if req.student_filter == "non_student":
        clauses.append(~student_expr)
    elif req.student_filter == "student":
        clauses.append(student_expr)

    # Lọc SĐT
    if req.phone_filter == "has_phone":
        clauses.append(and_(DimLead.phone_number.isnot(None), func.trim(DimLead.phone_number) != ""))
    elif req.phone_filter == "no_phone":
        clauses.append(or_(DimLead.phone_number.is_(None), func.trim(DimLead.phone_number) == ""))

    # Lọc khoảng ngày
    dt_from = _parse_iso_date(req.date_from, end_of_day=False)
    dt_to = _parse_iso_date(req.date_to, end_of_day=True)
    if dt_from or dt_to:
        date_col = (
            func.coalesce(FactLeadActivity.contacted_at, DimLead.first_created_at)
            if req.date_field == "contacted_at"
            else DimLead.first_created_at
        )
        if dt_from:
            clauses.append(date_col >= dt_from)
        if dt_to:
            clauses.append(date_col < dt_to)

    # Tìm kiếm nhanh Tên / SĐT
    if req.search and req.search.strip():
        kw = f"%{req.search.strip()}%"
        clauses.append(
            or_(
                DimLead.name.ilike(kw),
                DimLead.phone_number.ilike(kw),
            )
        )

    return clauses


def _needed_db_fields(selected_columns: List[str]) -> List[str]:
    fields: List[str] = []
    for col_key in selected_columns:
        for f in EXPORT_COLUMN_MAP[col_key]["db_fields"]:
            if f not in fields:
                fields.append(f)
    return fields


def _sort_expression(sort_by: str):
    if sort_by == "first_created_at":
        return DimLead.first_created_at
    if sort_by == "message_count":
        return func.coalesce(FactLeadActivity.message_count, 0)
    if sort_by == "name":
        return func.coalesce(DimLead.name, "")
    return func.coalesce(FactLeadActivity.contacted_at, DimLead.first_created_at)


def _db_field_expression(field_name: str, student_expr):
    mapping = {
        "name": DimLead.name.label("name"),
        "phone_number": DimLead.phone_number.label("phone_number"),
        "page_id": DimLead.page_id.label("page_id"),
        "customer_id": DimLead.customer_id.label("customer_id"),
        "first_created_at": DimLead.first_created_at.label("first_created_at"),
        "phone_at": DimLead.phone_at.label("phone_at"),
        "conversation_id": FactLeadActivity.conversation_id.label("conversation_id"),
        "assigned_users": FactLeadActivity.assigned_users.label("assigned_users"),
        "status_tag": FactLeadActivity.status_tag.label("status_tag"),
        "message_count": FactLeadActivity.message_count.label("message_count"),
        "contacted_at": FactLeadActivity.contacted_at.label("contacted_at"),
        "post_url": func.coalesce(FactLeadActivity.post_url, DimLead.post_url).label("post_url"),
        "ad_id": func.coalesce(FactLeadActivity.ad_id, DimLead.ad_id).label("ad_id"),
        "is_student": student_expr.label("is_student"),
    }
    return mapping[field_name]


def _build_projected_queries(
    db: Session,
    req: DataExportFilterRequest,
    selected_columns: List[str],
):
    """Tạo cặp (count_query, data_query, needed_db_fields) với Column Projection + SQL Pushdown."""
    needed_fields = _needed_db_fields(selected_columns)
    need_student_expr = req.student_filter != "all" or "is_student" in needed_fields
    student_expr = _student_sql_expr() if need_student_expr else literal(False)

    where_clauses = _build_where_clauses(req, student_expr)
    sort_col = _sort_expression(req.sort_by)
    order_clause = sort_col.asc() if req.sort_dir == "asc" else sort_col.desc()
    tie_breaker = FactLeadActivity.id.asc() if req.sort_dir == "asc" else FactLeadActivity.id.desc()

    projected_exprs = [_db_field_expression(f, student_expr) for f in needed_fields]

    if not req.dedupe_phone:
        count_stmt = (
            select(func.count(FactLeadActivity.id))
            .select_from(FactLeadActivity)
            .join(DimLead, DimLead.id == FactLeadActivity.lead_id)
            .where(*where_clauses)
        )
        data_stmt = (
            select(*projected_exprs)
            .select_from(FactLeadActivity)
            .join(DimLead, DimLead.id == FactLeadActivity.lead_id)
            .where(*where_clauses)
            .order_by(order_clause, tie_breaker)
        )
        return count_stmt, data_stmt, needed_fields

    # Khi dedupe_phone=True: dùng partition trong SQL để mỗi SĐT chỉ trả về 1 dòng mới nhất,
    # còn các dòng chưa có SĐT vẫn giữ nguyên bằng conversation_id riêng biệt.
    dedupe_key = case(
        (and_(DimLead.phone_number.isnot(None), func.trim(DimLead.phone_number) != ""), literal("p:").concat(DimLead.phone_number)),
        else_=literal("c:").concat(FactLeadActivity.conversation_id),
    )
    count_stmt = (
        select(func.count(func.distinct(dedupe_key)))
        .select_from(FactLeadActivity)
        .join(DimLead, DimLead.id == FactLeadActivity.lead_id)
        .where(*where_clauses)
    )
    rn_col = func.row_number().over(partition_by=dedupe_key, order_by=[order_clause, tie_breaker]).label("_rn")
    sort_key_col = sort_col.label("_sort_key")
    tie_key_col = FactLeadActivity.id.label("_tie_id")

    inner = (
        select(*projected_exprs, rn_col, sort_key_col, tie_key_col)
        .select_from(FactLeadActivity)
        .join(DimLead, DimLead.id == FactLeadActivity.lead_id)
        .where(*where_clauses)
        .subquery()
    )
    outer_cols = [inner.c[f] for f in needed_fields]
    outer_order = inner.c._sort_key.asc() if req.sort_dir == "asc" else inner.c._sort_key.desc()
    outer_tie = inner.c._tie_id.asc() if req.sort_dir == "asc" else inner.c._tie_id.desc()
    data_stmt = select(*outer_cols).where(inner.c._rn == 1).order_by(outer_order, outer_tie)
    return count_stmt, data_stmt, needed_fields


def _format_dt(val: Any) -> str:
    if not val:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%d/%m/%Y %H:%M")
    return str(val)


def _format_row(row_mapping: Any, selected_columns: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for col in selected_columns:
        if col == "name":
            out[col] = row_mapping["name"] or ""
        elif col == "phone_number":
            out[col] = row_mapping["phone_number"] or ""
        elif col == "page_name":
            raw_pg = row_mapping["page_id"]
            out[col] = resolve_canonical_page_name(raw_pg, fallback=str(raw_pg or ""))
        elif col == "assigned_users":
            out[col] = (row_mapping["assigned_users"] or "").strip() or "Chưa phân công"
        elif col == "pancake_link":
            out[col] = build_pancake_url(row_mapping["conversation_id"], None, row_mapping["page_id"]) or ""
        elif col == "status_tag":
            out[col] = row_mapping["status_tag"] or ""
        elif col == "is_student":
            out[col] = "Đã là học viên" if bool(row_mapping["is_student"]) else "Chưa là học viên"
        elif col == "message_count":
            out[col] = int(row_mapping["message_count"] or 0)
        elif col == "first_created_at":
            out[col] = _format_dt(row_mapping["first_created_at"])
        elif col == "contacted_at":
            out[col] = _format_dt(row_mapping["contacted_at"])
        elif col == "phone_at":
            out[col] = _format_dt(row_mapping["phone_at"])
        elif col == "channel_type":
            is_zalo = is_zalo_channel(row_mapping["page_id"], row_mapping["conversation_id"])
            out[col] = "Zalo cá nhân" if is_zalo else "Kênh nguồn (FB/TikTok)"
        elif col == "conversation_id":
            out[col] = row_mapping["conversation_id"] or ""
        elif col == "customer_id":
            out[col] = row_mapping["customer_id"] or ""
        elif col == "post_url":
            out[col] = row_mapping["post_url"] or ""
        elif col == "ad_id":
            out[col] = row_mapping["ad_id"] or ""
    return out


def _sanitize_excel_value(col_key: str, value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (int, float)) and col_key == "message_count":
        return value
    s = ILLEGAL_CHARACTERS_RE.sub("", str(value))
    # Ngăn Excel Formula Injection trên các cột text tự do từ khách/CRM
    if col_key in _UNTRUSTED_TEXT_COLUMNS and s and s[0] in _FORMULA_PREFIXES:
        return "'" + s
    return s


def _preview_cache_key(req: DataExportPreviewRequest, selected_columns: List[str]) -> str:
    payload = req.model_dump()
    payload["columns"] = selected_columns
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@router.get("/options")
def get_data_export_options(db: Session = Depends(get_db)):
    """Lấy danh mục cột, danh sách Page, Nhân viên, Tag (nhẹ, DISTINCT không kéo conversation_id, cache 15 phút)."""
    global _OPTIONS_CACHE
    now_ts = time.time()
    with _OPTIONS_LOCK:
        if _OPTIONS_CACHE is not None and (now_ts - _OPTIONS_CACHE[0] < OPTIONS_CACHE_TTL):
            return _OPTIONS_CACHE[1]

    # 1. Pages
    page_rows = db.query(DimLead.page_id).distinct().all()
    pages_set: Set[str] = set()
    for (pg,) in page_rows:
        if pg:
            cname = resolve_canonical_page_name(pg.strip(), fallback=None)
            if cname and not is_page_id(cname):
                pages_set.add(cname)
    pages_set.update(KNOWN_PAGE_NAMES.values())
    sorted_pages = sorted(pages_set)
    zalo_pages = sorted(p for p in sorted_pages if p in ZALO_PAGE_NAMES)
    source_pages = sorted(p for p in sorted_pages if p not in ZALO_PAGE_NAMES)

    # 2. Employees (DISTINCT không kéo conversation_id → chỉ vài KB egress)
    emp_rows = (
        db.query(FactLeadActivity.assigned_users)
        .filter(FactLeadActivity.assigned_users.isnot(None), FactLeadActivity.assigned_users != "")
        .distinct()
        .all()
    )
    emp_set: Set[str] = set()
    for (users,) in emp_rows:
        for u in str(users or "").split(","):
            u_clean = u.strip()
            if u_clean and u_clean != "Chưa phân công":
                emp_set.add(u_clean)
    employees = ["Chưa phân công"] + sorted(emp_set)

    # 3. Tags (DISTINCT không kéo conversation_id → chỉ vài KB egress)
    tag_rows = (
        db.query(FactLeadActivity.status_tag)
        .filter(FactLeadActivity.status_tag.isnot(None), FactLeadActivity.status_tag != "")
        .distinct()
        .all()
    )
    tag_set: Set[str] = set()
    for (t_str,) in tag_rows:
        for t in str(t_str or "").split(","):
            t_clean = t.strip()
            if t_clean:
                tag_set.add(t_clean)
    priority_tags = ["Remind", "Đào tạo", "Lead Other", "Đã add", "Đã là học viên", "Có thông tin", "Quan tâm sâu"]
    ordered_tags = [pt for pt in priority_tags if pt in tag_set] + sorted(t for t in tag_set if t not in priority_tags)

    result = {
        "columns": [
            {
                "key": c["key"],
                "label": c["label"],
                "default": c["default"],
                "db_field_count": len(c["db_fields"]),
            }
            for c in EXPORT_COLUMNS
        ],
        "pages": sorted_pages,
        "zalo_pages": zalo_pages,
        "source_pages": source_pages,
        "employees": employees,
        "tags": ordered_tags,
        "max_export_rows": MAX_EXPORT_ROWS,
    }

    with _OPTIONS_LOCK:
        _OPTIONS_CACHE = (now_ts, result)
    return result


@router.post("/preview")
def preview_data_export(req: DataExportPreviewRequest, db: Session = Depends(get_db)):
    """Xem trước dữ liệu theo đúng bộ lọc & các cột đã tích chọn (SQL Projection + phân trang + cache 3 phút)."""
    selected_columns = _validate_columns(req.columns)
    cache_key = _preview_cache_key(req, selected_columns)
    now_ts = time.time()

    with _PREVIEW_LOCK:
        cached = _PREVIEW_CACHE.get(cache_key)
        if cached and (now_ts - cached[0] < PREVIEW_CACHE_TTL):
            _PREVIEW_CACHE.move_to_end(cache_key)
            return {**cached[1], "cached": True}

    t0 = time.perf_counter()
    count_stmt, data_stmt, needed_fields = _build_projected_queries(db, req, selected_columns)
    total = int(db.execute(count_stmt).scalar() or 0)

    offset = (req.page - 1) * req.page_size
    rows = db.execute(data_stmt.limit(req.page_size).offset(offset)).mappings().all()
    items = [_format_row(r, selected_columns) for r in rows]
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

    payload = {
        "total": total,
        "page": req.page,
        "page_size": req.page_size,
        "total_pages": max(1, (total + req.page_size - 1) // req.page_size) if total > 0 else 1,
        "columns": [
            {"key": k, "label": EXPORT_COLUMN_MAP[k]["label"]}
            for k in selected_columns
        ],
        "projected_db_fields": needed_fields,
        "rows": items,
        "query_ms": elapsed_ms,
        "cached": False,
    }

    with _PREVIEW_LOCK:
        _PREVIEW_CACHE[cache_key] = (now_ts, payload)
        _PREVIEW_CACHE.move_to_end(cache_key)
        while len(_PREVIEW_CACHE) > PREVIEW_CACHE_MAX_ITEMS:
            _PREVIEW_CACHE.popitem(last=False)

    return payload


@router.post("/export")
def download_data_export_excel(req: DataExportDownloadRequest, db: Session = Depends(get_db)):
    """Kết xuất file Excel (.xlsx) nén tối ưu băng thông, chỉ SELECT đúng các cột đã tích."""
    selected_columns = _validate_columns(req.columns)
    _, data_stmt, needed_fields = _build_projected_queries(db, req, selected_columns)

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(title="Du_Lieu_Query")

    # Cấu hình độ rộng cột trước khi ghi dòng (yêu cầu của openpyxl write_only)
    for idx, col_key in enumerate(selected_columns, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = EXPORT_COLUMN_MAP[col_key]["width"]

    header_fill = PatternFill(start_color="0A1F44", end_color="0A1F44", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_align = Alignment(horizontal="left", vertical="center")
    link_font = Font(name="Calibri", size=11, color="1E5BD6", underline="single")

    header_cells = []
    for col_key in selected_columns:
        cell = WriteOnlyCell(ws, value=EXPORT_COLUMN_MAP[col_key]["label"])
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_align
        header_cells.append(cell)
    ws.append(header_cells)

    exported_count = 0
    result_proxy = db.execute(
        data_stmt.limit(req.max_rows).execution_options(yield_per=1000)
    ).mappings()

    for r in result_proxy:
        formatted = _format_row(r, selected_columns)
        row_cells = []
        for col_key in selected_columns:
            raw_val = _sanitize_excel_value(col_key, formatted.get(col_key, ""))
            cell = WriteOnlyCell(ws, value=raw_val)
            if col_key == "phone_number" and raw_val:
                cell.number_format = "@"
                cell.data_type = "s"
            elif col_key in ("pancake_link", "post_url") and isinstance(raw_val, str) and raw_val.startswith(("https://", "http://")):
                cell.hyperlink = raw_val
                cell.font = link_font
            row_cells.append(cell)
        ws.append(row_cells)
        exported_count += 1

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    now_vn = datetime.now(VN_TZ).strftime("%Y%m%d_%H%M")
    safe_base = re.sub(r"[^a-zA-Z0-9_\-]", "_", (req.filename or "").strip())[:60]
    out_filename = f"{safe_base}.xlsx" if safe_base else f"EzTech_Query_Export_{now_vn}.xlsx"

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{out_filename}"',
            "Cache-Control": "no-store",
            "X-Export-Row-Count": str(exported_count),
            "X-Projected-Db-Columns": str(len(needed_fields)),
            "Access-Control-Expose-Headers": "Content-Disposition, X-Export-Row-Count, X-Projected-Db-Columns",
        },
    )
