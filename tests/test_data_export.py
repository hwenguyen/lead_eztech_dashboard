"""
Tests for backend/data_export.py:
- JWT Auth protection (401 without token, 200 with token)
- SQL Column Projection (only required DB fields projected)
- Filtering (Zalo, group chat exclusion, employee any/exact, strict non_student, dedupe_phone)
- TTL cache hit
- Excel (.xlsx) export integrity, leading zero preservation, and formula injection protection
"""
import io
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.auth import create_jwt_token, hash_password
from backend.data_export import clear_data_export_cache, router as data_export_router
from database.db import Base, get_db
from database.models import AppUser, DealWin, DimLead, FactLeadActivity, SalesDeal


def _make_test_app():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = TestingSessionLocal()
    pw_hash, salt = hash_password("secret123")
    user = AppUser(
        username="tester",
        password_hash=pw_hash,
        salt=salt,
        full_name="Test Admin",
        role="admin",
        is_active=True,
    )
    db.add(user)

    # 1. Valid non-student Zalo lead (Hoài Phương alone) + formula-like name to test sanitization
    l1 = DimLead(
        customer_id="c1",
        name="=HYPERLINK(\"http://evil\",\"Khach 1\")",
        phone_number="0916843146",
        page_id="Eztech Phân Tích Dữ Liệu",
        first_created_at=datetime(2026, 10, 1, 10, 0),
    )
    # 2. Same phone as l1 on another Zalo page (co-assigned) -> tests dedupe_phone & employee_match_mode
    l2 = DimLead(
        customer_id="c2",
        name="Khach 1 Zalo 2",
        phone_number="0916843146",
        page_id="Tuấn Anh Data",
        first_created_at=datetime(2026, 10, 2, 10, 0),
    )
    # 3. Zalo group chat pzl_g_ (must be excluded by default)
    l3 = DimLead(
        customer_id="c3",
        name="HVPBIK52 - Group",
        phone_number=None,
        page_id="Tuấn Anh Data",
        first_created_at=datetime(2026, 10, 3, 10, 0),
    )
    # 4. Student via tag on this conv
    l4 = DimLead(
        customer_id="c4",
        name="Hoc Vien Tag",
        phone_number="0988000111",
        page_id="Hiền Minh Eztech",
        first_created_at=datetime(2026, 10, 4, 10, 0),
    )
    # 5. Student via DealWin (no student tag on Zalo conv!)
    l5 = DimLead(
        customer_id="c5",
        name="Hoc Vien DealWin",
        phone_number="0977000222",
        page_id="Hiền Minh Eztech",
        first_created_at=datetime(2026, 10, 5, 10, 0),
    )
    # 6. Student via tag on another conv with same phone
    l6_zalo = DimLead(
        customer_id="c6z",
        name="Hoc Vien CrossPage",
        phone_number="0966000333",
        page_id="Eztech Consultant",
        first_created_at=datetime(2026, 10, 6, 10, 0),
    )
    l6_tt = DimLead(
        customer_id="c6t",
        name="Hoc Vien CrossPage TT",
        phone_number="0966000333",
        page_id="Anh Kế toán làm Data (TikTok)",
        first_created_at=datetime(2026, 10, 6, 9, 0),
    )
    # 7. Phone-less non-student Zalo lead (Hoài Phương)
    l7 = DimLead(
        customer_id="c7",
        name="Khach Khong SDT",
        phone_number=None,
        page_id="Hiền Minh Eztech",
        first_created_at=datetime(2026, 10, 7, 10, 0),
    )
    db.add_all([l1, l2, l3, l4, l5, l6_zalo, l6_tt, l7])
    db.flush()

    db.add_all(
        [
            FactLeadActivity(
                lead_id=l1.id,
                conversation_id="pzl_u_629476615535063343_1",
                status_tag="Remind,TikTok TCKT",
                assigned_users="Hoài Phương",
                message_count=12,
                contacted_at=datetime(2026, 11, 10, 10, 0),
            ),
            FactLeadActivity(
                lead_id=l2.id,
                conversation_id="pzl_u_788602135347404973_2",
                status_tag="Có thông tin",
                assigned_users="Liên Vũ, Hoài Phương",
                message_count=8,
                contacted_at=datetime(2026, 11, 12, 10, 0),
            ),
            FactLeadActivity(
                lead_id=l3.id,
                conversation_id="pzl_g_788602135347404973_3",
                status_tag=None,
                assigned_users="Hoài Phương",
                message_count=5,
                contacted_at=datetime(2026, 11, 13, 10, 0),
            ),
            FactLeadActivity(
                lead_id=l4.id,
                conversation_id="pzl_u_131986891507252646_4",
                status_tag="Đã là học viên,TikTok TCKT",
                assigned_users="Hoài Phương",
                message_count=20,
                contacted_at=datetime(2026, 11, 14, 10, 0),
            ),
            FactLeadActivity(
                lead_id=l5.id,
                conversation_id="pzl_u_131986891507252646_5",
                status_tag="Đồng ý học",
                assigned_users="Hoài Phương",
                message_count=15,
                contacted_at=datetime(2026, 11, 15, 10, 0),
            ),
            FactLeadActivity(
                lead_id=l6_zalo.id,
                conversation_id="pzl_u_764881945463506349_6",
                status_tag="Data Talk",
                assigned_users="Hoài Phương",
                message_count=7,
                contacted_at=datetime(2026, 11, 16, 10, 0),
            ),
            FactLeadActivity(
                lead_id=l6_tt.id,
                conversation_id="tt_0:1:7196601676597871618:6",
                status_tag="Đã là học viên",
                assigned_users="Liên Vũ",
                message_count=9,
                contacted_at=datetime(2026, 11, 16, 9, 0),
            ),
            FactLeadActivity(
                lead_id=l7.id,
                conversation_id="pzl_u_131986891507252646_7",
                status_tag="Data Talk",
                assigned_users="Hoài Phương",
                message_count=4,
                contacted_at=datetime(2026, 11, 17, 10, 0),
            ),
        ]
    )
    db.add(DealWin(sheet_row_id="row_1", phone_number="0977000222", full_name="Hoc Vien DealWin", is_student=True))
    db.add(SalesDeal(deal_uid="d_1", ngay_thu="2026-11-01", sdt="0977000222", ho_ten="Hoc Vien DealWin"))
    db.commit()
    db.close()

    app = FastAPI()
    app.include_router(data_export_router)

    def _override_db():
        s = TestingSessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_db
    clear_data_export_cache()

    token = create_jwt_token({"sub": "tester", "role": "admin"}, timedelta(hours=1))
    return TestClient(app), {"Authorization": f"Bearer {token}"}


