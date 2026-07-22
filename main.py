from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from models import init_db, get_db, Post
from content_generator import get_rejection_batch, load_posts_from_json
from imagine import generate_image, batch_generate_images

app = FastAPI(
    title="SocialForge",
    description="AI-Powered Social Media Automation with Grok 4.5 + Grok Imagine",
    version="0.3.0",
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

class GenerateImageResponse(BaseModel):
    post_id: int
    image_url: Optional[str]
    success: bool
    message: str

class BatchGenerateRequest(BaseModel):
    limit: int = 5
    only_missing: bool = True  # only generate for posts that have no image_url yet

# ---------- Routes ----------
@app.get("/")
def root():
    return {
        "message": "SocialForge is running!",
        "version": "0.3.0",
        "docs": "/docs",
        "endpoints": [
            "GET /posts",
            "GET /posts/{id}",
            "GET /posts/batch/rejection",
            "POST /posts/seed",
            "PATCH /posts/{id}/status",
            "POST /posts/{id}/generate-image",
            "POST /posts/generate-images",
            "GET /health",
        ],
    }

@app.get("/posts", response_model=List[PostOut])
def list_posts(
    status: Optional[str] = Query(None, description="Filter by status"),
    boldness: Optional[str] = Query(None, description="mild | medium | high"),
    has_image: Optional[bool] = Query(None, description="Filter posts that already have an image_url"),
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

# ---------- Image Generation ----------
@app.post("/posts/{post_id}/generate-image", response_model=GenerateImageResponse)
def generate_post_image(post_id: int, db: Session = Depends(get_db)):
    """
    Generate an image for a single post using Grok Imagine
    and save the resulting URL to the database.
    """
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
    else:
        return GenerateImageResponse(
            post_id=post.id,
            image_url=None,
            success=False,
            message="Image generation failed. Check logs / API key / model name.",
        )

@app.post("/posts/generate-images")
def generate_images_batch(
    body: BatchGenerateRequest,
    db: Session = Depends(get_db),
):
    """
    Generate images for multiple posts.
    By default only generates for posts that don't have an image_url yet.
    """
    query = db.query(Post)
    if body.only_missing:
        query = query.filter(Post.image_url.is_(None))
    posts = query.order_by(Post.external_id).limit(body.limit).all()

    if not posts:
        return {"message": "No posts found to process", "processed": 0, "results": []}

    results = []
    for post in posts:
        if not post.image_prompt:
            results.append({
                "post_id": post.id,
                "success": False,
                "message": "No image_prompt",
            })
            continue

        image_url = generate_image(post.image_prompt)
        if image_url:
            post.image_url = image_url
            results.append({
                "post_id": post.id,
                "success": True,
                "image_url": image_url,
            })
        else:
            results.append({
                "post_id": post.id,
                "success": False,
                "message": "Generation failed",
            })

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
