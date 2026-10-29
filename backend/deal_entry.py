"""
Module Backend Quản lý Nhập Deal & Công nợ học viên (Deal Entry & Debt Management).
Được chuyển đổi và nâng cấp trực tiếp từ Google Apps Script (Deal Win Backend) lên FastAPI + Neon Postgres.
Tối ưu đặc biệt chống tốn băng thông Neon Egress:
- In-Memory Cache cho danh sách Deals, Công nợ, Danh mục và Nhật ký (0 query lặp lại).
- Reconcile công nợ cô lập theo đúng SĐT vừa thay đổi (chỉ đọc/ghi 1-3 dòng thay vì quét cả bảng).
- Tra cứu Pancake chỉ SELECT đúng 5 cột text nhẹ bằng with_entities + Index Scan (tuyệt đối không kéo JSONB tag_timeline hay payload).
"""

import json
import re
import time
import uuid
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc

from database.db import get_db
from database.models import SalesDeal, DealAuditLog, AppConfig, DimLead, FactLeadActivity
from database.schema import ensure_schema
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
DEALS_CACHE_TTL = 300  # 5 phút (tự động cập nhật tức thì khi có thao tác thêm/sửa/xoá)

_LISTS_CACHE: Optional[Dict[str, List[str]]] = None
_LISTS_CACHE_TS: float = 0.0
LISTS_CACHE_TTL = 600  # 10 phút

_LOGS_CACHE: Optional[List[Dict[str, Any]]] = None
_LOGS_CACHE_TS: float = 0.0
LOGS_CACHE_TTL = 300  # 5 phút

_PANCAKE_PHONE_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
PANCAKE_PHONE_TTL = 600  # 10 phút


# ───────────────────────── Hằng số & Danh mục mặc định ─────────────────────────

CONFIG_KEY_LISTS = "sales_deal_lists_v1"

