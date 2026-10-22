"""Module đồng bộ và map thông tin giữa DealWin (Google Sheet) và DimLead / FactLeadActivity (Pancake)."""
from typing import Optional, Tuple
from sqlalchemy.orm import Session
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
    lead = db.query(DimLead).filter(DimLead.phone_number == clean_phone).first()
    if not lead:
        return None, False, None, None

    activities = db.query(FactLeadActivity).filter(FactLeadActivity.lead_id == lead.id).all()
    all_tags = []
    assigned_user = None

    for act in activities:
        if act.status_tag:
            all_tags.append(act.status_tag.strip())
        if act.assigned_users and not assigned_user:
            assigned_user = act.assigned_users.strip()

    combined_tags = ", ".join(all_tags)
    is_student = bool(combined_tags and "học viên" in combined_tags.lower())

    return lead.id, is_student, assigned_user, combined_tags[:255] if combined_tags else None


def sync_all_deals_with_dim_leads(db: Session) -> Tuple[int, int, int]:
    """
    Quét và đồng bộ toàn bộ bảng deal_wins với dim_leads:
    - Map SĐT sang DimLead
    - Đánh dấu is_student nếu có tag 'Đã là học viên'
    - Cập nhật care_by theo nhân viên chăm sóc trên Pancake
    Trả về: (total_processed, student_count, care_by_updated)
    """
    # Lấy toàn bộ lead có SĐT
    leads = db.query(
        DimLead.id, DimLead.phone_number, FactLeadActivity.status_tag, FactLeadActivity.assigned_users
    ).join(
        FactLeadActivity, FactLeadActivity.lead_id == DimLead.id
    ).filter(DimLead.phone_number.isnot(None), DimLead.phone_number != '').all()

    lead_map = {}
    for lid, phone, status_tag, assigned in leads:
        if phone not in lead_map:
            lead_map[phone] = []
        lead_map[phone].append({
            'lead_id': lid,
            'status_tag': status_tag or '',
            'assigned': (assigned or '').strip()
        })

    deals = db.query(DealWin).all()
    student_count = 0
    care_by_updated = 0

    for d in deals:
        phone = d.phone_number
        items = lead_map.get(phone)
        if items:
            d.dim_lead_id = items[0]['lead_id']
            all_tags = ', '.join(it['status_tag'] for it in items if it['status_tag'])
            d.lead_tag = all_tags[:255] if all_tags else None
            
            if 'học viên' in all_tags.lower():
                d.is_student = True
                student_count += 1
            else:
                d.is_student = False

            users = [it['assigned'] for it in items if it['assigned']]
            if users:
                new_care = users[0]
                if d.care_by != new_care:
                    d.care_by = new_care
                    care_by_updated += 1
        else:
            d.is_student = False

    db.commit()
    return len(deals), student_count, care_by_updated
