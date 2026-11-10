# 📊 BÁO CÁO PHÂN TÍCH CHI TIẾT CASE A3: ĐÁNH GIÁ NĂNG LỰC TƯ VẤN & SLA VẬN HÀNH CHĂM SÓC KHÁCH HÀNG
**Dự án:** EzTech Data & Education Analytics — Track 1 (Business, Marketing & Insights)  
**Dữ liệu nguồn:** `leads_activities.csv` (16.774 bản ghi — Mốc chốt dữ liệu `2026-11-01`)  
**Ngày lập báo cáo:** 09/11/2026

---

## 📌 I. TÓM TẮT ĐIỀU HÀNH (EXECUTIVE SUMMARY)

Báo cáo này kiểm toán toàn diện hiệu suất vận hành của đội ngũ Tư vấn viên (Sales/CSKH) tại EzTech qua 2 chặng: **Chặng 1 (Săn SĐT trên 4 Kênh Nguồn)** và **Chặng 2 (Chăm sóc sâu & Đeo bám trên 4 Kênh Zalo)**.

### 🔑 4 Phát hiện cốt lõi (Key Findings):
1. **Lỗ hổng Thất thoát Lớn nhất — 20,4% Lead Kênh Nguồn chưa được phân công nhân viên:** Có tới **1.474 / 7.223 Lead Kênh Nguồn** (và **3.184 / 16.774 Lead toàn hệ thống — 19,0%**) bị bỏ trống nhân viên phụ trách (`assigned_users IS NULL`). Hậu quả là tỷ lệ thu được SĐT của nhóm bị bỏ rơi này chỉ đạt **17,2%**, thấp hơn **3,5 lần** so với nhóm có nhân viên phụ trách (**59,7%**), làm thất thoát ước tính **~626 SĐT khách hàng tiềm năng**.
2. **Chênh lệch Hiệu suất Xin SĐT giữa các Nhân viên lên tới 38,5 điểm %:** Trên các Kênh Nguồn, nhóm nhân sự dẫn đầu (`Bảo Trânn: 80,7%`, `Khuất Cường: 74,5%`, `Trần Đạt: 71,1%`, `Thanh Mai: 69,2%`) đạt hiệu suất thu SĐT gấp từ **1,4 đến 1,9 lần** so với nhóm đang bị quá tải hoặc cần hỗ trợ (`Linh Bùi: 51,3%`, `Hồng Minh: 51,5%`, `Pham Thu Huyen: 42,2%`).
3. **Bằng chứng Vàng về Sức mạnh của Đeo bám Đa ngày (`Touchpoint Days >= 2`):** Những khách hàng chỉ được tương tác trong **1 ngày duy nhất** có tỷ lệ chuyển thành Học viên chỉ đạt **14,34%**. Khi nhân viên kiên trì đeo bám sang **ngày thứ 3**, tỷ lệ Học viên tăng lên **20,67%**, và khi chạm từ **4–5 ngày trở lên**, tỷ lệ chuyển đổi thành Học viên vọt lên **30,14% – 31,42% (tăng gấp 2,2 lần)**!
4. **Báo động Đỏ về Tồn đọng Nhắc hẹn (`Remind` Aging Backlog):** Trong tổng số **4.104 khách hàng** đang gắn thẻ cần chăm sóc tiếp (`Remind`, `Đang tư vấn`, `Quan tâm`), có tới **3.759 khách (91,6%)** đã **quá 7 ngày chưa được nhân viên nhắn tin lại** (trong đó **1.591 khách — 38,8%** đã bị bỏ quên trên 30 ngày).

---

## 🚨 II. KIỂM TOÁN LỖ HỔNG PHÂN CÔNG & CÂN BẰNG TẢI (LEAKAGE & WORKLOAD AUDIT)

### 1. So sánh Nhóm "Đã phân công" vs. "Chưa phân công" (Kiểm chứng Giả thuyết H1)

