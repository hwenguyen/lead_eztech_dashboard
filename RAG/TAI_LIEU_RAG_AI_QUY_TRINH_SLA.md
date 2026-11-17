# Cẩm Nang RAG AI Quy Trình, Metric Dashboard & SLA Vận Hành EzTech

> Tài liệu chuẩn hóa cho **AI Quy Trình & SLA** dùng để:
> 1. Đọc hiểu và đối chiếu số liệu thực tế từ 6 Dashboard của hệ thống EzTech (`Tổng quan & Chỉ số`, `Facebook Analytics`, `TikTok Analytics`, `Báo cáo công việc`, `Chăm sóc Lead / Remind`, `Deal Win & Công nợ`).
> 2. Phát hiện điểm nghẽn SLA, lỗ hổng phễu chuyển đổi và đưa ra **Insight hành động** có định lượng.
> 3. Hướng dẫn chuẩn quy trình CRM, gắn Tag Pancake, chốt chặn Bot tự động và vận hành lớp học.

---

## 1. Định Nghĩa Chuẩn Các Chỉ Số (Metrics) Trên Từng Dashboard

### A. Dashboard Tổng Quan & Chỉ Số (`lead_metrics.py`)
- **Lead Mới (`new_leads`):** Khách hàng có thời điểm tạo hội thoại lần đầu (`first_created_at`) nằm trong kỳ báo cáo.
- **Lead Contact Lại (`recontact_leads`):** Khách hàng tạo **trước** kỳ báo cáo, nhưng có phát sinh tin nhắn mới (của khách hoặc nhân viên) hoặc phát sinh SĐT trong kỳ.
- **Tổng Lead (`total_leads`):** `Lead Mới + Lead Contact Lại` (không trùng lặp theo hội thoại).
- **SĐT thu được (`phone_leads`):** Mỗi số điện thoại chuẩn hóa chỉ tính **1 lần duy nhất** tại thời điểm khách gửi số lần đầu (`phone_at`; nếu NULL lấy `first_created_at`), bao gồm cả khách có SĐT hoặc được gắn tag `đã add`.
  - Tách làm **SĐT Mới** (`new_phone_leads`) và **SĐT Contact Lại** (`recontact_phone_leads`).
  - **Tỷ lệ SĐT / Lead Mới (%)** = `SĐT Mới / Lead Mới * 100%`.
  - **Tỷ lệ SĐT / Tổng Lead (%)** = `Tổng SĐT / Tổng Lead * 100%`.
- **Phạm vi Page mặc định:** Tính mọi Fanpage Facebook & TikTok, **TRỪ các page Zalo cá nhân** (vì Zalo là kênh chăm sóc sau khi đã có SĐT). Các nhóm chat Zalo (`pzl_g_...`) bị lọc bỏ hoàn toàn.
- **Phân loại nhóm Tag:**
  - Nhóm **Đào tạo**: tag `Đào tạo` hoặc `HV TCKT`.
  - Nhóm **Lead Other**: tag `Lead Other`, `Support Other` hoặc `HV Khác`.
  - Nếu 1 khách có cả 2 nhóm tag, hệ thống lấy theo tag được gắn **gần nhất** trong `tag_timeline`.

### B. Dashboard Facebook Analytics (`facebook_metrics.py`)
- **Chỉ số Content & Tương tác:** Tổng bài viết (`total_posts`), tổng cảm xúc (`total_reactions`: Like, Love, Haha, Care, Wow, Sad, Angry), tổng bình luận (`total_comments`), bình luận có SĐT (`comment_phones`), chia sẻ (`total_shares`), trung bình Reactions/bài & Comments/bài.
- **Phễu Facebook:** Lead FB (`new_leads` + `recontact_leads`), SĐT FB (`phone_leads`), Deal Win từ nguồn FB (`deal_wins`), tỷ lệ ra SĐT (`phone_conversion_rate`), tỷ lệ chốt Deal/SĐT (`deal_conversion_rate`).
- **Phân tách 3 nguồn kênh trên Facebook (`channel_breakdown`):**
  1. **Quảng cáo (`ads`):** Lead đi vào từ Facebook Ads (`ad_id`).
  2. **Bài viết (`post`):** Lead tương tác/comment từ bài đăng organic (`post_id`).
  3. **Tự nhiên (`organic`):** Khách chủ động inbox trực tiếp Fanpage không qua Ads hay Post.

