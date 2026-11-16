# Quy Trình Xuất Hóa Đơn & Đối Soát Thu Tiền / Hoàn Cọc (RAG AI Kế Toán EzTech)

> Tài liệu chuẩn hóa quy trình nội bộ từ **Quy trình xuất hóa đơn - EzTech.pptx**, áp dụng cho Bộ phận Kế toán, Nhân sự Check lệnh và Sale khi chốt giao dịch, theo dõi deal và phát hành hóa đơn điện tử tại **Công ty TNHH Công nghệ EzTech Việt Nam**.

---

## 1. Thông Tin Pháp Nhân & Tài Khoản Nhận Tiền Chính Thức

- **Thông tin pháp nhân xuất hóa đơn:**
  - **Tên đơn vị:** Công ty TNHH Công nghệ EzTech Việt Nam
  - **Mã số thuế (MST):** `0110633252`
  - **Địa chỉ:** 79 Ngọc Hồi, Phường Hoàng Liệt, Hà Nội
  - **Điện thoại / Email:** `(+84) 0898276368` | `contact@eztech-official.com`
- **Hai kênh tài khoản nhận thanh toán:**
  1. **Tài khoản công ty (Bắt buộc xuất hóa đơn):**
     - **Chủ tài khoản:** Công ty TNHH công nghệ EzTech Viet Nam
     - **Số tài khoản:** `9999336666`
     - **Ngân hàng:** VP Bank – Chi nhánh Trần Hưng Đạo
     - **Nguyên tắc bắt buộc:** *Mọi khoản tiền đi qua tài khoản công ty bắt buộc phải xuất hóa đơn.*
  2. **Tài khoản cá nhân (Momo):** Dùng cho trường hợp nhận cọc trước khi khách xuất hóa đơn công ty (sẽ hoàn cọc sau), hoặc khách không cần xuất hóa đơn và đóng làm 2 lần.

---

## 2. Bảng Phân Loại 4 Trường Hợp Chốt Khách, Tài Khoản & Mẫu Hóa Đơn (`TEZ` / `TEE`)

Khi phát sinh giao dịch, Kế toán và Sale đối chiếu đúng bảng phân loại dưới đây để gửi đúng số tài khoản và chọn đúng mẫu hóa đơn khi phát hành:

| Trường hợp khách hàng | Tài khoản gửi khách | Mẫu hóa đơn áp dụng | Ghi chú nghiệp vụ |
|---|---|---|---|
| **1. Xuất hóa đơn cho Công ty** | **STK công ty** (`9999336666` VP Bank) | **TEZ** | Nếu khách cọc trước 1–2 triệu bằng TK cá nhân thì nhận qua **Momo**, sau đó làm quy trình hoàn cọc khi tiền công ty về TK EzTech. |
| **2. Xuất hóa đơn cho Cá nhân** | **STK công ty** (`9999336666` VP Bank) | **TEE** | Bắt buộc xin Họ tên, Số CCCD (hoặc MST cá nhân) và Địa chỉ theo đơn vị hành chính **sau sáp nhập**. |
| **3. Không cần lấy hóa đơn (đóng 1 lần / qua TK cty)** | **STK công ty** (`9999336666` VP Bank) | **TEE** *(lưu bán cho người tiêu dùng)* | Vẫn bắt buộc nhập lên Web theo dõi hóa đơn và báo người phụ trách xuất hóa đơn. |
| **4. Không cần hóa đơn, chia 2 lần đóng** | **Momo** (Tài khoản cá nhân) | **Chưa áp dụng** | Thu qua tài khoản cá nhân Momo theo chính sách chia 2 đợt. |

---

## 3. Quy Trình Nhập Liệu Trên "Web Theo Dõi Deal & Xuất Hóa Đơn"

Mọi giao dịch chuyển qua **STK công ty** (bao gồm cả khách xuất công ty, xuất cá nhân và khách lẻ không lấy hóa đơn) đều phải được nhập đầy đủ lên **Web Theo dõi deal & xuất hóa đơn** (tab `Xuất hoá đơn` trên Dashboard):

