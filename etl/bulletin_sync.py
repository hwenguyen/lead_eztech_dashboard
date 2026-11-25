"""
Đồng bộ bản tin từ nhóm Zalo 'EzTech - Data & Finance Service' qua Pancake API (Page Eztech Consultant).
- Chỉ lưu các bản tin của 3 sếp: Ann, TRẦN HÀ TUẤN ANH, Hiền Minhh vào bảng bulletin_posts.
- Gom chuỗi tin nhắn liên tiếp của cùng 1 sếp trong vòng 3 phút thành 1 bản tin liền mạch (A5).
- Dừng sớm theo last_seen_message_ids & prefetch IN(...) để tối ưu triệt để Neon Egress và quota Pancake.
- Hoàn toàn tách biệt với hệ thống Lead (dim_leads / fact_lead_activities).
"""

import json
import logging
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc
from sqlalchemy.orm import Session, load_only

from database.db import SessionLocal
from database.models import AppConfig, BulletinPost, get_vn_now
from etl.pancake_client import PancakeClient
from etl.pipeline import get_token_for_page
from etl.utils import clean_html, normalize_phone, parse_pancake_date

logger = logging.getLogger("BulletinSync")

BULLETIN_CONFIG_KEY = "BULLETIN_SOURCE_CONFIG"
EZTECH_CONSULTANT_PAGE_ID = "pzl_764881945463506349"
DEFAULT_GROUP_NAME = "EzTech - Data & Finance Service"
DEFAULT_MERGE_WINDOW_SEC = 180  # Gom tin liên tiếp của cùng 1 sếp trong 3 phút
MAX_LAST_SEEN_IDS = 120

DEFAULT_BOSS_RULES: Dict[str, Dict[str, Any]] = {
    "ann": {
        "display_name": "Ann",
        "names": ["Ann"],
        "sender_ids": [],
    },
    "tuan_anh": {
        "display_name": "Trần Hà Tuấn Anh",
        "names": ["TRẦN HÀ TUẤN ANH", "Trần Hà Tuấn Anh"],
        "sender_ids": [],
    },
    "hien_minh": {
        "display_name": "Lý Hiền Minh",
        "names": ["Hiền Minhh", "Lý Hiền Minh", "Hiền Minh"],
        "sender_ids": [],
    },
}


def _norm_nfc(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(text)).strip().lower())


def _strip_accents(text: Optional[str]) -> str:
    if not text:
        return ""
    s = _norm_nfc(text).replace("đ", "d")
    s = "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def get_bulletin_source_config(db: Session) -> Dict[str, Any]:
    """Đọc cấu hình nguồn bản tin từ app_configs (có fallback mặc định an toàn)."""
    default_cfg: Dict[str, Any] = {
        "group_name": DEFAULT_GROUP_NAME,
        "group_conversation_id": "",
        "fetch_page_id": EZTECH_CONSULTANT_PAGE_ID,
        "dashboard_url": "",
        "active_weekdays": [0, 1, 2, 3, 4, 5],  # T2 (0) -> T7 (5); 6 = Chủ nhật
        "group_merge_window_sec": DEFAULT_MERGE_WINDOW_SEC,
        "last_seen_message_ids": [],
        "boss_rules": json.loads(json.dumps(DEFAULT_BOSS_RULES)),
    }
    row = db.query(AppConfig).filter(AppConfig.config_key == BULLETIN_CONFIG_KEY).first()
    if not row or not row.config_value:
        return default_cfg
    try:
        loaded = json.loads(row.config_value)
        if not isinstance(loaded, dict):
            return default_cfg
        merged = {**default_cfg, **loaded}
        if not isinstance(merged.get("boss_rules"), dict) or not merged["boss_rules"]:
            merged["boss_rules"] = json.loads(json.dumps(DEFAULT_BOSS_RULES))
        if not isinstance(merged.get("active_weekdays"), list):
            merged["active_weekdays"] = [0, 1, 2, 3, 4, 5]
        if not isinstance(merged.get("last_seen_message_ids"), list):
            merged["last_seen_message_ids"] = []
        return merged
    except Exception as e:
        logger.warning(f"Không parse được {BULLETIN_CONFIG_KEY}: {e}")
        return default_cfg


