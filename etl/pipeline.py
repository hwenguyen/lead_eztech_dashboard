import os
import logging
from typing import Optional, Dict, Any
from sqlalchemy import or_
from sqlalchemy.orm import Session
from database.db import SessionLocal
from database.models import RawConversation, DimLead, FactLeadActivity
from etl.pancake_client import PancakeClient
from etl.utils import parse_pancake_date, extract_customer_phone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def upsert_lead_data(db: Session, raw_data: dict, page_id: str, commit: bool = True):
    """
    Logic upsert Lead và Activity với hỗ trợ batch commit.
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
            if not raw_record.page_id or raw_record.page_id.strip().isdigit():
                raw_record.page_id = page_id

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
            # Chuẩn hoá page_id về tên chữ nếu trước đó lưu ID số
            if not lead.page_id or lead.page_id.strip().isdigit():
                lead.page_id = page_id
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
                        
        # Fallback lấy thời điểm hoạt động gần nhất từ updated_at nếu tin nhắn chưa bao quát
        conv_updated = parse_pancake_date(raw_data.get('updated_at'))
        if conv_updated:
            is_contacted = True
            if not contacted_at or conv_updated > contacted_at:
                contacted_at = conv_updated
            c_dates.add(conv_updated.strftime("%Y-%m-%d"))

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

        if commit:
            db.commit()
    except Exception as e:
        if commit:
            db.rollback()
        logger.error(f"Error upserting conversation {raw_data.get('id')}: {e}")

def run_etl_pipeline():
    logger.info("Starting Fast ETL Pipeline...")
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

    first_run_limit = int(os.getenv("FIRST_RUN_LIMIT", "2000"))
    daily_run_limit = int(os.getenv("DAILY_RUN_LIMIT", "500"))

    db = SessionLocal()
    
    try:
        for i, page_id in enumerate(page_ids):
            logger.info(f"Processing Page ID: {page_id}")
            
            page_token = tokens[i] if i < len(tokens) else None
            client = PancakeClient(api_token=page_token)
            
            # 1. Kiểm tra số lượng và xây dựng cache từ DB để skip tải lại tin nhắn không đổi
            existing_cache: Dict[str, Any] = {}
            try:
                raw_rows = db.query(RawConversation.pancake_id, RawConversation.payload).filter(
                    or_(RawConversation.page_id == page_id, RawConversation.page_id == "Anh Kế toán làm Data")
                ).all()
                existing_count = len(raw_rows)
                for p_id, payload in raw_rows:
                    if payload and isinstance(payload, dict):
                        existing_cache[str(p_id)] = {
                            "updated_at": payload.get("updated_at"),
                            "messages": payload.get("messages", []),
                            "phone_number": payload.get("phone_number")
                        }
                logger.info(f"Đã nạp {len(existing_cache)} hội thoại từ cache DB của Page {page_id}.")
            except Exception as e:
                logger.warning(f"Không thể đọc cache DB: {e}")
                existing_count = db.query(RawConversation).filter(
                    or_(RawConversation.page_id == page_id, RawConversation.page_id == "Anh Kế toán làm Data")
                ).count()

            if existing_count == 0:
                logger.info(f"🔔 FIRST RUN DETECTED! Kéo {first_run_limit} hội thoại lịch sử cho Page {page_id}...")
                client.limit = first_run_limit 
            else:
                logger.info(f"⚡ DAILY RUN DETECTED! Kéo {daily_run_limit} hội thoại mới/cập nhật gần nhất cho Page {page_id}...")
                client.limit = daily_run_limit

            # Đóng session trước khi cào dữ liệu qua API để không giữ idle connection trên Neon
            db.close()
            conversations = client.get_conversations(page_id=page_id, existing_cache=existing_cache)
            total = len(conversations)

            # Tên chuẩn của Page để lưu vào DB (ví dụ 'Anh Kế toán làm Data')
            canonical_page_name = getattr(client, 'page_name', None) or "Anh Kế toán làm Data"

            # 2. Mở session mới và lưu dữ liệu vào DB theo Batch (50 items/commit)
            db = SessionLocal()
            try:
                for idx, conv in enumerate(conversations):
                    upsert_lead_data(db, conv, canonical_page_name, commit=False)
                    if (idx + 1) % 50 == 0:
                        db.commit()
                        logger.info(f"Đã lưu vào DB: {idx + 1}/{total} hội thoại...")
                db.commit()
                logger.info(f"Hoàn tất lưu DB: {total}/{total} hội thoại.")
            except Exception as e:
                db.rollback()
                logger.error(f"Lỗi khi lưu dữ liệu theo batch: {e}")
            finally:
                db.close()
    finally:
        db.close()
        
    logger.info("ETL Pipeline completed successfully in record time.")

if __name__ == "__main__":
    # Test chạy trực tiếp
    run_etl_pipeline()
