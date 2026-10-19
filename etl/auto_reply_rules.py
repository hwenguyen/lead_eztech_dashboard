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
4. 'message': Nội dung tin nhắn bạn muốn Bot gửi cho khách.
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
        "priority": 1,
        "keywords": [
            "file", "xin file", "cho em xin file", "cho mình xin file",
            "tài liệu", "tai lieu", "xin tài liệu", "xin tai lieu",
            "template", "mẫu báo cáo", "mau bao cao", "mẫu", "mau",
            "cho em xin với", "cho mình xin với", "gửi em với", "gửi mình với",
            "cho em xin", "cho mình xin", "gửi file", "gui file", "sheet"
        ],
        "message": (
            "Dạ chào bạn, để nhận trọn bộ File tài liệu và hướng dẫn chi tiết, "
            "bạn để lại Số điện thoại (Zalo) để bên mình gửi qua Zalo cho bạn ngay nhé ạ! 😊"
        ),
    },

    # --------------------------------------------------------------------------
    # TRƯỜNG HỢP 2: KHÁCH XIN THAM GIA CỘNG ĐỒNG / NHÓM TRAO ĐỔI
    # --------------------------------------------------------------------------
    {
        "case_id": "tham_gia_cong_dong",
        "name": "Khách muốn vào nhóm / tham gia cộng đồng",
        "enabled": True,
        "priority": 2,
        "keywords": [
            "cộng đồng", "cong dong", "nhóm", "nhom", "group", "giao lưu",
            "tham gia nhóm", "tham gia group", "vào nhóm", "vao nhom",
            "link nhóm", "link group", "link zalo", "nhóm zalo", "nhom zalo"
        ],
        "message": (
            "Dạ chào bạn, bạn bấm vào link này để tham gia nhóm Zalo chia sẻ kiến thức "
            "và nhận tài liệu mới nhất cùng cộng đồng EzTech nhé: https://zalo.me/g/xxxxxx. "
            "Chúc bạn học tập hiệu quả! 🚀"
        ),
    },

    # --------------------------------------------------------------------------
    # TRƯỜNG HỢP 3: KHÁCH HỎI TƯ VẤN KHÓA HỌC / HỌC PHÍ / LỘ TRÌNH
    # --------------------------------------------------------------------------
    {
        "case_id": "tu_van_khoa_hoc",
        "name": "Khách hỏi tư vấn khóa học / học phí",
        "enabled": True,
        "priority": 3,
        "keywords": [
            "khóa học", "khoa hoc", "học phí", "hoc phi", "tư vấn", "tu van",
            "lộ trình", "lo trinh", "lớp học", "lop hoc", "đào tạo", "dao tao",
            "khóa power bi", "khoa power bi", "học data", "hoc data"
        ],
        "message": (
            "Dạ chào bạn, bạn để lại Số điện thoại Zalo để chuyên viên EzTech tư vấn "
            "lộ trình học phù hợp nhất và gửi ưu đãi học phí chi tiết cho bạn ngay nhé ạ!"
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
# CÁC KÊNH LEAD NGUỒN ĐƯỢC PHÉP CHẠY BOT (CHỈ FACEBOOK & TIKTOK, BỎ QUA ZALO)
# ==============================================================================
ALLOWED_SOURCE_PAGES = [
    # 1. Facebook:
    "514400205095512",          # Anh Kế toán làm Data (Facebook)
    
    # 2. TikTok:
    "tt_7196601676597871618",   # Anh Kế toán làm Data (TikTok @tuananhdata)
    "tt_7456003523327919120",   # Hành trang cho kế toán (TikTok @anhgadata)
    "tt_7661860189083943944",   # Chị Kế Toán GenZ (TikTok @chiketoangenz)
]