### Các trường thông tin bắt buộc khi "Thêm deal mới"
- **Ngày chuyển tiền:** Ngày thực tế tiền về sao kê (`dd/mm/yyyy`).
- **Hình thức thu tiền:** Chọn `Tk công ty` hoặc `Momo`.
- **Họ và tên khách & Số điện thoại:** Dùng đối chiếu học viên trên hệ thống.
- **Nhân viên chăm sóc:** Chọn đúng Sale phụ trách deal.
- **Loại hóa đơn:** Chọn đúng 1 trong 3 loại tương ứng với mẫu TEZ/TEE:
  - `Xuất hóa đơn về công ty` (Mẫu **TEZ**)
  - `Xuất hóa đơn cho cá nhân` (Mẫu **TEE**)
  - `Khách lẻ không lấy hóa đơn` (Mẫu **TEE** — bán cho người tiêu dùng)
- **Số tiền cần xuất (VNĐ)** và **Số tiền đã chuyển (VNĐ)**.
- **Thông tin xuất hóa đơn (có thể điền sau):**
  - *Công ty:* Tên công ty + Mã số thuế + Địa chỉ trụ sở (và Email nhận hóa đơn).
  - *Cá nhân:* Họ tên + Số CCCD/MST + Địa chỉ sau sáp nhập.
  - *Khách lẻ không lấy hóa đơn:* Ghi chú nội dung sao kê giao dịch chuyển khoản để Kế toán đối soát.
- **Note sao kê chuyển khoản / lưu ý đặc biệt:** Ghi rõ nếu có hoàn cọc (ví dụ: `"Hoàn lại cọc 1tr"`) hoặc lưu ý xuất hóa đơn riêng.

---

## 4. Chi Tiết Quy Trình Từng Trường Hợp (Cho Kế Toán & Sale)

### Trường hợp A: Khách xuất hóa đơn cho Công ty (Thanh toán thẳng từ TK công ty)
1. Gửi **STK công ty** (`9999336666` – VP Bank Trần Hưng Đạo).
2. Xin đủ 4 thông tin xuất hóa đơn công ty: **Tên công ty, Mã số thuế, Địa chỉ, Email nhận hóa đơn**.
3. Input thông tin giao dịch lên **Web theo dõi hóa đơn** (chọn loại `Xuất hóa đơn về công ty`, mẫu **TEZ**).
4. **Báo người phụ trách xuất hóa đơn (Bắt buộc)** để kiểm tra sao kê, gửi hóa đơn nháp (nếu cần) và phát hành hóa đơn điện tử mẫu **TEZ**.

### Trường hợp B: Khách xuất hóa đơn cho Công ty nhưng cọc trước 1–2 triệu bằng tài khoản cá nhân
Áp dụng khi khách muốn giữ suất/ưu đãi sớm bằng tiền cá nhân (1–2 triệu), sau đó công ty của khách mới đi lệnh chuyển đủ tiền khóa học từ tài khoản công ty:
- **Bước 1 — Nhận cọc qua Momo & Báo khách:**
  - Gửi khách tài khoản **Momo** cá nhân để nhận khoản cọc 1–2 triệu (hoặc theo dõi nếu khách lỡ chuyển khoản cọc trước).
  - Thông báo rõ với khách: *Sau khi công ty của khách chuyển tiền đi lệnh vào STK công ty EzTech (`9999336666`), EzTech sẽ thực hiện hoàn lại đúng số tiền đã cọc cá nhân.*
  - Đề nghị khách chuyển khoản toàn bộ phần tiền xuất hóa đơn từ tài khoản công ty vào STK công ty EzTech.
- **Bước 2 — Lập Đề nghị thanh toán hoàn cọc (sau khi tiền về STK công ty):**
  - Chỉ thực hiện **sau khi tiền đã vào tài khoản công ty** và xác nhận khớp sao kê.
  - Lập **Đề nghị thanh toán (`ĐNTT`)** theo biểu mẫu chuẩn **`BM.01-QT.KTNS.01`** (kính gửi Ban giám đốc & Phòng Kế toán, Bộ phận `Finance and Accounting`, Số `dd/mm/yyyy/ĐNTT`):
    - Ghi rõ nội dung đề nghị: *Hoàn cọc học phí cho anh/chị [Tên học viên]*.
    - Diễn giải chi tiết số tiền hoàn (`1.000.000` hoặc `2.000.000 VNĐ`), ghi chú lý do (học viên cọc trước bằng TK cá nhân, đã chuyển đủ từ TK công ty để xuất hóa đơn về công ty).
    - Điền đủ thông tin chuyển khoản hoàn cọc: **Tên người thụ hưởng, Số tài khoản, Ngân hàng, Đề nghị thanh toán trước ngày...**
  - *Lưu ý mẫu file:* File mẫu hoàn cọc Excel (`ĐNTT [Tên học viên].xlsx`) đã có sẵn trên kênh Check lệnh (nếu chưa thấy thì hỏi lại **chị Linh**).
