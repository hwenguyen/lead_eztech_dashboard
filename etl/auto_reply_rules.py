"""
================================================================================
CẤU HÌNH CÁC TRƯỜNG HỢP VÀ TIN NHẮN TỰ ĐỘNG (AUTO-REPLY RULES)
================================================================================
File này dùng để bạn TỰ DO THÊM, SỬA, HOẶC BẬT/TẮT các kịch bản trả lời tự động.

HƯỚNG DẪN:
1. AUTO_REPLY_RULES: Kịch bản dùng cho tin nhắn riêng trong INBOX.
2. COMMENT_REPLY_RULES: Kịch bản dành riêng cho BÌNH LUẬN (COMMENT) theo cơ chế Smart Combo:
   - "private_message": Tin nhắn riêng gửi trực tiếp vào Inbox/DM của khách.
   - "comment_success_message": Nội dung rep comment khi đã gửi DM thành công.
   - "comment_fallback_message": Nội dung rep comment khi khách khóa DM (để riêng tư).
3. 'case_id': Tên mã duy nhất (viết liền không dấu, vd: 'cmt_xin_file').
   Bot dùng mã này để ghi nhớ và KHÔNG BAO GIỜ rep trùng 2 lần cho cùng 1 comment.
4. 'keywords': Danh sách các từ khóa (tự động không phân biệt HOA/thường, có dấu/không dấu).
================================================================================
"""

# ==============================================================================
# 1. CẤU HÌNH KỊCH BẢN CHO TIN NHẮN INBOX (AUTO_REPLY_RULES)
# ==============================================================================
AUTO_REPLY_RULES = [
    # --------------------------------------------------------------------------
    # TRƯỜNG HỢP 1: KHÁCH XIN FILE / TÀI LIỆU
    # --------------------------------------------------------------------------
    {
        "case_id": "xin_file",
        "name": "Khách xin file / tài liệu / mẫu báo cáo",
        "enabled": True,
        "priority": 2,
        "keywords": [
            "file", "xin file", "cho em xin file", "cho mình xin file", "cho e xin file", "cho m xin file",
            "tài liệu", "tai lieu", "xin tài liệu", "xin tai lieu",
            "template", "mẫu báo cáo", "mau bao cao", "mẫu", "mau",
            "prompt", "xin prompt", "promt", "xin promt", "câu lệnh", "cau lenh", "xin câu lệnh",
            "hướng dẫn", "huong dan", "xin hướng dẫn", "file hướng dẫn",
            "cho em xin với", "cho mình xin với", "gửi em với", "gửi mình với",
            "cho em xin", "cho mình xin", "gửi file", "gui file", "sheet"
        ],
        "message": (
            "Chào bạn, mình thấy bạn quan tâm đến các bộ file và tài liệu chia sẻ về ứng dụng Excel, Power Query & AI trong công việc. Bạn nhắn mình SĐT để bạn quản lý lớp bên mình add ZL và gửi bạn thông tin chi tiết nhé"
        ),
    },

    # --------------------------------------------------------------------------
    # TRƯỜNG HỢP 2: KHÁCH XIN THAM GIA CỘNG ĐỒNG / NHÓM TRAO ĐỔI
    # --------------------------------------------------------------------------
    {
        "case_id": "tham_gia_cong_dong",
        "name": "Khách muốn vào nhóm / tham gia cộng đồng",
        "enabled": True,
        "priority": 1,
        "keywords": [
            "cộng đồng", "cong dong", "nhóm", "nhom", "group", "giao lưu",
            "tham gia nhóm", "tham gia group", "vào nhóm", "vao nhom",
            "link nhóm", "link group", "link zalo", "nhóm zalo", "nhom zalo"
        ],
        "message": (
            "Chào em, anh thấy em quan tâm đến các buổi workshop và tài liệu chia sẻ về ứng dụng Excel, Power Query & AI trong công việc. Em nhắn SĐT để bạn quản lý lớp add em vào nhóm cộng đồng nhé!"
        ),
    },
]