### C. Dashboard TikTok Analytics (`tiktok_metrics.py`)
- **Chỉ số Video:** Tổng video đăng tải (`total_posts`), lượt tim (`total_reactions`), chia sẻ (`total_shares`), bình luận (`total_comments`), bình luận có SĐT (`comment_phones`).
- **Phễu TikTok:** Lead TikTok (`new_leads` + `recontact_leads`), SĐT TikTok (`phone_leads`), Deal Win từ nguồn TikTok (`deal_wins`), tỷ lệ ra SĐT & tỷ lệ chốt Deal/SĐT.
- **Phân tách 2 nguồn kênh trên TikTok (`channel_breakdown`):**
  1. **Từ Video (`post`):** Khách comment/nhắn từ video cụ thể.
  2. **Tự nhiên (`organic`):** Khách chủ động nhắn vào inbox kênh TikTok.

### D. Dashboard Báo Cáo Công Việc Tuần (`work_report.py`)
- Đo sản lượng & chất lượng xử lý của **từng nhân viên Sale** (hoặc toàn team) trên cả 3 mặt trận:
  - **TikTok:** Lead mới, Contact lại, Tổng tiếp nhận, SĐT thu được, Tỷ lệ SĐT%.
  - **Facebook:** Lead mới, Contact lại, Tổng tiếp nhận, SĐT thu được, Tỷ lệ SĐT%.
  - **Zalo chăm sóc:** Tổng hội thoại chăm sóc và SĐT phát sinh trên Zalo.
- **Kết quả đầu ra (`student_stats` & `insights`):** Số học viên chốt (`total_deals`), Doanh thu thực thu (`total_revenue`), Giá trị hợp đồng (`total_contract_value`), và chân dung học viên (Ngành nghề, Vị trí công việc, Kỳ vọng học tập).

### E. Dashboard Chăm Sóc Lead (`Remind` & SLA Aging)
- Theo dõi tất cả hội thoại đang cần chăm sóc tiếp (đặc biệt tệp gắn tag `Remind`, `Suy nghĩ`, `Có thông tin`, `Đã gửi TT`, `Quan tâm sâu`).
- **Độ trễ SLA (`days_since_last_contact`):** Số ngày kể từ lần tương tác gần nhất (`contacted_at`) đến hiện tại, chia làm **4 ngưỡng**:
  - `< 1 ngày` (Trong ngày — đạt SLA).
  - `1 – 3 ngày` (Cần nhắc lịch lần 1–2).
  - `4 – 7 ngày` (Nguy cơ nguội — cần đổi góc tiếp cận/tặng tài liệu).
  - `> 7 ngày` (Quá hạn SLA / Tồn đọng bị bỏ quên).

### F. Dashboard Deal Win & Công Nợ (`DealWin`, `SalesDeal`)
- **Deal Win (`deal_wins`):** Học viên đã chốt đăng ký (`is_student = True`), tỷ lệ chuyển đổi `Convert = Deal Win / Tổng SĐT (%)`, xếp hạng Top Sale chốt Deal.
- **Công nợ (`sales_deals`):** Tổng phải thu (`tong_tien`), Đã thu (`da_thu`), Còn nợ (`con_no = phai_thu - da_thu - da_thu_no_cu`).

---

## 2. Bộ Ngưỡng Cảnh Báo SLA & Benchmark Đánh Giá Insight EzTech

Khi đọc số liệu thực tế từ các Dashboard, AI Quy trình & SLA đối chiếu theo các ngưỡng chuẩn nội bộ sau:

