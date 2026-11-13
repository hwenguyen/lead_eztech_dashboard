"""
Module Backend Báo cáo Công việc Tuần (Work Report).
Tổng hợp tự động toàn bộ số liệu Lead (TikTok, Facebook, Zalo), Học viên chốt (Deal Win / SalesDeal),
và Insight khách hàng thu được trong tuần của từng nhân viên để tự động điền vào form báo cáo.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
import time
import threading
from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, defer
from sqlalchemy import or_, desc

from database.db import get_db
from database.models import DealWin, SalesDeal, FactLeadActivity
from backend.lead_metrics import classify_leads, resolve_period, normalize_text, split_csv
from etl.utils import VN_TZ, ZALO_PAGE_NAMES, resolve_canonical_page_name, normalize_phone

logger = logging.getLogger("WorkReportService")

_WORK_REPORT_CACHE: Dict[str, Tuple[float, Any]] = {}
_WORK_REPORT_LOCK = threading.Lock()
_WORK_REPORT_TTL = 1800.0  # Cache in-memory 30 phút (xóa sau mỗi lần ETL) giúp giảm tối đa Neon Egress

def clear_work_report_cache():
    """Xóa bộ đệm báo cáo công việc."""
    with _WORK_REPORT_LOCK:
        _WORK_REPORT_CACHE.clear()


router = APIRouter(prefix="/api/work-report", tags=["Work Report"])

TIKTOK_PAGE_NAMES = {
    "Anh Kế toán làm Data (TikTok)",
    "Hành trang cho kế toán",
    "Chị Kế Toán GenZ",
    "Anh kế toán Daily",
}


def _is_tiktok_page(page_name: str) -> bool:
    if not page_name:
        return False
    if page_name in TIKTOK_PAGE_NAMES:
        return True
    low = page_name.lower()
    return "tiktok" in low or low.startswith("tt_")


def _is_zalo_page(page_name: str) -> bool:
    if not page_name:
        return False
    if page_name in ZALO_PAGE_NAMES:
        return True
    low = page_name.lower()
    return "zalo" in low or low.startswith("pzl_")


def _match_employee(field_val: Optional[str], target_emp: Optional[str]) -> bool:
    """Kiểm tra nhân viên có khớp với trường care_by / nv_cs (hỗ trợ cả chuỗi nhiều NV ngăn cách bởi dấu phẩy)."""
    if not target_emp:
        return True
    if not field_val:
        return False
    target_norm = normalize_text(target_emp)
    parts = [normalize_text(x) for x in field_val.split(",") if x.strip()]
    if target_norm in parts:
        return True
    return target_norm in normalize_text(field_val)


@router.get("")
def get_work_report(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    employee: Optional[str] = None,
    db: Session = Depends(get_db),
):
    # Mặc định kỳ báo cáo là 7 ngày gần nhất (1 tuần làm việc)
    if not end_date:
        end_date = datetime.now(VN_TZ).replace(tzinfo=None)
    if not start_date:
        start_date = end_date.replace(tzinfo=None) - timedelta(days=6)
    start, end = resolve_period(start_date, end_date)
    start_ymd = start.strftime("%Y-%m-%d")
    end_ymd = end.strftime("%Y-%m-%d")

    emp_clean = employee.strip() if employee and employee.strip() else None

    # 0. Kiểm tra in-memory cache
    cache_key = f"{start_ymd}_{end_ymd}_{emp_clean}"
    now_ts = time.time()
    with _WORK_REPORT_LOCK:
        if cache_key in _WORK_REPORT_CACHE:
            ts, cached_res = _WORK_REPORT_CACHE[cache_key]
            today_start = datetime.now(VN_TZ).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
            effective_ttl = 86400.0 if end < today_start else _WORK_REPORT_TTL
            if now_ts - ts < effective_ttl:
                return cached_res

    # 1. Lấy danh sách toàn bộ nhân viên từ Leads trong kỳ + DealWin + SalesDeal
    all_period_leads = classify_leads(db, start, end)
    emp_set = set()
    for l in all_period_leads.values():
        for e in l.employees:
            if e and e != "Chưa phân công":
                emp_set.add(e)

    # Bổ sung nhân viên từ bảng SalesDeal & DealWin để không sót nhân sự
    deal_emps = db.query(SalesDeal.nv_cs).filter(SalesDeal.nv_cs.isnot(None), SalesDeal.nv_cs != "").distinct().all()
    for (de,) in deal_emps:
        for e in split_csv(de):
            if e and e != "Chưa phân công":
                emp_set.add(e)

    employees_list = sorted(emp_set, key=lambda x: normalize_text(x))

    # 2. Phân loại Lead của nhân viên được chọn (Nguồn TikTok + Facebook)
    leads = classify_leads(db, start, end, employee=emp_clean) if emp_clean else all_period_leads

    tt_new = 0
    tt_recontact = 0
    tt_contact = 0
    tt_phones = 0

    fb_new = 0
    fb_recontact = 0
    fb_contact = 0
    fb_phones = 0

    page_stats_map: Dict[str, Dict[str, Any]] = {}
    tag_counter: Counter = Counter()
    daily_contact_counter: Counter = Counter()

    for l in leads.values():
        pg = l.page_id or "Khác"
        is_tt = _is_tiktok_page(pg)
        has_ph = bool(l.has_phone and l.phone_event_at)

        if is_tt:
            tt_contact += 1
            if l.is_new:
                tt_new += 1
            if l.is_recontact:
                tt_recontact += 1
            if has_ph:
                tt_phones += 1
        else:
            fb_contact += 1
            if l.is_new:
                fb_new += 1
            if l.is_recontact:
                fb_recontact += 1
            if has_ph:
                fb_phones += 1

        if pg not in page_stats_map:
            page_stats_map[pg] = {
                "page_name": pg,
                "platform": "tiktok" if is_tt else "facebook",
                "new_leads": 0,
                "recontact_leads": 0,
                "total_contacted": 0,
                "phone_leads": 0,
            }
        page_stats_map[pg]["total_contacted"] += 1
        if l.is_new:
            page_stats_map[pg]["new_leads"] += 1
        if l.is_recontact:
            page_stats_map[pg]["recontact_leads"] += 1
        if has_ph:
            page_stats_map[pg]["phone_leads"] += 1

        for t in l.tags:
            if not t:
                continue
            t_norm = normalize_text(t)
            if emp_clean and (t_norm == normalize_text(emp_clean) or (len(t_norm) >= 2 and t_norm in normalize_text(emp_clean).split())):
                continue
            # Chuẩn hoá chữ hoa chữ cái đầu để gộp "Đã add" và "đã add"
            t_display = t.strip()
            if t_norm == "đã add" or t_norm == "da add":
                t_display = "Đã add"
            tag_counter[t_display] += 1

        for cday in l.contact_days:
            daily_contact_counter[cday] += 1

    # Kiểm tra thêm kênh Zalo chăm sóc (nếu nhân viên có tương tác trên Zalo)
    zalo_new = 0
    zalo_recontact = 0
    zalo_contact = 0
    zalo_phones = 0
    for z_page in ZALO_PAGE_NAMES:
        z_leads = classify_leads(db, start, end, page_id=z_page, employee=emp_clean)
        for zl in z_leads.values():
            zalo_contact += 1
            if zl.is_new:
                zalo_new += 1
            if zl.is_recontact:
                zalo_recontact += 1
            if zl.has_phone and zl.phone_event_at:
                zalo_phones += 1

    total_new = tt_new + fb_new
    total_recontact = tt_recontact + fb_recontact
    total_contact = tt_contact + fb_contact
    total_phones = tt_phones + fb_phones

    tt_phone_rate = round((tt_phones / tt_contact * 100), 1) if tt_contact > 0 else 0.0
    fb_phone_rate = round((fb_phones / fb_contact * 100), 1) if fb_contact > 0 else 0.0
    total_phone_rate = round((total_phones / total_contact * 100), 1) if total_contact > 0 else 0.0

    # Chuỗi định dạng chuẩn theo đúng mẫu Google Sheet của EzTech
    tt_line = f"Tiktok: Tạo mới: {tt_new}, Contact trong tuần: {tt_contact}, SĐT {tt_phones}."
    fb_line = f"FB: Tạo mới: {fb_new}, Contact: {fb_contact}, SĐT: {fb_phones}"

    # 3. Truy vấn Học viên chốt (DealWin & SalesDeal) trong kỳ - Bỏ qua raw_data JSON để tiết kiệm Egress
    deal_wins_raw = db.query(DealWin).options(defer(DealWin.raw_data)).filter(
        DealWin.timestamp.between(start, end)
    ).order_by(desc(DealWin.timestamp)).all()

    matched_deal_wins = [
        d for d in deal_wins_raw
        if _match_employee(d.care_by, emp_clean)
    ]

    sales_deals_raw = db.query(SalesDeal).filter(
        SalesDeal.ngay_thu.between(start_ymd, end_ymd)
    ).order_by(desc(SalesDeal.ngay_thu)).all()

    matched_sales_deals = [
        sd for sd in sales_deals_raw
        if _match_employee(sd.nv_cs, emp_clean)
    ]

    # Gộp danh sách học viên chốt (ưu tiên thông tin lớp & học phí từ SalesDeal + kỳ vọng/ngành nghề từ DealWin)
    students_map: Dict[str, Dict[str, Any]] = {}
    classes_set = set()
    courses_set = set()
    industries_counter: Counter = Counter()
    jobs_counter: Counter = Counter()
    expectations_list: List[str] = []

    total_revenue = 0
    total_contract = 0

    for sd in matched_sales_deals:
        key = normalize_phone(sd.sdt) or sd.sdt or f"sd_{sd.id}"
        if sd.lop and sd.lop.strip():
            for c_code in split_csv(sd.lop):
                classes_set.add(c_code)
        if sd.chuong_trinh and sd.chuong_trinh.strip():
            courses_set.add(sd.chuong_trinh.strip())
        if sd.linh_vuc and sd.linh_vuc.strip():
            industries_counter[sd.linh_vuc.strip()] += 1
        if sd.chuc_vu and sd.chuc_vu.strip():
            jobs_counter[sd.chuc_vu.strip()] += 1
        if sd.ky_vong and sd.ky_vong.strip() and len(expectations_list) < 8:
            expectations_list.append(sd.ky_vong.strip())

        total_revenue += int(sd.da_thu or 0)
        total_contract += int(sd.tong_tien or 0)

        students_map[key] = {
            "full_name": sd.ho_ten or "Học viên",
            "phone_number": sd.sdt or "",
            "page_id": resolve_canonical_page_name(sd.nguon, fallback=sd.nguon or ""),
            "industry": sd.linh_vuc or "",
            "job_title": sd.chuc_vu or "",
            "expectation": sd.ky_vong or "",
            "course": sd.chuong_trinh or "",
            "class_code": sd.lop or "",
            "revenue": int(sd.da_thu or 0),
            "total_amount": int(sd.tong_tien or 0),
            "date": sd.ngay_thu or "",
            "care_by": sd.nv_cs or "",
            "note": sd.note or "",
        }

    for dw in matched_deal_wins:
        key = normalize_phone(dw.phone_number) if dw.phone_number else f"dw_{dw.id}"
        if dw.industry and dw.industry.strip():
            industries_counter[dw.industry.strip()] += 1
        if dw.job_title and dw.job_title.strip():
            jobs_counter[dw.job_title.strip()] += 1
        if dw.expectation and dw.expectation.strip():
            exp_str = dw.expectation.strip()
            if exp_str not in expectations_list and len(expectations_list) < 8:
                expectations_list.append(exp_str)

        if key not in students_map:
            students_map[key] = {
                "full_name": dw.full_name or "Học viên",
                "phone_number": dw.phone_number or "",
                "page_id": resolve_canonical_page_name(dw.page_id, fallback=dw.page_id or ""),
                "industry": dw.industry or "",
                "job_title": dw.job_title or "",
                "expectation": dw.expectation or "",
                "course": "",
                "class_code": "",
                "revenue": 0,
                "total_amount": 0,
                "date": dw.timestamp.strftime("%Y-%m-%d") if dw.timestamp else "",
                "care_by": dw.care_by or "",
                "note": "",
            }
        else:
            # Bổ sung thông tin nếu SalesDeal còn thiếu
            if not students_map[key]["industry"] and dw.industry:
                students_map[key]["industry"] = dw.industry
            if not students_map[key]["job_title"] and dw.job_title:
                students_map[key]["job_title"] = dw.job_title
            if not students_map[key]["expectation"] and dw.expectation:
                students_map[key]["expectation"] = dw.expectation

    students_list = list(students_map.values())
    total_students = len(students_list)

    # Nếu trong tuần không có mã lớp mới trong SalesDeal, lấy thêm các lớp gần nhất mà nhân viên này từng phụ trách để gợi ý
    if not classes_set and emp_clean:
        recent_classes = db.query(SalesDeal.lop).filter(
            SalesDeal.lop.isnot(None),
            SalesDeal.lop != "",
        ).order_by(desc(SalesDeal.id)).limit(30).all()
        for (rc,) in recent_classes:
            for c_code in split_csv(rc):
                if c_code:
                    classes_set.add(c_code)

    classes_list = sorted(classes_set)

    # Tạo dòng tóm tắt Học viên chốt
    if total_students > 0:
        names_preview = ", ".join(s["full_name"] for s in students_list[:5])
        if total_students > 5:
            names_preview += f" (+{total_students - 5} HV)"
        rev_str = f" | Thực thu: {total_revenue:,}đ" if total_revenue > 0 else ""
        student_summary_line = f"Chốt {total_students} học viên ({names_preview}){rev_str}."
    else:
        student_summary_line = "Chưa phát sinh học viên chốt mới trong tuần."

    # 4. Tổng hợp Insight tự động từ dữ liệu thật
    insight_lines: List[str] = []

    # Insight 1: Hiệu quả chuyển đổi SĐT giữa các kênh
    if total_contact > 0:
        best_channel = "TikTok" if tt_phone_rate >= fb_phone_rate and tt_phones > 0 else ("Facebook" if fb_phones > 0 else "Chưa có SĐT")
        insight_lines.append(
            f"Tỷ lệ thu SĐT đạt {total_phone_rate}% ({total_phones}/{total_contact} lead). "
            f"TikTok đạt {tt_phone_rate}% ({tt_phones}/{tt_contact}), FB đạt {fb_phone_rate}% ({fb_phones}/{fb_contact})."
        )

    # Insight 2: Trạng thái chăm sóc & Tag phổ biến
    top_tags_list = [{"tag": k, "count": v} for k, v in tag_counter.most_common(6)]
    if top_tags_list:
        tags_str = ", ".join(f"{item['tag']} ({item['count']})" for item in top_tags_list[:4])
        insight_lines.append(f"Trạng thái Lead chăm sóc: {tags_str}.")

    # Insight 3: Chân dung & Kỳ vọng Học viên (nếu có Deal Win trong kỳ hoặc lấy mẫu gần nhất của NV)
    if not industries_counter and not expectations_list and emp_clean:
        # Lấy 5 học viên gần nhất của nhân viên này để có insight mẫu nếu tuần hiện tại chưa có form học viên mới
        recent_dws = db.query(DealWin).options(defer(DealWin.raw_data)).filter(
            DealWin.care_by.ilike(f"%{emp_clean}%")
        ).order_by(desc(DealWin.timestamp)).limit(5).all()
        for rdw in recent_dws:
            if rdw.industry and rdw.industry.strip():
                industries_counter[rdw.industry.strip()] += 1
            if rdw.job_title and rdw.job_title.strip():
                jobs_counter[rdw.job_title.strip()] += 1
            if rdw.expectation and rdw.expectation.strip() and len(expectations_list) < 4:
                expectations_list.append(rdw.expectation.strip())

    persona_parts = []
    if industries_counter:
        top_inds = ", ".join(k for k, _ in industries_counter.most_common(2))
        persona_parts.append(f"Ngành nghề chính: {top_inds}")
    if jobs_counter:
        top_jobs = ", ".join(k for k, _ in jobs_counter.most_common(2))
        persona_parts.append(f"Vị trí: {top_jobs}")
    if expectations_list:
        sample_exp = "; ".join(expectations_list[:2])
        persona_parts.append(f"Nhu cầu/Kỳ vọng: {sample_exp}")

    if persona_parts:
        insight_lines.append("Insight học viên: " + " | ".join(persona_parts) + ".")

    result = {
        "period": {
            "start_date": start_ymd,
            "end_date": end_ymd,
        },
        "employee": emp_clean or "Tất cả nhân viên",
        "employees_list": employees_list,
        "lead_stats": {
            "total": {
                "new_leads": total_new,
                "recontact_leads": total_recontact,
                "total_contacted": total_contact,
                "phone_leads": total_phones,
                "phone_rate": total_phone_rate,
            },
            "tiktok": {
                "new_leads": tt_new,
                "recontact_leads": tt_recontact,
                "total_contacted": tt_contact,
                "phone_leads": tt_phones,
                "phone_rate": tt_phone_rate,
                "formatted_line": tt_line,
            },
            "facebook": {
                "new_leads": fb_new,
                "recontact_leads": fb_recontact,
                "total_contacted": fb_contact,
                "phone_leads": fb_phones,
                "phone_rate": fb_phone_rate,
                "formatted_line": fb_line,
            },
            "zalo": {
                "new_leads": zalo_new,
                "recontact_leads": zalo_recontact,
                "total_contacted": zalo_contact,
                "phone_leads": zalo_phones,
            },
            "by_page": sorted(page_stats_map.values(), key=lambda x: x["total_contacted"], reverse=True),
            "top_tags": top_tags_list,
        },
        "student_stats": {
            "total_deals": total_students,
            "total_revenue": total_revenue,
            "total_contract_value": total_contract,
            "classes": classes_list,
            "courses": sorted(courses_set),
            "students": students_list,
            "formatted_line": student_summary_line,
        },
        "insights": {
            "industries": [{"name": k, "count": v} for k, v in industries_counter.most_common(5)],
            "job_titles": [{"name": k, "count": v} for k, v in jobs_counter.most_common(5)],
            "expectations": expectations_list,
            "formatted_lines": insight_lines,
        },
    }

    # Lưu cache và dọn dẹp khóa hết hạn
    with _WORK_REPORT_LOCK:
        if len(_WORK_REPORT_CACHE) > 50:
            exp = [k for k, (t, _) in _WORK_REPORT_CACHE.items() if now_ts - t > _WORK_REPORT_TTL]
            for k in exp:
                _WORK_REPORT_CACHE.pop(k, None)
        _WORK_REPORT_CACHE[cache_key] = (now_ts, result)

    return result
