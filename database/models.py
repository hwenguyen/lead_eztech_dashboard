from sqlalchemy import Column, Integer, String, DateTime, JSON, Boolean, ForeignKey
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