| Phạm vi Dữ liệu | Trạng thái Phân công (`assigned_users`) | Số lượng Lead | Tỷ trọng (%) | Số Lead có SĐT | Tỷ lệ ra SĐT (CR %) | Tin nhắn TB (`AvgMsg`) | Tỷ lệ Chăm sóc $\ge 2$ ngày |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Bốn Kênh Nguồn Marketing** *(7.223 Leads)* | ✅ **Đã có Nhân viên nhận** | 5.749 | 79,6% | 3.430 | **59,7%** | 8,1 tin | **61,9%** |
| | ❌ **Chưa phân công (`NULL`)** | **1.474** | **20,4%** | 254 | **17,2%** | 3,0 tin | 29,0% |
| **2. Bốn Kênh Zalo Chăm sóc** *(9.553 Leads)* | ✅ **Đã có Nhân viên nhận** | 7.843 | 82,1% | 6.323 | **80,6%** | 38,7 tin | **78,4%** |
| | ❌ **Chưa phân công (`NULL`)** | **1.710** | **17,9%** | 121 | **7,1%** | 111,2 tin | 67,9% |
| **3. Toàn Hệ thống** *(16.776 Leads)* | ✅ **Đã có Nhân viên nhận** | 13.592 | 81,0% | 9.753 | **71,8%** | 25,8 tin | **71,4%** |
| | ❌ **Chưa phân công (`NULL`)** | **3.184** | **19,0%** | 375 | **11,8%** | 61,1 tin | 49,9% |

> [!CAUTION]
> **Thiệt hại định lượng từ 1.474 Lead Nguồn "Chưa phân công":**
> - Khi một khách hàng nhắn tin vào Fanpage/TikTok mà không có nhân viên nào nhận trách nhiệm (`assigned_users IS NULL`), cuộc hội thoại dừng lại trung bình ở **3,0 tin nhắn** (chủ yếu là tin nhắn tự động của Bot) và tỷ lệ thu được SĐT sụt giảm từ **59,7% xuống 17,2%** (mất đi **42,5 điểm %**).
> - **Số SĐT bị đánh rơi:** $1.474 \times (59,7\% - 17,2\%) = \mathbf{626\text{ SĐT khách hàng tiềm năng}}$ bị lãng phí hoàn toàn!

---

### 2. Truy tìm Kênh đang bị "Bỏ rơi" nhiều nhất

| Tên Kênh (`page_id`) | Nhóm Kênh | Tổng số Lead | Số Lead Chưa phân công | Tỷ lệ Bỏ sót (`Unassigned %`) | Mức độ Cảnh báo |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Chị Kế Toán GenZ** | Kênh Nguồn (TikTok) | 421 | **343** | **81,5%** | 🔴 **Nghiêm trọng nhất (Gần như bỏ trắng)** |
| **Hành trang cho kế toán** | Kênh Nguồn (TikTok) | 983 | **391** | **39,8%** | 🔴 **Rất cao (Cứ 5 khách thì bỏ sót 2)** |
| **Tuấn Anh Data** | Kênh Zalo Chăm sóc | 2.899 | **787** | **27,1%** | 🟠 **Cao (Khách Zalo chưa gán Sale)** |
| **Hiền Minh Eztech** | Kênh Zalo Chăm sóc | 2.157 | **424** | **19,7%** | 🟡 **Trung bình cao** |
| **Anh Kế toán làm Data (TikTok)** | Kênh Nguồn (TikTok) | 3.059 | **554** | **18,1%** | 🟡 **Trung bình cao (554 khách bị sót)** |
| **Eztech Consultant** | Kênh Zalo Chăm sóc | 2.023 | 288 | 14,2% | 🟢 **Trong ngưỡng kiểm soát** |
| **Eztech Phân Tích Dữ Liệu** | Kênh Zalo Chăm sóc | 2.474 | 211 | 8,5% | 🟢 **Tốt** |
| **Anh Kế toán làm Data (Facebook)** | Kênh Nguồn (FB) | 2.760 | 186 | **6,7%** | 🟢 **Tốt nhất hệ thống** |

---

## 🏆 III. THẺ ĐIỂM HIỆU SUẤT ĐỘI NGŨ TƯ VẤN (CONSULTANT SCORECARD)

Bảng tổng hợp hiệu suất của **Top 12 Nhân viên Tư vấn** trên cả Kênh Nguồn (đo kỹ năng xin SĐT) và Kênh Zalo (đo kỹ năng chăm sóc sâu & chốt học viên):

