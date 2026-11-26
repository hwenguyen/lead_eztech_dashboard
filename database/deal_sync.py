"""Module đồng bộ và map thông tin giữa DealWin (Google Sheet) và DimLead / FactLeadActivity (Pancake)."""
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple, Iterable, Set, List, Dict, Any
from sqlalchemy import or_, func
from sqlalchemy.orm import Session, defer
from database.models import DealWin, DimLead, FactLeadActivity
from etl.utils import VN_TZ, COMPANY_PHONE_NUMBERS, resolve_canonical_page_name, is_zalo_channel

DEFAULT_SOURCE_PAGE = "Other/ Web"
_IGNORED_MATCH_NAMES = {"", "unknown", "học viên", "hoc vien"}
_MAX_SINGLE_WORD_NAME_FREQ = 5

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
        elif lower in ('ngọc', 'ngoc', 'bảo ngọc', 'bao ngoc'):
            norm = 'Bảo Ngọc'
        elif lower in ('bảo trânn', 'bảo trân', 'bao tran'):
            norm = 'Bảo Trânn'
        elif lower in ('huy', 'nguyen gia huy', 'gia huy'):
            norm = 'Nguyen Gia Huy'
        elif lower in ('huyền', 'huyen', 'pham thu huyen', 'thu huyen'):
            norm = 'Pham Thu Huyen'
        elif lower in ('quốc anh', 'quoc anh', 'qanh', 'quóc ahn', 'quốc anh', 'nguyễn quoc anh', 'nguyễn quốc anh'):
            norm = 'Nguyễn Quốc Anh'
        elif lower in ('trần đạt', 'tran dat', 'đạt'):
            norm = 'Trần Đạt'
        elif lower in ('anh trinh', 'trinh'):
            norm = 'Anh Trinh'
        elif lower in ('hoài phương', 'hoai phuong'):
            norm = 'Hoài Phương'
        elif lower in ('my trà', 'my tra'):
            norm = 'My Trà'
        elif lower in ('nguyễn thị thanh mai', 'thanh mai'):
            norm = 'Nguyễn Thị Thanh Mai'
        elif lower in ('lam vante', 'vante'):
            norm = 'Lam Vante'
        elif lower in ('chị an', 'chj an', 'c an', 'an'):
            norm = 'Chị An'
        elif len(clean) >= 2 and lower not in ('hp',):
            norm = clean.title() if len(clean) > 2 else clean
        else:
            norm = None

        if norm and norm not in res:
            res.append(norm)

    return ', '.join(res) if res else None


def pick_best_assigned_user(items: List[Dict[str, Any]]) -> Optional[str]:
    """
    Chọn nhân viên phụ trách (assigned_user) từ các hội thoại của lead:
    - Điều kiện: tin nhắn của lead trong hội thoại với nhân viên đó nhiều nhất so với nhân viên khác (nếu có).
    - Nếu 1 nhân viên xuất hiện ở nhiều hội thoại của cùng lead, xét hội thoại có số tin nhắn lớn nhất trước,
      sau đó xét tổng số tin nhắn của lead trong các hội thoại có nhân viên đó.
    """
    emp_scores: Dict[str, Tuple[int, int, int]] = {}
    for it in items:
        raw_assigned = it.get('assigned') or ''
        norm_assigned = normalize_sale_name(raw_assigned)
        if not norm_assigned:
            continue
        msg_cnt = int(it.get('message_count') or 0)
        emps = [x.strip() for x in norm_assigned.split(',') if x.strip()]
        for idx, emp in enumerate(emps):
            prev_max, prev_sum, prev_idx = emp_scores.get(emp, (-1, 0, idx))
            emp_scores[emp] = (
                max(prev_max, msg_cnt),
                prev_sum + msg_cnt,
                min(prev_idx, idx),
            )

    if not emp_scores:
        return None

    best_emp = max(
        emp_scores.keys(),
        key=lambda e: (emp_scores[e][0], emp_scores[e][1], -emp_scores[e][2]),
    )
    return best_emp


def _resolve_lead_items(items: List[Dict[str, Any]]) -> Tuple[Optional[int], bool, Optional[str], Optional[str], Optional[str], str]:
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

    assigned_user = pick_best_assigned_user(items)

    return best_lead_id, is_student, assigned_user, combined_tags, best_page, source_page


