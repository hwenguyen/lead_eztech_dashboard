# 📘 TÀI LIỆU DỰ ÁN THỰC TẬP: PHÂN TÍCH DỮ LIỆU KHÁCH HÀNG & CHUYỂN ĐỔI SỐ
**EzTech Data & Education Dashboard**

---

## 📌 I. TỔNG QUAN DỰ ÁN

EzTech là đơn vị đào tạo và tư vấn chuyên sâu về ứng dụng Dữ liệu, Excel nâng cao, Power Query, Power BI và AI cho khối ngành Kế toán - Tài chính - Phân tích dữ liệu.

Trong kỳ thực tập này, các bạn sẽ làm việc trực tiếp trên **dữ liệu thực tế** phát sinh từ hệ thống quản lý Fanpage, kênh TikTok, Zalo và Chatbot của EzTech. Mục tiêu là giúp doanh nghiệp trả lời các câu hỏi lớn:
1. **Marketing & Tăng trưởng:** Kênh nào đem lại khách hàng tiềm năng chất lượng nhất? Nội dung nào thu hút khách để lại số điện thoại?
2. **Vận hành & Chăm sóc:** Đội ngũ tư vấn đang chăm sóc khách ra sao? Lead có bị bỏ quên không?
3. **Khai phá & Mô hình hóa:** Khách hàng quan tâm và e ngại điều gì trong các cuộc trò chuyện? Có dự đoán được khách nào sẽ cho số điện thoại không?

---

## 📂 II. TỪ ĐIỂN DỮ LIỆU (DATA DICTIONARY)

Bộ dữ liệu được lưu trữ trong thư mục `data_for_interns/` gồm **5 file CSV** đã được chuẩn hóa và mã hóa chuẩn `UTF-8 with BOM` (mở trực tiếp bằng Excel hoặc đọc qua Python không bị lỗi font tiếng Việt).

