# Bài học kinh nghiệm (Lessons Learned)

- [backend/tiktok-metrics-cache] Triệu chứng Axios báo "Network Error" khi gọi endpoint: Do backend gặp lỗi unhandled NameError (thiếu import VN_TZ từ etl.utils khi cache hit), khiến Uvicorn trả về 500 plain-text không kèm header CORS. Cách làm đúng: Luôn import đầy đủ hằng số/biến timezone (VN_TZ), test cả lần gọi đầu tiên và lần thứ hai (hit cache), và bọc endpoint với HTTPException để không bao giờ bị mất CORS. Tuyệt đối tránh chỉ test 1 lần (miss cache) mà bỏ qua nhánh cache hit.
