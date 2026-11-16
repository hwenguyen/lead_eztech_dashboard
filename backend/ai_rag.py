"""
Module AI Nội Bộ (Multi-Agent RAG + Internal API Tools):
- 3 Trợ lý chuyên biệt: AI Sale (`sale`), AI Kế toán (`ke_toan`), AI Quy trình (`quy_trinh`).
- Hybrid RAG: Gemini Embedding (`gemini-embedding-001`, 768 chiều) + Keyword boost.
- In-Memory Cache cho kho tri thức (`_KNOWLEDGE_CACHE`) giúp tốn 0 byte Neon Egress khi hỏi đáp lặp lại.
- Tool dữ liệu trực tiếp: Tự động trích xuất KPI Lead (`lead_metrics.py`), tra cứu Lead theo SĐT/tên,
  và đối soát doanh thu/công nợ (`sales_deals`, `deal_wins`).
"""

import os
import re
import math
import uuid
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple, Set

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, desc

from database.db import get_db
from database.models import (
    KnowledgeChunk,
    AppConfig,
    DimLead,
    FactLeadActivity,
    SalesDeal,
    DealWin,
    get_vn_now,
)
from backend.lead_metrics import classify_leads, normalize_text
from etl.utils import normalize_phone, resolve_canonical_page_name, build_pancake_url

logger = logging.getLogger("AiRagService")

router = APIRouter(prefix="/api/ai", tags=["AI RAG Assistant"])

DEFAULT_GEMINI_KEY = ""
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768
GENERATION_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-3.1-flash-lite",
]

# shortcut: in-memory cosine similarity over JSON vectors, upgrade to pgvector HNSW index when chunk count exceeds 10,000
_CACHE_LOCK = threading.Lock()
_KNOWLEDGE_CACHE: Optional[List[Dict[str, Any]]] = None
_KNOWLEDGE_CACHE_TS: float = 0.0
KNOWLEDGE_CACHE_TTL = 600  # 10 phút
_API_KEY_CACHE: Optional[Tuple[float, str]] = None