```
data_for_interns/
├── leads_activities.csv        # Dữ liệu khách hàng tiềm năng & hành vi tương tác
├── social_posts.csv            # Bài viết, video trên Facebook & TikTok
├── social_comments.csv         # Bình luận từ mạng xã hội
├── bot_auto_replies.csv        # Nhật ký bot gửi tin nhắn tự động
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

## 🎯 III. CÁC ĐỀ BÀI THỰC TẬP (PROJECT ASSIGNMENTS)

Thực tập sinh lựa chọn 1 đề bài chính theo nhóm năng lực (hoặc ghép cặp 1 Tech + 1 Business để làm đề bài tổng hợp).

---

### 🟢 TRACK 1: BUSINESS, MARKETING & OPERATIONS ANALYTICS (CHI TIẾT)
*Dành cho các bạn có thế mạnh về tư duy phân tích kinh doanh, marketing, vận hành đội ngũ tư vấn và trực quan hóa dữ liệu (Power BI, Excel, Tableau, Python).*

---

#### 📌 ĐỀ A1: PHÂN TÍCH PHỄU CHUYỂN ĐỔI LEAD & TỐI ƯU TỶ LỆ THU THẬP SĐT (Lead-to-Phone Conversion Funnel)

##### 1. Bối cảnh nghiệp vụ & Quy tắc dữ liệu bắt buộc (Business Rules)
Khi phân tích bảng `leads_activities.csv`, bạn **bắt buộc** phải nắm rõ quy trình thực tế tại EzTech để không bị kết luận sai lệch số liệu:
* **Phân biệt 2 nhóm kênh trong cột `page_id`:**
  * **Nhóm 1 — Kênh Nguồn Marketing (Acquisition Channels - 4 kênh):**
    1. `Anh Kế toán làm Data (TikTok)`
    2. `Anh Kế toán làm Data (Facebook)`
    3. `Hành trang cho kế toán` (TikTok)
    4. `Chị Kế Toán GenZ` (TikTok)
    *(Đây là nơi khách hàng mới tiếp cận nội dung/quảng cáo và nhắn tin lần đầu tiên).*
  * **Nhóm 2 — Kênh Zalo Chăm Sóc (Zalo Care Channels - 4 kênh):**
    1. `Tuấn Anh Data`
    2. `Eztech Phân Tích Dữ Liệu`
    3. `Hiền Minh Eztech`
    4. `Eztech Consultant`
    *(Đây là Zalo cá nhân của đội ngũ tư vấn dùng để kết bạn chăm sóc sâu **sau khi khách đã có SĐT**).*
  * ⚠️ **Nguyên tắc sống còn:** Khi đánh giá hiệu quả thu thập SĐT của Marketing, bạn phải **tách riêng 4 Kênh Nguồn** (không cộng gộp 4 Kênh Zalo vào mẫu số chung của Marketing, vì Kênh Zalo bản chất là khách đã có SĐT chuyển sang).
* **Quy tắc ghi nhận SĐT thành công:**
  * Một Lead được tính là có SĐT nếu `has_phone = 1` **HOẶC** trong cột `status_tag` có chứa thẻ `"Đã add"` (đã kết bạn Zalo).
  * Thời điểm thu được SĐT: Dùng cột `phone_at` (nếu `phone_at` bị trống đối với khách có SĐT thì dùng `first_created_at`).

##### 2. Hệ thống chỉ số cần tính (Key Metrics & Công thức)
| Chỉ số (Metric) | Công thức / Cách tính | Ý nghĩa kinh doanh |
| :--- | :--- | :--- |
| **Total Source Leads** | Đếm tổng số dòng thuộc 4 Kênh Nguồn theo kỳ | Quy mô thu hút khách hàng mới của Marketing |
| **Phone Collected Leads** | Số Lead thuộc Kênh Nguồn có `has_phone = 1` hoặc tag `"Đã add"` | Số lượng khách hàng tiềm năng chất lượng thu được |
| **Phone Conversion Rate (CR %)** | $\frac{\text{Phone Collected Leads}}{\text{Total Source Leads}} \times 100\%$ | Hiệu suất chuyển đổi từ tin nhắn ra số điện thoại |
| **Time-to-Phone** | $\text{phone\_at} - \text{first\_created\_at}$ (Đo cả *Median* và *Mean*) | Tốc độ thuyết phục khách để lại thông tin liên hệ |
| **Messages-to-Convert** | Trung bình / Trung vị `message_count` của nhóm có SĐT vs. không có SĐT | Độ dài hội thoại cần thiết để khách đủ tin tưởng cho số |

##### 3. Lộ trình phân tích chi tiết (4 Bước)
* **Bước 1 — Bức tranh toàn cảnh Phễu chuyển đổi (Funnel Overview):**
  * Xây dựng phễu 5 tầng cho 4 Kênh Nguồn:
    `Tổng Lead Mới` $\rightarrow$ `Đã phản hồi (is_contacted = t)` $\rightarrow$ `Tương tác qua lại (message_count >= 3)` $\rightarrow$ `Thu được SĐT (has_phone = 1)` $\rightarrow$ `Chuyển đổi sang nhóm Quan tâm học/Học viên (status_tag chứa: HV TCKT, Đào tạo, Đã là học viên)`.
  * Xác định bước nào trong phễu đang có tỷ lệ rơi rụng (Drop-off Rate) lớn nhất.
* **Bước 2 — Đánh giá Hiệu quả từng Kênh Nguồn (Channel Attribution):**
  * So sánh giữa nền tảng Facebook (`Anh Kế toán làm Data (Facebook)`) và 3 kênh TikTok.
  * Kênh nào mang lại số lượng (Volume) lớn nhất? Kênh nào có tỷ lệ ra số (CR %) cao nhất?
  * Phân tích xu hướng biến động theo tuần/tháng: Có giai đoạn nào lượng Lead tăng đột biến nhưng tỷ lệ ra SĐT lại sụt giảm không?
* **Bước 3 — Phân tích Hành vi & Điểm nghẽn Rơi rụng (Behavioral & Drop-off Analysis):**
  * **Phân tích theo độ dài hội thoại (`message_count`):** Nhóm khách không để lại SĐT (`has_phone = 0`) thường dừng cuộc trò chuyện ở tin nhắn thứ mấy (1 tin, 2 tin, hay 3–5 tin)? Ngưỡng tin nhắn "vàng" mà tại đó xác suất có SĐT đạt đỉnh là bao nhiêu?
  * **Phân tích theo Thời gian (Khung giờ & Thứ trong tuần):** Trích xuất Giờ (`0h–23h`) và Thứ (`Thứ 2 – Chủ Nhật`) từ `first_created_at`. Khung giờ nào khách nhắn tin nhiều nhưng tỷ lệ thu được SĐT lại thấp? (Gợi ý: So sánh giờ hành chính `08h–18h` vs. khung giờ tối/đêm `19h–24h`).
* **Bước 4 — Phân tích theo Nhóm Thẻ Nhu cầu (`status_tag`):**
  * Tách cột `status_tag` theo dấu phẩy `,` (Unpivot / Split to Rows).
  * Thống kê tỷ lệ có SĐT và số lượng tin nhắn trung bình theo các nhóm thẻ chính: `B2C`, `Data Talk`, `Tiktok HV TCKT`, `Remind`, `Lead Other`...

##### 4. Các giả thuyết kinh doanh gợi ý kiểm chứng (Business Hypotheses)
1. **Giả thuyết H1 (Chất lượng kênh):** *Khách đến từ TikTok có số lượng lớn nhờ video viral nhưng tỷ lệ để lại SĐT thấp hơn đáng kể so với khách đến từ Fanpage Facebook.*
2. **Giả thuyết H2 (Điểm chạm hội thoại):** *Những cuộc hội thoại duy trì được từ 4 tin nhắn trở lên (`message_count >= 4`) có tỷ lệ thu được SĐT cao gấp ít nhất 2 lần so với các hội thoại dưới 4 tin.*
3. **Giả thuyết H3 (Độ trễ ngoài giờ):** *Lead phát sinh sau 21h00 tối có tỷ lệ chuyển đổi ra SĐT thấp hơn giờ hành chính do thiếu nhân sự trực phản hồi ngay lập tức.*

##### 5. Yêu cầu Sản phẩm đầu ra (Deliverables)
* **Dashboard (2 trang hoặc 1 trang tổng hợp có bộ lọc):**
  * *Khu vực 1 (Overview):* 4 KPI Cards (Tổng Lead Nguồn, Tổng SĐT, CR %, Median Time-to-Phone), Biểu đồ Phễu (Funnel Chart), Biểu đồ Combo (Cột: Số Lead, Đường: CR % theo từng Kênh và theo Tuần).
  * *Khu vực 2 (Deep-dive):* Heatmap (Thứ × Giờ phát sinh Lead & CR %), Biểu đồ cột so sánh tỷ lệ ra SĐT theo các mức `message_count` (`1 tin`, `2-3 tin`, `4-6 tin`, `7-10 tin`, `>10 tin`), Biểu đồ phân tích theo `status_tag`.
* **Báo cáo thuyết trình (Slide/Doc):** Trình bày tối thiểu 3 Insights đắt giá nhất kèm **3 Khuyến nghị hành động (Actionable Recommendations)** để tăng tỷ lệ xin SĐT thêm 5–10%.

---

#### 📌 ĐỀ A2: ĐÁNH GIÁ HIỆU QUẢ NỘI DUNG MẠNG XÃ HỘI (Social Content Analytics: Viral vs. Lead Generation)

##### 1. Bối cảnh nghiệp vụ & Quy tắc dữ liệu bắt buộc
Đội ngũ Content Marketing của EzTech sản xuất nội dung đều đặn trên 4 kênh (`Anh Kế toán làm Data (TikTok)` - 149 bài, `Anh Kế toán làm Data (Facebook)` - 140 bài, `Hành trang cho kế toán` - 108 bài, `Chị Kế Toán GenZ` - 60 bài) với 4 định dạng (`video`: 332, `livestream`: 74, `post`: 27, `photo`: 24).
* **Bài toán thực tế:** Trong Marketing giáo dục, một nội dung "Viral" (nhiều Like/Tim) chưa chắc đã mang lại khách hàng thực sự. Ngược lại, có những bài viết ít Like nhưng đánh trúng nỗi đau nghề nghiệp khiến học viên bình luận xin tài liệu và để lại SĐT rất nhiều.
* ⚠️ **Lưu ý dữ liệu bắt buộc:**
  * Cột `view_count` trong `social_posts.csv` hiện có giá trị bằng `0` do giới hạn của API. Bạn **không sử dụng `view_count`** mà phải đánh giá qua `like_count`, `comment_count`, `share_count` và dữ liệu chi tiết từ bảng `social_comments.csv`.
  * Liên kết bảng `social_posts.csv` và `social_comments.csv` thông qua khóa ngoại `post_id` (có hơn 80% bình luận khớp trực tiếp với danh sách bài viết).

##### 2. Hệ thống chỉ số cần tính (Key Metrics & Công thức)
| Chỉ số (Metric) | Công thức / Cách tính | Ý nghĩa kinh doanh |
| :--- | :--- | :--- |
| **Total Engagement** | $\text{like\_count} + \text{comment\_count} + \text{share\_count}$ | Tổng lượng tương tác thô của bài viết |
| **Weighted Engagement Score** | $\text{like\_count} \times 1 + \text{comment\_count} \times 2 + \text{share\_count} \times 3$ | Điểm tương tác có trọng số (ưu tiên hành động Comment & Share) |
| **Discussion Ratio** | $\frac{\text{comment\_count}}{\text{like\_count} + 1}$ | Mức độ kích thích thảo luận / xin tài liệu so với thả tim dạo |
| **High-Intent Comments** | Số bình luận trong `social_comments.csv` có chứa từ khóa mua hàng/xin tài liệu (*xin file, ib, tư vấn, học phí, khóa học, đăng ký, @gmail...*) hoặc có `phone_masked IS NOT NULL` | Số lượng phản hồi chất lượng cao thực sự có nhu cầu |
| **Direct Phone Comments** | Tổng số bình luận có để lại SĐT (`phone_masked IS NOT NULL`) + `phone_number_count` | Khả năng thu SĐT trực tiếp ngay trên bài đăng |

##### 3. Lộ trình phân tích chi tiết (4 Bước)
* **Bước 1 — Phân tích Hiệu suất theo Kênh & Định dạng (Channel & Format Benchmark):**
  * So sánh hiệu quả trung bình (Mean & Median của Like, Comment, Share) giữa nền tảng `tiktok` và `facebook`.
  * So sánh 4 định dạng: `video`, `livestream`, `post`, `photo`. Định dạng nào tạo ra lượng `comment_count` trên mỗi bài cao nhất? (Đặc biệt lưu ý so sánh `livestream` vs. `video` trên TikTok).
* **Bước 2 — Phân nhóm Chủ đề Nội dung (Content Pillar Categorization):**
  * Dựa vào nội dung cột `clean_message` (caption và hashtag) trong `social_posts.csv`, hãy xây dựng bộ quy tắc từ khóa (dùng hàm `IF/SEARCH` trong Excel/DAX hoặc Python) để gán mỗi bài viết vào **5 Nhóm chủ đề (Content Pillars)**:
    1. **Excel & Kế toán thực chiến:** Chứa các từ `excel`, `kế toán`, `thu chi`, `dòng tiền`, `công nợ`, `bảng lương`, `hàm`...
    2. **Power Query / Power BI & Data:** Chứa các từ `power query`, `power bi`, `data`, `dữ liệu`, `báo cáo tự động`...
    3. **Ứng dụng AI trong Công việc:** Chứa các từ `ai`, `chatgpt`, `tự động`...
    4. **Hành trang Sinh viên / Chuyện nghề Kế toán:** Chứa các từ `thực tập`, `sinh viên`, `genz`, `phỏng vấn`, `sếp`, `đi làm`...
    5. **Livestream / Khác:** Các bài livestream hoặc thông báo chung.
  * Đo lường xem Nhóm chủ đề nào mang lại nhiều Like/Share nhất vs. Nhóm chủ đề nào mang lại nhiều Comment xin tài liệu / hỏi khóa học nhất.
* **Bước 3 — Xây dựng Ma trận Nội dung 4 Góc phần tư (2x2 Content Matrix):**
  * Phân loại 456 bài viết vào ma trận dựa trên 2 trục: **Trục Hoành (Viral = Like + Share)** và **Trục Tung (Lead/Intent = Comment Count & High-Intent Comments)**:
    * 🌟 **Nhóm 1 — Ngôi sao (High Viral, High Comment/Intent):** Vừa lan tỏa rộng vừa thu hút nhiều khách hỏi bài/xin file $\rightarrow$ Tìm công thức chung để nhân bản.
    * 🎯 **Nhóm 2 — Mồi câu chuyển đổi (Low Viral, High Comment/Intent):** Ít Like nhưng khách vào comment xin tài liệu/để lại SĐT rất cao $\rightarrow$ Đề xuất dùng làm bài chạy Quảng cáo (Ads).
    * 📢 **Nhóm 3 — Tăng nhận diện (High Viral, Low Comment/Intent):** Nhiều Like/Share nhưng ít người hỏi chuyên môn $\rightarrow$ Duy trì vừa phải để kéo tương tác kênh.
    * 📉 **Nhóm 4 — Kém hiệu quả (Low Viral, Low Comment/Intent):** Cần loại bỏ hoặc thay đổi cách viết Hook.
* **Bước 4 — Phân tích Hành vi Bình luận & Thời điểm Đăng bài (Timing & Lifespan):**
  * Khung giờ đăng bài nào (`inserted_at` của `social_posts`) mang lại lượng tương tác trung bình cao nhất?
  * Kết hợp với bảng `social_comments.csv`: Tính khoảng cách thời gian từ lúc đăng bài (`posts.inserted_at`) đến lúc khách bình luận (`comments.inserted_at`). Bao nhiêu % bình luận đến trong 24h đầu tiên? Bao nhiêu % đến từ hiệu ứng đuôi dài (Long-tail sau 3 ngày, 7 ngày)?

##### 4. Các giả thuyết kinh doanh gợi ý kiểm chứng (Business Hypotheses)
1. **Giả thuyết H1 (Lead Magnet):** *Các bài đăng có yếu tố tặng tài liệu/biểu mẫu thực hành (chứa từ khóa "file", "mẫu", "tặng", "hướng dẫn") có tỷ lệ `Comment / Like` cao gấp 3 lần các bài chia sẻ kiến thức lý thuyết thông thường.*
2. **Giả thuyết H2 (Định dạng Livestream):** *Định dạng `livestream` trên TikTok mặc dù có số lượt Like bằng 0 trên hệ thống nhưng lại tạo ra lượng bình luận tương tác trực tiếp cao vượt trội.*
3. **Giả thuyết H3 (Độ dài Caption):** *Trên Facebook, các bài viết có cấu trúc rõ ràng (độ dài vừa phải, có câu hỏi gợi mở ở cuối bài và kèm hashtag) tạo ra lượng tương tác cao hơn gấp đôi các bài đăng ngắn dưới 50 ký tự.*

##### 5. Yêu cầu Sản phẩm đầu ra (Deliverables)
* **Dashboard (2 trang):**
  * *Trang 1 (Content Pillar & Platform Overview):* KPI Cards, Biểu đồ so sánh hiệu quả theo 4 Kênh & 4 Định dạng, Biểu đồ Bar Chart so sánh 5 Nhóm chủ đề (Content Pillars) theo cả lượng Like và lượng Comment chất lượng.
  * *Trang 2 (2x2 Content Matrix & Top 10 Posts):* Biểu đồ Scatter Plot 4 góc phần tư, Bảng chi tiết Top 10 bài viết chuyển đổi tốt nhất, Biểu đồ phân tích Khung giờ đăng bài & Vòng đời bài viết.
* **Báo cáo chiến lược Content (Slide/Doc):** Đề xuất **Kế hoạch Nội dung (Content Plan)** cho tháng tiếp theo: Tỷ trọng phân bổ % giữa các chủ đề, khung giờ đăng vàng cho từng kênh, và 5 mẫu tiêu đề (Hook) hiệu quả nhất rút ra từ dữ liệu.

---

#### 📌 ĐỀ A3: ĐÁNH GIÁ NĂNG LỰC TƯ VẤN & SLA VẬN HÀNH CHĂM SÓC KHÁCH HÀNG (Sales Operations & SLA Analytics)

##### 1. Bối cảnh nghiệp vụ & Quy tắc dữ liệu bắt buộc
Sau khi Marketing mang Lead về, thành bại của doanh thu phụ thuộc vào tốc độ và sự kiên trì của đội ngũ tư vấn viên (`assigned_users` trong `leads_activities.csv` gồm các nhân sự chính như: `Trần Đạt`, `Liên Vũ`, `Linh Bùi`, `Hồng Minh`, `Nguyen Gia Huy`, `Bảo Ngọc`, `Hiền Minh Lý`, `Nguyễn Thị Thanh Mai`, `Khuất Cường`, `Pham Thu Huyen`...).
* **Quy trình vận hành 2 chặng:**
  * **Chặng 1 (Săn SĐT tại Kênh Nguồn):** Nhân viên trực các trang Facebook/TikTok để trả lời khách và xin SĐT.
  * **Chặng 2 (Chăm sóc sâu tại Kênh Zalo):** Sau khi có SĐT, nhân viên kết bạn qua các trang Zalo (`Tuấn Anh Data`, `Eztech Phân Tích Dữ Liệu`, `Hiền Minh Eztech`, `Eztech Consultant`) để tư vấn lộ trình học và nhắc hẹn (`Remind`).
* ⚠️ **Lưu ý xử lý dữ liệu bắt buộc:**
  * **Khách chưa phân công:** Có `3.182 dòng` mà cột `assigned_users` bị trống (`NULL`). Đây được gọi là nhóm **"Chưa phân công" (Unassigned Leads)** — một chỉ số cực kỳ quan trọng phản ánh lỗ hổng vận hành.
  * **Đo lường độ kiên trì qua `contacted_dates`:** Cột này lưu danh sách các ngày có tương tác cách nhau bởi dấu phẩy (vd: `2026-10-01,2026-10-03,2026-10-07`). Công thức đếm số ngày chăm sóc (Touchpoint Days) trong Excel/DAX:
    $$\text{Touchpoint Days} = \text{LEN(contacted\_dates)} - \text{LEN(SUBSTITUTE(contacted\_dates, ",", ""))} + 1$$
  * **Mốc thời gian chốt dữ liệu (Snapshot Date):** Lấy ngày **`2026-11-01`** làm mốc hiện tại để tính số ngày khách chưa được liên hệ lại ($\text{Days Since Last Contact} = \text{'2026-11-01'} - \text{contacted\_at}$).

##### 2. Hệ thống chỉ số cần tính (Key Metrics & Công thức)
| Chỉ số (Metric) | Công thức / Cách tính | Ý nghĩa vận hành |
| :--- | :--- | :--- |
| **Unassigned Rate (%)** | $\frac{\text{Số Lead có assigned\_users IS NULL}}{\text{Tổng số Lead}} \times 100\%$ | Tỷ lệ khách bị bỏ sót chưa có nhân viên nhận chăm sóc |
| **Consultant Workload** | Số lượng Lead được gán cho từng nhân viên (chia theo Kênh Nguồn & Kênh Zalo) | Đánh giá mức độ cân bằng tải công việc giữa các Sale |
| **Source Phone Win-Rate (%)** | Tỷ lệ thu được SĐT của từng nhân viên **chỉ tính trên 4 Kênh Nguồn** | Đánh giá kỹ năng khai thác và xin SĐT của từng nhân viên |
| **Persistence Rate (%)** | Tỷ lệ Lead được nhân viên tương tác từ **2 ngày trở lên** ($\text{Touchpoint Days} \ge 2$) | Đo lường độ kiên trì đeo bám khách hàng (Follow-up) |
| **Remind Backlog (>7 Days)** | Số lượng Lead có tag `"Remind"` / `"Đang tư vấn"` nhưng $\text{Days Since Last Contact} > 7$ | Khối lượng khách tiềm năng đang bị "ngâm" quá hạn chưa chăm lại |

##### 3. Lộ trình phân tích chi tiết (4 Bước)
* **Bước 1 — Kiểm toán Lỗ hổng Phân công & Cân bằng tải (Workload & Leakage Audit):**
  * Phân tích 3.182 Lead *"Chưa phân công"* (`assigned_users IS NULL`): Chúng tập trung ở Fanpage/TikTok nào nhiều nhất? Vào khung giờ nào? Tỷ lệ có SĐT của nhóm *"Chưa phân công"* thấp hơn bao nhiêu lần so với nhóm *"Đã có nhân viên phụ trách"*?
  * Phân tích phân bổ khối lượng Lead giữa Top 10 nhân viên tư vấn: Có tình trạng dồn quá nhiều Lead cho một vài người trong khi người khác nhận quá ít không?
* **Bước 2 — Đánh giá Hiệu suất Chuyển đổi của từng Nhân viên (Consultant Scorecard):**
  * Chỉ xét trên **4 Kênh Nguồn**: So sánh các nhân viên về `Số lượng Lead đảm nhận`, `Số tin nhắn trung bình / Lead` và `Tỷ lệ xin SĐT thành công (Phone Win-Rate %)`.
  * Xếp hạng nhân viên vào 4 nhóm trên biểu đồ phân tán (Scatter Plot):
    * **Ngôi sao:** Nhận nhiều Lead + Tỷ lệ ra SĐT cao.
    * **Chất lượng cao:** Nhận lượng Lead vừa phải nhưng chăm sóc rất kỹ, tỷ lệ ra SĐT đứng đầu.
    * **Quá tải:** Nhận quá nhiều Lead dẫn đến số tin nhắn/khách thấp và tỷ lệ ra SĐT bị tụt.
    * **Cần hỗ trợ/đào tạo:** Nhận ít Lead nhưng tỷ lệ chuyển đổi vẫn thấp.
* **Bước 3 — Chứng minh Giá trị của việc Đeo bám Đa ngày (Follow-up Impact Analysis):**
  * Phân nhóm khách hàng theo số ngày được chăm sóc (`Touchpoint Days`: `1 ngày`, `2 ngày`, `3 ngày`, `4-5 ngày`, `>5 ngày`).
  * So sánh tỷ lệ thu được SĐT và tỷ lệ xuất hiện các thẻ thành công (`Đã là học viên`, `HV TCKT`, `Đào tạo`) giữa nhóm chỉ nói chuyện **1 ngày duy nhất** so với nhóm được đeo bám **từ 2 ngày trở lên**.
* **Bước 4 — Quản trị Tệp khách Hẹn tư vấn lại (Remind Aging & SLA Compliance):**
  * Lọc riêng nhóm khách có tiềm năng nhưng chưa chốt ngay (trong `status_tag` có chứa `Remind`, `Đang tư vấn`, `Quan tâm sâu`, `Có thông tin`).
  * Tính tuổi tồn đọng tính đến ngày `2026-11-01` và chia thành 4 nhóm: `Mới tương tác (0-3 ngày)`, `Cần nhắc lại (4-7 ngày)`, `Nguy cơ nguội (8-14 ngày)`, `Bỏ quên (>14 ngày)`.
  * Chỉ ra cụ thể mỗi nhân viên đang có bao nhiêu khách `Remind` nằm trong vùng nguy hiểm (`>7 ngày`) cần phải ưu tiên gọi/nhắn tin ngay trong tuần tới.

##### 4. Các giả thuyết kinh doanh gợi ý kiểm chứng (Business Hypotheses)
1. **Giả thuyết H1 (Thất thoát do chưa phân công):** *Nhóm Lead không được gắn nhân viên phụ trách (`assigned_users IS NULL`) có tỷ lệ thu thập SĐT thấp hơn ít nhất 40% so với nhóm được gán nhân viên rõ ràng.*
2. **Giả thuyết H2 (Sức mạnh của Follow-up):** *Những khách hàng được nhân viên kiên trì tương tác từ 2 ngày trở lên (`Touchpoint Days >= 2`) có khả năng để lại SĐT và chuyển đổi thành học viên cao gấp đôi so với khách chỉ tương tác trong 1 ngày.*
3. **Giả thuyết H3 (Ngưỡng quá tải của Sale):** *Khi một nhân viên phải xử lý vượt quá ngưỡng $N$ hội thoại mới trong một ngày, số lượng tin nhắn trung bình trao đổi với mỗi khách giảm xuống và kéo theo tỷ lệ xin được SĐT sụt giảm.*

##### 5. Yêu cầu Sản phẩm đầu ra (Deliverables)
* **Dashboard Quản trị Vận hành (2 trang):**
  * *Trang 1 (Sales Team Scorecard & Leakage):* KPI Cards (Tổng Lead, % Chưa phân công, Phone Win-Rate TB, % Follow-up đa ngày), Biểu đồ so sánh tỷ lệ chuyển đổi giữa `Đã phân công` vs. `Chưa phân công`, Biểu đồ Scatter Plot đánh giá hiệu suất Top 10 nhân viên tư vấn.
  * *Trang 2 (Follow-up Persistence & Remind Aging):* Biểu đồ cột/đường thể hiện mối tương quan giữa `Touchpoint Days` và `Tỷ lệ chuyển đổi`, Biểu đồ Cột chồng (Stacked Bar) thống kê số lượng khách `Remind` theo nhóm tuổi tồn đọng (`0-3 ngày`, `4-7 ngày`, `8-14 ngày`, `>14 ngày`) của từng nhân viên.
* **Báo cáo Đề xuất Quy chuẩn Vận hành (SLA Playbook):**
  * Đề xuất bộ quy tắc **SLA (Service Level Agreement)** cho phòng Tư vấn: Thời gian tối đa phải nhận Lead, quy tắc bắt buộc chạm lại lần 2 sau 24h và lần 3 sau 72h trước khi đóng Lead, kèm cơ chế phân bổ lại các Lead đang bị ngâm quá 7 ngày.

---

### 🔵 TRACK 2: TECHNICAL, DATA SCIENCE & NLP
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

#### 📌 Đề B3: Đánh Giá & Tối Ưu Hệ Thống Bot Trả Lời Tự Động (Auto-Reply Bot Optimization)
* **Mục tiêu:** Đo lường độ chính xác của Bot tự động và giảm thiểu tình trạng Bot trả lời sai ngữ cảnh.
* **Nhiệm vụ cụ thể:**
  1. Phân tích các câu hỏi kích hoạt bot (`customer_message`) trong `bot_auto_replies.csv`: Bot đang bắt theo những từ khóa nào?
  2. Nối với `chat_messages_sample.csv` qua `conversation_id` để kiểm tra phản ứng của khách sau khi nhận tin bot: Khách có trả lời tiếp không? Có phản ứng bực mình hay nói bot rep sai không?
  3. Đo lường tỷ lệ giữ chân (Retention Rate) của Bot theo từng kịch bản (`case_id`).
  4. Đề xuất bộ quy tắc Regex / Keyword cải tiến giúp Bot phân biệt trường hợp "hỏi khóa học" (cần người tư vấn) vs "xin tài liệu" (bot rep tự động).
* **Sản phẩm đầu ra:** Báo cáo kiểm toán lỗi của Bot (Bot Audit Report) + File cấu hình rule Regex/Từ khóa tối ưu đề xuất.

---

## 🏆 IV. TIÊU CHÍ ĐÁNH GIÁ (EVALUATION RUBRIC)

Báo cáo kết thúc kỳ thực tập sẽ được đánh giá trên thang điểm 100 dựa trên 4 trụ cột:

1. **Tính chính xác & Xử lý Dữ liệu (25%):**
   * Làm sạch dữ liệu chuẩn, xử lý tốt giá trị thiếu (Missing values), trùng lặp, ngoại lai (Outliers).
   * Khóa ngoại ghép nối chuẩn xác giữa các bảng.
2. **Kỹ năng Kỹ thuật / Trực quan hóa (30%):**
   * Đối với Track Business: Dashboard trực quan, bố cục khoa học, màu sắc hài hòa, biểu đồ đúng mục đích phân tích.
   * Đối với Track Tech: Code viết sạch sẽ (Clean Code), có chú thích rõ ràng, mô hình đánh giá khách quan, tránh rò rỉ dữ liệu (Data Leakage).
3. **Tư duy Kinh doanh & Đào sâu Insight (30%):**
   * Không chỉ dừng lại ở việc mô tả số liệu ("cột A tăng, cột B giảm"), mà phải trả lời được câu hỏi: **"Tại sao lại như vậy?"** và **"Số liệu này có ý nghĩa gì đối với EzTech?"**.
4. **Khả năng Đề xuất Giải pháp (15%):**
   * Đưa ra được ít nhất **3 giải pháp hành động cụ thể** (Actionable Recommendations) có tính khả thi cao để giúp doanh nghiệp cải thiện chuyển đổi.

---

## 🚀 V. HƯỚNG DẪN BẮT ĐẦU NHANH (QUICK START)

### Nạp dữ liệu trong Python (Pandas):
```python
import pandas as pd

