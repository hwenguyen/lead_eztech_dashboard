"""
Test for broadcast multi-tag filtering and exclude_students logic.
"""
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.broadcast import (
    BroadcastPreviewRequest,
    BroadcastStartRequest,
    _BROADCAST_TASKS,
    get_active_broadcast,
    stop_broadcast,
)


def test_broadcast_requests_schema():
    # 1. Test single string tag
    req1 = BroadcastPreviewRequest(tag="Remind", exclude_students=True)
    assert req1.tag == "Remind"
    assert req1.exclude_students is True

    # 2. Test multi-tag as list
    req2 = BroadcastPreviewRequest(tag=["Remind", "Quan tâm sâu"], exclude_students=False)
    assert isinstance(req2.tag, list)
    assert len(req2.tag) == 2
    assert req2.exclude_students is False

    # 3. Test tags parameter
    req3 = BroadcastPreviewRequest(tags=["TagA", "TagB"])
    assert req3.tags == ["TagA", "TagB"]
    assert req3.exclude_students is True

    # 4. Test start broadcast request
    start_req = BroadcastStartRequest(
        campaign_name="test_campaign",
        template="Hello {name}",
        tags=["Remind"],
        exclude_students=True,
        limit=50
    )
    assert start_req.tags == ["Remind"]
    assert start_req.exclude_students is True
    print("[PASS] test_broadcast_requests_schema passed!")


def test_active_broadcast_and_stop():
    _BROADCAST_TASKS.clear()
    assert get_active_broadcast() is None

    _BROADCAST_TASKS["task_test_1"] = {
        "task_id": "task_test_1",
        "campaign_name": "camp_test",
        "is_running": True,
        "total": 10,
        "processed": 3,
        "success": 3,
        "failed": 0,
        "dry_run": False,
        "current_recipient": "Testing...",
        "started_at": "2026-11-11 11:00:00",
        "finished_at": None,
        "logs": [],
    }
    active = get_active_broadcast()
    assert active is not None
    assert active.task_id == "task_test_1"
    assert active.is_running is True

    stop_res = stop_broadcast("all")
    assert stop_res["status"] == "STOPPING"
    assert _BROADCAST_TASKS["task_test_1"]["is_running"] is False
    assert get_active_broadcast() is None
    _BROADCAST_TASKS.clear()
    print("[PASS] test_active_broadcast_and_stop passed!")


def test_broadcast_image_payload_validation():
    import base64
    from backend.broadcast import BroadcastImagePayload, decode_broadcast_images

    sample_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfakeimg").decode("ascii")

    # Data URL prefix stripped cleanly
    decoded = decode_broadcast_images([
        BroadcastImagePayload(
            filename="banner.png",
            content_type="image/png",
            data_base64=f"data:image/png;base64,{sample_b64}",
        )
    ])
    assert len(decoded) == 1
    assert decoded[0]["filename"] == "banner.png"
    assert decoded[0]["content_type"] == "image/png"
    assert decoded[0]["bytes"] == b"\x89PNG\r\n\x1a\nfakeimg"

    # Invalid MIME
    try:
        decode_broadcast_images([
            BroadcastImagePayload(filename="doc.pdf", content_type="application/pdf", data_base64=sample_b64)
        ])
        assert False, "Expected ValueError for invalid MIME"
    except ValueError:
        pass

    # Corrupt base64
    try:
        decode_broadcast_images([
            BroadcastImagePayload(filename="bad.jpg", content_type="image/jpeg", data_base64="!!!not-b64!!!")
        ])
        assert False, "Expected ValueError for corrupt base64"
    except ValueError:
        pass

    # > 5MB image rejected
    oversize_b64 = base64.b64encode(b"x" * (5 * 1024 * 1024 + 1)).decode("ascii")
    try:
        decode_broadcast_images([
            BroadcastImagePayload(filename="big.jpg", content_type="image/jpeg", data_base64=oversize_b64)
        ])
        assert False, "Expected ValueError for > 5MB image"
    except ValueError:
        pass

    # > 10 images rejected
    try:
        decode_broadcast_images([
            BroadcastImagePayload(filename=f"{i}.png", content_type="image/png", data_base64=sample_b64)
            for i in range(11)
        ])
        assert False, "Expected ValueError for > 10 images"
    except ValueError:
        pass

    print("[PASS] test_broadcast_image_payload_validation passed!")


