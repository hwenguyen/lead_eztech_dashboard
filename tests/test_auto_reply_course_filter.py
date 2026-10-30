"""
Self-check test for auto-reply bot course exclusion logic.
"""
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from etl.auto_reply_bot import is_course_related, should_reply, should_reply_comment
from etl.auto_reply_rules import AUTO_REPLY_RULES, COMMENT_REPLY_RULES, COURSE_KEYWORDS, COURSE_TAGS


def test_is_course_related():
    # Course inquiries must be identified
    course_samples = [
        "Cho em xin học phí khóa học",
        "Có lớp học online không ạ?",
        "Tư vấn khóa học giúp mình",
        "Đăng ký học như thế nào",
        "Học phí bao nhiêu vậy shop?",
        "Xin thông tin khóa học Excel",
        "Khóa học này có file không?",
        "Sau khoá học có hỗ trợ file không ạ",
        "Lộ trình học DA cho người mới",
        "Chi phí khóa học Power BI",
        "Lịch khai giảng sớm nhất",
        "Em muốn học kế toán tổng hợp",
        "cần tư vấn",
        "ib khoá học",
        "Chương trình học bao gồm những gì",
        "Cho mình xin bài giảng",
        "Em là học viên cũ",
        "Giá khóa học thế nào bạn",
        "C chưa vào được lớp",
        "Cho em link khoá học",
    ]
    for msg in course_samples:
        is_course, kw = is_course_related(msg)
        assert is_course, f"Expected '{msg}' to be recognized as course-related, but got False"

    # Non-course file / community inquiries must NOT be identified as course
    normal_samples = [
        "Cho em xin file",
        "xin file mẫu báo cáo",
        "Cho mình xin template",
        "Gửi em prompt với",
        "Cho em vào nhóm Zalo với ạ",
        "Xin link tham gia nhóm",
        "Cho em xin file excel chi phí lãi lỗ công trình",  # "chi phí" without "học/khóa học"
        "Gửi mình file quản lý dòng tiền",
    ]
    for msg in normal_samples:
        is_course, kw = is_course_related(msg)
        assert not is_course, f"Expected '{msg}' to NOT be course-related, but matched kw '{kw}'"

    print("[PASS] test_is_course_related passed!")


def test_should_reply_inbox_course_exclusion():
    # 1. Single message with course inquiry
    conv_course = {
        "id": "test_conv_course_1",
        "messages": [
            {"role": "admin", "message": "EzTech xin chào!"},
            {"role": "customer", "message": "Khóa học này có gửi file bài giảng không shop?"}
        ]
    }
    can_send, rule, kw, cust_msg, reason = should_reply(
        conv=conv_course,
        page_id="tt_7196601676597871618",
        db=None
    )
    assert not can_send, "Expected course conversation to be skipped"
    assert "khóa học" in reason.lower()

    # 2. Multi-message sequence: Customer asked course in Msg 1, then asked file in Msg 2
    conv_multi = {
        "id": "test_conv_multi_1",
        "messages": [
            {"role": "admin", "message": "Chào bạn!"},
            {"role": "customer", "message": "Học phí khóa này bao nhiêu vậy shop?"},
            {"role": "customer", "message": "Cho em xin file với ạ"}
        ]
    }
    can_send, rule, kw, cust_msg, reason = should_reply(
        conv=conv_multi,
        page_id="tt_7196601676597871618",
        db=None
    )
    assert not can_send, "Expected multi-message with course question to be skipped"
    assert "khóa học" in reason.lower()

    # 3. Tag exclusion: Customer asked for file but is tagged as an existing student / course
    conv_student_tag = {
        "id": "test_conv_tag_1",
        "tags": ["Đã là học viên"],
        "messages": [
            {"role": "admin", "message": "Chào bạn!"},
            {"role": "customer", "message": "Cho em xin file ạ"}
        ]
    }
    can_send, rule, kw, cust_msg, reason = should_reply(
        conv=conv_student_tag,
        page_id="tt_7196601676597871618",
        db=None
    )
    assert not can_send, "Expected conversation with student tag to be skipped"
    assert "học viên" in reason.lower() or "khóa học" in reason.lower()

    # 4. Normal file conversation should pass the course check
    conv_normal = {
        "id": "test_conv_normal_1",
        "messages": [
            {"role": "admin", "message": "EzTech xin chào!"},
            {"role": "customer", "message": "Cho em xin file mẫu báo cáo công nợ với ạ"}
        ]
    }
    can_send, rule, kw, cust_msg, reason = should_reply(
        conv=conv_normal,
        page_id="tt_7196601676597871618",
        db=None,
        prefetched_sent_convs=set(),
        prefetched_failed_counts={}
    )
    assert can_send, f"Expected normal file conversation to be allowed, got reason: {reason}"
    assert rule["case_id"] == "xin_file"

    print("[PASS] test_should_reply_inbox_course_exclusion passed!")


def test_should_reply_comment_course_exclusion():
    # Comment asking about course
    comment_course = {
        "comment_id": "test_cmt_1",
        "message": "Cho em xin thông tin khóa học và học phí với ạ"
    }
    can_reply, rule, kw, cust_msg, reason = should_reply_comment(
        comment=comment_course,
        page_id="tt_7196601676597871618",
        db=None
    )
    assert not can_reply, "Expected course comment to be skipped"
    assert "khóa học" in reason.lower()

    # Normal comment asking for file
    comment_file = {
        "comment_id": "test_cmt_2",
        "message": "Cho em xin file với ạ"
    }
    is_course, _ = is_course_related(comment_file["message"])
    assert not is_course

    print("[PASS] test_should_reply_comment_course_exclusion passed!")


def test_cmt_khoa_hoc_is_disabled():
    rule = next((r for r in COMMENT_REPLY_RULES if r.get("case_id") == "cmt_khoa_hoc"), None)
    assert rule is not None
    assert rule.get("enabled") is False, "cmt_khoa_hoc must be disabled"
    print("[PASS] test_cmt_khoa_hoc_is_disabled passed!")


if __name__ == "__main__":
    test_is_course_related()
    test_should_reply_inbox_course_exclusion()
    test_should_reply_comment_course_exclusion()
    test_cmt_khoa_hoc_is_disabled()
    print("\n[PASS] ALL TESTS PASSED!")
