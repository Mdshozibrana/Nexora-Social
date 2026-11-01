"""Settings come only from environment variables — never hardcode secrets
(course rule from Bonus Class 29: keys live in env, not in code)."""
import os


class Settings:
    BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")
    BOT_USERNAME: str = os.environ.get("BOT_USERNAME", "")
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///./tgsocial.db")
    WEBAPP_URL: str = os.environ.get("WEBAPP_URL", "")
    APP_NAME: str = os.environ.get("APP_NAME", "Nexora Social")
    ADMIN_IDS: list = [
        int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()
    ]
    # AdsGram (Telegram Mini App ad network) publisher block id. Empty =
    # ads off. The owner gets the id from adsgram.ai after registering
    # the bot; it is a public placement id, not a secret.
    ADSGRAM_BLOCK_ID: str = os.environ.get("ADSGRAM_BLOCK_ID", "")
    # Phase 28 (security hardening):
    # MODERATOR_IDS — a least-privilege tier below ADMIN_IDS: reports,
    # comment/post moderation and bans only (no points, verify grants,
    # member deletion, broadcasts or managed users).
    MODERATOR_IDS: list = [
        int(x) for x in os.environ.get("MODERATOR_IDS", "").split(",")
        if x.strip()
    ]
    # Emergency maintenance mode: "1" makes the API answer 503
    # (except /health) without stopping the service (security §14).
    MAINTENANCE_MODE: str = os.environ.get("MAINTENANCE_MODE", "")
    # How long a Telegram initData stays acceptable, in seconds.
    # Telegram issues fresh initData at every app open; 24h caps the
    # replay window of a captured string (security §1).
    INITDATA_MAX_AGE_SECONDS: int = int(
        os.environ.get("INITDATA_MAX_AGE_SECONDS", "86400"))


settings = Settings()

# Phase 28: per-user action budgets (security §3/§6) — (limit, window
# seconds). Deliberately generous for real members; they exist to
# stop scripts and floods, not people. Owner-adjustable policy
# numbers, like POINTS below. /auth is limited per IP instead.
RATE_LIMITS = {
    "post": (30, 3600),
    "comment": (120, 3600),
    "like": (600, 3600),
    "follow": (200, 3600),
    "report": (30, 86400),
    "upload": (30, 3600),
    "share": (120, 3600),
    "design_like": (600, 3600),
    "message": (300, 3600),
    "search": (240, 3600),
    "auth_ip": (120, 60),
    # Second-pass audit (R3): analytics reporters get budgets too —
    # the real client beats ~every 30s and sees a handful of ads.
    "heartbeat": (240, 3600),
    "ad_shown": (60, 3600),
    "view": (300, 3600),
}

# Points economy (PRD section 5). PLACEHOLDER defaults — these are product
# policy numbers the owner can adjust freely, not secrets. Likes deliberately
# earn nothing here (anti-farming rule for this phase).
POINTS = {"post": 5, "referral": 20}

# Daily tasks (owner request, Oct 31): each can be claimed ONCE per day.
# metric = how progress is counted for the current day:
#   checkin  -> the claim itself is the check-in
#   follows  -> Follow rows the user created today
#   comments -> Comment rows the user wrote today
DAILY_TASKS = [
    {"key": "checkin", "title": "Daily check-in", "icon": "📅",
     "target": 1, "points": 20, "metric": "checkin"},
    {"key": "follow2", "title": "Follow 2 people", "icon": "👥",
     "target": 2, "points": 5, "metric": "follows"},
    {"key": "comment5", "title": "Write 5 comments", "icon": "💬",
     "target": 5, "points": 5, "metric": "comments"},
]

# Monetization gate (owner request, Oct 31): ALL targets must be met
# before a creator's monetization unlocks. Numbers set by the owner:
# followers 500, lifetime points 5000, and a 30-day UNBROKEN check-in
# streak (one missed day resets the streak to zero).
MONETIZATION = {
    "followers": 500,        # at least this many followers
    "posts": 25,             # at least this many live posts
    "account_days": 14,      # account at least this many days old
    "lifetime_points": 5000,  # at least this many points earned in total
    "checkin_streak": 30,    # consecutive daily check-ins, no misses
}

# Official account (owner request, Oct 31): a system account named
# "Nexora Social" with a verified mark. Every member follows it
# automatically (and cannot unfollow), and its displayed follower count
# starts from a 10,000 base — real followers are added on top.
OFFICIAL_ID = 1  # reserved system id; no real Telegram account uses it
OFFICIAL_NAME = "Nexora Social"
OFFICIAL_USERNAME = "nexora"
OFFICIAL_FOLLOWER_BASE = 10000

# Verification (owner request, Nov 1): a member may APPLY for the
# verified blue tick once they reach this many followers. The admin
# reviews each application in the Admin Panel and approves/rejects.
VERIFICATION_MIN_FOLLOWERS = 1000
