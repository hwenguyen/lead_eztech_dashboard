# 📊 BÁO CÁO PHÂN TÍCH CHI TIẾT CASE A1: PHỄU CHUYỂN ĐỔI LEAD & TỐI ƯU TỶ LỆ THU THẬP SĐT
**Dự án:** EzTech Data & Education Analytics — Track 1 (Business, Marketing & Insights)  
**Dữ liệu nguồn:** `leads_activities.csv` (16.774 bản ghi thực tế)  
**Ngày lập báo cáo:** 09/11/2026

---

## 📌 I. TÓM TẮT ĐIỀU HÀNH (EXECUTIVE SUMMARY)

Báo cáo này phân tích toàn diện hành trình chuyển đổi của **16.774 khách hàng tiềm năng (Leads)** tại EzTech, trong đó tách biệt rõ **7.223 Leads thuộc 4 Kênh Nguồn Marketing (Facebook & TikTok)** và **9.553 Leads thuộc 4 Kênh Zalo Chăm sóc**.

### 🔑 4 Phát hiện cốt lõi (Key Findings):
1. **Hiệu suất Phễu Kênh Nguồn đạt 51,00% ra SĐT và 16,10% chuyển thành Học viên:** Trong 7.223 Leads từ 4 kênh nguồn, có **3.684 khách** để lại SĐT (`CR = 51,00%`) và **1.163 khách** chuyển đổi sang nhóm Quan tâm sâu / Học viên (`31,57%` tính trên tệp đã có SĐT).
2. **Nghịch lý Kênh TikTok vs. Facebook (Bác bỏ định kiến "TikTok chỉ toàn khách dạo"):** Kênh `Anh Kế toán làm Data (TikTok)` dẫn đầu tuyệt đối toàn công ty cả về sản lượng (**3.059 Leads**) lẫn tỷ lệ thu thập SĐT (**61,6%**) và tỷ lệ Học viên (**27,0% — 826 học viên**), vượt xa `Anh Kế toán làm Data (Facebook)` (**42,8%** ra SĐT, **11,9%** Học viên) dù số tin nhắn trung bình trên TikTok ngắn hơn (6,1 tin so với 10,0 tin trên Facebook).
3. **"Thung lũng chết" ở tin nhắn thứ 2–3 và "Điểm bùng nổ" ở tin nhắn thứ 4:** Những hội thoại dừng lại dưới 4 tin nhắn có tỷ lệ ra SĐT chỉ đạt **21,01%**, nhưng khi nhân viên kéo được khách tương tác từ **4 tin nhắn trở lên (`message_count >= 4`)**, tỷ lệ thu thập SĐT tăng vọt gấp **3 lần** lên **62,71%**.
4. **Khung giờ vàng thực sự nằm ở Buổi tối (`18h–23h`) và Cuối tuần:** Có tới **40,2%** tổng lượng Lead kênh nguồn đổ về từ `18h00 – 23h59` với tỷ lệ cho SĐT cao nhất trong ngày (**52,3% – 56,4%**), vượt qua cả giờ hành chính buổi sáng (**48,8%**) và buổi chiều (**46,6%**).

---

## 🏗️ II. PHÂN TÍCH PHỄU CHUYỂN ĐỔI & HIỆU QUẢ KÊNH (FUNNEL & CHANNEL ATTRIBUTION)

### 1. Chuẩn hóa Phạm vi Dữ liệu (Tách Kênh Nguồn vs. Kênh Zalo)
Để không làm sai lệch mẫu số đánh giá hiệu quả Marketing, 8 trang trong cột `page_id` được chia đúng theo chức năng vận hành thực tế:

