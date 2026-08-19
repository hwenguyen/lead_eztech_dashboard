import re
import os
import logging
from datetime import datetime
from dateutil.parser import parse
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert # Dùng insert của PostgreSQL cho Upsert (nếu dùng SQLite thì cần handle thủ công)
from database.db import SessionLocal
from database.models import RawConversation, DimLead, FactLeadActivity
from etl.pancake_client import PancakeClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PHONE_REGEX = re.compile(r"(0|\+84)(3[2-9]|5[6|8|9]|7[0|6-9]|8[1-5|8|9]|9[0-9])[0-9]{7}")

def extract_phone_number(text: str) -> str:
    if not text:
        return None
    match = PHONE_REGEX.search(text)
    return match.group(0) if match else None

from datetime import datetime, timedelta, timezone

def parse_pancake_date(date_str: str) -> datetime:
    try:
        dt = parse(date_str)
        # Nếu Pancake trả về không có múi giờ, ta ngầm định đó là UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
            
        # Chuyển đổi sang múi giờ Việt Nam (UTC+7)
        vn_tz = timezone(timedelta(hours=7))
        dt_vn = dt.astimezone(vn_tz)
        
        # Lưu vào DB dưới dạng naive datetime (bỏ tz đi để so sánh cho dễ)
        return dt_vn.replace(tzinfo=None)
    except:
        return datetime.utcnow() + timedelta(hours=7)

def upsert_lead_data(db: Session, raw_data: dict, page_id: str):
    """
    Logic upsert Lead và Activity.
    Vì SQLite không support sẵn postgresql.insert on_conflict_do_update dễ dàng trong SQLAlchemy < 2.0 (hoặc nếu không setup đúng dialect),
    Ta dùng query before insert/update cho dễ tương thích mọi DB.
    """
    try:
        # 1. Lưu Raw
        conv_id = str(raw_data.get('id', ''))
        customer_id = str(raw_data.get('customer_id', ''))
        
        # Bỏ qua Comment (Chỉ lấy Message)
        conv_type = str(raw_data.get('type', '')).upper()
        if conv_type == 'COMMENT':
            return
            
        if not conv_id or not customer_id:
            return

        raw_record = db.query(RawConversation).filter_by(pancake_id=conv_id).first()
        if not raw_record:
            raw_record = RawConversation(pancake_id=conv_id, page_id=page_id, payload=raw_data)
            db.add(raw_record)
        else:
            raw_record.payload = raw_data

        # 2. Extract DimLead
        phone = raw_data.get('phone_number')
        # Tìm SĐT trong text tin nhắn nếu trường phone trống
        if not phone and raw_data.get('messages'):
            for msg in raw_data['messages']:
                extracted = extract_phone_number(msg.get('message', ''))
                if extracted:
                    phone = extracted
                    break
                    
        lead = db.query(DimLead).filter_by(customer_id=customer_id).first()
        if not lead:
            lead = DimLead(
                customer_id=customer_id,
                name=raw_data.get('customer_name', 'Unknown'),
                phone_number=phone,
                page_id=page_id,
                first_created_at=parse_pancake_date(raw_data.get('inserted_at'))
            )
            db.add(lead)
            db.flush() # Để lấy lead.id
        else:
            # Update info if available
            if phone and not lead.phone_number:
                lead.phone_number = phone
            db.flush()

        # 3. Extract FactActivity
        msg_count = raw_data.get('message_count', 0)
        tags = raw_data.get('tags', [])
        status_tag = ",".join(tags) if isinstance(tags, list) and tags else None
        
        assigned_users = raw_data.get('assigned_users')
        
        # Determine is_contacted if any message from Admin
        is_contacted = False
        contacted_at = None
        c_dates = set()
        for msg in raw_data.get('messages', []):
            if msg.get('role') == 'Admin':
                is_contacted = True
                cat = parse_pancake_date(msg.get('inserted_at'))
                if cat:
                    c_dates.add(cat.strftime("%Y-%m-%d"))
                    if not contacted_at or cat > contacted_at:
                        contacted_at = cat
                        
        contacted_dates_str = ",".join(sorted(list(c_dates))) if c_dates else None

        activity = db.query(FactLeadActivity).filter_by(conversation_id=conv_id).first()
        if not activity:
            activity = FactLeadActivity(
                lead_id=lead.id,
                conversation_id=conv_id,
                status_tag=status_tag,
                assigned_users=assigned_users,
                message_count=msg_count,
                is_contacted=is_contacted,
                contacted_at=contacted_at,
                contacted_dates=contacted_dates_str
            )
            db.add(activity)
        else:
            activity.status_tag = status_tag
            activity.assigned_users = assigned_users
            activity.message_count = msg_count
            activity.is_contacted = is_contacted
            activity.contacted_dates = contacted_dates_str
            if contacted_at:
                activity.contacted_at = contacted_at

        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error upserting conversation {raw_data.get('id')}: {e}")

def run_etl_pipeline():
    logger.info("Starting ETL Pipeline...")
    page_ids = os.getenv("PAGE_IDS", "").split(",")
    page_ids = [p.strip() for p in page_ids if p.strip()]
    
    if not page_ids:
        logger.warning("No PAGE_IDS found in environment variables.")
        return

    client = PancakeClient()
    db = SessionLocal()
    
    try:
        for page_id in page_ids:
            logger.info(f"Processing Page ID: {page_id}")
            
            # Kiểm tra xem đã có dữ liệu cho Page này chưa
            existing_count = db.query(RawConversation).filter_by(page_id=page_id).count()
            if existing_count == 0:
                logger.info(f"🔔 FIRST RUN DETECTED! Kéo toàn bộ lịch sử cho Page {page_id} (giới hạn an toàn 10,000 hội thoại). Sẽ mất một lúc...")
                client.limit = 10000 
            else:
                logger.info(f"⚡ DAILY RUN DETECTED! Kéo 100 hội thoại mới/cập nhật gần nhất cho Page {page_id}...")
                client.limit = 100
                
            conversations = client.get_conversations(page_id=page_id)
            total = len(conversations)
            for idx, conv in enumerate(conversations):
                upsert_lead_data(db, conv, page_id)
                if (idx + 1) % 50 == 0:
                    logger.info(f"Đã lưu vào DB: {idx + 1}/{total} hội thoại...")
    finally:
        db.close()
        
    logger.info("ETL Pipeline completed successfully.")

if __name__ == "__main__":
    # Test chạy trực tiếp
    run_etl_pipeline()
