"""
Module Backend Quản lý Nhập Deal & Công nợ học viên (Deal Entry & Debt Management).
Nối trực tiếp từ bảng `deal_wins` (DB Deal Win có sẵn) sang `sales_deals`:
- Tự động kéo 100% thông tin học viên từ bảng `deal_wins` (Họ tên, SĐT, Email, Năm sinh, Địa chỉ, Lĩnh vực,
  Chức vụ/Ngành nghề, Kỳ vọng, NV chăm sóc, Fanpage nguồn, Tag Pancake, Ngày contact đầu, Link Pancake).
- Những học viên mới đổ về từ `deal_wins` chưa có Số tiền thu được / Lớp học / Link nhóm 1-1 sẽ mang trạng thái
  "Chờ bổ sung" để nhân viên vào điền nốt và lưu thẳng lên DB.
- Tối ưu chống tốn băng thông Neon Egress:
  + Đồng bộ tăng trưởng theo `MAX(deal_wins.id)` (chỉ đọc dòng mới, bỏ qua cột JSON `raw_data` và `tag_timeline`).
  + In-Memory Cache cho toàn bộ danh sách Deals, Công nợ, Danh mục, Nhật ký.
  + Reconcile công nợ cô lập theo đúng SĐT vừa thay đổi (chỉ đọc/ghi 1-3 dòng).
"""

import json
import re
import time
import uuid
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Set, Tuple, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, func, or_

from database.db import get_db
from database.models import SalesDeal, DealAuditLog, AppConfig, DealWin, DimLead, FactLeadActivity
from database.schema import ensure_schema
from database.deal_sync import normalize_sale_name, pick_best_assigned_user, sync_all_deals_with_dim_leads
from etl.utils import normalize_phone, resolve_canonical_page_name, build_pancake_url

logger = logging.getLogger("DealEntryService")

router = APIRouter(prefix="/api/deal-entry", tags=["Deal Entry"])

VN_TZ = timezone(timedelta(hours=7))


def get_vn_now() -> datetime:
    return datetime.now(VN_TZ).replace(tzinfo=None)


# ───────────────────────── In-Memory Cache chống tốn Neon Egress ─────────────────────────

_CACHE_LOCK = threading.Lock()
_DEALS_CACHE: Optional[List[Dict[str, Any]]] = None
_DEALS_CACHE_TS: float = 0.0
DEALS_CACHE_TTL = 300  # 5 phút

_LISTS_CACHE: Optional[Dict[str, List[str]]] = None
_LISTS_CACHE_TS: float = 0.0
LISTS_CACHE_TTL = 600  # 10 phút

_LOGS_CACHE: Optional[List[Dict[str, Any]]] = None
_LOGS_CACHE_TS: float = 0.0
LOGS_CACHE_TTL = 300  # 5 phút

_PANCAKE_PHONE_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
PANCAKE_PHONE_TTL = 600  # 10 phút

_LAST_SYNCED_DEAL_WIN_ID: int = -1
_LAST_SYNC_CHECK_TS: float = 0.0
SYNC_CHECK_INTERVAL = 120  # Chỉ kiểm tra MAX(id) của deal_wins mỗi 2 phút (4 bytes query)
_PANCAKE_LINKS_BACKFILLED: bool = False


def invalidate_deal_entry_cache():
    """Gọi khi bảng deal_wins có dữ liệu mới từ Webhook để trang Nhập Deal cập nhật ngay."""
    global _DEALS_CACHE, _LAST_SYNCED_DEAL_WIN_ID, _LAST_SYNC_CHECK_TS, _PANCAKE_LINKS_BACKFILLED
    with _CACHE_LOCK:
        _DEALS_CACHE = None
        _LAST_SYNCED_DEAL_WIN_ID = -1
        _LAST_SYNC_CHECK_TS = 0.0
        _PANCAKE_LINKS_BACKFILLED = False


# ───────────────────────── Hằng số & Danh mục mặc định ─────────────────────────

CONFIG_KEY_LISTS = "sales_deal_lists_v1"

BASE_STATUSES = [
    "Chờ bổ sung",
    "Hoàn thành",
    "Còn nợ",
    "Thu nợ",
    "Đã thu hết nợ",
    "Đặt cọc",
    "Bảo lưu",
    "Hoàn học phí",
]

ROLES = ["Admin", "Sale", "CSKH", "Kế toán", "Viewer"]

LIST_SEED: Dict[str, List[str]] = {
    "zaloCS": [
        "Tuấn Anh data",
        "EzTech Phân tích",
        "EzTech Consultant",
        "Hiền Minh EzTech",
    ],
    "nguon": [
        "Tiktok anh kế toán làm data",
        "Tiktok hành trang kế toán",
        "Tiktok chị kế toán",
        "Tiktok chị kế toán làm báo cáo",
        "Tiktok học data",
        "Facebook Anh kế toán làm data",
        "Facebook Phân tích",
        "Facebook Giải pháp",
        "Data Talk",
    ],
    "chuongTrinh": [
        "Data Finance",
        "Data Business",
        "K2- Power Query",
        "K1- Power BI",
        "Khoá AI",
    ],
    "lop": [
        "DF-K1",
        "DF-K2",
        "DB-K1",
        "PQ-K2",
        "PBI-K1",
        "AI-K1",
    ],
}


# ───────────────────────── Hàm tiện ích chuẩn hoá & Lớp học ─────────────────────────

def clean_phone(raw: Optional[str]) -> str:
    if not raw:
        return ""
    norm = normalize_phone(str(raw))
    if norm:
        return norm
    digits = re.sub(r"\D", "", str(raw))
    if digits.startswith("84") and len(digits) >= 11:
        digits = "0" + digits[2:]
    return digits


def parse_classes(val: Any) -> List[str]:
    if not val:
        return []
    if isinstance(val, list):
        items = [str(x).strip() for x in val if str(x).strip()]
    else:
        items = [x.strip() for x in re.split(r"[,;|]", str(val)) if x.strip()]
    seen = []
    for it in items:
        if it not in seen:
            seen.append(it)
    return seen


def parse_sources(val: Any) -> List[str]:
    if not val:
        return []
    if isinstance(val, list):
        items = [str(x).strip() for x in val if str(x).strip()]
    else:
        items = [x.strip() for x in re.split(r"[,;|]", str(val)) if x.strip()]
    seen = []
    for it in items:
        if it not in seen:
            seen.append(it)
    return seen


def merge_classes(a: List[str], b: List[str]) -> List[str]:
    out = list(a or [])
    for item in (b or []):
        clean = str(item).strip()
        if clean and clean not in out:
            out.append(clean)
    return out


def same_classes(a: List[str], b: List[str]) -> bool:
    return sorted(parse_classes(a)) == sorted(parse_classes(b))


def resolve_canonical_zalo_cs(raw: Optional[str]) -> str:
    """Tự động suy ra Zalo chăm sóc tương ứng từ Fanpage/Kênh hoặc nguồn."""
    if not raw:
        return ""
    s = str(raw).strip().lower()
    if "hiền minh" in s or "hien minh" in s:
        return "Hiền Minh EzTech"
    if "tuấn anh" in s or "tuan anh" in s:
        return "Tuấn Anh data"
    if "consultant" in s:
        return "EzTech Consultant"
    if "phân tích" in s or "phan tich" in s:
        return "EzTech Phân tích"
    return ""


