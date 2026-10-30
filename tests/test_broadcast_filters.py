"""
Test for broadcast multi-tag filtering and exclude_students logic.
"""
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.broadcast import BroadcastPreviewRequest, BroadcastStartRequest


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


if __name__ == "__main__":
    test_broadcast_requests_schema()
    print("[PASS] ALL BROADCAST SCHEMA TESTS PASSED!")
