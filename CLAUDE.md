# Lead EzTech Dashboard

FastAPI backend (`backend/`) + React frontend (`frontend-react/`) trên Render (free tier), DB Neon Postgres, ETL Pancake chạy GitHub Actions (`.github/workflows/pancake-etl.yml`, Python 3.10). Logic đếm lead nằm duy nhất ở `backend/lead_metrics.py`.

## Định nghĩa chỉ số (đã chốt với user 2026-10-03)
| Chỉ số | Định nghĩa |
|---|---|
| Lead Mới | `first_created_at` trong kỳ |
| Lead Contact Lại | Lead tạo TRƯỚC kỳ, có tin nhắn (khách hoặc nhân viên) trong kỳ |
| Tổng Lead | Mới + Contact Lại (không trùng) |
| SĐT thu được | Mỗi số tính 1 lần, vào thời điểm khách gửi số lần đầu (`dim_leads.phone_at`; NULL thì dùng `first_created_at`), gộp trùng theo số đã chuẩn hoá giữa các page đang chọn |
| SĐT Mới / SĐT Contact Lại | SĐT từ Lead Mới (tạo trong kỳ có SĐT hoặc tag "đã add") / SĐT từ Lead Contact Lại (lead cũ tương tác lại trong kỳ và có SĐT/tag) |
| SĐT / Tạo mới | SĐT Mới / Lead Mới (%) |
| Lead Other / Đào tạo | Khớp chính xác tên tag: Lead Other = Lead Other + Support Other + HV Khác; Đào tạo = Đào tạo + HV TCKT |

- **Phạm vi page**: không chọn page ("Tất cả page nguồn lead") → mọi page TRỪ page Zalo. Page Zalo (kênh chăm sóc sau khi có SĐT) chỉ xem khi chọn riêng. Page Zalo nhận diện qua key `pzl_` trong `KNOWN_PAGE_NAMES` (`etl/utils.py`) → **page Zalo mới phải khai báo ở đó**.
- Hội thoại chưa phân nhân viên tính cho "Chưa phân công"; cờ gộp theo LEAD, không theo hội thoại.
- SĐT: tính cho mọi lead có `has_phone` (có số điện thoại lưu trong `phone_number` hoặc gắn tag "đã add"). SĐT Mới tính cho Lead Mới trong kỳ; SĐT Contact Lại tính cho mọi Lead Contact Lại có SĐT trong kỳ.
- Trend: phân loại Mới/Contact Lại theo cả kỳ để tổng theo ngày khớp KPI; `phone_leads` theo ngày = số lead có SĐT hoạt động ngày đó.
- Thay đổi schema DB đi qua `database/schema.py::ensure_schema()` (gọi ở backend startup và đầu ETL).

## Session

### 2026-10-07 — Đã hoàn thành
- Lưu thời gian gắn tag của từng lead (`tag_timeline`):
  - Lấy trường `tag_histories` từ Pancake API v2 (`/pages/{page_id}/conversations`), bóc tách danh sách sự kiện gắn/gỡ tag: `tag`, `action`, `tagged_at`, `editor`.
  - Thêm cột `tag_timeline` (JSON / JSONB) vào model `FactLeadActivity` và auto-migration trong `database/schema.py`.
  - Cập nhật ETL `etl/pipeline.py` để lưu `tag_timeline` vào DB.
  - Cập nhật backend `backend/schemas.py`, `backend/lead_metrics.py`, `backend/main.py` trả về `tag_timeline` trong API `/api/leads/list`.
  - Cập nhật Frontend `LeadTable.tsx` hiển thị thời gian gắn tag (ví dụ: `05/10 09:32`) và hover tooltip (`Gắn lúc: 05/10/2026 09:32 bởi Nguyen Gia Huy`).

### 2026-10-05 — Đã hoàn thành
- Tối ưu GitHub Actions ETL & Quota:
  - Tạo `requirements-etl.txt` (loại bỏ streamlit, plotly, fastapi, pandas khỏi workflow ETL), bật cache `cache: 'pip'`.
  - Fix thiếu `import re` trong `etl/pancake_client.py`.
  - Thêm cơ chế Early Stopping (`days_back=3`, `DAILY_RUN_LIMIT=1000`) trong `PancakeClient.get_conversations`: dừng cào ngay khi gặp hội thoại cũ hơn 3 ngày thay vì quét cố định 500 bản ghi.
  - Tối ưu cache DB: giới hạn 1.500 bản ghi gần nhất và dùng `count()` để check first run thay vì kéo toàn bộ payload vào RAM.
  - Tăng tần suất lên 5 lần/ngày (08:00, 12:00, 16:00, 20:00, 00:00 VN). Ước tính ban đầu ~1 phút/lần là SAI: run thực tế 37m27s.
- Tối ưu lần 2 & Lọc tin nhắn mỗi ngày:
  - Lọc bỏ `COMMENT` ngay tại `pancake_client.py`: Pancake trả về cả comment bài viết; trước đây code kéo cả trăm comment, gọi API tải messages cho từng comment rồi qua `pipeline.py` mới vứt đi → lãng phí hàng nghìn request và gây nghẽn 37 phút. Giờ chỉ lấy đúng TIN NHẮN (Message/Inbox).
  - Giới hạn tin nhắn mỗi ngày: `DAILY_DAYS_BACK = 1` (chỉ lấy tin nhắn phát sinh trong 24h gần nhất thay vì 3 ngày), `DAILY_RUN_LIMIT = 200` (đủ cho số lượng khách nhắn trong ngày của 1 page).
  - Ghi DB theo lô: `prefetch_records()` nạp sẵn raw/lead/activity bằng `IN (...)`, bỏ 3 SELECT + flush mỗi hội thoại.
  - Bỏ qua hội thoại có payload giống hệt bản đã lưu → không ghi DB.
  - Cache DB chỉ nạp cho đúng ID API trả về (`cache_loader`), không kéo 1.500 payload/page.
  - Tải tin nhắn lỗi → giữ tin cũ + `updated_at` cũ (lần sau tải lại), không ghi đè `[]`.
  - Lịch chạy mới: Mỗi 15 phút trong giờ làm việc (08:00 - 18:00 VN) + 1 lần chốt số lúc 00:00 VN (~42 lần/ngày = ~1.260 phút/tháng, còn dư ~740 phút trên tổng 2.000 phút quota GitHub Free).
  - Log thời gian từng bước (liệt kê / cache / tải tin / ghi DB); workflow `timeout-minutes: 10` + `concurrency`.
