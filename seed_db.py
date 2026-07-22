"""
Seed the database with the rejection_posts.json batch.
Also merges any data/image_urls_batch*.json files (Drive public URLs).

Run:  python seed_db.py
"""
import json
from pathlib import Path
from models import init_db, SessionLocal, Post

def load_image_url_overrides() -> dict:
    """Load all data/image_urls_batch*.json into {post_id: url}."""
    overrides = {}
    data_dir = Path("data")
    if not data_dir.exists():
        return overrides
    for path in sorted(data_dir.glob("image_urls_batch*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                batch = json.load(f)
            for k, v in batch.items():
                overrides[int(k)] = v
            print(f"  Loaded image URLs from {path.name} ({len(batch)} entries)")
        except Exception as e:
            print(f"  Warning: could not load {path}: {e}")
    return overrides

def seed_rejection_posts(update_existing: bool = True):
    init_db()
    db = SessionLocal()

    json_path = Path("data/rejection_posts.json")
    if not json_path.exists():
        print("❌ data/rejection_posts.json not found")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    url_overrides = load_image_url_overrides()
    posts_data = data.get("posts", [])
    print(f"Loading {len(posts_data)} posts...")

    added = 0
    updated = 0
    skipped = 0

    for p in posts_data:
        pid = p["id"]
        # Prefer explicit image_url in post, then override file
        image_url = p.get("image_url") or url_overrides.get(pid)

        exists = db.query(Post).filter(Post.external_id == pid).first()

        if exists:
            if update_existing:
                if image_url:
                    exists.image_url = image_url
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
            external_id=pid,
            topic=data.get("topic", "Rejection & Resilience"),
            quote=p.get("quote"),
            content=p.get("caption"),
            boldness=p.get("boldness", "medium"),
            image_prompt=p.get("image_prompt"),
            image_url=image_url,
            platforms=p.get("platforms", ["x", "instagram", "threads", "linkedin", "facebook"]),
            status=p.get("status", "draft"),
        )
        db.add(post)
        added += 1

    db.commit()
    with_images = db.query(Post).filter(Post.image_url.isnot(None)).count()
    db.close()

    print(f"✅ Added {added} | Updated {updated} | Skipped {skipped}")
    print(f"🖼️  Posts with images: {with_images}")
    print("Database ready: socialforge.db")

if __name__ == "__main__":
    seed_rejection_posts()
