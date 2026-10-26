"""Module đồng bộ và map thông tin giữa DealWin (Google Sheet) và DimLead / FactLeadActivity (Pancake)."""
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple, Iterable, Set
from sqlalchemy import or_
from sqlalchemy.orm import Session, defer
from database.models import DealWin, DimLead, FactLeadActivity
from etl.utils import VN_TZ

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


def find_lead_info_by_phone(phone: Optional[str], db: Session) -> Tuple[Optional[int], bool, Optional[str], Optional[str]]:
    """
    Tìm thông tin DimLead và FactLeadActivity theo SĐT.
    Trả về: (dim_lead_id, is_student, care_by, lead_tag)
    - is_student: True nếu có tag chứa 'học viên' (vd: 'Đã là học viên')
    - care_by: Tên nhân viên phụ trách từ hội thoại có tag 'học viên'
    """
    if not phone or not str(phone).strip():
        return None, False, None, None

    clean_phone = str(phone).strip()
    lead_rows = db.query(DimLead.id).filter(DimLead.phone_number == clean_phone).all()
    if not lead_rows:
        return None, False, None, None

    lead_ids = [r[0] for r in lead_rows]
    activities = db.query(
        FactLeadActivity.status_tag,
        FactLeadActivity.assigned_users
    ).filter(FactLeadActivity.lead_id.in_(lead_ids)).all()
    all_tags = []
    hv_users = []
    other_users = []

    for status_tag, assigned_users in activities:
        tag_str = (status_tag or '').strip()
        user_str = (assigned_users or '').strip()
        if tag_str:
            all_tags.append(tag_str)
        if user_str:
            if 'học viên' in tag_str.lower():
                for n in user_str.split(','):
                    n_clean = n.strip()
                    if n_clean and n_clean not in hv_users:
                        hv_users.append(n_clean)
            else:
                for n in user_str.split(','):
                    n_clean = n.strip()
                    if n_clean and n_clean not in other_users:
                        other_users.append(n_clean)

    combined_tags = ", ".join(all_tags)
    is_student = bool(combined_tags and "học viên" in combined_tags.lower())

    if is_student and hv_users:
        assigned_user = ", ".join(hv_users)
    elif other_users:
        assigned_user = ", ".join(other_users)
    else:
        assigned_user = None

    return lead_ids[0], is_student, assigned_user, combined_tags[:255] if combined_tags else None


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
      chỉ quét các deal chưa được map (dim_lead_id IS NULL) hoặc mới cập nhật trong 48h gần nhất.
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
                DimLead.id, DimLead.phone_number, FactLeadActivity.status_tag, FactLeadActivity.assigned_users
            ).join(
                FactLeadActivity, FactLeadActivity.lead_id == DimLead.id
            ).filter(DimLead.phone_number.in_(chunk)).all()

            for lid, phone, status_tag, assigned in leads:
                if phone not in lead_map:
                    lead_map[phone] = []
                lead_map[phone].append({
                    'lead_id': lid,
                    'status_tag': status_tag or '',
                    'assigned': (assigned or '').strip()
                })

    student_count = 0
    care_by_updated = 0
    has_changes = False

    for d in deals:
        phone = d.phone_number
        items = lead_map.get(phone)
        if items:
            new_lead_id = items[0]['lead_id']
            if d.dim_lead_id != new_lead_id:
                d.dim_lead_id = new_lead_id
                has_changes = True

            all_tags = ', '.join(it['status_tag'] for it in items if it['status_tag'])
            new_tag = all_tags[:255] if all_tags else None
            if d.lead_tag != new_tag:
                d.lead_tag = new_tag
                has_changes = True
            
            # Chỉ tính là học viên nếu hội thoại có tag chứa 'học viên'
            hv_items = [it for it in items if 'học viên' in (it['status_tag'] or '').lower()]
            new_is_student = len(hv_items) > 0
            if new_is_student:
                student_count += 1
            if d.is_student != new_is_student:
                d.is_student = new_is_student
                has_changes = True

            # Gán nhân viên chăm sóc: Ưu tiên CHÍNH XÁC từ hội thoại có tag 'học viên'
            new_care = None
            if new_is_student:
                hv_assigned = [it['assigned'] for it in hv_items if it.get('assigned')]
                if hv_assigned:
                    names = []
                    for u in hv_assigned:
                        for n in u.split(','):
                            n_clean = n.strip()
                            if n_clean and n_clean not in names:
                                names.append(n_clean)
                    new_care = ', '.join(names) if names else hv_assigned[0]
            else:
                other_assigned = [it['assigned'] for it in items if it.get('assigned')]
                if other_assigned:
                    new_care = other_assigned[0]

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

            norm_care = normalize_sale_name(d.care_by)
            if norm_care != d.care_by:
                d.care_by = norm_care
                care_by_updated += 1
                has_changes = True

    if has_changes:
        db.commit()
    return len(deals), student_count, care_by_updated
