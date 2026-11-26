import io
from openpyxl import Workbook

from backend.class_schedule import (
    build_google_sheet_csv_url,
    parse_class_schedule_csv,
    parse_class_schedule_xlsx,
)


SAMPLE_CSV = """LỊCH QUẢN LÝ LỚP HỌC,,,,,,,,,,,,,,,,
Ngày học,,,,,,,,,2026-06-01,2026-06-03,,,,,,
,Buổi 1,Buổi 2,Buổi 3,Buổi 4,Buổi 5,Buổi 6,Buổi 7,Buổi 8,Buổi 9,Buổi 10,,,,,
Khóa PBIK48,Ngọc,Ngọc,Ngọc,Liên,Ngọc,Ngọc,Ngọc,Ngọc,Ngọc,Ngọc,,,,,
,Linh,Linh,Linh,Đạt,Linh,Linh,Linh,Linh,Linh,Linh,,,,,
,,,,,,,,,,,,,,,,
Khai giảng,LỊCH QUẢN LÝ LỚP HỌC - Khóa PBIK63 - Power Query,,,,,,,,,,,,,,,
Ngày học,2026-11-19,2026-11-26,2026-12-01,,,,,,,,,,,,,
Thứ 3 - T5,Buổi 1,Buổi 2,Buổi 3,,,,,,,,,,,,,
Giảng viên,a Tuấn Anh,a Tuấn Anh,a Hiếu,,,,,,,,,,,,,
"Sĩ số ",Liên,Liên,Liên,,,,,,,,,,,,,
,Đạt,Đạt,Đạt,,,,,,,,,,,,,
,Trân,Vượng,Vượng,,,,,,,,,,,,,
,,Hiếu,Hiếu,,,,,,,,,,,,,
,,,,,,,,,,,,,,,,
STT,Khoá học,Mã lớp,Dự kiến khai giảng,Thứ học,Số buổi,Giảng viên,Trạng thái,Note
2,Power BI,PBIK64,2026-12-02,Thứ 2 - Thứ 4,,,Fixed,"lớp K54, K58, K59 lên"
3,Power Query,PBIK65,21/12/2026 và 23/12/2026,Thứ 2 - Thứ 4,2026-12-23,,Dự kiến,sau lớp K62
"""


def test_build_google_sheet_csv_url():
    url = "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz123456/edit?gid=987654#gid=987654"
    assert build_google_sheet_csv_url(url) == (
        "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz123456/export?format=csv&gid=987654"
    )
    apps_script = "https://script.google.com/macros/s/AKfycbx123/exec"
    assert build_google_sheet_csv_url(apps_script) == apps_script


def test_parse_class_schedule_csv():
    events = parse_class_schedule_csv(SAMPLE_CSV)
    # 2 sessions from PBIK48 + 3 sessions from PBIK63 + 2 planned (PBIK64, PBIK65)
    assert len(events) == 7, f"Expected 7 events, got {len(events)}: {events}"

    nov26 = [e for e in events if e["date"] == "2026-11-26"][0]
    assert nov26["course_code"] == "PBIK63"
    assert nov26["course_type"] == "Power Query"
    assert nov26["session_label"] == "Buổi 2"
    assert nov26["instructor"] == "a Tuấn Anh"
    assert nov26["assistants"] == ["Liên", "Đạt", "Vượng", "Hiếu"]
    assert nov26["time_range"] == "19:30 - 21:30"

    pbik65 = [e for e in events if e["course_code"] == "PBIK65"][0]
    assert pbik65["is_planned"] is True
    assert pbik65["date"] == "2026-12-23"


def test_parse_class_schedule_xlsx():
    wb = Workbook()
    ws = wb.active
    ws.append(["Đang học", "LỊCH QUẢN LÝ LỚP HỌC - Khóa PBIK63 - Power Query"])
    ws.append(["Ngày học", "2026-11-26"])
    ws.append(["Thứ 3 - T5", "Buổi 2"])
    ws.append(["Giảng viên", "a Tuấn Anh"])
    ws.append(["Sĩ số", "Liên"])
    ws.append(["", "Đạt"])
    buf = io.BytesIO()
    wb.save(buf)
    events = parse_class_schedule_xlsx(buf.getvalue())
    assert len(events) == 1
    assert events[0]["course_code"] == "PBIK63"
    assert events[0]["assistants"] == ["Liên", "Đạt"]


if __name__ == "__main__":
    test_build_google_sheet_csv_url()
    test_parse_class_schedule_csv()
    test_parse_class_schedule_xlsx()
    print("All class_schedule parser tests passed!")