| Hạng (Theo Tải) | Nhân viên Tư vấn (`assigned_users`) | Tổng Lead Đảm nhận | Lead Kênh Nguồn | Lead Kênh Zalo | **Tỷ lệ Xin SĐT Kênh Nguồn (`Src CR %`)** | Tỷ lệ SĐT Toàn bộ (`All CR %`) | Tin nhắn TB / Lead | Tỷ lệ Đeo bám $\ge 2$ ngày | Số Lead gắn tag Học viên / Đào tạo | Tồn đọng `Remind > 7 ngày` | Phân nhóm Nhân sự |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **1** | **Trần Đạt** | **1.906** | 679 | 1.227 | **71,1%** | 72,7% | 38,0 | 77,0% | 304 | 424 | 🌟 **Ngôi sao Toàn diện** |
| **2** | **Liên Vũ** | **1.472** | 618 | 854 | **64,1%** | 77,6% | 26,8 | 78,5% | **510** | **510** | 🌟 **Ngôi sao Chốt HV** |
| **3** | **Linh Bùi** | **1.459** | **844** | 615 | 51,3% | 65,5% | 15,7 | 63,8% | 378 | 149 | ⚠️ **Quá tải Kênh Nguồn** |
| **4** | **Hồng Minh** | **1.406** | 613 | 793 | 51,5% | 68,4% | 31,8 | **86,1%** | **447** | 420 | 💪 **Kiên trì Đeo bám nhất** |
| **5** | **Nguyen Gia Huy** | **1.299** | 460 | 839 | 57,2% | 72,5% | 19,2 | 65,5% | 203 | 212 | 📈 **Ổn định (Mid-Core)** |
| **6** | **Bảo Ngọc** | **1.290** | 617 | 673 | 55,3% | 64,3% | 23,8 | 65,3% | 218 | 213 | 📈 **Ổn định (Mid-Core)** |
| **7** | **Hiền Minh Lý** | **1.162** | 355 | 807 | **64,2%** | 78,3% | 36,6 | **83,0%** | **716** | 341 | 🏆 **Quán quân Đào tạo** |
| **8** | **Nguyễn Thị Thanh Mai** | **833** | 299 | 534 | **69,2%** | 80,2% | 7,8 | 50,1% | 51 | 10 | 🎯 **Chuyên gia Săn SĐT** |
| **9** | **Khuất Cường** | **815** | 361 | 454 | **74,5%** | **81,2%** | 32,0 | 76,0% | 304 | 194 | 🌟 **Ngôi sao Chất lượng** |
| **10** | **Pham Thu Huyen** | **596** | 360 | 236 | **42,2%** | 59,4% | 18,7 | 58,1% | 108 | 54 | 🛠️ **Cần đào tạo thêm** |
| **11** | **My Trà** | **357** | 214 | 143 | 59,8% | 74,8% | 11,6 | 66,9% | 44 | 9 | 🎯 **Tải nhẹ - Hiệu quả khá** |
| **12** | **Bảo Trânn** | **326** | 171 | 155 | **80,7%** | **85,9%** | 8,1 | 59,8% | 17 | 8 | 🎯 **Quán quân Tỷ lệ SĐT** |

### 💡 Phân tích Ma trận Nhân sự (Insights từ Scorecard):
1. **Bằng chứng về Quá tải Kênh Nguồn (Kiểm chứng Giả thuyết H3):**
   * `Linh Bùi` đang phải gánh khối lượng Lead Kênh Nguồn lớn nhất công ty (**844 Leads nguồn** — cao hơn trung bình đội ngũ tới 45%). Hệ quả là số tin nhắn trao đổi trung bình của Linh Bùi bị kéo tụt xuống chỉ còn **15,7 tin**, tỷ lệ đeo bám đa ngày giảm còn **63,8%**, và tỷ lệ xin SĐT kênh nguồn chỉ đạt **51,3%** (thấp hơn `Khuất Cường` 23,2 điểm % và thấp hơn `Trần Đạt` 19,8 điểm %).
2. **Nhóm "Bàn tay Vàng" trong khâu Xin SĐT (`Bảo Trânn: 80,7%`, `Khuất Cường: 74,5%`, `Trần Đạt: 71,1%`, `Thanh Mai: 69,2%`):**
   * Đặc biệt là `Khuất Cường` và `Trần Đạt`: Không chỉ đạt tỷ lệ xin SĐT trên 71% mà còn duy trì độ sâu tư vấn rất cao (`32 – 38 tin nhắn/khách`) và mang về đồng đều **304 học viên** mỗi người.
3. **Nhóm Chuyên gia Chăm sóc & Chốt Học viên trên Zalo (`Hiền Minh Lý` & `Liên Vũ` & `Hồng Minh`):**
   * Đây là 3 nhân sự có tỷ lệ đeo bám đa ngày cao nhất công ty (**78,5% – 86,1%**) và nắm giữ số lượng Học viên lớn nhất (`Hiền Minh Lý: 716 HV`, `Liên Vũ: 510 HV`, `Hồng Minh: 447 HV`).

