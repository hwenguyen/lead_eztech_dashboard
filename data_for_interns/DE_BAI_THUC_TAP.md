# TÀI LIỆU DỰ ÁN THỰC TẬP: PHÂN TÍCH DỮ LIỆU KHÁCH HÀNG

---

## I. TỔNG QUAN DỰ ÁN

EzTech là đơn vị đào tạo và tư vấn chuyên sâu về ứng dụng Dữ liệu, Excel nâng cao, Power Query, Power BI và AI cho khối ngành Kế toán - Tài chính - Phân tích dữ liệu.

Trong kỳ thực tập này, các bạn sẽ làm việc trực tiếp trên **dữ liệu thực tế** phát sinh từ hệ thống quản lý Fanpage, kênh TikTok, Zalo của EzTech. Mục tiêu là giúp doanh nghiệp trả lời các câu hỏi lớn:
1. **Marketing & Tăng trưởng:** Kênh nào đem lại khách hàng tiềm năng chất lượng nhất? Nội dung nào thu hút khách để lại số điện thoại?
2. **Vận hành & Chăm sóc:** Đội ngũ tư vấn đang chăm sóc khách ra sao? Lead có bị bỏ quên không?
3. **Khai phá & Mô hình hóa:** Khách hàng quan tâm và e ngại điều gì trong các cuộc trò chuyện? Có dự đoán được khách nào sẽ cho số điện thoại không?

---

## II. DATA DICTIONARY

Bộ dữ liệu được lưu trữ trong thư mục `data_for_interns/` gồm **5 file CSV** đã được chuẩn hóa
```
data_for_interns/
├── leads_activities.csv        # Dữ liệu khách hàng tiềm năng & hành vi tương tác
├── social_posts.csv            # Bài viết, video trên Facebook & TikTok
├── social_comments.csv         # Bình luận từ mạng xã hội
└── chat_messages_sample.csv    # 20.000 tin nhắn chat qua lại giữa khách và page
```

---

### 1. File `leads_activities.csv` (16.774 dòng)
Chứa thông tin tổng hợp về khách hàng tiềm năng (Leads) và quá trình chăm sóc của nhân viên.

| Tên Cột | Kiểu Dữ Liệu | Ý Nghĩa Chi Tiết |
| :--- | :--- | :--- |
| `customer_id` | String (UUID) | Mã định danh duy nhất của khách hàng. |
| `conversation_id` | String | Mã hội thoại trên Pancake. **Khóa ngoại (Foreign Key)** dùng để JOIN với `chat_messages_sample.csv` và `bot_auto_replies.csv`. |
| `customer_name` | String | Tên hiển thị của khách hàng trên mạng xã hội (Facebook / TikTok / Zalo). |
| `phone_masked` | String | Số điện thoại của khách hàng đã được che 3 số giữa để bảo mật (ví dụ: `0983***679`). |
| `has_phone` | Integer (0/1) | Cờ đánh dấu khách có số điện thoại hay chưa (`1`: Đã có SĐT, `0`: Chưa có SĐT). Đây là **biến mục tiêu chính (Target Variable)** để đo tỷ lệ chuyển đổi hoặc huấn luyện Machine Learning. |
| `page_id` | String | Kênh nguồn tiếp cận khách hàng (vd: *Anh Kế toán làm Data (TikTok)*, *Tuấn Anh Data*, *Anh Kế toán làm Data (Facebook)*, *Eztech Phân Tích Dữ Liệu*, *Hiền Minh Eztech*). |
| `first_created_at` | Timestamp | Thời điểm khách hàng nhắn tin / tương tác lần đầu tiên với hệ thống. |
| `phone_at` | Timestamp | Thời điểm khách hàng gửi số điện thoại lần đầu tiên (hoặc thời điểm được gắn tag đã có số). |
| `status_tag` | String | Chuỗi các thẻ tag nghiệp vụ phân cách bởi dấu phẩy (vd: `Tiktok HV TCKT, Remind`, `Data Talk`, `B2C`, `Đang tư vấn`...). |
| `assigned_users` | String | Tên nhân viên tư vấn / sale phụ trách chăm sóc khách. |
| `message_count` | Integer | Tổng số tin nhắn phát sinh trong cuộc trò chuyện. |
| `is_contacted` | Boolean (t/f) | Trạng thái khách đã được nhân viên/admin liên hệ phản hồi hay chưa (`t` = True, `f` = False). |
| `contacted_at` | Timestamp | Thời điểm nhân viên tương tác gần nhất với khách. |
| `contacted_dates` | String | Danh sách các ngày phát sinh tương tác (phân cách bởi dấu phẩy, vd: `2026-10-01,2026-10-03`). Dùng để đo tần suất và số ngày chăm sóc. |

