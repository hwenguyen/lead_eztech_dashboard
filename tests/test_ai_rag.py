"""Kiểm thử module AI RAG (chunking, cosine similarity, hybrid retrieval, live context)."""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./leads_data.db"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base, KnowledgeChunk, SalesDeal, DimLead, FactLeadActivity, RawConversation, Comment, get_vn_now
from backend.ai_rag import (
    split_text_into_chunks,
    cosine_similarity,
    retrieve_relevant_chunks,
    build_live_data_context,
    clear_ai_knowledge_cache,
    _parse_daily_review_json,
    _collect_recent_customer_messages_sample,
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

        # AI Sale đọc TOÀN BỘ hội thoại trên TẤT CẢ các page (3 page + >12 tin + sửa role customer + lọc pzl_g_ + Comment + checklist)
        p_test = "0912345678"
        l_tt = DimLead(customer_id="tt_u1", name="Chị Lan", phone_number=p_test, page_id="Anh Kế toán làm Data (TikTok)", first_created_at=now_vn - timedelta(days=5))
        l_fb = DimLead(customer_id="fb_u1", name="Chị Lan", phone_number=p_test, page_id="Anh Kế toán làm Data (Facebook)", first_created_at=now_vn - timedelta(days=4))
        l_zl = DimLead(customer_id="zl_u1", name="Chị Lan", phone_number=p_test, page_id="Hiền Minh Eztech", first_created_at=now_vn - timedelta(days=3))
        l_grp = DimLead(customer_id="zl_g1", name="Nhóm Lớp", phone_number=p_test, page_id="Hiền Minh Eztech", first_created_at=now_vn - timedelta(days=2))
        db.add_all([l_tt, l_fb, l_zl, l_grp])
        db.flush()
        db.add_all([
            FactLeadActivity(lead_id=l_tt.id, conversation_id="tt_conv_1", status_tag="HV TCKT, đã add", assigned_users="Tran Dat", message_count=2, contacted_at=now_vn - timedelta(days=5)),
            FactLeadActivity(lead_id=l_fb.id, conversation_id="fb_conv_1", status_tag="Có thông tin", assigned_users="Tran Dat", message_count=2, contacted_at=now_vn - timedelta(days=4)),
            FactLeadActivity(lead_id=l_zl.id, conversation_id="pzl_u_1", status_tag="Đã gửi TT, Remind", assigned_users="Hien Minh", message_count=15, contacted_at=now_vn - timedelta(days=1)),
            FactLeadActivity(lead_id=l_grp.id, conversation_id="pzl_g_999", status_tag="Nhóm", assigned_users="", message_count=500, contacted_at=now_vn),
        ])
        zl_msgs = [
            {"message": "<div>Tin đầu tiên số 1: link giữa các file dễ lỗi và tick chọn và kéo thả</div>", "role": "Admin", "inserted_at": "2026-11-10T02:00:00"},
            {"message": "<div>Em gửi lộ trình K1. K2. K3 combo 7.5tr nhé ạ</div>", "role": "Admin", "inserted_at": "2026-11-10T02:05:00"},
        ] + [
            {"message": f"<div>Tin nhắn phụ thứ {k}</div>", "role": "Khách hàng" if k % 2 == 0 else "Admin", "inserted_at": f"2026-11-11T02:{k:02d}:00"}
            for k in range(3, 15)
        ] + [
            {"message": "<div>Mời chị tham gia Data Talk cuối tuần này nhé ạ</div>", "role": "Admin", "inserted_at": "2026-11-15T02:00:00"},
        ]
        db.add_all([
            RawConversation(pancake_id="tt_conv_1", page_id="Anh Kế toán làm Data (TikTok)", payload={"messages": [
                {"message": "<div>Em làm kế toán xây dựng hay phải tổng hợp Excel</div>", "role": "Khách hàng", "inserted_at": "2026-11-09T02:00:00"},
            ]}),
            RawConversation(pancake_id="fb_conv_1", page_id="Anh Kế toán làm Data (Facebook)", payload={"messages": [
                {"message": "<div>Chị nhắn bên FB hỏi thêm học phí</div>", "role": "customer", "inserted_at": "2026-11-09T03:00:00"},
            ]}),
            RawConversation(
                pancake_id="pzl_u_1",
                page_id="Hiền Minh Eztech",
                payload={
                    "messages": zl_msgs,
                    "notes": [
                        {
                            "message": "Khách làm kế toán tổng hợp đang dùng MISA, file Excel nặng, muốn đối chiếu sao kê và lên báo cáo lãi lỗ P&L cho sếp",
                            "created_by": {"fb_name": "Hiền Minh Lý"},
                            "removed_at": None,
                        }
                    ],
                },
            ),
            RawConversation(pancake_id="pzl_g_999", page_id="Hiền Minh Eztech", payload={"messages": [
                {"message": "<div>NOI_DUNG_NHOM_PHAI_BI_LOC</div>", "role": "Khách hàng", "inserted_at": "2026-11-16T02:00:00"},
            ]}),
            Comment(
                comment_id="cmt_1",
                page_id="fb_1",
                page_name="Anh Kế toán làm Data (Facebook)",
                customer_id="fb_u1",
                phone_number=p_test,
                message="Quan tâm khóa Power Query ạ",
                inserted_at=now_vn - timedelta(days=5),
                payload={
                    "page_customer": {
                        "notes": [
                            {
                                "message": "Trần Đạt đã add Zalo, khách hay phải tăng ca tối",
                                "created_by": {"fb_name": "Trần Đạt"},
                            }
                        ]
                    }
                },
            ),
        ])
        db.commit()

        sale_ctx, sale_tools = build_live_data_context(db, "sale", f"Soạn tin remind cho SĐT {p_test}")
        # Đọc đủ cả 3 page (không cắt ở 2 page) và loại bỏ nhóm Zalo pzl_g_
        assert "Anh Kế toán làm Data (TikTok)" in sale_ctx
        assert "Anh Kế toán làm Data (Facebook)" in sale_ctx
        assert "Hiền Minh Eztech" in sale_ctx
        assert "NOI_DUNG_NHOM_PHAI_BI_LOC" not in sale_ctx
        # Đọc đủ >12 tin (thấy tin đầu tiên số 1) và không bị cắt mất tin cũ
        assert "Tin đầu tiên số 1" in sale_ctx
        # Nhận diện đúng role='customer' là Khách (không bị nhầm thành Sale/Admin)
        assert "Khách: Chị nhắn bên FB hỏi thêm học phí" in sale_ctx
        # Đọc được Comment và tạo Checklist cấm lặp Step 2A / Step 3 / Data Talk
        assert "Quan tâm khóa Power Query ạ" in sale_ctx
        assert "Step 2A" in sale_ctx
        assert "Vòng 8: Data Talk" in sale_ctx
        assert "CẤM TUYỆT ĐỐI gửi lại Step 1, Step 2A" in sale_ctx
        # Retrieve được Note của Admin (từ cả RawConversation.payload.notes và Comment.payload.page_customer.notes) & chẩn đoán đúng nỗi đau
        assert "CHẨN ĐOÁN NHANH HỒ SƠ, GHI CHÚ CỦA ADMIN & NỖI ĐAU KHÁCH HÀNG" in sale_ctx
        assert "Note của Hiền Minh Lý" in sale_ctx
        assert "đang dùng MISA, file Excel nặng" in sale_ctx
        assert "Note của Trần Đạt" in sale_ctx
        assert "Quá tải thao tác thủ công trên Excel" in sale_ctx
        assert "Đang dùng phần mềm kế toán (MISA" in sale_ctx
        assert "Áp lực lên Báo cáo quản trị / Dashboard" in sale_ctx
        assert any("Ghi chú của Admin/Sale" in t for t in sale_tools)
        assert "Chẩn đoán nỗi đau khách hàng" in sale_tools
        # Không gọi thừa KPI Lead 7 ngày khi chỉ tra SĐT khách
        assert not any("KPI Lead 7 ngày" in t for t in sale_tools)

        # Kiểm thử parse JSON & ẩn SĐT khi tạo AI Đánh giá hằng ngày
        parsed = _parse_daily_review_json(
            '```json\n{"summary_status":"critical","headline":"Test","overview":["A"],"customer_insight":["B"],"process_sla":["C"],"actions":["D"]}\n```'
        )
        assert parsed["summary_status"] == "critical"
        assert parsed["overview"] == ["A"]
        assert parsed["actions"] == ["D"]

        msg_sample = _collect_recent_customer_messages_sample(db, now_vn, limit_convs=10)
        assert "Chị nhắn bên FB hỏi thêm học phí" in msg_sample
        assert p_test not in msg_sample  # không lộ SĐT trong mẫu insight

    print("ALL AI RAG TESTS PASSED!")


if __name__ == "__main__":
    test_ai_rag_pipeline()
