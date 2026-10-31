"""Shared user helpers used by both the bot and the API."""
from . import models


def get_or_create_user(db, tg_user: dict, referrer_id=None):
    """Upsert a user from a Telegram user object. Referral is recorded only
    for a genuinely new user, never for self-referral (PRD section 5)."""
    uid = int(tg_user["id"])
    user = db.get(models.User, uid)
    if user:
        user.username = tg_user.get("username") or user.username
        user.first_name = tg_user.get("first_name") or user.first_name
        db.commit()
        return user, False
    user = models.User(
        telegram_id=uid,
        username=tg_user.get("username"),
        first_name=tg_user.get("first_name", ""),
        referrer_id=referrer_id if referrer_id and referrer_id != uid else None,
    )
    db.add(user)
    db.commit()
    if user.referrer_id and db.get(models.User, user.referrer_id):
        db.add(models.Referral(referrer_id=user.referrer_id, new_user_id=uid))
        db.commit()
    return user, True
