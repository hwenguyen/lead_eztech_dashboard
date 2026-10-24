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

### 2026-10-09 — Đã hoàn thành
- Trang thống kê chăm sóc Lead Remind (`/api/leads/remind` + `RemindLeadTable.tsx`):
  - Hỗ trợ xem **Tất cả Lead** (8.700 khách) hoặc lọc riêng theo bất kỳ **Thẻ (Tag)** nào (`Remind`, `Có thông tin`, `Quan tâm sâu`,...).
  - Thêm dropdown chọn Thẻ (Tag) tự động quét toàn bộ 49 tags thực tế từ hệ thống.
  - Lọc theo từng nhân viên phụ trách, Fanpage, nhóm ngày cách tin nhắn cuối (`Hôm nay`, `1-3 ngày`, `4-7 ngày`, `> 7 ngày`), tìm kiếm Tên/SĐT.
  - Thêm In-Memory TTL Cache (60s) trên backend: các thao tác chuyển trang, lọc phụ đọc trực tiếp từ RAM (< 5ms), tốn 0 câu query phát sinh vào Neon DB.
  - Sắp xếp mặc định từ khoảng cách ngày gần nhất đến xa nhất (0 ngày -> 1 ngày -> 2 ngày...).
  - Thêm thẻ KPI tổng quan số lượng lead theo từng nhóm thời gian tương tác.
- Tích hợp link mở trực tiếp hội thoại Pancake (`https://pancake.vn/[page_slug]?c_id=[conversation_id]`):
  - Tham số `?c_id=` là mã hội thoại `conversation_id` (`RawConversation.pancake_id` / `FactLeadActivity.conversation_id`) để Pancake tự động cuộn đến hội thoại của khách.
  - Ánh xạ chuẩn xác toàn bộ 7 Fanpage sang Pancake slug:
    1. `Eztech Phân Tích Dữ Liệu`: `pzl_84377024368` (Zalo cá nhân SĐT +84377024368)
    2. `Anh Kế toán làm Data (TikTok)`: `tt_tuananhdata` (TikTok @tuananhdata)
    3. `Anh Kế toán làm Data (Facebook)`: `514400205095512` (Fanpage Facebook ID: 514400205095512)
    4. `Hiền Minh Eztech`: `pzl_84898276368` (Zalo cá nhân SĐT +84898276368)
    5. `Tuấn Anh Data`: `pzl_84389528224` (Zalo cá nhân SĐT +84389528224)
    6. `Hành trang cho kế toán`: `tt_anhgadata` (TikTok @anhgadata, chuẩn hoá thống nhất "Anh Gà Kế Toán" về "Hành trang cho kế toán")
    7. `Chị Kế Toán GenZ`: `tt_chiketoangenz` (TikTok @chiketoangenz)
  - Hiển thị nút "Mở Pancake" (`ExternalLink`) ở cả bảng Remind Lead và bảng Danh sách Lead (`LeadTable.tsx`).

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

### 2026-10-10 — Đã hoàn thành
- Thêm Fanpage Facebook mới: `514400205095512` (`Anh Kế toán làm Data (Facebook)`):
  - Phân biệt với kênh TikTok cùng tên `Anh Kế toán làm Data (TikTok)`.
  - Cấu hình access token và chạy first run ETL thành công (kéo toàn bộ 1.955 hội thoại lịch sử).
- Loại bỏ hoàn toàn Nhóm Chat Zalo (`pzl_g_...`) khỏi Backend & ETL:
  - **Nguyên nhân**: Zalo cá nhân (`pzl_`) có các nhóm chat lớp học, nhóm hỗ trợ mang tiền tố `pzl_g_...` (ví dụ `HVPBIK...`, `EzTech - Cộng đồng chia sẻ...`). Trước đây các nhóm này bị nhận nhầm là Lead cá nhân, SĐT chia sẻ trong nhóm bị tính là Lead có SĐT, và xuất hiện trong bảng Remind.
  - **Backend (`lead_metrics.py`, `main.py`)**:
    - Trong `_phone_owner_ids`: Lọc bỏ `~FactLeadActivity.conversation_id.like("pzl_g_%")` để số điện thoại trong group chat không bị đếm cho Lead.
    - Trong `classify_leads`: Lọc bỏ `~FactLeadActivity.conversation_id.like("pzl_g_%")` ở cả `active_lead_ids` và `query`, đồng thời chặn trong vòng lặp duyệt kết quả. Áp dụng cho toàn bộ 4 API: Summary, Trend, Leads List, Employees List.
    - Trong `get_remind_leads`: Lọc bỏ `~FactLeadActivity.conversation_id.like("pzl_g_%")` ở câu query và vòng lặp. Bảng Remind sạch 100% nhóm chat.
    - Trong `auto_repair_contacted_dates`: Bỏ qua các bản ghi có tiền tố `pzl_g_`.
  - **ETL (`pancake_client.py`, `pipeline.py`)**:
    - Lọc bỏ ngay tại `PancakeClient.get_conversations`: bỏ qua hội thoại nếu `conv_id.startswith("pzl_g_")` tương tự như lọc `COMMENT`, không tốn API request tải message.
    - Chốt chặn tại `upsert_lead_data` và vòng lặp `changed`: không lưu hội thoại `pzl_g_` vào DB.
  - **Kết quả**: Dữ liệu Zalo phản ánh đúng 100% khách hàng 1-1 cá nhân (ví dụ: `Tuấn Anh Data` từ 1.783 lead giảm về đúng 984 lead cá nhân; `Eztech Phân Tích Dữ Liệu` từ 2.008 lead về đúng 1.826 lead; `Hiền Minh Eztech` từ 1.262 lead về đúng 1.098 lead).

