import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.auth import get_current_user, require_tab_access
from backend.class_list import router as class_list_router, _aggregate_students_from_deals
from backend.deal_entry import router as deal_entry_router, _filter_deals_for_user, build_debt_summary
from backend.rbac_config import (
    DEPT_ADMIN,
    DEPT_CLASS_MANAGER,
    DEPT_CONSULTANT,
    DEPT_MARKETING,
    get_module_scope,
    get_user_permissions,
    has_tab_access,
)
from database.db import get_db


def _make_user(username: str, full_name: str, department: str, role: str = "staff"):
    return SimpleNamespace(
        id=1,
        username=username,
        full_name=full_name,
        department=department,
        role=role,
        is_active=True,
    )


SAMPLE_DEALS = [
    {
        "id": "deal-1",
        "ngayThu": "2026-11-01",
        "sdt": "0912345678",
        "hoTen": "Nguyễn Văn A",
        "zalo": "https://pancake.vn/pzl_84898276368?c_id=conv_a",
        "nhomCS": "https://pancake.vn/pzl_84898276368?c_id=group_a",
        "lop": ["DF-K1"],
        "nvCS": "Trần Quản Lý",
        "nguoiNhap": "Trần Quản Lý",
        "isStudent": True,
        "daThu": 3000000,
        "phaiThu": 2000000,
        "tongTien": 5000000,
        "thuNo": 0,
        "daThuNo": 0,
        "conNo": 2000000,
        "trangThai": "Còn nợ",
        "apps": [],
    },
    {
        # Second deal for same student (e.g. second class / debt payment) -> should deduplicate in class_list
        "id": "deal-2",
        "ngayThu": "2026-11-10",
        "sdt": "0912345678",
        "hoTen": "Nguyễn Văn A",
        "zalo": "",
        "nhomCS": "",
        "lop": ["PBI-K1"],
        "nvCS": "Trần Quản Lý",
        "nguoiNhap": "Trần Quản Lý",
        "isStudent": True,
        "daThu": 1000000,
        "phaiThu": 0,
        "tongTien": 1000000,
        "thuNo": 1000000,
        "daThuNo": 0,
        "conNo": 0,
        "trangThai": "Thu nợ",
        "apps": [],
    },
    {
        "id": "deal-3",
        "ngayThu": "2026-11-05",
        "sdt": "0987654321",
        "hoTen": "Lê Thị B",
        "zalo": "https://pancake.vn/pzl_84377024368?c_id=conv_b",
        "nhomCS": "",
        "lop": ["DF-K1"],
        "nvCS": "Hiền Minh",
        "nguoiNhap": "Hiền Minh",
        "isStudent": True,
        "daThu": 4000000,
        "phaiThu": 1000000,
        "tongTien": 5000000,
        "thuNo": 0,
        "daThuNo": 0,
        "conNo": 1000000,
        "trangThai": "Còn nợ",
        "apps": [],
    },
]


def test_rbac_matrix_class_list_and_gas_tool():
    admin = _make_user("admin", "Admin EzTech", DEPT_ADMIN, role="admin")
    class_mgr = _make_user("qllh", "Trần Quản Lý", DEPT_CLASS_MANAGER)
    consultant = _make_user("sale1", "Hiền Minh", DEPT_CONSULTANT)
    marketing = _make_user("mkt1", "Marketing A", DEPT_MARKETING)

    # class_list access: ONLY Quản lý lớp học & Admin
    assert has_tab_access(admin, "class_list") is True
    assert has_tab_access(class_mgr, "class_list") is True
    assert has_tab_access(consultant, "class_list") is False
    assert has_tab_access(marketing, "class_list") is False

    assert get_module_scope(admin, "class_list") == "all"
    assert get_module_scope(class_mgr, "class_list") == "all"

    # gas_tool scope: personal for Quản lý lớp học, Consultant, Marketing; all for Admin
    assert get_module_scope(admin, "gas_tool") == "all"
    assert get_module_scope(class_mgr, "gas_tool") == "personal"
    assert get_module_scope(consultant, "gas_tool") == "personal"
    assert get_module_scope(marketing, "gas_tool") == "personal"

    # Permissions payload reflects both rules
    perms = get_user_permissions(class_mgr)
    assert "class_list" in perms["allowed_tabs"]
    assert perms["module_scopes"]["class_list"] == "all"
    assert perms["module_scopes"]["gas_tool"] == "personal"


def test_aggregate_students_deduplicates_and_merges_classes():
    students = _aggregate_students_from_deals(SAMPLE_DEALS)
    assert len(students) == 2

    st_a = next(s for s in students if s["sdt"] == "0912345678")
    assert st_a["hoTen"] == "Nguyễn Văn A"
    assert st_a["lop"] == ["DF-K1", "PBI-K1"]
    assert st_a["linkPancake"] == "https://pancake.vn/pzl_84898276368?c_id=conv_a"
    assert st_a["linkSupport"] == "https://pancake.vn/pzl_84898276368?c_id=group_a"