1. **Lỗ hổng Phân công Nhân viên (`Chưa phân công`):**
   - **Ngưỡng Tốt:** `< 5%` tổng Lead kênh nguồn chưa gắn Sale.
   - **Cảnh báo Vàng:** `5% – 10%` Lead chưa có người nhận.
   - **Báo động Đỏ:** `> 10%` Lead chưa phân công.
   - *Bằng chứng nội bộ:* Lead kênh nguồn không có nhân viên phụ trách (`assigned_users IS NULL`) có tỷ lệ thu được SĐT chỉ quanh `~17%`, thấp hơn **~3.5 lần** so với Lead có Sale phụ trách (`~60%`), gây thất thoát trực tiếp nguồn SĐT.

2. **Tỷ lệ Thu SĐT Kênh Nguồn (`SĐT / Lead`):**
   - **Mục tiêu tổng kênh nguồn:** `>= 50%`.
   - **TikTok:** Mức tốt `50% – 62%`; dưới `40%` là cần rà soát lại CTA xin SĐT hoặc tỷ lệ bỏ sót tin nhắn trên page.
   - **Facebook:** Mức tốt `40% – 48%`; dưới `35%` là **Cảnh báo** (kiểm tra chất lượng tệp Ads vs Organic, hoặc tốc độ kéo hội thoại vượt mốc 4 tin nhắn — vì hội thoại dừng dưới 4 tin nhắn có tỷ lệ ra SĐT thấp hơn ~3 lần so với hội thoại >= 4 tin).

3. **SLA Đeo Bám & Tồn Đọng `Remind`:**
   - **Ngưỡng Tốt:** Tỷ lệ `Remind > 7 ngày` dưới `20%` tổng tệp `Remind`.
   - **Cảnh báo Vàng:** `20% – 40%` khách `Remind` quá 7 ngày chưa nhắn lại.
   - **Báo động Đỏ:** `> 40%` tệp `Remind` quá 7 ngày chưa tương tác lại.
   - *Bằng chứng nội bộ:* Khách chỉ tương tác trong 1 ngày tỷ lệ thành Học viên chỉ `~14%`; khi Sale đeo bám qua **>= 4–5 ngày khác nhau**, tỷ lệ chuyển đổi lên Học viên tăng gấp **2.2 lần** (`~30–31%`).

4. **Tỷ lệ Chuyển Đổi Cuối Phễu (`Deal Win / Tổng SĐT`):**
   - **Mục tiêu chuẩn:** `15% – 25%` trên lượng SĐT thu được (tùy thời điểm khai giảng).
   - **Điểm nghẽn phổ biến:** Nếu `SĐT` cao nhưng `Deal Win / SĐT < 10%` → nghẽn ở chặng **Zalo chăm sóc** (chưa chuyển qua các vòng `Đã gửi TT` → `Remind` → `Quan tâm sâu` hoặc tỷ lệ học viên gắn tag chưa đồng bộ).

5. **Cân Bằng Tải & Hiệu Suất Giữa Các Sale:**
   - So sánh tỷ lệ `SĐT / Lead` và số lượng `Remind > 7 ngày` giữa các nhân viên trong cùng kỳ.
   - Nếu chênh lệch tỷ lệ ra SĐT giữa top Sale và người thấp nhất **> 20 điểm %**, hoặc số lượng tồn đọng `Remind > 7 ngày` dồn cục vào 1–2 nhân sự → cần phân bổ lại Lead hoặc kèm cặp lại kịch bản Step 1–2.

---

## 3. Khung Trả Lời Insight Chuẩn 4 Phần (Bắt Buộc Khi Phân Tích Số Liệu)

