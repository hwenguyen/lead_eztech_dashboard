"""Đồng bộ schema DB: tạo bảng, thêm cột và index còn thiếu cho bảng đã tồn tại (create_all không tự làm việc này)."""
import logging
import time
from sqlalchemy import inspect, text
from database.db import engine, Base
import database.models  # noqa: F401 - đăng ký model vào Base.metadata

logger = logging.getLogger(__name__)

INDEX_DDL = [
    "CREATE INDEX IF NOT EXISTS ix_dim_leads_first_created_at ON dim_leads (first_created_at)",
    "CREATE INDEX IF NOT EXISTS ix_dim_leads_phone_at ON dim_leads (phone_at)",
    "CREATE INDEX IF NOT EXISTS ix_fact_lead_activities_lead_id ON fact_lead_activities (lead_id)",
    "CREATE INDEX IF NOT EXISTS ix_fact_lead_activities_contacted_at ON fact_lead_activities (contacted_at)",
]


def _run_ddl(statements):
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            # Không chờ khoá vô hạn khi ETL / auto repair đang giữ transaction trên bảng
            conn.execute(text("SET LOCAL lock_timeout = '30s'"))
        for ddl in statements:
            conn.execute(text(ddl))


def _add_missing_columns():
    existing = {col["name"] for col in inspect(engine).get_columns("dim_leads")}
    if "phone_at" in existing:
        return
    # Backend và ETL có thể cùng chạy → Postgres dùng IF NOT EXISTS để không lỗi khi bên kia thêm trước
    if_not_exists = "IF NOT EXISTS " if engine.dialect.name == "postgresql" else ""
    _run_ddl([f"ALTER TABLE dim_leads ADD COLUMN {if_not_exists}phone_at TIMESTAMP"])
    logger.info("Đã thêm cột dim_leads.phone_at.")


def ensure_schema(retries: int = 5):
    """Gọi khi khởi động Backend và đầu mỗi lần chạy ETL. Thiếu cột thì raise để không chạy nửa vời."""
    Base.metadata.create_all(bind=engine)

    for attempt in range(1, retries + 1):
        try:
            _add_missing_columns()
            break
        except Exception as e:
            if attempt == retries:
                raise
            logger.warning(f"Chưa thêm được cột (lần {attempt}/{retries}): {e}")
            time.sleep(5)

    try:
        _run_ddl(INDEX_DDL)
    except Exception as e:
        logger.error(f"Create index error: {e}")