def test_auth_required():
    client, headers = _make_test_app()
    assert client.get("/api/data-export/options").status_code == 401
    assert client.post("/api/data-export/preview", json={}).status_code == 401
    assert client.post("/api/data-export/export", json={}).status_code == 401

    ok = client.get("/api/data-export/options", headers=headers)
    assert ok.status_code == 200
    body = ok.json()
    assert "columns" in body and len(body["columns"]) >= 10
    assert "Hoài Phương" in body["employees"]
    print("[PASS] test_auth_required")


def test_projection_filters_dedupe_and_cache():
    client, headers = _make_test_app()
    payload = {
        "columns": ["assigned_users", "page_name", "phone_number", "name", "pancake_link"],
        "channel_group": "zalo",
        "employees": ["Hoài Phương"],
        "employee_match_mode": "any",
        "student_filter": "non_student",
        "exclude_zalo_groups": True,
        "dedupe_phone": False,
        "page": 1,
        "page_size": 50,
    }
    res1 = client.post("/api/data-export/preview", json=payload, headers=headers)
    assert res1.status_code == 200
    data1 = res1.json()
    # Should match l7 (no phone), l2 (co-assigned), l1 (alone) -> 3 rows
    # Excluded: l3 (group pzl_g_), l4 (tag student), l5 (DealWin/SalesDeal), l6_zalo (cross-page student tag), l6_tt (TikTok)
    assert data1["total"] == 3, data1
    assert data1["cached"] is False
    # Verify SQL column projection did NOT pull unused columns
    assert set(data1["projected_db_fields"]) == {
        "assigned_users",
        "page_id",
        "phone_number",
        "name",
        "conversation_id",
    }
    assert set(data1["rows"][0].keys()) == set(payload["columns"])
    assert all(r["pancake_link"].startswith("https://pancake.vn/pzl_") for r in data1["rows"])

    # Second identical call must hit RAM cache
    res2 = client.post("/api/data-export/preview", json=payload, headers=headers)
    assert res2.status_code == 200
    assert res2.json()["cached"] is True

    # Exact employee mode excludes l2 (Liên Vũ, Hoài Phương) -> 2 rows (l7, l1)
    exact_payload = {**payload, "employee_match_mode": "exact"}
    res_exact = client.post("/api/data-export/preview", json=exact_payload, headers=headers)
    assert res_exact.status_code == 200
    assert res_exact.json()["total"] == 2

    # Dedupe phone collapses l1 & l2 (same phone 0916843146) into 1 newest row, keeping l7 -> 2 rows
    dedupe_payload = {**payload, "dedupe_phone": True}
    res_dedupe = client.post("/api/data-export/preview", json=dedupe_payload, headers=headers)
    assert res_dedupe.status_code == 200
    assert res_dedupe.json()["total"] == 2
    print("[PASS] test_projection_filters_dedupe_and_cache")


def test_excel_export_integrity_and_security():
    client, headers = _make_test_app()
    payload = {
        "columns": ["name", "phone_number", "page_name", "assigned_users", "pancake_link"],
        "channel_group": "zalo",
        "employees": ["Hoài Phương"],
        "employee_match_mode": "any",
        "student_filter": "non_student",
        "exclude_zalo_groups": True,
        "dedupe_phone": False,
    }
    res = client.post("/api/data-export/export", json=payload, headers=headers)
    assert res.status_code == 200
    assert res.headers["x-export-row-count"] == "3"
    assert res.headers["x-projected-db-columns"] == "5"
    assert ".xlsx" in res.headers["content-disposition"]

    wb = load_workbook(io.BytesIO(res.content))
    ws = wb.active
    rows = list(ws.iter_rows(values_only=False))
    assert len(rows) == 4  # 1 header + 3 data rows
    headers_row = [c.value for c in rows[0]]
    assert headers_row == [
        "Tên khách hàng",
        "Số điện thoại (SĐT)",
        "Tên kênh (Page)",
        "Nhân viên phụ trách",
        "Link Pancake",
    ]
    # Check leading zero preserved as string and formula neutralized
    by_name = {r[0].value: r for r in rows[1:]}
    sanitized_name = "'=HYPERLINK(\"http://evil\",\"Khach 1\")"
    assert sanitized_name in by_name, list(by_name.keys())
    phone_cell = by_name[sanitized_name][1]
    assert phone_cell.value == "0916843146"
    assert isinstance(phone_cell.value, str)
    link_cell = by_name[sanitized_name][4]
    assert link_cell.value.startswith("https://pancake.vn/pzl_84377024368?c_id=")
    assert link_cell.hyperlink is not None
    print("[PASS] test_excel_export_integrity_and_security")


if __name__ == "__main__":
    test_auth_required()
    test_projection_filters_dedupe_and_cache()
    test_excel_export_integrity_and_security()
    print("\nALL DATA EXPORT TESTS PASSED!")
