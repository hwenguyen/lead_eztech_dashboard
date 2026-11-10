"""Module đồng bộ và map thông tin giữa DealWin (Google Sheet) và DimLead / FactLeadActivity (Pancake)."""
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple, Iterable, Set, List, Dict, Any
from sqlalchemy import or_
from sqlalchemy.orm import Session, defer
from database.models import DealWin, DimLead, FactLeadActivity
from etl.utils import VN_TZ, resolve_canonical_page_name

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


def _resolve_lead_items(items: List[Dict[str, Any]]) -> Tuple[Optional[int], bool, Optional[str], Optional[str], Optional[str]]:
    """
    Tổng hợp danh sách hội thoại của 1 SĐT:
    - Trả về: (dim_lead_id, is_student, care_by, lead_tag, page_id)
    - Vì 1 lead có thể nhắn trên nhiều kênh: chỉ lấy hội thoại thuộc kênh có số lượng tin nhắn (message_count) nhiều nhất.
    - Nhân viên phụ trách lấy theo assigned_user có số lượng tin nhắn của lead trong hội thoại với nhân viên đó nhiều nhất.
    """
    if not items:
        return None, False, None, None, None

    all_tags = []
    for it in items:
        for t in (it.get('status_tag') or '').split(','):
            t_clean = t.strip()
            if t_clean and t_clean not in all_tags:
                all_tags.append(t_clean)
    combined_tags = ", ".join(all_tags)[:255] if all_tags else None

    is_student = any('học viên' in (it.get('status_tag') or '').lower() for it in items)

    # Ưu tiên xét trong các hội thoại có nhân viên phụ trách (nếu có), chọn hội thoại thuộc kênh có số tin nhắn nhiều nhất
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
    best_page = best_conv.get('page_id') or None
    assigned_user = pick_best_assigned_user(items)

    return best_lead_id, is_student, assigned_user, combined_tags, best_page


def find_lead_info_by_phone(phone: Optional[str], db: Session) -> Tuple[Optional[int], bool, Optional[str], Optional[str], Optional[str]]:
    """
    Tìm thông tin DimLead và FactLeadActivity theo SĐT.
    Trả về: (dim_lead_id, is_student, care_by, lead_tag, page_id)
    """
    if not phone or not str(phone).strip():
        return None, False, None, None, None

    clean_phone = str(phone).strip()
    rows = db.query(
        DimLead.id,
        DimLead.page_id,
        FactLeadActivity.status_tag,
        FactLeadActivity.assigned_users,
        FactLeadActivity.message_count
    ).join(
        FactLeadActivity, FactLeadActivity.lead_id == DimLead.id
    ).filter(
        DimLead.phone_number == clean_phone,
        ~FactLeadActivity.conversation_id.like("pzl_g_%")
    ).all()

    if not rows:
        return None, False, None, None, None

    items = [
        {
            'lead_id': lid,
            'page_id': resolve_canonical_page_name(pg, fallback=pg) if pg else '',
            'status_tag': (status_tag or '').strip(),
            'assigned': (assigned_users or '').strip(),
            'message_count': int(msg_cnt or 0),
        }
        for lid, pg, status_tag, assigned_users, msg_cnt in rows
    ]
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
    query = db.query(DealWin).options(defer(DealWin.raw_data))

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
                DealWin.updated_at >= cutoff
            )
        )

    deals = query.all()
    if not deals:
        return 0, 0, 0

    deal_phones = list({d.phone_number for d in deals if d.phone_number and d.phone_number.strip()})
    lead_map = {}

    if deal_phones:
        # Chia chunk 500 SĐT để dùng index ix_dim_leads_phone_number cực nhanh
        for i in range(0, len(deal_phones), 500):
            chunk = deal_phones[i:i + 500]
            leads = db.query(
                DimLead.id,
                DimLead.phone_number,
                DimLead.page_id,
                FactLeadActivity.status_tag,
                FactLeadActivity.assigned_users,
                FactLeadActivity.message_count
            ).join(
                FactLeadActivity, FactLeadActivity.lead_id == DimLead.id
            ).filter(
                DimLead.phone_number.in_(chunk),
                ~FactLeadActivity.conversation_id.like("pzl_g_%")
            ).all()

            for lid, phone, pg, status_tag, assigned, msg_cnt in leads:
                if phone not in lead_map:
                    lead_map[phone] = []
                lead_map[phone].append({
                    'lead_id': lid,
                    'page_id': resolve_canonical_page_name(pg, fallback=pg) if pg else '',
                    'status_tag': status_tag or '',
                    'assigned': (assigned or '').strip(),
                    'message_count': int(msg_cnt or 0),
                })

    student_count = 0
    care_by_updated = 0
    has_changes = False

    for d in deals:
        phone = d.phone_number
        items = lead_map.get(phone)
        if items:
            new_lead_id, new_is_student, new_care, new_tag, new_page_id = _resolve_lead_items(items)
            if d.dim_lead_id != new_lead_id:
                d.dim_lead_id = new_lead_id
                has_changes = True

            if d.page_id != new_page_id:
                d.page_id = new_page_id
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

            norm_care = normalize_sale_name(d.care_by)
            if norm_care != d.care_by:
                d.care_by = norm_care
                care_by_updated += 1
                has_changes = True

    if has_changes:
        db.commit()
    return len(deals), student_count, care_by_updated