- Tối ưu Backend & In-Memory TTL Cache (Tăng tốc tải trang Web):
  - Khắc phục nghẽn RAM/CPU lúc khởi động trên Render: bỏ `ensure_schema()` ở cấp top-level import (chuyển vào `startup_event()` try/catch).
  - Ngừng chạy mặc định `auto_repair_contacted_dates()` mỗi lần Render bật dậy: chỉ chạy khi có biến môi trường `RUN_AUTO_REPAIR=true` hoặc gọi thủ công qua API `POST /api/admin/repair`.
  - In-memory TTL Cache cho `classify_leads` (45 giây, thread-safe): Khi React Dashboard mở lên gọi đồng thời 4 API (`/api/metrics/summary`, `/api/metrics/trend`, `/api/leads/list`, `/api/employees/list`), API đầu tiên tính toán và lưu cache, 3 API sau trả về ngay lập tức từ RAM (< 1ms), giảm 75% tải truy vấn lên Neon DB.
  - Caching 5 phút cho `/api/pages/list`: Giảm thiểu query distinct page_id liên tục.
  - Bổ sung admin endpoints: `POST /api/admin/clear-cache` và `POST /api/admin/repair`.

### 2026-10-03 — Đã hoàn thành
- Đổi cách tính SĐT sang "thu được trong kỳ" (thêm cột `phone_at`, chuẩn hoá số, gộp trùng), loại page Zalo khỏi tổng, tag khớp chính xác, thêm thẻ KPI "SĐT / Tạo mới" (6 thẻ, 3×2).
- `auto_repair_contacted_dates`: phần SĐT không còn xoá/ghi đè số (payload chỉ còn 30 tin gần nhất), chỉ chuẩn hoá + backfill `phone_at`.
- ETL: tin nhắn lấy từ cache không bị format lại (trước đó mất role → tin Admin bị quét SĐT như tin khách); regex SĐT bỏ qua chuỗi ngày giờ.

### 2026-10-02 — Đã hoàn thành
- PR #1: gom logic đếm vào `backend/lead_metrics.py`, tách Contact Lại + Tổng Lead, lọc nhân viên khớp chính xác, trend điền ngày trống.
- PR #2: ép driver `postgresql+psycopg2://` (SQLAlchemy 2.1 đổi mặc định) + `pool_pre_ping`; ETL đóng session trước khi cào.

### Bước tiếp / tồn đọng (chưa xử lý, chờ user quyết)
- **Token Pancake**: run ETL 03/10 04:54Z báo `Invalid access_token (102)` cho page "Anh Kế toán làm Data" → kéo 0 hội thoại nhưng job vẫn xanh. Cần tạo lại token; nên cho job fail khi một page lỗi.
- `contacted_dates` cộng cả ngày `updated_at` của hội thoại (`etl/pipeline.py`) → Contact Lại có thể gồm hội thoại chỉ đổi tag.
- ETL chỉ lưu 30 tin gần nhất và ghi đè `contacted_dates` mỗi lần tải lại → lịch sử contact của hội thoại dài mất dần (chủ yếu page Zalo). Lỗi tải tin nhắn trả `[]` cũng xoá tin đã lưu.
- `customer_id = 'unknown'` gộp mọi hội thoại thiếu id khách vào 1 lead; nhóm chat Zalo (`pzl_g_…`) bị tính là lead; giới hạn 500/2000 hội thoại áp trước khi lọc COMMENT.
- Page "user5025817249978" chưa có tên chuẩn; hai page TikTok "Anh Gà Kế Toán" và page này chưa gắn tag Lead Other/Đào tạo.
- `auto_repair_contacted_dates` load toàn bộ raw payload vào RAM mỗi lần startup (512MB) → rủi ro khi data lớn.
- Deps trong `requirements.txt` chưa pin (Render dùng Python 3.14).

### Quyết định & lý do
- SĐT "thu được trong kỳ" thay cho "lead có SĐT bất kỳ lúc nào": cách cũ ra 2.839 SĐT cho tháng 9 vì đếm lại số cũ mỗi khi lead được nhắn (tin hàng loạt trên Zalo) và đếm trùng TikTok–Zalo.
- Page Zalo không cộng vào tổng: cùng một người vừa là lead TikTok vừa là bạn Zalo → đếm 2 lần.
- Gom tag cũ vào Lead Other/Đào tạo để số liệu trước cuối tháng 9 vẫn có ý nghĩa.
- Ghi rõ driver psycopg2 trong URL thay vì pin SQLAlchemy: chạy được cả 2.0 (Actions, Py3.10) lẫn 2.1 (Render, Py3.14).
- Test local: venv trong Temp bị Application Control chặn DLL → chạy với `DISABLE_SQLALCHEMY_CEXT_RUNTIME=1 PYTHONUTF8=1`.
