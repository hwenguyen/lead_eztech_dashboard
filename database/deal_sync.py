"""Module đồng bộ và map thông tin giữa DealWin (Google Sheet) và DimLead / FactLeadActivity (Pancake)."""
from typing import Optional, Tuple
from sqlalchemy.orm import Session, defer
from database.models import DealWin, DimLead, FactLeadActivity

def find_lead_info_by_phone(phone: Optional[str], db: Session) -> Tuple[Optional[int], bool, Optional[str], Optional[str]]:
    """
    Tìm thông tin DimLead và FactLeadActivity theo SĐT.
    Trả về: (dim_lead_id, is_student, care_by, lead_tag)
    - is_student: True nếu có tag chứa 'học viên' (vd: 'Đã là học viên')
    - care_by: Tên nhân viên phụ trách từ Pancake (assigned_users)
    """
    if not phone or not str(phone).strip():
        return None, False, None, None

    clean_phone = str(phone).strip()
    lead_row = db.query(DimLead.id).filter(DimLead.phone_number == clean_phone).first()
    if not lead_row:
        return None, False, None, None

    lead_id = lead_row[0]
    activities = db.query(
        FactLeadActivity.status_tag,
        FactLeadActivity.assigned_users
    ).filter(FactLeadActivity.lead_id == lead_id).all()
    all_tags = []
    assigned_user = None

    for status_tag, assigned_users in activities:
        if status_tag:
            all_tags.append(status_tag.strip())
        if assigned_users and not assigned_user:
            assigned_user = assigned_users.strip()

    combined_tags = ", ".join(all_tags)
    is_student = bool(combined_tags and "học viên" in combined_tags.lower())

    return lead_id, is_student, assigned_user, combined_tags[:255] if combined_tags else None


def sync_all_deals_with_dim_leads(db: Session) -> Tuple[int, int, int]:
    """
    Quét và đồng bộ toàn bộ bảng deal_wins với dim_leads:
    - Dùng defer(DealWin.raw_data) để không tải 2MB JSON raw_data qua mạng
    - Chỉ truy vấn DimLead theo đúng danh sách SĐT có trong deal_wins (thay vì quét toàn bộ 13.000 dòng)
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
            
            new_is_student = ('học viên' in all_tags.lower())
            if new_is_student:
                student_count += 1
            if d.is_student != new_is_student:
                d.is_student = new_is_student
                has_changes = True

            users = [it['assigned'] for it in items if it['assigned']]
            if users:
                new_care = users[0]
                if d.care_by != new_care:
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
