"""
Parser & đồng bộ Lịch quản lý lớp học từ Google Sheet (CSV export) hoặc CSV text.
Lưu cấu hình + cache đã parse vào bảng `app_configs` (key: CLASS_SCHEDULE_SHEET_CONFIG)
kèm in-memory TTL cache để giảm tải Neon DB và Google Sheets.
"""

import csv
import io
import json
import logging
import re
import threading
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
from openpyxl import load_workbook
from sqlalchemy.orm import Session

from database.models import AppConfig, get_vn_now

logger = logging.getLogger("ClassSchedule")

CLASS_SCHEDULE_CONFIG_KEY = "CLASS_SCHEDULE_SHEET_CONFIG"
_CACHE_LOCK = threading.Lock()
_MEMORY_CACHE: Optional[Tuple[float, Dict[str, Any]]] = None
_MEMORY_CACHE_TTL = 300.0  # 5 phút
_AUTO_SYNC_LOCK = threading.Lock()
_LAST_AUTO_SYNC_ATTEMPT = 0.0
_AUTO_SYNC_RUNNING = False


def clear_class_schedule_cache() -> None:
    global _MEMORY_CACHE
    with _CACHE_LOCK:
        _MEMORY_CACHE = None


def build_google_sheet_csv_url(sheet_url: str) -> str:
    """
    Chuyển URL Google Sheet bất kỳ hoặc Google Apps Script Web App thành URL tải CSV trực tiếp.
    - Nếu là Apps Script (`script.google.com/macros/...`), giữ nguyên URL (hỗ trợ Sheet Private).
    - Nếu là Google Sheet URL, giữ nguyên `gid` nếu có trong query hoặc hash `#gid=...`.
    """
    raw = (sheet_url or "").strip()
    if not raw:
        return ""

    if "script.google.com/macros/" in raw or "export?format=csv" in raw or "output=csv" in raw:
        return raw

    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", raw)
    if not m:
        # Nếu user truyền thẳng spreadsheet ID
        if re.fullmatch(r"[a-zA-Z0-9_-]{20,}", raw):
            return f"https://docs.google.com/spreadsheets/d/{raw}/export?format=csv&gid=0"
        return raw

    sheet_id = m.group(1)
    gid_match = re.search(r"[?&#]gid=(\d+)", raw)
    gid = gid_match.group(1) if gid_match else "0"
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def _parse_date_str(val: str) -> Optional[str]:
    """Chuẩn hóa ngày về YYYY-MM-DD (hỗ trợ YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY)."""
    s = (val or "").strip()
    if not s:
        return None
    m_iso = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m_iso:
        y, m, d = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{m:02d}-{d:02d}"
    m_vn = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", s)
    if m_vn:
        d, m, y = int(m_vn.group(1)), int(m_vn.group(2)), int(m_vn.group(3))
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{m:02d}-{d:02d}"
    return None


def _infer_course_meta(header_text: str) -> Tuple[str, str, str]:
    """Trích (course_code, course_type, course_name) từ tiêu đề block."""
    clean = re.sub(r"\s+", " ", (header_text or "").strip())
    clean = re.sub(r"^LỊCH QUẢN LÝ LỚP HỌC\s*[-–:]?\s*", "", clean, flags=re.IGNORECASE).strip()
    code_match = re.search(r"\b(PBI\s*K\d+|K\d+)\b", clean, flags=re.IGNORECASE)
    course_code = code_match.group(1).replace(" ", "").upper() if code_match else clean[:20]

    lower = clean.lower()
    if "power query" in lower:
        course_type = "Power Query"
    elif "power bi" in lower or "pbi" in lower:
        course_type = "Power BI"
    elif "ai" in lower:
        course_type = "AI"
    else:
        course_type = "Khác"

    return course_code, course_type, clean or course_code


def _infer_time_range(schedule_days: str) -> str:
    s = (schedule_days or "").lower()
    if "thứ 7" in s and not any(k in s for k in ("thứ 2", "thứ 3", "thứ 4", "thứ 5", "thứ 6", "t2", "t3", "t4", "t5", "t6")):
        return "14:00 - 17:00"
    return "19:30 - 21:30"


