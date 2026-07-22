"""
Grok Imagine integration.

Uses the xAI API when XAI_API_KEY is set in the environment.
"""
import os
from typing import Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

XAI_API_KEY = os.getenv("XAI_API_KEY")
XAI_BASE_URL = "https://api.x.ai/v1"

def generate_image(prompt: str, style: str = "sci-fi cyberpunk") -> Optional[str]:
    """
    Generate an image from a text prompt using Grok Imagine / xAI image models.

    Returns a URL (or local path) of the generated image, or None on failure.
    """
    if not XAI_API_KEY:
        print("[Grok Imagine] No XAI_API_KEY found in environment. Using placeholder.")
        return f"https://placeholder.socialforge.local/generated/{hash(prompt) % 100000}.jpg"

    full_prompt = f"{prompt} Style: {style}, high quality, cinematic lighting, vibrant neon colors."

    print(f"[Grok Imagine] Generating image...")
    print(f"  Prompt: {full_prompt[:120]}...")

    try:
        # Note: Exact image generation endpoint may evolve.
        # This uses the current xAI image generation pattern.
        headers = {
            "Authorization": f"Bearer {XAI_API_KEY}",
            "Content-Type": "application/json",
        }

        # Primary attempt – adjust model name if needed (e.g. grok-imagine or flux-based)
        payload = {
            "model": "grok-2-image",
            "prompt": full_prompt,
            "n": 1,
        }

        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{XAI_BASE_URL}/images/generations",
                headers=headers,
                json=payload,
            )

            if response.status_code == 200:
                data = response.json()
                # Common response shapes
                if "data" in data and len(data["data"]) > 0:
                    url = data["data"][0].get("url") or data["data"][0].get("b64_json")
                    if url:
                        print("[Grok Imagine] Success")
                        return url
                print("[Grok Imagine] Unexpected response shape:", data)
                return None
            else:
                print(f"[Grok Imagine] Error {response.status_code}: {response.text[:300]}")
                return None

    except Exception as e:
        print(f"[Grok Imagine] Exception: {e}")
        return None


def batch_generate_images(posts: list[dict]) -> list[dict]:
    """Generate images for a list of posts that have image_prompt."""
    results = []
    for i, post in enumerate(posts, 1):
        prompt = post.get("image_prompt")
        if prompt:
            print(f"[{i}/{len(posts)}] Generating...")
            url = generate_image(prompt)
            post["image_url"] = url
        results.append(post)
    return results


if __name__ == "__main__":
    # Quick test
    test_prompt = "A glowing neon sign that says Rejection is just redirection, cyberpunk style"
    result = generate_image(test_prompt)
    print("Result:", result)
