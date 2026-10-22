from sqlalchemy import Column, Integer, String, DateTime, JSON, Boolean, ForeignKey, Text, Float
from sqlalchemy.orm import relationship
from database.db import Base
from datetime import datetime, timezone, timedelta

VN_TZ = timezone(timedelta(hours=7))
def get_vn_now():
    return datetime.now(VN_TZ).replace(tzinfo=None)

class RawConversation(Base):
    """Lưu trữ dữ liệu thô từ API để trace/debug."""
    __tablename__ = "raw_conversations"

    id = Column(Integer, primary_key=True, index=True)
    pancake_id = Column(String, unique=True, index=True, nullable=False)
    page_id = Column(String, index=True)
    payload = Column(JSON)
    created_at = Column(DateTime, default=get_vn_now)

class DimLead(Base):
    """Thông tin khách hàng (Leads)"""
    __tablename__ = "dim_leads"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    phone_number = Column(String, index=True, nullable=True)
    # Thời điểm khách gửi SĐT lần đầu. NULL = không rõ (số lấy từ hồ sơ Pancake/Zalo) → khi tính dùng first_created_at
    phone_at = Column(DateTime, nullable=True, index=True)
    page_id = Column(String, index=True, nullable=False)
    first_created_at = Column(DateTime, default=get_vn_now, index=True)
    
    # Quan hệ 1-N với FactLeadActivity
    activities = relationship("FactLeadActivity", back_populates="lead")

class FactLeadActivity(Base):
    """Hành vi của Lead (Contact, Tags)"""
    __tablename__ = "fact_lead_activities"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("dim_leads.id"), nullable=False, index=True)
    conversation_id = Column(String, unique=True, index=True, nullable=False)
    status_tag = Column(String, nullable=True)  # VD: "Đang tư vấn", "Đã liên hệ"
    assigned_users = Column(String, nullable=True, index=True) # Nhân viên phụ trách
    message_count = Column(Integer, default=0)
    is_contacted = Column(Boolean, default=False)
    contacted_at = Column(DateTime, nullable=True, index=True) # Last contacted at
    contacted_dates = Column(String, nullable=True) # Comma separated dates like "2026-08-11,2026-08-12"
    tag_timeline = Column(JSON, nullable=True) # Danh sách lịch sử gắn tag [{"tag": "...", "action": "add", "tagged_at": "...", "editor": "..."}]
    
    updated_at = Column(DateTime, default=get_vn_now, onupdate=get_vn_now)

    lead = relationship("DimLead", back_populates="activities")


class BotAutoReplyLog(Base):
    """Lịch sử Bot gửi tin nhắn tự động theo kịch bản."""
    __tablename__ = "bot_auto_replies"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String, index=True, nullable=False)
    customer_id = Column(String, index=True, nullable=True)
    page_id = Column(String, index=True, nullable=False)
    case_id = Column(String, index=True, nullable=False)  # vd: "xin_file", "tham_gia_cong_dong"
    customer_message = Column(String, nullable=True)
    reply_message = Column(String, nullable=False)
    sent_at = Column(DateTime, default=get_vn_now, index=True)
    status = Column(String, default="SENT", index=True)  # "SENT", "DRY_RUN", "FAILED"
    error_message = Column(String, nullable=True)


class Comment(Base):
    """Lưu trữ tất cả Comment từ các kênh nguồn (Facebook, TikTok...)."""
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    comment_id = Column(String, unique=True, index=True, nullable=False)  # Pancake conversation ID (vd: post_id_comment_id)
    page_id = Column(String, index=True, nullable=False)                  # ID trang (vd: 514400205095512, tt_...)
    page_name = Column(String, index=True, nullable=True)                 # Tên chuẩn của trang
    post_id = Column(String, index=True, nullable=True)                   # ID bài viết chứa comment
    post_url = Column(String, nullable=True)                              # Link bài viết (nếu có)
    customer_id = Column(String, index=True, nullable=True)               # ID người comment (PSID/TikTok UID)
    customer_name = Column(String, nullable=True)                         # Tên người comment
    phone_number = Column(String, index=True, nullable=True)              # SĐT nếu khách để lại
    message = Column(Text, nullable=True)                                 # Nội dung comment sạch (plain text)
    raw_message = Column(Text, nullable=True)                             # Nội dung gốc (HTML)
    message_count = Column(Integer, default=1)                            # Số tin nhắn / lượt reply trong comment thread
    tags = Column(String, nullable=True)                                  # Thẻ gắn trên comment
    assigned_users = Column(String, nullable=True)                        # Nhân viên phụ trách
    inserted_at = Column(DateTime, index=True, nullable=True)             # Thời điểm tạo comment trên MXH
    updated_at = Column(DateTime, nullable=True)                          # Thời điểm cập nhật cuối
    payload = Column(JSON, nullable=True)                                 # Dữ liệu gốc đầy đủ từ Pancake API
    created_at = Column(DateTime, default=get_vn_now)                     # Thời điểm lưu vào DB của hệ thống


