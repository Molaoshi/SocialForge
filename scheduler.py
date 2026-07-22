"""
Background scheduler: posts due content to X.
Runs every 2 minutes.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import logging
import os

from models import SessionLocal, Post

log = logging.getLogger("scheduler")
scheduler = BackgroundScheduler()


def check_and_post():
    """Find scheduled posts that are due and publish them to X."""
    from x_poster import post_tweet, is_configured

    if not is_configured():
        log.debug("X not configured — skip scheduler cycle")
        return

    db = SessionLocal()
    try:
        due = (
            db.query(Post)
            .filter(
                Post.status == "scheduled",
                Post.scheduled_at != None,
                Post.scheduled_at <= datetime.utcnow(),
            )
            .order_by(Post.scheduled_at)
            .limit(5)
            .all()
        )

        if not due:
            return

        base_url = os.getenv("APP_BASE_URL", "").rstrip("/")

        for post in due:
            text = post.content or post.quote or ""
            if not text.strip():
                post.status = "failed"
                log.warning("Post %s has no text", post.id)
                continue

            # Prefer absolute image URL for download
            image_url = post.image_url
            if image_url and image_url.startswith("/") and base_url:
                image_url = base_url + image_url

            result = post_tweet(text=text, image_url=image_url, base_url=base_url)

            if result.get("success"):
                post.status = "posted"
                post.posted_at = datetime.utcnow()
                log.info("Posted #%s → tweet %s", post.id, result.get("tweet_id"))
            else:
                post.status = "failed"
                log.error("Failed to post #%s: %s", post.id, result.get("error"))

        db.commit()
    except Exception as e:
        log.exception("Scheduler cycle error: %s", e)
        db.rollback()
    finally:
        db.close()


def start_scheduler():
    if scheduler.running:
        return
    scheduler.add_job(check_and_post, "interval", minutes=2, id="post_checker", replace_existing=True)
    scheduler.start()
    print("✅ Scheduler started (checks every 2 minutes)")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
