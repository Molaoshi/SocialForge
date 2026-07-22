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

# Correct model names (as of 2026):
#   grok-imagine-image
#   grok-imagine-image-quality
IMAGE_MODEL = "grok-imagine-image"


def generate_image(prompt: str, style: str = "sci-fi cyberpunk") -> Optional[str]:
    """
    Generate an image from a text prompt using Grok Imagine.

    Returns a URL of the generated image, or None on failure.
    Pricing: ~$0.02 per image (requires credits on the xAI account).
    """
    if not XAI_API_KEY:
        print("[Grok Imagine] No XAI_API_KEY found in environment.")
        return None

    full_prompt = f"{prompt} Style: {style}, high quality, cinematic lighting, vibrant neon colors."

    print(f"[Grok Imagine] Generating with model={IMAGE_MODEL}...")
    print(f"  Prompt: {full_prompt[:140]}...")

    try:
        headers = {
            "Authorization": f"Bearer {XAI_API_KEY}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": IMAGE_MODEL,
            "prompt": full_prompt,
            "n": 1,
            "response_format": "url",
        }

        with httpx.Client(timeout=90.0) as client:
            response = client.post(
                f"{XAI_BASE_URL}/images/generations",
                headers=headers,
                json=payload,
            )

            print(f"[Grok Imagine] Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                # Response shape: { "data": [ { "url": "..." } ] }
                if "data" in data and len(data["data"]) > 0:
                    item = data["data"][0]
                    url = item.get("url") or item.get("b64_json")
                    if url:
                        print("[Grok Imagine] Success")
                        return url
                print("[Grok Imagine] Unexpected response:", data)
                return None

            # Helpful error messages
            body = response.text[:500]
            print(f"[Grok Imagine] Error body: {body}")

            if response.status_code == 401:
                print("[Grok Imagine] Invalid or missing API key")
            elif response.status_code == 402 or "insufficient" in body.lower() or "credit" in body.lower():
                print("[Grok Imagine] No credits / payment required — add credits at console.x.ai")
            elif response.status_code == 404 or "model" in body.lower():
                print("[Grok Imagine] Model not found — check model name")

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
    test_prompt = "A glowing neon sign that says Rejection is just redirection, cyberpunk style"
    result = generate_image(test_prompt)
    print("Result:", result)