---

## 🔥 IV. TÁC ĐỘNG CỦA ĐEO BÁM ĐA NGÀY & TỒN ĐỌNG NHẮC HẸN (`REMIND` AGING)

### 1. Chứng minh Giá trị của việc Đeo bám Đa ngày (`Touchpoint Days` — Kiểm chứng Giả thuyết H2)
Dựa trên số ngày tương tác thực tế được tách từ cột `contacted_dates`, dữ liệu toàn hệ thống chứng minh quy luật **"Càng kiên trì chạm lại, tỷ lệ thành Học viên càng tăng vọt"**:

| Số ngày Chăm sóc (`Touchpoint Days`) | Số lượng Lead (Toàn hệ thống) | Tỷ trọng (%) | Tin nhắn TB (`AvgMsg`) | Tỷ lệ có SĐT (`Phone CR %`) | **Tỷ lệ chuyển thành Học viên / Đào tạo (`HV Rate %`)** | Mức tăng trưởng Học viên so với 1 ngày |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Chỉ tương tác 1 ngày** | 5.480 | 32,7% | 7,1 tin | 53,0% | **14,34%** | *Mốc cơ sở (1,0x)* |
| **Tương tác 2 ngày** | 3.485 | 20,8% | 20,0 tin | 62,8% | **15,55%** | Tăng **+1,08 lần** |
| **Tương tác 3 ngày** | 1.969 | 11,7% | 28,3 tin | 62,1% | **20,67%** | Tăng **+1,44 lần** |
| **Tương tác 4 – 5 ngày** | 2.359 | 14,1% | 49,8 tin | **68,7%** | **30,14%** | 🚀 **Tăng gấp 2,10 lần** |
| **Tương tác trên 5 ngày** | 3.482 | 20,8% | 75,5 tin | 62,9% | **31,42%** | 🚀 **Tăng gấp 2,19 lần** |

* **Riêng trên 4 Kênh Nguồn:** Nhóm khách chỉ tương tác 1 ngày có tỷ lệ Học viên là **15,01%**, nhưng nhóm được tương tác từ `4 – 5 ngày` đạt **22,46%** và nhóm `> 5 ngày` đạt tới **33,61%**!
* **Kết luận Giả thuyết H2:** Hoàn toàn chính xác! Một học viên kế toán hiếm khi quyết định đóng học phí ngay trong ngày đầu tiên nhắn tin. Việc nhân viên kiên trì chạm lại từ **ngày thứ 3 đến ngày thứ 5** là chìa khóa vàng giúp nhân đôi tỷ lệ chuyển đổi (từ 14,3% lên >30,1%).

---

### 2. Kiểm toán Tuổi nợ Tương tác của Tệp khách `Remind` (Aging Backlog tính đến `2026-11-01`)
Hiện có tổng cộng **4.104 khách hàng** đang mang các thẻ trạng thái cần theo dõi tiếp (`Remind`, `Đang tư vấn`, `Quan tâm sâu`, `Có thông tin`):

```
Phân bổ 4.104 Khách hàng trong Phễu Chăm sóc (Remind / Đang tư vấn):
├── 🟢 0 – 3 ngày (Đang chăm nóng):        128 khách ( 3,1%)  █
├── 🟡 4 – 7 ngày (Đến hạn cần nhắc lại):  217 khách ( 5,3%)  ██
├── 🟠 8 – 14 ngày (Nguy cơ nguội lạnh): 1.176 khách (28,7%)  ███████████
├── 🔴 15 – 30 ngày (Quá hạn nặng):        992 khách (24,2%)  █████████
└── ⚫ Trên 30 ngày (Bỏ quên hoàn toàn): 1.591 khách (38,8%)  ███████████████
```

* **Điểm nghẽn tồn đọng:** Có tới **3.759 / 4.104 khách (91,6%)** đã **quá 7 ngày** không nhận được bất kỳ tin nhắn hỏi thăm nào mới từ nhân viên tư vấn. Lượng tồn đọng `Remind > 7 ngày` lớn nhất đang nằm tại giỏ của: `Liên Vũ` (510 khách), `Trần Đạt` (424 khách), `Hồng Minh` (420 khách) và `Hiền Minh Lý` (341 khách).

---

## 📋 V. ĐỀ XUẤT BỘ QUY CHUẨN VẬN HÀNH (SLA PLAYBOOK) & GIẢI PHÁP

