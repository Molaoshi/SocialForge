from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.orm import declarative_base, sessionmaker
import datetime

Base = declarative_base()

class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(Integer, nullable=True)          # id from JSON batch
    topic = Column(String(255), default="Rejection & Resilience")
    quote = Column(Text)
    content = Column(Text)                                # full caption
    boldness = Column(String(50), default="medium")       # mild | medium | high
    image_prompt = Column(Text)
    image_url = Column(String(512), nullable=True)
    platforms = Column(JSON, default=list)                # ["x", "instagram", ...]
    status = Column(String(50), default="draft")          # draft | scheduled | posted | failed
    scheduled_at = Column(DateTime, nullable=True)
    posted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

# SQLite for simplicity (can switch to Postgres later)
engine = create_engine("sqlite:///socialforge.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