def parse_class_schedule_csv(csv_text: str) -> List[Dict[str, Any]]:
    """Parse nội dung CSV từ sheet 'LỊCH QUẢN LÝ LỚP HỌC' thành danh sách buổi học chuẩn hóa."""
    if not csv_text or not csv_text.strip():
        return []
    rows = list(csv.reader(io.StringIO(csv_text.lstrip("\ufeff"))))
    return parse_class_schedule_rows(rows)


def _excel_cell_to_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, date):
        return val.strftime("%Y-%m-%d")
    return str(val).strip()


def parse_class_schedule_xlsx(file_bytes: bytes) -> List[Dict[str, Any]]:
    """Parse file Excel (.xlsx) tải từ Google Sheet thành danh sách buổi học chuẩn hóa."""
    wb = load_workbook(filename=io.BytesIO(file_bytes), data_only=True, read_only=True)
    try:
        all_events: List[Dict[str, Any]] = []
        seen_ids = set()
        for ws in wb.worksheets:
            rows = [[_excel_cell_to_str(cell) for cell in row] for row in ws.iter_rows(values_only=True)]
            parsed = parse_class_schedule_rows(rows)
            for ev in parsed:
                if ev["id"] not in seen_ids:
                    seen_ids.add(ev["id"])
                    all_events.append(ev)
        all_events.sort(key=lambda x: (x["date"], x["course_code"], x["session_label"]))
        return all_events
    finally:
        wb.close()


