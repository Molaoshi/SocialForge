"""
Simple scheduler stub using APScheduler.

Later this will pull draft posts and push them to platforms
at scheduled times.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from models import SessionLocal, Post

scheduler = BackgroundScheduler()

def check_and_post():
    """Placeholder job – will eventually post due content."""
    db = SessionLocal()
    try:
        due = db.query(Post).filter(
            Post.status == "scheduled",
            Post.scheduled_at <= datetime.utcnow()
        ).all()
        for post in due:
            print(f"[Scheduler] Would post: {post.quote[:60]}...")
            # TODO: call platform posting functions
            # post.status = "posted"
            # post.posted_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()

def start_scheduler():
    scheduler.add_job(check_and_post, "interval", minutes=5, id="post_checker")
    scheduler.start()
    print("✅ Scheduler started (checks every 5 minutes)")

def stop_scheduler():
    scheduler.shutdown()
