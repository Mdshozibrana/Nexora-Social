"""Telegram Mini App login check. Every request from the Mini App carries
initData; we verify its HMAC signature with the bot token before trusting
the user id inside it (Telegram WebApp validation algorithm)."""
import hashlib
import hmac
import json
import urllib.parse


def validate_init_data(init_data: str, bot_token: str):
    """Return the Telegram user dict if the signature is valid, else None."""
    if not init_data or not bot_token:
        return None
    parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received_hash):
        return None
    try:
        return json.loads(parsed.get("user", "{}"))
    except json.JSONDecodeError:
        return None
