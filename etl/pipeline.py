import os
import time
import logging
from typing import Optional, Dict, Any, List, Iterable
from sqlalchemy import or_, func
from sqlalchemy.orm import Session, defer
from database.db import SessionLocal
from database.models import RawConversation, DimLead, FactLeadActivity, Comment, Post
from database.schema import ensure_schema
from etl.pancake_client import PancakeClient
from etl.utils import parse_pancake_date, resolve_phone, normalize_phone, is_page_id, resolve_canonical_page_name, is_source_page, clean_html, extract_phone_number, build_post_url
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
    Dùng defer() để KHÔNG tải cột JSON nặng (payload, tag_timeline) từ Neon về runner GitHub — tiết kiệm >95% băng thông egress."""
    conv_ids = list({str(c.get('id')) for c in conversations if c.get('id')})
    cust_ids = list({str(c.get('customer_id')) for c in conversations if c.get('customer_id')})
    maps: Dict[str, Dict[str, Any]] = {"raw": {}, "lead": {}, "activity": {}}
    for chunk in _chunks(conv_ids):
        for r in db.query(RawConversation).options(defer(RawConversation.payload)).filter(RawConversation.pancake_id.in_(chunk)):
            maps["raw"][r.pancake_id] = r
        for a in db.query(FactLeadActivity).options(defer(FactLeadActivity.tag_timeline)).filter(FactLeadActivity.conversation_id.in_(chunk)):
            maps["activity"][a.conversation_id] = a
    for chunk in _chunks(cust_ids):
        for lead in db.query(DimLead).filter(DimLead.customer_id.in_(chunk)):
            maps["lead"][lead.customer_id] = lead
    return maps


def prefetch_comments(db: Session, comments: List[dict]) -> Dict[str, Comment]:
    """Nạp sẵn Comment của cả lô bằng câu IN (...). Dùng defer(Comment.payload) để tiết kiệm 95% băng thông Neon."""
    cids = list({str(c.get('comment_id') or c.get('id')) for c in comments if c.get('comment_id') or c.get('id')})
    res: Dict[str, Comment] = {}
    for chunk in _chunks(cids):
        for r in db.query(Comment).options(defer(Comment.payload)).filter(Comment.comment_id.in_(chunk)):
            res[r.comment_id] = r
    return res


def prefetch_posts(db: Session, posts: List[dict]) -> Dict[str, Post]:
    """Nạp sẵn Post của cả lô bằng câu IN (...). Dùng defer(Post.payload) để tiết kiệm băng thông Neon."""
    pids = list({str(p.get('post_id') or p.get('id')) for p in posts if p.get('post_id') or p.get('id')})
    res: Dict[str, Post] = {}
    for chunk in _chunks(pids):
        for r in db.query(Post).options(defer(Post.payload)).filter(Post.post_id.in_(chunk)):
            res[r.post_id] = r
    return res


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
        
        # Bỏ qua Comment và Group chat Zalo (Chỉ lấy Message khách hàng cá nhân)
        conv_type = str(raw_data.get('type', '')).upper()
        if conv_type == 'COMMENT' or conv_id.startswith('pzl_g_'):
            return
            
        if not conv_id or not customer_id:
            return

        if prefetched is not None:
            raw_record = prefetched["raw"].get(conv_id)
        else:
            raw_record = db.query(RawConversation).options(defer(RawConversation.payload)).filter_by(pancake_id=conv_id).first()
        if not raw_record:
            raw_record = RawConversation(pancake_id=conv_id, page_id=page_id, payload=raw_data)
            db.add(raw_record)
            if prefetched is not None:
                prefetched["raw"][conv_id] = raw_record
        else:
            # Chỉ đọc raw_record.payload từ DB khi raw_data bị rỗng messages (hiếm gặp), tránh lazy-load tốn băng thông Neon
            if not raw_data.get('messages'):
                old_payload = raw_record.payload or {}
                if old_payload.get('messages'):
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
                # Lead đã có từ trước nay mới có số mà không thấy tin chứa số hay tag -> coi như vừa thu được
                phone_at = phone_at or parse_pancake_date(raw_data.get('updated_at'))
            # Giữ thời điểm SỚM NHẤT thu được số (từ tin nhắn hoặc tag "Đã add")
            if phone_at and (not lead.phone_at or phone_at < lead.phone_at):
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

def upsert_comment_data(db: Session, comment_data: dict, page_name: str, commit: bool = True, prefetched: dict = None):
    """Lưu trữ và cập nhật dữ liệu Comment vào bảng comments."""
    try:
        cid = str(comment_data.get('comment_id') or comment_data.get('id') or '')
        if not cid:
            return

        page_id = str(comment_data.get('page_id') or '')
        post_id = str(comment_data.get('post_id') or '') or None
        post_url = str(comment_data.get('post_url') or '') or None
        cust_id = str(comment_data.get('customer_id') or '') or None
        cust_name = comment_data.get('customer_name')
        phone = comment_data.get('phone_number')
        clean_msg = comment_data.get('message')
        raw_msg = comment_data.get('raw_message')
        msg_count = comment_data.get('message_count', 1)
        tags_str = comment_data.get('tags')
        assigned_str = comment_data.get('assigned_users')
        inserted_at = parse_pancake_date(comment_data.get('inserted_at'))
        updated_at = parse_pancake_date(comment_data.get('updated_at'))
        payload = comment_data.get('payload')

        if prefetched is not None and "comment" in prefetched:
            rec = prefetched["comment"].get(cid)
        else:
            rec = db.query(Comment).filter_by(comment_id=cid).first()

        if not rec:
            rec = Comment(
                comment_id=cid,
                page_id=page_id,
                page_name=page_name,
                post_id=post_id,
                post_url=post_url,
                customer_id=cust_id,
                customer_name=cust_name,
                phone_number=phone,
                message=clean_msg,
                raw_message=raw_msg,
                message_count=msg_count,
                tags=tags_str,
                assigned_users=assigned_str,
                inserted_at=inserted_at,
                updated_at=updated_at,
                payload=payload
            )
            db.add(rec)
            if prefetched is not None and "comment" in prefetched:
                prefetched["comment"][cid] = rec
        else:
            rec.page_id = page_id
            rec.page_name = page_name
            if post_id:
                rec.post_id = post_id
            if post_url:
                rec.post_url = post_url
            if cust_id:
                rec.customer_id = cust_id
            if cust_name:
                rec.customer_name = cust_name
            if phone:
                rec.phone_number = phone
            rec.message = clean_msg
            rec.raw_message = raw_msg
            rec.message_count = msg_count
            rec.tags = tags_str
            rec.assigned_users = assigned_str
            if inserted_at:
                rec.inserted_at = inserted_at
            if updated_at:
                rec.updated_at = updated_at
            rec.payload = payload

        if commit:
            db.commit()
    except Exception as e:
        if commit:
            db.rollback()
        logger.error(f"Lỗi khi upsert comment {comment_data.get('comment_id')}: {e}")


def upsert_post_data(db: Session, post_data: dict, page_name: str, commit: bool = True, prefetched: dict = None):
    """Lưu trữ và cập nhật dữ liệu Bài viết (Post) vào bảng posts."""
    try:
        pid = str(post_data.get('post_id') or post_data.get('id') or '')
        if not pid:
            return

        page_id = str(post_data.get('page_id') or '')
        is_tiktok = page_id.startswith("tt_") or "tiktok" in resolve_canonical_page_name(page_id).lower() or pid.startswith("tt_")
        platform = post_data.get("platform") or ("tiktok" if is_tiktok else "facebook")
        p_type = post_data.get('type') or ("video" if is_tiktok else "post")
        message = post_data.get('message')
        post_url = build_post_url(pid, page_id, post_data.get('post_url'))
        creator_id = post_data.get('creator_id')
        creator_name = post_data.get('creator_name')
        comment_count = int(post_data.get('comment_count') or 0)
        like_count = int(post_data.get('like_count') or 0)
        love_count = int(post_data.get('love_count') or 0)
        haha_count = int(post_data.get('haha_count') or 0)
        wow_count = int(post_data.get('wow_count') or 0)
        sad_count = int(post_data.get('sad_count') or 0)
        angry_count = int(post_data.get('angry_count') or 0)
        care_count = int(post_data.get('care_count') or 0)
        reactions_total = int(post_data.get('reactions_total') or 0)
        share_count = int(post_data.get('share_count') or 0)
        view_count = int(post_data.get('view_count') or 0)
        phone_number_count = int(post_data.get('phone_number_count') or 0)
        inserted_at = parse_pancake_date(post_data.get('inserted_at'))
        updated_at = parse_pancake_date(post_data.get('updated_at'))
        payload = post_data.get('payload')

        if prefetched is not None and "post" in prefetched:
            rec = prefetched["post"].get(pid)
        else:
            rec = db.query(Post).options(defer(Post.payload)).filter_by(post_id=pid).first()

        if not rec:
            rec = Post(
                post_id=pid,
                page_id=page_id,
                page_name=page_name,
                platform=platform,
                type=p_type,
                message=message,
                post_url=post_url,
                creator_id=creator_id,
                creator_name=creator_name,
                comment_count=comment_count,
                like_count=like_count,
                love_count=love_count,
                haha_count=haha_count,
                wow_count=wow_count,
                sad_count=sad_count,
                angry_count=angry_count,
                care_count=care_count,
                reactions_total=reactions_total,
                share_count=share_count,
                view_count=view_count,
                phone_number_count=phone_number_count,
                inserted_at=inserted_at,
                updated_at=updated_at,
                payload=payload
            )
            db.add(rec)
            if prefetched is not None and "post" in prefetched:
                prefetched["post"][pid] = rec
        else:
            # Chỉ cập nhật khi có sự thay đổi thực sự về số liệu hoặc thời gian cập nhật
            has_changed = (
                rec.updated_at != updated_at
                or rec.comment_count != comment_count
                or rec.reactions_total != reactions_total
                or rec.share_count != share_count
                or rec.view_count != view_count
                or rec.phone_number_count != phone_number_count
            )
            if has_changed:
                rec.page_id = page_id
                rec.page_name = page_name
                rec.platform = platform
                rec.type = p_type
                if message:
                    rec.message = message
                if post_url:
                    rec.post_url = post_url
                if creator_id:
                    rec.creator_id = creator_id
                if creator_name:
                    rec.creator_name = creator_name
                if comment_count:
                    rec.comment_count = comment_count
                if like_count:
                    rec.like_count = like_count
                rec.love_count = love_count
                rec.haha_count = haha_count
                rec.wow_count = wow_count
                rec.sad_count = sad_count
                rec.angry_count = angry_count
                rec.care_count = care_count
                if reactions_total:
                    rec.reactions_total = reactions_total
                if share_count:
                    rec.share_count = share_count
                if view_count:
                    rec.view_count = view_count
                rec.phone_number_count = phone_number_count
                if inserted_at:
                    rec.inserted_at = inserted_at
                if updated_at:
                    rec.updated_at = updated_at
                if payload:
                    rec.payload = payload

        if commit:
            db.commit()
    except Exception as e:
        if commit:
            db.rollback()
        logger.error(f"Lỗi khi upsert post {post_data.get('post_id')}: {e}")


def load_pancake_pages_config() -> List[Dict[str, Any]]:
    """Nạp danh sách Fanpage và token từ các biến môi trường PANCAKE_PAGES_JSON hoặc PAGE_IDS."""
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

    # 2. Bổ sung các page từ PAGE_IDS nếu chưa có trong danh sách (hoặc nạp toàn bộ nếu chưa có JSON)
    page_ids_env = os.getenv("PAGE_IDS", "")
    page_ids = [p.strip() for p in page_ids_env.split(",") if p.strip()]
    
    if page_ids:
        existing_pids = {str(p.get("page_id", "")).strip() for p in pages_to_process}
        existing_pids |= {re.sub(r"^(pzl_|tt_|fb_)", "", pid) for pid in existing_pids}

        single_token = os.getenv("PANCAKE_API_TOKEN", "").strip()
        tokens_env = os.getenv("PANCAKE_API_TOKENS", "").strip()
        tokens = [t.strip() for t in tokens_env.split(",") if t.strip()] if (tokens_env and not tokens_env.startswith(("{", "["))) else []
        default_token = single_token or (tokens[0] if tokens else None)
        if not default_token and pages_to_process:
            for p in pages_to_process:
                if p.get("token"):
                    default_token = p.get("token")
                    break

        for i, page_id in enumerate(page_ids):
            clean_pid = re.sub(r"^(pzl_|tt_|fb_)", "", page_id)
            if page_id not in existing_pids and clean_pid not in existing_pids:
                token = tokens[i] if i < len(tokens) and tokens[i] else default_token
                pages_to_process.append({
                    "page_id": page_id,
                    "page_name": None,
                    "token": token
                })
                logger.info(f"Bổ sung Page ID '{page_id}' từ PAGE_IDS vào danh sách cào.")

    return pages_to_process


def run_etl_pipeline():
    t_start = time.perf_counter()
    logger.info("Starting Fast ETL Pipeline...")
    # ETL có thể chạy trước khi Backend kịp thêm cột mới → tự đồng bộ schema
    ensure_schema()

    pages_to_process = load_pancake_pages_config()
    if not pages_to_process:
        logger.warning("No pages found in environment variables (PANCAKE_PAGES_JSON or PAGE_IDS).")
        return

    first_run_limit = int(os.getenv("FIRST_RUN_LIMIT", "2000"))
    daily_run_limit = int(os.getenv("DAILY_RUN_LIMIT", "200"))
    daily_days_back = int(os.getenv("DAILY_DAYS_BACK", "1"))
    comment_first_run_limit = int(os.getenv("COMMENT_FIRST_RUN_LIMIT", str(first_run_limit)))
    comment_daily_run_limit = int(os.getenv("COMMENT_DAILY_RUN_LIMIT", str(daily_run_limit)))
    comment_daily_days_back = int(os.getenv("COMMENT_DAILY_DAYS_BACK", str(daily_days_back)))

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

                # Tên chuẩn của riêng Page này (ưu tiên tên cấu hình chuẩn hệ thống -> tên cấu hình preset -> tên API trả về -> tên DB)
                canonical_page_name = (
                    resolve_canonical_page_name(page_id, fallback=None)
                    or known_page_name
                    or preset_name
                    or getattr(client, 'page_name', None)
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
                    cid = str(c.get('id', ''))
                    if str(c.get('type', '')).upper() == 'COMMENT' or cid.startswith('pzl_g_'):
                        continue
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

                # 3. Lấy Comment cho các kênh nguồn (Facebook Fanpage, TikTok...) và lưu vào bảng comments
                if is_source_page(page_id):
                    logger.info(f"\n--- [COMMENTS] Bắt đầu cào Comment cho Page nguồn: {canonical_page_name} ({page_id}) ---")

                    has_existing_comments = False
                    try:
                        has_existing_comments = db.query(Comment.id).filter(
                            or_(
                                Comment.page_id == page_id,
                                Comment.page_id == clean_num,
                                Comment.page_id == canonical_page_name
                            )
                        ).first() is not None
                    except Exception as e_chk:
                        logger.warning(f"[COMMENTS] Không thể kiểm tra dữ liệu comment cũ trong DB: {e_chk}")
                        has_existing_comments = False

                    if not has_existing_comments:
                        logger.info(f"[COMMENTS] 🔔 FIRST RUN DETECTED! Kéo {comment_first_run_limit} comments lịch sử cho Page {page_id}...")
                        comment_limit = comment_first_run_limit
                        comment_days_back = None
                    else:
                        logger.info(f"[COMMENTS] ⚡ DAILY RUN DETECTED! Kéo comment {comment_daily_days_back} ngày gần nhất (tối đa {comment_daily_run_limit}) cho Page {page_id}...")
                        comment_limit = comment_daily_run_limit
                        comment_days_back = comment_daily_days_back

                    # Đóng session trước khi cào qua API để tránh giữ idle connection trên Neon
                    db.close()

                    def load_comment_cache(cids):
                        s = SessionLocal()
                        try:
                            rows = s.query(Comment.comment_id, Comment.updated_at, Comment.message_count).filter(Comment.comment_id.in_(cids)).all()
                            return {r.comment_id: {'updated_at': r.updated_at, 'message_count': r.message_count} for r in rows}
                        finally:
                            s.close()

                    try:
                        comments_data = client.get_comments(
                            page_id=page_id,
                            cache_loader=load_comment_cache,
                            days_back=comment_days_back,
                            limit=comment_limit
                        )
                        db = SessionLocal()
                        if comments_data:
                            changed_comments = [c for c in comments_data if not c.get("is_cached")]
                            logger.info(
                                f"[COMMENTS] Page {page_id}: Nhận được {len(comments_data)} comments "
                                f"(mới/cập nhật: {len(changed_comments)}, giữ nguyên: {len(comments_data) - len(changed_comments)})."
                            )
                            if changed_comments:
                                for start in range(0, len(changed_comments), DB_BATCH):
                                    batch = changed_comments[start:start + DB_BATCH]
                                    prefetched_comments = {"comment": prefetch_comments(db, batch)}
                                    for c_item in batch:
                                        upsert_comment_data(db, c_item, canonical_page_name, commit=False, prefetched=prefetched_comments)
                                    db.commit()
                                logger.info(f"[COMMENTS] ✅ Đã lưu thành công {len(changed_comments)} comments thay đổi cho Page {page_id} vào bảng comments.")

                                # Tự động trích xuất các bài viết/video TikTok từ comment threads mới vào bảng posts
                                is_tiktok_page = str(page_id).startswith("tt_") or "tiktok" in canonical_page_name.lower()
                                unique_posts = {}
                                for c_item in changed_comments:
                                    p_id = c_item.get("post_id") or ((c_item.get("payload") or {}).get("post_id") if isinstance(c_item.get("payload"), dict) else None)
                                    if p_id and str(p_id) not in unique_posts:
                                        p_obj = (c_item.get("payload") or {}).get("post") if isinstance(c_item.get("payload"), dict) else {}
                                        p_url = c_item.get("post_url") or (p_obj.get("permalink_url") if isinstance(p_obj, dict) else None) or (p_obj.get("url") if isinstance(p_obj, dict) else None)
                                        p_msg = (p_obj.get("message") or p_obj.get("title")) if isinstance(p_obj, dict) else None
                                        p_ins = (p_obj.get("inserted_at") if isinstance(p_obj, dict) else None) or c_item.get("inserted_at")
                                        unique_posts[str(p_id)] = {
                                            "post_id": str(p_id),
                                            "page_id": str(page_id),
                                            "platform": "tiktok" if is_tiktok_page else "facebook",
                                            "type": "video" if is_tiktok_page else "post",
                                            "message": p_msg,
                                            "post_url": build_post_url(str(p_id), page_id, p_url),
                                            "inserted_at": p_ins,
                                            "payload": p_obj if p_obj else {"post_id": p_id, "from_comment": True}
                                        }
                                if unique_posts:
                                    prefetched_p = {"post": prefetch_posts(db, list(unique_posts.values()))}
                                    for p_data in unique_posts.values():
                                        upsert_post_data(db, p_data, canonical_page_name, commit=False, prefetched=prefetched_p)
                                    db.commit()
                                    logger.info(f"[POSTS] Đã đồng bộ {len(unique_posts)} bài viết/video từ comments cho Page {page_id}.")

                            # 4. Tự động phản hồi bình luận (Auto-Reply Comments) theo kịch bản
                            enable_comment_reply = os.getenv("ENABLE_COMMENT_REPLY", "true").strip().lower() not in ("false", "0", "off", "no")
                            if enable_comment_reply and changed_comments:
                                try:
                                    from etl.auto_reply_bot import process_page_comment_replies
                                    reply_dry_run = os.getenv("COMMENT_REPLY_DRY_RUN", "false").strip().lower() in ("true", "1", "yes")
                                    reply_days_back = int(os.getenv("COMMENT_REPLY_DAYS_BACK", "1"))
                                    max_comment_replies = int(os.getenv("MAX_COMMENT_REPLIES_PER_RUN", "10"))

                                    process_page_comment_replies(
                                        client=client,
                                        comments_data=changed_comments,
                                        page_id=page_id,
                                        db=db,
                                        dry_run=reply_dry_run,
                                        max_replies=max_comment_replies,
                                        days_back=reply_days_back
                                    )
                                except Exception as reply_err:
                                    logger.error(f"[COMMENTS] ❌ Lỗi khi tự động phản hồi comment cho Page {page_id}: {reply_err}")
                        else:
                            logger.info(f"[COMMENTS] Page {page_id}: Không có comment mới nào.")
                    except Exception as c_err:
                        if 'db' in locals() and db:
                            try:
                                db.rollback()
                            except Exception:
                                pass
                        db = SessionLocal()
                        logger.error(f"[COMMENTS] ❌ Lỗi khi cào/lưu comments cho Page {page_id}: {c_err}")

                    # 5. Cào và đồng bộ danh sách Bài viết (Posts) vào bảng posts
                    enable_posts_sync = os.getenv("ENABLE_POSTS_SYNC", "true").strip().lower() not in ("false", "0", "off", "no")
                    if enable_posts_sync:
                        posts_days_back = int(os.getenv("POSTS_DAYS_BACK", "7"))
                        posts_limit = int(os.getenv("POSTS_LIMIT", "50"))
                        try:
                            posts_data = client.get_posts(
                                page_id=page_id,
                                days_back=posts_days_back,
                                limit=posts_limit
                            )
                            if posts_data:
                                logger.info(f"[POSTS] Page {page_id}: Nhận được {len(posts_data)} posts. Đang lưu vào DB...")
                                for start in range(0, len(posts_data), DB_BATCH):
                                    batch = posts_data[start:start + DB_BATCH]
                                    prefetched_posts = {"post": prefetch_posts(db, batch)}
                                    for p_item in batch:
                                        upsert_post_data(db, p_item, canonical_page_name, commit=False, prefetched=prefetched_posts)
                                    db.commit()
                                logger.info(f"[POSTS] ✅ Đã lưu thành công {len(posts_data)} bài viết cho Page {page_id} vào bảng posts.")
                            else:
                                logger.info(f"[POSTS] Page {page_id}: Không có bài viết nào.")
                        except Exception as p_err:
                            if 'db' in locals() and db:
                                try:
                                    db.rollback()
                                except Exception:
                                    pass
                            db = SessionLocal()
                            logger.error(f"[POSTS] ❌ Lỗi khi cào/lưu bài viết cho Page {page_id}: {p_err}")

            except Exception as page_err:
                logger.error(f"Lỗi khi cào dữ liệu cho Page {page_id}: {page_err}", exc_info=True)
                # Đảm bảo session db mở lại cho lượt loop tiếp theo
                db = SessionLocal()
    finally:
        db.close()

    # Tự động đồng bộ tag "Đã là học viên" và nhân viên chăm sóc từ DimLead sang DealWin
    try:
        from database.deal_sync import sync_all_deals_with_dim_leads
        db_sync = SessionLocal()
        total_deals, students, care_updated = sync_all_deals_with_dim_leads(db_sync)
        logger.info(f"[DEAL_WINS] ✅ Đã đồng bộ Deal Win: {total_deals} deal, {students} học viên có tag 'Đã là học viên', {care_updated} lượt cập nhật care_by từ Pancake.")
        db_sync.close()
    except Exception as sync_err:
        logger.warning(f"[DEAL_WINS] ⚠️ Không thể đồng bộ Deal Win tự động: {sync_err}")

    # Xóa cache trên Render API để dashboard nhận dữ liệu mới ngay
    try:
        import requests
        secret = os.getenv("ADMIN_SECRET_KEY") or os.getenv("WEBHOOK_SECRET")
        headers = {"X-Admin-Secret": secret} if secret else {}
        requests.post("https://pancake-lead-api.onrender.com/api/admin/clear-cache", headers=headers, timeout=5)
    except Exception:
        pass
        
    logger.info(f"ETL Pipeline hoàn tất trong {time.perf_counter() - t_start:.1f}s.")

if __name__ == "__main__":
    # Test chạy trực tiếp
    run_etl_pipeline()