def _clean_match_name(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = " ".join(str(raw).strip().lower().split())
    if len(s) < 2 or s in _IGNORED_MATCH_NAMES:
        return None
    return s


def _is_within_deal_window(
    deal_ts: Optional[datetime],
    first_created_at: Optional[datetime],
    updated_at: Optional[datetime],
) -> bool:
    if not deal_ts:
        return True
    ts = deal_ts.replace(tzinfo=None) if getattr(deal_ts, "tzinfo", None) else deal_ts
    if updated_at:
        u = updated_at.replace(tzinfo=None) if getattr(updated_at, "tzinfo", None) else updated_at
        if (ts - timedelta(days=60)) <= u <= (ts + timedelta(days=45)):
            return True
    if first_created_at:
        f = first_created_at.replace(tzinfo=None) if getattr(first_created_at, "tzinfo", None) else first_created_at
        if (ts - timedelta(days=180)) <= f <= (ts + timedelta(days=14)):
            return True
    return False


def _find_missing_phone_zalo_students(
    db: Session,
    deal_specs: List[Dict[str, Any]],
) -> Dict[Any, List[Dict[str, Any]]]:
    """
    Bù liên kết cho các hội thoại Zalo cá nhân ('Đã là học viên') bị thiếu SĐT hoặc dính SĐT hotline nội bộ:
    - Khớp theo tên chính xác (từ DealWin.full_name hoặc DimLead.name đã khớp SĐT ở kênh khác).
    - Chỉ chấp nhận tên 1 từ nếu là biệt danh hiếm (tổng số dòng trong dim_leads <= 5) để tránh trùng tên phổ biến (Dung, Trang, Hương...).
    - Không bao giờ ghép thêm trên cùng 1 Page Zalo mà SĐT đó đã có hội thoại.
    - Nếu cùng 1 Page Zalo có > 1 học viên trùng tên khớp vào cùng 1 deal, bỏ qua trang đó để tránh đoán nhầm.
    """
    if not deal_specs:
        return {}

    all_names: Set[str] = set()
    single_word_names: Set[str] = set()
    for spec in deal_specs:
        for nm in spec["names"]:
            all_names.add(nm)
            if " " not in nm:
                single_word_names.add(nm)

    if not all_names:
        return {}

    # Kiểm tra độ hiếm của tên 1 từ trên toàn bảng dim_leads
    allowed_single_words: Set[str] = set()
    if single_word_names:
        sw_list = list(single_word_names)
        for i in range(0, len(sw_list), 500):
            chunk = sw_list[i:i + 500]
            freq_rows = (
                db.query(func.lower(func.trim(DimLead.name)), func.count(DimLead.id))
                .filter(func.lower(func.trim(DimLead.name)).in_(chunk))
                .group_by(func.lower(func.trim(DimLead.name)))
                .all()
            )
            for lname, cnt in freq_rows:
                if lname and int(cnt or 0) <= _MAX_SINGLE_WORD_NAME_FREQ:
                    allowed_single_words.add(lname)

    valid_names = {nm for nm in all_names if (" " in nm) or (nm in allowed_single_words)}
    if not valid_names:
        return {}

    company_phones = list(COMPANY_PHONE_NUMBERS)
    candidates_by_name: Dict[str, List[Dict[str, Any]]] = {}
    name_list = list(valid_names)
    for i in range(0, len(name_list), 500):
        chunk = name_list[i:i + 500]
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
                FactLeadActivity.updated_at,
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
        for lid, dname, pg, first_dt, conv_id, status_tag, assigned, msg_cnt, upd_dt in rows:
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
                "updated_at": upd_dt,
            })

    if not candidates_by_name:
        return {}

    result: Dict[Any, List[Dict[str, Any]]] = {}
    for spec in deal_specs:
        key = spec["key"]
        existing_zalo_pages: Set[str] = spec["existing_zalo_pages"]
        existing_lead_ids: Set[int] = spec["existing_lead_ids"]
        deal_ts: Optional[datetime] = spec.get("timestamp")

        by_page: Dict[str, List[Dict[str, Any]]] = {}
        seen_lids: Set[int] = set(existing_lead_ids)
        for nm in spec["names"]:
            if nm not in valid_names:
                continue
            for cand in candidates_by_name.get(nm, []):
                lid = cand["lead_id"]
                pg = cand["page_id"]
                if lid in seen_lids or not pg or pg in existing_zalo_pages:
                    continue
                if not _is_within_deal_window(deal_ts, cand["first_created_at"], cand["updated_at"]):
                    continue
                seen_lids.add(lid)
                by_page.setdefault(pg, []).append(cand)

        matched: List[Dict[str, Any]] = []
        for pg, pg_cands in by_page.items():
            # Chỉ ghép khi trang Zalo đó có đúng 1 học viên trùng tên (tránh đoán nhầm giữa 2 người trùng tên)
            if len(pg_cands) == 1:
                matched.append(pg_cands[0])
        if matched:
            result[key] = matched

    return result


