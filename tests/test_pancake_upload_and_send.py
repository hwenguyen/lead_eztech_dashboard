"""
Tests for PancakeClient.upload_content() and mutually-exclusive content_ids in send_message().
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from etl.pancake_client import PancakeClient


def _make_response(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text or (str(json_data) if json_data is not None else "")
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


class TestPancakeUploadAndSend(unittest.TestCase):
    def _make_client(self, token="tok_initial", resolved_pid="514400205095512"):
        client = PancakeClient(api_token="user_tok")
        client.session = MagicMock()
        client._get_page_access_token = MagicMock(return_value=(token, resolved_pid, "Test Page"))
        return client

    def test_upload_content_multipart_success(self):
        client = self._make_client()
        client.session.post.return_value = _make_response(
            200,
            {"success": True, "id": "cnt_123", "attachment_type": "PHOTO"},
        )

        res = client.upload_content(
            page_id="514400205095512",
            file_bytes=b"\xff\xd8\xff\xe0test",
            filename="promo.jpg",
            content_type="image/jpeg",
        )

        self.assertTrue(res["success"])
        self.assertEqual(res["id"], "cnt_123")
        self.assertEqual(res["attachment_type"], "PHOTO")

        call_args = client.session.post.call_args
        self.assertEqual(
            call_args.args[0],
            "https://pages.fm/api/public_api/v1/pages/514400205095512/upload_contents",
        )
        self.assertEqual(call_args.kwargs["params"], {"page_access_token": "tok_initial"})
        self.assertEqual(
            call_args.kwargs["files"],
            {"file": ("promo.jpg", b"\xff\xd8\xff\xe0test", "image/jpeg")},
        )

    def test_upload_content_token_refresh_on_102(self):
        client = PancakeClient(api_token="user_tok")
        client.session = MagicMock()
        client._get_page_access_token = MagicMock(
            side_effect=[
                ("tok_expired", "514400205095512", "Test Page"),
                ("tok_fresh", "514400205095512", "Test Page"),
            ]
        )
        client.session.post.side_effect = [
            _make_response(200, {"success": False, "error_code": 102, "message": "invalid access_token"}),
            _make_response(200, {"success": True, "id": "cnt_fresh", "attachment_type": "PHOTO"}),
        ]

        res = client.upload_content("514400205095512", b"img", "a.png", "image/png")

        self.assertTrue(res["success"])
        self.assertEqual(res["id"], "cnt_fresh")
        self.assertEqual(client._get_page_access_token.call_count, 2)
        self.assertTrue(client._get_page_access_token.call_args_list[1].kwargs.get("force_refresh"))
        self.assertEqual(
            client.session.post.call_args_list[1].kwargs["params"],
            {"page_access_token": "tok_fresh"},
        )

    def test_send_message_with_content_ids_omits_message(self):
        client = self._make_client()
        client.session.post.return_value = _make_response(200, {"success": True, "id": "msg_999"})

        res = client.send_message(
            page_id="514400205095512",
            conversation_id="conv_abc",
            message="Ignored text that must not accompany content_ids",
            action="reply_inbox",
            content_ids=["cnt_1", "cnt_2"],
        )

        self.assertTrue(res["success"])
        sent_json = client.session.post.call_args.kwargs["json"]
        self.assertEqual(sent_json["action"], "reply_inbox")
        self.assertEqual(sent_json["content_ids"], ["cnt_1", "cnt_2"])
        self.assertNotIn("message", sent_json)

    def test_send_message_text_only_keeps_message(self):
        client = self._make_client()
        client.session.post.return_value = _make_response(200, {"success": True, "id": "msg_100"})

        res = client.send_message(
            page_id="514400205095512",
            conversation_id="conv_abc",
            message="Chao ban!",
            action="reply_inbox",
        )

        self.assertTrue(res["success"])
        sent_json = client.session.post.call_args.kwargs["json"]
        self.assertEqual(sent_json, {"action": "reply_inbox", "message": "Chao ban!"})


if __name__ == "__main__":
    unittest.main()