def _build_test_client(user_obj):
    app = FastAPI()
    app.include_router(class_list_router, dependencies=[Depends(require_tab_access("class_list"))])
    app.include_router(deal_entry_router, dependencies=[Depends(require_tab_access("gas_tool"))])
    app.dependency_overrides[get_current_user] = lambda: user_obj
    app.dependency_overrides[get_db] = lambda: None
    return TestClient(app)


def test_class_list_api_rbac_and_filters():
    # Consultant -> 403
    consultant = _make_user("sale1", "Hiền Minh", DEPT_CONSULTANT)
    client_sale = _build_test_client(consultant)
    resp_sale = client_sale.get("/api/class-list/students")
    assert resp_sale.status_code == 403

    # Marketing -> 403
    marketing = _make_user("mkt1", "Marketing A", DEPT_MARKETING)
    client_mkt = _build_test_client(marketing)
    resp_mkt = client_mkt.get("/api/class-list/students")
    assert resp_mkt.status_code == 403

    # Quản lý lớp học -> 200 and sees ALL students across all staff
    class_mgr = _make_user("qllh", "Trần Quản Lý", DEPT_CLASS_MANAGER)
    client_mgr = _build_test_client(class_mgr)
    with patch("backend.class_list.get_cached_deals", return_value=SAMPLE_DEALS), \
         patch("backend.class_list.read_lists", return_value={"lop": ["DF-K1", "PBI-K1", "AI-K1"]}):
        resp = client_mgr.get("/api/class-list/students")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["class_counts"]["DF-K1"] == 2
        assert body["class_counts"]["PBI-K1"] == 1
        assert body["class_counts"]["AI-K1"] == 0

        # Filter by class
        resp_pbi = client_mgr.get("/api/class-list/students", params={"class_name": "PBI-K1"})
        assert resp_pbi.status_code == 200
        assert resp_pbi.json()["total"] == 1
        assert resp_pbi.json()["students"][0]["sdt"] == "0912345678"

        # Filter by staff
        resp_staff = client_mgr.get("/api/class-list/students", params={"staff": "Hiền Minh"})
        assert resp_staff.status_code == 200
        assert resp_staff.json()["total"] == 1
        assert resp_staff.json()["students"][0]["hoTen"] == "Lê Thị B"


def test_deal_entry_scoping_for_class_manager_vs_admin():
    class_mgr = _make_user("qllh", "Trần Quản Lý", DEPT_CLASS_MANAGER)
    admin = _make_user("admin", "Admin EzTech", DEPT_ADMIN, role="admin")

    # Quản lý lớp học only sees their own deals & debts
    client_mgr = _build_test_client(class_mgr)
    with patch("backend.deal_entry.get_cached_deals", return_value=SAMPLE_DEALS), \
         patch("backend.deal_entry.read_lists", return_value={"lop": ["DF-K1"], "zaloCS": [], "nguon": [], "chuongTrinh": []}):
        resp_mgr = client_mgr.get("/api/deal-entry/init")
        assert resp_mgr.status_code == 200
        data_mgr = resp_mgr.json()
        assert {d["id"] for d in data_mgr["deals"]} == {"deal-1", "deal-2"}
        assert data_mgr["debts"]["count"] == 1
        assert data_mgr["debts"]["totalConNo"] == 2000000

    # Quản lý lớp học lookup-phone must NOT leak Hiền Minh's deal/debt
    with patch("backend.deal_entry.get_cached_deals", return_value=SAMPLE_DEALS), \
         patch("backend.deal_entry._lookup_pancake_lightweight", return_value={}):
        resp_lookup = client_mgr.get("/api/deal-entry/lookup-phone", params={"sdt": "0987654321"})
        assert resp_lookup.status_code == 200
        assert resp_lookup.json()["found"] is False

    # Admin still sees ALL deals & debts
    client_admin = _build_test_client(admin)
    with patch("backend.deal_entry.get_cached_deals", return_value=SAMPLE_DEALS), \
         patch("backend.deal_entry.read_lists", return_value={"lop": ["DF-K1"], "zaloCS": [], "nguon": [], "chuongTrinh": []}):
        resp_admin = client_admin.get("/api/deal-entry/init")
        assert resp_admin.status_code == 200
        data_admin = resp_admin.json()
        assert len(data_admin["deals"]) == 3
        assert data_admin["debts"]["count"] == 2
        assert data_admin["debts"]["totalConNo"] == 3000000


class TestClassListAndRbac(unittest.TestCase):
    def test_rbac_matrix(self):
        test_rbac_matrix_class_list_and_gas_tool()

    def test_aggregate_students(self):
        test_aggregate_students_deduplicates_and_merges_classes()

    def test_class_list_api(self):
        test_class_list_api_rbac_and_filters()

    def test_deal_entry_scoping(self):
        test_deal_entry_scoping_for_class_manager_vs_admin()


if __name__ == "__main__":
    unittest.main()