| Nhóm Kênh | Tên Kênh (`page_id`) | Tổng Lead | Đã liên hệ (`is_contacted`) | Tương tác $\ge 3$ tin | Có SĐT (`has_phone` / `Đã add`) | Tỷ lệ ra SĐT (CR %) | Tag Học viên / Đào tạo | Tin nhắn TB (Median) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Kênh Nguồn Marketing** *(Acquisition)* | **Anh Kế toán làm Data (TikTok)** | 3.059 | 3.058 (100%) | 2.436 (79,6%) | 1.885 | **61,6%** | 826 (27,0%) | 6,1 (5) |
| | **Anh Kế toán làm Data (Facebook)** | 2.760 | 2.760 (100%) | 2.505 (90,8%) | 1.180 | **42,8%** | 329 (11,9%) | 10,0 (9) |
| | **Hành trang cho kế toán (TikTok)** | 983 | 983 (100%) | 686 (69,8%) | 494 | **50,3%** | 0 (0,0%) | 3,8 (4) |
| | **Chị Kế Toán GenZ (TikTok)** | 421 | 421 (100%) | 201 (47,7%) | 125 | **29,7%** | 8 (1,9%) | 2,8 (2) |
| **Tổng Nhóm 1** | **4 Kênh Nguồn Marketing** | **7.223** | **7.222 (100%)** | **5.828 (80,7%)** | **3.684** | **51,0%** | **1.163 (16,1%)** | **7,0 (6)** |
| **2. Kênh Zalo Chăm sóc** *(Care & Follow-up)* | **Tuấn Anh Data** | 2.899 | 2.899 (100%) | 2.712 (93,5%) | 1.625 | **56,1%** | 692 (23,9%) | 62,4 (24) |
| | **Eztech Phân Tích Dữ Liệu** | 2.474 | 2.474 (100%) | 2.397 (96,9%) | 2.008 | **81,2%** | 258 (10,4%) | 44,0 (34) |
| | **Hiền Minh Eztech** | 2.157 | 2.157 (100%) | 2.069 (95,9%) | 1.512 | **70,1%** | 1.102 (51,1%) | 73,0 (40) |
| | **Eztech Consultant** | 2.023 | 2.023 (100%) | 1.551 (76,7%) | 1.299 | **64,2%** | 325 (16,1%) | 23,0 (6) |
| **Tổng Nhóm 2** | **4 Kênh Zalo Chăm sóc** | **9.553** | **9.553 (100%)** | **8.729 (91,4%)** | **6.444** | **67,5%** | **2.377 (24,9%)** | **51,7 (25)** |

---

### 2. Sơ đồ Phễu Chuyển đổi 5 Tầng (4 Kênh Nguồn Marketing)

```
[Tầng 1] Tổng Lead Kênh Nguồn mới vào       ██████████████████████████████  7.223 (100,0%)
   │     (Tỷ lệ phản hồi ban đầu: 99,99%)
[Tầng 2] Đã có phản hồi (is_contacted = t)   ██████████████████████████████  7.222 (100,0%)
   │     (Rơi rụng 1.394 khách chỉ nhắn 0-2 tin: -19,3%)
[Tầng 3] Tương tác qua lại (>= 3 tin nhắn)   ████████████████████████░░░░░░  5.828 (80,7%)
   │     (Rơi rụng 633 khách ở tin thứ 3: -8,8%)
[Tầng 4] Hội thoại đủ sâu (>= 4 tin nhắn)    █████████████████████░░░░░░░░░  5.195 (71,9%)
   │     (Chuyển đổi thành SĐT liên hệ)
[Tầng 5] Thu thập SĐT thành công             ███████████████░░░░░░░░░░░░░░░  3.684 (51,0%)
   │     (Chuyển hóa sang Đào tạo / Học viên)
[Tầng 6] Nhóm Học viên / Quan tâm Khóa học   █████░░░░░░░░░░░░░░░░░░░░░░░░░  1.163 (16,1%)
```

