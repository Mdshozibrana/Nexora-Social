"""Database tables — PRD section 6. Media is stored on Telegram's own
servers; only the file_id lives here (PRD section 7)."""
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Integer,
    String, Text, UniqueConstraint,
)

from .db import Base


class User(Base):
    __tablename__ = "users"
    telegram_id = Column(BigInteger, primary_key=True)
    username = Column(String(64), nullable=True, index=True)
    first_name = Column(String(128), default="")
    photo_file_id = Column(String(256), nullable=True)
    cover_file_id = Column(String(256), nullable=True)
    name_changed_at = Column(DateTime, nullable=True)
    bio = Column(Text, default="")
    points_balance = Column(Integer, default=0)
    referrer_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=True)
    is_banned = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=False)
    # Phase 136: private account — only approved followers see
    # this member's posts (follow requests, not instant follows).
    is_private = Column(Boolean, default=False)
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
    # Phase 78 (Nearby): opt-in live location sharing. Coordinates
    # exist only while sharing is on; turning it off clears them.
    share_location = Column(Boolean, default=False)
    # Phase 96: the member's own Theme Colours picks, stored per
    # ACCOUNT as JSON ({"bg": ..., "card": ..., "accent": ...}) so a
    # theme change touches only that member — never anyone else.
    theme = Column(String(256), nullable=True)
    # Phase 127: crypto payout wallet — the network (TON / Gram /
    # USDT) and address the member is paid at. Set from the
    # Monetization card; the admin never edits it for them.
    wallet_address = Column(String(256), nullable=True)
    wallet_network = Column(String(16), nullable=True)
    # Phase 144: notification preferences — per-type on/off,
    # stored as JSON ({"likes": false, ...}) on the member's
    # own row, same pattern as the per-account theme. NULL (or
    # a missing key) means ON, so every existing member keeps
    # today's behaviour until they change it. One column, no
    # new table — backup was 42 tables at Phase 144.
    notif_prefs = Column(Text, nullable=True)
    # Phase 151: blood donation — opt-in only. blood_group is
    # health-adjacent, so it is NULL until the member chooses
    # one, and blood_donor stays False until they opt in; the
    # directory and the profile badge read these two columns.
    blood_group = Column(String(3), nullable=True)
    blood_donor = Column(Boolean, default=False)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    loc_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    type = Column(String(16), default="text")  # photo | video | text
    media_file_id = Column(String(256), nullable=True)
    # Phase 51: Telegram's own thumbnail for a video post — the
    # feed/profile player shows it as the preview (poster) frame.
    thumb_file_id = Column(String(256), nullable=True)
    caption = Column(Text, default="")
    hashtags = Column(String(512), default="")
    like_count = Column(Integer, default=0)
    comment_count = Column(Integer, default=0)
    # Phase 118: a repost is a Post row of type "repost"
    # pointing at the original; it carries no media itself.
    repost_of_id = Column(Integer, ForeignKey("posts.id"),
                        nullable=True)
    repost_count = Column(Integer, default=0)
    # Phase 123: creator tools — one pinned post per author.
    is_pinned = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    # Phase 167/168: written in the Nexora Inbox page's own box.
    # Phase 169 removed the page; the column is retained (unused)
    # so old posts keep their flag — never drop it.
    via_inbox = Column(Boolean, default=False)
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
    # Phase 118: a reply points at its parent comment;
    # top-level comments have parent_id NULL (one level only).
    parent_id = Column(Integer, ForeignKey("comments.id"),
                       nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Mention(Base):
    """Phase 170: @username mentions — one row per mentioned member
    per post or comment (never both columns set). Rows are the
    render source for tappable mention links and the dedupe record
    for notifications (a re-edit notifies only NEW mentions)."""
    __tablename__ = "mentions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=True,
                     index=True)
    comment_id = Column(Integer, ForeignKey("comments.id"),
                        nullable=True, index=True)
    mentioned_id = Column(BigInteger,
                          ForeignKey("users.telegram_id"), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PostMedia(Base):
    """Phase 171: album items — one row per photo in a multi-photo
    post, in position order. Single-media posts keep using
    posts.media_file_id; the first album item is ALSO stored there,
    so every existing reader (feed, /media, insights, search)
    keeps working without changes."""
    __tablename__ = "post_media"
    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, ForeignKey("posts.id"), index=True)
    file_id = Column(String(256), nullable=False)
    media_type = Column(String(16), default="photo")
    position = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Draft(Base):
    """Phase 123: an unfinished post, saved from the composer and
    finished later — text plus an optional already-uploaded media
    reference. Publishing it goes through the normal post path
    (points included) and deletes the draft."""
    __tablename__ = "drafts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"),
                     index=True)
    text = Column(Text, default="")
    media_file_id = Column(String(256), nullable=True)
    media_type = Column(String(16), nullable=True)  # photo | video
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class CommentLike(Base):
    """Phase 123: a like on one comment (toggle)."""
    __tablename__ = "comment_likes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    comment_id = Column(Integer, ForeignKey("comments.id"), index=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("comment_id", "user_id"),)