def parse_class_schedule_rows(rows: List[List[str]]) -> List[Dict[str, Any]]:
    """
    Parse ma trận dòng (từ CSV hoặc XLSX) có các block 'LỊCH QUẢN LÝ LỚP HỌC'
    thành danh sách buổi học chuẩn hóa.
    """
    if not rows:
        return []

    events: List[Dict[str, Any]] = []
    seen_keys = set()
    courses_with_sessions = set()

    n = len(rows)
    i = 0
    while i < n:
        row = rows[i]
        c0 = (row[0] if len(row) > 0 else "").strip()
        c1 = (row[1] if len(row) > 1 else "").strip()

        # Nhận diện đầu block LỊCH QUẢN LÝ LỚP HỌC
        is_block_start = False
        block_status = ""
        block_title = ""

        if c1.upper().startswith("LỊCH QUẢN LÝ LỚP HỌC"):
            is_block_start = True
            block_status = c0 or "Đang học"
            block_title = c1
        elif c0.upper().startswith("LỊCH QUẢN LÝ LỚP HỌC"):
            is_block_start = True
            block_status = "Đang học"
            block_title = c0

        if is_block_start:
            # Quét tối đa 15 dòng tiếp theo trong block này
            j = i + 1
            date_row: List[str] = []
            session_row: List[str] = []
            instructor_row: List[str] = []
            course_label_from_session = ""
            assistant_rows: List[List[str]] = []

            while j < n:
                r = rows[j]
                r0 = (r[0] if len(r) > 0 else "").strip()
                r1 = (r[1] if len(r) > 1 else "").strip()

                if r1.upper().startswith("LỊCH QUẢN LÝ LỚP HỌC") or r0.upper().startswith("LỊCH QUẢN LÝ LỚP HỌC"):
                    break
                if r0.upper() == "STT" and ("KHOÁ HỌC" in r1.upper() or "KHÓA HỌC" in r1.upper()):
                    break
                if r0.upper().startswith("KỊCH BẢN CHĂM SÓC"):
                    break
                # Dòng trống hoàn toàn -> kết thúc block (trừ khi chưa thấy date/session nào)
                if not any(cell.strip() for cell in r):
                    if date_row or session_row:
                        break
                    j += 1
                    continue

                if r0.lower() == "ngày học" and not date_row:
                    date_row = r
                elif any(re.match(r"^Buổi\s+\d+", cell.strip(), re.IGNORECASE) for cell in r[1:]):
                    session_row = r
                elif r0.lower() == "giảng viên":
                    instructor_row = r
                elif r0.lower().startswith("khóa ") or r0.lower().startswith("khoá "):
                    course_label_from_session = r0
                    assistant_rows.append(r)
                elif date_row or session_row:
                    assistant_rows.append(r)

                j += 1

            # Xử lý dữ liệu block vừa gom được
            header_source = block_title if "khóa" in block_title.lower() or "khoá" in block_title.lower() or "pbi" in block_title.lower() else course_label_from_session
            if header_source and date_row:
                course_code, course_type, course_name = _infer_course_meta(header_source)
                schedule_days = (session_row[0] if session_row else "").strip()
                time_range = _infer_time_range(schedule_days)

                max_cols = max(len(date_row), len(session_row), len(instructor_row))
                for col in range(1, max_cols):
                    raw_date = date_row[col] if col < len(date_row) else ""
                    iso_date = _parse_date_str(raw_date)
                    if not iso_date:
                        continue

                    session_label = (session_row[col] if col < len(session_row) else "").strip() or f"Buổi {col}"
                    instructor = (instructor_row[col] if col < len(instructor_row) else "").strip()

                    assistants: List[str] = []
                    notes: List[str] = []
                    for ar in assistant_rows:
                        val = (ar[col] if col < len(ar) else "").strip()
                        if not val:
                            continue
                        if val.lower().startswith("học "):
                            notes.append(val)
                        elif val not in assistants:
                            assistants.append(val)

                    dedup_key = (course_code, iso_date, session_label)
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)
                    courses_with_sessions.add(course_code)

                    events.append({
                        "id": f"cls_{course_code}_{iso_date}_{col}",
                        "date": iso_date,
                        "time_range": time_range,
                        "course_code": course_code,
                        "course_type": course_type,
                        "course_name": course_name,
                        "session_label": session_label,
                        "schedule_days": schedule_days,
                        "status": block_status or "Đang học",
                        "instructor": instructor,
                        "assistants": assistants,
                        "note": ", ".join(notes),
                        "is_planned": False,
                    })

            i = j
            continue

        # Nhận diện bảng Dự kiến khai giảng: STT,Khoá học,Mã lớp,Dự kiến khai giảng,...
        if c0.upper() == "STT" and ("KHOÁ HỌC" in c1.upper() or "KHÓA HỌC" in c1.upper()):
            j = i + 1
            while j < n:
                r = rows[j]
                r0 = (r[0] if len(r) > 0 else "").strip()
                if not any(cell.strip() for cell in r) or r0.upper().startswith("KỊCH BẢN"):
                    break
                if len(r) >= 4:
                    c_type = (r[1] if len(r) > 1 else "").strip()
                    c_code = (r[2] if len(r) > 2 else "").strip().upper()
                    raw_open = (r[3] if len(r) > 3 else "").strip()
                    sched_days = (r[4] if len(r) > 4 else "").strip()
                    alt_date = (r[5] if len(r) > 5 else "").strip()
                    instr = (r[6] if len(r) > 6 else "").strip()
                    st = (r[7] if len(r) > 7 else "").strip() or "Dự kiến"
                    note = (r[8] if len(r) > 8 else "").strip()

                    if c_code and c_code not in courses_with_sessions:
                        iso_date = _parse_date_str(raw_open) or _parse_date_str(alt_date)
                        if iso_date:
                            dedup_key = (c_code, iso_date, "Dự kiến khai giảng")
                            if dedup_key not in seen_keys:
                                seen_keys.add(dedup_key)
                                events.append({
                                    "id": f"plan_{c_code}_{iso_date}",
                                    "date": iso_date,
                                    "time_range": _infer_time_range(sched_days),
                                    "course_code": c_code,
                                    "course_type": c_type or "Khác",
                                    "course_name": f"Khóa {c_code} - {c_type}".strip(" -"),
                                    "session_label": "Dự kiến khai giảng",
                                    "schedule_days": sched_days,
                                    "status": st,
                                    "instructor": instr,
                                    "assistants": [],
                                    "note": note,
                                    "is_planned": True,
                                })
                j += 1
            i = j
            continue

        i += 1

    events.sort(key=lambda x: (x["date"], x["course_code"], x["session_label"]))
    return events


