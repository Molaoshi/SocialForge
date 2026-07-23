"""
Post to X using OAuth 2.0 (text) + OAuth 1.0a (media when available).

Env:
  OAuth 2.0: X_ACCESS_TOKEN, X_REFRESH_TOKEN, X_CLIENT_ID, X_CLIENT_SECRET
  OAuth 1.0a (for images): X_API_KEY, X_API_KEY_SECRET (or X_API_SECRET),
                           X_ACCESS_TOKEN_OAUTH1, X_ACCESS_TOKEN_SECRET
                           (or X_ACCESS_TOKEN_SECRET alone with OAuth1 user tokens)
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
MEDIA_UPLOAD_V2 = "https://api.x.com/2/media/upload"
MEDIA_UPLOAD_V11 = "https://upload.twitter.com/1.1/media/upload.json"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
TOKEN_FILE = Path(__file__).parent / "data" / "x_tokens.json"


def _load_persisted_tokens() -> None:
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


_load_persisted_tokens()


def _access_token() -> Optional[str]:
    return os.getenv("X_ACCESS_TOKEN") or os.getenv("X_USER_ACCESS_TOKEN")


def _api_key() -> Optional[str]:
    return os.getenv("X_API_KEY") or os.getenv("X_CONSUMER_KEY")


def _api_secret() -> Optional[str]:
    return (
        os.getenv("X_API_KEY_SECRET")
        or os.getenv("X_API_SECRET")
        or os.getenv("X_CONSUMER_SECRET")
    )


def _oauth1_access_token() -> Optional[str]:
    return os.getenv("X_ACCESS_TOKEN_OAUTH1") or os.getenv("X_OAUTH1_ACCESS_TOKEN")


def _oauth1_access_secret() -> Optional[str]:
    return (
        os.getenv("X_ACCESS_TOKEN_SECRET")
        or os.getenv("X_OAUTH1_ACCESS_TOKEN_SECRET")
        or os.getenv("X_ACCESS_TOKEN_S")
    )


def oauth1_media_ready() -> bool:
    return bool(_api_key() and _api_secret() and _oauth1_access_token() and _oauth1_access_secret())


def refresh_access_token() -> tuple[Optional[str], str]:
    refresh = os.getenv("X_REFRESH_TOKEN")
    client_id = os.getenv("X_CLIENT_ID")
    client_secret = os.getenv("X_CLIENT_SECRET")

    if not refresh:
        return None, "X_REFRESH_TOKEN not set"
    if not client_id:
        return None, "X_CLIENT_ID not set"

    errors = []

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
                    data={"grant_type": "refresh_token", "refresh_token": refresh},
                )
                if r.status_code == 200:
                    payload = r.json()
                    new_access = payload.get("access_token")
                    new_refresh = payload.get("refresh_token")
                    if new_access:
                        _persist_tokens(new_access, new_refresh)
                        return new_access, ""
                    errors.append("confidential: 200 but no access_token")
                else:
                    errors.append(f"confidential {r.status_code}: {r.text[:200]}")
        except Exception as e:
            errors.append(f"confidential exception: {e}")

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
                    return new_access, ""
                errors.append("public: 200 but no access_token")
            else:
                errors.append(f"public {r.status_code}: {r.text[:200]}")
    except Exception as e:
        errors.append(f"public exception: {e}")

    return None, " | ".join(errors)


def ensure_access_token() -> tuple[Optional[str], str]:
    token = _access_token()
    if not token:
        new_t, err = refresh_access_token()
        if new_t:
            return new_t, ""
        return None, err or "No X_ACCESS_TOKEN"
    return token, ""


def _auth_headers(token: Optional[str] = None) -> dict:
    t = token or _access_token()
    if not t:
        raise RuntimeError("X_ACCESS_TOKEN not set")
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


def _normalize_media_type(ctype: str) -> str:
    ctype = (ctype or "image/jpeg").split(";")[0].strip().lower()
    mapping = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg", "image/x-png": "image/png"}
    return mapping.get(ctype, ctype if ctype.startswith("image/") else "image/jpeg")


def _upload_oauth1_v11(image_bytes: bytes) -> tuple[Optional[str], str]:
    """Upload via legacy v1.1 endpoint with OAuth 1.0a user context."""
    if not oauth1_media_ready():
        return None, "OAuth1 not configured (need X_API_KEY, X_API_KEY_SECRET, X_ACCESS_TOKEN_OAUTH1, X_ACCESS_TOKEN_SECRET)"

    try:
        from requests_oauthlib import OAuth1Session

        session = OAuth1Session(
            client_key=_api_key(),
            client_secret=_api_secret(),
            resource_owner_key=_oauth1_access_token(),
            resource_owner_secret=_oauth1_access_secret(),
        )
        r = session.post(
            MEDIA_UPLOAD_V11,
            files={"media": image_bytes},
            timeout=90,
        )
        if r.status_code not in (200, 201):
            return None, f"oauth1/v1.1 {r.status_code}: {r.text[:250]}"
        data = r.json()
        media_id = data.get("media_id_string") or data.get("media_id")
        if media_id:
            return str(media_id), ""
        return None, f"oauth1/v1.1 no media_id: {str(data)[:200]}"
    except Exception as e:
        return None, f"oauth1/v1.1 exception: {e}"


def _upload_oauth2_v2(image_bytes: bytes, media_type: str, token: str) -> tuple[Optional[str], str]:
    media_type = _normalize_media_type(media_type)
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(media_type, "jpg")
    errors = []

    try:
        with httpx.Client(timeout=90.0) as client:
            files = {"media": (f"image.{ext}", image_bytes, media_type)}
            data = {"media_category": "tweet_image", "media_type": media_type}
            headers = {"Authorization": f"Bearer {token}"}
            r = client.post(MEDIA_UPLOAD_V2, headers=headers, data=data, files=files)
            if r.status_code in (401, 403):
                new_t, _ = refresh_access_token()
                if new_t:
                    headers = {"Authorization": f"Bearer {new_t}"}
                    r = client.post(MEDIA_UPLOAD_V2, headers=headers, data=data, files=files)
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

    try:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        payload = {"media": b64, "media_category": "tweet_image", "media_type": media_type}
        with httpx.Client(timeout=90.0) as client:
            r = client.post(
                MEDIA_UPLOAD_V2,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )
            if r.status_code in (401, 403):
                new_t, _ = refresh_access_token()
                if new_t:
                    r = client.post(
                        MEDIA_UPLOAD_V2,
                        headers={"Authorization": f"Bearer {new_t}", "Content-Type": "application/json"},
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


def upload_image_bytes(image_bytes: bytes, media_type: str = "image/jpeg") -> tuple[Optional[str], str]:
    if not image_bytes or len(image_bytes) < 100:
        return None, "Image bytes empty or too small"
    if len(image_bytes) > 5 * 1024 * 1024:
        return None, f"Image too large ({len(image_bytes)} bytes). Max 5MB."

    errors = []

    # 1) OAuth 1.0a v1.1 (best chance for accounts without media.write)
    if oauth1_media_ready():
        mid, err = _upload_oauth1_v11(image_bytes)
        if mid:
            return mid, ""
        errors.append(err)
    else:
        errors.append("oauth1 skipped (missing X_ACCESS_TOKEN_OAUTH1 / X_ACCESS_TOKEN_SECRET)")

    # 2) OAuth 2.0 v2
    token, tok_err = ensure_access_token()
    if token:
        mid, err = _upload_oauth2_v2(image_bytes, media_type, token)
        if mid:
            return mid, ""
        errors.append(err)
    else:
        errors.append(tok_err or "no oauth2 token")

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
            r = client.post(f"{X_API_BASE}/tweets", headers=_auth_headers(token), json=body)

            if r.status_code in (401, 403) and "duplicate" not in r.text.lower():
                new_t, refresh_err = refresh_access_token()
                if new_t:
                    r = client.post(f"{X_API_BASE}/tweets", headers=_auth_headers(new_t), json=body)
                elif r.status_code == 401:
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