BASE_STATUSES = [
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


def merge_classes(a: List[str], b: List[str]) -> List[str]:
    out = list(a or [])
    for item in (b or []):
        clean = str(item).strip()
        if clean and clean not in out:
            out.append(clean)
    return out


def same_classes(a: List[str], b: List[str]) -> bool:
    return sorted(parse_classes(a)) == sorted(parse_classes(b))


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


# ───────────────────────── Thuật toán Đối trừ Công nợ FIFO (settleDebts) ─────────────────────────

def settle_debts(deals: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Tính toán công nợ tự động theo nguyên tắc FIFO cho từng SĐT.
    """
    res: Dict[str, Dict[str, Any]] = {}
    by_phone: Dict[str, List[Dict[str, Any]]] = {}

    for d in deals:
        did = d["id"]
        phai_thu = int(d.get("phaiThu") or 0)
        trang_thai = str(d.get("trangThai") or "").strip()
        ngay_thu_ar = str(d.get("ngayThuAR") or "").strip()

        res[did] = {
            "thuNo": 0,
            "daThuNo": 0,
            "conNo": max(0, phai_thu),
            "apps": [],
            "trangThai": trang_thai or ("Còn nợ" if phai_thu > 0 else "Hoàn thành"),
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

            is_debt_payment_row = (
                trang_thai_lower in ("thu nợ", "thu no", "trả nợ", "thanh toán công nợ")
                or (
                    len(open_debts) > 0
                    and phai_thu == 0
                    and da_thu > 0
                    and not str(d.get("chuongTrinh") or "").strip()
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
                if not is_debt_payment_row and not r["trangThai"]:
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
    return {
        "_sort_id": row.id,
        "id": row.deal_uid,
        "ngayThu": row.ngay_thu or "",
        "ngayContact": row.ngay_contact or "",
        "sdt": row.sdt or "",
        "hoTen": row.ho_ten or "",
        "zalo": row.zalo or "",
        "nhomCS": row.nhom_cs or "",
        "chuongTrinh": row.chuong_trinh or "",
        "lop": parse_classes(row.lop),
        "chucVu": row.chuc_vu or "",
        "nvCS": row.nv_cs or "",
        "zaloCS": row.zalo_cs or "",
        "nguon": row.nguon or "",
        "daThu": int(row.da_thu or 0),
        "phaiThu": int(row.phai_thu or 0),
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
        "apps": [],
    }


def get_cached_deals(db: Session, force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    Trả về danh sách deals từ RAM nếu còn hạn TTL (tốn 0 bytes Neon Egress).
    Chỉ truy vấn DB khi khởi động lần đầu hoặc hết TTL.
    """
    global _DEALS_CACHE, _DEALS_CACHE_TS
    now_ts = time.time()
    if not force_refresh and _DEALS_CACHE is not None and (now_ts - _DEALS_CACHE_TS) < DEALS_CACHE_TTL:
        return _DEALS_CACHE

    rows = db.query(SalesDeal).order_by(asc(SalesDeal.ngay_thu), asc(SalesDeal.id)).all()
    deals = [model_to_dict(r) for r in rows]
    res = settle_debts(deals)

    row_map = {r.deal_uid: r for r in rows}
    dirty = False

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

    # Nếu đã có cache trong RAM, chỉ thay thế đúng các dòng thuộc SĐT vừa cập nhật (0 query toàn bảng)
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
    zalo: Optional[str] = ""
    nhomCS: Optional[str] = ""
    chuongTrinh: Optional[str] = ""
    lop: List[str] = Field(default_factory=list)
    chucVu: Optional[str] = ""
    nvCS: Optional[str] = ""
    zaloCS: Optional[str] = ""
    nguon: Optional[str] = ""
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
    """Khởi tạo dữ liệu cho trang Quản lý Nhập Deal & Công nợ (Đọc từ RAM Cache)."""
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
            FactLeadActivity.conversation_id,
            FactLeadActivity.assigned_users,
        )
        .filter(DimLead.phone_number == phone)
        .order_by(asc(DimLead.first_created_at))
        .limit(10)
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
    source_page = ""
    assigned_sale = ""

    for name, _, page_id, conv_id, assigned_users in rows:
        if name and not lead_name:
            lead_name = name
        pg_name = resolve_canonical_page_name(page_id) if page_id else ""
        if conv_id and str(conv_id).startswith("pzl_") and not str(conv_id).startswith("pzl_g_"):
            zalo_url = build_pancake_url(page_id, conv_id) or zalo_url
        elif pg_name and not source_page:
            source_page = pg_name
        if assigned_users and not assigned_sale:
            assigned_sale = assigned_users.split(",")[0].strip()

    if not zalo_url:
        for _, _, page_id, conv_id, _ in rows:
            if conv_id:
                zalo_url = build_pancake_url(page_id, conv_id) or ""
                if zalo_url:
                    break

    info = {
        "foundInPancake": True,
        "hoTen": lead_name,
        "ngayContact": first_contact,
        "zalo": zalo_url,
        "nguon": source_page,
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

    # 1. Đọc từ _DEALS_CACHE trong RAM (0 Egress)
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

    # 2. Tìm trên Pancake với truy vấn tối giản (chỉ 5 cột scalar)
    pancake_info = _lookup_pancake_lightweight(db, phone)

    if not hit and not pancake_info:
        return {"ok": True, "found": False}

    return {
        "ok": True,
        "found": True,
        "foundInDeals": hit is not None,
        "hoTen": (hit["hoTen"] if hit else pancake_info.get("hoTen")) or "",
        "chucVu": (hit.get("chucVu") if hit else "") or "",
        "zalo": (hit.get("zalo") if hit else pancake_info.get("zalo")) or "",
        "nhomCS": (hit.get("nhomCS") if hit else "") or "",
        "nvCS": (hit.get("nvCS") if hit else pancake_info.get("nvCS")) or "",
        "zaloCS": (hit.get("zaloCS") if hit else "") or "",
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
    """Thêm mới hoặc Cập nhật Deal, chỉ reconcile đúng SĐT bị ảnh hưởng để tiết kiệm tối đa Egress."""
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

    lists = read_lists(db)
    lop_list = list(lists.get("lop") or [])
    list_changed = False
    for c in merged_classes:
        if c and c not in lop_list:
            lop_list.append(c)
            list_changed = True
    if list_changed:
        lists["lop"] = lop_list
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
        db_row.zalo = (payload.zalo or "").strip()
        db_row.nhom_cs = (payload.nhomCS or "").strip()
        db_row.chuong_trinh = (payload.chuongTrinh or "").strip()
        db_row.lop = ", ".join(merged_classes)
        db_row.chuc_vu = (payload.chucVu or "").strip()
        if payload.nvCS is not None and payload.nvCS.strip():
            db_row.nv_cs = payload.nvCS.strip()
        db_row.zalo_cs = (payload.zaloCS or "").strip()
        db_row.nguon = (payload.nguon or "").strip()
        db_row.da_thu = da_thu
        db_row.phai_thu = phai_thu
        db_row.tong_tien = tong_tien
        db_row.ngay_thu_ar = to_iso_date(payload.ngayThuAR)
        db_row.trang_thai = (payload.trangThai or "").strip()
        db_row.note = (payload.note or "").strip()
        db_row.nguoi_sua = actor
        db_row.sua_luc = now

        deal_uid = db_row.deal_uid
        db.commit()
        write_audit_log(
            db,
            actor,
            "Sửa deal",
            deal_uid,
            {"sdt": phone, "hoTen": ho_ten, "daThu": da_thu, "phaiThu": phai_thu, "trangThai": db_row.trang_thai},
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
            zalo=(payload.zalo or "").strip(),
            nhom_cs=(payload.nhomCS or "").strip(),
            chuong_trinh=(payload.chuongTrinh or "").strip(),
            lop=", ".join(merged_classes),
            chuc_vu=(payload.chucVu or "").strip(),
            nv_cs=nv_cs,
            zalo_cs=(payload.zaloCS or "").strip(),
            nguon=(payload.nguon or "").strip(),
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
            {"sdt": phone, "hoTen": ho_ten, "daThu": da_thu, "phaiThu": phai_thu, "trangThai": db_row.trang_thai},
        )

    # Đồng bộ lớp học cho các dòng cùng SĐT đã nạp sẵn trong same_phone_rows (không cần SELECT lại)
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
