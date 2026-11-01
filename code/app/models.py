"""Database tables — PRD section 6. Media is stored on Telegram's own
servers; only the file_id lives here (PRD section 7)."""
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Integer,
    String, Text, UniqueConstraint,
)

from .db import Base


class User(Base):
    __tablename__ = "users"
    telegram_id = Column(BigInteger, primary_key=True)
    username = Column(String(64), nullable=True, index=True)
    first_name = Column(String(128), default="")
    photo_file_id = Column(String(256), nullable=True)
    bio = Column(Text, default="")
    points_balance = Column(Integer, default=0)
    referrer_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True)
    is_banned = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=False)
    # Phase 19 (admin dashboard): Telegram gives the member's language;
    # the country is approximated once from their IP at sign-in (geoip).
    country = Column(String(64), nullable=True)
    language_code = Column(String(16), nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    # Phase 20: accounts the owner creates and operates from the Admin
    # Panel (managed/test members). Only admins can create them or act
    # as them; they are tagged in admin lists.
    is_managed = Column(Boolean, default=False)
    # Phase 28: auth revocation. When set, initData issued BEFORE this
    # moment is rejected — the member must reopen the app (Telegram
    # issues fresh initData), which kills any leaked string without
    # banning the account (security §1/§14).
    auth_revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    type = Column(String(16), default="text")  # photo | video | text
    media_file_id = Column(String(256), nullable=True)
    caption = Column(Text, default="")
    hashtags = Column(String(512), default="")
    like_count = Column(Integer, default=0)
    comment_count = Column(Integer, default=0)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Like(Base):
    __tablename__ = "likes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, ForeignKey("posts.id"), index=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("post_id", "user_id"),)


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, ForeignKey("posts.id"), index=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    text = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class Follow(Base):
    __tablename__ = "follows"
    id = Column(Integer, primary_key=True, autoincrement=True)
    follower_id = Column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    following_id = Column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("follower_id", "following_id"),)


class Referral(Base):
    __tablename__ = "referrals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    referrer_id = Column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    new_user_id = Column(BigInteger, ForeignKey("users.telegram_id"), unique=True)
    qualified = Column(Boolean, default=False)  # True after first post (PRD s.5)
    created_at = Column(DateTime, default=datetime.utcnow)


class PointsLedger(Base):
    __tablename__ = "points_ledger"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    amount = Column(Integer)  # + earn / - spend
    reason = Column(String(64))
    ref_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, ForeignKey("posts.id"), index=True)
    reporter_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    reason = Column(String(256), default="")
    status = Column(String(16), default="open")
    created_at = Column(DateTime, default=datetime.utcnow)


class NotificationLog(Base):
    __tablename__ = "notifications_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    type = Column(String(32))
    sent_at = Column(DateTime, default=datetime.utcnow)


class SavedPost(Base):
    """A bookmark: posts/videos a user saved from the options menu
    (owner request, Oct 31). Listed under /me/saved."""
    __tablename__ = "saved_posts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, ForeignKey("posts.id"), index=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("post_id", "user_id"),)


class PostShare(Base):
    """In-app share: one member sends a post/video to another member
    (owner request, Oct 31). The receiver finds it under 'Shared with me'
    and also gets a bot notification."""
    __tablename__ = "post_shares"
    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, ForeignKey("posts.id"), index=True)
    from_user_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    to_user_id = Column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DailyClaim(Base):
    """One row per user per daily task per day — the once-a-day guard for
    the daily-tasks points (owner request, Oct 31)."""
    __tablename__ = "daily_claims"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    task_key = Column(String(32))
    day = Column(String(10))  # ISO date, UTC — the day the reward was claimed
    claimed_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("user_id", "task_key", "day"),)


class UserActivity(Base):
    """Per-member, per-day app usage (Phase 19, admin dashboard). The
    Mini App sends a heartbeat every ~30s while it is open; each beat
    adds the elapsed seconds since the previous beat (capped), so
    `seconds` is real time-in-app and `sessions` counts separate
    visits (a beat after a >2-minute gap starts a new session)."""
    __tablename__ = "user_activity"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    day = Column(String(10))  # ISO date, UTC
    seconds = Column(Integer, default=0)
    sessions = Column(Integer, default=0)
    last_beat_at = Column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("user_id", "day"),)


class AdEvent(Base):
    """One row per ad actually shown to a member (Phase 19). The Mini
    App reports back when the AdsGram interstitial finishes showing,
    so the dashboard can count real impressions."""
    __tablename__ = "ad_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Notification(Base):
    """In-app notification (Phase 20). Until now members only heard
    about likes/comments/follows as bot DMs; this table powers the
    🔔 list inside the app. `text` carries system messages (video
    live, announcements); social rows resolve the actor at read time."""
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    actor_id = Column(BigInteger, nullable=True)
    type = Column(String(32))  # like | comment | follow | share |
                               # post_live | announcement
    post_id = Column(Integer, nullable=True)
    text = Column(String(256), default="")
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class VerificationRequest(Base):
    """Blue-tick application (Phase 22). A member with at least
    VERIFICATION_MIN_FOLLOWERS followers may apply; the admin approves
    or rejects from the Admin Panel. Approval sets users.is_verified.
    Only one pending request per member at a time; a rejected member
    may apply again."""
    __tablename__ = "verification_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"),
                     index=True, nullable=False)
    status = Column(String(16), default="pending", nullable=False)
    # pending | approved | rejected
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    decided_at = Column(DateTime, nullable=True)
    decided_by = Column(BigInteger, nullable=True)


class Design(Base):
    """Design gallery entry (Phase 25). Posted ONLY as the official
    account (the admin acting as @nexora); the design's prompt is
    its caption. Members browse the Pinterest-style gallery and
    like designs; posting is official-only by design."""
    __tablename__ = "designs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    image_file_id = Column(String(256), nullable=False)
    prompt = Column(Text, default="")
    like_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class DesignLike(Base):
    __tablename__ = "design_likes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    design_id = Column(Integer, ForeignKey("designs.id"), index=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("design_id", "user_id"),)


class AdminAuditLog(Base):
    """Phase 28 (security §10/§13): every privileged action leaves a
    record — which admin, what action, on whom, when. Rows are only
    ever appended by the admin endpoints; nothing in the app updates
    or deletes them."""
    __tablename__ = "admin_audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_id = Column(BigInteger, index=True, nullable=False)
    action = Column(String(64), nullable=False)
    target_id = Column(BigInteger, nullable=True)
    detail = Column(String(512), default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
