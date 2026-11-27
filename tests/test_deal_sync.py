"""Test logic map Page Zalo chăm sóc chính & Nguồn (FB/TikTok -> Other/ Web) cho Deal Win."""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.db import Base
from database.models import DealWin, DimLead, FactLeadActivity
from database.deal_sync import (
    DEFAULT_SOURCE_PAGE,
    _resolve_lead_items,
    find_lead_info_by_phone,
    sync_all_deals_with_dim_leads,
)
from etl.utils import extract_phone_number, resolve_phone


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


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


def test_company_hotlines_are_ignored():
    assert extract_phone_number("Liên hệ 0377024368 nhé") is None
    assert extract_phone_number("Hotline 0989279368 hoặc số em 0936001767") == "0936001767"
    phone, _ = resolve_phone({
        "phone_number": "0377024368",
        "messages": [{"role": "Khách hàng", "message": "0377024368"}],
    })
    assert phone is None


def test_missing_phone_zalo_student_fallback_and_collision_guards():
    db = _make_session()
    try:
        # Case 1: TRƯƠNG THỊ QUYÊN ("Mtq") — Eztech Consultant có SĐT nhưng chỉ 3 tin,
        # Hiền Minh Eztech có 75 tin (Đã là học viên) nhưng bị phone_number = NULL,
        # Eztech Phân Tích Dữ Liệu bị dính hotline 0377024368.
        l1 = DimLead(id=1, customer_id="c1", name="Mtq", phone_number="0936001767",
                     page_id="Eztech Consultant", first_created_at=datetime(2026, 11, 25, 15, 0))
        l2 = DimLead(id=2, customer_id="c2", name="Mtq", phone_number=None,
                     page_id="Hiền Minh Eztech", first_created_at=datetime(2026, 11, 16, 16, 50))
        l3 = DimLead(id=3, customer_id="c3", name="Mtq", phone_number="0377024368",
                     page_id="Eztech Phân Tích Dữ Liệu", first_created_at=datetime(2026, 11, 15, 22, 25))
        db.add_all([l1, l2, l3])
        db.add_all([
            FactLeadActivity(lead_id=1, conversation_id="pzl_u_764881945463506349_1",
                             status_tag="Đã là học viên,Web", assigned_users="Nguyen Gia Huy",
                             message_count=3, updated_at=datetime(2026, 11, 25, 15, 31)),
            FactLeadActivity(lead_id=2, conversation_id="pzl_u_131986891507252646_2",
                             status_tag="Data Talk,Đã là học viên", assigned_users="Hồng Minh",
                             message_count=75, updated_at=datetime(2026, 11, 18, 16, 31)),
            FactLeadActivity(lead_id=3, conversation_id="pzl_u_629476615535063343_3",
                             status_tag="Đã là học viên,Data Talk", assigned_users="Anh Trinh",
                             message_count=8, updated_at=datetime(2026, 11, 17, 12, 46)),
        ])

        # Case 2: Common 1-word name ("Dung" appears 6 times in DB) MUST NOT hijack another student's deal
        for idx in range(10, 16):
            db.add(DimLead(id=idx, customer_id=f"cd{idx}", name="Dung",
                           phone_number="0989678795" if idx == 10 else None,
                           page_id="Hiền Minh Eztech" if idx == 10 else "Tuấn Anh Data",
                           first_created_at=datetime(2026, 11, 10, 10, 0)))
        db.add_all([
            FactLeadActivity(lead_id=10, conversation_id="pzl_u_131986891507252646_10",
                             status_tag="Đã là học viên", assigned_users="Vượng Nguyễn",
                             message_count=35, updated_at=datetime(2026, 11, 12, 10, 0)),
            FactLeadActivity(lead_id=11, conversation_id="pzl_u_788602135347404973_11",
                             status_tag="Đã là học viên", assigned_users="Trần Đạt",
                             message_count=99, updated_at=datetime(2026, 11, 12, 10, 0)),
        ])

        # Case 3: Same-page guard — phone already has a conversation on Eztech Phân Tích Dữ Liệu
        db.add_all([
            DimLead(id=20, customer_id="ca20", name="Anna Lee", phone_number="0988464893",
                    page_id="Eztech Phân Tích Dữ Liệu", first_created_at=datetime(2026, 11, 1, 10, 0)),
            DimLead(id=21, customer_id="ca21", name="Anna Lee", phone_number=None,
                    page_id="Eztech Phân Tích Dữ Liệu", first_created_at=datetime(2026, 11, 2, 10, 0)),
        ])
        db.add_all([
            FactLeadActivity(lead_id=20, conversation_id="pzl_u_629476615535063343_20",
                             status_tag="Đã là học viên", assigned_users="Linh Bùi",
                             message_count=74, updated_at=datetime(2026, 11, 5, 10, 0)),
            FactLeadActivity(lead_id=21, conversation_id="pzl_u_629476615535063343_21",
                             status_tag="Đã là học viên", assigned_users="Khuất Cường",
                             message_count=91, updated_at=datetime(2026, 11, 5, 10, 0)),
        ])

        d1 = DealWin(id=101, full_name="TRƯƠNG THỊ QUYÊN", phone_number="0936001767",
                     timestamp=datetime(2026, 11, 17, 16, 52))
        d2 = DealWin(id=102, full_name="Nguyễn Thị Hoàng Dung", phone_number="0989678795",
                     timestamp=datetime(2026, 11, 12, 12, 0))
        d3 = DealWin(id=103, full_name="Nguyễn Thị Hồng Hạnh", phone_number="0988464893",
                     timestamp=datetime(2026, 11, 5, 12, 0))
        db.add_all([d1, d2, d3])
        db.commit()

        # Verify find_lead_info_by_phone
        lid, is_stu, care, _, page_id, src = find_lead_info_by_phone(
            "0936001767", db, full_name="TRƯƠNG THỊ QUYÊN", deal_timestamp=datetime(2026, 11, 17, 16, 52)
        )
        assert lid == 2
        assert is_stu is True
        assert care == "Hồng Minh"
        assert page_id == "Hiền Minh Eztech"
        assert src == DEFAULT_SOURCE_PAGE

        # Verify sync_all_deals_with_dim_leads
        sync_all_deals_with_dim_leads(db, full_scan=True)
        db.refresh(d1)
        db.refresh(d2)
        db.refresh(d3)

        assert d1.dim_lead_id == 2
        assert d1.page_id == "Hiền Minh Eztech"
        assert d1.care_by == "Hồng Minh"

        # Common 1-word name "Dung" rejected -> keeps Hiền Minh Eztech / Vượng Nguyễn
        assert d2.page_id == "Hiền Minh Eztech"
        assert d2.care_by == "Vượng Nguyễn"

        # Same-page guard -> keeps Linh Bùi (74 msgs), ignores other Anna Lee on same page
        assert d3.dim_lead_id == 20
        assert d3.care_by == "Linh Bùi"
    finally:
        db.close()


