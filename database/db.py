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

# Đối với SQLite cần thêm check_same_thread=False
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,   # Kiểm tra kết nối trước khi dùng
    pool_recycle=1800,    # Tái tạo kết nối sau 30 phút (tránh TLS handshake & setup egress liên tục)
    pool_size=5,
    max_overflow=10,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
