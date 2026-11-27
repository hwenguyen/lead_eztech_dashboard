"""Module đồng bộ và map thông tin giữa DealWin (Google Sheet) và DimLead / FactLeadActivity (Pancake)."""
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple, Iterable, Set, List, Dict, Any
from sqlalchemy import or_, func
from sqlalchemy.orm import Session, defer
from database.models import DealWin, DimLead, FactLeadActivity, RawConversation
from etl.utils import (
    VN_TZ,
    COMPANY_PHONE_NUMBERS,
    normalize_phone,
    parse_deal_date,
    resolve_canonical_page_name,
    is_zalo_channel,
)

DEFAULT_SOURCE_PAGE = "Other/ Web"
_IGNORED_MATCH_NAMES = {"", "unknown", "học viên", "hoc vien"}
_MAX_SINGLE_WORD_NAME_FREQ = 4
_MAX_MULTI_WORD_NAME_FREQ = 6
_PRIORITY_DEAL_OWNER = "Anh Trinh"

def normalize_sale_name(raw: Optional[str]) -> Optional[str]:
    """
    Chuẩn hóa tên nhân viên chăm sóc từ Google Sheet / Pancake:
    - Loại bỏ các ghi chú, từ khóa rác không phải tên người ('Bỏ qua', 'Chưa đóng tiền', 'TUẤN ANH DATA'...).
    - Tách các cụm ghép bởi dấu phẩy, cộng, &, gạch chéo...
    - Chuẩn hóa tên viết tắt về tên đầy đủ chuẩn ('Liên' -> 'Liên Vũ', 'Cường' -> 'Khuất Cường', 'Minh' -> 'Hiền Minh Lý'...).
    - Trả về chuỗi tên chuẩn (hoặc nhiều tên ngăn cách bởi dấu phẩy nếu nhiều người cùng phụ trách).
    """
    if not raw or not str(raw).strip():
        return None

    text = str(raw).strip()
    junk_patterns = [
        'bỏ qua', 'chưa đóng tiền', 'không học', 'đăng kí chưa', 
        'chưa phân công', 'đóng trc', 'tuan anh data', 'tuấn anh data', 
        'anh bean', 'chỉ học', 'ở tuấn anh', 'học t7', 'học k2'
    ]
    if any(j in text.lower() for j in junk_patterns) and not any(kw in text.lower() for kw in ('liên', 'linh', 'minh', 'cường', 'ngọc', 'huy', 'trần đạt')):
        return None

    # Loại bỏ ghi chú sau dấu gạch chéo nếu không phải tên sale
    text = re.sub(r'/(?!\s*(?:liên|linh|ngọc|minh|an))\w+.*$', '', text, flags=re.IGNORECASE)

    parts = re.split(r'[,+&;/]', text)
    res = []
    non_sales = ('học', 't7', 'k2', 'tuan anh', 'tuấn anh', 'data', 'pass', 'lead', 'cn', 'công nợ', 'chị bii', 'chj bii')
    for p in parts:
        clean = p.strip()
        clean = re.sub(r'[/\\].*$', '', clean).strip()
        clean = re.sub(r'[-–].*$', '', clean).strip()
        clean = re.sub(r'^zl\s+', '', clean, flags=re.IGNORECASE).strip()
        lower = clean.lower()
        if not lower:
            continue
        if any(j in lower for j in junk_patterns) or any(ns in lower for ns in non_sales):
            continue

        if lower in ('cường', 'cuong', 'khuất cường'):
            norm = 'Khuất Cường'
        elif lower in ('liên', 'lien', 'liên vũ'):
            norm = 'Liên Vũ'
        elif lower in ('hiền minh', 'hien minh', 'hiền minh lý', 'minh', 'minhh'):
            norm = 'Hiền Minh Lý'
        elif lower in ('hồng minh', 'hong minh'):
            norm = 'Hồng Minh'
        elif lower in ('linh', 'linh bùi', 'linh bui'):
            norm = 'Linh Bùi'
        elif lower in ('thùy linh', 'thuỳ linh', 'thuy linh'):
            norm = 'Thùy Linh'
        elif lower in ('ngọc', 'ngoc', 'bảo ngọc', 'bao ngoc'):
            norm = 'Bảo Ngọc'
        elif lower in ('bích ngọc', 'bich ngoc'):
            norm = 'Bích Ngọc'
        elif lower in ('bảo trânn', 'bảo trân', 'bao tran'):
            norm = 'Bảo Trânn'
        elif lower in ('huy', 'nguyen gia huy', 'gia huy'):
            norm = 'Nguyen Gia Huy'
        elif lower in ('huyền', 'huyen', 'pham thu huyen', 'thu huyen'):
            norm = 'Pham Thu Huyen'
        elif lower in ('thu hiền', 'thu hien'):
            norm = 'Thu Hiền'
        elif lower in ('vượng', 'vuong', 'vượng nguyễn', 'vuong nguyen'):
            norm = 'Vượng Nguyễn'
        elif lower in ('minh quân', 'minh quan'):
            norm = 'Minh Quân'
        elif lower in ('quốc anh', 'quoc anh', 'qanh', 'quóc ahn', 'quốc anh', 'nguyễn quoc anh', 'nguyễn quốc anh'):
            norm = 'Nguyễn Quốc Anh'
        elif lower in ('trần đạt', 'tran dat', 'đạt'):
            norm = 'Trần Đạt'
        elif lower in ('anh trinh', 'trinh'):
            norm = 'Anh Trinh'
        elif lower in ('hoài phương', 'hoai phuong', 'hp', 'hphuong'):
            norm = 'Hoài Phương'
        elif lower in ('my trà', 'my tra'):
            norm = 'My Trà'
        elif lower in ('nguyễn thị thanh mai', 'thanh mai'):
            norm = 'Nguyễn Thị Thanh Mai'
        elif lower in ('lam vante', 'vante'):
            norm = 'Lam Vante'
        elif lower in ('chị an', 'chj an', 'c an', 'an'):
            norm = 'Chị An'
        elif len(clean) >= 2:
            norm = clean.title() if len(clean) > 2 else clean
        else:
            norm = None

        if norm and norm not in res:
            res.append(norm)

    return ', '.join(res) if res else None


