"""
================================================================================
CẤU HÌNH CÁC TRƯỜNG HỢP VÀ TIN NHẮN TỰ ĐỘNG (AUTO-REPLY RULES)
================================================================================
File này dùng để bạn TỰ DO THÊM, SỬA, HOẶC BẬT/TẮT các kịch bản trả lời tự động.

HƯỚNG DẪN:
1. Mỗi trường hợp là một Dictionary {} nằm trong danh sách AUTO_REPLY_RULES.
2. 'case_id': Tên mã duy nhất (viết liền không dấu, vd: 'xin_file', 'cong_dong').
   Bot dùng mã này để nhớ và đảm bảo KHÔNG BAO GIỜ gửi trùng 2 lần cho cùng 1 khách.
3. 'keywords': Danh sách các từ khóa. Chỉ cần tin nhắn của khách chứa 1 trong các từ này
   thì bot sẽ nhận diện (tự động không phân biệt chữ HOA/thường, có dấu hay không dấu).
4. 'message': Nội dung tin nhắn bạn muốn Bot gửi cho khách (qua tin nhắn Inbox).
   'comment_message': (Tùy chọn) Nội dung riêng khi trả lời bình luận (Comment). Nếu không điền sẽ dùng 'message'.
5. 'enabled': True để BẬT, False để TẠM TẮT trường hợp này.
6. 'priority': Mức ưu tiên (số nhỏ hơn sẽ được ưu tiên kiểm tra trước).
================================================================================
"""

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
            "file", "xin file", "cho em xin file", "cho mình xin file",
            "tài liệu", "tai lieu", "xin tài liệu", "xin tai lieu",
            "template", "mẫu báo cáo", "mau bao cao", "mẫu", "mau",
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
   
    # --------------------------------------------------------------------------
    # BẠN CÓ THỂ THÊM CÁC TRƯỜNG HỢP MỚI TẠI ĐÂY THEO MẪU:
    # {
    #     "case_id": "truong_hop_moi",
    #     "name": "Mô tả trường hợp",
    #     "enabled": True,
    #     "priority": 4,
    #     "keywords": ["từ khóa 1", "từ khóa 2"],
    #     "message": "Nội dung tin nhắn gửi...",
    # },
    # --------------------------------------------------------------------------
]