def format_vn_datetime(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    return dt.strftime("%d/%m/%Y %H:%M")


def is_iso_date(s: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", str(s or "").strip()))


def to_iso_date(val: Any) -> str:
    if not val:
        return ""
    s = str(val).strip()
    if is_iso_date(s):
        return s
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return s[:10] if len(s) >= 10 else ""


# ───────────────────────── Đồng bộ trực tiếp từ bảng deal_wins (Zero-Bloat Egress) ─────────────────────────

def _is_valid_pancake_conv_url(url: Optional[str]) -> bool:
    """Kiểm tra link Pancake đã là URL hội thoại hợp lệ có ?c_id= (không phải page_id đơn thuần)."""
    if not url:
        return False
    s = str(url).strip()
    if "pancake.vn/" not in s or "?c_id=" not in s:
        return False
    cid = s.split("?c_id=", 1)[1].strip()
    if not cid or cid.isdigit():
        return False
    return True


def _resolve_pancake_info_batch(
    db: Session,
    lead_ids: Set[int],
    phones: Set[str],
) -> Tuple[Dict[int, Dict[str, str]], Dict[str, Dict[str, str]]]:
    """
    Truy vấn batch thông tin ngày contact đầu và URL hội thoại Pancake chuẩn (cùng logic trang Chăm sóc Lead)
    cho tập hợp `lead_ids` và `phones` (không đọc các cột JSON nặng).
    """
    lead_info_map: Dict[int, Dict[str, Any]] = {}
    phone_info_map: Dict[str, Dict[str, Any]] = {}

    clean_ids = {int(lid) for lid in lead_ids if lid}
    clean_phones = {clean_phone(p) for p in phones if p}
    clean_phones.discard("")

    if not clean_ids and not clean_phones:
        return {}, {}

    filters = []
    if clean_ids:
        filters.append(DimLead.id.in_(clean_ids))
    if clean_phones:
        filters.append(DimLead.phone_number.in_(clean_phones))

    act_rows = (
        db.query(
            DimLead.id,
            DimLead.phone_number,
            DimLead.customer_id,
            DimLead.page_id,
            DimLead.first_created_at,
            FactLeadActivity.conversation_id,
            FactLeadActivity.status_tag,
            FactLeadActivity.message_count,
            FactLeadActivity.assigned_users,
        )
        .outerjoin(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)
        .filter(or_(*filters))
        .all()
    )

    for lid, p_num, cust_id, l_page_id, first_dt, conv_id, status_tag, msg_count, assigned_users in act_rows:
        if conv_id and str(conv_id).startswith("pzl_g_"):
            continue
        url = (
            build_pancake_url(
                conversation_id=conv_id,
                customer_id=cust_id,
                page_name_or_id=l_page_id,
            )
            or ""
        )
        tag_lower = (status_tag or "").lower()
        has_assigned = 1 if normalize_sale_name(assigned_users) else 0
        # Chỉ lấy hội thoại thuộc kênh có số lượng tin nhắn nhiều nhất
        score = (
            has_assigned,
            int(msg_count or 0),
            1 if conv_id else 0,
            1 if "học viên" in tag_lower else 0,
        )
        dt_str = first_dt.strftime("%Y-%m-%d") if first_dt else ""

        if lid:
            l_entry = lead_info_map.setdefault(lid, {"ngay_contact": "", "zalo": "", "_score": (-1, -1, -1, -1)})
            if dt_str and (not l_entry["ngay_contact"] or dt_str < l_entry["ngay_contact"]):
                l_entry["ngay_contact"] = dt_str
            if url and score > l_entry["_score"]:
                l_entry["zalo"] = url
                l_entry["_score"] = score

        c_p = clean_phone(p_num)
        if c_p:
            p_entry = phone_info_map.setdefault(c_p, {"ngay_contact": "", "zalo": "", "_score": (-1, -1, -1, -1)})
            if dt_str and (not p_entry["ngay_contact"] or dt_str < p_entry["ngay_contact"]):
                p_entry["ngay_contact"] = dt_str
            if url and score > p_entry["_score"]:
                p_entry["zalo"] = url
                p_entry["_score"] = score

    return (
        {k: {"ngay_contact": v["ngay_contact"], "zalo": v["zalo"]} for k, v in lead_info_map.items()},
        {k: {"ngay_contact": v["ngay_contact"], "zalo": v["zalo"]} for k, v in phone_info_map.items()},
    )


def _backfill_all_pancake_links(db: Session, rows: List[SalesDeal], force: bool = False) -> bool:
    """
    Điền tự động đường link hội thoại Pancake (giống trang Chăm sóc Lead) vào cột `zalo`
    cho toàn bộ học viên trong `sales_deals` đang bị trống hoặc sai định dạng link.
    """
    global _PANCAKE_LINKS_BACKFILLED
    if _PANCAKE_LINKS_BACKFILLED and not force:
        return False

    missing_rows = rows if force else [r for r in rows if not _is_valid_pancake_conv_url(r.zalo)]
    if not missing_rows:
        _PANCAKE_LINKS_BACKFILLED = True
        return False

    dw_ids = {r.deal_win_id for r in missing_rows if r.deal_win_id}
    dw_lead_map: Dict[int, int] = {}
    if dw_ids:
        dw_pairs = (
            db.query(DealWin.id, DealWin.dim_lead_id)
            .filter(DealWin.id.in_(dw_ids), DealWin.dim_lead_id.isnot(None))
            .all()
        )
        for dw_id, d_lid in dw_pairs:
            if dw_id and d_lid:
                dw_lead_map[dw_id] = d_lid

    lead_ids = set(dw_lead_map.values())
    phones = {clean_phone(r.sdt) for r in missing_rows if r.sdt}
    phones.discard("")

    lead_info_map, phone_info_map = _resolve_pancake_info_batch(db, lead_ids, phones)

    updated = False
    for r in missing_rows:
        lid = dw_lead_map.get(r.deal_win_id or 0, 0)
        c_p = clean_phone(r.sdt)
        l_info = lead_info_map.get(lid, {})
        p_info = phone_info_map.get(c_p, {})

        best_zalo = p_info.get("zalo") or l_info.get("zalo") or ""
        best_contact = p_info.get("ngay_contact") or l_info.get("ngay_contact") or ""

        if best_zalo and r.zalo != best_zalo:
            r.zalo = best_zalo
            updated = True
        if best_contact and not r.ngay_contact:
            r.ngay_contact = best_contact
            updated = True

    _PANCAKE_LINKS_BACKFILLED = True
    return updated


def sync_from_deal_wins(db: Session, force: bool = False) -> int:
    """
    Nối trực tiếp dữ liệu học viên từ bảng `deal_wins` sang `sales_deals`:
    - Chỉ kiểm tra `SELECT MAX(id) FROM deal_wins` (4 bytes). Nếu không có dòng mới và không force -> tốn 0 Egress.
    - Khi có học viên mới trong `deal_wins`, chỉ SELECT đúng các cột thông tin (bỏ qua `raw_data` JSON)
      và nạp thông tin ngày contact đầu / link Pancake từ `dim_leads` (bỏ qua `tag_timeline` JSONB).
    - Không bao giờ ghi đè lên Số tiền thu được, Lớp học, Chương trình học, Link nhóm 1-1 mà nhân viên đã điền.
    """
    global _LAST_SYNCED_DEAL_WIN_ID, _LAST_SYNC_CHECK_TS, _DEALS_CACHE
    now_ts = time.time()

    if not force and _LAST_SYNCED_DEAL_WIN_ID >= 0 and (now_ts - _LAST_SYNC_CHECK_TS) < SYNC_CHECK_INTERVAL:
        return 0

    if force:
        sync_all_deals_with_dim_leads(db, full_scan=True)

    max_dw_id = db.query(func.max(DealWin.id)).scalar() or 0
    _LAST_SYNC_CHECK_TS = now_ts

    if not force and _LAST_SYNCED_DEAL_WIN_ID >= max_dw_id:
        return 0

    # Lấy tập hợp các deal_win_id đã có trong sales_deals (chỉ đọc 1 cột integer)
    existing_dw_rows = (
        db.query(SalesDeal.deal_win_id)
        .filter(SalesDeal.deal_win_id.isnot(None))
        .all()
    )
    existing_dw_ids = {r[0] for r in existing_dw_rows if r[0] is not None}

    # Chỉ truy vấn những bản ghi DealWin chưa có trong sales_deals (KHÔNG đọc raw_data)
    dw_query = db.query(
        DealWin.id,
        DealWin.timestamp,
        DealWin.email,
        DealWin.full_name,
        DealWin.phone_number,
        DealWin.birth_year,
        DealWin.address,
        DealWin.industry,
        DealWin.job_title,
        DealWin.expectation,
        DealWin.care_by,
        DealWin.page_id,
        DealWin.dim_lead_id,
        DealWin.is_student,
        DealWin.lead_tag,
    )

    if existing_dw_ids and not force:
        dw_query = dw_query.filter(~DealWin.id.in_(existing_dw_ids))

    dw_rows = dw_query.order_by(asc(DealWin.id)).all()
    new_dw_rows = [r for r in dw_rows if r.id not in existing_dw_ids]

    if force and existing_dw_ids:
        dw_by_id = {r.id: r for r in dw_rows}
        linked_sales = db.query(SalesDeal).filter(SalesDeal.deal_win_id.isnot(None)).all()
        sync_dirty = False
        for sd in linked_sales:
            dw = dw_by_id.get(sd.deal_win_id)
            if not dw:
                continue
            new_nv = (dw.care_by or "").strip()
            if new_nv == "Chưa phân công":
                new_nv = ""
            new_nguon = resolve_canonical_page_name(dw.page_id, fallback=dw.page_id) if dw.page_id else ""
            new_is_student = bool(dw.is_student) if dw.is_student is not None else True
            new_tag = (dw.lead_tag or "").strip()
            if (sd.nv_cs or "") != new_nv:
                sd.nv_cs = new_nv
                sync_dirty = True
            if (sd.nguon or "") != new_nguon:
                sd.nguon = new_nguon
                sync_dirty = True
            new_zalo_cs = resolve_canonical_zalo_cs(dw.page_id or new_nguon)
            if new_zalo_cs and (sd.zalo_cs or "") != new_zalo_cs:
                sd.zalo_cs = new_zalo_cs
                sync_dirty = True
            if sd.is_student != new_is_student:
                sd.is_student = new_is_student
                sync_dirty = True
            if (sd.lead_tag or "") != new_tag:
                sd.lead_tag = new_tag
                sync_dirty = True
        if sync_dirty:
            db.commit()
            with _CACHE_LOCK:
                _DEALS_CACHE = None

    if not new_dw_rows:
        _LAST_SYNCED_DEAL_WIN_ID = max_dw_id
        return 0

    # Batch lấy thông tin ngày contact đầu và link hội thoại Pancake cho các dim_lead_id và phone_number
    lead_ids = {r.dim_lead_id for r in new_dw_rows if r.dim_lead_id}
    phones_to_check = {clean_phone(r.phone_number) for r in new_dw_rows if r.phone_number}
    phones_to_check.discard("")

    lead_info_map, phone_pancake_map = _resolve_pancake_info_batch(db, lead_ids, phones_to_check)

    # Lấy lớp học đã có theo SĐT (để đồng bộ nếu học viên đã có dòng trước đó)
    phone_classes_map: Dict[str, str] = {}
    if phones_to_check:
        existing_phone_lop = (
            db.query(SalesDeal.sdt, SalesDeal.lop)
            .filter(SalesDeal.sdt.in_(phones_to_check), SalesDeal.lop.isnot(None), SalesDeal.lop != "")
            .all()
        )
        for p_sdt, p_lop in existing_phone_lop:
            if p_sdt and p_lop:
                phone_classes_map[p_sdt] = p_lop

    now = get_vn_now()
    today_iso = now.strftime("%Y-%m-%d")
    added_count = 0

    for r in new_dw_rows:
        phone = clean_phone(r.phone_number) or (str(r.phone_number or "").strip())
        ho_ten = (r.full_name or "").strip() or "Học viên"
        if not phone and not ho_ten:
            continue

        ngay_thu = r.timestamp.strftime("%Y-%m-%d") if r.timestamp else today_iso
        l_info = lead_info_map.get(r.dim_lead_id or 0, {})
        p_info = phone_pancake_map.get(phone, {})
        ngay_contact = l_info.get("ngay_contact") or p_info.get("ngay_contact") or ""
        zalo_link = l_info.get("zalo") or p_info.get("zalo") or ""
        nguon_name = resolve_canonical_page_name(r.page_id, fallback=r.page_id) if r.page_id else ""

        new_deal = SalesDeal(
            deal_uid=str(uuid.uuid4()),
            deal_win_id=r.id,
            ngay_thu=ngay_thu,
            ngay_contact=ngay_contact,
            sdt=phone,
            ho_ten=ho_ten,
            email=(r.email or "").strip(),
            nam_sinh=(r.birth_year or "").strip(),
            dia_chi=(r.address or "").strip(),
            linh_vuc=(r.industry or "").strip(),
            chuc_vu=(r.job_title or "").strip(),
            ky_vong=(r.expectation or "").strip(),
            is_student=bool(r.is_student) if r.is_student is not None else True,
            lead_tag=(r.lead_tag or "").strip(),
            zalo=zalo_link,
            nhom_cs="",
            chuong_trinh="",
            lop=phone_classes_map.get(phone, ""),
            nv_cs=(r.care_by or "").strip(),
            zalo_cs=resolve_canonical_zalo_cs(r.page_id or nguon_name),
            nguon=nguon_name,
            da_thu=0,
            phai_thu=0,
            tong_tien=0,
            ngay_thu_ar="",
            trang_thai="Chờ bổ sung",
            note="",
            nguoi_nhap="DealWin Sync",
            tao_luc=r.timestamp or now,
            thu_no=0,
            da_thu_no=0,
            con_no=0,
        )
        db.add(new_deal)
        added_count += 1

    if added_count > 0:
        db.commit()
        with _CACHE_LOCK:
            _DEALS_CACHE = None

    _LAST_SYNCED_DEAL_WIN_ID = max_dw_id
    return added_count


# ───────────────────────── Thuật toán Đối trừ Công nợ FIFO (settleDebts) ─────────────────────────

def settle_debts(deals: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Tính toán công nợ tự động theo nguyên tắc FIFO cho từng SĐT.
    - Nếu deal từ bảng `deal_wins` mới đồng bộ sang chưa nhập tiền (`daThu == 0` và `phaiThu == 0`),
      giữ trạng thái "Chờ bổ sung" để nhân viên nhận biết và điền nốt.
    """
    res: Dict[str, Dict[str, Any]] = {}
    by_phone: Dict[str, List[Dict[str, Any]]] = {}

    for d in deals:
        did = d["id"]
        da_thu = int(d.get("daThu") or 0)
        phai_thu = int(d.get("phaiThu") or 0)
        trang_thai = str(d.get("trangThai") or "").strip()
        ngay_thu_ar = str(d.get("ngayThuAR") or "").strip()

        if da_thu == 0 and phai_thu == 0:
            default_st = trang_thai if trang_thai in ("Bảo lưu", "Hoàn học phí") else "Chờ bổ sung"
        elif phai_thu > 0:
            default_st = "Còn nợ"
        else:
            default_st = "Hoàn thành" if trang_thai in ("", "Chờ bổ sung", "Còn nợ") else trang_thai

        res[did] = {
            "thuNo": 0,
            "daThuNo": 0,
            "conNo": max(0, phai_thu),
            "apps": [],
            "trangThai": default_st,
            "ngayThuAR": ngay_thu_ar,
        }

        phone = d.get("sdt") or ""
        if phone:
            by_phone.setdefault(phone, []).append(d)

    for phone, group in by_phone.items():
        sorted_group = sorted(
            group,
            key=lambda x: (x.get("ngayThu") or "9999-99-99", x.get("_sort_id") or 0)
        )

        open_debts: List[Dict[str, Any]] = []

        for d in sorted_group:
            did = d["id"]
            r = res[did]
            da_thu = int(d.get("daThu") or 0)
            phai_thu = int(d.get("phaiThu") or 0)
            tong_tien = int(d.get("tongTien") or 0)
            trang_thai_lower = str(d.get("trangThai") or "").strip().lower()

            if da_thu == 0 and phai_thu == 0:
                continue

            is_debt_payment_row = (
                trang_thai_lower in ("thu nợ", "thu no", "trả nợ", "thanh toán công nợ")
                or (
                    len(open_debts) > 0
                    and phai_thu == 0
                    and da_thu > 0
                    and not str(d.get("chuongTrinh") or "").strip()
                    and not d.get("dealWinId")
                )
            )

            available_for_debt = 0
            if is_debt_payment_row:
                available_for_debt = da_thu
            elif len(open_debts) > 0 and tong_tien > 0 and da_thu > tong_tien and phai_thu == 0:
                available_for_debt = da_thu - tong_tien

            if available_for_debt > 0 and open_debts:
                rem_pay = available_for_debt
                used_for_debt = 0
                for debt_item in open_debts:
                    if rem_pay <= 0:
                        break
                    debt_id = debt_item["id"]
                    debt_res = res[debt_id]
                    need = debt_res["conNo"]
                    if need <= 0:
                        continue
                    apply_amt = min(rem_pay, need)
                    debt_res["daThuNo"] += apply_amt
                    debt_res["conNo"] -= apply_amt
                    debt_res["apps"].append({
                        "ngay": d.get("ngayThu") or "",
                        "soTien": apply_amt,
                        "dealId": did,
                    })
                    if d.get("ngayThu"):
                        debt_res["ngayThuAR"] = d["ngayThu"]
                    if debt_res["conNo"] <= 0:
                        debt_res["trangThai"] = "Đã thu hết nợ"
                    else:
                        debt_res["trangThai"] = "Còn nợ"

                    rem_pay -= apply_amt
                    used_for_debt += apply_amt

                r["thuNo"] = used_for_debt
                if is_debt_payment_row:
                    r["trangThai"] = "Thu nợ"

            if phai_thu > 0:
                r["conNo"] = phai_thu - r["daThuNo"]
                if r["conNo"] > 0:
                    if trang_thai_lower not in ("bảo lưu", "hoàn học phí"):
                        r["trangThai"] = "Còn nợ"
                    open_debts.append(d)
                else:
                    r["trangThai"] = "Đã thu hết nợ"
            else:
                if not is_debt_payment_row and r["trangThai"] in ("", "Chờ bổ sung", "Còn nợ"):
                    r["trangThai"] = "Hoàn thành"

    return res


# ───────────────────────── Đọc / Ghi Danh mục & Deal (Có Cache RAM) ─────────────────────────

def read_lists(db: Session, use_cache: bool = True) -> Dict[str, List[str]]:
    global _LISTS_CACHE, _LISTS_CACHE_TS
    now_ts = time.time()
    if use_cache and _LISTS_CACHE is not None and (now_ts - _LISTS_CACHE_TS) < LISTS_CACHE_TTL:
        return {k: list(v) for k, v in _LISTS_CACHE.items()}

    cfg = db.query(AppConfig).filter(AppConfig.config_key == CONFIG_KEY_LISTS).first()
    if not cfg or not cfg.config_value:
        lists_data = {k: list(v) for k, v in LIST_SEED.items()}
        cfg = AppConfig(
            config_key=CONFIG_KEY_LISTS,
            config_value=json.dumps(lists_data, ensure_ascii=False),
        )
        db.add(cfg)
        db.commit()
        with _CACHE_LOCK:
            _LISTS_CACHE = lists_data
            _LISTS_CACHE_TS = now_ts
        return lists_data

    try:
        parsed = json.loads(cfg.config_value)
        out = {}
        for k, default_vals in LIST_SEED.items():
            vals = parsed.get(k)
            if isinstance(vals, list):
                out[k] = [str(x).strip() for x in vals if str(x).strip()]
            else:
                out[k] = list(default_vals)
        with _CACHE_LOCK:
            _LISTS_CACHE = out
            _LISTS_CACHE_TS = now_ts
        return {k: list(v) for k, v in out.items()}
    except Exception:
        return {k: list(v) for k, v in LIST_SEED.items()}


def write_lists(db: Session, lists_data: Dict[str, List[str]]) -> Dict[str, List[str]]:
    global _LISTS_CACHE, _LISTS_CACHE_TS
    cleaned: Dict[str, List[str]] = {}
    for k in LIST_SEED.keys():
        raw_list = lists_data.get(k) or []
        seen = []
        for item in raw_list:
            s = str(item).strip()
            if s and s not in seen:
                seen.append(s)
        cleaned[k] = seen

    cfg = db.query(AppConfig).filter(AppConfig.config_key == CONFIG_KEY_LISTS).first()
    if not cfg:
        cfg = AppConfig(
            config_key=CONFIG_KEY_LISTS,
            config_value=json.dumps(cleaned, ensure_ascii=False),
        )
        db.add(cfg)
    else:
        cfg.config_value = json.dumps(cleaned, ensure_ascii=False)
        cfg.updated_at = get_vn_now()
    db.commit()

    with _CACHE_LOCK:
        _LISTS_CACHE = {k: list(v) for k, v in cleaned.items()}
        _LISTS_CACHE_TS = time.time()
    return cleaned


def model_to_dict(row: SalesDeal) -> Dict[str, Any]:
    da_thu = int(row.da_thu or 0)
    phai_thu = int(row.phai_thu or 0)
    lop_list = parse_classes(row.lop)
    nhom_cs = row.nhom_cs or ""
    # Đánh dấu dòng còn thiếu thông tin cần nhân viên điền nốt (Số tiền / Lớp học / Nhóm 1-1)
    is_incomplete = (da_thu == 0 and phai_thu == 0) or len(lop_list) == 0 or not nhom_cs.strip()

    return {
        "_sort_id": row.id,
        "id": row.deal_uid,
        "dealWinId": row.deal_win_id,
        "ngayThu": row.ngay_thu or "",
        "ngayContact": row.ngay_contact or "",
        "sdt": row.sdt or "",
        "hoTen": row.ho_ten or "",
        "email": row.email or "",
        "namSinh": row.nam_sinh or "",
        "diaChi": row.dia_chi or "",
        "linhVuc": row.linh_vuc or "",
        "kyVong": row.ky_vong or "",
        "isStudent": bool(row.is_student) if row.is_student is not None else True,
        "leadTag": row.lead_tag or "",
        "zalo": row.zalo or "",
        "nhomCS": nhom_cs,
        "chuongTrinh": row.chuong_trinh or "",
        "lop": lop_list,
        "chucVu": row.chuc_vu or "",
        "nvCS": row.nv_cs or "",
        "zaloCS": row.zalo_cs or resolve_canonical_zalo_cs(row.nguon) or "",
        "nguon": row.nguon or "",
        "daThu": da_thu,
        "phaiThu": phai_thu,
        "tongTien": int(row.tong_tien or 0),
        "ngayThuAR": row.ngay_thu_ar or "",
        "trangThai": row.trang_thai or "",
        "note": row.note or "",
        "nguoiNhap": row.nguoi_nhap or "",
        "taoLuc": format_vn_datetime(row.tao_luc),
        "nguoiSua": row.nguoi_sua or "",
        "suaLuc": format_vn_datetime(row.sua_luc),
        "thuNo": int(row.thu_no or 0),
        "daThuNo": int(row.da_thu_no or 0),
        "conNo": int(row.con_no or 0),
        "isIncomplete": is_incomplete,
        "apps": [],
    }


def get_cached_deals(db: Session, force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    Tự động kiểm tra và nối dữ liệu mới từ `deal_wins` sang `sales_deals`,
    sau đó trả về danh sách deals từ RAM Cache (tốn 0 bytes Neon Egress cho các lần đọc tiếp theo).
    """
    global _DEALS_CACHE, _DEALS_CACHE_TS
    sync_from_deal_wins(db, force=force_refresh)

    now_ts = time.time()
    if not force_refresh and _DEALS_CACHE is not None and (now_ts - _DEALS_CACHE_TS) < DEALS_CACHE_TTL:
        return _DEALS_CACHE

    rows = db.query(SalesDeal).order_by(asc(SalesDeal.ngay_thu), asc(SalesDeal.id)).all()
    backfilled = _backfill_all_pancake_links(db, rows, force=force_refresh)
    deals = [model_to_dict(r) for r in rows]
    res = settle_debts(deals)

    row_map = {r.deal_uid: r for r in rows}
    dirty = backfilled

    for d in deals:
        did = d["id"]
        r = res[did]
        db_row = row_map[did]

        if (
            db_row.thu_no != r["thuNo"]
            or db_row.da_thu_no != r["daThuNo"]
            or db_row.con_no != r["conNo"]
            or (db_row.trang_thai or "") != r["trangThai"]
            or (db_row.ngay_thu_ar or "") != r["ngayThuAR"]
        ):
            db_row.thu_no = r["thuNo"]
            db_row.da_thu_no = r["daThuNo"]
            db_row.con_no = r["conNo"]
            db_row.trang_thai = r["trangThai"]
            db_row.ngay_thu_ar = r["ngayThuAR"]
            dirty = True

        d["thuNo"] = r["thuNo"]
        d["daThuNo"] = r["daThuNo"]
        d["conNo"] = r["conNo"]
        d["apps"] = r["apps"]
        d["trangThai"] = r["trangThai"]
        d["ngayThuAR"] = r["ngayThuAR"]

    if dirty:
        db.commit()

    deals.sort(key=lambda x: (x.get("ngayThu") or "", x.get("_sort_id") or 0), reverse=True)
    with _CACHE_LOCK:
        _DEALS_CACHE = deals
        _DEALS_CACHE_TS = time.time()
    return deals


def reconcile_phones_and_update_cache(db: Session, phones: Set[str]) -> List[Dict[str, Any]]:
    """
    Tối ưu Egress: Khi thêm/sửa/xoá 1 deal, công nợ chỉ thay đổi trên đúng SĐT của deal đó.
    Chỉ SELECT các dòng thuộc `phones` (1-3 dòng), tính lại công nợ và cập nhật trực tiếp vào _DEALS_CACHE trong RAM!
    """
    global _DEALS_CACHE, _DEALS_CACHE_TS
    valid_phones = {p for p in phones if p}
    if not valid_phones:
        return get_cached_deals(db)

    phone_rows = (
        db.query(SalesDeal)
        .filter(SalesDeal.sdt.in_(valid_phones))
        .order_by(asc(SalesDeal.ngay_thu), asc(SalesDeal.id))
        .all()
    )
    phone_deals = [model_to_dict(r) for r in phone_rows]
    res = settle_debts(phone_deals)

    row_map = {r.deal_uid: r for r in phone_rows}
    dirty = False

    for d in phone_deals:
        did = d["id"]
        r = res[did]
        db_row = row_map[did]

        if (
            db_row.thu_no != r["thuNo"]
            or db_row.da_thu_no != r["daThuNo"]
            or db_row.con_no != r["conNo"]
            or (db_row.trang_thai or "") != r["trangThai"]
            or (db_row.ngay_thu_ar or "") != r["ngayThuAR"]
        ):
            db_row.thu_no = r["thuNo"]
            db_row.da_thu_no = r["daThuNo"]
            db_row.con_no = r["conNo"]
            db_row.trang_thai = r["trangThai"]
            db_row.ngay_thu_ar = r["ngayThuAR"]
            dirty = True

        d["thuNo"] = r["thuNo"]
        d["daThuNo"] = r["daThuNo"]
        d["conNo"] = r["conNo"]
        d["apps"] = r["apps"]
        d["trangThai"] = r["trangThai"]
        d["ngayThuAR"] = r["ngayThuAR"]

    if dirty:
        db.commit()

    if _DEALS_CACHE is not None:
        with _CACHE_LOCK:
            remaining = [d for d in _DEALS_CACHE if d.get("sdt") not in valid_phones]
            combined = remaining + phone_deals
            combined.sort(key=lambda x: (x.get("ngayThu") or "", x.get("_sort_id") or 0), reverse=True)
            _DEALS_CACHE = combined
            _DEALS_CACHE_TS = time.time()
            return _DEALS_CACHE

    return get_cached_deals(db, force_refresh=True)


def build_debt_summary(deals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Tạo bảng Công nợ từ danh sách deals trong RAM (tốn 0 DB query)."""
    open_deals = [d for d in deals if int(d.get("conNo") or 0) > 0]
    open_deals.sort(key=lambda x: (x.get("ngayThu") or "9999-99-99", x.get("_sort_id") or 0))

    items = []
    total_phai_thu = 0
    total_da_thu_no = 0
    total_con_no = 0

    for d in open_deals:
        apps = d.get("apps") or []
        last_pay = apps[-1]["ngay"] if apps else ""
        ngay_thu = d.get("ngayThu") or ""
        thang_ps = f"{ngay_thu[5:7]}/{ngay_thu[:4]}" if len(ngay_thu) >= 7 else ""

        phai_thu = int(d.get("phaiThu") or 0)
        da_thu_no = int(d.get("daThuNo") or 0)
        con_no = int(d.get("conNo") or 0)

        total_phai_thu += phai_thu
        total_da_thu_no += da_thu_no
        total_con_no += con_no

        items.append({
            "id": d["id"],
            "sdt": d["sdt"],
            "hoTen": d["hoTen"],
            "ngayThuGoc": ngay_thu,
            "thangPhatSinh": thang_ps,
            "phaiThuBanDau": phai_thu,
            "daThuNo": da_thu_no,
            "conNo": con_no,
            "lanThuGanNhat": last_pay,
            "nvCS": d.get("nvCS") or "",
            "nguoiNhap": d.get("nguoiNhap") or "",
            "lop": d.get("lop") or [],
            "chuongTrinh": d.get("chuongTrinh") or "",
            "note": d.get("note") or "",
        })

    return {
        "items": items,
        "totalPhaiThu": total_phai_thu,
        "totalDaThuNo": total_da_thu_no,
        "totalConNo": total_con_no,
        "count": len(items),
    }


def write_audit_log(db: Session, user_email: str, action: str, deal_id: str, detail: Any):
    global _LOGS_CACHE
    try:
        text = json.dumps(detail or {}, ensure_ascii=False)
        if len(text) > 1000:
            text = text[:1000] + "…"
        log_row = DealAuditLog(
            created_at=get_vn_now(),
            user_email=user_email or "admin",
            action=action,
            deal_id=deal_id or "",
            detail=text,
        )
        db.add(log_row)
        db.commit()
        with _CACHE_LOCK:
            _LOGS_CACHE = None
    except Exception as e:
        logger.warning(f"Không thể ghi audit log: {e}")


# ───────────────────────── Schemas Request ─────────────────────────

class DealSavePayload(BaseModel):
    id: Optional[str] = None
    ngayThu: str
    ngayContact: Optional[str] = ""
    sdt: str
    hoTen: str
    email: Optional[str] = ""
    namSinh: Optional[str] = ""
    diaChi: Optional[str] = ""
    linhVuc: Optional[str] = ""
    kyVong: Optional[str] = ""
    zalo: Optional[str] = ""
    nhomCS: Optional[str] = ""
    chuongTrinh: Optional[str] = ""
    lop: List[str] = Field(default_factory=list)
    chucVu: Optional[str] = ""
    nvCS: Optional[str] = ""
    zaloCS: Optional[str] = ""
    nguon: Optional[Union[str, List[str]]] = ""
    daThu: int = 0
    phaiThu: int = 0
    tongTien: Optional[int] = None
    ngayThuAR: Optional[str] = ""
    trangThai: Optional[str] = ""
    note: Optional[str] = ""
    actor: Optional[str] = "admin"


class SetClassesPayload(BaseModel):
    lop: List[str] = Field(default_factory=list)
    actor: Optional[str] = "admin"


class SaveListsPayload(BaseModel):
    lists: Dict[str, List[str]]
    actor: Optional[str] = "admin"


# ───────────────────────── API Endpoints ─────────────────────────

@router.get("/init")
def init_deal_entry(force: bool = Query(False), db: Session = Depends(get_db)):
    """Khởi tạo dữ liệu cho trang Quản lý Nhập Deal & Công nợ (Tự động nối từ deal_wins + Đọc từ RAM Cache)."""
    ensure_schema()
    lists = read_lists(db, use_cache=not force)
    deals = get_cached_deals(db, force_refresh=force)
    debts = build_debt_summary(deals)

    return {
        "ok": True,
        "statuses": BASE_STATUSES,
        "lists": lists,
        "deals": deals,
        "debts": debts,
    }


def _lookup_pancake_lightweight(db: Session, phone: str) -> Dict[str, Any]:
    """
    Tra cứu thông tin khách trên Pancake cực nhẹ (Zero-Bloat Egress):
    - Kiểm tra _PANCAKE_PHONE_CACHE trong RAM trước.
    - Chỉ SELECT 5 cột scalar nhỏ bằng .with_entities(), tuyệt đối không đọc JSONB tag_timeline hay contacted_dates.
    - Dùng exact match trên index ix_dim_leads_phone_number.
    """
    now_ts = time.time()
    cached = _PANCAKE_PHONE_CACHE.get(phone)
    if cached and (now_ts - cached[0]) < PANCAKE_PHONE_TTL:
        return cached[1]

    rows = (
        db.query(DimLead, FactLeadActivity)
        .outerjoin(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)
        .with_entities(
            DimLead.name,
            DimLead.first_created_at,
            DimLead.page_id,
            DimLead.customer_id,
            FactLeadActivity.conversation_id,
            FactLeadActivity.assigned_users,
            FactLeadActivity.status_tag,
            FactLeadActivity.message_count,
        )
        .filter(DimLead.phone_number == phone)
        .order_by(asc(DimLead.first_created_at))
        .limit(15)
        .all()
    )

    if not rows:
        with _CACHE_LOCK:
            _PANCAKE_PHONE_CACHE[phone] = (now_ts, {})
        return {}

    lead_name = rows[0][0] or ""
    first_dt = rows[0][1]
    first_contact = first_dt.strftime("%Y-%m-%d") if first_dt else ""
    zalo_url = ""
    best_score = (-1, -1, -1, -1)
    source_page = ""
    conv_items: List[Dict[str, Any]] = []

    for idx, (name, _, page_id, cust_id, conv_id, assigned_users, status_tag, msg_count) in enumerate(rows):
        if name and not lead_name:
            lead_name = name
        pg_name = resolve_canonical_page_name(page_id) if page_id else ""

        if conv_id and str(conv_id).startswith("pzl_g_"):
            continue

        conv_items.append({
            "lead_id": idx,
            "page_id": pg_name,
            "status_tag": status_tag or "",
            "assigned": assigned_users or "",
            "message_count": int(msg_count or 0),
        })

        candidate_url = (
            build_pancake_url(
                conversation_id=conv_id,
                customer_id=cust_id,
                page_name_or_id=page_id,
            )
            or ""
        )
        score = (
            1 if normalize_sale_name(assigned_users) else 0,
            int(msg_count or 0),
            1 if conv_id else 0,
            1 if "học viên" in (status_tag or "").lower() else 0,
        )
        if score > best_score:
            best_score = score
            if candidate_url:
                zalo_url = candidate_url
            if pg_name:
                source_page = pg_name

    assigned_sale = pick_best_assigned_user(conv_items) or ""

    info = {
        "foundInPancake": True,
        "hoTen": lead_name,
        "ngayContact": first_contact,
        "zalo": zalo_url,
        "nguon": source_page,
        "zaloCS": resolve_canonical_zalo_cs(source_page),
        "nvCS": assigned_sale,
    }
    with _CACHE_LOCK:
        _PANCAKE_PHONE_CACHE[phone] = (now_ts, info)
    return info


@router.get("/lookup-phone")
def lookup_phone(
    sdt: str = Query(..., description="Số điện thoại cần tra cứu"),
    exclude_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Tra cứu SĐT siêu tốc và tiết kiệm Egress:
    - Phần lịch sử Deal & Công nợ đọc 100% từ _DEALS_CACHE trong RAM (0 câu query DB).
    - Phần Pancake dùng _lookup_pancake_lightweight (Index Scan + RAM Cache).
    """
    ensure_schema()
    phone = clean_phone(sdt)
    if not phone or len(phone) < 9:
        return {"ok": True, "found": False}

    deals = get_cached_deals(db)
    hit = None
    debt = 0
    since = ""
    all_classes: List[str] = []
    previous_deals = []

    for d in deals:
        if d["sdt"] != phone:
            continue
        if exclude_id and d["id"] == exclude_id:
            continue
        if not hit:
            hit = d
        all_classes = merge_classes(all_classes, d.get("lop") or [])
        con_no = int(d.get("conNo") or 0)
        if con_no > 0:
            debt += con_no
            ngay_thu = d.get("ngayThu") or ""
            if not since or (ngay_thu and ngay_thu < since):
                since = ngay_thu
        previous_deals.append({
            "id": d["id"],
            "ngayThu": d["ngayThu"],
            "chuongTrinh": d["chuongTrinh"],
            "daThu": d["daThu"],
            "phaiThu": d["phaiThu"],
            "conNo": d["conNo"],
            "trangThai": d["trangThai"],
        })

    pancake_info = _lookup_pancake_lightweight(db, phone)

    if not hit and not pancake_info:
        return {"ok": True, "found": False}

    return {
        "ok": True,
        "found": True,
        "foundInDeals": hit is not None,
        "hoTen": (hit["hoTen"] if hit else pancake_info.get("hoTen")) or "",
        "email": (hit.get("email") if hit else "") or "",
        "namSinh": (hit.get("namSinh") if hit else "") or "",
        "diaChi": (hit.get("diaChi") if hit else "") or "",
        "linhVuc": (hit.get("linhVuc") if hit else "") or "",
        "kyVong": (hit.get("kyVong") if hit else "") or "",
        "chucVu": (hit.get("chucVu") if hit else "") or "",
        "zalo": (hit.get("zalo") if hit else pancake_info.get("zalo")) or "",
        "nhomCS": (hit.get("nhomCS") if hit else "") or "",
        "nvCS": (hit.get("nvCS") if hit else pancake_info.get("nvCS")) or "",
        "zaloCS": (
            (hit.get("zaloCS") or resolve_canonical_zalo_cs(hit.get("nguon")))
            if hit
            else pancake_info.get("zaloCS")
        ) or "",
        "nguon": (hit.get("nguon") if hit else pancake_info.get("nguon")) or "",
        "ngayContact": (hit.get("ngayContact") if hit else pancake_info.get("ngayContact")) or "",
        "lop": all_classes,
        "conNo": debt,
        "noTuNgay": since,
        "previousDeals": previous_deals,
        "pancake": pancake_info,
    }


@router.post("/deals")
def save_deal(payload: DealSavePayload, db: Session = Depends(get_db)):
    """
    Thêm mới hoặc Điền bổ sung / Cập nhật Deal:
    - Lưu đầy đủ thông tin Số tiền thu được, Phải thu, Lớp học, Link nhóm 1-1, Ghi chú...
    - Nếu dòng này được nối từ `deal_wins` (`deal_win_id`), đồng bộ ngược các trường thông tin học viên
      (`ho_ten`, `sdt`, `email`, `nam_sinh`, `dia_chi`, `linh_vuc`, `chuc_vu`, `ky_vong`, `nv_cs`) về bảng `deal_wins`.
    - Chỉ reconcile đúng SĐT bị ảnh hưởng để tiết kiệm tối đa Egress.
    """
    ensure_schema()
    phone = clean_phone(payload.sdt)
    if not phone:
        raise HTTPException(status_code=400, detail="Số điện thoại không hợp lệ")
    ho_ten = (payload.hoTen or "").strip()
    if not ho_ten:
        raise HTTPException(status_code=400, detail="Vui lòng nhập Họ tên học viên")
    ngay_thu = to_iso_date(payload.ngayThu)
    if not ngay_thu:
        raise HTTPException(status_code=400, detail="Vui lòng chọn Ngày thu tiền hợp lệ")

    da_thu = max(0, int(payload.daThu or 0))
    phai_thu = max(0, int(payload.phaiThu or 0))
    tong_tien = int(payload.tongTien) if payload.tongTien is not None else (da_thu + phai_thu)
    if tong_tien == 0 and (da_thu > 0 or phai_thu > 0):
        tong_tien = da_thu + phai_thu

    classes = parse_classes(payload.lop)
    actor = (payload.actor or "admin").strip()
    now = get_vn_now()

    same_phone_rows = db.query(SalesDeal).filter(SalesDeal.sdt == phone).all()
    existing_phone_classes: List[str] = []
    for r in same_phone_rows:
        if payload.id and r.deal_uid == payload.id:
            continue
        existing_phone_classes = merge_classes(existing_phone_classes, parse_classes(r.lop))

    merged_classes = classes if classes else existing_phone_classes
    sources = parse_sources(payload.nguon)
    nguon_str = ", ".join(sources)

    lists = read_lists(db)
    lop_list = list(lists.get("lop") or [])
    list_changed = False
    for c in merged_classes:
        if c and c not in lop_list:
            lop_list.append(c)
            list_changed = True

    nguon_list = list(lists.get("nguon") or [])
    for s in sources:
        if s and s not in nguon_list:
            nguon_list.append(s)
            list_changed = True

    if list_changed:
        lists["lop"] = lop_list
        lists["nguon"] = nguon_list
        write_lists(db, lists)

    affected_phones: Set[str] = {phone}

    if payload.id:
        db_row = db.query(SalesDeal).filter(SalesDeal.deal_uid == payload.id).first()
        if not db_row:
            raise HTTPException(status_code=404, detail="Không tìm thấy deal cần sửa")

        if db_row.sdt:
            affected_phones.add(db_row.sdt)

        db_row.ngay_thu = ngay_thu
        db_row.ngay_contact = to_iso_date(payload.ngayContact)
        db_row.sdt = phone
        db_row.ho_ten = ho_ten
        if payload.email is not None:
            db_row.email = payload.email.strip()
        if payload.namSinh is not None:
            db_row.nam_sinh = payload.namSinh.strip()
        if payload.diaChi is not None:
            db_row.dia_chi = payload.diaChi.strip()
        if payload.linhVuc is not None:
            db_row.linh_vuc = payload.linhVuc.strip()
        if payload.kyVong is not None:
            db_row.ky_vong = payload.kyVong.strip()
        db_row.zalo = (payload.zalo or "").strip()
        db_row.nhom_cs = (payload.nhomCS or "").strip()
        db_row.chuong_trinh = (payload.chuongTrinh or "").strip()
        db_row.lop = ", ".join(merged_classes)
        db_row.chuc_vu = (payload.chucVu or "").strip()
        if payload.nvCS is not None and payload.nvCS.strip():
            db_row.nv_cs = payload.nvCS.strip()
        db_row.zalo_cs = (payload.zaloCS or "").strip()
        db_row.nguon = nguon_str
        db_row.da_thu = da_thu
        db_row.phai_thu = phai_thu
        db_row.tong_tien = tong_tien
        db_row.ngay_thu_ar = to_iso_date(payload.ngayThuAR)
        db_row.trang_thai = (payload.trangThai or "").strip()
        db_row.note = (payload.note or "").strip()
        db_row.nguoi_sua = actor
        db_row.sua_luc = now

        # Đồng bộ ngược thông tin học viên sang bảng deal_wins (nếu dòng này nối từ deal_wins)
        if db_row.deal_win_id:
            db.query(DealWin).filter(DealWin.id == db_row.deal_win_id).update(
                {
                    DealWin.full_name: ho_ten,
                    DealWin.phone_number: phone,
                    DealWin.email: db_row.email,
                    DealWin.birth_year: db_row.nam_sinh,
                    DealWin.address: db_row.dia_chi,
                    DealWin.industry: db_row.linh_vuc,
                    DealWin.job_title: db_row.chuc_vu,
                    DealWin.expectation: db_row.ky_vong,
                    DealWin.care_by: db_row.nv_cs,
                },
                synchronize_session=False,
            )

        deal_uid = db_row.deal_uid
        db.commit()
        write_audit_log(
            db,
            actor,
            "Cập nhật deal",
            deal_uid,
            {"sdt": phone, "hoTen": ho_ten, "daThu": da_thu, "phaiThu": phai_thu, "lop": merged_classes},
        )
    else:
        deal_uid = str(uuid.uuid4())
        nv_cs = (payload.nvCS or "").strip() or actor
        db_row = SalesDeal(
            deal_uid=deal_uid,
            ngay_thu=ngay_thu,
            ngay_contact=to_iso_date(payload.ngayContact),
            sdt=phone,
            ho_ten=ho_ten,
            email=(payload.email or "").strip(),
            nam_sinh=(payload.namSinh or "").strip(),
            dia_chi=(payload.diaChi or "").strip(),
            linh_vuc=(payload.linhVuc or "").strip(),
            ky_vong=(payload.kyVong or "").strip(),
            is_student=True,
            zalo=(payload.zalo or "").strip(),
            nhom_cs=(payload.nhomCS or "").strip(),
            chuong_trinh=(payload.chuongTrinh or "").strip(),
            lop=", ".join(merged_classes),
            chuc_vu=(payload.chucVu or "").strip(),
            nv_cs=nv_cs,
            zalo_cs=(payload.zaloCS or "").strip(),
            nguon=nguon_str,
            da_thu=da_thu,
            phai_thu=phai_thu,
            tong_tien=tong_tien,
            ngay_thu_ar=to_iso_date(payload.ngayThuAR),
            trang_thai=(payload.trangThai or "").strip(),
            note=(payload.note or "").strip(),
            nguoi_nhap=actor,
            tao_luc=now,
        )
        db.add(db_row)
        db.commit()
        write_audit_log(
            db,
            actor,
            "Thêm deal",
            deal_uid,
            {"sdt": phone, "hoTen": ho_ten, "daThu": da_thu, "phaiThu": phai_thu, "lop": merged_classes},
        )

    synced = False
    for r in same_phone_rows:
        if r.deal_uid == deal_uid:
            continue
        if not same_classes(parse_classes(r.lop), merged_classes):
            r.lop = ", ".join(merged_classes)
            r.nguoi_sua = actor
            r.sua_luc = now
            synced = True
    if synced:
        db.commit()

    deals = reconcile_phones_and_update_cache(db, affected_phones)
    debts = build_debt_summary(deals)
    return {
        "ok": True,
        "dealId": deal_uid,
        "deals": deals,
        "debts": debts,
        "lists": lists,
    }


@router.put("/deals/{deal_id}/classes")
def update_deal_classes(deal_id: str, payload: SetClassesPayload, db: Session = Depends(get_db)):
    """Cập nhật nhanh Lớp học cho deal và chỉ đồng bộ các dòng của đúng SĐT đó."""
    ensure_schema()
    db_row = db.query(SalesDeal).filter(SalesDeal.deal_uid == deal_id).first()
    if not db_row:
        raise HTTPException(status_code=404, detail="Không tìm thấy deal")

    classes = parse_classes(payload.lop)
    actor = (payload.actor or "admin").strip()
    now = get_vn_now()
    old_classes = parse_classes(db_row.lop)
    phone = db_row.sdt

    same_phone_rows = db.query(SalesDeal).filter(SalesDeal.sdt == phone).all()
    for r in same_phone_rows:
        r.lop = ", ".join(classes)
        r.nguoi_sua = actor
        r.sua_luc = now
    db.commit()

    lists = read_lists(db)
    lop_list = list(lists.get("lop") or [])
    changed = False
    for c in classes:
        if c and c not in lop_list:
            lop_list.append(c)
            changed = True
    if changed:
        lists["lop"] = lop_list
        write_lists(db, lists)

    write_audit_log(db, actor, "Sửa lớp", deal_id, {"sdt": phone, "truoc": old_classes, "sau": classes})

    deals = reconcile_phones_and_update_cache(db, {phone})
    debts = build_debt_summary(deals)
    return {"ok": True, "deals": deals, "debts": debts, "lists": lists}


@router.delete("/deals/{deal_id}")
def delete_deal(deal_id: str, actor: str = Query("admin"), db: Session = Depends(get_db)):
    """Xoá 1 deal và chỉ tính lại công nợ cho SĐT của deal đó."""
    global _DEALS_CACHE
    ensure_schema()
    db_row = db.query(SalesDeal).filter(SalesDeal.deal_uid == deal_id).first()
    if not db_row:
        raise HTTPException(status_code=404, detail="Không tìm thấy deal")

    phone = db_row.sdt
    ho_ten = db_row.ho_ten
    da_thu = int(db_row.da_thu or 0)
    db.delete(db_row)
    db.commit()

    if _DEALS_CACHE is not None:
        with _CACHE_LOCK:
            _DEALS_CACHE = [d for d in _DEALS_CACHE if d.get("id") != deal_id]

    write_audit_log(db, actor, "Xoá deal", deal_id, {"sdt": phone, "hoTen": ho_ten, "daThu": da_thu})

    deals = reconcile_phones_and_update_cache(db, {phone})
    debts = build_debt_summary(deals)
    return {"ok": True, "deals": deals, "debts": debts}


@router.put("/lists")
def save_lists_endpoint(payload: SaveListsPayload, db: Session = Depends(get_db)):
    """Lưu danh mục (Zalo chăm sóc, Nguồn, Chương trình học, Lớp học)."""
    ensure_schema()
    updated = write_lists(db, payload.lists)
    write_audit_log(db, payload.actor or "admin", "Sửa danh mục", "", {"keys": list(updated.keys())})
    return {"ok": True, "lists": updated}


@router.get("/logs")
def get_deal_logs(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    """Lấy lịch sử thao tác (đọc từ RAM cache nếu không có log mới)."""
    global _LOGS_CACHE, _LOGS_CACHE_TS
    ensure_schema()
    now_ts = time.time()
    if _LOGS_CACHE is not None and (now_ts - _LOGS_CACHE_TS) < LOGS_CACHE_TTL:
        return {"ok": True, "logs": _LOGS_CACHE[:limit]}

    rows = db.query(DealAuditLog).order_by(desc(DealAuditLog.id)).limit(100).all()
    logs_list = [
        {
            "id": r.id,
            "createdAt": format_vn_datetime(r.created_at),
            "userEmail": r.user_email,
            "action": r.action,
            "dealId": r.deal_id,
            "detail": r.detail,
        }
        for r in rows
    ]
    with _CACHE_LOCK:
        _LOGS_CACHE = logs_list
        _LOGS_CACHE_TS = now_ts

    return {"ok": True, "logs": logs_list[:limit]}