> [!IMPORTANT]
> **Insight từ Phễu & Kênh Nguồn:**
> - **Sự vượt trội của TikTok `Anh Kế toán làm Data`:** Không chỉ mang về lượng Lead lớn nhất (`3.059` khách), kênh này còn có tỷ lệ chuyển đổi ra SĐT đạt **61,6%** (cao hơn Facebook tới **+18,8 điểm %**). Lý do là các video trên kênh đánh trực diện vào nhu cầu *"Nhận file biểu mẫu kế toán / Xem demo thực tế"*, khách chủ động để lại số Zalo để nhận file mà không cần thuyết phục dài dòng.
> - **Báo động đỏ tại kênh `Chị Kế Toán GenZ`:** Có tới **52,3%** khách rời đi trước khi đạt 3 tin nhắn (`AvgMsg = 2,8`), kéo tỷ lệ ra SĐT xuống chỉ còn **29,7%**. Nguyên nhân cốt lõi (khi đối chiếu với dữ liệu phân công) là **81,5% hội thoại của trang này chưa được gán nhân viên phụ trách**!

---

## ⏱️ III. PHÂN TÍCH TỐC ĐỘ THU THẬP SĐT & ĐỘ DÀI HỘI THOẠI

### 1. Thời gian chuyển đổi ra SĐT (`Time-to-Phone`)
Đo lường khoảng thời gian từ lúc khách nhắn tin đầu tiên (`first_created_at`) đến lúc thu được số điện thoại (`phone_at`) trên các kênh nguồn:

| Kênh Nguồn Marketing | Số Lead có mốc `phone_at` hợp lệ | Trung vị (`Median`) | Trung bình (`Mean`) | Tỷ lệ cho số ngay trong $\le 1$ giờ đầu | Tỷ lệ cho số trong vòng $\le 24$ giờ |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Anh Kế toán làm Data (TikTok)** | 1.789 | **11,55 giờ** | 91,74 giờ | **26,0%** | **66,7%** |
| **Anh Kế toán làm Data (Facebook)** | 1.137 | **14,67 giờ** | 97,74 giờ | 16,7% | 61,6% |
| **Hành trang cho kế toán** | 472 | **15,04 giờ** | 40,77 giờ | 22,9% | 61,0% |
| **Chị Kế Toán GenZ** | 89 | **17,34 giờ** | 29,99 giờ | 14,6% | 55,1% |

* **Nhận định:** Chỉ có khoảng **16,7% – 26,0%** khách hàng cho SĐT ngay trong giờ đầu tiên. Trung vị thời gian lấy số kéo dài từ **11,5 đến 17,3 giờ** (tương đương việc khách nhắn tin vào buổi tối hôm trước nhưng phải đợi đến trưa hôm sau nhân viên tư vấn vào ca mới xin được SĐT).

---

### 2. Ma trận Độ dài Hội thoại (`message_count`) vs. Tỷ lệ ra SĐT

| Nhóm Số lượng Tin nhắn (`message_count`) | Số lượng Lead Nguồn | Tỷ trọng (%) | Số Lead có SĐT | Tỷ lệ chuyển đổi CR (%) | Đánh giá Hành vi Khách hàng |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **0 tin** *(Chỉ tạo luồng/comment)* | 646 | 8,9% | 0 | **0,0%** | Lỗi đồng bộ hoặc khách bấm nhầm quảng cáo rồi thoát ngay |
| **1 tin** | 182 | 2,5% | 90 | **49,5%** | Nhóm khách thiện chí cao, nhắn thẳng SĐT ngay ở câu đầu tiên |
| **2 – 3 tin** *(Thung lũng chết)* | 1.200 | 16,6% | 336 | **28,0%** | Khách hỏi 1 câu $\rightarrow$ Bot/Admin chào lại $\rightarrow$ Khách im lặng rời đi |
| **4 – 6 tin** *(Ngưỡng bùng nổ)* | 1.969 | 27,3% | 1.115 | **56,6%** | Khách bắt đầu trả lời câu hỏi khai thác nhu cầu của Sale |
| **7 – 10 tin** | 1.686 | 23,3% | 1.073 | **63,6%** | Tương tác tư vấn sâu, niềm tin được xác lập |
| **11 – 20 tin** | 1.343 | 18,6% | 929 | **69,2%** | Trao đổi kỹ về lộ trình/tài liệu, gần như chắc chắn cho SĐT |
| **Trên 20 tin** | 197 | 2,7% | 141 | **71,6%** | Tư vấn chi tiết trực tiếp trên Fanpage/TikTok |

