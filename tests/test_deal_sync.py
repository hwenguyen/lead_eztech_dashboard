"""Test logic map Page Zalo chăm sóc chính & Nguồn (FB/TikTok -> Other/ Web) cho Deal Win."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.deal_sync import DEFAULT_SOURCE_PAGE, _resolve_lead_items


def test_only_fb_or_tiktok_returns_no_zalo_care_page():
    items = [{
        "lead_id": 1,
        "page_id": "Anh Kế toán làm Data (Facebook)",
        "conversation_id": "514400205095512_28443307731927507",
        "status_tag": "Đã add",
        "assigned": "Linh Bùi",
        "message_count": 18,
    }]
    lead_id, is_student, care_by, lead_tag, page_id, source_page = _resolve_lead_items(items)
    assert lead_id == 1
    assert is_student is False
    assert care_by == "Linh Bùi"
    assert lead_tag == "Đã add"
    assert page_id is None
    assert source_page == "Anh Kế toán làm Data (Facebook)"


def test_picks_highest_msg_zalo_and_highest_msg_source():
    items = [
        {
            "lead_id": 10,
            "page_id": "Anh Kế toán làm Data (Facebook)",
            "conversation_id": "514400205095512_1",
            "status_tag": "",
            "assigned": "",
            "message_count": 10,
        },
        {
            "lead_id": 11,
            "page_id": "Anh Kế toán làm Data (TikTok)",
            "conversation_id": "tt_0:1:719:1",
            "status_tag": "",
            "assigned": "",
            "message_count": 25,
        },
        {
            "lead_id": 12,
            "page_id": "Eztech Consultant",
            "conversation_id": "pzl_u_7648_1",
            "status_tag": "",
            "assigned": "",
            "message_count": 3,
        },
        {
            "lead_id": 13,
            "page_id": "Eztech Phân Tích Dữ Liệu",
            "conversation_id": "pzl_u_6294_1",
            "status_tag": "Đã là học viên",
            "assigned": "Trần Đạt",
            "message_count": 69,
        },
    ]
    _, is_student, care_by, _, page_id, source_page = _resolve_lead_items(items)
    assert is_student is True
    assert care_by == "Trần Đạt"
    assert page_id == "Eztech Phân Tích Dữ Liệu"
    assert source_page == "Anh Kế toán làm Data (TikTok)"


def test_only_zalo_or_empty_defaults_source_to_other_web():
    zalo_only = [{
        "lead_id": 20,
        "page_id": "Hiền Minh Eztech",
        "conversation_id": "pzl_u_1319_1",
        "status_tag": "Đã là học viên",
        "assigned": "Hiền Minh Lý",
        "message_count": 50,
    }]
    assert _resolve_lead_items(zalo_only)[4:] == ("Hiền Minh Eztech", DEFAULT_SOURCE_PAGE)
    assert _resolve_lead_items([]) == (None, False, None, None, None, "Other/ Web")


if __name__ == "__main__":
    test_only_fb_or_tiktok_returns_no_zalo_care_page()
    test_picks_highest_msg_zalo_and_highest_msg_source()
    test_only_zalo_or_empty_defaults_source_to_other_web()
    print("OK")
