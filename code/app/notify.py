"""Bot notifications (PRD section 4, MVP item 7).
Sends go through the Bot API directly with httpx. The bot token is used
only in server-side requests. Every send is written to notifications_log,
and a per-user hourly cap keeps the bot from spamming (Telegram can ban
bots that message too aggressively)."""
import httpx

from . import models
from .config import settings
from datetime import datetime, timedelta

MAX_PER_HOUR = 20


async def send_message(chat_id: int, text: str) -> bool:
    """One Bot API sendMessage. False (never raises) when there is no live
    token or Telegram rejects the send (e.g. the user blocked the bot)."""
    if not settings.BOT_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, json={"chat_id": chat_id, "text": text})
        return r.status_code == 200
    except httpx.HTTPError:
        return False


async def notify_user(db, user_id: int, ntype: str, text: str) -> bool:
    """Send + log a notification, respecting the hourly cap."""
    if user_id is None:
        return False
    since = datetime.utcnow() - timedelta(hours=1)
    recent = db.query(models.NotificationLog).filter(
        models.NotificationLog.user_id == user_id,
        models.NotificationLog.sent_at >= since).count()
    if recent >= MAX_PER_HOUR:
        return False
    sent = await send_message(user_id, text)
    if sent:
        db.add(models.NotificationLog(user_id=user_id, type=ntype))
        db.commit()
    return sent