### 2026-10-16 — Đã hoàn thành
- Chuyển đổi và nâng cấp sang Project Neon mới (`muddy-term-83260316`):
  - Do Project cũ đạt 98.2% hạn mức Network Transfer Egress (5 GB/tháng).
  - Khôi phục an toàn 100% dữ liệu (12.122 bản ghi) sang Neon Project mới.
  - Cập nhật driver `postgresql+psycopg2://` và `pool_recycle=300` trong `database/db.py` để Neon compute tự động scale-to-zero khi không có traffic.

### 2026-10-19 — Đã hoàn thành
- Tích hợp Bot Tự Động Phản Hồi Tin Nhắn (Auto-Reply Bot):
  - Tệp cấu hình kịch bản: `etl/auto_reply_rules.py` hỗ trợ nhiều trường hợp linh hoạt (xin file tài liệu -> tin nhắn A, tham gia nhóm cộng đồng -> tin nhắn B, tư vấn khóa học -> tin nhắn C).
  - Tệp xử lý bot: `etl/auto_reply_bot.py` quét tin nhắn, khử dấu & HTML thông minh.
  - 3 Chốt chặn an toàn:
    1. Bỏ qua nếu tin nhắn cuối cùng đã có Admin/Nhân viên trả lời.
    2. Lưu vết vào bảng `bot_auto_replies` trong Neon DB để chống spam lặp lại (mỗi khách/kịch bản chỉ gửi 1 lần).
    3. Chỉ áp dụng cho các kênh Lead nguồn (Facebook, TikTok), bỏ qua các nhóm Zalo cá nhân.
  - Tích hợp vào GitHub Actions Workflow (`.github/workflows/pancake-etl.yml`): Tự động kích hoạt bot gửi tin nhắn sau mỗi lần chạy cào dữ liệu ETL.
  - Sửa lỗi Pancake Send Message API: Bổ sung trường bắt buộc `"action": "reply_inbox"` vào payload JSON theo đúng OpenAPI spec của Pancake Public API v1 (`/conversations/{conversation_id}/messages`).
  - Tối ưu chống Spam nền tảng (TikTok): Tăng độ trễ giữa các lần gửi lên ngẫu nhiên 6 – 12 giây (kèm cơ chế backoff 10 – 15 giây khi gặp lỗi) và giới hạn tối đa 2 lần thử đối với các tài khoản chặn tin nhắn riêng tư.

### 2026-10-20 — Đã hoàn thành
- Tạo bảng `comments` trên Neon Database và bổ sung ETL cào toàn bộ Comment từ kênh nguồn:
  - Model `Comment` trong `database/models.py`: lưu `comment_id`, `page_id`, `page_name`, `post_id`, `customer_id`, `customer_name`, `phone_number`, `message` (sạch), `raw_message` (HTML), `message_count`, `tags`, `assigned_users`, `inserted_at`, `updated_at`, `payload` (JSON).
  - Tự động tạo bảng và các index (`page_id`, `post_id`, `customer_id`, `inserted_at`, `phone_number`) qua `database/schema.py::ensure_schema()`.
  - Bổ sung hàm `PancakeClient.get_comments(...)` trong `etl/pancake_client.py`: cào comment qua Pancake API v2, hỗ trợ Early Stopping (`days_back`), cache `updated_at`, và ThreadPool tải tin nhắn song song.
  - Tích hợp vào luồng ETL chính `etl/pipeline.py`: tự động nhận diện kênh nguồn (Facebook Fanpage, TikTok) và lưu comment vào bảng `comments` (hoàn toàn tách biệt khỏi `dim_leads` để không làm sai lệch chỉ số Lead).
