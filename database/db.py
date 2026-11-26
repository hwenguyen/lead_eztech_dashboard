import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# Nạp biến môi trường từ .env.local (do Neon CLI sinh ra) và .env
load_dotenv(".env.local")
load_dotenv(".env")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./leads_data.db")

# SQLAlchemy 2.1 đổi driver mặc định của postgresql:// sang psycopg (v3) → chỉ định rõ psycopg2 đang cài
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]
if DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+psycopg2://"):
    DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[len("postgresql://"):]

# Đối với SQLite cần thêm check_same_thread=False; Postgres dùng TCP keepalive tránh treo socket khi vượt idle
connect_args = (
    {"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite")
    else {
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
        "connect_timeout": 10,
    }
)

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,   # Kiểm tra kết nối trước khi dùng
    pool_recycle=240,     # Đóng kết nối nhàn rỗi sau 4 phút để Neon tự ngủ sau 5 phút không dùng
    pool_size=3,          # Đủ cho 3 API song song lúc mở Deal Win / Nhập Deal mà không phải tạo thêm overflow
    max_overflow=5,
    pool_timeout=15,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
