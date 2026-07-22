"""
Post to X (Twitter) using OAuth 2.0 user access token.

Env vars required:
  X_ACCESS_TOKEN       - OAuth 2.0 user access token (tweet.write)
  X_REFRESH_TOKEN      - optional, for token refresh
  X_CLIENT_ID          - for refresh
  X_CLIENT_SECRET      - for refresh

Optional (legacy OAuth 1.0a, not required for text posts):
  X_API_KEY, X_API_KEY_SECRET, X_ACCESS_TOKEN_SECRET
"""
from __future__ import annotations

import os
import base64
import logging
from typing import Optional

import httpx

log = logging.getLogger("x_poster")

X_API_BASE = "https://api.x.com/2"
MEDIA_UPLOAD_URL = "https://api.x.com/2/media/upload"
TOKEN_URL = "https://api.x.com/2/oauth2/token"


def _access_token() -> Optional[str]:
    return os.getenv("X_ACCESS_TOKEN") or os.getenv("X_USER_ACCESS_TOKEN")


def refresh_access_token() -> Optional[str]:
    """Refresh OAuth 2.0 access token using refresh_token."""
    refresh = os.getenv("X_REFRESH_TOKEN")
    client_id = os.getenv("X_CLIENT_ID")
    client_secret = os.getenv("X_CLIENT_SECRET")
    if not (refresh and client_id):
        return None

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": client_id,
    }
    auth = None
    if client_secret:
        auth = (client_id, client_secret)

    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(TOKEN_URL, data=data, auth=auth)
            if r.status_code != 200:
                log.error("Token refresh failed: %s %s", r.status_code, r.text[:300])
                return None
            payload = r.json()
            new_token = payload.get("access_token")
            new_refresh = payload.get("refresh_token")
            if new_token:
                os.environ["X_ACCESS_TOKEN"] = new_token
            if new_refresh:
                os.environ["X_REFRESH_TOKEN"] = new_refresh
            return new_token
    except Exception as e:
        log.error("Token refresh error: %s", e)
        return None


def _auth_headers(token: Optional[str] = None) -> dict:
    t = token or _access_token()
    if not t:
        raise RuntimeError("X_ACCESS_TOKEN not set")
    return {
        "Authorization": f"Bearer {t}",
        "Content-Type": "application/json",
    }


def upload_image_bytes(image_bytes: bytes, media_type: str = "image/jpeg") -> Optional[str]:
    """
    Upload image via X API v2 media endpoint.
    Returns media_id string, or None on failure.
    Requires tweet.write + ideally media.write scope on the token.
    """
    token = _access_token()
    if not token:
        return None

    # v2 simple-ish upload: send base64 media in JSON (for smaller images)
    # Fallback path uses multipart if needed.
    b64 = base64.b64encode(image_bytes).decode("ascii")

    payload = {
        "media": b64,
        "media_category": "tweet_image",
        "media_type": media_type,
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            r = client.post(
                MEDIA_UPLOAD_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if r.status_code in (401, 403):
                # try refresh once
                new_t = refresh_access_token()
                if new_t:
                    r = client.post(
                        MEDIA_UPLOAD_URL,
                        headers={
                            "Authorization": f"Bearer {new_t}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )

            if r.status_code not in (200, 201):
                log.error("Media upload failed: %s %s", r.status_code, r.text[:400])
                return None

            data = r.json()
            # Response shapes vary; try common fields
            media_id = (
                data.get("data", {}).get("id")
                or data.get("data", {}).get("media_id")
                or data.get("media_id")
                or data.get("id")
            )
            if media_id is not None:
                return str(media_id)
            log.error("Media upload: no media_id in response: %s", data)
            return None
    except Exception as e:
        log.error("Media upload exception: %s", e)
        return None


def download_image(url: str) -> Optional[tuple[bytes, str]]:
    """Download image bytes from a URL (Drive proxy or external)."""
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            r = client.get(url)
            if r.status_code != 200 or len(r.content) < 500:
                return None
            ctype = r.headers.get("content-type", "image/jpeg").split(";")[0]
            if "html" in ctype:
                return None
            return r.content, ctype
    except Exception as e:
        log.error("Image download failed: %s", e)
        return None


def post_tweet(
    text: str,
    image_url: Optional[str] = None,
    *,
    base_url: Optional[str] = None,
) -> dict:
    """
    Post a tweet. Optionally attach an image from image_url.

    Returns dict:
      { success, tweet_id?, text?, error?, media_attached? }
    """
    token = _access_token()
    if not token:
        return {"success": False, "error": "X_ACCESS_TOKEN not configured"}

    media_ids = []
    media_attached = False

    if image_url:
        # Resolve relative proxy URLs against app base
        fetch_url = image_url
        if image_url.startswith("/") and base_url:
            fetch_url = base_url.rstrip("/") + image_url

        downloaded = download_image(fetch_url)
        if downloaded:
            img_bytes, ctype = downloaded
            media_id = upload_image_bytes(img_bytes, media_type=ctype or "image/jpeg")
            if media_id:
                media_ids.append(media_id)
                media_attached = True
            else:
                log.warning("Image upload failed — posting text only")
        else:
            log.warning("Could not download image from %s — posting text only", image_url)

    body: dict = {"text": text[:280]}  # hard cap
    if media_ids:
        body["media"] = {"media_ids": media_ids}

    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                f"{X_API_BASE}/tweets",
                headers=_auth_headers(token),
                json=body,
            )
            if r.status_code in (401, 403):
                new_t = refresh_access_token()
                if new_t:
                    r = client.post(
                        f"{X_API_BASE}/tweets",
                        headers=_auth_headers(new_t),
                        json=body,
                    )

            if r.status_code not in (200, 201):
                return {
                    "success": False,
                    "error": f"X API {r.status_code}: {r.text[:400]}",
                    "media_attached": media_attached,
                }

            data = r.json().get("data", {})
            return {
                "success": True,
                "tweet_id": data.get("id"),
                "text": data.get("text"),
                "media_attached": media_attached,
            }
    except Exception as e:
        return {"success": False, "error": str(e), "media_attached": media_attached}


def is_configured() -> bool:
    return bool(_access_token())