def save_bulletin_source_config(db: Session, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Lưu cấu hình nguồn bản tin vào app_configs."""
    serialized = json.dumps(cfg, ensure_ascii=False)
    row = db.query(AppConfig).filter(AppConfig.config_key == BULLETIN_CONFIG_KEY).first()
    if not row:
        row = AppConfig(config_key=BULLETIN_CONFIG_KEY, config_value=serialized, updated_at=get_vn_now())
        db.add(row)
    else:
        row.config_value = serialized
        row.updated_at = get_vn_now()
    db.commit()
    return cfg


def extract_conversation_name(conv: Dict[str, Any]) -> str:
    """Trích xuất tên hiển thị của cuộc hội thoại / nhóm Zalo từ Pancake conversation object."""
    for key in ("name", "title", "group_name", "conversation_name"):
        val = conv.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    customers = conv.get("customers") or []
    if isinstance(customers, list) and customers:
        first_c = customers[0]
        if isinstance(first_c, dict) and first_c.get("name"):
            return str(first_c["name"]).strip()
    page_cust = conv.get("page_customer")
    if isinstance(page_cust, dict) and page_cust.get("name"):
        return str(page_cust["name"]).strip()
    return ""


def _extract_sender_candidates(msg: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Lấy (sender_id, danh sách tên ứng viên của người gửi tin nhắn)."""
    m_from = msg.get("from") or {}
    if not isinstance(m_from, dict):
        m_from = {}
    sender_id = str(m_from.get("id") or m_from.get("uid") or m_from.get("admin_id") or "").strip()

    names: List[str] = []
    for cand in (
        m_from.get("name"),
        m_from.get("admin_name"),
        m_from.get("username"),
        msg.get("sender_name"),
    ):
        if isinstance(cand, str) and cand.strip():
            cleaned = cand.strip()
            if cleaned not in names:
                names.append(cleaned)
    return sender_id, names


def match_boss_sender(
    msg: Dict[str, Any],
    boss_rules: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[Tuple[str, str, str]]:
    """
    Kiểm tra tin nhắn có phải do 1 trong 3 sếp (Ann, TRẦN HÀ TUẤN ANH, Hiền Minhh) gửi hay không.
    Trả về (boss_key, boss_display_name, matched_sender_name) hoặc None.
    """
    rules = boss_rules or DEFAULT_BOSS_RULES
    sender_id, name_candidates = _extract_sender_candidates(msg)
    if not sender_id and not name_candidates:
        return None

    # 1. Ưu tiên khớp chính xác sender_id nếu đã cấu hình
    if sender_id:
        for boss_key, rule in rules.items():
            ids = {str(x).strip() for x in (rule.get("sender_ids") or []) if str(x).strip()}
            if sender_id in ids:
                return boss_key, rule.get("display_name") or boss_key, (name_candidates[0] if name_candidates else sender_id)

    # 2. Khớp theo tên hiển thị Zalo (NFC exact lower, sau đó không dấu exact cho tên đủ rõ ràng)
    for cand in name_candidates:
        cand_nfc = _norm_nfc(cand)
        cand_ascii = _strip_accents(cand)
        for boss_key, rule in rules.items():
            configured_names = [str(n).strip() for n in (rule.get("names") or []) if str(n).strip()]
            for target in configured_names:
                target_nfc = _norm_nfc(target)
                target_ascii = _strip_accents(target)
                if cand_nfc == target_nfc:
                    return boss_key, rule.get("display_name") or cand, cand
                if (len(target_ascii.split()) >= 2 or len(target_ascii) >= 6) and cand_ascii == target_ascii:
                    return boss_key, rule.get("display_name") or cand, cand

    return None


def _extract_attachments_and_text(msg: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """Làm sạch nội dung text và trích xuất danh sách file/ảnh/link đính kèm từ tin nhắn Pancake."""
    raw_text = msg.get("message") or msg.get("original_message") or ""
    text = clean_html(str(raw_text)).strip() if raw_text else ""

    attachments_out: List[Dict[str, Any]] = []
    raw_atts = msg.get("attachments") or []
    if isinstance(raw_atts, list):
        for att in raw_atts:
            if not isinstance(att, dict):
                continue
            att_type = str(att.get("type") or "file").strip().lower()
            if att_type == "system_message" and not text:
                sys_body = clean_html(str(att.get("message") or att.get("description") or "")).strip()
                if sys_body:
                    text = sys_body
                continue

            img_obj = att.get("image") if isinstance(att.get("image"), dict) else {}
            url = (
                att.get("url")
                or att.get("file_url")
                or img_obj.get("url")
                or att.get("link")
                or att.get("preview_url")
            )
            title = att.get("title") or att.get("name") or att.get("filename") or ""
            desc = att.get("description") or ""
            link = att.get("link") or url

            if url or link or title:
                attachments_out.append({
                    "type": att_type,
                    "url": str(url).strip() if url else None,
                    "link": str(link).strip() if link else None,
                    "title": str(title).strip() if title else None,
                    "description": str(desc).strip() if desc else None,
                })
            if not text and desc:
                text = clean_html(str(desc)).strip()

    if not text and attachments_out:
        first_att = attachments_out[0]
        label = first_att.get("title") or first_att.get("link") or first_att.get("type") or "tệp đính kèm"
        text = f"[Đính kèm: {label}]"

    return text, attachments_out


def _build_post_title(content: str) -> str:
    """Tạo tiêu đề ngắn gọn từ dòng đầu tiên có nội dung của bản tin."""
    for line in (content or "").splitlines():
        clean_line = re.sub(r"\s+", " ", line).strip()
        if clean_line:
            return clean_line[:117] + "..." if len(clean_line) > 120 else clean_line
    return "Thông báo mới"


def discover_group_conversation(
    client: PancakeClient,
    page_id: str,
    group_name: str,
    max_convs: int = 100,
) -> Optional[Dict[str, Any]]:
    """Tìm hội thoại nhóm Zalo (pzl_g_...) khớp với tên nhóm 'EzTech - Data & Finance Service'."""
    target_nfc = _norm_nfc(group_name)
    target_ascii = _strip_accents(group_name)

    convs = client.list_page_conversations(
        page_id=page_id,
        max_convs=max_convs,
        include_groups=True,
        only_groups=True,
        max_api_pages=15,
    )
    exact_match = None
    partial_match = None

    for conv in convs:
        cname = extract_conversation_name(conv)
        if not cname:
            continue
        cn_nfc = _norm_nfc(cname)
        cn_ascii = _strip_accents(cname)
        if cn_nfc == target_nfc or cn_ascii == target_ascii:
            exact_match = conv
            break
        if target_ascii and target_ascii in cn_ascii and not partial_match:
            partial_match = conv

    return exact_match or partial_match


def sync_bulletin_from_group(
    db: Optional[Session] = None,
    max_pages: int = 10,
    force_rediscover: bool = False,
    force_full: bool = False,
) -> Dict[str, Any]:
    """
    Đồng bộ bản tin từ nhóm Zalo 'EzTech - Data & Finance Service' (dùng Page Eztech Consultant).
    - Chỉ giữ lại tin nhắn của 3 sếp: Ann, TRẦN HÀ TUẤN ANH, Hiền Minhh.
    - Dừng sớm theo last_seen_message_ids (cả tin nhân viên) và prefetch theo lô IN(...) để tiết kiệm Neon Egress.
    - Gom chuỗi tin liên tiếp của cùng 1 sếp trong vòng group_merge_window_sec (mặc định 180s).
    """
    own_session = db is None
    session = db or SessionLocal()
    try:
        cfg = get_bulletin_source_config(session)
        page_id = str(cfg.get("fetch_page_id") or EZTECH_CONSULTANT_PAGE_ID).strip()
        group_name = str(cfg.get("group_name") or DEFAULT_GROUP_NAME).strip()
        group_conv_id = str(cfg.get("group_conversation_id") or "").strip()
        boss_rules = cfg.get("boss_rules") or DEFAULT_BOSS_RULES
        merge_window_sec = int(cfg.get("group_merge_window_sec") or DEFAULT_MERGE_WINDOW_SEC)
        last_seen_list: List[str] = [str(x) for x in (cfg.get("last_seen_message_ids") or []) if x]
        last_seen_set = set() if force_full else set(last_seen_list)

        page_token = get_token_for_page(page_id, group_conv_id or None)
        client = PancakeClient(api_token=page_token)

        if not group_conv_id or force_rediscover:
            found_conv = discover_group_conversation(client, page_id=page_id, group_name=group_name)
            if not found_conv:
                return {
                    "success": False,
                    "fetched": 0,
                    "inserted": 0,
                    "merged": 0,
                    "skipped_non_boss": 0,
                    "group_conversation_id": group_conv_id or None,
                    "message": f"Không tìm thấy nhóm Zalo '{group_name}' trên Page '{page_id}'. Kiểm tra lại Token Pancake hoặc tên nhóm.",
                }
            group_conv_id = str(found_conv.get("id") or "").strip()
            resolved_name = extract_conversation_name(found_conv) or group_name
            cfg["group_conversation_id"] = group_conv_id
            cfg["group_name"] = resolved_name
            save_bulletin_source_config(session, cfg)
            group_name = resolved_name

        fetched_total = 0
        skipped_non_boss = 0
        skipped_empty = 0
        current_count = 0
        seen_batch_ids = set()
        newly_seen_ordered: List[str] = []
        raw_boss_candidates: List[Dict[str, Any]] = []

        for page_idx in range(max_pages):
            res = client.fetch_conversation_messages_page(
                page_id=page_id,
                conversation_id=group_conv_id,
                current_count=current_count,
            )
            if not res.get("success"):
                if page_idx == 0:
                    return {
                        "success": False,
                        "fetched": fetched_total,
                        "inserted": 0,
                        "merged": 0,
                        "skipped_non_boss": skipped_non_boss,
                        "group_conversation_id": group_conv_id,
                        "message": res.get("message") or "Không thể tải tin nhắn từ Pancake.",
                    }
                break

            messages = res.get("messages") or []
            if not messages:
                break

            fetched_total += len(messages)
            hit_previously_seen = False

            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                if msg.get("is_removed") or msg.get("is_hidden"):
                    continue

                msg_id = str(msg.get("id") or "").strip()
                if not msg_id or msg_id in seen_batch_ids:
                    continue
                seen_batch_ids.add(msg_id)

                if msg_id in last_seen_set:
                    hit_previously_seen = True
                    continue

                newly_seen_ordered.append(msg_id)

                matched = match_boss_sender(msg, boss_rules=boss_rules)
                if not matched:
                    skipped_non_boss += 1
                    continue

                boss_key, boss_display, sender_name = matched
                content, attachments = _extract_attachments_and_text(msg)
                if not content:
                    skipped_empty += 1
                    continue

                posted_at = parse_pancake_date(msg.get("inserted_at")) or get_vn_now()
                sender_id, _ = _extract_sender_candidates(msg)
                raw_boss_candidates.append({
                    "msg_id": msg_id,
                    "boss_key": boss_key,
                    "boss_display": boss_display,
                    "sender_name": sender_name,
                    "sender_id": sender_id or None,
                    "content": content,
                    "attachments": attachments,
                    "posted_at": posted_at,
                })

            # Dừng sớm ngay khi gặp tin nhắn đã quét ở lần sync trước (kể cả tin nhân viên)
            if hit_previously_seen:
                break
            if len(messages) < 30:
                break
            current_count += len(messages)

        inserted_count = 0
        merged_count = 0

        if raw_boss_candidates:
            # 1. Chỉ truy vấn các msg_id thực sự nằm trong batch này + 1 bản tin gần nhất để gộp chuỗi (0 full-table scan)
            cand_ids = [c["msg_id"] for c in raw_boss_candidates]
            existing_db_ids = {
                r[0]
                for r in session.query(BulletinPost.pancake_message_id)
                .filter(BulletinPost.pancake_message_id.in_(cand_ids))
                .all()
            }

            # Kiểm tra thêm merged_message_ids của 10 bản tin gần nhất để tránh chèn lại tin đã được gộp
            recent_posts = (
                session.query(BulletinPost)
                .options(
                    load_only(
                        BulletinPost.id,
                        BulletinPost.pancake_message_id,
                        BulletinPost.boss_key,
                        BulletinPost.title,
                        BulletinPost.content,
                        BulletinPost.attachments,
                        BulletinPost.merged_message_ids,
                        BulletinPost.posted_at,
                    )
                )
                .filter(BulletinPost.group_conversation_id == group_conv_id)
                .order_by(desc(BulletinPost.posted_at), desc(BulletinPost.id))
                .limit(10)
                .all()
            )
            for rp in recent_posts:
                existing_db_ids.add(rp.pancake_message_id)
                for mid in (rp.merged_message_ids or []):
                    existing_db_ids.add(str(mid))

            # Sắp xếp tăng dần theo thời gian để gom chuỗi tin liên tiếp của cùng 1 sếp chuẩn xác
            raw_boss_candidates.sort(key=lambda x: (x["posted_at"], x["msg_id"]))
            last_post: Optional[BulletinPost] = recent_posts[0] if recent_posts else None

            for c in raw_boss_candidates:
                if c["msg_id"] in existing_db_ids:
                    continue

                can_merge = False
                if last_post is not None and last_post.boss_key == c["boss_key"] and last_post.posted_at:
                    delta_sec = (c["posted_at"] - last_post.posted_at).total_seconds()
                    if 0 <= delta_sec <= merge_window_sec:
                        can_merge = True

                if can_merge and last_post is not None:
                    # Gộp chuỗi tin liên tiếp của cùng 1 sếp (VD: nhắn 3 bong bóng liền nhau hoặc chữ + ảnh)
                    if c["content"] and c["content"] not in (last_post.content or ""):
                        last_post.content = f"{last_post.content}\n{c['content']}".strip()
                    if c["attachments"]:
                        merged_atts = list(last_post.attachments or [])
                        existing_urls = {a.get("url") or a.get("link") for a in merged_atts if isinstance(a, dict)}
                        for att in c["attachments"]:
                            att_key = att.get("url") or att.get("link")
                            if not att_key or att_key not in existing_urls:
                                merged_atts.append(att)
                        last_post.attachments = merged_atts
                    merged_ids = list(last_post.merged_message_ids or [])
                    if c["msg_id"] not in merged_ids:
                        merged_ids.append(c["msg_id"])
                    last_post.merged_message_ids = merged_ids
                    existing_db_ids.add(c["msg_id"])
                    merged_count += 1
                else:
                    post = BulletinPost(
                        pancake_message_id=c["msg_id"],
                        group_conversation_id=group_conv_id,
                        group_name=group_name,
                        source_page_id=page_id,
                        sender_id=c["sender_id"],
                        sender_name=c["sender_name"],
                        boss_key=c["boss_key"],
                        boss_display_name=c["boss_display"],
                        title=_build_post_title(c["content"]),
                        content=c["content"],
                        attachments=c["attachments"] or None,
                        merged_message_ids=[c["msg_id"]],
                        posted_at=c["posted_at"],
                        is_pinned=False,
                        raw_payload=None,  # Không lưu JSON thô nặng để tối ưu dung lượng & Neon Egress
                        created_at=get_vn_now(),
                    )
                    session.add(post)
                    existing_db_ids.add(c["msg_id"])
                    last_post = post
                    inserted_count += 1

            session.commit()

        # Cập nhật rolling window last_seen_message_ids để lần sau dừng sớm ngay trang 1
        if newly_seen_ordered:
            updated_seen = list(dict.fromkeys(newly_seen_ordered + last_seen_list))[:MAX_LAST_SEEN_IDS]
            cfg["last_seen_message_ids"] = updated_seen
            save_bulletin_source_config(session, cfg)

        return {
            "success": True,
            "fetched": fetched_total,
            "inserted": inserted_count,
            "merged": merged_count,
            "skipped_non_boss": skipped_non_boss,
            "skipped_empty": skipped_empty,
            "group_conversation_id": group_conv_id,
            "group_name": group_name,
            "message": (
                f"Đã đồng bộ {inserted_count} bản tin mới"
                + (f" (và gộp {merged_count} tin nối tiếp)" if merged_count > 0 else "")
                + f" từ nhóm '{group_name}'."
            ),
        }
    except Exception as e:
        session.rollback()
        logger.error(f"Lỗi sync_bulletin_from_group: {e}", exc_info=True)
        return {
            "success": False,
            "fetched": 0,
            "inserted": 0,
            "merged": 0,
            "skipped_non_boss": 0,
            "message": str(e),
        }
    finally:
        if own_session:
            session.close()


def list_consultant_zalo_contacts(max_convs: int = 300) -> Dict[str, Any]:
    """Liệt kê các hội thoại 1-1 trên page Eztech Consultant để Admin map nhanh với nhân viên EzTech."""
    page_token = get_token_for_page(EZTECH_CONSULTANT_PAGE_ID)
    client = PancakeClient(api_token=page_token)
    convs = client.list_page_conversations(
        page_id=EZTECH_CONSULTANT_PAGE_ID,
        max_convs=max_convs,
        include_groups=False,
        only_groups=False,
        only_personal_zalo=True,
        max_api_pages=15,
    )
    contacts: List[Dict[str, Any]] = []
    for c in convs:
        cid = str(c.get("id") or "").strip()
        if not cid:
            continue
        name = extract_conversation_name(c) or "Unknown"
        phone = None
        recent_phones = c.get("recent_phone_numbers") or []
        if isinstance(recent_phones, list) and recent_phones:
            phone = normalize_phone(recent_phones[0].get("phone_number"))
        if not phone:
            customers = c.get("customers") or []
            if isinstance(customers, list) and customers:
                phone = normalize_phone(customers[0].get("phone_number"))
        contacts.append({
            "conversation_id": cid,
            "display_name": name,
            "phone_number": phone,
            "updated_at": c.get("updated_at"),
        })
    return {
        "success": True,
        "page_id": EZTECH_CONSULTANT_PAGE_ID,
        "count": len(contacts),
        "contacts": contacts,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from database.schema import ensure_schema
    ensure_schema()
    print(json.dumps(sync_bulletin_from_group(), ensure_ascii=False, indent=2))