def test_start_broadcast_empty_template_requires_images():
    import base64
    from unittest.mock import patch
    from fastapi import HTTPException, BackgroundTasks
    from backend.broadcast import BroadcastImagePayload, start_broadcast

    # Both empty -> 400
    req_empty = BroadcastStartRequest(campaign_name="c1", template="   ", images=[], dry_run=True)
    try:
        start_broadcast(req_empty, BackgroundTasks())
        assert False, "Expected HTTPException 400 when both template and images are empty"
    except HTTPException as exc:
        assert exc.status_code == 400

    # Empty template + valid image -> allowed (dry_run)
    sample_b64 = base64.b64encode(b"imgdata").decode("ascii")
    req_img_only = BroadcastStartRequest(
        campaign_name="c2",
        template="",
        send_mode="images_only",
        images=[BroadcastImagePayload(filename="a.jpg", content_type="image/jpeg", data_base64=sample_b64)],
        dry_run=True,
    )
    with patch("backend.broadcast.threading.Thread") as mock_thread:
        res = start_broadcast(req_img_only, BackgroundTasks())
        mock_thread.return_value.start.assert_called_once()
    assert res["status"] == "STARTED"
    assert res["campaign_name"] == "c2"
    _BROADCAST_TASKS.clear()
    print("[PASS] test_start_broadcast_empty_template_requires_images passed!")


def test_channel_content_id_batch_limits():
    from backend.broadcast import _get_max_content_ids_for_channel

    assert _get_max_content_ids_for_channel("fb_514400205095512", "514400205095512_123", is_zalo=False) == 30
    assert _get_max_content_ids_for_channel("514400205095512", "514400205095512_123", is_zalo=False) == 30
    assert _get_max_content_ids_for_channel("pzl_629476615535063343", "pzl_u_123", is_zalo=True) == 30
    assert _get_max_content_ids_for_channel("tt_7196601676597871618", "tt_0:1:a:b", is_zalo=False) == 1
    assert _get_max_content_ids_for_channel("unknown_platform", "unknown_1", is_zalo=False) == 1
    print("[PASS] test_channel_content_id_batch_limits passed!")


def test_send_images_caches_per_page_and_reuploads_on_fb_expiry():
    from unittest.mock import MagicMock
    from backend.broadcast import _send_images_with_auto_reupload

    client = MagicMock()
    upload_seq = {"fb_A": ["cnt_A1_old", "cnt_A1_fresh"], "fb_B": ["cnt_B1"]}
    upload_calls = []

    def fake_upload(page_id, file_bytes, filename, content_type="image/jpeg", conversation_id=None):
        upload_calls.append(page_id)
        return {"success": True, "id": upload_seq[page_id].pop(0), "attachment_type": "PHOTO"}

    send_calls = []

    def fake_send(page_id, conversation_id, message="", action="reply_inbox", content_ids=None, **kwargs):
        send_calls.append((page_id, conversation_id, list(content_ids or [])))
        if content_ids == ["cnt_A1_old"] and conversation_id == "conv_A2":
            return {"success": False, "message_code": "invalid_upload_fb_attachments_result", "message": "expired"}
        return {"success": True, "id": "msg_ok"}

    client.upload_content.side_effect = fake_upload
    client.send_message.side_effect = fake_send

    decoded_imgs = [{"filename": "p.jpg", "content_type": "image/jpeg", "bytes": b"123"}]
    cache = {}

    # 1. Conv A1 uploads once for fb_A
    r1 = _send_images_with_auto_reupload(client, "fb_A", "conv_A1", decoded_imgs, cache, is_zalo=False)
    assert r1["success"] is True
    # 2. Conv B1 uploads once for fb_B
    r2 = _send_images_with_auto_reupload(client, "fb_B", "conv_B1", decoded_imgs, cache, is_zalo=False)
    assert r2["success"] is True
    # 3. Conv A2 hits expired content_id -> clears fb_A cache, re-uploads cnt_A1_fresh, succeeds
    r3 = _send_images_with_auto_reupload(client, "fb_A", "conv_A2", decoded_imgs, cache, is_zalo=False)
    assert r3["success"] is True
    assert upload_calls == ["fb_A", "fb_B", "fb_A"]
    assert send_calls == [
        ("fb_A", "conv_A1", ["cnt_A1_old"]),
        ("fb_B", "conv_B1", ["cnt_B1"]),
        ("fb_A", "conv_A2", ["cnt_A1_old"]),
        ("fb_A", "conv_A2", ["cnt_A1_fresh"]),
    ]
    print("[PASS] test_send_images_caches_per_page_and_reuploads_on_fb_expiry passed!")


