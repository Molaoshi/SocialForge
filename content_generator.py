import json
import os
from pathlib import Path
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

# Core content generation using Grok 4.5

def load_posts_from_json(file_path: str = "data/rejection_posts.json") -> List[Dict[str, Any]]:
    """Load structured posts from JSON for scheduling."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {file_path}")
    
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    return data.get("posts", [])


def generate_posts(topic: str, count: int = 50) -> List[Dict[str, Any]]:
    """
    Generate new posts on a topic using Grok via xAI API.
    Falls back to placeholder if no API key.
    """
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        print(f"[Content] No XAI_API_KEY – returning placeholders for '{topic}'")
        return [{
            "id": i,
            "quote": f"Placeholder quote {i} about {topic}",
            "caption": f"Post {i} about {topic}. #Growth",
            "boldness": "medium",
            "image_prompt": f"Motivational quote about {topic}, sci-fi cyberpunk style",
            "status": "draft",
            "platforms": ["x", "instagram", "threads", "linkedin", "facebook"]
        } for i in range(1, count + 1)]

    print(f"[Content] Generating {count} posts on '{topic}' with Grok...")
    # TODO: Real multi-turn research + generation with Grok 4.5
    # For now we still use the curated batch for quality
    return load_posts_from_json()


def get_rejection_batch() -> List[Dict[str, Any]]:
    """Convenience function to load the rejection resilience batch."""
    return load_posts_from_json()


if __name__ == "__main__":
    posts = get_rejection_batch()
    print(f"Loaded {len(posts)} posts from rejection_posts.json")
    print("Sample post:")
    print(json.dumps(posts[0], indent=2))
