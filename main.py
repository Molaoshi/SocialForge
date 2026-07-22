from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, Response
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import re
import httpx

from models import init_db, get_db, Post
from content_generator import load_posts_from_json
from imagine import generate_image

app = FastAPI(
    title="SocialForge",
    description="AI-Powered Social Media Automation with Grok 4.5 + Grok Imagine",
    version="0.6.0",
)

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Simple in-memory cache for proxied Drive images (file_id -> bytes)
_image_cache: dict[str, tuple[bytes, str]] = {}

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
    force: bool = False


def extract_drive_file_id(url: str) -> Optional[str]:
    """Extract Google Drive file ID from common URL shapes."""
    if not url:
        return None
    # /uc?export=view&id=FILE_ID
    m = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    # /file/d/FILE_ID/
    m = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    # /d/FILE_ID
    m = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    # already a bare file id
    if re.fullmatch(r'[a-zA-Z0-9_-]{20,}', url.strip()):
        return url.strip()
    return None


def to_proxy_url(url: Optional[str]) -> Optional[str]:
    """Rewrite Drive URLs to our local proxy so <img> tags work."""
    if not url:
        return None
    fid = extract_drive_file_id(url)
    if fid:
        return f"/media/drive/{fid}"
    return url


def serialize_post(post: Post) -> dict:
    return {
        "id": post.id,
        "external_id": post.external_id,
        "topic": post.topic,
        "quote": post.quote,
        "content": post.content,
        "boldness": post.boldness,
        "image_prompt": post.image_prompt,
        "image_url": to_proxy_url(post.image_url),
        "platforms": post.platforms,
        "status": post.status,
        "scheduled_at": post.scheduled_at,
        "posted_at": post.posted_at,
        "created_at": post.created_at,
    }

# ---------- UI ----------
@app.get("/")
def ui():
    index = static_dir / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "SocialForge API is running (UI not found)", "docs": "/docs"}

@app.get("/api")
def api_root():
    return {"message": "SocialForge API", "version": "0.6.0", "docs": "/docs"}

# ---------- Drive image proxy ----------
@app.get("/media/drive/{file_id}")
async def proxy_drive_image(file_id: str):
    """
    Proxy a public Google Drive file so it can be embedded in <img> tags.
    Caches in memory after first fetch.
    """
    if file_id in _image_cache:
        data, content_type = _image_cache[file_id]
        return Response(content=data, media_type=content_type, headers={
            "Cache-Control": "public, max-age=86400",
        })

    # Prefer the download endpoint; falls back to view
    urls = [
        f"https://drive.google.com/uc?export=download&id={file_id}",
        f"https://drive.google.com/uc?export=view&id={file_id}",
        f"https://drive.google.com/thumbnail?id={file_id}&sz=w2000",
    ]

    last_error = None
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        for url in urls:
            try:
                r = await client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; SocialForge/0.6)",
                })
                if r.status_code == 200 and r.content and len(r.content) > 1000:
                    content_type = r.headers.get("content-type", "image/jpeg")
                    # Skip HTML error pages Google sometimes returns
                    if "text/html" in content_type:
                        continue
                    _image_cache[file_id] = (r.content, content_type)
                    return Response(content=r.content, media_type=content_type, headers={
                        "Cache-Control": "public, max-age=86400",
                    })
            except Exception as e:
                last_error = str(e)
                continue

    raise HTTPException(
        status_code=502,
        detail=f"Could not fetch Drive file {file_id}. {last_error or 'Check sharing is Anyone with the link'}",
    )

# ---------- Posts ----------
@app.get("/posts")
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
    posts = query.order_by(Post.external_id).limit(limit).all()
    return [serialize_post(p) for p in posts]

@app.get("/posts/{post_id}")
def get_post(post_id: int, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return serialize_post(post)

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

@app.patch("/posts/{post_id}/status")
def update_status(post_id: int, body: StatusUpdate, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    post.status = body.status
    if body.status == "posted":
        post.posted_at = datetime.utcnow()
    db.commit()
    db.refresh(post)
    return serialize_post(post)

@app.patch("/posts/{post_id}/image-url")
def set_image_url(post_id: int, body: ImageUrlUpdate, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    post.image_url = body.image_url
    db.commit()
    db.refresh(post)
    return serialize_post(post)

# ---------- Image generation ----------
@app.post("/posts/{post_id}/generate-image", response_model=GenerateImageResponse)
def generate_post_image(
    post_id: int,
    force: bool = Query(False),
    db: Session = Depends(get_db),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if post.image_url and not force:
        return GenerateImageResponse(
            post_id=post.id,
            image_url=to_proxy_url(post.image_url),
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
            image_url=to_proxy_url(image_url),
            success=True,
            message="Image generated via xAI API",
            source="api",
        )

    return GenerateImageResponse(
        post_id=post.id,
        image_url=to_proxy_url(post.image_url),
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
        if post.image_url and not body.force:
            results.append({
                "post_id": post.id,
                "success": True,
                "image_url": to_proxy_url(post.image_url),
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
                "image_url": to_proxy_url(image_url),
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
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat(), "cached_images": len(_image_cache)}