- **Bước 3 — Gửi Check lệnh, Hoàn cọc & Xuất hóa đơn (Bắt buộc):**
  - Nhập deal lên Web theo dõi hóa đơn, ghi chú tại mục *Note sao kê*: `"Hoàn lại cọc 1tr"` (hoặc số tiền cọc tương ứng).
  - Gửi file **Đề nghị thanh toán (`ĐNTT`)** lên kênh **Check lệnh** kèm thông tin học viên, nguồn, số tiền đã về TK công ty và thông tin/mã QR tài khoản nhận hoàn cọc của khách.
  - Kế toán thực hiện **hoàn cọc** cho khách, đồng thời **bắt buộc xuất hóa đơn mẫu TEZ** cho toàn bộ khoản tiền đã nhận qua tài khoản công ty.

### Trường hợp C: Khách xuất hóa đơn cho Cá nhân
1. Gửi **STK công ty** (`9999336666` – VP Bank Trần Hưng Đạo).
2. Xin đầy đủ thông tin cá nhân của khách: **Họ tên, Số CCCD, Địa chỉ sau sáp nhập** (và Email nhận hóa đơn nếu có).
3. Input thông tin lên **Web theo dõi hóa đơn** (chọn loại `Xuất hóa đơn cho cá nhân`).
4. **Báo người phụ trách xuất hóa đơn (Bắt buộc)** để phát hành hóa đơn mẫu **TEE**.

### Trường hợp D: Khách KHÔNG cần xuất hóa đơn
1. **Nếu khách đóng 1 lần / chuyển qua STK công ty:**
   - Gửi **STK công ty** (`9999336666` – VP Bank Trần Hưng Đạo).
   - Input giao dịch lên **Web theo dõi hóa đơn** (chọn loại `Khách lẻ không lấy hóa đơn`).
   - **Báo người phụ trách xuất hóa đơn (Bắt buộc)** để xuất và lưu hóa đơn mẫu **TEE** dưới dạng **bán cho người tiêu dùng**.
2. **Nếu khách chia làm 2 lần đóng và không cần hóa đơn:**
   - Gửi tài khoản **Momo** cá nhân để nhận thanh toán (chưa áp dụng mẫu hóa đơn TEZ/TEE trên hệ thống).

---

## 5. Checklist Kiểm Tra Nhanh Dành Cho Kế Toán Khi Đối Soát Xuất Hóa Đơn

1. **Kiểm tra dòng tiền:** Tiền đã vào **STK công ty `9999336666`** thì **100% bắt buộc phải có hóa đơn đầu ra** (`TEZ` hoặc `TEE`).
2. **Kiểm tra đúng mẫu hóa đơn:**
   - Có MST doanh nghiệp / xuất về công ty → Mẫu **`TEZ`**.
   - Xuất cho cá nhân (có Tên + CCCD + Địa chỉ sau sáp nhập) → Mẫu **`TEE`**.
   - Khách lẻ không lấy hóa đơn (qua TK công ty) → Mẫu **`TEE`** (lưu bán cho người tiêu dùng).
3. **Kiểm tra trường hợp hoàn cọc:** Chỉ duyệt hoàn cọc theo mẫu **`BM.01-QT.KTNS.01`** trên Check lệnh **sau khi** khoản tiền thanh toán từ công ty của khách đã ghi có thực tế trên sao kê VP Bank `9999336666`.
4. **Đối chiếu 2 hệ thống:** Đối chiếu số tiền & thông tin khách giữa **Web theo dõi deal & xuất hóa đơn** với bảng **Nhập Deal & Công nợ (`sales_deals`)** trên EzTech Dashboard.