---

### 2. File `social_posts.csv` (456 dòng)
Lưu trữ thông tin các bài đăng, video trên kênh TikTok và Fanpage Facebook của EzTech.

| Tên Cột | Kiểu Dữ Liệu | Ý Nghĩa Chi Tiết |
| :--- | :--- | :--- |
| `post_id` | String | Mã bài viết/video. **Khóa chính** dùng để JOIN với `social_comments.csv`. |
| `platform` | String | Nền tảng đăng bài (`tiktok` hoặc `facebook`). |
| `page_name` | String | Tên kênh / Fanpage đăng bài. |
| `type` | String | Định dạng bài (`video`, `post`, `livestream`...). |
| `clean_message` | String | Tiêu đề, caption, nội dung bài viết đã làm sạch khoảng trắng. |
| `like_count` | Integer | Số lượt thích / thả tim bài viết. |
| `comment_count` | Integer | Số lượt bình luận ghi nhận trên bài viết. |
| `share_count` | Integer | Số lượt chia sẻ bài viết / video. |
| `view_count` | Integer | Lượt xem (Lưu ý: API không trả chỉ số này nên giá trị là 0, hãy tập trung vào Like/Comment/Share). |
| `phone_number_count` | Integer | Số lượng SĐT thu được trực tiếp trong phần mô tả bài viết. |
| `inserted_at` | Timestamp | Thời điểm đăng bài lên mạng xã hội. |

---

### 3. File `social_comments.csv` (6.718 dòng)
Lưu trữ các bình luận của khán giả để lại dưới các bài viết và video.

| Tên Cột | Kiểu Dữ Liệu | Ý Nghĩa Chi Tiết |
| :--- | :--- | :--- |
| `comment_id` | String | Mã định danh duy nhất của bình luận. |
| `post_id` | String | Mã bài viết chứa bình luận này. **Khóa ngoại** JOIN sang `social_posts.csv`. |
| `page_name` | String | Tên trang / kênh phát sinh bình luận. |
| `customer_name` | String | Tên người để lại bình luận. |
| `phone_masked` | String | Số điện thoại nếu khách để lại trực tiếp trong phần bình luận (đã mask). |
| `clean_message` | String | Nội dung văn bản bình luận của khách. |
| `tags` | String | Thẻ gắn trên bình luận (nếu có). |
| `assigned_users` | String | Nhân viên phụ trách xử lý bình luận (nếu có). |
| `inserted_at` | Timestamp | Thời điểm khách để lại bình luận. |

---

### 4. File `bot_auto_replies.csv` (762 dòng)
Nhật ký Bot tự động trả lời tin nhắn của khách hàng theo kịch bản từ khóa.

| Tên Cột | Kiểu Dữ Liệu | Ý Nghĩa Chi Tiết |
| :--- | :--- | :--- |
| `conversation_id` | String | Mã hội thoại kích hoạt bot. **Khóa ngoại** JOIN sang `leads_activities.csv` và `chat_messages_sample.csv`. |
| `customer_id` | String | Mã khách hàng. |
| `page_id` | String | Kênh tiếp nhận tin nhắn. |
| `case_id` | String | Kịch bản Bot kích hoạt (vd: `xin_file`, `tham_gia_cong_dong`...). |
| `customer_message` | String | Tin nhắn khách nhắn khiến Bot nhận diện và kích hoạt trả lời. |
| `reply_message` | String | Nội dung câu trả lời tự động do Bot gửi lại cho khách. |
| `sent_at` | Timestamp | Thời điểm Bot gửi tin nhắn tự động. |
| `status` | String | Trạng thái gửi tin (`SENT` = Đã gửi thành công). |

---

### 5. File `chat_messages_sample.csv` (20.000 dòng)
Trích xuất 20.000 tin nhắn hội thoại text thuần (đã gọt sạch 100% các thẻ HTML như `<div>`, `<span>`, `<Copy>...` và loại bỏ tin nhắn rỗng).

| Tên Cột | Kiểu Dữ Liệu | Ý Nghĩa Chi Tiết |
| :--- | :--- | :--- |
| `conversation_id` | String | Mã cuộc trò chuyện. **Khóa ngoại** JOIN sang `leads_activities.csv`. |
| `page_id` | String | Tên Fanpage / Kênh chat. |
| `sender_role` | String | Người gửi tin nhắn: `Admin` (Nhân viên/Bot) hoặc `Khách hàng`. |
| `sent_at` | Timestamp | Thời điểm gửi tin nhắn cụ thể. |
| `message_text` | String | Nội dung tin nhắn sạch hoàn toàn, sẵn sàng cho việc phân tích NLP. |

