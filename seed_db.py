"""
Seed the database with the rejection_posts.json batch.
Run once:  python seed_db.py
"""
import json
from pathlib import Path
from models import init_db, SessionLocal, Post

def seed_rejection_posts():
    init_db()
    db = SessionLocal()

    json_path = Path("data/rejection_posts.json")
    if not json_path.exists():
        print("❌ data/rejection_posts.json not found")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    posts_data = data.get("posts", [])
    print(f"Loading {len(posts_data)} posts...")

    added = 0
    skipped = 0

    for p in posts_data:
        # Avoid duplicates by external_id
        exists = db.query(Post).filter(Post.external_id == p["id"]).first()
        if exists:
            skipped += 1
            continue

        post = Post(
            external_id=p["id"],
            topic=data.get("topic", "Rejection & Resilience"),
            quote=p.get("quote"),
            content=p.get("caption"),
            boldness=p.get("boldness", "medium"),
            image_prompt=p.get("image_prompt"),
            platforms=p.get("platforms", ["x", "instagram", "threads", "linkedin", "facebook"]),
            status=p.get("status", "draft"),
        )
        db.add(post)
        added += 1

    db.commit()
    db.close()

    print(f"✅ Added {added} posts | Skipped {skipped} existing")
    print("Database ready: socialforge.db")

if __name__ == "__main__":
    seed_rejection_posts()