class Poll(Base):
    """Phase 123: a post's poll — one per post, question + 2-4
    options. Members vote once; a vote is final."""
    __tablename__ = "polls"
    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, ForeignKey("posts.id"), unique=True,
                     index=True)
    question = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class PollOption(Base):
    __tablename__ = "poll_options"
    id = Column(Integer, primary_key=True, autoincrement=True)
    poll_id = Column(Integer, ForeignKey("polls.id"), index=True)
    text = Column(String(100), default="")
    position = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class PollVote(Base):
    """One vote per member per poll — the (poll_id, user_id)
    unique pair enforces it; option_id says what they picked."""
    __tablename__ = "poll_votes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    poll_id = Column(Integer, ForeignKey("polls.id"), index=True)
    option_id = Column(Integer, ForeignKey("poll_options.id"),
                       index=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("poll_id", "user_id"),)


class Follow(Base):
    __tablename__ = "follows"
    id = Column(Integer, primary_key=True, autoincrement=True)
    follower_id = Column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    following_id = Column(BigInteger, ForeignKey("users.telegram_id"), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("follower_id", "following_id"),)


class FollowRequest(Base):
    """Phase 136: a request to follow a private account. One
    pending row per (requester, target) at a time — the target
    accepts (a follow row appears) or rejects (nothing does).
    After a decision a fresh request is a new row."""
    __tablename__ = "follow_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    requester_id = Column(BigInteger, ForeignKey("users.telegram_id"),
                          index=True, nullable=False)
    target_id = Column(BigInteger, ForeignKey("users.telegram_id"),
                       index=True, nullable=False)
    status = Column(String(16), default="pending", nullable=False)
    # pending | accepted | rejected
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("requester_id", "target_id",
                                       "status"),)


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


class AppSetting(Base):
    """Tiny key-value store for owner-adjustable settings
    (Phase 44: the ad-earnings rate behind the Earning Panel)."""
    __tablename__ = "app_settings"
    key = Column(String(64), primary_key=True)
    value = Column(String(256), default="")


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


class UserBlock(Base):
    """Second-pass audit R5 (security §5/§6): a member blocking
    another member. The effect is mutual invisibility — neither
    side sees the other's posts or profile (the blocker keeps a
    /me/blocked list to undo it), follows are removed both ways,
    and comments/likes/follows/shares between the two are refused.
    Muting is the same relation read from the visibility side."""
    __tablename__ = "user_blocks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    blocker_id = Column(BigInteger, ForeignKey("users.telegram_id"),
                        index=True)
    blocked_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("blocker_id", "blocked_id"),)


class PostView(Base):
    """Phase 31 (owner request): UNIQUE views of a post — one row
    per (post, viewer), so a member rewatching a video never
    inflates the count. Shown on reels as the 👁 count."""
    __tablename__ = "post_views"
    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, ForeignKey("posts.id"), index=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("post_id", "user_id"),)


class DesignView(Base):
    """Phase 31: UNIQUE views of a design — one row per
    (design, viewer), recorded when the detail sheet opens."""
    __tablename__ = "design_views"
    id = Column(Integer, primary_key=True, autoincrement=True)
    design_id = Column(Integer, ForeignKey("designs.id"), index=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("design_id", "user_id"),)


