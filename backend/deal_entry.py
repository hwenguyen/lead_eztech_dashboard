"""
Module Backend Quản lý Nhập Deal & Công nợ học viên (Deal Entry & Debt Management).
Được chuyển đổi và nâng cấp trực tiếp từ Google Apps Script (Deal Win Backend) lên FastAPI + Neon Postgres.
Tích hợp tự động tra cứu thông tin khách hàng từ Pancake (dim_leads / fact_lead_activities).
"""

import json
import re
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, or_

from database.db import get_db
from database.models import SalesDeal, DealAuditLog, AppConfig, AppUser, DimLead, FactLeadActivity
from database.schema import ensure_schema
from etl.utils import normalize_phone, resolve_canonical_page_name, build_pancake_url

logger = logging.getLogger("DealEntryService")

router = APIRouter(prefix="/api/deal-entry", tags=["Deal Entry"])

VN_TZ = timezone(timedelta(hours=7))


def get_vn_now() -> datetime:
    return datetime.now(VN_TZ).replace(tzinfo=None)


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
    Tính toán công nợ tự động theo nguyên tắc FIFO cho từng SĐT:
    - Mỗi deal có `daThu` (số tiền thu lần này) và `phaiThu` (số tiền khách còn nợ ở deal này).
    - Khi có một dòng `trangThai == 'Thu nợ'` (hoặc `daThu > 0` và `phaiThu == 0` với ghi chú/trạng thái thu nợ,
      hoặc `daThu > tongTien` khi đóng dư sang nợ cũ), số tiền thu nợ sẽ được cấn trừ lần lượt vào các khoản
      nợ cũ (`phaiThu > 0`) của cùng SĐT theo thứ tự ngày thu tăng dần.
    """
    res: Dict[str, Dict[str, Any]] = {}
    by_phone: Dict[str, List[Dict[str, Any]]] = {}

    for d in deals:
        did = d["id"]
        da_thu = int(d.get("daThu") or 0)
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
        # Sắp xếp theo ngayThu tăng dần, sau đó theo thứ tự tạo
        sorted_group = sorted(
            group,
            key=lambda x: (x.get("ngayThu") or "9999-99-99", x.get("_sort_id") or 0)
        )

        # Danh sách các khoản nợ đang mở của SĐT này
        open_debts: List[Dict[str, Any]] = []

        for d in sorted_group:
            did = d["id"]
            r = res[did]
            da_thu = int(d.get("daThu") or 0)
            phai_thu = int(d.get("phaiThu") or 0)
            tong_tien = int(d.get("tongTien") or 0)
            trang_thai_lower = str(d.get("trangThai") or "").strip().lower()

            # Xác định số tiền trong giao dịch này dùng để trả nợ cũ:
            # 1. Nếu trạng thái là "Thu nợ" -> toàn bộ daThu dùng để trả nợ cũ
            # 2. Nếu có nợ cũ đang mở và dòng này có phaiThu == 0 và chuongTrinh trống hoặc ghi "Thu nợ"
            # 3. Nếu daThu > tongTien (khi tongTien > 0 và phaiThu == 0) -> phần dư trả nợ cũ
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

            # Nếu bản thân deal này có phát sinh phải thu khách hàng (phaiThu > 0)
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


# ───────────────────────── Đọc / Ghi Danh mục & Deal ─────────────────────────

def read_lists(db: Session) -> Dict[str, List[str]]:
    cfg = db.query(AppConfig).filter(AppConfig.config_key == CONFIG_KEY_LISTS).first()
    if not cfg or not cfg.config_value:
        # Khởi tạo từ LIST_SEED
        lists_data = dict(LIST_SEED)
        cfg = AppConfig(
            config_key=CONFIG_KEY_LISTS,
            config_value=json.dumps(lists_data, ensure_ascii=False),
        )
        db.add(cfg)
        db.commit()
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
        return out
    except Exception:
        return dict(LIST_SEED)


def write_lists(db: Session, lists_data: Dict[str, List[str]]) -> Dict[str, List[str]]:
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


def reconcile_all_deals(db: Session, actor_email: str = "system") -> List[Dict[str, Any]]:
    """
    Đọc tất cả deal, tính lại công nợ FIFO, cập nhật những bản ghi có thay đổi xuống DB
    và trả về danh sách deal đầy đủ kèm thông tin công nợ.
    """
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

    # Trả về danh sách mới nhất lên đầu
    deals.sort(key=lambda x: (x.get("ngayThu") or "", x.get("_sort_id") or 0), reverse=True)
    return deals


def build_debt_summary(deals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Tạo bảng Công nợ (tương đương sheet CongNo trong Apps Script)."""
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
    try:
        text = json.dumps(detail or {}, ensure_ascii=False)
        if len(text) > 5000:
            text = text[:5000] + "…"
        log_row = DealAuditLog(
            created_at=get_vn_now(),
            user_email=user_email or "admin",
            action=action,
            deal_id=deal_id or "",
            detail=text,
        )
        db.add(log_row)
        db.commit()
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
def init_deal_entry(db: Session = Depends(get_db)):
    """Khởi tạo toàn bộ dữ liệu cho trang Quản lý Nhập Deal & Công nợ."""
    ensure_schema()
    lists = read_lists(db)
    deals = reconcile_all_deals(db)
    debts = build_debt_summary(deals)

    # Tự động gộp các lớp đang có trong deal vào danh mục lop nếu chưa có
    existing_classes: List[str] = list(lists.get("lop") or [])
    changed_list = False
    for d in deals:
        for cl in d.get("lop") or []:
            if cl and cl not in existing_classes:
                existing_classes.append(cl)
                changed_list = True
    if changed_list:
        lists["lop"] = existing_classes
        write_lists(db, lists)

    return {
        "ok": True,
        "statuses": BASE_STATUSES,
        "lists": lists,
        "deals": deals,
        "debts": debts,
    }


