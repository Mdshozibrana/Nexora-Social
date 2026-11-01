"""Telegram Mini App login check. Every request from the Mini App carries
initData; we verify its HMAC signature with the bot token before trusting
the user id inside it (Telegram WebApp validation algorithm).

Phase 28 (security §1): the signature alone is not enough — a captured
initData string would otherwise work forever. Validation now also
enforces freshness: auth_date must be no older than
INITDATA_MAX_AGE_SECONDS (default 24h; Telegram issues fresh initData
at every app open) and not from the future beyond a small clock skew.
That bounds the replay window of any leaked string."""
import hashlib
import hmac
import json
import time
import urllib.parse

_MAX_SKEW_SECONDS = 300


def _parse(init_data: str):
    if not init_data:
        return {}
    return dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))


def init_data_auth_date(init_data: str):
    """The auth_date of an initData string as an int, or None. Only
    meaningful for a string whose signature already validated."""
    raw = _parse(init_data).get("auth_date")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def validate_init_data(init_data: str, bot_token: str, max_age=None):
    """Return the Telegram user dict if the signature is valid AND the
    data is fresh, else None."""
    if not init_data or not bot_token:
        return None
    parsed = _parse(init_data)
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received_hash):
        return None
    # Freshness (Phase 28): reject expired or future-dated auth data.
    if max_age is None:
        from .config import settings
        max_age = settings.INITDATA_MAX_AGE_SECONDS
    auth_date = init_data_auth_date(init_data)
    if auth_date is None:
        return None
    now = int(time.time())
    if auth_date > now + _MAX_SKEW_SECONDS:
        return None
    if max_age and now - auth_date > max_age:
        return None
    try:
        return json.loads(parsed.get("user", "{}"))
    except json.JSONDecodeError:
        return None
