from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime

Base = declarative_base()

class Post(Base):
    __tablename__ = 'posts'
    id = Column(Integer, primary_key=True)
    topic = Column(String)
    content = Column(Text)
    image_prompt = Column(Text)
    image_url = Column(String)
    platform = Column(String)
    status = Column(String, default='draft')
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

engine = create_engine('sqlite:///socialforge.db')
Base.metadata.create_all(engine)