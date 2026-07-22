import json
from pathlib import Path

# Core content generation using Grok 4.5

def load_posts_from_json(file_path: str = "data/rejection_posts.json"):
    """Load structured posts from JSON for scheduling."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {file_path}")
    
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    return data.get("posts", [])


def generate_posts(topic: str, count: int = 100):
    """Generate new posts on a topic (placeholder for Grok 4.5 integration)."""
    print(f"Generating {count} posts on {topic}...")
    # TODO: Integrate with xAI Grok API for real research + generation
    return [f"Post {i} about {topic}" for i in range(count)]


def get_rejection_batch():
    """Convenience function to load the rejection resilience batch."""
    return load_posts_from_json()


if __name__ == "__main__":
    posts = get_rejection_batch()
    print(f"Loaded {len(posts)} posts from rejection_posts.json")
    print("Sample post:")
    print(json.dumps(posts[0], indent=2))
