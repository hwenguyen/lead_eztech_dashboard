"""
ETL Auto-Learn: Tự động học các tình huống xử lý từ chối & văn phong chốt đơn mới
từ những hội thoại vừa gắn tag 'Đã là học viên', lưu vào bảng `knowledge_chunks` (category='sale').

Thiết kế độc lập với FastAPI/Pydantic để chạy gọn bằng `requirements-etl.txt` trên GitHub Actions.
Mặc định chỉ chạy 1 lần mỗi đêm (khung 22:00 - 05:00 giờ VN), hoặc chạy ngay khi truyền `--force`.
"""

import os
import re
import json
import html
import uuid
import argparse
import logging
from datetime import timedelta
from typing import List, Dict, Any, Optional

import requests
from sqlalchemy import desc
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from database.db import SessionLocal
from database.models import (
    AppConfig,
    FactLeadActivity,
    RawConversation,
    KnowledgeChunk,
    get_vn_now,
)

load_dotenv(".env.local")
load_dotenv(".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AiAutoLearn")

AUTOLEARN_DOC_NAME = "Case Chốt Đơn Thực Tế (AI Tự Học)"
SEEN_CONVS_KEY = "ai_autolearn_seen_convs"
LAST_RUN_DATE_KEY = "ai_last_autolearn_date"
MAX_STORED_CHUNKS = 60
EMBEDDING_MODEL = "gemini-embedding-001"
GENERATION_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-3.1-flash-lite",
]


def _get_config(db: Session, key: str) -> str:
    row = db.query(AppConfig).filter(AppConfig.config_key == key).first()
    return (row.config_value or "").strip() if row else ""


def _set_config(db: Session, key: str, value: str) -> None:
    row = db.query(AppConfig).filter(AppConfig.config_key == key).first()
    if row:
        row.config_value = value
    else:
        db.add(AppConfig(config_key=key, config_value=value))


def _resolve_gemini_key(db: Session) -> str:
    return os.getenv("GEMINI_API_KEY", "").strip() or _get_config(db, "GEMINI_API_KEY")


def clean_and_mask_messages(msgs: List[Dict[str, Any]], max_msgs: int = 24) -> str:
    """Làm sạch HTML và ẩn SĐT khỏi nội dung hội thoại trước khi gửi Gemini tóm tắt."""
    if not isinstance(msgs, list):
        return ""
    lines: List[str] = []
    for m in msgs[-max_msgs:]:
        raw_txt = html.unescape(str(m.get("message") or m.get("original_message") or ""))
        txt = re.sub(r"<[^>]+>", " ", raw_txt)
        txt = re.sub(r"\s+", " ", txt).strip()
        if not txt:
            continue
        # Ẩn số điện thoại Việt Nam (9-11 chữ số) để không lưu PII vào RAG
        txt = re.sub(r"(?<!\d)(?:\+?84|0)\d[\d\s\.\-]{7,10}\d(?!\d)", "[SĐT]", txt)
        role = "Khách" if m.get("role") == "Khách hàng" else "Sale"
        lines.append(f"{role}: {txt[:300]}")
    return "\n".join(lines)


