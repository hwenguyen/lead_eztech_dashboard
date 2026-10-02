import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

# Sử dụng SQLite tạm nếu không có DATABASE_URL để test trên môi trường Free Tier dễ dàng.
# Trên production, hãy set DATABASE_URL=postgresql://user:password@host:port/dbname
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./leads_data.db")

# SQLAlchemy 2.1 đổi driver mặc định của postgresql:// sang psycopg (v3) → chỉ định rõ psycopg2 đang cài
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[len("postgresql://"):]

# Đối với SQLite cần thêm check_same_thread=False
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,  # Neon đóng kết nối idle → kiểm tra trước khi dùng lại connection trong pool
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
