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