def _call_gemini_extract(convs_text: str, api_key: str) -> List[str]:
    """Dùng Gemini rút trích các bài học / câu trả lời thực chiến hay nhất từ hội thoại chốt mới."""
    prompt = (
        "Dưới đây là một số đoạn hội thoại thật giữa Sale EzTech và khách hàng vừa đăng ký học thành công.\n"
        "Hãy rút trích tối đa 5 tình huống/kinh nghiệm xử lý HAY NHẤT (cách đồng cảm, cách trả lời thắc mắc, cách xử lý từ chối hoặc chuyển bước chốt).\n"
        "QUY TẮC BẮT BUỘC:\n"
        "- KHÔNG ghi tên riêng khách hàng, KHÔNG ghi SĐT, KHÔNG ghi ngày khai giảng cụ thể hay số tiền cũ nếu dễ lỗi thời.\n"
        "- Chỉ giữ lại kỹ thuật giao tiếp, cách giải thích dễ hiểu và hướng xử lý tự nhiên như người thật nhắn tin.\n"
        "- Trả về đúng định dạng JSON array gồm các chuỗi ngắn gọn (mỗi phần tử 1 tình huống dạng: 'Tình huống: ...\\nCách Sale xử lý: ...'). Nếu không có tình huống nào nổi bật, trả về [].\n\n"
        f"{convs_text}"
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.25,
            "maxOutputTokens": 2048,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    for model_name in GENERATION_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            resp = requests.post(url, json=payload, timeout=20)
            if resp.status_code == 400 and "thinking" in resp.text.lower():
                no_think = {**payload, "generationConfig": {"temperature": 0.25, "maxOutputTokens": 2048}}
                resp = requests.post(url, json=no_think, timeout=20)
            if resp.status_code == 200:
                parts = (resp.json().get("candidates") or [{}])[0].get("content", {}).get("parts") or []
                raw = "".join(p.get("text", "") for p in parts).strip()
                m = re.search(r"\[.*\]", raw, flags=re.S)
                if m:
                    items = json.loads(m.group(0))
                    if isinstance(items, list):
                        return [str(x).strip() for x in items if str(x).strip()]
                return []
        except Exception as e:
            logger.warning(f"Gemini extract fallback on {model_name}: {e}")
    return []


def _embed_batch(texts: List[str], api_key: str) -> List[Optional[List[float]]]:
    if not texts:
        return []
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{EMBEDDING_MODEL}:batchEmbedContents?key={api_key}"
    payload = {
        "requests": [
            {
                "model": f"models/{EMBEDDING_MODEL}",
                "content": {"parts": [{"text": t[:3000]}]},
                "outputDimensionality": 768,
            }
            for t in texts
        ]
    }
    try:
        resp = requests.post(url, json=payload, timeout=25)
        if resp.status_code == 200:
            return [e.get("values") for e in resp.json().get("embeddings", [])]
    except Exception as e:
        logger.warning(f"Embedding error during auto-learn: {e}")
    return [None for _ in texts]


def run_auto_learn(db: Session, days_back: int = 2, max_convs: int = 12, force: bool = False) -> int:
    now_vn = get_vn_now()
    today_str = now_vn.strftime("%Y-%m-%d")

    if not force:
        # Chỉ chạy tự động trong khung đêm (22:00 - 05:00 VN) và tối đa 1 lần/đêm
        if not (now_vn.hour >= 22 or now_vn.hour < 5):
            logger.info(f"Bỏ qua auto-learn vì hiện tại là {now_vn.strftime('%H:%M')} VN (chỉ chạy ban đêm).")
            return 0
        if _get_config(db, LAST_RUN_DATE_KEY) == today_str:
            logger.info(f"Auto-learn đã chạy trong ngày {today_str}, bỏ qua.")
            return 0

    api_key = _resolve_gemini_key(db)
    if not api_key:
        logger.warning("Chưa cấu hình GEMINI_API_KEY, bỏ qua auto-learn.")
        return 0

    try:
        seen_ids: List[str] = json.loads(_get_config(db, SEEN_CONVS_KEY) or "[]")
        if not isinstance(seen_ids, list):
            seen_ids = []
    except Exception:
        seen_ids = []
    seen_set = set(seen_ids)

    cutoff = now_vn - timedelta(days=days_back)
    acts = (
        db.query(FactLeadActivity.conversation_id)
        .filter(
            FactLeadActivity.updated_at >= cutoff,
            FactLeadActivity.status_tag.ilike("%Đã là học viên%"),
            ~FactLeadActivity.conversation_id.like("pzl_g_%"),
        )
        .order_by(desc(FactLeadActivity.updated_at))
        .limit(max_convs * 3)
        .all()
    )
    new_conv_ids = [cid for (cid,) in acts if cid and cid not in seen_set][:max_convs]
    if not new_conv_ids:
        logger.info("Không có hội thoại 'Đã là học viên' mới cần học.")
        _set_config(db, LAST_RUN_DATE_KEY, today_str)
        db.commit()
        return 0

    raw_rows = (
        db.query(RawConversation.pancake_id, RawConversation.payload["messages"])
        .filter(RawConversation.pancake_id.in_(new_conv_ids))
        .all()
    )

    transcripts: List[str] = []
    processed_ids: List[str] = []
    for cid, msgs in raw_rows:
        processed_ids.append(cid)
        if isinstance(msgs, str):
            try:
                msgs = json.loads(msgs)
            except Exception:
                msgs = []
        if not isinstance(msgs, list) or len(msgs) < 4:
            continue
        cleaned = clean_and_mask_messages(msgs)
        if len(cleaned) >= 120:
            transcripts.append(f"=== Hội thoại ===\n{cleaned}")

    added_chunks = 0
    if transcripts:
        learned_cases = _call_gemini_extract("\n\n".join(transcripts[:8]), api_key)
        if learned_cases:
            embeddings = _embed_batch(learned_cases, api_key)
            doc_id = f"doc_{uuid.uuid4().hex[:10]}"
            for idx, (case_txt, emb) in enumerate(zip(learned_cases, embeddings)):
                db.add(
                    KnowledgeChunk(
                        doc_id=doc_id,
                        doc_name=AUTOLEARN_DOC_NAME,
                        category="sale",
                        chunk_index=idx,
                        content=case_txt,
                        embedding=emb,
                        created_by="auto_learn_etl",
                    )
                )
                added_chunks += 1

            # Giới hạn tối đa MAX_STORED_CHUNKS đoạn tự học để giữ nhẹ Neon Storage
            all_auto = (
                db.query(KnowledgeChunk.id)
                .filter(KnowledgeChunk.doc_name == AUTOLEARN_DOC_NAME)
                .order_by(desc(KnowledgeChunk.id))
                .all()
            )
            if len(all_auto) > MAX_STORED_CHUNKS:
                stale_ids = [row_id for (row_id,) in all_auto[MAX_STORED_CHUNKS:]]
                db.query(KnowledgeChunk).filter(KnowledgeChunk.id.in_(stale_ids)).delete(synchronize_session=False)

    merged_seen = (seen_ids + processed_ids)[-500:]
    _set_config(db, SEEN_CONVS_KEY, json.dumps(merged_seen))
    _set_config(db, LAST_RUN_DATE_KEY, today_str)
    db.commit()
    logger.info(f"Auto-learn hoàn tất: quét {len(processed_ids)} hội thoại mới, thêm {added_chunks} case vào RAG.")
    return added_chunks


def main():
    parser = argparse.ArgumentParser(description="Auto-learn RAG cases from converted student chats")
    parser.add_argument("--days", type=int, default=2, help="Số ngày quét ngược về trước")
    parser.add_argument("--limit", type=int, default=12, help="Số hội thoại mới tối đa mỗi lượt")
    parser.add_argument("--force", action="store_true", help="Chạy ngay không chờ khung giờ đêm")
    args = parser.parse_args()

    with SessionLocal() as db:
        run_auto_learn(db, days_back=args.days, max_convs=args.limit, force=args.force)


if __name__ == "__main__":
    main()