def _extract_tag_editor_latest_times(tag_timeline: Any) -> Dict[str, Tuple[float, float]]:
    """
    Trả về {emp_name: (latest_closing_tag_ts, latest_any_tag_ts)} từ tag_timeline của 1 hội thoại
    để phân xử khi có nhiều Sale cùng được gán trên hội thoại chính.
    """
    times: Dict[str, Tuple[float, float]] = {}
    if not isinstance(tag_timeline, list):
        return times
    for entry in tag_timeline:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("action") or "add").lower() != "add":
            continue
        editor_norm = normalize_sale_name(entry.get("editor"))
        if not editor_norm:
            continue
        dt = parse_deal_date(entry.get("tagged_at"))
        ts = dt.timestamp() if dt else 1.0
        tag_low = str(entry.get("tag") or "").strip().lower()
        is_closing = any(k in tag_low for k in ("học viên", "đồng ý học", "công nợ", "còn cn"))
        for emp in [x.strip() for x in editor_norm.split(",") if x.strip()]:
            prev_close, prev_any = times.get(emp, (0.0, 0.0))
            times[emp] = (
                max(prev_close, ts) if is_closing else prev_close,
                max(prev_any, ts),
            )
    return times


def _count_admin_messages_by_sale(messages: Any) -> Dict[str, int]:
    """Đếm số tin nhắn Admin theo từng nhân viên (nếu dữ liệu tin nhắn có ghi sender_name là tên nhân viên)."""
    counts: Dict[str, int] = {}
    if not isinstance(messages, list):
        return counts
    for m in messages:
        if not isinstance(m, dict) or m.get("role") != "Admin":
            continue
        emp_norm = normalize_sale_name(m.get("sender_name"))
        if not emp_norm:
            continue
        for emp in [x.strip() for x in emp_norm.split(",") if x.strip()]:
            counts[emp] = counts.get(emp, 0) + 1
    return counts


def _extract_student_tagged_at(tag_timeline: Any) -> Optional[datetime]:
    """Lấy thời điểm gắn tag 'Đã là học viên' sớm nhất từ tag_timeline."""
    if not isinstance(tag_timeline, list):
        return None
    dts: List[datetime] = []
    for entry in tag_timeline:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("action") or "add").lower() != "add":
            continue
        tag_low = str(entry.get("tag") or "").strip().lower()
        if "học viên" in tag_low:
            dt = parse_deal_date(entry.get("tagged_at"))
            if dt:
                dts.append(dt)
    return min(dts) if dts else None


def _extract_source_sale_hints(items: List[Dict[str, Any]]) -> Set[str]:
    """Tập hợp tên nhân viên xuất hiện ở kênh nguồn FB/TikTok (qua assigned_users hoặc tag tên Sale)."""
    hints: Set[str] = set()
    for it in items:
        if is_zalo_channel(it.get("page_id"), it.get("conversation_id")):
            continue
        norm_a = normalize_sale_name(it.get("assigned"))
        if norm_a:
            hints.update(x.strip() for x in norm_a.split(",") if x.strip())
        for raw_t in (it.get("status_tag") or "").split(","):
            t_clean = raw_t.strip()
            if not t_clean:
                continue
            t_low = t_clean.lower()
            if any(k in t_low for k in ("đã add", "da add", "đào tạo", "lead", "mess", "tiktok", "data", "học viên", "web")):
                continue
            norm_t = normalize_sale_name(t_clean)
            if norm_t and "," not in norm_t:
                hints.add(norm_t)
    return hints