Để thu hồi ngay các cơ hội bị bỏ phí và chuẩn hóa kỷ luật đội ngũ Sale, báo cáo đề xuất **Bộ Quy chuẩn SLA 4 Điểm (4-Point SLA Playbook)**:

### 1. Quy chuẩn SLA #1 — "Zero Unassigned Lead" (Xóa sổ 20,4% Lead không người nhận)
* **Mục tiêu:** Giảm tỷ lệ `Unassigned Rate` trên 4 Kênh Nguồn từ **20,4% xuống < 1,0%**, thu hồi **+626 SĐT tiềm năng**.
* **Cơ chế thực thi:**
  * Cấu hình tự động chia đều hội thoại (Auto Round-Robin trên Pancake) cho nhân viên đang trong ca trực ngay khi khách nhắn tin đầu tiên, đặc biệt bắt buộc bật ngay cho 2 kênh đang bị bỏ quên là `Chị Kế Toán GenZ` (81,5% chưa gán) và `Hành trang cho kế toán` (39,8% chưa gán).
  * **Cam kết SLA nhận khách:** Mọi Lead mới phát sinh phải có tên nhân viên phụ trách (`assigned_users`) trong vòng **tối đa 15 phút** (giờ hành chính & ca tối) hoặc trước **08h30 sáng hôm sau** (đối với khách nhắn sau 22h30 đêm).

### 2. Quy chuẩn SLA #2 — Cân bằng tải Kênh Nguồn & Ghép cặp Đào tạo (Buddy Coaching)
* **Cân bằng tải (Re-balancing):** Giảm bớt 25%–30% lượng Lead Kênh Nguồn mới chia cho `Linh Bùi` (đang quá tải ở mức 844 leads nguồn) và phân bổ sang cho các nhân sự đang có tỷ lệ chuyển đổi SĐT rất cao nhưng còn dư công suất nguồn như `Bảo Trânn` (`Src CR = 80,7%`), `Khuất Cường` (`74,5%`), `Nguyễn Thị Thanh Mai` (`69,2%`).
* **Đào tạo nội bộ:** Đúc kết kịch bản xin SĐT của `Bảo Trânn`, `Khuất Cường` và `Trần Đạt` thành tài liệu mẫu để huấn luyện trực tiếp 1-1 cho nhóm có `Src CR < 52%` (`Pham Thu Huyen: 42,2%`, `Linh Bùi: 51,3%`).

### 3. Quy chuẩn SLA #3 — Quy tắc Đeo bám "Nhịp chạm 1 - 3 - 5" (Bắt buộc tối thiểu 3 ngày chạm)
* Vì số liệu chứng minh chạm từ 3–5 ngày giúp nhân đôi tỷ lệ thành Học viên (từ 14,3% lên >30,1%), nhân viên tuyệt đối **không được ngừng chăm sóc sau ngày đầu tiên**:
  * **Ngày 1 (Day 1):** Phản hồi nhu cầu, tặng File mẫu / giải đáp thắc mắc và xin SĐT kết bạn Zalo.
  * **Ngày 3 (Day 3 — Sau 48h):** Gửi thêm 1 video hướng dẫn ngắn hoặc hỏi thăm xem khách đã mở và áp dụng được File mẫu hôm trước chưa.
  * **Ngày 5 (Day 5 — Sau 96h):** Gửi Case Study kết quả của học viên cùng ngành kế toán + Mời tham gia buổi học thử / hội thảo `Data Talk` hoặc ưu đãi khóa học.

### 4. Quy chuẩn SLA #4 — Chiến dịch "Giải cứu 3.759 Khách Remind Quá hạn" & Luật Thu hồi Giỏ khách
* **Chiến dịch Re-activation trong tuần tới:** Sử dụng tính năng Broadcast / Nhắn tin chăm sóc lại theo danh sách lọc cho **2.168 khách** thuộc nhóm `8 – 14 ngày` (1.176 khách) và `15 – 30 ngày` (992 khách) bằng một thông điệp giá trị mới (ví dụ: tặng Bộ công cụ AI/Power Query mới cập nhật tháng 11).
* **Luật Thu hồi Lead (Clawback Rule):** Bất kỳ khách hàng nào gắn thẻ `Remind` hoặc `Đang tư vấn` mà nhân viên phụ trách để quá **10 ngày không phát sinh tin nhắn mới**, hệ thống sẽ tự động thu hồi và chuyển giao cho nhân viên khác chăm sóc.