# ==============================================================================
# 2. CẤU HÌNH KỊCH BẢN PHẢN HỒI BÌNH LUẬN (COMMENT_REPLY_RULES) - SMART COMBO
# ==============================================================================
# Luồng hoạt động của Bot khi khách comment:
# Bước 1: Bot gửi tin nhắn riêng (private_message) vào Inbox khách.
# Bước 2:
#   - Nếu gửi DM thành công -> Bot rep comment bằng [comment_success_message]
#   - Nếu khách khóa DM    -> Bot rep comment bằng [comment_fallback_message]
# ==============================================================================
COMMENT_REPLY_RULES = [
    # --------------------------------------------------------------------------
    # COMMENT RULE 1: KHÁCH COMMENT XIN FILE / TÀI LIỆU / CÂU LỆNH / HƯỚNG DẪN / IB
    # --------------------------------------------------------------------------
    {
        "case_id": "cmt_xin_file",
        "name": "Khách comment xin file / tài liệu / câu lệnh / hướng dẫn",
        "enabled": True,
        "priority": 3,
        "keywords": [
            "file", "xin file", "cho em xin file", "cho mình xin file", "cho e xin file", "cho m xin file",
            "tài liệu", "tai lieu", "xin tài liệu", "xin tai lieu",
            "template", "mẫu báo cáo", "mau bao cao", "mẫu", "mau",
            "prompt", "xin prompt", "promt", "xin promt", "promtp", "câu lệnh", "cau lenh", "xin câu lệnh",
            "hướng dẫn", "huong dan", "xin hướng dẫn", "xin huong dan", "file hướng dẫn",
            "thông tin file", "thong tin file", "thông tin tài liệu", "thong tin tai lieu",
            "ib", "inbox", "inb", "ib mình", "ib e", "ib nha", "inbox mình", "inbox e", "check ib",
            "công thức", "cong thuc", "sheet", "from", "xin from",
            "cho em xin", "cho e xin", "cho mình xin", "cho m xin", "cho mk xin", "e xin", "m xin", "mk xin",
            "cho em xin với", "cho e xin với", "cho em xin vs", "cho e xin vs",
            "cho mình xin với", "cho m xin với", "cho mình xin vs", "cho m xin vs",
            "gửi em với", "gui em voi", "gửi e với", "gui e voi", "gửi e vs", "gui e vs",
            "gửi mình với", "gui minh voi", "gửi m với", "gui m voi", "gửi mình vs", "gửi m vs",
            "gửi file", "gui file", "xin với", "xin voi", "xin vs"
        ],
        # 1. Tin nhắn riêng gửi trực tiếp vào Inbox/DM của khách:
        "private_message": (
            "Chào bạn, mình thấy bạn quan tâm đến bộ file và tài liệu Excel, Power Query & AI. Bạn nhắn mình SĐT để bạn quản lý lớp bên mình add ZL và gửi bạn tài liệu chi tiết nhé!"
        ),
        # 2. Nội dung rep comment khi đã gửi DM thành công (hoặc kênh TikTok):
        "comment_success_message": [
            "Chào bạn, bạn nhắn tin cho page để mình gửi tài liệu cho bạn nha!",
            "Dạ bạn nhắn tin cho bên mình để nhận trọn bộ tài liệu nhé!",
            "Chào bạn, bạn gửi tin nhắn cho page bên mình gửi file và hướng dẫn chi tiết nha!",
            "Dạ bạn nhắn tin qua page để bên mình gửi bạn file thực hành nhé!",
        ],
        # 3. Nội dung rep comment khi gửi DM thất bại (khách khóa DM / chặn người lạ):
        "comment_fallback_message": [
            "Chào bạn, bạn chủ động nhắn tin cho page để mình gửi tài liệu cho bạn nha!",
            "Dạ bạn nhắn tin cho bên mình để nhận file và tài liệu thực hành nhé!",
            "Chào bạn, bạn gửi tin nhắn cho page để bên mình gửi bạn tài liệu chi tiết nha!",
        ],
    },

    # --------------------------------------------------------------------------
    # COMMENT RULE 2: KHÁCH COMMENT HỎI KHÓA HỌC / LỚP HỌC / HỌC PHÍ / ĐĂNG KÝ
    # --------------------------------------------------------------------------
    {
        "case_id": "cmt_khoa_hoc",
        "name": "Khách comment hỏi khóa học / lộ trình / học phí / đăng ký",
        "enabled": True,
        "priority": 1,
        "keywords": [
            "khóa học", "khoa hoc", "học phí", "hoc phi", "lộ trình", "lo trinh",
            "lớp học", "lop hoc", "tư vấn", "tu van", "học ở đâu", "hoc o dau",
            "có lớp", "co lop", "chi phí", "chi phi", "đào tạo", "dao tao",
            "học online", "hoc online", "đăng ký", "dang ky", "đăng ký học", "dang ky hoc",
            "học như thế nào", "hoc nhu the nao", "đk học", "dk hoc"
        ],
        # 1. Tin nhắn riêng gửi trực tiếp vào Inbox/DM của khách:
        "private_message": (
            "Chào bạn, mình thấy bạn đang quan tâm đến ứng dụng Excel, Power Query & AI trong CV. Bạn đang làm trong lĩnh vực nào nhỉ để mình gửi lộ trình học phù hợp cho bạn nhé"
        ),
        # 2. Nội dung rep comment khi đã gửi DM thành công (hoặc kênh TikTok):
        "comment_success_message": [
            "Chào bạn, bạn nhắn tin cho page để bên mình tư vấn lộ trình học phù hợp nhé!",
            "Dạ bạn nhắn tin cho page để mình gửi bạn thông tin chi tiết về khóa học nha!",
            "Chào bạn, bạn gửi tin nhắn cho page để bên mình gửi thông tin và ưu đãi khóa học nhé!",
        ],
        # 3. Nội dung rep comment khi gửi DM thất bại (khách khóa DM / chặn người lạ):
        "comment_fallback_message": [
            "Chào bạn, bạn chủ động nhắn tin cho page để bên mình gửi thông tin chi tiết về khóa học nhé!",
            "Dạ bạn nhắn tin cho page để bên mình gửi bạn lộ trình học chi tiết nha!",
        ],
    },

    # --------------------------------------------------------------------------
    # COMMENT RULE 3: KHÁCH COMMENT THAM GIA NHÓM / CỘNG ĐỒNG
    # --------------------------------------------------------------------------
    {
        "case_id": "cmt_cong_dong",
        "name": "Khách comment muốn tham gia nhóm / cộng đồng",
        "enabled": True,
        "priority": 2,
        "keywords": [
            "cộng đồng", "cong dong", "nhóm", "nhom", "group", "giao lưu",
            "tham gia nhóm", "tham gia group", "vào nhóm", "vao nhom",
            "link nhóm", "link group", "link zalo", "nhóm zalo", "nhom zalo",
            "tham gia", "xin tham gia", "tham gia với", "tham gia vs",
            "cho em tham gia", "cho e tham gia", "cho mình tham gia", "cho m tham gia", "cho mk tham gia",
            "vào với", "vao voi", "vào vs"
        ],
        # 1. Tin nhắn riêng gửi trực tiếp vào Inbox/DM của khách:
        "private_message": (
            "Chào bạn, mình thấy bạn quan tâm đến các buổi workshop và tài liệu chia sẻ về ứng dụng Excel, Power Query & AI trong công việc. Bạn nhắn SĐT để bạn quản lý lớp add bạn vào nhóm cộng đồng nhé."
        ),
        # 2. Nội dung rep comment khi đã gửi DM thành công (hoặc kênh TikTok):
        "comment_success_message": [
            "Chào bạn, bạn nhắn tin cho page để bên mình gửi bạn thông tin tham gia nhóm nhé!",
            "Dạ bạn gửi tin nhắn cho page để bên mình hỗ trợ bạn vào nhóm cộng đồng nha!",
            "Chào bạn, bạn nhắn tin cho page để nhận link tham gia nhóm giao lưu nhé!",
        ],
        # 3. Nội dung rep comment khi gửi DM thất bại (khách khóa DM / chặn người lạ):
        "comment_fallback_message": [
            "Chào bạn, bạn chủ động nhắn tin cho page để bên mình gửi thông tin tham gia nhóm nha!",
            "Dạ bạn nhắn tin cho page để bên mình hỗ trợ bạn vào nhóm cộng đồng nhé!",
        ],
    },
]