Mỗi khi đọc thông số Dashboard để đưa ra nhận định cho quản lý / vận hành, trả lời gọn gàng theo đúng 4 mục:
1. **Bức tranh số liệu thực tế:** Nêu rõ khoảng thời gian phân tích, trích dẫn chính xác các con số từ từng Dashboard liên quan (tổng Lead, SĐT, CR%, FB/TikTok breakdown, Deal Win, Remind aging) và biến động so với kỳ trước (nếu có).
2. **Điểm nghẽn & Cảnh báo SLA:** Chỉ đích danh kênh/page, nhân viên hoặc chặng phễu đang vượt ngưỡng cảnh báo (ví dụ: tỷ lệ `Chưa phân công`, page rớt CR, tỷ lệ `Remind > 7 ngày`, Ads vs Organic lệch hiệu suất).
3. **Nguyên nhân gốc rễ (đối chiếu quy trình EzTech):** Giải thích tại sao chỉ số bị tụt (ví dụ: bỏ sót gán Sale khiến hội thoại dừng dưới 3 tin, dồn Lead vào một người, chưa đeo bám đủ chuỗi Remind 3 lần sang Zalo).
4. **Đề xuất hành động ưu tiên:** 2–4 đầu việc cụ thể, giao rõ cho kênh/bộ phận/nhân sự nào và chỉ số kỳ vọng cải thiện.

---

## 4. Quy Trình CRM, Chuỗi Tag & Chốt Chặn Bot Tự Động

### Chuỗi trạng thái chuẩn trên Zalo chăm sóc (từ trái sang phải)
1. **`Có thông tin`**: Đã lấy được SĐT từ nguồn (TikTok, Facebook, Web, giới thiệu) + đã kết bạn Zalo + hỏi câu khai thác insight.
2. **`Đã gửi TT`**: Đã gửi lộ trình Data Finance hoặc link demo B2C sau bước khai thác.
3. **`Remind`**: Đang chăm sóc qua các vòng kịch bản Remind (Video Scope, Feedback, Layout, Quyền lợi, Bộ 100 file, Lịch khai giảng, Data Talk).
4. **`Suy nghĩ`**: Sau khi đã Remind **3 lần** mà khách chưa phản hồi.
5. **`Quan tâm sâu`**: Khách hỏi chi tiết lịch học, học phí, trường hợp cụ thể — cần bám sát để chốt.
6. **`Đồng ý học`**: Khách đồng ý học nhưng chưa điền link đăng ký hoặc chưa chuyển khoản.
7. **`Đã là học viên`**: Đã chuyển khoản, lập nhóm Support 1-1 và add vào group lớp (gắn thêm `Còn CN` nếu đóng theo đợt/còn công nợ).

### Quy tắc gắn Tag trên kênh nguồn (TikTok / Mess FB) & Chốt chặn Bot
- Khi xin được SĐT và kết bạn Zalo, gắn thẻ `đã add` và ghi chú: `"[Tên NV] + đã add ở + [Zalo add]"`.
- **Chốt chặn Bot Auto-Reply:** Bot tự động bỏ qua không trả lời nếu hội thoại có tag học viên/khóa học (`Đã là học viên`, `Đào tạo`, `HV TCKT`, `HV Khác`) hoặc tin nhắn khách chứa từ khóa hỏi về khóa học/học phí/lộ trình/lớp học để nhân viên tư vấn 1-1.

---

## 5. Quy Trình Vận Hành Lớp Học (Trước - Trong - Sau Khóa)

- **Trước khóa:** Thu học phí linh hoạt, lập nhóm Zalo Support 1-1 (gồm 1 nick công ty, chị An, bạn support 1-1, học viên), tạo account Power BI / E-learning ghim lên nhóm, hỗ trợ cài đặt Power BI Desktop / Excel / Zoom, add học viên vào group lớp & SharePoint (3 folder: `BTVN`, `Học liệu`, `Record`).
- **Trong khóa:** Sáng & chiều nhắc nội dung buổi học; mở Zoom 19h15, nhắc vào lớp 19h20–19h25; bấm record, điểm danh, gửi recap & up record/học liệu lên SharePoint; nhắc & feedback BTVN.
- **Sau khóa:** Nhắc làm Bài tập cuối khóa (BTCK), xin feedback học viên sau buổi cuối vài tiếng, mở khóa E-learning K3 sau khi học viên hoàn thành K1 & K2.