AI_ASSISTANTS: Dict[str, Dict[str, Any]] = {
    "sale": {
        "id": "sale",
        "name": "AI Sale & Khóa Học",
        "badge": "Soạn tin & Lead",
        "description": "Dán trực tiếp tin nhắn/câu hỏi của khách để AI soạn sẵn câu trả lời chuẩn Sale EzTech, hoặc hỏi số liệu Lead / SĐT.",
        "categories": ["sale", "chung"],
        "system_prompt": (
            "Bạn là Trợ lý AI Sale thực chiến của EzTech Việt Nam, chuyên hỗ trợ nhân viên Sale soạn tin nhắn trả lời khách hàng và tra cứu thông tin khóa học/sản phẩm "
            "(Data Finance K1-K2-K3, Data Business, Power BI, Power Query, Excel & AI cho Tài chính - Kế toán, Bộ báo cáo B2C, EzHoadon, EzExcel) cũng như số liệu Lead/SĐT.\n\n"
            "HÃY PHÂN BIỆT 2 TÌNH HUỐNG KHI SALE NHẮN:\n"
            "1. KHI SALE DÁN TIN NHẮN / CÂU HỎI CỦA KHÁCH HÀNG (hoặc hỏi cách trả lời khách):\n"
            "- Xuất ra **mẫu tin nhắn** chia thành 2 đến 3 đoạn văn ngắn (mỗi đoạn khoảng 2–5 câu) để Sale copy gửi thẳng như đang nhắn tin trên Zalo/Facebook.\n"
            "- BẮT BUỘC VỀ VĂN PHONG NHẮN TIN NGƯỜI THẬT:\n"
            "  + Viết hoàn toàn bằng đoạn văn tự nhiên như người thật nhắn tin (xưng 'em' - gọi 'anh/chị' khớp theo khách; dùng các từ tự nhiên như 'Dạ', 'chị ơi', 'bên em', 'nhé ạ', 'á chị').\n"
            "  + KHÔNG dùng gạch đầu dòng, KHÔNG đánh số thứ tự 1/2/3, KHÔNG in đậm **...** bên trong nội dung tin nhắn gửi khách.\n"
            "  + HẠN CHẾ TỐI ĐA dấu gạch ngang dài (— / –) và dấu đóng mở ngoặc () trong tin nhắn; diễn đạt thành câu nối tự nhiên bằng dấu phẩy hoặc dấu chấm.\n"
            "  + Đưa đúng thông tin giá, quyền lợi, lịch học, link (nếu cần) từ tài liệu RAG và kết thúc bằng 1 câu hỏi mở nhẹ nhàng để dẫn bước tiếp theo.\n"
            "  + Có thể thêm 1 dòng ngắn **Gợi ý cho Sale:** ở cuối (1–2 câu ngắn nhắc chiến thuật chốt hoặc tag CRM), TUYỆT ĐỐI KHÔNG ghi `[Nguồn: ...]` ở bất kỳ chỗ nào.\n\n"
            "2. KHI SALE HỎI TRA CỨU NỘI BỘ (số liệu Lead/SĐT, tra SĐT khách, hỏi quy trình/chính sách):\n"
            "- Trả lời thẳng, ngắn gọn, chính xác theo dữ liệu hệ thống và tài liệu RAG. KHÔNG chèn `[Nguồn: ...]` vào cuối câu trả lời.\n\n"
            "QUY TẮC CHUNG: Chỉ dùng thông tin có thật trong tài liệu nội bộ và dữ liệu hệ thống cung cấp; nếu thiếu thông tin, nói rõ chưa có thay vì tự bịa."
        ),
        "sample_questions": [
            "Khách nhắn: Chị thấy học phí 7tr5 hơi cao em ạ, với chị hay tăng ca tối sợ không theo kịp lịch học",
            "Khách nhắn: Em ơi chị dùng MacBook với chỉ biết Excel cơ bản thôi có học được khóa kế toán không?",
            "Tóm tắt chỉ số Lead và SĐT 7 ngày qua theo từng nhân viên",
        ],
    },
    "ke_toan": {
        "id": "ke_toan",
        "name": "AI Kế Toán & Công Nợ",
        "badge": "Thu chi & Deal Win",
        "description": "Tra cứu chính sách học phí, quy định hoàn/bảo lưu, xuất hóa đơn và đối soát doanh thu / công nợ học viên.",
        "categories": ["ke_toan", "chung"],
        "system_prompt": (
            "Bạn là Trợ lý AI Kế toán & Quản lý Công nợ nội bộ của EzTech. "
            "Nhiệm vụ: Hỗ trợ tra cứu chính sách học phí, quy định đóng cọc/hoàn phí/bảo lưu, quy trình xuất hóa đơn điện tử, "
            "và đối soát số liệu thu tiền, phải thu, công nợ học viên từ bảng Nhập Deal & Công nợ (sales_deals / deal_wins). "
            "Quy tắc: Luôn trình bày con số chính xác theo dữ liệu hệ thống (định dạng VNĐ dễ đọc), tuyệt đối không suy đoán số tiền và không cần chèn `[Nguồn: ...]` vào nội dung trả lời."
        ),
        "sample_questions": [
            "Tổng hợp doanh thu đã thu và công nợ còn phải thu hiện tại",
            "Quy trình đối soát Deal Win và nhập công nợ học viên mới như thế nào?",
            "Quy định bảo lưu và hoàn học phí cho học viên?",
        ],
    },
    "quy_trinh": {
        "id": "quy_trinh",
        "name": "AI Quy Trình & SLA",
        "badge": "Vận hành & KPI",
        "description": "Tra cứu định nghĩa chỉ số KPI, quy tắc gắn Tag Pancake, SLA phản hồi khách hàng và quy trình vận hành.",
        "categories": ["quy_trinh", "chung"],
        "system_prompt": (
            "Bạn là Trợ lý AI Quy trình & Vận hành (SLA) của EzTech. "
            "Nhiệm vụ: Hướng dẫn nhân sự mới và đội vận hành về định nghĩa các chỉ số KPI trên Dashboard, "
            "quy tắc gắn thẻ (Tag) trên Pancake, quy trình chăm sóc Lead qua Zalo cá nhân, và quy định Bot tự động. "
            "Quy tắc: Trả lời chuẩn xác theo tài liệu quy trình của EzTech, trình bày từng bước rõ ràng, không cần chèn `[Nguồn: ...]` vào câu trả lời."
        ),
        "sample_questions": [
            "Cách tính Lead Mới, Lead Contact Lại và SĐT thu được trên Dashboard?",
            "Quy tắc phân biệt tag Đào tạo và Lead Other trên Pancake?",
            "Khi nào Bot tự động dừng trả lời để nhân viên tư vấn 1-1?",
        ],
    },
}


