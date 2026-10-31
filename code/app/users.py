"""Shared user helpers used by both the bot and the API."""
from . import models
from .config import OFFICIAL_ID, OFFICIAL_NAME, OFFICIAL_USERNAME

WELCOME_POST = (
    "Welcome to Nexora Social! This is the official account — follow for updates, "
    "tips and announcements. Post your first photo or video, complete "
    "daily tasks, and grow with the community. #nexora"
)


def ensure_official(db):
    """The platform's official account (owner request, Oct 31): a system
    user with a verified mark that every member follows. Created once,
    with a welcome post so Following feeds are never empty."""
    official = db.get(models.User, OFFICIAL_ID)
    if official is None:
        official = models.User(
            telegram_id=OFFICIAL_ID, username=OFFICIAL_USERNAME,
            first_name=OFFICIAL_NAME, is_verified=True,
            bio="Official Nexora Social account — updates, tips and announcements.")
        db.add(official)
        db.commit()
        from .services import register_post
        register_post(db, official, "text", None, WELCOME_POST)
    return official


def _follow_official(db, user):
    """Every member follows the official account — new users at signup,
    existing users on their next visit (backfill)."""
    if user.telegram_id == OFFICIAL_ID:
        return
    official = ensure_official(db)
    exists = db.query(models.Follow).filter_by(
        follower_id=user.telegram_id,
        following_id=official.telegram_id).first()
    if exists is None:
        db.add(models.Follow(follower_id=user.telegram_id,
                             following_id=official.telegram_id))
        db.commit()


def get_or_create_user(db, tg_user: dict, referrer_id=None):
    """Upsert a user from a Telegram user object. Referral is recorded only
    for a genuinely new user, never for self-referral (PRD section 5)."""
    uid = int(tg_user["id"])
    user = db.get(models.User, uid)
    if user:
        user.username = tg_user.get("username") or user.username
        user.first_name = tg_user.get("first_name") or user.first_name
        db.commit()
        _follow_official(db, user)
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
    _follow_official(db, user)
    return user, True
