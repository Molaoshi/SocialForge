"""
Post to X using OAuth 2.0 user access token + automatic refresh.

Required env:
  X_ACCESS_TOKEN, X_REFRESH_TOKEN, X_CLIENT_ID, X_CLIENT_SECRET
"""
from __future__ import annotations

import os
import json
import base64
import logging
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger("x_poster")

X_API_BASE = "https://api.x.com/2"
MEDIA_UPLOAD_URL = "https://api.x.com/2/media/upload"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
TOKEN_FILE = Path(__file__).parent / "data" / "x_tokens.json"


def _load_persisted_tokens() -> None:
    """Load last refreshed tokens from disk into env (survives within same deploy)."""
    try:
        if TOKEN_FILE.exists():
            data = json.loads(TOKEN_FILE.read_text())
            if data.get("access_token"):
                os.environ["X_ACCESS_TOKEN"] = data["access_token"]
            if data.get("refresh_token"):
                os.environ["X_REFRESH_TOKEN"] = data["refresh_token"]
    except Exception as e:
        log.warning("Could not load persisted tokens: %s", e)


def _persist_tokens(access: Optional[str], refresh: Optional[str]) -> None:
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing = {}
        if TOKEN_FILE.exists():
            try:
                existing = json.loads(TOKEN_FILE.read_text())
            except Exception:
                existing = {}
        if access:
            existing["access_token"] = access
            os.environ["X_ACCESS_TOKEN"] = access
        if refresh:
            existing["refresh_token"] = refresh
            os.environ["X_REFRESH_TOKEN"] = refresh
        TOKEN_FILE.write_text(json.dumps(existing))
    except Exception as e:
        log.warning("Could not persist tokens: %s", e)
        if access:
            os.environ["X_ACCESS_TOKEN"] = access
        if refresh:
            os.environ["X_REFRESH_TOKEN"] = refresh


# Load any previously refreshed tokens on import
_load_persisted_tokens()


def _access_token() -> Optional[str]:
    return os.getenv("X_ACCESS_TOKEN") or os.getenv("X_USER_ACCESS_TOKEN")


def refresh_access_token() -> tuple[Optional[str], str]:
    """
    Refresh OAuth 2.0 access token.
    Tries confidential client (Basic auth) then public client (client_id in body).
    Returns (new_access_token, error_message).
    """
    refresh = os.getenv("X_REFRESH_TOKEN")
    client_id = os.getenv("X_CLIENT_ID")
    client_secret = os.getenv("X_CLIENT_SECRET")

    if not refresh:
        return None, "X_REFRESH_TOKEN not set"
    if not client_id:
        return None, "X_CLIENT_ID not set"

    errors = []

    # --- Confidential client: Basic auth, no client_id in body ---
    if client_secret:
        try:
            basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            with httpx.Client(timeout=20.0) as client:
                r = client.post(
                    TOKEN_URL,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Authorization": f"Basic {basic}",
                    },
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh,
                    },
                )
                if r.status_code == 200:
                    payload = r.json()
                    new_access = payload.get("access_token")
                    new_refresh = payload.get("refresh_token")
                    if new_access:
                        _persist_tokens(new_access, new_refresh)
                        log.info("Token refreshed (confidential client)")
                        return new_access, ""
                    errors.append("confidential: 200 but no access_token")
                else:
                    errors.append(f"confidential {r.status_code}: {r.text[:200]}")
        except Exception as e:
            errors.append(f"confidential exception: {e}")

    # --- Public client: client_id in body ---
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(
                TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh,
                    "client_id": client_id,
                },
            )
            if r.status_code == 200:
                payload = r.json()
                new_access = payload.get("access_token")
                new_refresh = payload.get("refresh_token")
                if new_access:
                    _persist_tokens(new_access, new_refresh)
                    log.info("Token refreshed (public client)")
                    return new_access, ""
                errors.append("public: 200 but no access_token")
            else:
                errors.append(f"public {r.status_code}: {r.text[:200]}")
    except Exception as e:
        errors.append(f"public exception: {e}")

    return None, " | ".join(errors)


def ensure_access_token() -> tuple[Optional[str], str]:
    """
    Return a usable access token. On failure, try refresh first.
    """
    token = _access_token()
    if not token:
        # try refresh from refresh_token alone
        new_t, err = refresh_access_token()
        if new_t:
            return new_t, ""
        return None, err or "No X_ACCESS_TOKEN"
    return token, ""


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
    token, tok_err = ensure_access_token()
    if not token:
        return None, tok_err or "No access token"

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

    # Multipart (preferred)
    try:
        with httpx.Client(timeout=90.0) as client:
            files = {"media": (f"image.{ext}", image_bytes, media_type)}
            data = {"media_category": "tweet_image", "media_type": media_type}
            headers = {"Authorization": f"Bearer {token}"}
            r = client.post(MEDIA_UPLOAD_URL, headers=headers, data=data, files=files)

            if r.status_code in (401, 403):
                new_t, _ = refresh_access_token()
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

    # JSON base64 fallback
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
                new_t, _ = refresh_access_token()
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
    # Always ensure we have a fresh-enough token
    token, tok_err = ensure_access_token()
    if not token:
        return {"success": False, "error": f"Auth failed: {tok_err}"}

    media_ids = []
    media_attached = False
    media_error = ""

    if image_url:
        fetch_url = image_url
        if image_url.startswith("/") and base_url:
            fetch_url = base_url.rstrip("/") + image_url
        elif image_url.startswith("/") and not base_url:
            media_error = "APP_BASE_URL not set — cannot resolve relative image path"

        if not media_error:
            img_bytes, ctype, dl_err = download_image(fetch_url)
            if dl_err:
                media_error = dl_err
            else:
                media_id, up_err = upload_image_bytes(img_bytes, media_type=ctype or "image/jpeg")
                if media_id:
                    media_ids.append(media_id)
                    media_attached = True
                else:
                    media_error = up_err or "Media upload failed"

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

            # Token expired mid-request → refresh and retry once
            if r.status_code in (401, 403):
                new_t, refresh_err = refresh_access_token()
                if new_t:
                    r = client.post(
                        f"{X_API_BASE}/tweets",
                        headers=_auth_headers(new_t),
                        json=body,
                    )
                else:
                    return {
                        "success": False,
                        "error": f"X API {r.status_code}: token expired and refresh failed: {refresh_err}",
                        "media_attached": media_attached,
                        "media_error": media_error,
                    }

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
    return bool(_access_token() or os.getenv("X_REFRESH_TOKEN"))
