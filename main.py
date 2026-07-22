from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
from datetime import datetime, timedelta
from pathlib import Path
import re
import os
import httpx

from models import init_db, get_db, Post
from content_generator import load_posts_from_json
from imagine import generate_image

app = FastAPI(
    title="SocialForge",
    description="AI-Powered Social Media Automation with Grok 4.5 + Grok Imagine",
    version="0.7.0",
)

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

_image_cache: dict[str, tuple[bytes, str]] = {}


@app.on_event("startup")
def startup():
    init_db()
    try:
        from scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        print(f"Scheduler start skipped: {e}")


# ---------- Schemas ----------
class StatusUpdate(BaseModel):
    status: str

class ImageUrlUpdate(BaseModel):
    image_url: str

class ScheduleUpdate(BaseModel):
    scheduled_at: Optional[datetime] = None  # ISO datetime; if None, schedule in 1 min

class GenerateImageResponse(BaseModel):
    post_id: int
    image_url: Optional[str]
    success: bool
    message: str
    source: str = "api"

class BatchGenerateRequest(BaseModel):
    limit: int = 5
    only_missing: bool = True
    force: bool = False


def extract_drive_file_id(url: str) -> Optional[str]:
    if not url:
        return None
    m = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    m = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    m = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    if re.fullmatch(r'[a-zA-Z0-9_-]{20,}', url.strip()):
        return url.strip()
    return None


def to_proxy_url(url: Optional[str]) -> Optional[str]:
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


def app_base_url(request: Request) -> str:
    env = os.getenv("APP_BASE_URL", "").rstrip("/")
    if env:
        return env
    return str(request.base_url).rstrip("/")


# ---------- UI ----------
@app.get("/")
def ui():
    index = static_dir / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "SocialForge API is running", "docs": "/docs"}


@app.get("/api")
def api_root():
    from x_poster import is_configured
    return {
        "message": "SocialForge API",
        "version": "0.7.0",
        "x_configured": is_configured(),
        "docs": "/docs",
    }


# ---------- Drive image proxy ----------
@app.get("/media/drive/{file_id}")
async def proxy_drive_image(file_id: str):
    if file_id in _image_cache:
        data, content_type = _image_cache[file_id]
        return Response(content=data, media_type=content_type, headers={
            "Cache-Control": "public, max-age=86400",
        })

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
                    "User-Agent": "Mozilla/5.0 (compatible; SocialForge/0.7)",
                })
                if r.status_code == 200 and r.content and len(r.content) > 1000:
                    content_type = r.headers.get("content-type", "image/jpeg")
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
        detail=f"Could not fetch Drive file {file_id}. {last_error or ''}",
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


@app.post("/posts/{post_id}/schedule")
def schedule_post(post_id: int, body: ScheduleUpdate, db: Session = Depends(get_db)):
    """Mark post as scheduled. Default: 1 minute from now."""
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    when = body.scheduled_at or (datetime.utcnow() + timedelta(minutes=1))
    post.scheduled_at = when
    post.status = "scheduled"
    db.commit()
    db.refresh(post)
    return serialize_post(post)


@app.post("/posts/{post_id}/post-to-x")
def post_to_x_now(post_id: int, request: Request, db: Session = Depends(get_db)):
    """Immediately post this item to X."""
    from x_poster import post_tweet, is_configured

    if not is_configured():
        raise HTTPException(
            status_code=400,
            detail="X_ACCESS_TOKEN not set. Add it in Railway Variables.",
        )

    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    text = post.content or post.quote or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="Post has no text")

    base = app_base_url(request)
    image_url = to_proxy_url(post.image_url)
    if image_url and image_url.startswith("/"):
        image_url = base + image_url

    result = post_tweet(text=text, image_url=image_url, base_url=base)

    if result.get("success"):
        post.status = "posted"
        post.posted_at = datetime.utcnow()
        db.commit()
        db.refresh(post)
        return {
            "success": True,
            "tweet_id": result.get("tweet_id"),
            "media_attached": result.get("media_attached"),
            "post": serialize_post(post),
        }

    post.status = "failed"
    db.commit()
    raise HTTPException(status_code=502, detail=result.get("error", "Post failed"))


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
        message="API generation failed",
        source="api",
    )


@app.post("/posts/generate-images")
def generate_images_batch(body: BatchGenerateRequest, db: Session = Depends(get_db)):
    query = db.query(Post)
    if body.only_missing and not body.force:
        query = query.filter(Post.image_url.is_(None))
    posts = query.order_by(Post.external_id).limit(body.limit).all()

    if not posts:
        return {"message": "No posts found", "processed": 0, "results": []}

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
            results.append({"post_id": post.id, "success": False, "message": "API failed", "source": "api"})

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
    from x_poster import is_configured
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "cached_images": len(_image_cache),
        "x_configured": is_configured(),
    }