DEFAULT_SEED_DOCS: List[Dict[str, str]] = [
    {
        "doc_name": "Kịch bản Tư vấn & Xử lý Từ chối Sale EzTech",
        "category": "sale",
        "content": (
            "1. Đối tượng học viên mục tiêu của EzTech:\n"
            "- Kế toán viên, Kế toán tổng hợp, Kiểm toán, Tài chính doanh nghiệp muốn chuyển dịch hoặc nâng cấp kỹ năng Phân tích dữ liệu (Data Analytics: Excel nâng cao, Power BI, SQL, Python).\n"
            "- Nỗi đau thường gặp: Làm báo cáo thủ công tốn thời gian, file Excel nặng hay treo, sếp yêu cầu dashboard trực quan theo thời gian thực.\n\n"
            "2. Quy trình 5 bước tư vấn chốt Sale chuẩn:\n"
            "- Bước 1: Khai thác nhu cầu (Hỏi công việc hiện tại, công cụ đang dùng, mục tiêu học để làm báo cáo hay chuyển ngành).\n"
            "- Bước 2: Xin SĐT kết bạn Zalo tư vấn sâu và gửi đề cương + video học thử.\n"
            "- Bước 3: Gửi lộ trình cá nhân hóa + case study thực tế ngành Tài chính - Kế toán.\n"
            "- Bước 4: Báo học phí kèm ưu đãi đăng ký sớm / nhóm và chính sách cam kết đồng hành 1-1.\n"
            "- Bước 5: Chốt cọc giữ chỗ hoặc hoàn tất học phí, gắn tag 'Đã là học viên' trên Pancake và điền form Deal Win.\n\n"
            "3. Xử lý từ chối thường gặp:\n"
            "- Khách báo 'Bận không có thời gian': Nhấn mạnh lộ trình học linh hoạt, có video record xem lại trọn đời, nhóm hỗ trợ 1-1 giải đáp trực tiếp trên bài tập thực tế.\n"
            "- Khách báo 'Sợ không theo kịp vì không biết code/IT': Khẳng định giáo trình thiết kế riêng cho dân Kế toán - Tài chính, đi từ tư duy dữ liệu và bài toán thực tế, cầm tay chỉ việc từ con số 0.\n"
            "- Khách báo 'Học phí cao': Chia nhỏ chi phí theo tháng/buổi học và so sánh với giá trị tiết kiệm hàng chục giờ làm báo cáo mỗi tháng; hỗ trợ chính sách đóng thành 2 đợt nếu học viên khó khăn."
        ),
    },
    {
        "doc_name": "Quy định Đối soát Deal Win, Công nợ & Hóa đơn",
        "category": "ke_toan",
        "content": (
            "1. Quy trình đồng bộ Deal Win sang Nhập Deal & Công nợ:\n"
            "- Khi học viên chuyển khoản thành công, Sale điền thông tin học viên vào Sheet/Form Deal Win và gắn tag 'Đã là học viên' trên Pancake.\n"
            "- Hệ thống tự động kéo học viên từ bảng deal_wins sang bảng sales_deals với trạng thái 'Chờ bổ sung' nếu chưa điền đủ Số tiền thu / Lớp học / Nhóm CS 1-1.\n"
            "- Kế toán và Sale vào tab 'Nhập Deal & Công Nợ' để cập nhật: Tổng tiền (phai_thu / tong_tien), Đã thu (da_thu), Chương trình học, Lớp học, Ngày thu AR.\n\n"
            "2. Công thức tính Công nợ trên hệ thống:\n"
            "- Còn nợ (con_no) = Phải thu (phai_thu) - Đã thu (da_thu) - Đã thu nợ cũ.\n"
            "- Các trạng thái chuẩn: 'Đã hoàn thành' (khi còn nợ = 0), 'Còn nợ' (khi còn nợ > 0), 'Chờ bổ sung' (mới đồng bộ từ Deal Win), 'Bảo lưu', 'Hoàn học phí'.\n\n"
            "3. Chính sách Đặt cọc, Bảo lưu & Xuất hóa đơn:\n"
            "- Học viên đóng cọc cần ghi rõ Ngày hẹn thu AR (ngay_thu_ar) để Kế toán và Sale theo dõi nhắc hạn.\n"
            "- Bảo lưu: Học viên được hỗ trợ bảo lưu sang khóa kế tiếp khi có lý do chính đáng và báo trước cho bộ phận CSKH.\n"
            "- Xuất hóa đơn điện tử: Thực hiện tại tab 'Xuất hoá đơn' trên Dashboard sau khi Kế toán xác nhận khoản thu đã khớp sao kê ngân hàng."
        ),
    },
    {
        "doc_name": "Quy chuẩn Chỉ số KPI, Gắn Tag Pancake & Vận hành SLA",
        "category": "quy_trinh",
        "content": (
            "1. Định nghĩa chuẩn các chỉ số KPI trên EzTech Dashboard:\n"
            "- Lead Mới: Khách hàng có thời điểm tạo hội thoại lần đầu (first_created_at) nằm trong kỳ báo cáo.\n"
            "- Lead Contact Lại: Khách hàng tạo TRƯỚC kỳ báo cáo, nhưng có phát sinh tin nhắn (của khách hoặc nhân viên) trong kỳ.\n"
            "- Tổng Lead = Lead Mới + Lead Contact Lại (không trùng lặp).\n"
            "- SĐT thu được: Mỗi số điện thoại chuẩn hóa chỉ tính 1 lần duy nhất vào thời điểm khách gửi số lần đầu (phone_at). Bao gồm cả khách có số điện thoại hoặc được gắn tag 'đã add'.\n"
            "- Tỷ lệ SĐT / Tạo mới (%) = SĐT Mới / Lead Mới.\n\n"
            "2. Quy tắc phạm vi Page và Kênh Zalo:\n"
            "- Mặc định khi xem 'Tất cả page nguồn lead': Hệ thống tính mọi Fanpage Facebook & TikTok, TRỪ các page Zalo cá nhân (vì Zalo là kênh chăm sóc sau khi đã xin được SĐT).\n"
            "- Các nhóm chat Zalo (có mã pzl_g_...) được hệ thống tự động lọc bỏ để không làm sai lệch số lượng Lead cá nhân.\n\n"
            "3. Quy tắc gắn Tag trên Pancake & SLA Chăm sóc:\n"
            "- Nhóm Đào tạo: Gắn chính xác tag 'Đào tạo' hoặc 'HV TCKT'.\n"
            "- Nhóm Lead Other: Gắn chính xác tag 'Lead Other', 'Support Other' hoặc 'HV Khác'.\n"
            "- Khi khách đã đăng ký học: Bắt buộc gắn tag 'Đã là học viên' để Bot Gửi Tin tự động loại trừ (không gửi tin broadcast quảng cáo làm phiền học viên).\n"
            "- Chốt chặn Bot tự động: Bot sẽ tự động dừng trả lời nếu hội thoại có tag khóa học ('Đã là học viên', 'Đào tạo', 'HV TCKT'...) hoặc khách nhắn từ khóa hỏi về học phí, lộ trình, khai giảng để nhân viên Sale vào tư vấn 1-1."
        ),
    },
]