def pick_best_assigned_user(items: List[Dict[str, Any]], db: Optional[Session] = None) -> Optional[str]:
    """
    Chọn nhân viên phụ trách (care_by) CHỈ từ đoạn hội thoại chính có số lượng tin nhắn nhiều nhất
    (loại bỏ việc gộp/cộng dồn nhiều page khi 1 SĐT nhắn ở nhiều page):
    1. Chọn duy nhất hội thoại có message_count lớn nhất (trong nhóm có assigned_users; nếu đều trống thì xét toàn bộ).
    2. Nếu trên hội thoại chính có 'Anh Trinh' cùng nhân viên khác -> tính là deal của 'Anh Trinh'.
    3. Nếu có nhiều Sale khác cùng phụ trách trên hội thoại chính -> ưu tiên Sale nhắn nhiều nhất trong đoạn hội thoại đó,
       sau đó xét thời điểm gắn tag mới nhất trong tag_timeline (ưu tiên tag chốt học viên rồi đến tag bất kỳ), cuối cùng theo thứ tự xuất hiện.
    4. Nếu hội thoại chính không có assigned_users -> fallback theo người gắn tag mới nhất trong tag_timeline của hội thoại chính.
    """
    if not items:
        return None

    assigned_pool = [it for it in items if normalize_sale_name(it.get("assigned"))] or items
    main_conv = max(
        assigned_pool,
        key=lambda x: (
            int(x.get("message_count") or 0),
            1 if "học viên" in (x.get("status_tag") or "").lower() else 0,
            int(x.get("lead_id") or 0),
        ),
    )

    norm_assigned = normalize_sale_name(main_conv.get("assigned"))
    if norm_assigned:
        emps = [x.strip() for x in norm_assigned.split(",") if x.strip()]
        if len(emps) == 1:
            return emps[0]
        if _PRIORITY_DEAL_OWNER in emps:
            return _PRIORITY_DEAL_OWNER

        msgs = main_conv.get("messages")
        if msgs is None and db is not None and main_conv.get("conversation_id"):
            raw_row = (
                db.query(RawConversation.payload)
                .filter(RawConversation.pancake_id == main_conv["conversation_id"])
                .first()
            )
            if raw_row and isinstance(raw_row[0], dict):
                msgs = raw_row[0].get("messages")

        msg_counts = _count_admin_messages_by_sale(msgs)
        tag_times = _extract_tag_editor_latest_times(main_conv.get("tag_timeline"))
        return max(
            emps,
            key=lambda emp: (
                msg_counts.get(emp, 0),
                tag_times.get(emp, (0.0, 0.0))[0],
                tag_times.get(emp, (0.0, 0.0))[1],
                -emps.index(emp),
            ),
        )

    # Fallback duy nhất khi hội thoại chính không có assigned_users: lấy người gắn tag mới nhất trên hội thoại chính
    tag_times = _extract_tag_editor_latest_times(main_conv.get("tag_timeline"))
    if tag_times:
        if _PRIORITY_DEAL_OWNER in tag_times:
            return _PRIORITY_DEAL_OWNER
        return max(tag_times.keys(), key=lambda e: tag_times[e])

    return None


def _resolve_lead_items(
    items: List[Dict[str, Any]],
    db: Optional[Session] = None,
) -> Tuple[Optional[int], bool, Optional[str], Optional[str], Optional[str], str]:
    """
    Tổng hợp danh sách hội thoại của 1 SĐT:
    - Trả về: (dim_lead_id, is_student, care_by, lead_tag, page_id, source_page)
    - page_id: chỉ lấy Page Zalo chăm sóc chính (kênh Zalo có số lượng tin nhắn nhiều nhất).
    - source_page: chỉ lấy Page Facebook/TikTok nơi khách gửi SĐT có số lượng tin nhắn nhiều nhất, mặc định "Other/ Web".
    - Nhân viên phụ trách lấy theo assigned_user có số lượng tin nhắn của lead trong hội thoại với nhân viên đó nhiều nhất.
    """
    if not items:
        return None, False, None, None, None, DEFAULT_SOURCE_PAGE

    all_tags = []
    for it in items:
        for t in (it.get('status_tag') or '').split(','):
            t_clean = t.strip()
            if t_clean and t_clean not in all_tags:
                all_tags.append(t_clean)
    combined_tags = ", ".join(all_tags)[:255] if all_tags else None

    is_student = any('học viên' in (it.get('status_tag') or '').lower() for it in items)

    assigned_pool = [it for it in items if normalize_sale_name(it.get('assigned'))] or items
    best_conv = max(
        assigned_pool,
        key=lambda x: (
            int(x.get('message_count') or 0),
            1 if 'học viên' in (x.get('status_tag') or '').lower() else 0,
            int(x.get('lead_id') or 0),
        ),
    )
    best_lead_id = best_conv['lead_id']

    zalo_items = [it for it in items if is_zalo_channel(it.get('page_id'), it.get('conversation_id'))]
    if zalo_items:
        best_zalo = max(
            zalo_items,
            key=lambda x: (
                int(x.get('message_count') or 0),
                1 if normalize_sale_name(x.get('assigned')) else 0,
                1 if 'học viên' in (x.get('status_tag') or '').lower() else 0,
                int(x.get('lead_id') or 0),
            ),
        )
        best_page = best_zalo.get('page_id') or None
    else:
        best_page = None

    source_msgs: Dict[str, int] = {}
    for it in items:
        pg = (it.get('page_id') or '').strip()
        if pg and not is_zalo_channel(pg, it.get('conversation_id')):
            source_msgs[pg] = source_msgs.get(pg, 0) + int(it.get('message_count') or 0)
    source_page = max(source_msgs.items(), key=lambda kv: kv[1])[0] if source_msgs else DEFAULT_SOURCE_PAGE

    assigned_user = pick_best_assigned_user(items, db=db)

    return best_lead_id, is_student, assigned_user, combined_tags, best_page, source_page


