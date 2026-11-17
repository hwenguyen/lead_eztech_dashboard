"""Kiểm thử module AI RAG (chunking, cosine similarity, hybrid retrieval, live context)."""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./leads_data.db"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base, KnowledgeChunk, SalesDeal, DimLead, FactLeadActivity, get_vn_now
from backend.ai_rag import (
    split_text_into_chunks,
    cosine_similarity,
    retrieve_relevant_chunks,
    build_live_data_context,
    clear_ai_knowledge_cache,
)


def test_ai_rag_pipeline():
    # 1. Kiểm thử tách đoạn văn bản (chunking)
    sample_text = "Đoạn 1 về khóa học Data Analyst.\n\n" + ("Nội dung chi tiết Power BI và SQL. " * 30)
    chunks = split_text_into_chunks(sample_text, max_chars=300, overlap=50)
    assert len(chunks) >= 2
    assert all(len(c) <= 300 for c in chunks)

    # 2. Kiểm thử độ tương đồng cosine
    assert abs(cosine_similarity([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-6
    assert abs(cosine_similarity([1.0, 0.0], [0.0, 1.0]) - 0.0) < 1e-6

    # 3. Kiểm thử Hybrid Retrieval + Cô lập Category theo từng AI (Sale vs Kế toán)
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)
    TestSession = sessionmaker(bind=test_engine)

    with TestSession() as db:
        clear_ai_knowledge_cache()
        db.add_all(
            [
                KnowledgeChunk(
                    doc_id="doc_sale_1",
                    doc_name="Kịch bản Sale",
                    category="sale",
                    chunk_index=0,
                    content="Cách xử lý khi khách chê học phí khóa Data Analyst cao: chia nhỏ lộ trình đóng 2 đợt.",
                    embedding=[0.9, 0.1, 0.0],
                ),
                KnowledgeChunk(
                    doc_id="doc_kt_1",
                    doc_name="Quy định Kế toán",
                    category="ke_toan",
                    chunk_index=0,
                    content="Công thức tính còn nợ = phải thu trừ đã thu trên bảng sales_deals.",
                    embedding=[0.1, 0.9, 0.0],
                ),
                SalesDeal(
                    deal_uid="deal_test_1",
                    ngay_thu="2026-11-16",
                    sdt="0988777666",
                    ho_ten="Nguyễn Văn A",
                    chuong_trinh="Data Analyst",
                    da_thu=3000000,
                    phai_thu=5000000,
                    tong_tien=5000000,
                    con_no=2000000,
                ),
            ]
        )
        db.commit()

        # AI Sale chỉ lấy tài liệu category 'sale' / 'chung', không bốc nhầm 'ke_toan'
        sale_res = retrieve_relevant_chunks(db, "khách chê học phí cao", ["sale", "chung"], api_key="", top_k=3)
        assert len(sale_res) == 1
        assert sale_res[0]["doc_name"] == "Kịch bản Sale"

        # AI Kế toán lấy dữ liệu công nợ trực tiếp từ bảng sales_deals
        kt_ctx, kt_tools = build_live_data_context(db, "ke_toan", "Kiểm tra công nợ SĐT 0988777666")
        assert "Nguyễn Văn A" in kt_ctx
        assert "2,000,000" in kt_ctx
        assert len(kt_tools) >= 1

        # AI Quy trình & SLA đọc dữ liệu Dashboard Tổng quan & tồn đọng Remind
        now_vn = get_vn_now()
        lead1 = DimLead(customer_id="c1", name="Khách 1", phone_number="0901111222", page_id="fb_page_1", first_created_at=now_vn - timedelta(days=1))
        lead2 = DimLead(customer_id="c2", name="Khách 2", phone_number="", page_id="fb_page_1", first_created_at=now_vn - timedelta(days=10))
        db.add_all([lead1, lead2])
        db.flush()
        db.add_all([
            FactLeadActivity(lead_id=lead1.id, conversation_id="conv_1", status_tag="Đào tạo, Remind", assigned_users="Tran Dat", contacted_at=now_vn - timedelta(days=9)),
            FactLeadActivity(lead_id=lead2.id, conversation_id="conv_2", status_tag="Có thông tin", assigned_users="", contacted_at=now_vn - timedelta(days=1)),
        ])
        db.commit()
        clear_ai_knowledge_cache()

        qt_ctx, qt_tools = build_live_data_context(db, "quy_trinh", "Kiểm tra tồn đọng Remind và chỉ số 7 ngày qua")
        assert "DỮ LIỆU DASHBOARD" in qt_ctx
        assert ">7 ngày quá hạn=1" in qt_ctx
        assert "Tran Dat" in qt_ctx
        assert len(qt_tools) >= 2

        # Câu hỏi thuần định nghĩa không gọi nặng dashboard
        rule_ctx, rule_tools = build_live_data_context(db, "quy_trinh", "Cách tính Lead Mới trên Dashboard?")
        assert rule_ctx == ""
        assert rule_tools == []

    print("ALL AI RAG TESTS PASSED!")


if __name__ == "__main__":
    test_ai_rag_pipeline()