def clear_ai_knowledge_cache():
    global _KNOWLEDGE_CACHE, _KNOWLEDGE_CACHE_TS, _API_KEY_CACHE
    with _CACHE_LOCK:
        _KNOWLEDGE_CACHE = None
        _KNOWLEDGE_CACHE_TS = 0.0
        _API_KEY_CACHE = None


def get_gemini_api_key(db: Session) -> str:
    global _API_KEY_CACHE
    now = time.time()
    if _API_KEY_CACHE and (now - _API_KEY_CACHE[0] < 300):
        return _API_KEY_CACHE[1]

    key = ""
    try:
        cfg = db.query(AppConfig).filter(AppConfig.config_key == "GEMINI_API_KEY").first()
        if cfg and cfg.config_value and cfg.config_value.strip():
            key = cfg.config_value.strip()
    except Exception:
        pass

    if not key:
        key = os.getenv("GEMINI_API_KEY", "").strip() or DEFAULT_GEMINI_KEY

    _API_KEY_CACHE = (now, key)
    return key


def mask_api_key(key: str) -> str:
    if not key or len(key) < 12:
        return "Chưa cấu hình"
    return f"{key[:7]}...{key[-5:]}"


def split_text_into_chunks(text: str, max_chars: int = 800, overlap: int = 120) -> List[str]:
    cleaned = re.sub(r"\r\n?", "\n", (text or "").strip())
    if not cleaned:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", cleaned) if p.strip()]
    chunks: List[str] = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_chars:
            current = f"{current}\n\n{para}".strip() if current else para
        else:
            if current:
                chunks.append(current)
            if len(para) <= max_chars:
                current = para
            else:
                step = max(200, max_chars - overlap)
                for idx in range(0, len(para), step):
                    piece = para[idx : idx + max_chars].strip()
                    if piece:
                        chunks.append(piece)
                current = ""
    if current:
        chunks.append(current)
    return chunks


def embed_texts(texts: List[str], api_key: str) -> List[Optional[List[float]]]:
    if not texts:
        return []
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{EMBEDDING_MODEL}:batchEmbedContents?key={api_key}"
    requests_payload = [
        {
            "model": f"models/{EMBEDDING_MODEL}",
            "content": {"parts": [{"text": t[:3000]}]},
            "outputDimensionality": EMBEDDING_DIM,
        }
        for t in texts
    ]
    try:
        resp = requests.post(url, json={"requests": requests_payload}, timeout=20)
        if resp.status_code == 200:
            embeddings = resp.json().get("embeddings", [])
            return [emb.get("values") for emb in embeddings]
        logger.warning(f"Gemini batchEmbedContents status {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Gemini embedding error: {e}")
    return [None for _ in texts]


