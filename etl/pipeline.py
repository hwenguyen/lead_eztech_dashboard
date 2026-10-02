import os
import logging
from sqlalchemy.orm import Session
from database.db import SessionLocal
from database.models import RawConversation, DimLead, FactLeadActivity
from etl.pancake_client import PancakeClient
from etl.utils import parse_pancake_date, extract_customer_phone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        # Tìm SĐT trong tin nhắn của khách nếu trường phone trống (bỏ qua tin Admin để không dính hotline)
        if not phone:
            phone = extract_customer_phone(raw_data.get('messages', []))

        conv_inserted = parse_pancake_date(raw_data.get('inserted_at'))
        lead = db.query(DimLead).filter_by(customer_id=customer_id).first()
        if not lead:
            lead = DimLead(
                customer_id=customer_id,
                name=raw_data.get('customer_name', 'Unknown'),
                phone_number=phone,
                page_id=page_id,
                first_created_at=conv_inserted
            )
            db.add(lead)
            db.flush() # Để lấy lead.id
        else:
            # Update info if available
            if phone and not lead.phone_number:
                lead.phone_number = phone
            # Lead Mới tính theo hội thoại SỚM NHẤT của khách
            if conv_inserted and (not lead.first_created_at or conv_inserted < lead.first_created_at):
                lead.first_created_at = conv_inserted
            db.flush()

        # 3. Extract FactActivity
        msg_count = raw_data.get('message_count', 0)
        tags = raw_data.get('tags', [])
        status_tag = ",".join(tags) if isinstance(tags, list) and tags else None
        
        assigned_users = raw_data.get('assigned_users')
        
        # Determine is_contacted if any message from Admin or Customer
        is_contacted = False
        contacted_at = None
        c_dates = set()
        
        # Có phát sinh tin nhắn (khách hoặc nhân viên nhắn) đều tính là có liên hệ/tương tác
        for msg in raw_data.get('messages', []):
            cat = parse_pancake_date(msg.get('inserted_at'))
            if cat:
                is_contacted = True
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
    page_ids_env = os.getenv("PAGE_IDS", "")
    page_ids = [p.strip() for p in page_ids_env.split(",") if p.strip()]
    
    if not page_ids:
        logger.warning("No PAGE_IDS found in environment variables.")
        return

    # Hỗ trợ nhiều token cho nhiều page
    tokens_env = os.getenv("PANCAKE_API_TOKENS")
    if tokens_env:
        tokens = [t.strip() for t in tokens_env.split(",")]
    else:
        # Fallback dùng chung 1 token
        tokens = [os.getenv("PANCAKE_API_TOKEN")] * len(page_ids)

    db = SessionLocal()
    
    try:
        for i, page_id in enumerate(page_ids):
            logger.info(f"Processing Page ID: {page_id}")
            
            # Lấy token tương ứng với page, nếu thiếu thì dùng None (sẽ fallback trong class)
            page_token = tokens[i] if i < len(tokens) else None
            client = PancakeClient(api_token=page_token)
            
            # Kiểm tra xem đã có dữ liệu cho Page này chưa
            existing_count = db.query(RawConversation).filter_by(page_id=page_id).count()
            if existing_count == 0:
                logger.info(f"🔔 FIRST RUN DETECTED! Kéo toàn bộ lịch sử cho Page {page_id} (giới hạn an toàn 10,000 hội thoại). Sẽ mất một lúc...")
                client.limit = 10000 
            else:
                logger.info(f"⚡ DAILY RUN DETECTED! Kéo 500 hội thoại mới/cập nhật gần nhất cho Page {page_id}...")
                client.limit = 500

            # Trả connection về pool trước khi cào (có thể >1 giờ) — Neon sẽ đóng kết nối idle,
            # giữ transaction mở qua lúc cào gây lỗi "SSL connection has been closed unexpectedly"
            db.close()
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