@router.get("/lookup-phone")
def lookup_phone(sdt: str = Query(..., description="Số điện thoại cần tra cứu"), exclude_id: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Tra cứu SĐT khi người dùng nhập vào form Deal:
    1. Tìm trong bảng SalesDeal xem khách đã có deal cũ hay đang còn nợ không.
    2. Tìm trong bảng DimLead / FactLeadActivity (Pancake) để tự động gợi ý Họ tên, Ngày contact đầu tiên,
       Link Zalo Pancake, Nguồn page và Nhân viên chăm sóc!
    """
    ensure_schema()
    phone = clean_phone(sdt)
    if not phone or len(phone) < 9:
        return {"ok": True, "found": False}

    # 1. Tìm trong SalesDeal (công nợ & lớp học cũ)
    deals = reconcile_all_deals(db)
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

    # 2. Tìm trong DimLead & FactLeadActivity (dữ liệu Pancake)
    pancake_info: Dict[str, Any] = {}
    lead_rows = (
        db.query(DimLead, FactLeadActivity)
        .outerjoin(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)
        .filter(DimLead.phone_number.like(f"%{phone[-9:]}%"))
        .order_by(asc(DimLead.first_created_at))
        .all()
    )

    if lead_rows:
        first_lead = lead_rows[0][0]
        lead_name = first_lead.name or ""
        first_contact = first_lead.first_created_at.strftime("%Y-%m-%d") if first_lead.first_created_at else ""
        zalo_url = ""
        source_page = ""
        assigned_sale = ""

        for ld, act in lead_rows:
            if ld.name and not lead_name:
                lead_name = ld.name
            pg_name = resolve_canonical_page_name(ld.page_id) if ld.page_id else ""
            conv_id = act.conversation_id if act else ""
            if conv_id and str(conv_id).startswith("pzl_") and not str(conv_id).startswith("pzl_g_"):
                zalo_url = build_pancake_url(ld.page_id, conv_id) or zalo_url
            elif pg_name and not source_page:
                source_page = pg_name
            if act and act.assigned_users and not assigned_sale:
                assigned_sale = act.assigned_users.split(",")[0].strip()

        # Nếu chưa có link Zalo riêng thì lấy link hội thoại Pancake bất kỳ
        if not zalo_url:
            for ld, act in lead_rows:
                if act and act.conversation_id:
                    zalo_url = build_pancake_url(ld.page_id, act.conversation_id) or ""
                    if zalo_url:
                        break

        pancake_info = {
            "foundInPancake": True,
            "hoTen": lead_name,
            "ngayContact": first_contact,
            "zalo": zalo_url,
            "nguon": source_page,
            "nvCS": assigned_sale,
        }

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
    """Thêm mới hoặc Cập nhật Deal, đồng bộ lớp học theo SĐT và tự động đối trừ công nợ FIFO."""
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

    # Lấy các lớp hiện có của cùng SĐT để gộp đồng bộ
    same_phone_rows = db.query(SalesDeal).filter(SalesDeal.sdt == phone).all()
    existing_phone_classes: List[str] = []
    for r in same_phone_rows:
        if payload.id and r.deal_uid == payload.id:
            continue
        existing_phone_classes = merge_classes(existing_phone_classes, parse_classes(r.lop))

    merged_classes = merge_classes(existing_phone_classes, classes) if classes else existing_phone_classes
    if classes:
        merged_classes = classes  # Nếu người dùng chủ động chỉnh danh sách lớp thì ưu tiên theo lựa chọn mới

    # Tự động thêm lớp mới vào Danh mục nếu chưa có
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

    if payload.id:
        db_row = db.query(SalesDeal).filter(SalesDeal.deal_uid == payload.id).first()
        if not db_row:
            raise HTTPException(status_code=404, detail="Không tìm thấy deal cần sửa")

        before_snapshot = model_to_dict(db_row)
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
        write_audit_log(db, actor, "Sửa deal", deal_uid, {"truoc": before_snapshot, "sau": payload.dict()})
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
        write_audit_log(db, actor, "Thêm deal", deal_uid, payload.dict())

    # Đồng bộ lớp học cho tất cả các dòng khác cùng SĐT (syncClasses_)
    other_rows = db.query(SalesDeal).filter(SalesDeal.sdt == phone, SalesDeal.deal_uid != deal_uid).all()
    synced = False
    for r in other_rows:
        if not same_classes(parse_classes(r.lop), merged_classes):
            r.lop = ", ".join(merged_classes)
            r.nguoi_sua = actor
            r.sua_luc = now
            synced = True
    if synced:
        db.commit()

    deals = reconcile_all_deals(db, actor)
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
    """Cập nhật nhanh Lớp học cho deal và tự động đồng bộ mọi deal cùng SĐT."""
    ensure_schema()
    db_row = db.query(SalesDeal).filter(SalesDeal.deal_uid == deal_id).first()
    if not db_row:
        raise HTTPException(status_code=404, detail="Không tìm thấy deal")

    classes = parse_classes(payload.lop)
    actor = (payload.actor or "admin").strip()
    now = get_vn_now()
    old_classes = parse_classes(db_row.lop)

    # Cập nhật tất cả deal cùng SĐT
    same_phone_rows = db.query(SalesDeal).filter(SalesDeal.sdt == db_row.sdt).all()
    for r in same_phone_rows:
        r.lop = ", ".join(classes)
        r.nguoi_sua = actor
        r.sua_luc = now
    db.commit()

    # Bổ sung lớp mới vào Danh mục nếu chưa có
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

    write_audit_log(db, actor, "Sửa lớp", deal_id, {"sdt": db_row.sdt, "truoc": old_classes, "sau": classes})

    deals = reconcile_all_deals(db, actor)
    debts = build_debt_summary(deals)
    return {"ok": True, "deals": deals, "debts": debts, "lists": lists}


@router.delete("/deals/{deal_id}")
def delete_deal(deal_id: str, actor: str = Query("admin"), db: Session = Depends(get_db)):
    """Xoá 1 deal và tính lại công nợ."""
    ensure_schema()
    db_row = db.query(SalesDeal).filter(SalesDeal.deal_uid == deal_id).first()
    if not db_row:
        raise HTTPException(status_code=404, detail="Không tìm thấy deal")

    snapshot = model_to_dict(db_row)
    db.delete(db_row)
    db.commit()

    write_audit_log(db, actor, "Xoá deal", deal_id, snapshot)

    deals = reconcile_all_deals(db, actor)
    debts = build_debt_summary(deals)
    return {"ok": True, "deals": deals, "debts": debts}


@router.put("/lists")
def save_lists_endpoint(payload: SaveListsPayload, db: Session = Depends(get_db)):
    """Lưu danh mục (Zalo chăm sóc, Nguồn, Chương trình học, Lớp học)."""
    ensure_schema()
    updated = write_lists(db, payload.lists)
    write_audit_log(db, payload.actor or "admin", "Sửa danh mục", "", updated)
    return {"ok": True, "lists": updated}


@router.get("/logs")
def get_deal_logs(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    """Lấy lịch sử thao tác (sheet Log)."""
    ensure_schema()
    rows = db.query(DealAuditLog).order_by(desc(DealAuditLog.id)).limit(limit).all()
    return {
        "ok": True,
        "logs": [
            {
                "id": r.id,
                "createdAt": format_vn_datetime(r.created_at),
                "userEmail": r.user_email,
                "action": r.action,
                "dealId": r.deal_id,
                "detail": r.detail,
            }
            for r in rows
        ],
    }