def cosine_similarity(v1: Optional[List[float]], v2: Optional[List[float]]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    return dot / (n1 * n2)


def _load_knowledge_cache(db: Session) -> List[Dict[str, Any]]:
    global _KNOWLEDGE_CACHE, _KNOWLEDGE_CACHE_TS
    now = time.time()
    with _CACHE_LOCK:
        if _KNOWLEDGE_CACHE is not None and (now - _KNOWLEDGE_CACHE_TS < KNOWLEDGE_CACHE_TTL):
            return _KNOWLEDGE_CACHE

    rows = db.query(KnowledgeChunk).order_by(KnowledgeChunk.id.asc()).all()
    items = [
        {
            "id": r.id,
            "doc_id": r.doc_id,
            "doc_name": r.doc_name,
            "category": r.category,
            "chunk_index": r.chunk_index,
            "content": r.content,
            "embedding": r.embedding,
            "norm_content": normalize_text(f"{r.doc_name} {r.content}"),
            "created_by": r.created_by,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
        }
        for r in rows
    ]
    with _CACHE_LOCK:
        _KNOWLEDGE_CACHE = items
        _KNOWLEDGE_CACHE_TS = now
    return items


def retrieve_relevant_chunks(
    db: Session,
    query_text: str,
    categories: List[str],
    api_key: str,
    top_k: int = 6,
) -> List[Dict[str, Any]]:
    all_chunks = _load_knowledge_cache(db)
    target_chunks = [c for c in all_chunks if c["category"] in categories]
    if not target_chunks:
        return []

    query_vecs = embed_texts([query_text], api_key)
    query_vec = query_vecs[0] if query_vecs else None
    norm_q = normalize_text(query_text)
    q_tokens = [tok for tok in norm_q.split() if len(tok) >= 2]

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for chunk in target_chunks:
        vec_score = cosine_similarity(query_vec, chunk.get("embedding")) if query_vec else 0.0
        kw_hits = sum(1 for tok in q_tokens if tok in chunk["norm_content"])
        kw_score = (kw_hits / len(q_tokens)) if q_tokens else 0.0
        final_score = (vec_score * 0.75) + (kw_score * 0.25) if query_vec else kw_score
        if final_score > 0.08 or len(target_chunks) <= top_k:
            scored.append((final_score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "doc_id": item["doc_id"],
            "doc_name": item["doc_name"],
            "category": item["category"],
            "content": item["content"],
            "score": round(score, 3),
        }
        for score, item in scored[:top_k]
    ]


def build_live_data_context(db: Session, assistant_id: str, question: str) -> Tuple[str, List[str]]:
    """Trích xuất dữ liệu thực tế từ DB theo đúng trợ lý (Sale / Kế toán) mà không quét bảng thừa."""
    tools_used: List[str] = []
    context_blocks: List[str] = []
    now_vn = get_vn_now()
    norm_q = normalize_text(question)

    # Bóc số điện thoại nếu câu hỏi có chứa dãy 4-11 chữ số
    phone_matches = re.findall(r"(?:\+?84|0)?\d[\d\s\.\-]{3,11}\d", question)
    search_digits = [re.sub(r"\D", "", m) for m in phone_matches if len(re.sub(r"\D", "", m)) >= 4]

    if assistant_id == "sale":
        wants_kpi = any(
            kw in norm_q
            for kw in ("lead", "sdt", "so dien thoai", "kpi", "bao nhieu", "tong", "nhan vien", "thong ke", "7 ngay", "tuan", "hom nay", "ti le")
        )
        if wants_kpi:
            try:
                start_7d = (now_vn - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
                end_now = now_vn.replace(hour=23, minute=59, second=59, microsecond=999999)
                leads_map = classify_leads(db, start_7d, end_now)
                new_leads = recontact_leads = new_phone = recontact_phone = 0
                emp_counts: Dict[str, int] = {}
                phone_emp_counts: Dict[str, int] = {}
                for ld in leads_map.values():
                    emp = ld.primary_employee or "Chưa phân công"
                    if ld.is_new:
                        new_leads += 1
                        emp_counts[emp] = emp_counts.get(emp, 0) + 1
                        if ld.has_phone:
                            new_phone += 1
                    else:
                        recontact_leads += 1
                        if ld.has_phone:
                            recontact_phone += 1
                    if ld.has_phone:
                        phone_emp_counts[emp] = phone_emp_counts.get(emp, 0) + 1

                total_leads = new_leads + recontact_leads
                total_phone = new_phone + recontact_phone
                emp_stats = ", ".join(f"{k}: {v} lead mới" for k, v in list(emp_counts.items())[:8])
                phone_emp = ", ".join(f"{k}: {v} SĐT" for k, v in list(phone_emp_counts.items())[:8])
                context_blocks.append(
                    f"[DỮ LIỆU LEAD 7 NGÀY QUA ({start_7d.strftime('%d/%m/%Y')} - {now_vn.strftime('%d/%m/%Y')})]\n"
                    f"- Tổng Lead: {total_leads} (Lead Mới: {new_leads}, Contact Lại: {recontact_leads})\n"
                    f"- Tổng SĐT thu được: {total_phone} (SĐT Mới: {new_phone}, SĐT Contact Lại: {recontact_phone})\n"
                    f"- Phân bổ Lead Mới theo nhân sự: {emp_stats or 'Chưa có'}\n"
                    f"- Phân bổ SĐT theo nhân sự: {phone_emp or 'Chưa có'}"
                )
                tools_used.append("KPI Lead 7 ngày (lead_metrics)")
            except Exception as e:
                logger.warning(f"Sale KPI tool error: {e}")

        if search_digits:
            digit_q = search_digits[0][-9:]
            leads = (
                db.query(DimLead, FactLeadActivity)
                .outerjoin(FactLeadActivity, FactLeadActivity.lead_id == DimLead.id)
                .filter(DimLead.phone_number.like(f"%{digit_q}%"))
                .limit(5)
                .all()
            )
            if leads:
                lines = ["[KẾT QUẢ TRA CỨU LEAD THEO SĐT]"]
                for ld, act in leads:
                    page_name = resolve_canonical_page_name(ld.page_id)
                    p_url = build_pancake_url(ld.page_id, act.conversation_id if act else None)
                    lines.append(
                        f"- Khách: {ld.name or 'Chưa rõ'} | SĐT: {ld.phone_number} | Page: {page_name} | "
                        f"Tag: {act.status_tag if act else 'Chưa gắn'} | Sale: {act.assigned_users if act else 'Chưa phân'} | "
                        f"Link Pancake: {p_url or 'N/A'}"
                    )
                context_blocks.append("\n".join(lines))
                tools_used.append(f"Tra cứu SĐT ({digit_q})")

    elif assistant_id == "ke_toan":
        wants_finance_stats = bool(search_digits) or any(
            kw in norm_q
            for kw in ("doanh thu", "tong hop", "bao nhieu", "cong no", "con no", "da thu", "phai thu", "chua dong", "so lieu", "bao cao", "hien tai")
        )
        if wants_finance_stats:
            try:
                totals = db.query(
                    func.count(SalesDeal.id),
                    func.coalesce(func.sum(SalesDeal.tong_tien), 0),
                    func.coalesce(func.sum(SalesDeal.da_thu), 0),
                    func.coalesce(func.sum(SalesDeal.con_no), 0),
                ).first()
                deal_win_count = db.query(func.count(DealWin.id)).scalar() or 0
                debt_count = db.query(func.count(SalesDeal.id)).filter(SalesDeal.con_no > 0).scalar() or 0
                if totals:
                    cnt, tong_tien, da_thu, con_no = totals
                    context_blocks.append(
                        f"[TỔNG HỢP DOANH THU & CÔNG NỢ TRÊN HỆ THỐNG]\n"
                        f"- Tổng số học viên (Deal Win): {deal_win_count:,} học viên\n"
                        f"- Tổng số bản ghi Nhập Deal (sales_deals): {cnt:,} deal\n"
                        f"- Tổng học phí phải thu: {int(tong_tien):,} VNĐ\n"
                        f"- Tổng tiền đã thu: {int(da_thu):,} VNĐ\n"
                        f"- Tổng công nợ còn phải thu: {int(con_no):,} VNĐ ({debt_count} deal còn nợ)"
                    )
                    tools_used.append("Tổng hợp Doanh thu & Công nợ (sales_deals)")

                if "no" in norm_q or "chua dong" in norm_q or "con no" in norm_q or search_digits:
                    q_deals = db.query(SalesDeal)
                    if search_digits:
                        q_deals = q_deals.filter(SalesDeal.sdt.like(f"%{search_digits[0][-9:]}%"))
                    else:
                        q_deals = q_deals.filter(SalesDeal.con_no > 0)
                    top_deals = q_deals.order_by(desc(SalesDeal.con_no), desc(SalesDeal.id)).limit(8).all()
                    if top_deals:
                        d_lines = ["[DANH SÁCH DEAL / CÔNG NỢ CHI TIẾT]"]
                        for d in top_deals:
                            d_lines.append(
                                f"- Học viên: {d.ho_ten} | SĐT: {d.sdt} | Chương trình: {d.chuong_trinh or 'Chưa rõ'} | "
                                f"Lớp: {d.lop or '-'} | Đã thu: {int(d.da_thu or 0):,}đ | Còn nợ: {int(d.con_no or 0):,}đ | "
                                f"Hạn AR: {d.ngay_thu_ar or '-'} | NV CS: {d.nv_cs or '-'}"
                            )
                        context_blocks.append("\n".join(d_lines))
                        tools_used.append("Chi tiết Công nợ học viên")
            except Exception as e:
                logger.warning(f"Accounting tool error: {e}")

    return "\n\n".join(context_blocks), tools_used


def call_gemini_generate(
    system_prompt: str,
    user_prompt: str,
    history: List[Dict[str, str]],
    api_key: str,
) -> Tuple[str, str]:
    contents: List[Dict[str, Any]] = []
    for msg in history[-6:]:
        role = "model" if msg.get("role") == "assistant" else "user"
        text_val = (msg.get("content") or "").strip()
        if text_val:
            contents.append({"role": role, "parts": [{"text": text_val[:2000]}]})

    contents.append({"role": "user", "parts": [{"text": user_prompt}]})

    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.25,
            "maxOutputTokens": 4096,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    last_error = ""
    for model_name in GENERATION_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            resp = requests.post(url, json=payload, timeout=25)
            # Nếu model không hỗ trợ thinkingConfig thì thử lại bỏ thinkingConfig
            if resp.status_code == 400 and "thinking" in resp.text.lower():
                fallback_payload = {
                    **payload,
                    "generationConfig": {"temperature": 0.25, "maxOutputTokens": 4096},
                }
                resp = requests.post(url, json=fallback_payload, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates") or []
                if candidates:
                    finish_reason = candidates[0].get("finishReason")
                    if finish_reason and finish_reason != "STOP":
                        logger.warning(f"Gemini {model_name} finishReason={finish_reason}")
                    parts = candidates[0].get("content", {}).get("parts") or []
                    answer = "".join(p.get("text", "") for p in parts).strip()
                    if answer:
                        return answer, model_name
            last_error = f"{model_name} HTTP {resp.status_code}: {resp.text[:180]}"
            logger.warning(f"Gemini model {model_name} fallback: {last_error}")
        except Exception as e:
            last_error = f"{model_name} exception: {e}"
            logger.warning(f"Gemini request error on {model_name}: {e}")

    raise HTTPException(
        status_code=502,
        detail=f"Không thể kết nối Gemini API lúc này ({last_error}). Vui lòng kiểm tra lại GEMINI_API_KEY hoặc thử lại sau ít giây.",
    )


def seed_default_knowledge_if_empty(db: Session) -> int:
    count = db.query(func.count(KnowledgeChunk.id)).scalar() or 0
    if count > 0:
        return 0
    return _ingest_documents_list(db, DEFAULT_SEED_DOCS, created_by="system_seed")


def _ingest_documents_list(db: Session, docs: List[Dict[str, str]], created_by: str = "admin") -> int:
    api_key = get_gemini_api_key(db)
    total_chunks = 0
    for doc in docs:
        doc_name = (doc.get("doc_name") or "").strip()
        category = (doc.get("category") or "sale").strip()
        content = (doc.get("content") or "").strip()
        if not doc_name or not content:
            continue

        chunks = split_text_into_chunks(content)
        if not chunks:
            continue

        embeddings = embed_texts(chunks, api_key)
        doc_id = f"doc_{uuid.uuid4().hex[:10]}"
        for idx, (chunk_text, emb) in enumerate(zip(chunks, embeddings)):
            db.add(
                KnowledgeChunk(
                    doc_id=doc_id,
                    doc_name=doc_name,
                    category=category,
                    chunk_index=idx,
                    content=chunk_text,
                    embedding=emb,
                    created_by=created_by,
                )
            )
            total_chunks += 1

    db.commit()
    clear_ai_knowledge_cache()
    return total_chunks


# ───────────────────────── Pydantic Schemas ─────────────────────────


class ChatMessageInput(BaseModel):
    role: str = Field(..., description="user hoặc assistant")
    content: str


class ChatRequest(BaseModel):
    assistant_id: str = Field("sale", description="sale | ke_toan | quy_trinh")
    question: str = Field(..., min_length=1, max_length=2000)
    history: List[ChatMessageInput] = Field(default_factory=list)


class IngestDocumentRequest(BaseModel):
    doc_name: str = Field(..., min_length=2, max_length=200)
    category: str = Field("sale", description="sale | ke_toan | quy_trinh | chung")
    content: str = Field(..., min_length=10)


class ApiKeyConfigRequest(BaseModel):
    api_key: str = Field(..., min_length=10)


# ───────────────────────── API Routes ─────────────────────────


@router.get("/assistants")
def list_assistants(db: Session = Depends(get_db)):
    try:
        seed_default_knowledge_if_empty(db)
    except Exception as e:
        logger.warning(f"Auto-seed warning: {e}")

    all_chunks = _load_knowledge_cache(db)
    doc_map: Dict[str, Set[str]] = {"sale": set(), "ke_toan": set(), "quy_trinh": set(), "chung": set()}
    for c in all_chunks:
        cat = c["category"]
        if cat in doc_map:
            doc_map[cat].add(c["doc_id"])

    assistants_out = []
    for aid, info in AI_ASSISTANTS.items():
        cats = info["categories"]
        doc_ids = set()
        for cat in cats:
            doc_ids |= doc_map.get(cat, set())
        assistants_out.append(
            {
                **info,
                "doc_count": len(doc_ids),
            }
        )

    key = get_gemini_api_key(db)
    return {
        "assistants": assistants_out,
        "total_chunks": len(all_chunks),
        "masked_api_key": mask_api_key(key),
        "has_api_key": bool(key),
    }


@router.get("/documents")
def list_documents(category: Optional[str] = Query(None), db: Session = Depends(get_db)):
    all_chunks = _load_knowledge_cache(db)
    docs_by_id: Dict[str, Dict[str, Any]] = {}
    for c in all_chunks:
        if category and c["category"] != category:
            continue
        did = c["doc_id"]
        if did not in docs_by_id:
            docs_by_id[did] = {
                "doc_id": did,
                "doc_name": c["doc_name"],
                "category": c["category"],
                "chunk_count": 0,
                "preview": c["content"][:220] + ("..." if len(c["content"]) > 220 else ""),
                "has_embedding": bool(c.get("embedding")),
                "created_at": c["created_at"],
            }
        docs_by_id[did]["chunk_count"] += 1

    return {"documents": list(docs_by_id.values())}


@router.post("/documents")
def ingest_document(req: IngestDocumentRequest, db: Session = Depends(get_db)):
    if req.category not in ("sale", "ke_toan", "quy_trinh", "chung"):
        raise HTTPException(status_code=400, detail="Danh mục không hợp lệ (chọn sale, ke_toan, quy_trinh hoặc chung).")

    added = _ingest_documents_list(
        db,
        [{"doc_name": req.doc_name, "category": req.category, "content": req.content}],
        created_by="user",
    )
    return {"status": "ok", "chunks_added": added, "doc_name": req.doc_name}


@router.post("/seed")
def seed_sample_documents(db: Session = Depends(get_db)):
    existing_names = {c["doc_name"] for c in _load_knowledge_cache(db)}
    to_add = [d for d in DEFAULT_SEED_DOCS if d["doc_name"] not in existing_names]
    if not to_add:
        return {"status": "ok", "chunks_added": 0, "message": "Tài liệu mẫu đã có sẵn trong kho tri thức."}
    added = _ingest_documents_list(db, to_add, created_by="system_seed")
    return {"status": "ok", "chunks_added": added, "message": f"Đã nạp thêm {len(to_add)} tài liệu mẫu ({added} đoạn)."}


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str, db: Session = Depends(get_db)):
    deleted = db.query(KnowledgeChunk).filter(KnowledgeChunk.doc_id == doc_id).delete(synchronize_session=False)
    db.commit()
    clear_ai_knowledge_cache()
    return {"status": "ok", "deleted_chunks": deleted}


@router.post("/config")
def update_ai_config(req: ApiKeyConfigRequest, db: Session = Depends(get_db)):
    clean_key = req.api_key.strip()
    cfg = db.query(AppConfig).filter(AppConfig.config_key == "GEMINI_API_KEY").first()
    if cfg:
        cfg.config_value = clean_key
    else:
        db.add(AppConfig(config_key="GEMINI_API_KEY", config_value=clean_key))
    db.commit()
    clear_ai_knowledge_cache()
    return {"status": "ok", "masked_api_key": mask_api_key(clean_key)}


@router.post("/chat")
def chat_with_assistant(req: ChatRequest, db: Session = Depends(get_db)):
    assistant = AI_ASSISTANTS.get(req.assistant_id) or AI_ASSISTANTS["sale"]
    api_key = get_gemini_api_key(db)

    # 1. Truy xuất các đoạn tài liệu RAG liên quan
    retrieved_chunks = retrieve_relevant_chunks(
        db=db,
        query_text=req.question,
        categories=assistant["categories"],
        api_key=api_key,
        top_k=6,
    )

    # 2. Lấy dữ liệu trực tiếp từ hệ thống (KPI Lead, SĐT, hoặc Công nợ Kế toán)
    live_data_context, tools_used = build_live_data_context(db, assistant["id"], req.question)

    # 3. Ghép ngữ cảnh gửi cho Gemini
    context_parts: List[str] = []
    if live_data_context:
        context_parts.append(f"=== DỮ LIỆU HỆ THỐNG TRỰC TIẾP (THỜI GIAN THỰC) ===\n{live_data_context}")

    if retrieved_chunks:
        rag_text = "\n\n".join(
            f"[Tài liệu: {c['doc_name']} | Danh mục: {c['category']}]\n{c['content']}"
            for c in retrieved_chunks
        )
        context_parts.append(f"=== TÀI LIỆU NỘI BỘ (KHO TRI THỨC RAG) ===\n{rag_text}")

    composed_prompt = (
        f"{chr(10).join(context_parts)}\n\n"
        f"=== CÂU HỎI CỦA NHÂN VIÊN ===\n{req.question}\n\n"
        f"Hãy trả lời dựa trên dữ liệu hệ thống và tài liệu nội bộ ở trên."
    )

    answer, model_used = call_gemini_generate(
        system_prompt=assistant["system_prompt"],
        user_prompt=composed_prompt,
        history=[m.model_dump() for m in req.history],
        api_key=api_key,
    )

    return {
        "assistant_id": assistant["id"],
        "assistant_name": assistant["name"],
        "answer": answer,
        "model": model_used,
        "sources": [
            {"doc_name": c["doc_name"], "category": c["category"], "score": c["score"]}
            for c in retrieved_chunks
        ],
        "tools_used": tools_used,
    }
