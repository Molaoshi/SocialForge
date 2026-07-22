"""
Seed the database with the rejection_posts.json batch.
Run once:  python seed_db.py

If a post in the JSON already has image_url, it is stored and
the API will not need to generate a new image for it.
"""
import json
from pathlib import Path
from models import init_db, SessionLocal, Post

def seed_rejection_posts(update_existing: bool = True):
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
    updated = 0
    skipped = 0

    for p in posts_data:
        exists = db.query(Post).filter(Post.external_id == p["id"]).first()

        if exists:
            if update_existing:
                # Keep existing image_url unless JSON provides a new one
                if p.get("image_url"):
                    exists.image_url = p["image_url"]
                if p.get("caption"):
                    exists.content = p["caption"]
                if p.get("quote"):
                    exists.quote = p["quote"]
                if p.get("image_prompt"):
                    exists.image_prompt = p["image_prompt"]
                updated += 1
            else:
                skipped += 1
            continue

        post = Post(
            external_id=p["id"],
            topic=data.get("topic", "Rejection & Resilience"),
            quote=p.get("quote"),
            content=p.get("caption"),
            boldness=p.get("boldness", "medium"),
            image_prompt=p.get("image_prompt"),
            image_url=p.get("image_url"),  # use pre-set URL if present
            platforms=p.get("platforms", ["x", "instagram", "threads", "linkedin", "facebook"]),
            status=p.get("status", "draft"),
        )
        db.add(post)
        added += 1

    db.commit()
    db.close()

    print(f"✅ Added {added} | Updated {updated} | Skipped {skipped}")
    print("Database ready: socialforge.db")

if __name__ == "__main__":
    seed_rejection_posts()