> [!TIP]
> **Kiểm chứng Giả thuyết H2 (Điểm chạm hội thoại thứ 4):**
> - Nhóm có `< 4 tin nhắn` (`2.028` leads): Tỷ lệ ra SĐT chỉ đạt **21,01%**.
> - Nhóm có `>= 4 tin nhắn` (`5.195` leads): Tỷ lệ ra SĐT đạt **62,71%** (**gấp 2,98 lần**).
> - **Bài học nghiệp vụ:** Tin nhắn thứ 2 và thứ 3 là ranh giới sống còn. Nếu câu phản hồi đầu tiên của Admin/Bot chỉ là câu chào chung chung hoặc bắt khách chờ đợi, 72% khách ở nhóm 2–3 tin sẽ bỏ đi mãi mãi.

---

## 🕒 IV. PHÂN TÍCH KHUNG GIỜ VÀNG & THẺ NHU CẦU (`STATUS_TAG`)

### 1. Phân tích theo Khung giờ trong ngày (`00h – 23h`) và Thứ trong tuần

| Khung Giờ Phát Sinh Lead | Số lượng Lead Nguồn | Tỷ trọng (%) | Số Lead có SĐT | Tỷ lệ CR (%) | Số tin nhắn TB | Đặc điểm Tệp khách |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **00h – 07h (Đêm & Sáng sớm)** | 544 | 7,5% | 291 | **53,5%** | 8,5 | "Cú đêm" cày TikTok/chạy deadline kế toán, độ quan tâm rất thật |
| **08h – 11h (Sáng hành chính)** | 1.955 | **27,1%** | 955 | **48,8%** | 5,9 | Đông khách nhất nhưng khách đang ở công ty, ngại chat dài |
| **12h – 13h (Nghỉ trưa)** | 638 | 8,8% | 310 | **48,6%** | 7,3 | Tranh thủ giờ nghỉ trưa lướt mạng tìm tài liệu |
| **14h – 17h (Chiều hành chính)** | 1.182 | 16,4% | 551 | **46,6%** | 6,6 | CR thấp nhất ngày do khách bận công việc cuối giờ chiều |
| **18h – 20h (Tối sớm)** | 1.412 | **19,5%** | 797 | **56,4%** | **8,3** | **Khung giờ Vàng số 1:** Khách đã về nhà, sẵn sàng trò chuyện sâu |
| **21h – 23h (Đêm muộn)** | 1.492 | **20,7%** | 780 | **52,3%** | 7,4 | **Khung giờ Vàng số 2:** Lượng Lead cao thứ nhì, nhu cầu học cao |

* **Theo Thứ trong tuần:** Lượng Lead tăng dần từ đầu tuần đến cuối tuần, đạt đỉnh vào **Thứ Sáu (`1.184` leads, CR = `53,6%`)** và đạt tỷ lệ chuyển đổi cao nhất vào **Chủ Nhật (`1.014` leads, CR = `54,0%`)**.
* **Kiểm chứng Giả thuyết H3:** Bác bỏ giả thuyết rằng khách nhắn buổi tối có chất lượng thấp! Thực tế khách nhắn từ `18h – 23h` có tỷ lệ cho SĐT cao nhất (**52,3% – 56,4%** vs **46,6% – 48,8%** giờ hành chính). Nếu tăng cường nhân sự trực ca tối (`18h30 – 22h30`), tỷ lệ này còn có thể vượt mốc 65%.

---