def test_multiword_zalo_name_collision_and_coassigned_care_by_resolution():
    db = _make_session()
    try:
        # 1. Multi-word collision ("Phan Lan"):
        # Học viên cũ tháng 8 có Zalo thiếu SĐT (57 tin, Trần Đạt, updated_at mới do backfill),
        # Học viên mới tháng 11 ("0985368357") đã có Zalo 54 tin với Khuất Cường -> PHẢI lấy Khuất Cường, không bị trộn sang Trần Đạt.
        db.add_all([
            DimLead(id=30, customer_id="pl_aug_phone", name="Phan Lan", phone_number="0917954559",
                    page_id="Eztech Phân Tích Dữ Liệu", first_created_at=datetime(2026, 8, 13, 15, 0)),
            DimLead(id=31, customer_id="pl_aug_nophone", name="Phan Lan", phone_number=None,
                    page_id="Hiền Minh Eztech", first_created_at=datetime(2026, 8, 23, 22, 0)),
            DimLead(id=32, customer_id="pl_nov", name="Phan Lan", phone_number="0985368357",
                    page_id="Eztech Phân Tích Dữ Liệu", first_created_at=datetime(2026, 10, 30, 15, 57)),
        ])
        db.add_all([
            FactLeadActivity(
                lead_id=31, conversation_id="pzl_u_131986891507252646_31",
                status_tag="Đã là học viên,Công Nợ", assigned_users="Trần Đạt", message_count=57,
                tag_timeline=[{"tag": "Đã là học viên", "action": "add", "tagged_at": "2026-08-23 22:07:55", "editor": "Trần Đạt"}],
                updated_at=datetime(2026, 11, 10, 10, 0),
            ),
            FactLeadActivity(
                lead_id=32, conversation_id="pzl_u_629476615535063343_32",
                status_tag="Đã là học viên,Mess FB", assigned_users="Khuất Cường", message_count=54,
                tag_timeline=[{"tag": "Đã là học viên", "action": "add", "tagged_at": "2026-11-26 17:27:20", "editor": "Khuất Cường"}],
                updated_at=datetime(2026, 11, 26, 18, 0),
            ),
        ])

        # 2. Co-assigned "Anh Trinh, Hồng Minh" + "Trần, Nguyen Gia Huy" + "Hiền Minh Lý, Nguyễn Thị Thanh Mai" (tag_timeline tie-break)
        db.add_all([
            DimLead(id=40, customer_id="co40", name="Tư Vương", phone_number="0979240119",
                    page_id="Hiền Minh Eztech", first_created_at=datetime(2026, 11, 25, 14, 30)),
            DimLead(id=41, customer_id="co41", name="Khanhhq", phone_number="898502253",  # sẽ khớp SĐT mất số 0 đầu
                    page_id="Tuấn Anh Data", first_created_at=datetime(2026, 11, 15, 10, 0)),
        ])
        # Lưu SĐT chuẩn có số 0 trong DimLead để test bù số 0 đầu từ DealWin ("898502253" -> "0898502253")
        db.query(DimLead).filter_by(id=41).update({"phone_number": "0898502253"})
        db.add_all([
            FactLeadActivity(
                lead_id=40, conversation_id="pzl_u_131986891507252646_40",
                status_tag="Đã là học viên,Công Nợ",
                assigned_users="Hiền Minh Lý, Nguyễn Thị Thanh Mai",
                message_count=58,
                tag_timeline=[
                    {"tag": "Có thông tin", "action": "add", "tagged_at": "2026-11-25 14:34:36", "editor": "Hiền Minh Lý"},
                    {"tag": "Đồng ý học", "action": "add", "tagged_at": "2026-11-25 15:13:18", "editor": "Nguyễn Thị Thanh Mai"},
                    {"tag": "Đã là học viên", "action": "add", "tagged_at": "2026-11-26 10:04:12", "editor": "Nguyễn Thị Thanh Mai"},
                ],
            ),
            FactLeadActivity(
                lead_id=41, conversation_id="pzl_u_788602135347404973_41",
                status_tag="Đã là học viên",
                assigned_users="Anh Trinh, Trần, Liên Vũ",
                message_count=91,
            ),
        ])

        dw_phan_lan = DealWin(id=201, full_name="Phan Lan", phone_number="0985368357",
                              timestamp=datetime(2026, 11, 26, 17, 17, 49))
        dw_tu_vuong = DealWin(id=202, full_name="Vương Thị Tư", phone_number="0979240119",
                              timestamp=datetime(2026, 11, 26, 10, 5, 50))
        dw_no_zero = DealWin(id=203, full_name="Trần Thị Mỹ Huyền", phone_number="898502253",
                             timestamp=datetime(2026, 11, 15, 10, 37, 38))
        db.add_all([dw_phan_lan, dw_tu_vuong, dw_no_zero])
        db.commit()

        sync_all_deals_with_dim_leads(db, full_scan=True)
        db.refresh(dw_phan_lan)
        db.refresh(dw_tu_vuong)
        db.refresh(dw_no_zero)

        # Phan Lan: giữ đúng Khuất Cường / Eztech Phân Tích Dữ Liệu (lead 32), không bốc nhầm lead 31 của tháng 8
        assert dw_phan_lan.dim_lead_id == 32
        assert dw_phan_lan.page_id == "Eztech Phân Tích Dữ Liệu"
        assert dw_phan_lan.care_by == "Khuất Cường"

        # Vương Thị Tư: phân xử giữa Hiền Minh Lý và Nguyễn Thị Thanh Mai dựa vào thời điểm gắn tag chốt mới nhất
        assert dw_tu_vuong.care_by == "Nguyễn Thị Thanh Mai"

        # Bù số 0 đầu SĐT ("898502253" -> "0898502253") và ưu tiên "Anh Trinh" khi có Anh Trinh cùng nhân viên khác
        assert dw_no_zero.phone_number == "0898502253"
        assert dw_no_zero.dim_lead_id == 41
        assert dw_no_zero.care_by == "Anh Trinh"

        # Giữ nguyên nhân viên "Trần" và chỉ lấy đoạn hội thoại nhiều tin nhắn nhất làm đoạn chính (không cộng dồn nhiều page)
        from database.deal_sync import normalize_sale_name, pick_best_assigned_user
        assert normalize_sale_name("Trần") == "Trần"
        assert pick_best_assigned_user([
            {"lead_id": 1, "page_id": "Tuấn Anh Data", "conversation_id": "pzl_u_1_1", "assigned": "Trần", "message_count": 40, "status_tag": "Đã là học viên"},
            {"lead_id": 2, "page_id": "Eztech Consultant", "conversation_id": "pzl_u_2_2", "assigned": "Linh Bùi", "message_count": 25, "status_tag": ""},
            {"lead_id": 3, "page_id": "Anh Kế toán làm Data (Facebook)", "conversation_id": "514400205095512_3", "assigned": "Linh Bùi", "message_count": 25, "status_tag": ""},
        ]) == "Trần"
        # Nhiều sale trên cùng đoạn hội thoại chính -> ưu tiên sale nhắn nhiều nhất rồi mới đến thời điểm gắn tag
        assert pick_best_assigned_user([{
            "lead_id": 9, "page_id": "Hiền Minh Eztech", "conversation_id": "pzl_u_1319_9",
            "assigned": "Linh Bùi, Bảo Ngọc", "message_count": 50, "status_tag": "Đã là học viên",
            "messages": [
                {"role": "Admin", "sender_name": "Bảo Ngọc"},
                {"role": "Admin", "sender_name": "Bảo Ngọc"},
                {"role": "Admin", "sender_name": "Linh Bùi"},
            ],
            "tag_timeline": [{"tag": "Đã là học viên", "action": "add", "tagged_at": "2026-11-26 10:00:00", "editor": "Linh Bùi"}],
        }]) == "Bảo Ngọc"
    finally:
        db.close()


if __name__ == "__main__":
    test_only_fb_or_tiktok_returns_no_zalo_care_page()
    test_picks_highest_msg_zalo_and_highest_msg_source()
    test_only_zalo_or_empty_defaults_source_to_other_web()
    test_company_hotlines_are_ignored()
    test_missing_phone_zalo_student_fallback_and_collision_guards()
    test_multiword_zalo_name_collision_and_coassigned_care_by_resolution()
    print("OK")