# ==============================================================================
# CẤU HÌNH KỊCH BẢN PHẢN HỒI BÌNH LUẬN RIÊNG (COMMENT_REPLY_RULES)
# ==============================================================================
# Danh sách này dành riêng cho việc tự động Reply Comment trên Facebook & TikTok.
# Nếu danh sách này có dữ liệu, bot sẽ ưu tiên dùng danh sách này khi reply comment.
# Bạn có thể tự do thêm bớt từ khóa hoặc chỉnh sửa nội dung phản hồi bên dưới.
# ==============================================================================
COMMENT_REPLY_RULES = [
    # --------------------------------------------------------------------------
    # COMMENT RULE 1: KHÁCH COMMENT XIN FILE / TÀI LIỆU / CÂU LỆNH
    # --------------------------------------------------------------------------
    {
        "case_id": "cmt_xin_file",
        "name": "Khách comment xin file / tài liệu / câu lệnh",
        "enabled": True,
        "priority": 1,
        "keywords": [
            "file", "xin file", "cho em xin file", "cho mình xin file",
            "tài liệu", "tai lieu", "xin tài liệu", "xin tai lieu",
            "template", "mẫu báo cáo", "mau bao cao", "mẫu", "mau",
            "cho em xin với", "cho mình xin với", "gửi em với", "gửi mình với",
            "cho em xin", "cho mình xin", "gửi file", "gui file", "sheet",
            "câu lệnh", "cau lenh", "xin câu lệnh", "prompt", "xin prompt",
            "công thức", "cong thuc"
        ],
        # 1. Tin nhắn riêng gửi trực tiếp vào Inbox/DM của khách:
        "private_message": (
            "Chào bạn, mình thấy bạn quan tâm đến bộ file và tài liệu Excel, Power Query & AI. Bạn nhắn mình SĐT để bạn quản lý lớp bên mình add ZL và gửi bạn tài liệu chi tiết nhé!"
        ),
        # 2. Nội dung rep comment khi đã gửi DM thành công (khách mở DM):
        "comment_success_message": (
            "Dạ mình đã gửi thông tin qua tin nhắn riêng cho bạn rồi nhé, bạn kiểm tra mục Tin nhắn / Tin nhắn chờ giúp mình nha!"
        ),
        # 3. Nội dung rep comment khi gửi DM thất bại (khách khóa DM / chặn người lạ):
        "comment_fallback_message": (
            "Do tài khoản của bạn đang chặn nhận tin nhắn từ người lạ, bạn bấm nút 'Nhắn tin' cho kênh hoặc để lại SĐT để bên mình gửi tài liệu cho bạn nhé!"
        ),
        "message": (
            "Chào bạn, bạn nhắn tin cho page hoặc để lại SĐT/Zalo bên mình gửi bạn file và tài liệu thực hành nhé!"
        ),
    },

    # --------------------------------------------------------------------------
    # COMMENT RULE 2: KHÁCH COMMENT HỎI KHÓA HỌC / LỚP HỌC / HỌC PHÍ
    # --------------------------------------------------------------------------
    {
        "case_id": "cmt_khoa_hoc",
        "name": "Khách comment hỏi khóa học / lộ trình / học phí",
        "enabled": True,
        "priority": 2,
        "keywords": [
            "khóa học", "khoa hoc", "học phí", "hoc phi", "lộ trình", "lo trinh",
            "lớp học", "lop hoc", "tư vấn", "tu van", "học ở đâu", "hoc o dau",
            "có lớp", "co lop", "chi phí", "chi phi", "đào tạo", "dao tao",
            "học online", "hoc online"
        ],
        # 1. Tin nhắn riêng gửi trực tiếp vào Inbox/DM của khách:
        "private_message": (
            "Chào bạn, mình gửi bạn thông tin chi tiết về lộ trình học ứng dụng Excel, Power Query & AI trong công việc. Bạn nhắn mình SĐT để bạn quản lý lớp tư vấn lịch học và ưu đãi cho bạn nhé!"
        ),
        # 2. Nội dung rep comment khi đã gửi DM thành công (khách mở DM):
        "comment_success_message": (
            "Dạ mình đã gửi lộ trình và ưu đãi qua tin nhắn riêng cho bạn rồi nhé, bạn kiểm tra mục Tin nhắn / Tin nhắn chờ giúp mình nha!"
        ),
        # 3. Nội dung rep comment khi gửi DM thất bại (khách khóa DM / chặn người lạ):
        "comment_fallback_message": (
            "Do tài khoản của bạn đang chặn nhận tin nhắn từ người lạ, bạn bấm nút 'Nhắn tin' cho kênh hoặc để lại SĐT để bên mình tư vấn chi tiết cho bạn nhé!"
        ),
        "message": (
            "Chào bạn, bạn nhắn tin cho page hoặc để lại SĐT bên mình gửi thông tin lộ trình và ưu đãi lớp học cho bạn nhé!"
        ),
    },

    # --------------------------------------------------------------------------
    # COMMENT RULE 3: KHÁCH COMMENT THAM GIA NHÓM / CỘNG ĐỒNG
    # --------------------------------------------------------------------------
    {
        "case_id": "cmt_cong_dong",
        "name": "Khách comment muốn tham gia nhóm / cộng đồng",
        "enabled": True,
        "priority": 3,
        "keywords": [
            "cộng đồng", "cong dong", "nhóm", "nhom", "group", "giao lưu",
            "tham gia nhóm", "tham gia group", "vào nhóm", "vao nhom",
            "link nhóm", "link group", "link zalo", "nhóm zalo", "nhom zalo"
        ],
        # 1. Tin nhắn riêng gửi trực tiếp vào Inbox/DM của khách:
        "private_message": (
            "Chào bạn, mình gửi bạn thông tin tham gia cộng đồng Excel, Power Query & AI. Bạn nhắn mình SĐT để bạn quản lý lớp add bạn vào nhóm Zalo cùng học tập và giao lưu nhé!"
        ),
        # 2. Nội dung rep comment khi đã gửi DM thành công (khách mở DM):
        "comment_success_message": (
            "Dạ mình đã nhắn tin riêng cho bạn rồi nhé, bạn kiểm tra mục Tin nhắn / Tin nhắn chờ giúp mình nha!"
        ),
        # 3. Nội dung rep comment khi gửi DM thất bại (khách khóa DM / chặn người lạ):
        "comment_fallback_message": (
            "Do tài khoản của bạn đang chặn nhận tin nhắn từ người lạ, bạn bấm nút 'Nhắn tin' cho kênh hoặc để lại SĐT để bên mình add vào nhóm cộng đồng nhé!"
        ),
        "message": (
            "Chào bạn, bạn nhắn SĐT để bên mình add bạn vào nhóm Zalo cộng đồng cùng học tập và trao đổi nhé!"
        ),
    },
]


# ==============================================================================
# CÁC KÊNH LEAD NGUỒN ĐƯỢC PHÉP CHẠY BOT (CHỈ FACEBOOK & TIKTOK, BỎ QUA ZALO)
# ==============================================================================
ALLOWED_SOURCE_PAGES = [
    # 1. Facebook:
    #"514400205095512",          # Anh Kế toán làm Data (Facebook)
    # 2. TikTok:
    "tt_7196601676597871618",   # Anh Kế toán làm Data (TikTok @tuananhdata)
    "tt_7456003523327919120",   # Hành trang cho kế toán (TikTok @anhgadata)
    #"tt_7661860189083943944",   # Chị Kế Toán GenZ (TikTok @chiketoangenz)
]