# Luôn chỉ định encoding='utf-8-sig' để hiển thị tiếng Việt chuẩn
leads = pd.read_csv('data_for_interns/leads_activities.csv', encoding='utf-8-sig')
posts = pd.read_csv('data_for_interns/social_posts.csv', encoding='utf-8-sig')
comments = pd.read_csv('data_for_interns/social_comments.csv', encoding='utf-8-sig')
bots = pd.read_csv('data_for_interns/bot_auto_replies.csv', encoding='utf-8-sig')
chats = pd.read_csv('data_for_interns/chat_messages_sample.csv', encoding='utf-8-sig')

# Nối bảng Lead với Tin nhắn chat
leads_with_chat = pd.merge(
    chats, 
    leads[['conversation_id', 'customer_name', 'has_phone', 'page_id']], 
    on='conversation_id', 
    how='inner'
)
print("Số dòng chat đã ghép với Lead:", len(leads_with_chat))
```

### Nạp dữ liệu vào Power BI / Excel:
* Mở **Power BI Desktop** $\rightarrow$ Chọn **Get Data** $\rightarrow$ **Text/CSV** $\rightarrow$ Chọn file trong thư mục `data_for_interns`.
* Chọn định dạng file gốc là: `65001: Unicode (UTF-8)`.

---
*Chúc các bạn có một kỳ thực tập bổ ích và tạo ra nhiều giá trị thực tiễn cho doanh nghiệp!*