# ==============================================================================
# 3. QUY TẮC CHỐNG SPAM KHÁCH CŨ (BỎ QUA NẾU ĐÃ CÓ TIN NHẮN TỪ TRƯỚC)
# ==============================================================================
# True: Nếu khách hàng comment mà ĐÃ CÓ TIN NHẮN TỪ TRƯỚC (đã từng có hội thoại trong
#       Inbox hoặc đã từng được bot gửi tin nhắn thành công), Bot sẽ BỎ QUA HOÀN TOÀN
#       (không gửi tin nhắn riêng và không trả lời comment) để tránh làm phiền khách.
# False: Vẫn rep comment / gửi tin nhắn bình thường.
SKIP_IF_CUSTOMER_HAS_PRIOR_MESSAGES = True


# ==============================================================================
# 4. CẤU HÌNH GỬI TIN NHẮN RIÊNG (PRIVATE INBOX / DM) TỪ COMMENT
# ==============================================================================
# False: Tạm thời ẩn/tắt gửi tin nhắn riêng vào Inbox khi khách comment.
#        Chỉ trả lời bình luận công khai (mời khách inbox) cho các trường hợp chưa có ai inbox.
# True:  Thử gửi tin nhắn riêng vào Inbox trước (chỉ áp dụng Facebook).
ENABLE_PRIVATE_REPLY = False


# ==============================================================================
# 4. CÁC KÊNH LEAD NGUỒN ĐƯỢC PHÉP CHẠY BOT (CHỈ FACEBOOK & TIKTOK, BỎ QUA ZALO)
# ==============================================================================
ALLOWED_SOURCE_PAGES = [
    # 1. Facebook:
    "514400205095512",          # Anh Kế toán làm Data (Facebook)
    # 2. TikTok:
    "tt_7196601676597871618",   # Anh Kế toán làm Data (TikTok @tuananhdata)
    "tt_7456003523327919120",   # Hành trang cho kế toán (TikTok @anhgadata)
    "tt_7661860189083943944",   # Chị Kế Toán GenZ (TikTok @chiketoangenz)
]
