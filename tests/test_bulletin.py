"""
Unit & Integration tests cho Trang Bản Tin & Công Việc:
1. Lọc 3 sếp (Ann, TRẦN HÀ TUẤN ANH, Hiền Minhh) & Gom chuỗi tin liên tiếp 3 phút (A5) + dừng sớm last_seen_message_ids
2. Đánh dấu đã đọc, Nhắc hẹn & Checklist riêng tư theo nhân sự, Admin xem & phân việc hàng loạt cho nhiều nhân sự
3. Fix #1: Retry cap & backoff nhắc đúng giờ + không làm thức Neon khi nhân sự chưa map Zalo
4. Fix #4: Soft-delete checklist lặp hôm nay không hồi sinh + không ghi DB khi duyệt ngày xa
5. Fix #5: Cắt gọn tin nhắn Zalo <= 1800 ký tự & tôn trọng active_weekdays
6. A2 (AI tách việc), A3 (Rollover việc hôm qua), A4 (Nhắc hẹn lặp lại hàng tuần)
"""

import json
import os
import sys
import unittest
from datetime import timedelta
from unittest.mock import patch

os.environ["DATABASE_URL"] = "postgresql://test:test@127.0.0.1:5432/test_bulletin"
os.environ["SKIP_ENSURE_SCHEMA"] = "false"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.db import Base
from database.models import (
    AppUser,
    BulletinPost,
    DimLead,
    EztechStaff,
    get_vn_now,
)
from backend.auth import hash_password
from backend.bulletin import (
    ChecklistCreateRequest,
    ReminderCreateRequest,
    ReminderUpdateRequest,
    RolloverChecklistRequest,
    ai_extract_tasks_from_post,
    clear_bulletin_meta_cache,
    create_checklist,
    create_reminder,
    delete_checklist,
    get_pending_rollover_items,
    list_checklists,
    list_reminders,
    rollover_pending_items,
    update_reminder,
)
from backend.bulletin_notifier import (
    MAX_ZALO_MSG_CHARS,
    compute_next_exact_due_at,
    dispatch_daily_digest,
    dispatch_due_exact_reminders,
)
from etl.bulletin_sync import match_boss_sender, sync_bulletin_from_group


class BulletinSystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    def setUp(self):
        clear_bulletin_meta_cache()
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.TestingSessionLocal()

        pw_hash, salt = hash_password("123456")
        self.admin = AppUser(
            username="admin",
            password_hash=pw_hash,
            salt=salt,
            full_name="Admin EzTech",
            department="Admin",
            role="admin",
            is_default_password=False,
            is_active=True,
        )
        self.staff_a = AppUser(
            username="nv_a",
            password_hash=pw_hash,
            salt=salt,
            full_name="Nguyễn Văn A",
            department="Consultant",
            role="staff",
            is_default_password=False,
            is_active=True,
        )
        self.staff_b = AppUser(
            username="nv_b",
            password_hash=pw_hash,
            salt=salt,
            full_name="Trần Thị B",
            department="Consultant",
            role="staff",
            is_default_password=False,
            is_active=True,
        )
        self.db.add_all([self.admin, self.staff_a, self.staff_b])
        self.db.commit()
        self.db.refresh(self.admin)
        self.db.refresh(self.staff_a)
        self.db.refresh(self.staff_b)

        self.staff_a_zalo = EztechStaff(
            user_id=self.staff_a.id,
            full_name="Nguyễn Văn A",
            phone_number="0901234567",
            zalo_conversation_id="pzl_u_764881945463506349_111111",
            zalo_display_name="Văn A EzTech",
            receive_daily_digest=True,
            is_active=True,
        )
        self.db.add(self.staff_a_zalo)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_match_boss_sender_exact_and_safe(self):
        self.assertEqual(match_boss_sender({"from": {"name": "Ann"}})[0], "ann")
        self.assertEqual(match_boss_sender({"from": {"name": "TRẦN HÀ TUẤN ANH"}})[0], "tuan_anh")
        self.assertEqual(match_boss_sender({"from": {"name": "Hiền Minhh"}})[0], "hien_minh")
        self.assertIsNone(match_boss_sender({"from": {"name": "Hannah Nguyen"}}))
        self.assertIsNone(match_boss_sender({"from": {"name": "Nguyễn Văn A"}}))

    def test_sync_grouping_and_early_stop(self):
        fake_convs = [
            {
                "id": "pzl_g_764881945463506349_99999",
                "customers": [{"name": "EzTech -Data & Finance Service"}],
            }
        ]
        fake_messages_page = {
            "success": True,
            "messages": [
                {
                    "id": "msg_ann_2",
                    "message": "Nhớ gửi trước 16h nhé mọi người",
                    "from": {"id": "u_ann", "name": "Ann"},
                    "inserted_at": "2026-11-25T02:01:00",
                },
                {
                    "id": "msg_ann_1",
                    "message": "Thông báo họp team 14h hôm nay",
                    "from": {"id": "u_ann", "name": "Ann"},
                    "inserted_at": "2026-11-25T02:00:00",
                },
                {
                    "id": "msg_tuan_anh_1",
                    "message": "Cập nhật KPI tuần mới nhé cả nhà",
                    "from": {"id": "u_ta", "name": "TRẦN HÀ TUẤN ANH"},
                    "inserted_at": "2026-11-25T03:00:00",
                },
                {
                    "id": "msg_staff_skip",
                    "message": "Dạ em nhận thông tin ạ",
                    "from": {"id": "u_nv", "name": "Nguyễn Văn A"},
                    "inserted_at": "2026-11-25T04:05:00",
                },
            ],
        }

        with patch("etl.bulletin_sync.get_token_for_page", return_value="dummy_token"), \
             patch("etl.pancake_client.PancakeClient.list_page_conversations", return_value=fake_convs), \
             patch("etl.pancake_client.PancakeClient.fetch_conversation_messages_page", return_value=fake_messages_page):
            res = sync_bulletin_from_group(db=self.db, max_pages=1)
            res2 = sync_bulletin_from_group(db=self.db, max_pages=3)

        self.assertTrue(res["success"])
        self.assertEqual(res["inserted"], 2)
        self.assertEqual(res["merged"], 1)
        self.assertEqual(res2["inserted"], 0)
        self.assertEqual(res2["merged"], 0)
        ann_post = self.db.query(BulletinPost).filter(BulletinPost.boss_key == "ann").first()
        self.assertIn("Thông báo họp team 14h hôm nay", ann_post.content)
        self.assertIn("Nhớ gửi trước 16h nhé mọi người", ann_post.content)
        self.assertIsNone(ann_post.raw_payload)
        self.assertEqual(self.db.query(DimLead).count(), 0)

    def test_privacy_multi_assign_soft_delete_rollover_and_recurrence(self):
        today = get_vn_now().strftime("%Y-%m-%d")
        yesterday = (get_vn_now() - timedelta(days=1)).strftime("%Y-%m-%d")
        far_future = (get_vn_now() + timedelta(days=10)).strftime("%Y-%m-%d")

        # Admin phân 1 checklist lặp hàng ngày cho CẢ 2 nhân sự A và B cùng lúc
        cl_multi = create_checklist(
            ChecklistCreateRequest(
                title="SOP đầu ngày",
                checklist_date=yesterday,
                items=["Check lead mới", "Kiểm tra tin Zalo"],
                owner_user_ids=[self.staff_a.id, self.staff_b.id],
                is_recurring_daily=True,
            ),
            current_user=self.admin,
            db=self.db,
        )
        self.assertEqual(cl_multi["created_count"], 2)

        # Duyệt ngày xa (+10 ngày) KHÔNG tự tạo bản sao checklist vào DB
        far_cls = list_checklists(checklist_date=far_future, current_user=self.staff_a, db=self.db)
        self.assertEqual(len(far_cls["items"]), 0)

        # Mở hôm nay -> tự sinh bản sao cho staff_a
        today_cls = list_checklists(checklist_date=today, current_user=self.staff_a, db=self.db)
        self.assertEqual(len(today_cls["items"]), 1)
        today_cl_id = today_cls["items"][0]["id"]

        # Xóa bản sao hôm nay -> soft-delete, mở lại hôm nay KHÔNG hồi sinh
        delete_checklist(today_cl_id, current_user=self.staff_a, db=self.db)
        today_cls_after = list_checklists(checklist_date=today, current_user=self.staff_a, db=self.db)
        self.assertEqual(len(today_cls_after["items"]), 0)

        # A3: Rollover các việc chưa xong từ hôm qua của staff_a sang hôm nay
        pending_roll = get_pending_rollover_items(target_date=today, current_user=self.staff_a, db=self.db)
        self.assertEqual(pending_roll["count"], 2)
        roll_res = rollover_pending_items(RolloverChecklistRequest(target_date=today), current_user=self.staff_a, db=self.db)
        self.assertEqual(roll_res["moved_count"], 2)
        pending_roll_after = get_pending_rollover_items(target_date=today, current_user=self.staff_a, db=self.db)
        self.assertEqual(pending_roll_after["count"], 0)

        # A4: Nhắc hẹn lặp hàng tuần -> đánh dấu completed tự sinh kỳ tuần sau
        rem = create_reminder(
            ReminderCreateRequest(
                title="Họp giao ban tuần",
                remind_at=f"{today}T09:00",
                recurrence_rule="weekly",
            ),
            current_user=self.staff_a,
            db=self.db,
        )
        upd = update_reminder(
            rem["id"],
            ReminderUpdateRequest(status="completed"),
            current_user=self.staff_a,
            db=self.db,
        )
        self.assertIn("next_reminder", upd)
        expected_next_date = (get_vn_now() + timedelta(days=7)).strftime("%Y-%m-%d")
        self.assertEqual(upd["next_reminder"]["due_date"], expected_next_date)
        self.assertEqual(upd["next_reminder"]["status"], "pending")

        # Staff B không thể xem nhắc hẹn của Staff A
        b_rems = list_reminders(status_filter="all", owner_user_id=self.staff_a.id, current_user=self.staff_b, db=self.db)
        self.assertEqual(b_rems["total"], 0)

    def test_exact_worker_no_neon_spin_and_zalo_truncation(self):
        today = get_vn_now().strftime("%Y-%m-%d")
        now_vn = get_vn_now()

        # Staff B chưa có Zalo conversation_id tạo nhắc đúng giờ quá hạn -> compute_next_exact_due_at PHẢI trả None
        create_reminder(
            ReminderCreateRequest(
                title="Nhắc của NV B chưa map Zalo",
                remind_at=(now_vn - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M"),
                notify_exact_time=True,
            ),
            current_user=self.staff_b,
            db=self.db,
        )
        self.assertIsNone(compute_next_exact_due_at(self.db, now_vn=now_vn))

        # Staff A có Zalo -> lỗi gửi -> backoff 15p (không poll mỗi 60s)
        create_reminder(
            ReminderCreateRequest(
                title="Nhắc của NV A bị lỗi gửi",
                remind_at=(now_vn - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M"),
                notify_exact_time=True,
            ),
            current_user=self.staff_a,
            db=self.db,
        )
        with patch("backend.bulletin_notifier.get_token_for_page", return_value="dummy"), \
             patch("etl.pancake_client.PancakeClient.send_message", return_value={"success": False, "message": "Zalo err"}):
            r1 = dispatch_due_exact_reminders(db=self.db, dry_run=False)
            self.assertEqual(r1["failed"], 1)
            next_wake = compute_next_exact_due_at(self.db, now_vn=now_vn)
            self.assertIsNotNone(next_wake)
            self.assertGreater(next_wake, now_vn + timedelta(minutes=10))

        # Cắt gọn tin nhắn Zalo <= 1800 ký tự khi có quá nhiều đầu việc
        many_items = [f"Hạng mục công việc số {i} cần xử lý chi tiết cho khách hàng EzTech" for i in range(1, 55)]
        create_checklist(
            ChecklistCreateRequest(title="Checklist dài", checklist_date=today, items=many_items),
            current_user=self.staff_a,
            db=self.db,
        )
        dry_res = dispatch_daily_digest(db=self.db, slot="11h", target_date=today, dry_run=True)
        preview = dry_res["results"][0]["preview_message"]
        self.assertLessEqual(len(preview), MAX_ZALO_MSG_CHARS)
        self.assertIn("hạng mục khác", preview)

    def test_ai_extract_tasks_from_post(self):
        post = BulletinPost(
            pancake_message_id="msg_ai_1",
            group_conversation_id="pzl_g_test",
            group_name="EzTech -Data & Finance Service",
            sender_name="Ann",
            boss_key="ann",
            boss_display_name="Ann",
            title="Chuẩn bị file khóa học mới",
            content="Trước 16h hôm nay các bạn kiểm tra danh sách học viên và gửi link Zoom nhé",
            posted_at=get_vn_now(),
        )
        self.db.add(post)
        self.db.commit()
        self.db.refresh(post)

        fake_ai_json = json.dumps({
            "summary": "Sếp Ann yêu cầu chuẩn bị danh sách học viên và link Zoom trước 16h",
            "checklist_title": "Chuẩn bị lớp học hôm nay",
            "checklist_items": ["Kiểm tra danh sách học viên", "Gửi link Zoom cho lớp"],
            "suggested_reminder": {
                "title": "Hoàn tất gửi link Zoom trước 16h",
                "description": "Hạn chót từ sếp Ann",
                "remind_at": "2026-11-25T15:30",
                "priority": "high",
            },
        }, ensure_ascii=False)

        with patch("backend.ai_rag.get_gemini_api_key", return_value="fake_key"), \
             patch("backend.ai_rag.call_gemini_generate", return_value=(fake_ai_json, "gemini-3-flash-preview", False)):
            out = ai_extract_tasks_from_post(post.id, current_user=self.staff_a, db=self.db)

        self.assertEqual(len(out["checklist_items"]), 2)
        self.assertEqual(out["suggested_reminder"]["priority"], "high")
        self.assertEqual(out["suggested_reminder"]["remind_at"], "2026-11-25T15:30")


if __name__ == "__main__":
    unittest.main()
