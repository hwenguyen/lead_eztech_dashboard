"""Kiểm thử ETL Auto-Learn (ẩn PII, chống trùng hội thoại, giới hạn chunk, khung giờ đêm)."""
import os
import sys
import json
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite:///./leads_data.db"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import (
    Base,
    DimLead,
    FactLeadActivity,
    RawConversation,
    KnowledgeChunk,
    AppConfig,
    get_vn_now,
)
from etl.ai_autolearn import (
    clean_and_mask_messages,
    run_auto_learn,
    AUTOLEARN_DOC_NAME,
    SEEN_CONVS_KEY,
)


def test_clean_and_mask_messages():
    msgs = [
        {"role": "Khách hàng", "message": "<div>SĐT chị là 0988777666, zalo nhé</div>"},
        {"role": "Admin", "message": "<div>Dạ vâng chị nhắn em thêm +84912345678 ạ</div>"},
    ]
    out = clean_and_mask_messages(msgs)
    assert "0988777666" not in out
    assert "84912345678" not in out
    assert "[SĐT]" in out


def test_run_auto_learn_dedup_and_persist():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=eng)
    Sess = sessionmaker(bind=eng)

    with Sess() as db:
        db.add(AppConfig(config_key="GEMINI_API_KEY", config_value="test_key_123456"))
        lead = DimLead(customer_id="c_learn_1", name="Chị Hoa", phone_number="0912345678", page_id="Tuấn Anh Data")
        db.add(lead)
        db.flush()
        db.add(
            FactLeadActivity(
                lead_id=lead.id,
                conversation_id="conv_learn_1",
                status_tag="Tiktok HV TCKT,Đã là học viên",
                updated_at=get_vn_now(),
            )
        )
        db.add(
            RawConversation(
                pancake_id="conv_learn_1",
                page_id="Tuấn Anh Data",
                payload={
                    "messages": [
                        {"role": "Khách hàng", "message": "<div>Chị hay tăng ca tối sợ không theo kịp</div>"},
                        {"role": "Admin", "message": "<div>Mỗi buổi đều có record xem lại chị ơi</div>"},
                        {"role": "Khách hàng", "message": "<div>Số chị 0912345678 nhé</div>"},
                        {"role": "Admin", "message": "<div>Dạ em kết bạn Zalo gửi lộ trình cho mình ạ</div>"},
                    ]
                },
            )
        )
        db.commit()

        fake_cases = ["Tình huống: Khách sợ tăng ca không kịp lịch.\nCách Sale xử lý: Nhấn mạnh có record xem lại và support 1-1."]
        with patch("etl.ai_autolearn._call_gemini_extract", return_value=fake_cases), patch(
            "etl.ai_autolearn._embed_batch", return_value=[[0.1] * 768]
        ):
            added1 = run_auto_learn(db, days_back=2, max_convs=10, force=True)
            assert added1 == 1

            # Lần chạy thứ 2 không học trùng conv_learn_1
            added2 = run_auto_learn(db, days_back=2, max_convs=10, force=True)
            assert added2 == 0

        chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.doc_name == AUTOLEARN_DOC_NAME).all()
        assert len(chunks) == 1
        assert chunks[0].category == "sale"
        seen_cfg = db.query(AppConfig).filter(AppConfig.config_key == SEEN_CONVS_KEY).first()
        assert "conv_learn_1" in json.loads(seen_cfg.config_value)

    print("ALL AUTO-LEARN TESTS PASSED!")


if __name__ == "__main__":
    test_clean_and_mask_messages()
    test_run_auto_learn_dedup_and_persist()
