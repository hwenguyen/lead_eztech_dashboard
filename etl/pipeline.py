import os
import logging
from typing import Optional, Dict, Any
from sqlalchemy import or_
from sqlalchemy.orm import Session
from database.db import SessionLocal
from database.models import RawConversation, DimLead, FactLeadActivity
from database.schema import ensure_schema
from etl.pancake_client import PancakeClient
from etl.utils import parse_pancake_date, resolve_phone, normalize_phone, is_page_id, resolve_canonical_page_name
import re

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
            if not raw_record.page_id or is_page_id(raw_record.page_id):
                raw_record.page_id = page_id

        # 2. Extract DimLead
        # SĐT: ưu tiên số Pancake đã thu thập, sau đó tìm trong tin nhắn của khách (bỏ qua tin Admin để không dính hotline)
        phone, phone_at = resolve_phone(raw_data)

        conv_inserted = parse_pancake_date(raw_data.get('inserted_at'))
        lead = db.query(DimLead).filter_by(customer_id=customer_id).first()
        if not lead:
            lead = DimLead(
                customer_id=customer_id,
                name=raw_data.get('customer_name', 'Unknown'),
                phone_number=phone,
                phone_at=phone_at,
                page_id=page_id,
                first_created_at=conv_inserted
            )
            db.add(lead)
            db.flush() # Để lấy lead.id
        else:
            # Update info if available
            if lead.phone_number:
                lead.phone_number = normalize_phone(lead.phone_number) or lead.phone_number
            elif phone:
                lead.phone_number = phone
                # Lead đã có từ trước nay mới có số mà không thấy tin chứa số → coi như vừa thu được
                phone_at = phone_at or parse_pancake_date(raw_data.get('updated_at'))
            # Giữ thời điểm SỚM NHẤT khách gửi đúng số đang lưu. Payload chỉ có 30 tin gần nhất nên
            # khi không còn thấy tin chứa số (phone_at = None) thì giữ nguyên giá trị đã lưu.
            if phone_at and phone == lead.phone_number and (not lead.phone_at or phone_at < lead.phone_at):
                lead.phone_at = phone_at
            # Chuẩn hoá page_id về tên chữ nếu trước đó lưu ID số / pzl_ ID
            if not lead.page_id or is_page_id(lead.page_id):
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
    # ETL có thể chạy trước khi Backend kịp thêm cột mới → tự đồng bộ schema
    ensure_schema()

    pages_to_process: List[Dict[str, Any]] = []

    # 1. Hỗ trợ cấu hình dạng JSON / Dict qua secret PANCAKE_PAGES_JSON, PANCAKE_CONFIG hoặc PANCAKE_API_TOKENS
    pages_json_env = os.getenv("PANCAKE_PAGES_JSON") or os.getenv("PANCAKE_CONFIG")
    
    pancake_api_tokens_env = os.getenv("PANCAKE_API_TOKENS", "").strip()
    if not pages_json_env and (pancake_api_tokens_env.startswith("{") or pancake_api_tokens_env.startswith("[")):
        pages_json_env = pancake_api_tokens_env

    if pages_json_env and pages_json_env.strip():
        try:
            import json, ast
            raw_cfg = pages_json_env.strip()
            try:
                cfg_data = json.loads(raw_cfg)
            except Exception:
                cfg_data = ast.literal_eval(raw_cfg)
            
            if isinstance(cfg_data, dict):
                for pid, pdata in cfg_data.items():
                    if isinstance(pdata, dict):
                        pages_to_process.append({
                            "page_id": str(pid).strip(),
                            "page_name": pdata.get("name"),
                            "token": pdata.get("token")
                        })
                    elif isinstance(pdata, str):
                        pages_to_process.append({
                            "page_id": str(pid).strip(),
                            "page_name": None,
                            "token": pdata.strip()
                        })
            elif isinstance(cfg_data, list):
                for item in cfg_data:
                    if isinstance(item, dict) and "page_id" in item:
                        pages_to_process.append(item)
            logger.info(f"Đã nạp {len(pages_to_process)} Fanpage từ cấu hình JSON/Dict.")
        except Exception as e:
            logger.warning(f"Không thể parse cấu hình JSON/Dict: {e}")

    # 2. Nếu không có hoặc parse lỗi, fallback sang PAGE_IDS và PANCAKE_API_TOKENS
    if not pages_to_process:
        page_ids_env = os.getenv("PAGE_IDS", "")
        page_ids = [p.strip() for p in page_ids_env.split(",") if p.strip()]
        
        if not page_ids:
            logger.warning("No PAGE_IDS found in environment variables.")
            return

        tokens_env = os.getenv("PANCAKE_API_TOKENS", "").strip()
        single_token = os.getenv("PANCAKE_API_TOKEN", "").strip()
        tokens = [t.strip() for t in tokens_env.split(",") if t.strip()] if tokens_env else []
        default_token = single_token or (tokens[0] if tokens else None)

        for i, page_id in enumerate(page_ids):
            token = tokens[i] if i < len(tokens) and tokens[i] else default_token
            pages_to_process.append({
                "page_id": page_id,
                "page_name": None,
                "token": token
            })

    first_run_limit = int(os.getenv("FIRST_RUN_LIMIT", "2000"))
    daily_run_limit = int(os.getenv("DAILY_RUN_LIMIT", "1000"))
    daily_days_back = int(os.getenv("DAILY_DAYS_BACK", "3"))

    db = SessionLocal()
    
    try:
        for p_info in pages_to_process:
            page_id = p_info["page_id"]
            page_token = p_info.get("token")
            preset_name = p_info.get("page_name")
            logger.info(f"Processing Page ID: {page_id} (Tên cấu hình: {preset_name or 'Auto'})")
            try:
                client = PancakeClient(api_token=page_token)
                
                # 1. Kiểm tra số lượng và xây dựng cache từ DB để skip tải lại tin nhắn không đổi
                existing_cache: Dict[str, Any] = {}
                known_page_name = resolve_canonical_page_name(page_id, fallback=None)
                if known_page_name == str(page_id).strip() and is_page_id(page_id):
                    known_page_name = None

                clean_id = str(page_id).strip()
                clean_num = re.sub(r"^(pzl_|tt_|fb_)", "", clean_id)
                try:
                    page_filter = or_(
                        RawConversation.page_id == page_id,
                        RawConversation.page_id == clean_num,
                        RawConversation.page_id == known_page_name,
                        RawConversation.pancake_id.contains(clean_num)
                    )
                    existing_count = db.query(RawConversation.id).filter(page_filter).count()

                    # Nạp tối đa 1.500 hội thoại gần nhất làm cache so khớp để tiết kiệm RAM và mạng
                    raw_rows = db.query(
                        RawConversation.pancake_id,
                        RawConversation.payload,
                        RawConversation.page_id
                    ).filter(page_filter).order_by(RawConversation.id.desc()).limit(1500).all()

                    for p_id, payload, pg_name in raw_rows:
                        if pg_name and not is_page_id(pg_name) and not known_page_name:
                            known_page_name = str(pg_name).strip()
                        if payload and isinstance(payload, dict):
                            existing_cache[str(p_id)] = {
                                "updated_at": payload.get("updated_at"),
                                "messages": payload.get("messages", []),
                                "phone_number": payload.get("phone_number")
                            }
                    logger.info(f"Đã nạp {len(existing_cache)} hội thoại từ cache DB của Page {page_id} (Tên đã biết: '{known_page_name or 'Chưa rõ'}').")
                except Exception as e:
                    logger.warning(f"Không thể đọc cache DB: {e}")
                    existing_count = 0

                if existing_count == 0:
                    logger.info(f"🔔 FIRST RUN DETECTED! Kéo {first_run_limit} hội thoại lịch sử cho Page {page_id}...")
                    client.limit = first_run_limit 
                    days_back_param = None
                else:
                    logger.info(f"⚡ DAILY RUN DETECTED! Kéo hội thoại {daily_days_back} ngày gần nhất (tối đa {daily_run_limit}) cho Page {page_id}...")
                    client.limit = daily_run_limit
                    days_back_param = daily_days_back

                # Đóng session trước khi cào dữ liệu qua API để không giữ idle connection trên Neon
                db.close()
                conversations = client.get_conversations(
                    page_id=page_id,
                    existing_cache=existing_cache,
                    days_back=days_back_param
                )
                total = len(conversations)

                # Tên chuẩn của riêng Page này (ưu tiên tên API trả về -> tên cấu hình preset -> tên cấu hình chuẩn -> tên DB)
                canonical_page_name = (
                    getattr(client, 'page_name', None)
                    or preset_name
                    or resolve_canonical_page_name(page_id, fallback=None)
                    or known_page_name
                    or (page_id if not is_page_id(page_id) else None)
                )
                if not canonical_page_name or is_page_id(canonical_page_name):
                    canonical_page_name = preset_name or known_page_name or resolve_canonical_page_name(page_id, fallback=page_id)

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
                    logger.error(f"Lỗi khi lưu dữ liệu theo batch cho Page {page_id}: {e}")
            except Exception as page_err:
                logger.error(f"Lỗi khi cào dữ liệu cho Page {page_id}: {page_err}", exc_info=True)
                # Đảm bảo session db mở lại cho lượt loop tiếp theo
                db = SessionLocal()
    finally:
        db.close()
        
    logger.info("ETL Pipeline completed successfully in record time.")

if __name__ == "__main__":
    # Test chạy trực tiếp
    run_etl_pipeline()
