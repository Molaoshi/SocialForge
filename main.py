from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from models import init_db, get_db, Post
from content_generator import get_rejection_batch, load_posts_from_json

app = FastAPI(
    title="SocialForge",
    description="AI-Powered Social Media Automation with Grok 4.5 + Grok Imagine",
    version="0.2.0",
)

# Initialize DB on startup
@app.on_event("startup")
def startup():
    init_db()

# ---------- Pydantic schemas ----------
class PostOut(BaseModel):
    id: int
    external_id: Optional[int]
    topic: Optional[str]
    quote: Optional[str]
    content: Optional[str]
    boldness: Optional[str]
    image_prompt: Optional[str]
    image_url: Optional[str]
    platforms: Optional[list]
    status: str
    scheduled_at: Optional[datetime]
    posted_at: Optional[datetime]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True

class StatusUpdate(BaseModel):
    status: str  # draft | scheduled | posted | failed

# ---------- Routes ----------
@app.get("/")
def root():
    return {
        "message": "SocialForge is running!",
        "docs": "/docs",
        "endpoints": [
            "GET /posts",
            "GET /posts/{id}",
            "GET /posts/batch/rejection",
            "POST /posts/seed",
            "PATCH /posts/{id}/status",
        ],
    }

@app.get("/posts", response_model=List[PostOut])
def list_posts(
    status: Optional[str] = Query(None, description="Filter by status"),
    boldness: Optional[str] = Query(None, description="mild | medium | high"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(Post)
    if status:
        query = query.filter(Post.status == status)
    if boldness:
        query = query.filter(Post.boldness == boldness)
    return query.order_by(Post.external_id).limit(limit).all()

@app.get("/posts/{post_id}", response_model=PostOut)
def get_post(post_id: int, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post

@app.get("/posts/batch/rejection")
def get_rejection_json():
    """Return the raw JSON batch (useful before seeding)."""
    return load_posts_from_json()

@app.post("/posts/seed")
def seed_posts(db: Session = Depends(get_db)):
    """Load rejection_posts.json into the database."""
    from seed_db import seed_rejection_posts
    seed_rejection_posts()
    count = db.query(Post).count()
    return {"message": "Seed complete", "total_posts_in_db": count}

@app.patch("/posts/{post_id}/status", response_model=PostOut)
def update_status(post_id: int, body: StatusUpdate, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    post.status = body.status
    if body.status == "posted":
        post.posted_at = datetime.utcnow()
    db.commit()
    db.refresh(post)
    return post

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
