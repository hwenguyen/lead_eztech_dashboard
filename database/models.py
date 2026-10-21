from sqlalchemy import Column, Integer, String, DateTime, JSON, Boolean, ForeignKey, Text
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
    """Lưu trữ tất cả Bài viết (Post) từ các Fanpage (Facebook, TikTok...)."""
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(String, unique=True, index=True, nullable=False)     # ID bài viết từ Pancake (vd: 256469571178082_1719461745119729)
    page_id = Column(String, index=True, nullable=False)                  # ID trang sở hữu
    page_name = Column(String, index=True, nullable=True)                 # Tên chuẩn của trang
    type = Column(String, index=True, nullable=True)                      # video, photo, text, livestream, rating...
    message = Column(Text, nullable=True)                                 # Nội dung bài viết (caption / status)
    post_url = Column(String, nullable=True)                              # Link trực tiếp tới bài viết
    creator_id = Column(String, nullable=True)                            # ID người tạo bài (from.id)
    creator_name = Column(String, nullable=True)                          # Tên người tạo bài (from.name)
    comment_count = Column(Integer, default=0)                            # Số lượng bình luận
    like_count = Column(Integer, default=0)                               # Lượt like
    love_count = Column(Integer, default=0)                               # Lượt love
    haha_count = Column(Integer, default=0)                               # Lượt haha
    wow_count = Column(Integer, default=0)                                # Lượt wow
    sad_count = Column(Integer, default=0)                                # Lượt sad
    angry_count = Column(Integer, default=0)                              # Lượt angry
    care_count = Column(Integer, default=0)                               # Lượt care
    reactions_total = Column(Integer, default=0)                          # Tổng các lượt tương tác
    phone_number_count = Column(Integer, default=0)                       # Số SĐT phát hiện trong bài viết
    inserted_at = Column(DateTime, index=True, nullable=True)            # Thời điểm đăng bài viết trên MXH
    updated_at = Column(DateTime, nullable=True)                         # Thời điểm cập nhật cuối
    payload = Column(JSON, nullable=True)                                 # Toàn bộ dữ liệu gốc đầy đủ từ Pancake API
    created_at = Column(DateTime, default=get_vn_now)                     # Thời điểm lưu vào DB của hệ thống



