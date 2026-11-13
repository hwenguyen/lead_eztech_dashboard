import os
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, SalesDeal
from database.db import get_db
from backend.main import app
import backend.deal_entry as de


class MockPostResp:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {"ok": True}
        self.text = text

    def json(self):
        return self._json


class DealSheetSyncTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        self._prev_overrides = dict(app.dependency_overrides)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        with de._CACHE_LOCK:
            de._DEALS_CACHE = None
            de._DEALS_CACHE_TS = 0.0
            de._LISTS_CACHE = None
            de._LISTS_CACHE_TS = 0.0
            de._SHEET_CFG_CACHE = None
            de._SHEET_CFG_TS = 0.0
            de._LAST_SYNCED_DEAL_WIN_ID = 0
            de._LAST_SYNC_CHECK_TS = time.time()
            de._PANCAKE_LINKS_BACKFILLED = True

    def tearDown(self):
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self._prev_overrides)
        self.engine.dispose()

    def test_deal_to_sheet_row_mapping(self):
        row = de._deal_to_sheet_row(
            {
                "id": "DEAL-1",
                "ngayThu": "2026-11-13",
                "ngayContact": "2026-11-01",
                "sdt": "0912345678",
                "hoTen": "Nguyen Van A",
                "lop": ["DB-K1", "DF-K2"],
                "daThu": 5000000,
                "phaiThu": 2000000,
                "tongTien": 7000000,
                "conNo": 2000000,
            }
        )
        self.assertEqual(row["ngayThu"], "13/11/2026")
        self.assertEqual(row["ngayContact"], "01/11/2026")
        self.assertEqual(row["lop"], "DB-K1, DF-K2")
        self.assertEqual(row["daThu"], 5000000)
        self.assertEqual(row["conNo"], 2000000)
        self.assertEqual(len(row), 29)

    def test_config_and_live_sync_on_save_class_delete_and_push_all(self):
        calls = []
        called_event = threading.Event()

        def fake_post(url, json=None, timeout=None, allow_redirects=None):
            calls.append((url, json))
            called_event.set()
            return MockPostResp(200, {"ok": True})

        webhook = "https://script.google.com/macros/s/fake-id/exec"
        sheet_url = "https://docs.google.com/spreadsheets/d/fake-sheet/edit"

        # 1. Save & get config
        r_put = self.client.put(
            "/api/deal-entry/sheet-sync/config",
            json={
                "webhook_url": webhook,
                "sheet_url": sheet_url,
                "only_students": True,
                "auto_sync": True,
            },
        )
        self.assertEqual(r_put.status_code, 200)
        self.assertTrue(r_put.json()["configured"])

        r_get = self.client.get("/api/deal-entry/sheet-sync/config")
        self.assertEqual(r_get.status_code, 200)
        self.assertEqual(r_get.json()["webhook_url"], webhook)
        self.assertEqual(r_get.json()["sheet_url"], sheet_url)
        self.assertTrue(r_get.json()["only_students"])

        with patch("requests.post", side_effect=fake_post):
            # 2. Save a student deal -> should trigger async upsert_phone
            called_event.clear()
            r_save = self.client.post(
                "/api/deal-entry/deals",
                json={
                    "ngayThu": "2026-11-13",
                    "sdt": "0988777666",
                    "hoTen": "Tran Thi B",
                    "isStudent": True,
                    "daThu": 3000000,
                    "phaiThu": 1000000,
                    "tongTien": 4000000,
                    "lop": ["DB-K1"],
                },
            )
            self.assertEqual(r_save.status_code, 200)
            deal_id = r_save.json()["dealId"]
            self.assertTrue(called_event.wait(timeout=2.0))
            self.assertEqual(calls[-1][0], webhook)
            self.assertEqual(calls[-1][1]["action"], "upsert_phone")
            self.assertEqual(len(calls[-1][1]["rows"]), 1)
            self.assertEqual(calls[-1][1]["rows"][0]["id"], deal_id)

            # 3. Quick class update -> should trigger upsert_phone with updated class
            called_event.clear()
            r_cls = self.client.put(
                f"/api/deal-entry/deals/{deal_id}/classes",
                json={"lop": ["DB-K1", "DE-K2"]},
            )
            self.assertEqual(r_cls.status_code, 200)
            self.assertTrue(called_event.wait(timeout=2.0))
            self.assertEqual(calls[-1][1]["action"], "upsert_phone")
            self.assertEqual(calls[-1][1]["rows"][0]["lop"], "DB-K1, DE-K2")

            # Add one non-student row directly in DB & refresh cache to test only_students filter on push-all
            db = self.SessionLocal()
            db.add(
                SalesDeal(
                    deal_uid="NON-STUDENT-1",
                    ngay_thu="2026-11-13",
                    sdt="0900111222",
                    ho_ten="Lead Chua Chot",
                    is_student=False,
                    da_thu=0,
                    phai_thu=0,
                    tong_tien=0,
                )
            )
            db.commit()
            db.close()
            with de._CACHE_LOCK:
                de._DEALS_CACHE = None

            # 4. push-all should exclude non-student because only_students=True
            r_push = self.client.post("/api/deal-entry/sheet-sync/push-all")
            self.assertEqual(r_push.status_code, 200)
            self.assertEqual(r_push.json()["synced_count"], 1)
            self.assertEqual(calls[-1][1]["action"], "replace_all")
            self.assertEqual([r["id"] for r in calls[-1][1]["rows"]], [deal_id])

            # 5. Delete deal -> should trigger delete with deal_id
            called_event.clear()
            r_del = self.client.delete(f"/api/deal-entry/deals/{deal_id}")
            self.assertEqual(r_del.status_code, 200)
            self.assertTrue(called_event.wait(timeout=2.0))
            self.assertEqual(calls[-1][1]["action"], "delete")
            self.assertEqual(calls[-1][1]["deal_id"], deal_id)


if __name__ == "__main__":
    unittest.main()