class DesignSave(Base):
    """Phase 66: a member's saved (pinned) designs — the 📌 button
    on the design popup's action rail. Listed under /me/design-saved
    and shown in the Saved view."""
    __tablename__ = "design_saves"
    id = Column(Integer, primary_key=True, autoincrement=True)
    design_id = Column(Integer, ForeignKey("designs.id"), index=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("design_id", "user_id"),)


class DesignShare(Base):
    """Phase 66: in-app design shares — one member sends a design
    to another from the popup's action rail; it lands in the
    receiver's Shared view with a bot notification."""
    __tablename__ = "design_shares"
    id = Column(Integer, primary_key=True, autoincrement=True)
    design_id = Column(Integer, ForeignKey("designs.id"), index=True)
    from_user_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    to_user_id = Column(BigInteger, ForeignKey("users.telegram_id"),
                        index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Message(Base):
    """Phase 36 (owner: a Facebook-style messenger in the top
    corner): a direct message between two members. read_at stays
    NULL until the recipient opens the thread."""
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sender_id = Column(BigInteger, ForeignKey("users.telegram_id"),
                       index=True)
    recipient_id = Column(BigInteger, ForeignKey("users.telegram_id"),
                          index=True)
    text = Column(Text, default="")
    # Phase 138: DM photos — a Telegram file_id, like posts/stories.
    media_file_id = Column(String(256), nullable=True)
    media_type = Column(String(16), nullable=True)  # photo only
    # Phase 139: story replies — a DM that answers a story.
    story_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    read_at = Column(DateTime, nullable=True)


class Story(Base):
    """Phase 36: a photo story. Visible for 24 hours from
    created_at (the API filters expired ones out), shown in the
    stories strip at the top of the Messages view."""
    __tablename__ = "stories"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"),
                     index=True)
    media_file_id = Column(String(256))
    created_at = Column(DateTime, default=datetime.utcnow)


class StoryView(Base):
    """Phase 36: UNIQUE story views — one row per (story,
    viewer); the author's own opens never count."""
    __tablename__ = "story_views"
    id = Column(Integer, primary_key=True, autoincrement=True)
    story_id = Column(Integer, ForeignKey("stories.id"), index=True)
    viewer_id = Column(BigInteger, ForeignKey("users.telegram_id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("story_id", "viewer_id"),)


class PayoutRequest(Base):
    """Phase 127: a crypto payout request — the member's wallet
    (snapshotted at request time), the points asked for, and the
    admin's decision. Approving sets amount + currency and spends
    the points; marking paid records the transaction reference."""
    __tablename__ = "payout_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"),
                     index=True, nullable=False)
    wallet_address = Column(String(256), nullable=False)
    wallet_network = Column(String(16), nullable=False)
    points = Column(Integer, nullable=False)
    status = Column(String(16), default="pending", nullable=False)
    # pending | approved | rejected | paid
    amount = Column(String(64), nullable=True)
    currency = Column(String(16), nullable=True)
    tx_ref = Column(String(256), nullable=True)
    requested_at = Column(DateTime, default=datetime.utcnow, index=True)
    decided_at = Column(DateTime, nullable=True)
    decided_by = Column(BigInteger, nullable=True)
    paid_at = Column(DateTime, nullable=True)



class SecurityEvent(Base):
    """Phase 128: persistent security log — screening rejections,
    rate-limit hits, rejected logins, denied admin routes, server
    errors, self-deletions. One-line details only, never a
    traceback; pruned to the newest 1000 rows on insert."""
    __tablename__ = "security_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(32), nullable=False, index=True)
    actor_id = Column(BigInteger, nullable=True)
    target_id = Column(BigInteger, nullable=True)
    detail = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)



class Broadcast(Base):
    """Phase 131: broadcast history — one row per admin broadcast:
    the text, the target group, who sent it, when, and how many of
    the targeted members actually received the DM."""
    __tablename__ = "broadcasts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(Text, nullable=False)
    target = Column(String(16), default="all", nullable=False)
    # all | verified | new_7d | inactive_30d
    sent_by = Column(BigInteger, nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow, index=True)
    delivered_count = Column(Integer, default=0, nullable=False)
    total_count = Column(Integer, default=0, nullable=False)