### 2. Phân tích theo Nhóm Thẻ Nhu cầu (`status_tag` trên Kênh Nguồn)
Khi tách cột `status_tag` trên 4 kênh nguồn, các nhóm thẻ nghiệp vụ chính cho thấy bức tranh chuyển đổi rất rõ ràng:
* **Nhóm Sự kiện / Hội thảo (`Data Talk` - 165 leads):** Đạt tỷ lệ ra SĐT cao nhất **86,7%** (vì khách đăng ký tham gia buổi chia sẻ bắt buộc để lại thông tin nhận link Zoom/tài liệu).
* **Nhóm Quan tâm Khóa học Kế toán (`HV TCKT` - 303 leads & `Đào tạo` - 809 leads):** Đạt tỷ lệ ra SĐT từ **67,2% – 75,9%**, độ dài tương tác trung bình **10,0 – 10,1 tin nhắn**.
* **Nhóm Nhu cầu Khác / Xin file lẻ (`Lead Other` - 1.436 leads):** Tỷ lệ có SĐT đạt **75,9%**, trung bình chỉ mất **4,3 tin nhắn** (nhận tài liệu tự động/nhanh).

---

## 🚀 V. KHUYẾN NGHỊ HÀNH ĐỘNG (ACTIONABLE RECOMMENDATIONS)

Dựa trên bằng chứng dữ liệu, nhóm phân tích đề xuất **3 giải pháp trọng tâm** để nâng tỷ lệ chuyển đổi SĐT toàn phễu từ **51,0% lên 60,0%+** (tương đương tăng thêm **~650 SĐT chất lượng** trên cùng mức chi phí):

1. **Tái cấu trúc Kịch bản Phản hồi ở Tin nhắn số 2 & số 3 (Xóa bỏ "Thung lũng chết" 28%):**
   * **Vấn đề:** Có 1.200 khách dừng lại ở 2–3 tin nhắn với CR chỉ 28,0%, nhưng nếu bước sang tin thứ 4 thì CR nhảy vọt lên 56,6%.
   * **Hành động:** Thay vì mở đầu bằng câu hỏi đóng hoặc câu chào khuôn mẫu (*"Chào bạn, bạn cần tư vấn khóa học nào?"*), đổi câu phản hồi số 2 thành **Câu hỏi lựa chọn kèm Mồi câu giá trị (Micro-hook)**: *"Chào bạn, mình gửi tặng bạn Bộ File mẫu Excel/Power Query kèm lộ trình nhé. Bạn đang làm Kế toán tổng hợp hay Kế toán nội bộ để mình gửi đúng bản chuẩn qua Zalo cho bạn?"*.
2. **Thiết lập Ca trực Trọng điểm Buổi tối (`18h30 – 22h30`) và Chủ Nhật:**
   * **Vấn đề:** 40,2% lượng Lead (2.904 khách) đổ về từ `18h – 23h` với độ thiện chí cao nhất trong ngày, nhưng `Median Time-to-Phone` hiện mất tới `11,5 – 15,0 giờ` (khách nhắn tối nay phải đợi sáng mai mới được Sale xin số).
   * **Hành động:** Bố trí tối thiểu 2–3 nhân sự có tỷ lệ chốt số cao trực xoay vòng khung giờ `18h30 – 22h30` với mục tiêu phản hồi và xin SĐT ngay trong **15 phút đầu tiên**, rút ngắn `Median Time-to-Phone` từ 12 giờ xuống dưới 1 giờ.
3. **Khắc phục ngay lỗ hổng bỏ rơi kênh `Chị Kế Toán GenZ` và nhân rộng mô hình Mồi câu của TikTok sang Facebook:**
   * **Hành động 1:** Gán nhân viên phụ trách tự động (Round-robin) cho 100% hội thoại vào kênh `Chị Kế Toán GenZ` và `Hành trang cho kế toán` để kéo CR từ 29,7% lên ngang mức chuẩn 50%–60%.
   * **Hành động 2:** Áp dụng chiến thuật gắn *Lead Magnet (Tặng File/Template + Webinar Data Talk)* của kênh TikTok sang các bài viết và tin nhắn tự động trên Fanpage Facebook (`Anh Kế toán làm Data (Facebook)`) nhằm nâng CR của Facebook từ 42,8% lên >55%.
