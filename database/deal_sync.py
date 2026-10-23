"""Module đồng bộ và map thông tin giữa DealWin (Google Sheet) và DimLead / FactLeadActivity (Pancake)."""
from typing import Optional, Tuple
from sqlalchemy.orm import Session, defer
from database.models import DealWin, DimLead, FactLeadActivity

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


def sync_all_deals_with_dim_leads(db: Session) -> Tuple[int, int, int]:
    """
    Quét và đồng bộ toàn bộ bảng deal_wins với dim_leads:
    - Dùng defer(DealWin.raw_data) để không tải 2MB JSON raw_data qua mạng
    - Chỉ truy vấn DimLead theo đúng danh sách SĐT có trong deal_wins (thay vì quét toàn bộ 13.000 dòng)
    - Chỉ gán nhân viên chăm sóc (care_by) từ chính hội thoại CÓ TAG 'học viên' (hoặc 'Đã là học viên')
    - Chỉ ghi DB khi có trường thay đổi thực sự
    Trả về: (total_processed, student_count, care_by_updated)
    """
    deals = db.query(DealWin).options(defer(DealWin.raw_data)).all()
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

            if new_care and d.care_by != new_care:
                d.care_by = new_care
                care_by_updated += 1
                has_changes = True
        else:
            if d.is_student:
                d.is_student = False
                has_changes = True

    if has_changes:
        db.commit()
    return len(deals), student_count, care_by_updated