def _clean_match_name(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = " ".join(str(raw).strip().lower().split())
    if len(s) < 2 or s in _IGNORED_MATCH_NAMES:
        return None
    return s


def _has_reliable_zalo_student_by_phone(
    base_items: List[Dict[str, Any]],
    deal_ts: Optional[datetime],
) -> bool:
    """
    Kiểm tra SĐT đã có sẵn hội thoại Zalo 'Đã là học viên' đáng tin cậy chưa.
    Nếu ĐÃ CÓ -> tuyệt đối không chạy ghép thêm theo tên Zalo (tránh 100% rủi ro râu ông nọ cắm cằm bà kia).
    Ngoại lệ duy nhất cho phép tìm thêm: hội thoại Zalo khớp SĐT quá ngắn (< 5 tin) VÀ mới tạo muộn > 2 ngày sau khi chốt Deal
    (điển hình ca khách chat 75 tin ở Zalo chính không lưu SĐT, tuần sau mới nhắn 3 tin ở Zalo phụ có SĐT).
    """
    ts = deal_ts.replace(tzinfo=None) if (deal_ts and getattr(deal_ts, "tzinfo", None)) else deal_ts
    for it in base_items:
        if not is_zalo_channel(it.get("page_id"), it.get("conversation_id")):
            continue
        if "học viên" not in (it.get("status_tag") or "").lower():
            continue
        msg_cnt = int(it.get("message_count") or 0)
        if msg_cnt >= 5:
            return True
        first_dt = it.get("first_created_at")
        if first_dt and ts:
            f = first_dt.replace(tzinfo=None) if getattr(first_dt, "tzinfo", None) else first_dt
            if f <= ts + timedelta(days=2):
                return True
        elif not ts:
            return True
    return False


def _match_student_time_distance_sec(
    deal_ts: Optional[datetime],
    hv_tagged_at: Optional[datetime],
    first_created_at: Optional[datetime],
) -> Optional[float]:
    """
    Kiểm tra hội thoại Zalo thiếu SĐT có khớp chặt với thời điểm điền form DealWin hay không.
    Ưu tiên đối chiếu thời điểm gắn tag 'Đã là học viên' trong [-7 ngày, +14 ngày] quanh deal_ts
    (không dùng FactLeadActivity.updated_at vì cột đó bị thay đổi khi chạy backfill lịch sử).
    Trả về khoảng cách giây (càng nhỏ càng sát) hoặc None nếu nằm ngoài cửa sổ an toàn.
    """
    if not deal_ts:
        return 0.0
    ts = deal_ts.replace(tzinfo=None) if getattr(deal_ts, "tzinfo", None) else deal_ts
    if hv_tagged_at:
        h = hv_tagged_at.replace(tzinfo=None) if getattr(hv_tagged_at, "tzinfo", None) else hv_tagged_at
        if (ts - timedelta(days=7)) <= h <= (ts + timedelta(days=14)):
            return abs((h - ts).total_seconds())
        return None
    if first_created_at:
        f = first_created_at.replace(tzinfo=None) if getattr(first_created_at, "tzinfo", None) else first_created_at
        if (ts - timedelta(days=21)) <= f <= (ts + timedelta(days=3)):
            return abs((f - ts).total_seconds()) + 86400.0 * 7
    return None


def _find_missing_phone_zalo_students(
    db: Session,
    deal_specs: List[Dict[str, Any]],
) -> Dict[Any, List[Dict[str, Any]]]:
    """
    Bù liên kết cực kỳ chặt chẽ cho hội thoại Zalo cá nhân ('Đã là học viên') bị thiếu SĐT:
    1. CHỈ chạy khi SĐT của Deal chưa có hội thoại Zalo 'Đã là học viên' đáng tin cậy (_has_reliable_zalo_student_by_phone = False).
    2. Đối chiếu thời điểm gắn tag 'Đã là học viên' (tag_timeline) trong cửa sổ hẹp [-7 ngày, +14 ngày] quanh DealWin.timestamp.
    3. Chống trùng tên Zalo khách hàng:
       - Tên 1 từ: chỉ nhận biệt danh hiếm (tổng dòng dim_leads <= 4 VÀ không thuộc bất kỳ SĐT nào khác).
       - Tên >= 2 từ: nhận nếu tên chưa thuộc về SĐT nào khác (other_phones == 0, tổng dòng <= 6);
         nếu có trùng với 1-2 SĐT khác thì BẮT BUỘC phải có bằng chứng chéo trùng nhân viên Sale với kênh nguồn FB/TikTok của chính SĐT đó.
    4. Khóa độc quyền 1-1: mỗi dim_lead_id thiếu SĐT chỉ được gán cho tối đa 1 SĐT DealWin duy nhất có thời điểm chốt sát nhất.
    """
    if not deal_specs:
        return {}

    all_names: Set[str] = set()
    for spec in deal_specs:
        all_names.update(spec["names"])
    if not all_names:
        return {}

    # Thống kê trên toàn bảng dim_leads: tổng số dòng và tập hợp SĐT đã biết của từng tên
    name_total_cnt: Dict[str, int] = {}
    name_known_phones: Dict[str, Set[str]] = {}
    name_list_all = list(all_names)
    for i in range(0, len(name_list_all), 500):
        chunk = name_list_all[i:i + 500]
        rows_stat = (
            db.query(func.lower(func.trim(DimLead.name)), DimLead.phone_number)
            .filter(func.lower(func.trim(DimLead.name)).in_(chunk))
            .all()
        )
        for raw_lname, raw_p in rows_stat:
            lname = _clean_match_name(raw_lname)
            if not lname:
                continue
            name_total_cnt[lname] = name_total_cnt.get(lname, 0) + 1
            norm_p = normalize_phone(raw_p)
            if norm_p and norm_p not in COMPANY_PHONE_NUMBERS:
                name_known_phones.setdefault(lname, set()).add(norm_p)

    # Lọc sơ bộ các tên có khả năng hợp lệ (tên 1 từ phải <= 4 dòng, tên nhiều từ không quá đại trà nếu không có Sale chứng thực)
    queryable_names = {
        nm for nm in all_names
        if ((" " not in nm and name_total_cnt.get(nm, 0) <= _MAX_SINGLE_WORD_NAME_FREQ)
            or (" " in nm and len(name_known_phones.get(nm, set())) <= 3))
    }
    if not queryable_names:
        return {}

    company_phones = list(COMPANY_PHONE_NUMBERS)
    candidates_by_name: Dict[str, List[Dict[str, Any]]] = {}
    q_list = list(queryable_names)
    for i in range(0, len(q_list), 500):
        chunk = q_list[i:i + 500]
        rows = (
            db.query(
                DimLead.id,
                DimLead.name,
                DimLead.page_id,
                DimLead.first_created_at,
                FactLeadActivity.conversation_id,
                FactLeadActivity.status_tag,
                FactLeadActivity.assigned_users,
                FactLeadActivity.message_count,
                FactLeadActivity.tag_timeline,
            )
            .join(FactLeadActivity, FactLeadActivity.lead_id == DimLead.id)
            .filter(
                func.lower(func.trim(DimLead.name)).in_(chunk),
                FactLeadActivity.conversation_id.like("pzl_u_%"),
                or_(
                    DimLead.phone_number.is_(None),
                    DimLead.phone_number == "",
                    DimLead.phone_number.in_(company_phones),
                ),
                FactLeadActivity.status_tag.isnot(None),
            )
            .all()
        )
        for lid, dname, pg, first_dt, conv_id, status_tag, assigned, msg_cnt, tag_tl in rows:
            if "học viên" not in (status_tag or "").lower():
                continue
            lname = _clean_match_name(dname)
            if not lname:
                continue
            candidates_by_name.setdefault(lname, []).append({
                "lead_id": lid,
                "page_id": resolve_canonical_page_name(pg, fallback=pg) if pg else "",
                "conversation_id": conv_id or "",
                "status_tag": (status_tag or "").strip(),
                "assigned": (assigned or "").strip(),
                "message_count": int(msg_cnt or 0),
                "first_created_at": first_dt,
                "tag_timeline": tag_tl,
                "hv_tagged_at": _extract_student_tagged_at(tag_tl),
            })

    if not candidates_by_name:
        return {}

    # Thu thập các cặp (khoảng_cách_thời_gian, spec_key, phone_key, page_id, cand) để phân bổ độc quyền 1-1
    scored_matches: List[Tuple[float, Any, str, str, Dict[str, Any]]] = []

    for spec in deal_specs:
        key = spec["key"]
        deal_phone: str = spec.get("phone") or f"__no_phone_{key}"
        existing_zalo_pages: Set[str] = spec["existing_zalo_pages"]
        existing_lead_ids: Set[int] = spec["existing_lead_ids"]
        known_sales: Set[str] = spec.get("known_sales") or set()
        deal_ts: Optional[datetime] = spec.get("timestamp")

        by_page: Dict[str, List[Tuple[float, Dict[str, Any]]]] = {}
        seen_lids: Set[int] = set(existing_lead_ids)

        for nm in spec["names"]:
            if nm not in queryable_names:
                continue
            total_cnt = name_total_cnt.get(nm, 0)
            other_phones = name_known_phones.get(nm, set()) - ({deal_phone} if not deal_phone.startswith("__") else set())
            other_cnt = len(other_phones)

            for cand in candidates_by_name.get(nm, []):
                lid = cand["lead_id"]
                pg = cand["page_id"]
                if lid in seen_lids or not pg or pg in existing_zalo_pages:
                    continue

                # Kiểm tra độ sạch chống trùng tên
                cand_norm_sale = normalize_sale_name(cand.get("assigned")) or ""
                cand_sales = {x.strip() for x in cand_norm_sale.split(",") if x.strip()}
                is_sale_corroborated = bool(known_sales and cand_sales and (known_sales & cand_sales))

                if " " not in nm:
                    if total_cnt > _MAX_SINGLE_WORD_NAME_FREQ or other_cnt > 0:
                        continue
                else:
                    if other_cnt == 0:
                        if total_cnt > _MAX_MULTI_WORD_NAME_FREQ and not is_sale_corroborated:
                            continue
                    elif other_cnt <= 2:
                        if not is_sale_corroborated:
                            continue
                    else:
                        continue

                dist = _match_student_time_distance_sec(deal_ts, cand["hv_tagged_at"], cand["first_created_at"])
                if dist is None:
                    continue

                seen_lids.add(lid)
                by_page.setdefault(pg, []).append((dist, cand))

        for pg, pg_cands in by_page.items():
            if len(pg_cands) == 1:
                dist, cand = pg_cands[0]
                scored_matches.append((dist, key, deal_phone, pg, cand))

    if not scored_matches:
        return {}

    # Khóa độc quyền 1-1: 1 lead_id thiếu SĐT chỉ được gán cho đúng 1 SĐT khách hàng có khoảng cách chốt gần nhất
    scored_matches.sort(key=lambda x: x[0])
    claimed_lead_owner: Dict[int, str] = {}
    result: Dict[Any, List[Dict[str, Any]]] = {}
    for _, key, deal_phone, _, cand in scored_matches:
        lid = cand["lead_id"]
        owner = claimed_lead_owner.get(lid)
        if owner is not None and owner != deal_phone:
            continue
        claimed_lead_owner[lid] = deal_phone
        result.setdefault(key, []).append(cand)

    return result


def find_lead_info_by_phone(
    phone: Optional[str],
    db: Session,
    full_name: Optional[str] = None,
    deal_timestamp: Optional[datetime] = None,
) -> Tuple[Optional[int], bool, Optional[str], Optional[str], Optional[str], str]:
    """
    Tìm thông tin DimLead và FactLeadActivity theo SĐT (có chuẩn hoá bù số 0 đầu và bù liên kết an toàn
    với hội thoại Zalo 'Đã là học viên' bị thiếu SĐT khi SĐT chưa có hội thoại Zalo học viên).
    Trả về: (dim_lead_id, is_student, care_by, lead_tag, page_id, source_page)
    """
    raw_phone = str(phone).strip() if phone and str(phone).strip() else ""
    norm_phone = normalize_phone(raw_phone) or raw_phone
    phone_variants = list({p for p in (raw_phone, norm_phone) if p})

    items: List[Dict[str, Any]] = []
    candidate_names: Set[str] = set()
    fn_clean = _clean_match_name(full_name)
    if fn_clean:
        candidate_names.add(fn_clean)

    if phone_variants:
        rows = db.query(
            DimLead.id,
            DimLead.name,
            DimLead.page_id,
            DimLead.first_created_at,
            FactLeadActivity.conversation_id,
            FactLeadActivity.status_tag,
            FactLeadActivity.assigned_users,
            FactLeadActivity.message_count,
            FactLeadActivity.tag_timeline,
        ).join(
            FactLeadActivity, FactLeadActivity.lead_id == DimLead.id
        ).filter(
            DimLead.phone_number.in_(phone_variants),
            ~FactLeadActivity.conversation_id.like("pzl_g_%")
        ).all()

        for lid, dname, pg, first_dt, conv_id, status_tag, assigned_users, msg_cnt, tag_tl in rows:
            canon_pg = resolve_canonical_page_name(pg, fallback=pg) if pg else ''
            items.append({
                'lead_id': lid,
                'page_id': canon_pg,
                'conversation_id': conv_id or '',
                'status_tag': (status_tag or '').strip(),
                'assigned': (assigned_users or '').strip(),
                'message_count': int(msg_cnt or 0),
                'first_created_at': first_dt,
                'tag_timeline': tag_tl,
            })
            dn_clean = _clean_match_name(dname)
            if dn_clean:
                candidate_names.add(dn_clean)

    if candidate_names and not _has_reliable_zalo_student_by_phone(items, deal_timestamp):
        existing_zalo_pages = {
            it['page_id'] for it in items
            if it.get('page_id') and is_zalo_channel(it.get('page_id'), it.get('conversation_id'))
        }
        known_sales = _extract_source_sale_hints(items)
        for it in items:
            na = normalize_sale_name(it.get('assigned'))
            if na:
                known_sales.update(x.strip() for x in na.split(",") if x.strip())

        extra = _find_missing_phone_zalo_students(db, [{
            "key": "single",
            "phone": norm_phone,
            "names": candidate_names,
            "existing_zalo_pages": existing_zalo_pages,
            "existing_lead_ids": {it["lead_id"] for it in items},
            "known_sales": known_sales,
            "timestamp": deal_timestamp,
        }])
        if extra.get("single"):
            items.extend(extra["single"])

    if not items:
        return None, False, None, None, None, DEFAULT_SOURCE_PAGE

    return _resolve_lead_items(items, db=db)


def sync_all_deals_with_dim_leads(
    db: Session,
    full_scan: bool = False,
    target_phones: Optional[Iterable[str]] = None
) -> Tuple[int, int, int]:
    """
    Quét và đồng bộ bảng deal_wins với dim_leads:
    - Nếu target_phones được cung cấp (từ các lead có tương tác trong lượt chạy ETL hiện tại):
      chỉ truy vấn các deal khớp với những SĐT này -> tiết kiệm >99% băng thông Neon.
    - Nếu full_scan=False (mặc định cho các lượt chạy tự động):
      chỉ quét các deal chưa được map (dim_lead_id IS NULL hoặc page_id IS NULL) hoặc mới cập nhật trong 48h gần nhất.
    - Nếu full_scan=True: quét toàn bộ 1.500+ deal (dùng khi bấm nút thủ công trên Dashboard).
    - Dùng defer(DealWin.raw_data) để không tải JSON raw_data qua mạng.
    Trả về: (total_processed, student_count, care_by_updated)
    """
    # Bỏ qua toàn bộ các dòng đã được nhân viên chỉnh sửa thủ công (ETL không cào đè lại nữa)
    query = db.query(DealWin).options(defer(DealWin.raw_data)).filter(
        or_(DealWin.is_manually_edited == False, DealWin.is_manually_edited.is_(None))
    )

    if target_phones is not None:
        clean_targets = list({str(p).strip() for p in target_phones if p and str(p).strip()})
        if not clean_targets:
            # Không có SĐT nào phát sinh trong đợt chạy -> không cần query DB
            return 0, 0, 0
        query = query.filter(DealWin.phone_number.in_(clean_targets))
    elif not full_scan:
        cutoff = datetime.now(VN_TZ).replace(tzinfo=None) - timedelta(days=2)
        query = query.filter(
            or_(
                DealWin.dim_lead_id.is_(None),
                DealWin.page_id.is_(None),
                DealWin.source_page.is_(None),
                DealWin.updated_at >= cutoff
            )
        )

    deals = query.all()
    if not deals:
        return 0, 0, 0

    query_phones_set: Set[str] = set()
    for d in deals:
        raw_p = str(d.phone_number).strip() if d.phone_number and str(d.phone_number).strip() else ""
        if raw_p:
            query_phones_set.add(raw_p)
            norm_p = normalize_phone(raw_p)
            if norm_p:
                query_phones_set.add(norm_p)
    deal_phones = list(query_phones_set)
    lead_map: Dict[str, List[Dict[str, Any]]] = {}
    lead_names_by_phone: Dict[str, Set[str]] = {}

    if deal_phones:
        # Chia chunk 500 SĐT để dùng index ix_dim_leads_phone_number cực nhanh
        for i in range(0, len(deal_phones), 500):
            chunk = deal_phones[i:i + 500]
            leads = db.query(
                DimLead.id,
                DimLead.phone_number,
                DimLead.name,
                DimLead.page_id,
                DimLead.first_created_at,
                FactLeadActivity.conversation_id,
                FactLeadActivity.status_tag,
                FactLeadActivity.assigned_users,
                FactLeadActivity.message_count,
                FactLeadActivity.tag_timeline,
            ).join(
                FactLeadActivity, FactLeadActivity.lead_id == DimLead.id
            ).filter(
                DimLead.phone_number.in_(chunk),
                ~FactLeadActivity.conversation_id.like("pzl_g_%")
            ).all()

            for lid, phone, dname, pg, first_dt, conv_id, status_tag, assigned, msg_cnt, tag_tl in leads:
                p_key = normalize_phone(phone) or phone
                lead_map.setdefault(p_key, []).append({
                    'lead_id': lid,
                    'page_id': resolve_canonical_page_name(pg, fallback=pg) if pg else '',
                    'conversation_id': conv_id or '',
                    'status_tag': status_tag or '',
                    'assigned': (assigned or '').strip(),
                    'message_count': int(msg_cnt or 0),
                    'first_created_at': first_dt,
                    'tag_timeline': tag_tl,
                })
                dn_clean = _clean_match_name(dname)
                if dn_clean:
                    lead_names_by_phone.setdefault(p_key, set()).add(dn_clean)

    # Bù liên kết an toàn với các hội thoại Zalo 'Đã là học viên' bị thiếu SĐT (CHỈ khi SĐT chưa có Zalo học viên hợp lệ)
    deal_specs: List[Dict[str, Any]] = []
    for d in deals:
        raw_p = str(d.phone_number).strip() if d.phone_number and str(d.phone_number).strip() else ""
        p_key = normalize_phone(raw_p) or raw_p
        base_items = lead_map.get(p_key) or []
        if _has_reliable_zalo_student_by_phone(base_items, d.timestamp):
            continue
        names: Set[str] = set(lead_names_by_phone.get(p_key, set()))
        fn_clean = _clean_match_name(d.full_name)
        if fn_clean:
            names.add(fn_clean)
        if not names:
            continue
        existing_zalo_pages = {
            it['page_id'] for it in base_items
            if it.get('page_id') and is_zalo_channel(it.get('page_id'), it.get('conversation_id'))
        }
        known_sales = _extract_source_sale_hints(base_items)
        for it in base_items:
            na = normalize_sale_name(it.get('assigned'))
            if na:
                known_sales.update(x.strip() for x in na.split(",") if x.strip())

        deal_specs.append({
            "key": d.id,
            "phone": p_key,
            "names": names,
            "existing_zalo_pages": existing_zalo_pages,
            "existing_lead_ids": {it['lead_id'] for it in base_items},
            "known_sales": known_sales,
            "timestamp": d.timestamp,
        })
    extra_zalo_by_deal = _find_missing_phone_zalo_students(db, deal_specs)

    student_count = 0
    care_by_updated = 0
    has_changes = False

    for d in deals:
        raw_p = str(d.phone_number).strip() if d.phone_number and str(d.phone_number).strip() else ""
        p_key = normalize_phone(raw_p) or raw_p
        if p_key and d.phone_number != p_key:
            d.phone_number = p_key
            has_changes = True
        base_items = lead_map.get(p_key) or []
        extra_items = extra_zalo_by_deal.get(d.id) or []
        items = base_items + extra_items if extra_items else base_items
        if items:
            new_lead_id, new_is_student, new_care, new_tag, new_page_id, new_source_page = _resolve_lead_items(items, db=db)
            if d.dim_lead_id != new_lead_id:
                d.dim_lead_id = new_lead_id
                has_changes = True

            if d.page_id != new_page_id:
                d.page_id = new_page_id
                has_changes = True

            if d.source_page != new_source_page:
                d.source_page = new_source_page
                has_changes = True

            if d.lead_tag != new_tag:
                d.lead_tag = new_tag
                has_changes = True

            if new_is_student:
                student_count += 1
            if d.is_student != new_is_student:
                d.is_student = new_is_student
                has_changes = True

            if new_care:
                norm_care = normalize_sale_name(new_care)
                if norm_care and d.care_by != norm_care:
                    d.care_by = norm_care
                    care_by_updated += 1
                    has_changes = True
            else:
                norm_care = normalize_sale_name(d.care_by) or "Chưa phân công"
                if norm_care != d.care_by:
                    d.care_by = norm_care
                    care_by_updated += 1
                    has_changes = True
        else:
            if d.dim_lead_id is not None:
                d.dim_lead_id = None
                has_changes = True
            if d.is_student:
                d.is_student = False
                has_changes = True
            if d.page_id is not None:
                d.page_id = None
                has_changes = True
            if d.source_page != DEFAULT_SOURCE_PAGE:
                d.source_page = DEFAULT_SOURCE_PAGE
                has_changes = True

            norm_care = normalize_sale_name(d.care_by) or "Chưa phân công"
            if norm_care != d.care_by:
                d.care_by = norm_care
                care_by_updated += 1
                has_changes = True

    if has_changes:
        db.commit()
    return len(deals), student_count, care_by_updated