- Bổ sung luồng tự động trả lời bình luận (Comment Auto-Reply) theo mô hình Smart Combo (DM + Rep Comment):
  - Thêm `should_reply_comment()` và `process_page_comment_replies()` trong `etl/auto_reply_bot.py`.
  - Thêm danh sách cấu hình riêng `COMMENT_REPLY_RULES` trong `etl/auto_reply_rules.py` (hỗ trợ `private_message`, `comment_success_message`, `comment_fallback_message`).
  - Cơ chế Smart Combo:
    1. Thử gửi tin nhắn riêng (Private Message / DM) vào Inbox của khách qua Pancake API (`action="private_replies"`).
    2. Nếu gửi DM thành công (khách mở DM / Facebook): Rep comment công khai thông báo kiểm tra tin nhắn chờ (`comment_success_message`).
    3. Nếu gửi DM thất bại (khách TikTok khóa DM): Rep comment công khai điều hướng khách chủ động bấm nhắn tin hoặc để lại SĐT (`comment_fallback_message`).
  - Kiểm tra điều kiện an toàn: chỉ reply comment gần đây (`days_back=1`), thread chưa có admin trả lời (`message_count <= 1`), chưa từng reply trước đó (`bot_auto_replies`), và khớp từ khóa trong `COMMENT_REPLY_RULES`.
  - Chốt chặn khách cũ (`SKIP_IF_CUSTOMER_HAS_PRIOR_MESSAGES = True`): Tự động quét và đối chiếu định danh khách (`customer_id`, `psid`, SĐT); nếu khách đã có tin nhắn trao đổi từ trước trong Inbox (`raw_conversations`) hoặc đã từng được bot gửi tin nhắn thành công (`bot_auto_replies`), bot sẽ **bỏ qua hoàn toàn** (không gửi DM và không rep comment) để tránh spam khách cũ.
  - Tích hợp trực tiếp vào bước cào comment trong `etl/pipeline.py`, tự động chạy sau khi lưu comment vào DB.
  - Hỗ trợ chạy thủ công qua CLI `etl/auto_reply_bot.py --send --comments-only`.


### 2026-10-24 — Đã hoàn thành
- Chuyển đổi biểu đồ SĐT thu được:
  - Thay thế biểu đồ "SĐT thu được / Nhân viên" thành biểu đồ tròn "SĐT thu được / Lead Other & Đào tạo" (`phone_tag_stats`) thể hiện cơ cấu SĐT thu được giữa các nhóm phân loại Lead Other, Đào tạo (và Other).
  - Cập nhật backend `backend/main.py` và `backend/schemas.py`: tính toán `phone_tag_stats` cho các lead có SĐT thu được theo phân loại tag.
  - Cập nhật frontend `StatsPieChart.tsx`: thêm thuộc tính `unit` tùy biến đơn vị tooltip (`SĐT` thay vì mặc định `Lead`).
  - Đổi tên biểu đồ thứ 3 thành "Tổng Lead / Lead Other & Đào tạo" để phân biệt rõ ràng giữa SĐT thu được và Tổng số Lead.
  - Thêm bộ lọc cho biểu đồ SĐT thu được (`headerAction`): cho phép chuyển đổi nhanh giữa **Tổng SĐT**, **SĐT Mới** (`new_phone_tag_stats`), và **SĐT Contact lại** (`recontact_phone_tag_stats`).

### Bước tiếp / tồn đọng (chưa xử lý, chờ user quyết)
- Cập nhật link nhóm Zalo thực tế vào `etl/auto_reply_rules.py` (hiện đang là link placeholder).
- **Token Pancake**: run ETL 03/10 04:54Z báo `Invalid access_token (102)` cho page "Anh Kế toán làm Data" → kéo 0 hội thoại nhưng job vẫn xanh. Cần tạo lại token; nên cho job fail khi một page lỗi.
- `contacted_dates` cộng cả ngày `updated_at` của hội thoại (`etl/pipeline.py`) → Contact Lại có thể gồm hội thoại chỉ đổi tag.
- ETL chỉ lưu 30 tin gần nhất và ghi đè `contacted_dates` mỗi lần tải lại → lịch sử contact của hội thoại dài mất dần (chủ yếu page Zalo). Lỗi tải tin nhắn trả `[]` cũng xoá tin đã lưu.
- `customer_id = 'unknown'` gộp mọi hội thoại thiếu id khách vào 1 lead; giới hạn 500/2000 hội thoại áp trước khi lọc COMMENT.
- Page "user5025817249978" chưa có tên chuẩn; hai page TikTok "Anh Gà Kế Toán" và page này chưa gắn tag Lead Other/Đào tạo.
- `auto_repair_contacted_dates` load toàn bộ raw payload vào RAM mỗi lần startup (512MB) → rủi ro khi data lớn.
- Deps trong `requirements.txt` chưa pin (Render dùng Python 3.14).

### Quyết định & lý do
- SĐT "thu được trong kỳ" thay cho "lead có SĐT bất kỳ lúc nào": cách cũ ra 2.839 SĐT cho tháng 9 vì đếm lại số cũ mỗi khi lead được nhắn (tin hàng loạt trên Zalo) và đếm trùng TikTok–Zalo.
- Page Zalo không cộng vào tổng: cùng một người vừa là lead TikTok vừa là bạn Zalo → đếm 2 lần.
- Gom tag cũ vào Lead Other/Đào tạo để số liệu trước cuối tháng 9 vẫn có ý nghĩa.
- Ghi rõ driver psycopg2 trong URL thay vì pin SQLAlchemy: chạy được cả 2.0 (Actions, Py3.10) lẫn 2.1 (Render, Py3.14).
- Test local: venv trong Temp bị Application Control chặn DLL → chạy với `DISABLE_SQLALCHEMY_CEXT_RUNTIME=1 PYTHONUTF8=1`.
