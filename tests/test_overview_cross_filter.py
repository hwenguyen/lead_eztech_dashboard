import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, DimLead, FactLeadActivity
from database.db import get_db
from backend.main import app
from backend.lead_metrics import clear_metrics_cache


class TestOverviewCrossFiltering(unittest.TestCase):
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
        clear_metrics_cache()
        self.client = TestClient(app)

        db = self.SessionLocal()
        try:
            leads = [
                # Lead 1: New on 2026-11-17, has phone, Trần Đạt, Lead Other
                DimLead(
                    customer_id="cust_1",
                    name="Lead One",
                    phone_number="0901111111",
                    phone_at=datetime(2026, 11, 17, 10, 5),
                    page_id="Eztech",
                    first_created_at=datetime(2026, 11, 17, 10, 0),
                ),
                # Lead 2: New on 2026-11-17, no phone, Linh Bùi, Đào tạo
                DimLead(
                    customer_id="cust_2",
                    name="Lead Two",
                    phone_number=None,
                    phone_at=None,
                    page_id="Eztech",
                    first_created_at=datetime(2026, 11, 17, 11, 0),
                ),
                # Lead 3: Created before period -> Recontact on 2026-11-17, has phone, Trần Đạt, Lead Other
                DimLead(
                    customer_id="cust_3",
                    name="Lead Three",
                    phone_number="0903333333",
                    phone_at=datetime(2026, 11, 17, 15, 0),
                    page_id="Eztech",
                    first_created_at=datetime(2026, 11, 10, 9, 0),
                ),
                # Lead 4: New on 2026-11-18, has phone, Linh Bùi, Other tag category
                DimLead(
                    customer_id="cust_4",
                    name="Lead Four",
                    phone_number="0904444444",
                    phone_at=datetime(2026, 11, 18, 14, 10),
                    page_id="Eztech",
                    first_created_at=datetime(2026, 11, 18, 14, 0),
                ),
            ]
            db.add_all(leads)
            db.flush()

            acts = [
                FactLeadActivity(
                    lead_id=leads[0].id,
                    conversation_id="conv_1",
                    status_tag="Lead Other",
                    assigned_users="Trần Đạt",
                    is_contacted=True,
                    contacted_at=datetime(2026, 11, 17, 10, 10),
                    contacted_dates="2026-11-17",
                ),
                FactLeadActivity(
                    lead_id=leads[1].id,
                    conversation_id="conv_2",
                    status_tag="Đào tạo",
                    assigned_users="Linh Bùi",
                    is_contacted=True,
                    contacted_at=datetime(2026, 11, 17, 11, 10),
                    contacted_dates="2026-11-17",
                ),
                FactLeadActivity(
                    lead_id=leads[2].id,
                    conversation_id="conv_3",
                    status_tag="Lead Other",
                    assigned_users="Trần Đạt",
                    is_contacted=True,
                    contacted_at=datetime(2026, 11, 17, 15, 10),
                    contacted_dates="2026-11-17",
                ),
                FactLeadActivity(
                    lead_id=leads[3].id,
                    conversation_id="conv_4",
                    status_tag="Tư vấn",
                    assigned_users="Linh Bùi",
                    is_contacted=True,
                    contacted_at=datetime(2026, 11, 18, 14, 15),
                    contacted_dates="2026-11-18",
                ),
            ]
            db.add_all(acts)
            db.commit()
        finally:
            db.close()

    def tearDown(self):
        clear_metrics_cache()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self._prev_overrides)
        self.engine.dispose()

    def test_selected_date_matches_trend_bucket_and_filters_leads(self):
        base_params = {"start_date": "2026-11-17", "end_date": "2026-11-18"}
        trend_res = self.client.get("/api/metrics/trend", params=base_params)
        self.assertEqual(trend_res.status_code, 200)
        buckets = {pt["date"]: pt for pt in trend_res.json()["data"]}
        self.assertEqual(buckets["2026-11-17"], {"date": "2026-11-17", "new_leads": 2, "recontact_leads": 1, "phone_leads": 2})

        sum_res = self.client.get("/api/metrics/summary", params={**base_params, "selected_date": "2026-11-17"})
        self.assertEqual(sum_res.status_code, 200)
        s = sum_res.json()
        self.assertEqual(s["new_leads"], buckets["2026-11-17"]["new_leads"])
        self.assertEqual(s["recontact_leads"], buckets["2026-11-17"]["recontact_leads"])
        self.assertEqual(s["phone_leads"], buckets["2026-11-17"]["phone_leads"])
        self.assertEqual(s["total_leads"], 3)

        list_res = self.client.get("/api/leads/list", params={**base_params, "selected_date": "2026-11-17"})
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(list_res.json()["total"], s["total_leads"])
        self.assertEqual({row["customer_id"] for row in list_res.json()["data"]}, {"cust_1", "cust_2", "cust_3"})

    def test_primary_employee_filter_keeps_employee_donut_slices(self):
        base_params = {"start_date": "2026-11-17", "end_date": "2026-11-18", "primary_employee": "Trần Đạt"}
        sum_res = self.client.get("/api/metrics/summary", params=base_params)
        self.assertEqual(sum_res.status_code, 200)
        s = sum_res.json()
        self.assertEqual(s["new_leads"], 1)
        self.assertEqual(s["recontact_leads"], 1)
        self.assertEqual(s["total_leads"], 2)
        self.assertEqual(s["phone_leads"], 2)
        # All employees remain in employee donut stats for Power BI self-highlighting
        self.assertEqual(s["new_leads_employee_stats"].get("Trần Đạt"), 1)
        self.assertEqual(s["new_leads_employee_stats"].get("Linh Bùi"), 2)

        trend_res = self.client.get("/api/metrics/trend", params=base_params)
        self.assertEqual(trend_res.status_code, 200)
        buckets = {pt["date"]: pt for pt in trend_res.json()["data"]}
        self.assertEqual(buckets["2026-11-17"], {"date": "2026-11-17", "new_leads": 1, "recontact_leads": 1, "phone_leads": 2})
        self.assertEqual(buckets["2026-11-18"], {"date": "2026-11-18", "new_leads": 0, "recontact_leads": 0, "phone_leads": 0})

        list_res = self.client.get("/api/leads/list", params=base_params)
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual({row["customer_id"] for row in list_res.json()["data"]}, {"cust_1", "cust_3"})

    def test_lead_type_filter_preserves_ratio_chart_totals(self):
        base_params = {"start_date": "2026-11-17", "end_date": "2026-11-18", "lead_type": "new"}
        sum_res = self.client.get("/api/metrics/summary", params=base_params)
        self.assertEqual(sum_res.status_code, 200)
        s = sum_res.json()
        self.assertEqual(s["new_leads"], 3)
        self.assertEqual(s["recontact_leads"], 0)
        self.assertEqual(s["ratio_new_leads"], 3)
        self.assertEqual(s["ratio_recontact_leads"], 1)

        list_res = self.client.get("/api/leads/list", params=base_params)
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(list_res.json()["total"], 3)

    def test_tag_category_and_has_phone_filter_across_endpoints(self):
        base_params = {
            "start_date": "2026-11-17",
            "end_date": "2026-11-18",
            "tag_category": "Lead Other",
            "has_phone": "true",
        }
        sum_res = self.client.get("/api/metrics/summary", params=base_params)
        self.assertEqual(sum_res.status_code, 200)
        s = sum_res.json()
        self.assertEqual(s["new_leads"], 1)
        self.assertEqual(s["recontact_leads"], 1)
        self.assertEqual(s["total_leads"], 2)
        self.assertEqual(s["phone_leads"], 2)
        self.assertEqual(s["phone_tag_stats"]["Lead Other"], 2)
        self.assertEqual(s["phone_tag_stats"]["Other"], 1)

        trend_res = self.client.get("/api/metrics/trend", params=base_params)
        self.assertEqual(trend_res.status_code, 200)
        buckets = {pt["date"]: pt for pt in trend_res.json()["data"]}
        self.assertEqual(buckets["2026-11-17"], {"date": "2026-11-17", "new_leads": 1, "recontact_leads": 1, "phone_leads": 2})
        self.assertEqual(buckets["2026-11-18"], {"date": "2026-11-18", "new_leads": 0, "recontact_leads": 0, "phone_leads": 0})

        list_res = self.client.get("/api/leads/list", params=base_params)
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual({row["customer_id"] for row in list_res.json()["data"]}, {"cust_1", "cust_3"})


if __name__ == "__main__":
    unittest.main()
