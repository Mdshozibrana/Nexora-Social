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


settings = Settings()

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
