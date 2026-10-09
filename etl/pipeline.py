import os
import time
import logging
from typing import Optional, Dict, Any, List, Iterable
from sqlalchemy import or_, func
from sqlalchemy.orm import Session
from database.db import SessionLocal
from database.models import RawConversation, DimLead, FactLeadActivity
from database.schema import ensure_schema
from etl.pancake_client import PancakeClient
from etl.utils import parse_pancake_date, resolve_phone, normalize_phone, is_page_id, resolve_canonical_page_name
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

IN_CHUNK = 500  # Số phần tử tối đa trong 1 câu IN (...) khi nạp sẵn dữ liệu
DB_BATCH = 200  # Số hội thoại mỗi lô ghi DB (1 lần prefetch + 1 commit)


def _chunks(items: List[str], size: int = IN_CHUNK) -> Iterable[List[str]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def prefetch_records(db: Session, conversations: List[dict]) -> Dict[str, Dict[str, Any]]:
    """Nạp sẵn RawConversation / DimLead / FactLeadActivity của cả lô bằng vài câu IN (...).
    Thay cho 3 câu SELECT + flush cho MỖI hội thoại — mỗi câu là 1 round trip từ runner GitHub tới Neon."""
    conv_ids = list({str(c.get('id')) for c in conversations if c.get('id')})
    cust_ids = list({str(c.get('customer_id')) for c in conversations if c.get('customer_id')})
    maps: Dict[str, Dict[str, Any]] = {"raw": {}, "lead": {}, "activity": {}}
    for chunk in _chunks(conv_ids):
        for r in db.query(RawConversation).filter(RawConversation.pancake_id.in_(chunk)):
            maps["raw"][r.pancake_id] = r
        for a in db.query(FactLeadActivity).filter(FactLeadActivity.conversation_id.in_(chunk)):
            maps["activity"][a.conversation_id] = a
    for chunk in _chunks(cust_ids):
        for lead in db.query(DimLead).filter(DimLead.customer_id.in_(chunk)):
            maps["lead"][lead.customer_id] = lead
    return maps


def upsert_lead_data(db: Session, raw_data: dict, page_id: str, commit: bool = True,
                     prefetched: Optional[Dict[str, Dict[str, Any]]] = None):
    """
    Logic upsert Lead và Activity với hỗ trợ batch commit.
    prefetched: kết quả prefetch_records() → không query/flush từng dòng (nhanh hơn nhiều trên Neon).
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

        if prefetched is not None:
            raw_record = prefetched["raw"].get(conv_id)
        else:
            raw_record = db.query(RawConversation).filter_by(pancake_id=conv_id).first()
        if not raw_record:
            raw_record = RawConversation(pancake_id=conv_id, page_id=page_id, payload=raw_data)
            db.add(raw_record)
            if prefetched is not None:
                prefetched["raw"][conv_id] = raw_record
        else:
            # Preserve old messages if new payload is from cache and empty
            old_payload = raw_record.payload or {}
            if not raw_data.get('messages') and old_payload.get('messages'):
                raw_data['messages'] = old_payload.get('messages')
                
            raw_record.payload = raw_data
            if not raw_record.page_id or is_page_id(raw_record.page_id):
                raw_record.page_id = page_id

        # 2. Extract DimLead
        # SĐT: ưu tiên số Pancake đã thu thập, sau đó tìm trong tin nhắn của khách
        phone, phone_at = resolve_phone(raw_data)

        # Ngày tạo hội thoại tự sinh từ Pancake API (chuẩn giờ Việt Nam UTC+7)
        conv_inserted = parse_pancake_date(raw_data.get('inserted_at'))

        if prefetched is not None:
            lead = prefetched["lead"].get(customer_id)
        else:
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
            if prefetched is not None:
                # Activity gắn qua relationship → không cần flush lấy lead.id ngay
                prefetched["lead"][customer_id] = lead
            else:
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
            if prefetched is None:
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

        tag_timeline = raw_data.get('tag_timeline')

        if prefetched is not None:
            activity = prefetched["activity"].get(conv_id)
        else:
            activity = db.query(FactLeadActivity).filter_by(conversation_id=conv_id).first()
        if not activity:
            activity = FactLeadActivity(
                lead=lead,
                conversation_id=conv_id,
                status_tag=status_tag,
                assigned_users=assigned_users,
                message_count=msg_count,
                is_contacted=is_contacted,
                contacted_at=contacted_at,
                contacted_dates=contacted_dates_str,
                tag_timeline=tag_timeline
            )
            db.add(activity)
            if prefetched is not None:
                prefetched["activity"][conv_id] = activity
        else:
            activity.status_tag = status_tag
            activity.assigned_users = assigned_users
            activity.message_count = msg_count
            activity.is_contacted = is_contacted
            activity.contacted_dates = contacted_dates_str
            if tag_timeline:
                activity.tag_timeline = tag_timeline
            if contacted_at:
                activity.contacted_at = contacted_at

        if commit:
            db.commit()
    except Exception as e:
        if commit:
            db.rollback()
        logger.error(f"Error upserting conversation {raw_data.get('id')}: {e}")

def run_etl_pipeline():
    t_start = time.perf_counter()
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
    daily_run_limit = int(os.getenv("DAILY_RUN_LIMIT", "200"))
    daily_days_back = int(os.getenv("DAILY_DAYS_BACK", "1"))

    db = SessionLocal()
    
    try:
        for p_info in pages_to_process:
            page_id = p_info["page_id"]
            page_token = p_info.get("token")
            preset_name = p_info.get("page_name")
            logger.info(f"Processing Page ID: {page_id} (Tên cấu hình: {preset_name or 'Auto'})")
            try:
                client = PancakeClient(api_token=page_token)
                
                # 1. Kiểm tra page đã có dữ liệu chưa (first run) — chỉ cần 1 dòng, không kéo payload
                t_page = time.perf_counter()
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
                    has_existing = db.query(RawConversation.id).filter(page_filter).first() is not None
                    if has_existing and not known_page_name:
                        for (pg_name,) in db.query(RawConversation.page_id).filter(page_filter).distinct().limit(20):
                            if pg_name and not is_page_id(pg_name):
                                known_page_name = str(pg_name).strip()
                                break
                except Exception as e:
                    logger.warning(f"Không thể kiểm tra dữ liệu cũ trong DB: {e}")
                    has_existing = False

                if not has_existing:
                    logger.info(f"🔔 FIRST RUN DETECTED! Kéo {first_run_limit} hội thoại lịch sử cho Page {page_id}...")
                    client.limit = first_run_limit 
                    days_back_param = None
                else:
                    logger.info(f"⚡ DAILY RUN DETECTED! Kéo hội thoại {daily_days_back} ngày gần nhất (tối đa {daily_run_limit}) cho Page {page_id}...")
                    client.limit = daily_run_limit
                    days_back_param = daily_days_back

                # Cache chỉ nạp cho đúng các hội thoại API vừa trả về (thay vì 1.500 payload gần nhất)
                stored_payloads: Dict[str, dict] = {}

                def load_cache(conv_ids: List[str]) -> Dict[str, dict]:
                    s = SessionLocal()
                    try:
                        for chunk in _chunks(conv_ids):
                            rows = s.query(
                                RawConversation.pancake_id,
                                func.json_extract_path_text(RawConversation.payload, 'updated_at').label('updated_at'),
                                func.json_extract_path_text(RawConversation.payload, 'message_count').label('message_count'),
                                func.json_extract_path_text(RawConversation.payload, 'tags').label('tags'),
                                func.json_extract_path_text(RawConversation.payload, 'assigned_users').label('assigned_users')
                            ).filter(
                                RawConversation.pancake_id.in_(chunk)
                            )
                            for r in rows:
                                pid = str(r.pancake_id)
                                stored_payloads[pid] = {
                                    'updated_at': r.updated_at,
                                    'message_count': r.message_count,
                                    'tags': r.tags,
                                    'assigned_users': r.assigned_users
                                }
                    finally:
                        s.close()
                    return stored_payloads

                # Đóng session trước khi cào dữ liệu qua API để không giữ idle connection trên Neon
                db.close()
                t_api = time.perf_counter()
                conversations = client.get_conversations(
                    page_id=page_id,
                    cache_loader=load_cache,
                    days_back=days_back_param
                )
                api_secs = time.perf_counter() - t_api

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

                # Bỏ qua hội thoại giống hệt bản đã lưu (không đổi gì) → không ghi DB
                import json
                def sort_tags(t):
                    if not t: return "[]"
                    if isinstance(t, str):
                        try:
                            t = json.loads(t)
                        except Exception:
                            return t
                    return json.dumps(sorted(t)) if isinstance(t, list) else str(t)

                changed = []
                for c in conversations:
                    if str(c.get('type', '')).upper() == 'COMMENT':
                        continue
                    cid = str(c.get('id'))
                    cached = stored_payloads.get(cid)
                    if not cached:
                        changed.append(c)
                        continue
                    
                    if str(cached.get('updated_at')) != str(c.get('updated_at')) \
                       or str(cached.get('message_count')) != str(c.get('message_count')) \
                       or sort_tags(cached.get('tags')) != sort_tags(c.get('tags')) \
                       or str(cached.get('assigned_users') or '') != str(c.get('assigned_users') or ''):
                        changed.append(c)
                total = len(changed)
                logger.info(
                    f"Page {page_id}: API trả {len(conversations)} hội thoại ({api_secs:.1f}s), "
                    f"thay đổi cần ghi DB: {total}, giữ nguyên: {len(conversations) - total}."
                )

                # 2. Mở session mới và ghi DB theo lô: mỗi lô nạp sẵn bản ghi bằng vài câu IN rồi commit 1 lần
                t_db = time.perf_counter()
                db = SessionLocal()
                try:
                    for start in range(0, total, DB_BATCH):
                        batch = changed[start:start + DB_BATCH]
                        prefetched = prefetch_records(db, batch)
                        for conv in batch:
                            upsert_lead_data(db, conv, canonical_page_name, commit=False, prefetched=prefetched)
                        db.commit()
                        logger.info(f"Đã lưu vào DB: {min(start + DB_BATCH, total)}/{total} hội thoại...")
                    logger.info(
                        f"Hoàn tất Page {page_id}: ghi {total} hội thoại trong {time.perf_counter() - t_db:.1f}s, "
                        f"tổng {time.perf_counter() - t_page:.1f}s."
                    )
                except Exception as e:
                    db.rollback()
                    logger.error(f"Lỗi khi lưu dữ liệu theo batch cho Page {page_id}: {e}")
            except Exception as page_err:
                logger.error(f"Lỗi khi cào dữ liệu cho Page {page_id}: {page_err}", exc_info=True)
                # Đảm bảo session db mở lại cho lượt loop tiếp theo
                db = SessionLocal()
    finally:
        db.close()
        
    logger.info(f"ETL Pipeline hoàn tất trong {time.perf_counter() - t_start:.1f}s.")

if __name__ == "__main__":
    # Test chạy trực tiếp
    run_etl_pipeline()
