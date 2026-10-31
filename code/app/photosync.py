"""Fetch a member's Telegram profile photo (as a file_id) via the Bot
API, so profiles can show the real picture through the /media proxy.
Needs the live bot token; without one it quietly returns None."""
import httpx

from .config import settings


async def fetch_telegram_photo_file_id(telegram_id: int):
    if not settings.BOT_TOKEN:
        return None
    api = f"https://api.telegram.org/bot{settings.BOT_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                f"{api}/getUserProfilePhotos",
                params={"user_id": telegram_id, "limit": 1})
        data = r.json()
        photos = (data.get("result") or {}).get("photos") or []
        if photos and photos[0]:
            return photos[0][-1]["file_id"]  # largest size, newest photo
    except Exception:
        return None
    return None
