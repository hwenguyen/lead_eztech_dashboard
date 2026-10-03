# Lead EzTech Dashboard

FastAPI backend (`backend/`) + React frontend (`frontend-react/`) trên Render (free tier), DB Neon Postgres, ETL Pancake chạy GitHub Actions (`.github/workflows/pancake-etl.yml`, Python 3.10). Logic đếm lead nằm duy nhất ở `backend/lead_metrics.py`.

## Định nghĩa chỉ số (đã chốt với user 2026-10-02)
| Chỉ số | Định nghĩa |
|---|---|
| Lead Mới | `first_created_at` trong kỳ |
| Lead Contact Lại | Lead tạo TRƯỚC kỳ, có tin nhắn (khách hoặc nhân viên) trong kỳ |
| Tổng Lead | Mới + Contact Lại (không trùng) |
| SĐT Mới / Contact Lại | Lead tương ứng có SĐT bất kỳ lúc nào (phone_number hoặc tag "Đã add"), đếm theo lead, không dedup số |

- Chỉ xét hội thoại đã phân nhân viên; cờ gộp theo LEAD, không theo hội thoại.
- SĐT chỉ trích từ tin nhắn của khách (bỏ tin Admin để không dính hotline).
- Trend: phân loại Mới/Contact Lại theo cả kỳ để tổng theo ngày khớp KPI.

## Session

### 2026-10-02 — Đã hoàn thành
- PR #1: gom logic đếm vào `backend/lead_metrics.py`, tách "Lead Liên Hệ" thành Contact Lại + Tổng Lead (5 KPI card), sửa regex/nguồn trích SĐT, lọc nhân viên khớp chính xác, trend điền ngày trống, prefilter SQL + index `contacted_at`, auto_repair đồng bộ `contacted_at`/`phone_number`. Thêm `.gitignore`, commit `package-lock.json`.
- PR #2: deploy backend lỗi do Render cài SQLAlchemy 2.1 (driver mặc định `psycopg` v3) → ép `postgresql+psycopg2://` + `pool_pre_ping`. ETL lỗi 30/09–01/10 do giữ connection qua >1h cào (Neon đóng) → `db.close()` trước khi cào.
- Đã xác nhận API live trả schema mới (25/09–02/10: Mới 297, Contact Lại 277, Tổng 574).

### Bước tiếp
- User kiểm tra UI (Ctrl+F5) với filter page/nhân viên.
- Chạy tay workflow "Pancake ETL Pipeline" để bù dữ liệu page "Eztech Phân Tích Dữ Liệu" (chưa cập nhật từ 30/09); theo dõi lần chạy schedule kế tiếp có pass không.
- So sánh số SĐT trước/sau auto_repair (repair chạy nền lúc startup, có thể xoá SĐT dính hotline).
- Cân nhắc pin version trong `requirements.txt` (Render đang dùng Python 3.14, deps không pin) và tách deps ETL/Streamlit khỏi backend.
- ETL Playwright gần đây mất >1h (trước ~25 phút), có warning timeout filter "Tin nhắn cá nhân" → điều tra.
- `auto_repair_contacted_dates` load toàn bộ raw payload vào RAM mỗi lần startup (512MB) → rủi ro khi data lớn.

### Quyết định & lý do
- Định nghĩa chỉ số ở bảng trên: user chọn tách Contact Lại/Tổng để tỉ lệ không >100%; giữ "bất kỳ ai nhắn" và "lead có SĐT bất kỳ lúc nào".
- Ghi rõ driver psycopg2 trong URL thay vì pin SQLAlchemy: chạy được cả 2.0 (Actions, Py3.10) lẫn 2.1 (Render, Py3.14).
- Ghi chú môi trường test local: venv trong Temp bị Application Control chặn DLL → chạy với `DISABLE_SQLALCHEMY_CEXT_RUNTIME=1`.