def test_worker_logs_partial_send_when_cancelled_mid_recipient():
    import base64
    from unittest.mock import MagicMock, patch
    from backend.broadcast import _run_broadcast_worker

    _BROADCAST_TASKS.clear()
    task_id = "task_cancel_mid"
    _BROADCAST_TASKS[task_id] = {
        "task_id": task_id,
        "campaign_name": "camp_cancel",
        "is_running": True,
        "total": 0,
        "processed": 0,
        "success": 0,
        "failed": 0,
        "dry_run": False,
        "current_recipient": None,
        "started_at": "2026-11-16 14:00:00",
        "finished_at": None,
        "logs": [],
    }

    fake_db = MagicMock()
    added_logs = []
    fake_db.add.side_effect = lambda obj: added_logs.append(obj)

    fake_client = MagicMock()
    fake_client.send_message.return_value = {"success": True, "id": "msg_text_ok"}

    candidates = [{
        "lead_id": 1,
        "customer_id": "c1",
        "conversation_id": "514400205095512_111",
        "name": "Nguyen A",
        "gender": "male",
        "gender_title": "Anh",
        "phone_number": "0901",
        "page_id": "Anh Kế toán làm Data (Facebook)",
        "api_page_id": "514400205095512",
        "is_zalo": False,
        "status_tag": "",
        "assigned_users": "",
        "first_created_at": None,
        "contacted_at": None,
        "days_since_contact": 0,
    }]

    sample_b64 = base64.b64encode(b"imgdata").decode("ascii")
    req_data = {
        "campaign_name": "camp_cancel",
        "template": "Chao {name}",
        "send_mode": "text_then_images",
        "images": [{"filename": "p.jpg", "content_type": "image/jpeg", "data_base64": sample_b64}],
        "dry_run": False,
        "limit": 10,
        "custom_token": "tok_test",
    }

    with (
        patch("backend.broadcast.SessionLocal", return_value=fake_db),
        patch("backend.broadcast._filter_broadcast_candidates", return_value=candidates),
        patch("backend.broadcast.PancakeClient", return_value=fake_client),
        patch("backend.broadcast._sleep_with_cancel_check", return_value=False),
    ):
        _run_broadcast_worker(task_id, req_data)

    assert len(added_logs) == 1, f"Expected partial send log recorded in DB, got {len(added_logs)}"
    assert added_logs[0].status == "FAILED"
    assert "Đã gửi chữ" in (added_logs[0].error_message or "")
    assert _BROADCAST_TASKS[task_id]["processed"] == 1
    assert _BROADCAST_TASKS[task_id]["failed"] == 1
    _BROADCAST_TASKS.clear()
    print("[PASS] test_worker_logs_partial_send_when_cancelled_mid_recipient passed!")


