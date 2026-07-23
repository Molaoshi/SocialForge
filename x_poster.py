"""
Post to X (Twitter) using OAuth 2.0 user access token.

Env vars:
  X_ACCESS_TOKEN, X_REFRESH_TOKEN, X_CLIENT_ID, X_CLIENT_SECRET
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
    auth = (client_id, client_secret) if client_secret else None

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


def _normalize_media_type(ctype: str) -> str:
    ctype = (ctype or "image/jpeg").split(";")[0].strip().lower()
    mapping = {
        "image/jpg": "image/jpeg",
        "image/pjpeg": "image/jpeg",
        "image/x-png": "image/png",
    }
    return mapping.get(ctype, ctype if ctype.startswith("image/") else "image/jpeg")


def upload_image_bytes(image_bytes: bytes, media_type: str = "image/jpeg") -> tuple[Optional[str], str]:
    """
    Upload image via X API v2.
    Returns (media_id, error_message).
    Tries multipart first (most reliable), then JSON base64.
    """
    token = _access_token()
    if not token:
        return None, "X_ACCESS_TOKEN not set"

    if not image_bytes or len(image_bytes) < 100:
        return None, "Image bytes empty or too small"

    if len(image_bytes) > 5 * 1024 * 1024:
        return None, f"Image too large ({len(image_bytes)} bytes). Max 5MB."

    media_type = _normalize_media_type(media_type)
    ext = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
    }.get(media_type, "jpg")

    errors = []

    # --- Method 1: multipart/form-data (official curl style) ---
    try:
        with httpx.Client(timeout=90.0) as client:
            files = {
                "media": (f"image.{ext}", image_bytes, media_type),
            }
            data = {
                "media_category": "tweet_image",
                "media_type": media_type,
            }
            headers = {"Authorization": f"Bearer {token}"}
            r = client.post(MEDIA_UPLOAD_URL, headers=headers, data=data, files=files)

            if r.status_code in (401, 403):
                new_t = refresh_access_token()
                if new_t:
                    headers = {"Authorization": f"Bearer {new_t}"}
                    r = client.post(MEDIA_UPLOAD_URL, headers=headers, data=data, files=files)

            if r.status_code in (200, 201):
                payload = r.json()
                media_id = (
                    (payload.get("data") or {}).get("id")
                    or (payload.get("data") or {}).get("media_id")
                    or payload.get("media_id")
                    or payload.get("id")
                )
                if media_id:
                    return str(media_id), ""
                errors.append(f"multipart ok but no media_id: {str(payload)[:200]}")
            else:
                errors.append(f"multipart {r.status_code}: {r.text[:250]}")
    except Exception as e:
        errors.append(f"multipart exception: {e}")

    # --- Method 2: JSON + base64 ---
    try:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "media": b64,
            "media_category": "tweet_image",
            "media_type": media_type,
        }
        with httpx.Client(timeout=90.0) as client:
            r = client.post(
                MEDIA_UPLOAD_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if r.status_code in (401, 403):
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
            if r.status_code in (200, 201):
                body = r.json()
                media_id = (
                    (body.get("data") or {}).get("id")
                    or (body.get("data") or {}).get("media_id")
                    or body.get("media_id")
                    or body.get("id")
                )
                if media_id:
                    return str(media_id), ""
                errors.append(f"json ok but no media_id: {str(body)[:200]}")
            else:
                errors.append(f"json {r.status_code}: {r.text[:250]}")
    except Exception as e:
        errors.append(f"json exception: {e}")

    return None, " | ".join(errors)


def download_image(url: str) -> tuple[Optional[bytes], str, str]:
    """
    Download image. Returns (bytes, content_type, error).
    """
    if not url:
        return None, "", "No image URL"
    try:
        with httpx.Client(timeout=45.0, follow_redirects=True) as client:
            r = client.get(url, headers={"User-Agent": "SocialForge/0.7"})
            if r.status_code != 200:
                return None, "", f"Download HTTP {r.status_code} for {url[:80]}"
            if len(r.content) < 500:
                return None, "", f"Downloaded file too small ({len(r.content)} bytes)"
            ctype = r.headers.get("content-type", "image/jpeg").split(";")[0]
            if "html" in ctype.lower() or "text/" in ctype.lower():
                return None, "", f"Got {ctype} instead of image from {url[:80]}"
            return r.content, ctype, ""
    except Exception as e:
        return None, "", f"Download error: {e}"


def post_tweet(
    text: str,
    image_url: Optional[str] = None,
    *,
    base_url: Optional[str] = None,
) -> dict:
    """
    Post a tweet, optionally with image.
    Returns { success, tweet_id?, media_attached?, media_error?, error? }
    """
    token = _access_token()
    if not token:
        return {"success": False, "error": "X_ACCESS_TOKEN not configured"}

    media_ids = []
    media_attached = False
    media_error = ""

    if image_url:
        fetch_url = image_url
        if image_url.startswith("/") and base_url:
            fetch_url = base_url.rstrip("/") + image_url
        elif image_url.startswith("/") and not base_url:
            media_error = "APP_BASE_URL not set — cannot resolve relative image path"
            log.warning(media_error)

        if not media_error:
            img_bytes, ctype, dl_err = download_image(fetch_url)
            if dl_err:
                media_error = dl_err
                log.warning("Image download failed: %s", dl_err)
            else:
                media_id, up_err = upload_image_bytes(img_bytes, media_type=ctype or "image/jpeg")
                if media_id:
                    media_ids.append(media_id)
                    media_attached = True
                else:
                    media_error = up_err or "Media upload failed"
                    log.warning("Image upload failed: %s", media_error)

    body: dict = {"text": text[:280]}
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
                    "media_error": media_error,
                }

            data = r.json().get("data", {})
            return {
                "success": True,
                "tweet_id": data.get("id"),
                "text": data.get("text"),
                "media_attached": media_attached,
                "media_error": media_error,
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "media_attached": media_attached,
            "media_error": media_error,
        }


def is_configured() -> bool:
    return bool(_access_token())
