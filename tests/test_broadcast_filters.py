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


if __name__ == "__main__":
    test_broadcast_requests_schema()
    test_active_broadcast_and_stop()
    print("[PASS] ALL BROADCAST SCHEMA TESTS PASSED!")