class Tip(Base):
    """Phase 133: a Telegram Stars tip that actually landed.
    One row per completed payment — the invoice alone never
    creates a row. post_id is null for a tip on a profile.
    telegram_payment_charge_id makes the successful_payment
    handler idempotent: a duplicate update records nothing. """
    __tablename__ = "tips"
    id = Column(Integer, primary_key=True, autoincrement=True)
    from_user_id = Column(BigInteger, ForeignKey("users.telegram_id"),
                         index=True, nullable=False)
    to_user_id = Column(BigInteger, ForeignKey("users.telegram_id"),
                       index=True, nullable=False)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=True)
    amount_stars = Column(Integer, nullable=False)
    telegram_payment_charge_id = Column(String(128), nullable=True,
                                        unique=True, index=True)
    status = Column(String(16), default="completed", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)



class ScheduledPost(Base):
    """Phase 135: a post waiting for its time — text plus an
    optional already-uploaded media reference, and the UTC time it
    should go out. The sweeper publishes it through the normal
    post path; a failed row stays failed with a short error and is
    never retried automatically. Polls are NOT scheduled (they
    live on a live post)."""
    __tablename__ = "scheduled_posts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"),
                     index=True, nullable=False)
    text = Column(Text, default="")
    media_file_id = Column(String(256), nullable=True)
    media_type = Column(String(16), nullable=True)  # photo | video
    scheduled_at = Column(DateTime, nullable=False, index=True)
    status = Column(String(16), default="pending", nullable=False)
    # pending | posted | failed | cancelled
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    posted_post_id = Column(Integer, ForeignKey("posts.id"),
                            nullable=True)
    error = Column(String(256), nullable=True)


class MessageReaction(Base):
    """Phase 138: one emoji reaction per member per DM message.
    Unique per (message_id, user_id) — tapping your own emoji
    again removes it, tapping another replaces it."""
    __tablename__ = "message_reactions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(Integer, ForeignKey("messages.id"),
                        index=True, nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"),
                     index=True, nullable=False)
    emoji = Column(String(16), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("message_id", "user_id"),)


class HashtagFollow(Base):
    """Phase 140: a member follows a hashtag — its posts show
    up in the Hashtags feed. One row per (member, tag); the tag
    is stored lowercase without the '#'. No notifications:
    a hashtag is not a person."""
    __tablename__ = "hashtag_follows"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"),
                     index=True, nullable=False)
    tag = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    __table_args__ = (UniqueConstraint("user_id", "tag"),)


class BannedWord(Base):
    """Phase 142: admin-managed banned-word list. Posts and
    comments carrying a banned word are refused (case-insensitive
    substring match on the lowercased text). One row per word,
    stored lowercase; DMs are private and are never checked."""
    __tablename__ = "banned_words"
    id = Column(Integer, primary_key=True, autoincrement=True)
    word = Column(String(64), nullable=False, unique=True, index=True)
    added_by = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class BloodRequest(Base):
    """Phase 151: an open call for blood — hospital, city,
    units, an optional note and an optional contact the author
    typed voluntarily. Text only; the only contact path is an
    in-app DM, and no phone number is ever stored or shown.
    There is NO responses table: a donor's tap notifies the
    requester and opens a DM — that IS the response."""
    __tablename__ = "blood_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    author_id = Column(BigInteger, ForeignKey("users.telegram_id"),
                       index=True, nullable=False)
    blood_group = Column(String(3), nullable=False)
    hospital = Column(Text, nullable=False)
    city = Column(String(100), nullable=False)
    units = Column(Integer, default=1, nullable=False)
    note = Column(Text, default="")
    contact = Column(String(200), nullable=True)
    status = Column(String(16), default="open", nullable=False)
    # open | fulfilled | cancelled
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    fulfilled_at = Column(DateTime, nullable=True)


class SkillEntry(Base):
    """Phase 158: skill swap — a member lists what they can teach
    and/or want to learn. Free text, no money, no scheduling in
    the app; the swap is arranged in a DM. Matching is computed,
    not stored: teach X matches learn X. There is no ratings or
    payments table in v1."""
    __tablename__ = "skill_entries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"),
                     index=True, nullable=False)
    skill = Column(String(80), nullable=False, index=True)
    kind = Column(String(8), nullable=False)  # "teach" | "learn"
    note = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