def get_class_schedule_data(db: Session) -> Dict[str, Any]:
    """Đọc dữ liệu lịch lớp đã cache (in-memory TTL -> DB app_configs)."""
    global _MEMORY_CACHE
    now_ts = time.time()
    with _CACHE_LOCK:
        if _MEMORY_CACHE and (now_ts - _MEMORY_CACHE[0] < _MEMORY_CACHE_TTL):
            return _MEMORY_CACHE[1]

    default_data: Dict[str, Any] = {
        "sheet_url": "",
        "csv_export_url": "",
        "auto_sync_enabled": True,
        "sync_interval_minutes": 15,
        "last_synced_at": None,
        "last_sync_error": None,
        "events": [],
    }
    row = db.query(AppConfig).filter(AppConfig.config_key == CLASS_SCHEDULE_CONFIG_KEY).first()
    if row and row.config_value:
        try:
            loaded = json.loads(row.config_value)
            if isinstance(loaded, dict):
                default_data = {**default_data, **loaded}
        except Exception as e:
            logger.warning(f"Lỗi parse {CLASS_SCHEDULE_CONFIG_KEY}: {e}")

    with _CACHE_LOCK:
        _MEMORY_CACHE = (now_ts, default_data)
    return default_data


def _save_class_schedule_data(db: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    global _MEMORY_CACHE
    serialized = json.dumps(payload, ensure_ascii=False)
    row = db.query(AppConfig).filter(AppConfig.config_key == CLASS_SCHEDULE_CONFIG_KEY).first()
    if row:
        row.config_value = serialized
        row.updated_at = get_vn_now()
    else:
        db.add(AppConfig(config_key=CLASS_SCHEDULE_CONFIG_KEY, config_value=serialized))
    db.commit()

    with _CACHE_LOCK:
        _MEMORY_CACHE = (time.time(), payload)
    return payload


def sync_class_schedule(
    db: Session,
    sheet_url: Optional[str] = None,
    csv_text: Optional[str] = None,
    auto_sync_enabled: Optional[bool] = None,
    sync_interval_minutes: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Đồng bộ lịch lớp học từ Google Apps Script / Google Sheet URL hoặc từ CSV text dán tay.
    """
    current = get_class_schedule_data(db)
    target_url = (sheet_url if sheet_url is not None else current.get("sheet_url") or "").strip()
    export_url = build_google_sheet_csv_url(target_url) if target_url else ""
    next_auto = current.get("auto_sync_enabled", True) if auto_sync_enabled is None else bool(auto_sync_enabled)
    next_interval = int(
        sync_interval_minutes
        if sync_interval_minutes is not None
        else (current.get("sync_interval_minutes") or 15)
    )
    next_interval = max(5, min(next_interval, 1440))

    raw_csv = (csv_text or "").strip()
    if not raw_csv:
        if not export_url:
            raise ValueError("Chưa cấu hình URL Google Apps Script / Google Sheet hoặc nội dung CSV.")
        try:
            resp = requests.get(export_url, timeout=20, allow_redirects=True)
            resp.raise_for_status()
            content_type = (resp.headers.get("content-type") or "").lower()
            if "text/html" in content_type and "accounts.google.com" in str(resp.url):
                raise ValueError(
                    "URL bị chặn đăng nhập Google. Nếu Sheet đang Private, hãy dùng Google Apps Script Web App (Execute as: Me, Who has access: Anyone)."
                )
            resp.encoding = resp.encoding or "utf-8"
            raw_csv = resp.text
        except requests.RequestException as exc:
            raise ValueError(f"Không tải được dữ liệu từ Google Sheet / Apps Script: {exc}") from exc

    events = parse_class_schedule_csv(raw_csv)
    if not events:
        raise ValueError(
            "Không tìm thấy dữ liệu lịch lớp hợp lệ (kiểm tra lại tên sheet hoặc định dạng 'LỊCH QUẢN LÝ LỚP HỌC')."
        )

    synced_at = get_vn_now().strftime("%Y-%m-%d %H:%M:%S")
    updated = {
        "sheet_url": target_url,
        "csv_export_url": export_url,
        "auto_sync_enabled": next_auto,
        "sync_interval_minutes": next_interval,
        "last_synced_at": synced_at,
        "last_sync_error": None,
        "events": events,
    }
    return _save_class_schedule_data(db, updated)


def trigger_background_auto_sync_if_due(db_session_factory) -> None:
    """
    Kiểm tra nhẹ nhàng xem đã đến hạn tự động đồng bộ lịch lớp chưa.
    Nếu đến hạn và có cấu hình URL + bật auto_sync_enabled -> chạy đồng bộ ở background thread.
    """
    global _LAST_AUTO_SYNC_ATTEMPT, _AUTO_SYNC_RUNNING
    now_ts = time.time()

    with _AUTO_SYNC_LOCK:
        if _AUTO_SYNC_RUNNING:
            return
        # Tối thiểu 60s mới kiểm tra lại 1 lần để tránh spam
        if now_ts - _LAST_AUTO_SYNC_ATTEMPT < 60.0:
            return
        _LAST_AUTO_SYNC_ATTEMPT = now_ts

    # Kiểm tra nhanh từ memory cache nếu đã có
    cached_cfg: Optional[Dict[str, Any]] = None
    with _CACHE_LOCK:
        if _MEMORY_CACHE:
            cached_cfg = _MEMORY_CACHE[1]

    if cached_cfg is not None:
        if not cached_cfg.get("auto_sync_enabled", True) or not (cached_cfg.get("sheet_url") or "").strip():
            return
        interval_sec = max(5, int(cached_cfg.get("sync_interval_minutes") or 15)) * 60
        last_str = cached_cfg.get("last_synced_at")
        if last_str:
            try:
                last_dt = datetime.strptime(last_str, "%Y-%m-%d %H:%M:%S")
                now_vn = get_vn_now().replace(tzinfo=None)
                if (now_vn - last_dt).total_seconds() < interval_sec:
                    return
            except Exception:
                pass

    def _run():
        global _AUTO_SYNC_RUNNING
        with _AUTO_SYNC_LOCK:
            if _AUTO_SYNC_RUNNING:
                return
            _AUTO_SYNC_RUNNING = True
        try:
            with db_session_factory() as db:
                cfg = get_class_schedule_data(db)
                if not cfg.get("auto_sync_enabled", True) or not (cfg.get("sheet_url") or "").strip():
                    return
                interval_sec = max(5, int(cfg.get("sync_interval_minutes") or 15)) * 60
                last_str = cfg.get("last_synced_at")
                if last_str:
                    try:
                        last_dt = datetime.strptime(last_str, "%Y-%m-%d %H:%M:%S")
                        now_vn = get_vn_now().replace(tzinfo=None)
                        if (now_vn - last_dt).total_seconds() < interval_sec:
                            return
                    except Exception:
                        pass
                sync_class_schedule(db)
                logger.info("Auto-sync lịch lớp học từ Google Apps Script thành công.")
        except Exception as exc:
            logger.warning(f"Auto-sync lịch lớp học lỗi: {exc}")
        finally:
            with _AUTO_SYNC_LOCK:
                _AUTO_SYNC_RUNNING = False

    threading.Thread(target=_run, daemon=True, name="ClassScheduleAutoSync").start()


def sync_class_schedule_from_file(
    db: Session,
    filename: str,
    file_bytes: bytes,
) -> Dict[str, Any]:
    """Import lịch lớp trực tiếp từ file .csv hoặc .xlsx (dành cho Google Sheet Private)."""
    lower = (filename or "").lower()
    if lower.endswith(".xlsx") or lower.endswith(".xlsm"):
        events = parse_class_schedule_xlsx(file_bytes)
    elif lower.endswith(".csv"):
        try:
            text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = file_bytes.decode("latin-1")
        events = parse_class_schedule_csv(text)
    else:
        raise ValueError("Chỉ hỗ trợ file .xlsx hoặc .csv xuất từ Google Sheet.")

    if not events:
        raise ValueError("Không tìm thấy dữ liệu 'LỊCH QUẢN LÝ LỚP HỌC' hợp lệ trong file vừa tải lên.")

    current = get_class_schedule_data(db)
    synced_at = get_vn_now().strftime("%Y-%m-%d %H:%M:%S")
    updated = {
        "sheet_url": current.get("sheet_url") or "",
        "csv_export_url": current.get("csv_export_url") or "",
        "last_synced_at": synced_at,
        "last_sync_error": None,
        "events": events,
    }
    return _save_class_schedule_data(db, updated)
