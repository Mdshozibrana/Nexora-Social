"""Bot notifications (PRD section 4, MVP item 7).
Sends go through the Bot API directly with httpx. The bot token is used
only in server-side requests. Every send is written to notifications_log,
and a per-user hourly cap keeps the bot from spamming (Telegram can ban
bots that message too aggressively)."""
import httpx
import json

from . import models
from .config import OFFICIAL_ID, settings
from datetime import datetime, timedelta

MAX_PER_HOUR = 20
# Phase 144: per-member notification preferences (Settings page).
# Keys are the toggles; every key defaults ON — a missing key, or
# no prefs at all, means the member never changed it, so today's
# behaviour is preserved for everyone until they opt out.
# Phase 151: blood requests + donor answers (8th toggle).
NOTIF_PREF_KEYS = ("likes", "comments", "follows", "follow_requests",
                   "tips", "messages", "system", "blood", "skills")
# Which pref key gates each notification type the app actually
# creates. "mention" is deliberately absent: no code path ever
# creates a mention notification, so there is nothing to toggle.
# "broadcast" is the admin announcement (NotificationLog only).
NOTIF_TYPE_MAP = {
    "like": "likes", "repost": "likes", "share": "likes",
    "comment": "comments", "reply": "comments",
    "follow": "follows", "follow_request": "follow_requests",
    "tip": "tips", "message": "messages",
    "payout": "system", "verification": "system",
    "post_live": "system", "announcement": "system",
    "broadcast": "system",
    # Phase 151: blood-request alerts + donor answers.
    "blood_request": "blood", "blood_respond": "blood",
    # Phase 158: skill-swap connect (9th toggle).
    "skill_connect": "skills",
}


def _load_prefs(db, user_id):
    """The member's saved prefs as key -> bool (missing keys read
    as True). Anything unreadable means all ON."""
    try:
        user = db.get(models.User, user_id) if user_id else None
    except Exception:
        return {}
    raw = getattr(user, "notif_prefs", None) if user else None
    if not raw:
        return {}
    try:
        saved = json.loads(raw)
    except Exception:
        return {}
    return saved if isinstance(saved, dict) else {}


def notif_allowed(db, user_id, ntype):
    """True when the member wants this notification type. Unknown
    types default to allowed — a new type must never silently
    disappear because the map forgot it."""
    key = NOTIF_TYPE_MAP.get(ntype)
    if key is None:
        return True
    prefs = _load_prefs(db, user_id)
    val = prefs.get(key, True)
    return bool(val) if isinstance(val, bool) else True



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


async def send_document(chat_id: int, filename: str, data: bytes,
                        caption: str = "") -> bool:
    """One Bot API sendDocument (Phase 100: the data-export file).
    False (never raises) when there is no live token or Telegram
    rejects the send (e.g. the user blocked the bot)."""
    if not settings.BOT_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendDocument"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                url, data={"chat_id": str(chat_id), "caption": caption},
                files={"document": (filename, data, "application/json")})
        return r.status_code == 200
    except httpx.HTTPError:
        return False


async def notify_user(db, user_id: int, ntype: str, text: str) -> bool:
    """Send + log a notification, respecting the hourly cap."""
    if user_id is None:
        return False
    # Phase 144: the recipient opted this type out.
    if not notif_allowed(db, user_id, ntype):
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


def record(db, user_id, ntype, actor_id=None, post_id=None, text=""):
    """Write an in-app notification row (Phase 20, the 🔔 list). Kept
    separate from the DM path: the list is not hourly-capped, and a
    member who blocked the bot still sees their in-app list. Self
    actions and the official system account never get rows."""
    if not user_id or user_id == actor_id or user_id == OFFICIAL_ID:
        return
    # Phase 144: the recipient opted this type out.
    if not notif_allowed(db, user_id, ntype):
        return
    db.add(models.Notification(
        user_id=user_id, actor_id=actor_id, type=ntype,
        post_id=post_id, text=text or ""))
    db.commit()
