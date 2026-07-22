from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from pathlib import Path

from models import init_db, get_db, Post
from content_generator import load_posts_from_json
from imagine import generate_image

app = FastAPI(
    title="SocialForge",
    description="AI-Powered Social Media Automation with Grok 4.5 + Grok Imagine",
    version="0.5.0",
)

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.on_event("startup")
def startup():
    init_db()

# ---------- Schemas ----------
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

class ImageUrlUpdate(BaseModel):
    image_url: str

class GenerateImageResponse(BaseModel):
    post_id: int
    image_url: Optional[str]
    success: bool
    message: str
    source: str = "api"  # api | existing | json

class BatchGenerateRequest(BaseModel):
    limit: int = 5
    only_missing: bool = True
    force: bool = False  # if True, regenerate even when image_url exists

# ---------- UI ----------
@app.get("/")
def ui():
    index = static_dir / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "SocialForge API is running (UI not found)", "docs": "/docs"}

@app.get("/api")
def api_root():
    return {"message": "SocialForge API", "version": "0.5.0", "docs": "/docs"}

# ---------- Posts ----------
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
    seed_rejection_posts(update_existing=True)
    count = db.query(Post).count()
    with_images = db.query(Post).filter(Post.image_url.isnot(None)).count()
    return {
        "message": "Seed complete",
        "total_posts_in_db": count,
        "posts_with_images": with_images,
    }

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

@app.patch("/posts/{post_id}/image-url", response_model=PostOut)
def set_image_url(post_id: int, body: ImageUrlUpdate, db: Session = Depends(get_db)):
    """Manually set / override the image URL for a post (no API call)."""
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    post.image_url = body.image_url
    db.commit()
    db.refresh(post)
    return post

# ---------- Image generation (API only when needed) ----------
@app.post("/posts/{post_id}/generate-image", response_model=GenerateImageResponse)
def generate_post_image(
    post_id: int,
    force: bool = Query(False, description="Regenerate even if image_url already exists"),
    db: Session = Depends(get_db),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Prefer existing URL — no API call
    if post.image_url and not force:
        return GenerateImageResponse(
            post_id=post.id,
            image_url=post.image_url,
            success=True,
            message="Using existing image_url (no API call)",
            source="existing",
        )

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
            message="Image generated via xAI API",
            source="api",
        )

    return GenerateImageResponse(
        post_id=post.id,
        image_url=post.image_url,
        success=False,
        message="API generation failed. Set image_url manually or add credits at console.x.ai",
        source="api",
    )

@app.post("/posts/generate-images")
def generate_images_batch(body: BatchGenerateRequest, db: Session = Depends(get_db)):
    query = db.query(Post)
    if body.only_missing and not body.force:
        query = query.filter(Post.image_url.is_(None))
    posts = query.order_by(Post.external_id).limit(body.limit).all()

    if not posts:
        return {"message": "No posts found to process", "processed": 0, "results": []}

    results = []
    for post in posts:
        # Prefer existing
        if post.image_url and not body.force:
            results.append({
                "post_id": post.id,
                "success": True,
                "image_url": post.image_url,
                "source": "existing",
            })
            continue

        if not post.image_prompt:
            results.append({"post_id": post.id, "success": False, "message": "No image_prompt"})
            continue

        image_url = generate_image(post.image_prompt)
        if image_url:
            post.image_url = image_url
            results.append({
                "post_id": post.id,
                "success": True,
                "image_url": image_url,
                "source": "api",
            })
        else:
            results.append({
                "post_id": post.id,
                "success": False,
                "message": "API generation failed",
                "source": "api",
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
