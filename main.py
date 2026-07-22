from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from pathlib import Path

from models import init_db, get_db, Post
from content_generator import get_rejection_batch, load_posts_from_json
from imagine import generate_image

app = FastAPI(
    title="SocialForge",
    description="AI-Powered Social Media Automation with Grok 4.5 + Grok Imagine",
    version="0.4.0",
)

# Serve the UI
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

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
    status: str

class GenerateImageResponse(BaseModel):
    post_id: int
    image_url: Optional[str]
    success: bool
    message: str

class BatchGenerateRequest(BaseModel):
    limit: int = 5
    only_missing: bool = True

# ---------- UI ----------
@app.get("/")
def ui():
    """Serve the main UI."""
    index = static_dir / "index.html"
    if index.exists():
        return FileResponse(index)
    return {
        "message": "SocialForge API is running (UI not found)",
        "docs": "/docs",
    }

# ---------- API Routes ----------
@app.get("/api")
def api_root():
    return {
        "message": "SocialForge API",
        "version": "0.4.0",
        "docs": "/docs",
    }

@app.get("/posts", response_model=List[PostOut])
def list_posts(
    status: Optional[str] = Query(None),
    boldness: Optional[str] = Query(None),
    has_image: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(Post)
    if status:
        query = query.filter(Post.status == status)
    if boldness:
        query = query.filter(Post.boldness == boldness)
    if has_image is True:
        query = query.filter(Post.image_url.isnot(None))
    elif has_image is False:
        query = query.filter(Post.image_url.is_(None))
    return query.order_by(Post.external_id).limit(limit).all()

@app.get("/posts/{post_id}", response_model=PostOut)
def get_post(post_id: int, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post

@app.get("/posts/batch/rejection")
def get_rejection_json():
    return load_posts_from_json()

@app.post("/posts/seed")
def seed_posts(db: Session = Depends(get_db)):
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

@app.post("/posts/{post_id}/generate-image", response_model=GenerateImageResponse)
def generate_post_image(post_id: int, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if not post.image_prompt:
        raise HTTPException(status_code=400, detail="Post has no image_prompt")

    image_url = generate_image(post.image_prompt)

    if image_url:
        post.image_url = image_url
        db.commit()
        db.refresh(post)
        return GenerateImageResponse(
            post_id=post.id,
            image_url=image_url,
            success=True,
            message="Image generated and saved",
        )
    return GenerateImageResponse(
        post_id=post.id,
        image_url=None,
        success=False,
        message="Image generation failed. Check logs / API key / model name.",
    )

@app.post("/posts/generate-images")
def generate_images_batch(body: BatchGenerateRequest, db: Session = Depends(get_db)):
    query = db.query(Post)
    if body.only_missing:
        query = query.filter(Post.image_url.is_(None))
    posts = query.order_by(Post.external_id).limit(body.limit).all()

    if not posts:
        return {"message": "No posts found to process", "processed": 0, "results": []}

    results = []
    for post in posts:
        if not post.image_prompt:
            results.append({"post_id": post.id, "success": False, "message": "No image_prompt"})
            continue

        image_url = generate_image(post.image_prompt)
        if image_url:
            post.image_url = image_url
            results.append({"post_id": post.id, "success": True, "image_url": image_url})
        else:
            results.append({"post_id": post.id, "success": False, "message": "Generation failed"})

    db.commit()
    success_count = sum(1 for r in results if r.get("success"))
    return {
        "message": f"Processed {len(results)} posts, {success_count} successful",
        "processed": len(results),
        "successful": success_count,
        "results": results,
    }

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