---

## III. PROJECT ASSIGNMENTS

Thực tập sinh lựa chọn 1 đề bài chính theo nhóm năng lực (hoặc ghép cặp 1 Tech + 1 Business để làm đề bài tổng hợp).

---

### TRACK 1: BUSINESS, MARKETING & OPERATIONS ANALYTICS
*Dành cho các bạn có thế mạnh về tư duy phân tích kinh doanh, marketing, chăm sóc khách hàng và trực quan hóa số liệu (Power BI, Excel, Tableau).*

#### 📌 Đề A1: Phân Tích Phễu Chuyển Đổi Lead & Tỷ Lệ Thu Thập SĐT (Lead Funnel Analysis)
* **Mục tiêu:** Tìm ra kênh tiếp thị hiệu quả nhất và điểm nghẽn khiến khách hàng không để lại số điện thoại.
* **Nhiệm vụ cụ thể:**
  1. Thống kê tỷ lệ chuyển đổi ra SĐT (`has_phone`) trên từng kênh (`page_id`). Kênh nào có tỷ lệ cao nhất và thấp nhất?
  2. Đo lường thời gian trung bình (Time-to-Phone): Khách mất bao lâu từ lúc tạo (`first_created_at`) đến khi để lại SĐT (`phone_at`)?
  3. Phân tích số lượng tin nhắn (`message_count`): Khách thường nhắn bao nhiêu tin thì đồng ý cho số? Có ngưỡng tin nhắn nào mà sau đó khách sẽ bỏ đi không?
  4. Phân tích khung giờ vàng: Khách để lại SĐT nhiều nhất vào các khung giờ nào trong ngày và ngày nào trong tuần?
* **Sản phẩm đầu ra:** 1 Dashboard trực quan + Báo cáo tóm tắt 3 khuyến nghị giúp tối ưu kịch bản xin số điện thoại.

#### 📌 Đề A2: Đánh Giá Hiệu Quả Nội Dung Mạng Xã Hội (Social Content: Viral vs. Lead)
* **Mục tiêu:** Đánh giá mối tương quan giữa bài viết nhiều view/like với khả năng thu hút khách để lại bình luận và SĐT.
* **Nhiệm vụ cụ thể:**
  1. Ghép nối `social_posts.csv` và `social_comments.csv` bằng `post_id`.
  2. Phân nhóm các bài viết/video theo chủ đề (dựa vào từ khóa trong `clean_message`: mẹo Excel, Power Query, AI cho kế toán, giải trí...).
  3. So sánh: Bài viết có lượt Like/Comment cao có phải là bài thu được nhiều bình luận để lại SĐT nhất không?
  4. Xác định top 10 bài viết/video có tỷ lệ tương tác và chuyển đổi tốt nhất trên cả TikTok và Facebook.
* **Sản phẩm đầu ra:** Báo cáo phân tích nội dung + Đề xuất 5 chủ đề nội dung tiềm năng cho tháng tiếp theo.

#### 📌 Đề A3: Đánh Giá Năng Lực Tư Vấn & Chăm Sóc Khách Hàng (Sales Operations SLA)
* **Mục tiêu:** Đo lường năng suất, thời gian phản hồi và chất lượng chăm sóc của đội ngũ tư vấn.
* **Nhiệm vụ cụ thể:**
  1. Phân bổ số lượng lead cho các nhân viên (`assigned_users`): Có xảy ra tình trạng người quá tải, người quá ít không?
  2. Tỷ lệ lấy được SĐT thành công của từng nhân viên tư vấn?
  3. Phân tích tần suất chăm sóc: Khách được liên hệ qua bao nhiêu ngày (`contacted_dates`)? 
  4. Xác định tỷ lệ "Lead bị bỏ quên": Có bao nhiêu % khách không được nhắn tin lại sau 3 ngày hoặc 7 ngày?
* **Sản phẩm đầu ra:** Bảng xếp hạng hiệu suất tư vấn (Sales Scorecard) + Bộ quy chuẩn thời gian phản hồi (SLA) đề xuất cho công ty.

---

### TRACK 2: TECHNICAL, DATA SCIENCE & NLP
*Dành cho các bạn có thế mạnh về lập trình Python, xử lý ngôn ngữ tự nhiên (NLP), Machine Learning và Data Modeling.*