def test_worker_counts_zalo_calls_on_partial_failure():
    import base64
    from unittest.mock import MagicMock, patch
    from backend.broadcast import _run_broadcast_worker

    _BROADCAST_TASKS.clear()
    task_id = "task_zalo_count"
    _BROADCAST_TASKS[task_id] = {
        "task_id": task_id,
        "campaign_name": "camp_zalo",
        "is_running": True,
        "total": 0,
        "processed": 0,
        "success": 0,
        "failed": 0,
        "dry_run": False,
        "current_recipient": None,
        "started_at": "2026-11-16 14:00:00",
        "finished_at": None,
        "logs": [],
    }

    fake_db = MagicMock()
    fake_client = MagicMock()
    fake_client.upload_content.return_value = {"success": True, "id": "cnt_zl_1", "attachment_type": "PHOTO"}

    # Lead 1: text OK (+1 call), images FAIL. Lead 2: text OK (+1 call), images OK (+1 call) => total 3 calls >= batch_size(3)
    def fake_send(page_id, conversation_id, message="", action="reply_inbox", content_ids=None, **kwargs):
        if conversation_id == "pzl_u_1" and content_ids:
            return {"success": False, "message": "temporary image error"}
        return {"success": True, "id": "ok"}

    fake_client.send_message.side_effect = fake_send

    candidates = [
        {
            "lead_id": i,
            "customer_id": f"c{i}",
            "conversation_id": f"pzl_u_{i}",
            "name": f"Khach {i}",
            "gender": "male",
            "gender_title": "Anh",
            "phone_number": f"090{i}",
            "page_id": "Eztech Phân Tích Dữ Liệu",
            "api_page_id": "pzl_629476615535063343",
            "is_zalo": True,
            "status_tag": "",
            "assigned_users": "",
            "first_created_at": None,
            "contacted_at": None,
            "days_since_contact": 0,
        }
        for i in (1, 2, 3)
    ]

    sleep_prefixes = []

    def fake_sleep(tid, secs, status_prefix=None):
        sleep_prefixes.append(status_prefix or "")
        return True

    sample_b64 = base64.b64encode(b"imgdata").decode("ascii")
    req_data = {
        "campaign_name": "camp_zalo",
        "template": "Chao {name}",
        "send_mode": "text_then_images",
        "images": [{"filename": "p.jpg", "content_type": "image/jpeg", "data_base64": sample_b64}],
        "dry_run": False,
        "limit": 10,
        "zalo_protection": True,
        "zalo_batch_size": 3,
        "custom_token": "tok_test",
    }

    with (
        patch("backend.broadcast.SessionLocal", return_value=fake_db),
        patch("backend.broadcast._filter_broadcast_candidates", return_value=candidates),
        patch("backend.broadcast.PancakeClient", return_value=fake_client),
        patch("backend.broadcast._sleep_with_cancel_check", side_effect=fake_sleep),
    ):
        _run_broadcast_worker(task_id, req_data)

    assert any("Nghỉ giải lao bảo vệ Zalo" in p for p in sleep_prefixes), (
        f"Expected Zalo batch pause after 3 real calls (1 partial + 2 full), got pauses: {sleep_prefixes}"
    )
    _BROADCAST_TASKS.clear()
    print("[PASS] test_worker_counts_zalo_calls_on_partial_failure passed!")


if __name__ == "__main__":
    test_broadcast_requests_schema()
    test_active_broadcast_and_stop()
    test_broadcast_image_payload_validation()
    test_start_broadcast_empty_template_requires_images()
    test_channel_content_id_batch_limits()
    test_send_images_caches_per_page_and_reuploads_on_fb_expiry()
    test_worker_logs_partial_send_when_cancelled_mid_recipient()
    test_worker_counts_zalo_calls_on_partial_failure()
    print("[PASS] ALL BROADCAST SCHEMA TESTS PASSED!")