class Post(Base):
    """Lưu trữ tất cả Bài viết / Video (Post) từ các Fanpage (TikTok, Facebook...)."""
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(String, unique=True, index=True, nullable=False)     # ID bài viết/video từ Pancake (vd: 7234567890 hoặc 256469571178082_1719461745119729)
    page_id = Column(String, index=True, nullable=False)                  # ID trang sở hữu (vd: tt_7196601676597871618, 514400205095512)
    page_name = Column(String, index=True, nullable=True)                 # Tên chuẩn của trang
    platform = Column(String, index=True, default="tiktok")               # Nền tảng: tiktok, facebook
    type = Column(String, index=True, nullable=True)                      # video, photo, text, livestream, rating...
    message = Column(Text, nullable=True)                                 # Nội dung bài viết (caption video / status)
    post_url = Column(String, nullable=True)                              # Link trực tiếp tới video TikTok / bài viết Facebook
    creator_id = Column(String, nullable=True)                            # ID người tạo bài (from.id)
    creator_name = Column(String, nullable=True)                          # Tên người tạo bài (from.name)
    comment_count = Column(Integer, default=0)                            # Số lượng bình luận
    like_count = Column(Integer, default=0)                               # Lượt like / thả tim TikTok
    love_count = Column(Integer, default=0)                               # Lượt love (FB)
    haha_count = Column(Integer, default=0)                               # Lượt haha (FB)
    wow_count = Column(Integer, default=0)                                # Lượt wow (FB)
    sad_count = Column(Integer, default=0)                                # Lượt sad (FB)
    angry_count = Column(Integer, default=0)                              # Lượt angry (FB)
    care_count = Column(Integer, default=0)                               # Lượt care (FB)
    reactions_total = Column(Integer, default=0)                          # Tổng các lượt tương tác
    share_count = Column(Integer, default=0)                              # Lượt chia sẻ video TikTok
    view_count = Column(Integer, default=0)                               # Lượt xem video TikTok (play_count)
    phone_number_count = Column(Integer, default=0)                       # Số SĐT phát hiện trong bài viết
    inserted_at = Column(DateTime, index=True, nullable=True)            # Thời điểm đăng bài viết trên MXH
    updated_at = Column(DateTime, nullable=True)                         # Thời điểm cập nhật cuối
    payload = Column(JSON, nullable=True)                                 # Toàn bộ dữ liệu gốc đầy đủ từ Pancake API
    created_at = Column(DateTime, default=get_vn_now)                     # Thời điểm lưu vào DB của hệ thống


class DealWin(Base):
    """Lưu trữ các Deal chốt thành công / Học viên từ Google Sheet 'THÔNG TIN HỌC VIÊN - EzTech'."""
    __tablename__ = "deal_wins"

    id = Column(Integer, primary_key=True, index=True)
    sheet_row_id = Column(String, unique=True, index=True, nullable=True) # ID định danh dòng trên sheet (vd: row_2)
    timestamp = Column(DateTime, index=True, nullable=True)               # Timestamp (Dấu thời gian)
    email = Column(String, nullable=True)                                 # Email
    full_name = Column(String, index=True, nullable=True)                 # Họ và tên
    phone_number = Column(String, index=True, nullable=True)              # SĐT
    birth_year = Column(String, nullable=True)                           # Năm sinh
    address = Column(String, nullable=True)                              # Địa chỉ (Tỉnh / Thành phố)
    industry = Column(String, nullable=True)                             # Lĩnh vực hoạt động
    job_title = Column(String, nullable=True)                            # Vị trí/ Ngành nghề
    expectation = Column(Text, nullable=True)                            # Mục đích/ Kì vọng tham gia khoá học
    source_channel = Column(String, nullable=True)                       # Bạn biết đến khóa đào tạo qua đâu?
    note = Column(Text, nullable=True)                                   # Note
    course_name = Column(String, index=True, nullable=True)              # HỌC KHÓA (K31, K32, K33, DAK...)
    payment_status = Column(String, nullable=True)                       # ĐÓNG TIỀN (text gốc: "Nộp 3,5tr", "Đã đóng"...)
    revenue = Column(Float, default=0.0, nullable=False)                 # Doanh thu / Số tiền quy đổi dạng số (VNĐ)
    care_by = Column(String, index=True, nullable=True)                  # CHĂM SÓC (Nhân viên sale phụ trách: Hiền Minh...)
    status = Column(String, default="WIN", index=True)                   # Trạng thái (WIN, CANCELLED, REFUND...)
    raw_data = Column(JSON, nullable=True)                               # Lưu toàn bộ dữ liệu gốc của dòng form
    created_at = Column(DateTime, default=get_vn_now)                    # Thời điểm lưu vào DB
    updated_at = Column(DateTime, default=get_vn_now, onupdate=get_vn_now)

    # Thuộc tính tương thích ngược (aliases)
    @property
    def customer_name(self):
        return self.full_name

    @property
    def product_name(self):
        return self.course_name

    @property
    def sales_person(self):
        return self.care_by

    @property
    def submitted_at(self):
        return self.timestamp





