"""Shared user helpers used by both the bot and the API."""
from . import models
from .config import OFFICIAL_ID, OFFICIAL_NAME, OFFICIAL_USERNAME, settings

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
        # Phase 60: never let a stray "@" into the stored
        # username (renders add their own @).
        user.username = (tg_user.get("username") or "").lstrip("@") \
            or user.username
        # Phase 42: an in-app name edit (by the member or an
        # admin) wins over this Telegram sync — name_changed_at
        # marks the name as app-managed; without the guard, an
        # edited name snapped back to the Telegram name at the
        # next /auth and the 60-day rule could never hold.
        if user.name_changed_at is None:
            user.first_name = tg_user.get("first_name") or user.first_name
        if tg_user.get("language_code"):
            user.language_code = tg_user["language_code"]
        # Admins (the owner) always carry the verified mark.
        if uid in settings.ADMIN_IDS and not user.is_verified:
            user.is_verified = True
        db.commit()
        _follow_official(db, user)
        return user, False
    user = models.User(
        telegram_id=uid,
        username=(tg_user.get("username") or "").lstrip("@") or None,
        first_name=tg_user.get("first_name", ""),
        language_code=tg_user.get("language_code"),
        is_verified=uid in settings.ADMIN_IDS,
        referrer_id=referrer_id if referrer_id and referrer_id != uid else None,
    )
    db.add(user)
    db.commit()
    if user.referrer_id and db.get(models.User, user.referrer_id):
        db.add(models.Referral(referrer_id=user.referrer_id, new_user_id=uid))
        db.commit()
    _follow_official(db, user)
    return user, True
