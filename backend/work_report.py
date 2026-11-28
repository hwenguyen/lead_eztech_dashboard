"""
Module Backend Báo cáo Công việc Tuần (Work Report).
Tổng hợp tự động toàn bộ số liệu Lead (TikTok, Facebook, Zalo), Học viên chốt (Deal Win / SalesDeal),
và Insight khách hàng thu được trong tuần của từng nhân viên để tự động điền vào form báo cáo.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
import time
import threading
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, defer, joinedload
from sqlalchemy import or_, desc

from database.db import get_db
from database.models import DealWin, SalesDeal, FactLeadActivity, AppUser, DailyChecklist
from backend.auth import require_tab_access
from backend.rbac_config import get_module_scope, resolve_scoped_employee
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
    "Học Kế toán cùng EzTech",
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
    current_user: AppUser = Depends(require_tab_access("work_report")),
    db: Session = Depends(get_db),
):
    is_personal = get_module_scope(current_user, "work_report") == "personal"
    employee = resolve_scoped_employee(current_user, "work_report", employee)

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
    cache_key = f"{start_ymd}_{end_ymd}_{emp_clean}_{'p' if is_personal else 'a'}"
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
    if is_personal:
        employees_list = [emp_clean] if emp_clean else []
    else:
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
        has_ph = bool(l.has_phone)

        if is_tt:
            tt_contact += 1
            if l.is_new:
                tt_new += 1
            else:
                tt_recontact += 1
            if has_ph:
                tt_phones += 1
        else:
            fb_contact += 1
            if l.is_new:
                fb_new += 1
            else:
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
        else:
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
            else:
                zalo_recontact += 1
            if zl.has_phone:
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
        or_(SalesDeal.is_deleted == False, SalesDeal.is_deleted.is_(None)),
        SalesDeal.ngay_thu.between(start_ymd, end_ymd),
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

        if key in students_map:
            students_map[key]["revenue"] += int(sd.da_thu or 0)
            students_map[key]["total_amount"] += int(sd.tong_tien or 0)
            if sd.lop and sd.lop.strip():
                existing_cls = split_csv(students_map[key]["class_code"])
                for c_code in split_csv(sd.lop):
                    if c_code not in existing_cls:
                        existing_cls.append(c_code)
                students_map[key]["class_code"] = ", ".join(existing_cls)
        else:
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
        if key not in students_map:
            if dw.industry and dw.industry.strip():
                industries_counter[dw.industry.strip()] += 1
            if dw.job_title and dw.job_title.strip():
                jobs_counter[dw.job_title.strip()] += 1
            if dw.expectation and dw.expectation.strip():
                exp_str = dw.expectation.strip()
                if exp_str not in expectations_list and len(expectations_list) < 8:
                    expectations_list.append(exp_str)
            src_raw = dw.source_page or dw.page_id or ""
            students_map[key] = {
                "full_name": dw.full_name or "Học viên",
                "phone_number": dw.phone_number or "",
                "page_id": resolve_canonical_page_name(src_raw, fallback=src_raw),
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
            if not students_map[key]["industry"] and dw.industry and dw.industry.strip():
                students_map[key]["industry"] = dw.industry.strip()
                industries_counter[dw.industry.strip()] += 1
            if not students_map[key]["job_title"] and dw.job_title and dw.job_title.strip():
                students_map[key]["job_title"] = dw.job_title.strip()
                jobs_counter[dw.job_title.strip()] += 1
            if not students_map[key]["expectation"] and dw.expectation and dw.expectation.strip():
                exp_str = dw.expectation.strip()
                students_map[key]["expectation"] = exp_str
                if exp_str not in expectations_list and len(expectations_list) < 8:
                    expectations_list.append(exp_str)

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


class WorkReportAiAutofillRequest(BaseModel):
    start_date: str
    end_date: str
    employee_name: Optional[str] = None
    sections: List[Dict[str, Any]] = []


def _parse_ai_autofill_json(raw_text: str) -> List[Dict[str, Any]]:
    cleaned = (raw_text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", cleaned, flags=re.DOTALL)
    candidate = fence.group(1) if fence else cleaned
    if not fence:
        s_idx = candidate.find("{")
        e_idx = candidate.rfind("}")
        if s_idx != -1 and e_idx > s_idx:
            candidate = candidate[s_idx : e_idx + 1]
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict) and isinstance(parsed.get("updates"), list):
            return [u for u in parsed["updates"] if isinstance(u, dict)]
        if isinstance(parsed, list):
            return [u for u in parsed if isinstance(u, dict)]
    except Exception:
        pass
    return []


@router.post("/ai-autofill")
def ai_autofill_work_report(
    payload: WorkReportAiAutofillRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(require_tab_access("work_report")),
):
    """Đọc toàn bộ Checklist trong tuần của nhân sự và dùng Gemini AI điền vào các mục tương ứng của Báo cáo công việc."""
    from backend.ai_rag import get_gemini_api_key, call_gemini_generate

    api_key = get_gemini_api_key(db)
    if not api_key:
        raise HTTPException(status_code=400, detail="Chưa cấu hình GEMINI_API_KEY để chạy AI tự điền.")

    scoped_emp = resolve_scoped_employee(db, current_user, "work_report", payload.employee_name)
    start_str = (payload.start_date or "")[:10]
    end_str = (payload.end_date or "")[:10]
    if not start_str or not end_str:
        raise HTTPException(status_code=400, detail="Thiếu khoảng ngày start_date / end_date.")

    q = (
        db.query(DailyChecklist)
        .options(joinedload(DailyChecklist.items))
        .filter(
            DailyChecklist.is_deleted == False,
            DailyChecklist.checklist_date >= start_str,
            DailyChecklist.checklist_date <= end_str,
        )
    )

    users_map: Dict[int, str] = {}
    for u in db.query(AppUser.id, AppUser.full_name, AppUser.username).all():
        users_map[u.id] = (u.full_name or u.username or "").strip()

    if scoped_emp:
        target_norm = scoped_emp.strip().lower()
        matched_ids = [
            uid for uid, uname in users_map.items()
            if uname.lower() == target_norm or target_norm in uname.lower()
        ]
        if matched_ids:
            q = q.filter(DailyChecklist.owner_user_id.in_(matched_ids))
        else:
            return {
                "checklist_count": 0,
                "done_count": 0,
                "pending_count": 0,
                "updates": [],
                "message": f"Không tìm thấy tài khoản Checklist khớp với '{scoped_emp}'.",
            }

    checklists = q.order_by(DailyChecklist.checklist_date.asc(), DailyChecklist.id.asc()).all()
    if not checklists:
        return {
            "checklist_count": 0,
            "done_count": 0,
            "pending_count": 0,
            "updates": [],
            "message": f"Không có dữ liệu Checklist nào từ {start_str} đến {end_str}.",
        }

    done_count = 0
    pending_count = 0
    checklist_lines: List[str] = []
    for cl in checklists:
        owner_name = users_map.get(cl.owner_user_id, "")
        header = f"[{cl.checklist_date}] {cl.title}" + (f" ({owner_name})" if not scoped_emp and owner_name else "")
        if cl.admin_note:
            header += f" | Admin Note: {cl.admin_note}"
        checklist_lines.append(header)
        for it in cl.items:
            if it.is_done:
                done_count += 1
                status_tag = "[ĐÃ XONG]"
            else:
                pending_count += 1
                status_tag = "[CHƯA XONG]"
            assigned_tag = " [Task được giao]" if it.is_assigned else ""
            note_part = f" (Ghi chú: {it.note})" if it.note else ""
            checklist_lines.append(f"  - {status_tag}{assigned_tag} {it.content}{note_part}")

    # Mô tả khung các mục hiện tại (trừ các dòng số liệu tự động s1_r1, s1_r2, s1_r_zalo)
    protected_row_ids = {"s1_r1", "s1_r2", "s1_r_zalo"}
    section_outline: List[str] = []
    for sec in payload.sections:
        sec_num = sec.get("sectionNumber")
        sec_title = sec.get("title") or ""
        section_outline.append(f"Mục {sec_num}: {sec_title}")
        for r in sec.get("rows") or []:
            rid = r.get("id")
            if rid in protected_row_ids:
                continue
            section_outline.append(f"  - rowId=\"{rid}\" | Công việc=\"{r.get('task') or ''}\"")

    system_prompt = (
        "Bạn là Trợ lý tổng hợp Báo cáo Công việc Tuần của EzTech Việt Nam.\n"
        "Nhiệm vụ: Đọc toàn bộ Checklist công việc trong tuần của nhân sự và phân loại, tổng hợp ngắn gọn, súc tích "
        "vào đúng các mục tương ứng trong bảng Báo cáo công việc.\n\n"
        "QUY TẮC BẮT BUỘC:\n"
        "- Chỉ dùng thông tin có thật trong Checklist đầu vào, KHÔNG tự bịa việc.\n"
        "- Việc `[ĐÃ XONG]` → tổng hợp gọn theo nhóm việc vào cột `completed` (Đã hoàn thành trong tuần).\n"
        "- Việc `[CHƯA XONG]` hoặc `[Task được giao]` cần làm tiếp → tổng hợp thành đầu việc ngắn gọn vào cột `nextPlan` (Kế hoạch cho tuần tiếp theo).\n"
        "- Ưu tiên điền vào các `rowId` có sẵn trong khung bảng; nếu có nhóm việc mới chưa có dòng phù hợp thì đặt `rowId: null` và ghi rõ `task` (tên đầu việc) kèm `sectionNumber` (1..6).\n"
        "- TUYỆT ĐỐI KHÔNG đụng vào các dòng số liệu tự động (Chăm sóc Lead TikTok/FB/Zalo).\n"
        "- Viết ngắn gọn, rõ ràng dạng gạch đầu dòng `- ...`, không rào đón.\n"
        "- BẮT BUỘC trả về DUY NHẤT 1 JSON hợp lệ theo mẫu:\n"
        '{\n  "updates": [\n    {\n      "sectionNumber": 2,\n      "rowId": "s2_r1",\n      "task": "Tên công việc (nếu rowId là null)",\n      "completed": "- ... (để chuỗi rỗng nếu không có)",\n      "nextPlan": "- ... (để chuỗi rỗng nếu không có)"\n    }\n  ]\n}'
    )

    user_prompt = (
        f"=== KHUNG BẢNG BÁO CÁO CÔNG VIỆC ({start_str} đến {end_str}) ===\n"
        + "\n".join(section_outline)
        + "\n\n=== DỮ LIỆU CHECKLIST TRONG TUẦN ===\n"
        + "\n".join(checklist_lines)
        + "\n\nHãy xuất JSON phân loại và điền vào các mục tương ứng."
    )

    raw_answer, _, _ = call_gemini_generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        history=[],
        api_key=api_key,
        temperature=0.2,
        enable_search=False,
    )
    updates = _parse_ai_autofill_json(raw_answer)

    return {
        "checklist_count": len(checklists),
        "done_count": done_count,
        "pending_count": pending_count,
        "updates": updates,
        "message": f"Đã tổng hợp {done_count} việc hoàn thành và {pending_count} việc tiếp theo từ {len(checklists)} checklist.",
    }