#### 📌 Đề B1: Khai Phá Dữ Liệu Hội Thoại & Nhận Diện Ý Định (Chat NLP & Intent Mining)
* **Mục tiêu:** Tự động phân loại nhu cầu và tìm ra các rào cản tâm lý của khách hàng thông qua ngôn ngữ chat.
* **Nhiệm vụ cụ thể:**
  1. Sử dụng Python tiền xử lý văn bản trong `chat_messages_sample.csv` (lọc stop-words, chuẩn hóa từ ngữ viết tắt, teen-code tiếng Việt).
  2. Trích xuất các cụm từ phổ biến (N-grams, WordCloud) tách biệt giữa câu hỏi của `Khách hàng` và câu trả lời của `Admin`.
  3. Áp dụng kỹ thuật phân cụm chủ đề (Topic Modeling - LDA) để gom nhóm các ý định của khách: Hỏi học phí, hỏi chứng chỉ, xin tài liệu, hỏi lộ trình học...
  4. Nhận diện các "Rào cản từ chối" (Objection Mining): Tìm các câu khách thể hiện sự phân vân (vd: học phí đắt, bận rộn, sợ không theo kịp...).
* **Sản phẩm đầu ra:** Jupyter Notebook mã nguồn sạch + Báo cáo các cụm chủ đề chính và bộ gợi ý kịch bản trả lời tương ứng.

#### 📌 Đề B2: Xây Dựng Mô Hình Dự Đoán Khách Sẽ Cho SĐT (Lead Propensity Model)
* **Mục tiêu:** Huấn luyện mô hình Machine Learning dự đoán xác suất một khách hàng mới sẽ để lại số điện thoại.
* **Nhiệm vụ cụ thể:**
  1. Nối `leads_activities.csv` với các tin nhắn đầu tiên của khách trong `chat_messages_sample.csv` qua `conversation_id`.
  2. Kỹ thuật tạo đặc trưng (Feature Engineering):
     * Kênh nguồn (`page_id`), khung giờ nhắn tin đầu tiên.
     * Độ dài tin nhắn đầu tiên của khách, số lượng từ.
     * Các từ khóa xuất hiện trong tin nhắn (TF-IDF hoặc cờ có chứa: *học phí, khóa học, xin file...*).
  3. Huấn luyện các mô hình phân loại nhị phân (Logistic Regression, Random Forest, LightGBM/XGBoost) với biến mục tiêu là `has_phone` (0 hoặc 1).
  4. Đánh giá mô hình qua các chỉ số: ROC-AUC, F1-Score, Precision, Recall và phân tích các đặc trưng quan trọng nhất (Feature Importance).
* **Sản phẩm đầu ra:** Pipeline huấn luyện mô hình hoàn chỉnh + Phân tích các yếu tố quyết định khiến khách hàng dễ để lại SĐT.

---

## IV. TIÊU CHÍ ĐÁNH GIÁ (EVALUATION RUBRIC)

Báo cáo kết thúc kỳ thực tập sẽ được đánh giá trên thang điểm 100 dựa trên 4 trụ cột:

1. **Phương thức trình bày & truyền đạt:**
   * Trình bày rõ ý tưởng, hướng làm và tại sao thực hiện các bước, kết quả.
   * Sản phẩm trực quan, dễ hiểu, dễ nắm được ý muốn truyền đạt.
2. **Kỹ năng Kỹ thuật / Trực quan hóa (30%):**
   * Đối với Track Business: Dashboard trực quan, bố cục khoa học, màu sắc hài hòa, biểu đồ đúng mục đích phân tích.
   * Đối với Track Tech: Trình bày rõ ý tưởng, kết quả đạt được.
3. **Tư duy Kinh doanh & Đào sâu Insight (30%):**
   * Không chỉ dừng lại ở việc mô tả số liệu ("cột A tăng, cột B giảm"), mà phải trả lời được câu hỏi: **"Tại sao lại như vậy?"** và **"Số liệu này có ý nghĩa gì đối với EzTech?"**.
4. **Khả năng Đề xuất Giải pháp (15%):**
   * Đưa ra được ít nhất **3 giải pháp hành động cụ thể** (Actionable Recommendations) có tính khả thi cao để giúp doanh nghiệp cải thiện chuyển đổi.

---
*Chúc các bạn có một kỳ thực tập bổ ích và tạo ra nhiều giá trị thực tiễn cho doanh nghiệp!*
