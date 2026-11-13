import os
import sys
import time
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, DimLead, FactLeadActivity, BotAutoReplyLog
from database.db import get_db
from backend.main import app
import backend.add_friend as af


class MockResp:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


def _build_mock_ctx(msg_status=200, msg_ok=True, tag_status=200, is_stranger=True):
    session = MagicMock()

    def fake_get(url, **kwargs):
        if "search_zalo_users" in url:
            return MockResp(
                200,
                {
                    "success": True,
                    "users": [
                        {
                            "uid": "u123",
                            "zalo_name": "Nguyen Van A",
                            "display_name": "Nguyen Van A",
                        }
                    ],
                },
            )
        if "/conversations/" in url:
            return MockResp(
                200,
                {
                    "id": "conv_999",
                    "from": {"id": "u123", "is_stranger": is_stranger},
                    "customers": [{"id": "cust_1"}],
                    "tags": [],
                },
            )
        return MockResp(200, {})

    def fake_post(url, **kwargs):
        if "send_request_friend" in url:
            return MockResp(200, {"success": True})
        if "/messages" in url:
            return MockResp(
                msg_status,
                {"success": msg_ok, "message": "" if msg_ok else "Blocked spam"},
            )
        if "/toggle_tag" in url:
            return MockResp(tag_status, {"success": tag_status == 200})
        return MockResp(200, {})

    session.get.side_effect = fake_get
    session.post.side_effect = fake_post

    return {
        "session": session,
        "page_id": "pzl_764881945463506349",
        "tags_map": {
            "data talk": {"id": 10, "text": "Data Talk", "color": "#000", "lighten_color": "#fff"},
            "đã add": {"id": 20, "text": "Đã add", "color": "#000", "lighten_color": "#fff"},
        },
    }


class TestAutoAddFriendLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

        db = cls.TestingSession()
        # Seed leads & activities:
        # 1. Lead matching Trần Đạt + TikTok + Data Talk, NO "Đã add"
        l1 = DimLead(
            id=1,
            customer_id="cust_lead_1",
            name="Nguyen Thi Lan",
            phone_number="0987654321",
            page_id="TikTok - Kế Toán",
            first_created_at=datetime(2026, 11, 12, 10, 0, 0),
        )
        a1 = FactLeadActivity(
            conversation_id="conv_fb_1",
            lead_id=1,
            assigned_users="Tran Dat",
            status_tag="Data Talk, Có thông tin",
            message_count=3,
        )
        # 2. Lead matching Trần Đạt + TikTok, ALREADY has "Đã add" tag on another conversation
        l2 = DimLead(
            id=2,
            customer_id="cust_lead_2",
            name="Pham Van Minh",
            phone_number="0912345678",
            page_id="TikTok - Kế Toán",
            first_created_at=datetime(2026, 11, 12, 11, 0, 0),
        )
        a2_src = FactLeadActivity(
            conversation_id="conv_fb_2",
            lead_id=2,
            assigned_users="Tran Dat",
            status_tag="Data Talk",
            message_count=2,
        )
        a2_zalo = FactLeadActivity(
            conversation_id="pzl_764881945463506349_conv2",
            lead_id=2,
            assigned_users="Tran Dat",
            status_tag="Đã add",
            message_count=1,
        )
        # 3. Lead assigned to Linh Bùi on Facebook page
        l3 = DimLead(
            id=3,
            customer_id="cust_lead_3",
            name="Le Thi Hoa",
            phone_number="0905112233",
            page_id="FB Eztech Academy",
            first_created_at=datetime(2026, 11, 12, 9, 0, 0),
        )
        a3 = FactLeadActivity(
            conversation_id="conv_fb_3",
            lead_id=3,
            assigned_users="Linh Bui",
            status_tag="Web",
            message_count=5,
        )
        db.add_all([l1, a1, l2, a2_src, a2_zalo, l3, a3])
        db.commit()
        db.close()

    def setUp(self):
        def override_get_db():
            db = self.TestingSession()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_execute_single_added_and_already_friend_and_partial(self):
        # 1. Stranger -> ADDED with message + tag
        ctx1 = _build_mock_ctx(is_stranger=True)
        st1, det1 = af._execute_pancake_add_friend_single(
            page=ctx1,
            target_dashboard="Eztech Consultant",
            phone="0987654321",
            friend_request_msg="Hi",
            inbox_msg="Hello",
            note_text="",
            tags=["Data Talk"],
            send_inbox_message=True,
            add_note=False,
        )
        self.assertEqual(st1, "ADDED")
        self.assertIn("đã nhắn tin chào", det1)
        self.assertIn("Data Talk", det1)

        # 2. Existing friend -> ALREADY_FRIEND (not ADDED)
        ctx2 = _build_mock_ctx(is_stranger=False)
        st2, det2 = af._execute_pancake_add_friend_single(
            page=ctx2,
            target_dashboard="Eztech Consultant",
            phone="0987654321",
            friend_request_msg="Hi",
            inbox_msg="Hello",
            note_text="",
            tags=["Đã add"],
            send_inbox_message=True,
            add_note=False,
        )
        self.assertEqual(st2, "ALREADY_FRIEND")
        self.assertIn("Đã là bạn bè sẵn", det2)

        # 3. Greeting message fails + unknown tag -> PARTIAL with explicit errors
        ctx3 = _build_mock_ctx(msg_status=500, msg_ok=False, is_stranger=True)
        st3, det3 = af._execute_pancake_add_friend_single(
            page=ctx3,
            target_dashboard="Eztech Consultant",
            phone="0987654321",
            friend_request_msg="Hi",
            inbox_msg="Hello",
            note_text="",
            tags=["TagKhongTonTai"],
            send_inbox_message=True,
            add_note=False,
        )
        self.assertEqual(st3, "PARTIAL")
        self.assertIn("lỗi nhắn tin", det3)
        self.assertIn("lỗi tag [TagKhongTonTai (không có trên Page)]", det3)

    def test_config_returns_page_tags_and_lead_filters(self):
        fake_pages = [
            {"id": "Eztech Consultant", "name": "Eztech Consultant", "badge": "Zalo Personal"},
            {"id": "Ann", "name": "Ann", "badge": "Zalo Personal"},
        ]
        fake_tags = {
            "Eztech Consultant": ["Web", "Data Talk", "Đã add"],
            "Ann": ["KH B2B", "Data Talk"],
        }
        with patch.object(af, "_fetch_pancake_pages_and_tags", return_value=(fake_pages, fake_tags)):
            r = self.client.get("/api/add-friend/config")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["tags_by_page"]["Eztech Consultant"], ["Web", "Data Talk", "Đã add"])
        self.assertEqual(data["tags_by_page"]["Ann"], ["KH B2B", "Data Talk"])
        self.assertIn("Trần Đạt", data["lead_filters"]["employees"])
        self.assertIn("Linh Bùi", data["lead_filters"]["employees"])
        self.assertIn("TikTok - Kế Toán", data["lead_filters"]["source_pages"])
        self.assertIn("Data Talk", data["lead_filters"]["lead_tags"])

    def test_leads_phones_filters_and_exclude_added_tag(self):
        # Exclude "Đã add" = True -> lead_2 (0912345678) MUST be excluded even when filtering Trần Đạt + Data Talk
        r1 = self.client.get(
            "/api/add-friend/leads-phones",
            params={
                "employee": "Trần Đạt",
                "source_page": "TikTok - Kế Toán",
                "tag": "Data Talk",
                "exclude_added_tag": "true",
            },
        )
        self.assertEqual(r1.status_code, 200)
        phones1 = [it["phone"] for it in r1.json()["items"]]
        self.assertEqual(phones1, ["0987654321"])

        # Exclude "Đã add" = False -> lead_2 appears too
        r2 = self.client.get(
            "/api/add-friend/leads-phones",
            params={
                "employee": "Trần Đạt",
                "source_page": "TikTok - Kế Toán",
                "tag": "Data Talk",
                "exclude_added_tag": "false",
            },
        )
        self.assertEqual(r2.status_code, 200)
        phones2 = sorted([it["phone"] for it in r2.json()["items"]])
        self.assertEqual(phones2, ["0912345678", "0987654321"])

    def test_dry_run_progress_and_active_endpoint(self):
        with patch.object(af, "SessionLocal", self.TestingSession):
            r_start = self.client.post(
                "/api/add-friend/start",
                json={
                    "campaign_name": "test_cam",
                    "page_name": "Eztech Consultant",
                    "items": [{"phone": "0987654321", "name": "Lan", "source": "TikTok", "nhu_cau": ""}],
                    "message_template": "Chào {name}",
                    "dry_run": True,
                },
            )
            self.assertEqual(r_start.status_code, 200)
            task_id = r_start.json()["task_id"]

            r_active = self.client.get("/api/add-friend/active")
            self.assertEqual(r_active.status_code, 200)
            self.assertEqual(r_active.json()["active"]["task_id"], task_id)

            # Wait up to 3s for dry_run background worker to finish
            st = None
            for _ in range(15):
                r_st = self.client.get(f"/api/add-friend/status/{task_id}")
                self.assertEqual(r_st.status_code, 200)
                st = r_st.json()
                if not st["is_running"]:
                    break
                time.sleep(0.2)

            self.assertIsNotNone(st)
            self.assertFalse(st["is_running"])
            self.assertEqual(st["processed"], 1)
            self.assertEqual(st["added_count"], 1)
            self.assertEqual(st["logs"][0]["status"], "DRY_RUN")


if __name__ == "__main__":
    unittest.main(verbosity=2)