def find_lead_info_by_phone(
    phone: Optional[str],
    db: Session,
    full_name: Optional[str] = None,
    deal_timestamp: Optional[datetime] = None,
) -> Tuple[Optional[int], bool, Optional[str], Optional[str], Optional[str], str]:
    """
    Tìm thông tin DimLead và FactLeadActivity theo SĐT (có bù liên kết an toàn với hội thoại Zalo
    'Đã là học viên' bị thiếu SĐT / dính hotline nội bộ).
    Trả về: (dim_lead_id, is_student, care_by, lead_tag, page_id, source_page)
    """
    clean_phone = str(phone).strip() if phone and str(phone).strip() else ""
    items: List[Dict[str, Any]] = []
    candidate_names: Set[str] = set()
    fn_clean = _clean_match_name(full_name)
    if fn_clean:
        candidate_names.add(fn_clean)

    if clean_phone:
        rows = db.query(
            DimLead.id,
            DimLead.name,
            DimLead.page_id,
            FactLeadActivity.conversation_id,
            FactLeadActivity.status_tag,
            FactLeadActivity.assigned_users,
            FactLeadActivity.message_count
        ).join(
            FactLeadActivity, FactLeadActivity.lead_id == DimLead.id
        ).filter(
            DimLead.phone_number == clean_phone,
            ~FactLeadActivity.conversation_id.like("pzl_g_%")
        ).all()

        for lid, dname, pg, conv_id, status_tag, assigned_users, msg_cnt in rows:
            canon_pg = resolve_canonical_page_name(pg, fallback=pg) if pg else ''
            items.append({
                'lead_id': lid,
                'page_id': canon_pg,
                'conversation_id': conv_id or '',
                'status_tag': (status_tag or '').strip(),
                'assigned': (assigned_users or '').strip(),
                'message_count': int(msg_cnt or 0),
            })
            dn_clean = _clean_match_name(dname)
            if dn_clean:
                candidate_names.add(dn_clean)

    if candidate_names:
        existing_zalo_pages = {
            it['page_id'] for it in items
            if it.get('page_id') and is_zalo_channel(it.get('page_id'), it.get('conversation_id'))
        }
        extra = _find_missing_phone_zalo_students(db, [{
            "key": "single",
            "names": candidate_names,
            "existing_zalo_pages": existing_zalo_pages,
            "existing_lead_ids": {it["lead_id"] for it in items},
            "timestamp": deal_timestamp,
        }])
        if extra.get("single"):
            items.extend(extra["single"])

    if not items:
        return None, False, None, None, None, DEFAULT_SOURCE_PAGE

    return _resolve_lead_items(items)


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

    deal_phones = list({d.phone_number for d in deals if d.phone_number and d.phone_number.strip()})
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
                FactLeadActivity.conversation_id,
                FactLeadActivity.status_tag,
                FactLeadActivity.assigned_users,
                FactLeadActivity.message_count
            ).join(
                FactLeadActivity, FactLeadActivity.lead_id == DimLead.id
            ).filter(
                DimLead.phone_number.in_(chunk),
                ~FactLeadActivity.conversation_id.like("pzl_g_%")
            ).all()

            for lid, phone, dname, pg, conv_id, status_tag, assigned, msg_cnt in leads:
                if phone not in lead_map:
                    lead_map[phone] = []
                lead_map[phone].append({
                    'lead_id': lid,
                    'page_id': resolve_canonical_page_name(pg, fallback=pg) if pg else '',
                    'conversation_id': conv_id or '',
                    'status_tag': status_tag or '',
                    'assigned': (assigned or '').strip(),
                    'message_count': int(msg_cnt or 0),
                })
                dn_clean = _clean_match_name(dname)
                if dn_clean:
                    lead_names_by_phone.setdefault(phone, set()).add(dn_clean)

    # Bù liên kết an toàn với các hội thoại Zalo 'Đã là học viên' bị thiếu SĐT / dính hotline nội bộ
    deal_specs: List[Dict[str, Any]] = []
    for d in deals:
        phone = d.phone_number
        base_items = lead_map.get(phone) or []
        names: Set[str] = set(lead_names_by_phone.get(phone, set()))
        fn_clean = _clean_match_name(d.full_name)
        if fn_clean:
            names.add(fn_clean)
        if not names:
            continue
        existing_zalo_pages = {
            it['page_id'] for it in base_items
            if it.get('page_id') and is_zalo_channel(it.get('page_id'), it.get('conversation_id'))
        }
        deal_specs.append({
            "key": d.id,
            "names": names,
            "existing_zalo_pages": existing_zalo_pages,
            "existing_lead_ids": {it['lead_id'] for it in base_items},
            "timestamp": d.timestamp,
        })
    extra_zalo_by_deal = _find_missing_phone_zalo_students(db, deal_specs)

    student_count = 0
    care_by_updated = 0
    has_changes = False

    for d in deals:
        phone = d.phone_number
        base_items = lead_map.get(phone) or []
        extra_items = extra_zalo_by_deal.get(d.id) or []
        items = base_items + extra_items if extra_items else base_items
        if items:
            new_lead_id, new_is_student, new_care, new_tag, new_page_id, new_source_page = _resolve_lead_items(items)
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
                norm_care = normalize_sale_name(d.care_by)
                if norm_care != d.care_by:
                    d.care_by = norm_care
                    care_by_updated += 1
                    has_changes = True
        else:
            if d.is_student:
                d.is_student = False
                has_changes = True
            if d.page_id is not None:
                d.page_id = None
                has_changes = True
            if d.source_page != DEFAULT_SOURCE_PAGE:
                d.source_page = DEFAULT_SOURCE_PAGE
                has_changes = True

            norm_care = normalize_sale_name(d.care_by)
            if norm_care != d.care_by:
                d.care_by = norm_care
                care_by_updated += 1
                has_changes = True

    if has_changes:
        db.commit()
    return len(deals), student_count, care_by_updated
