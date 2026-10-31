"""Settings come only from environment variables — never hardcode secrets
(course rule from Bonus Class 29: keys live in env, not in code)."""
import os


class Settings:
    BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")
    BOT_USERNAME: str = os.environ.get("BOT_USERNAME", "")
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///./tgsocial.db")
    WEBAPP_URL: str = os.environ.get("WEBAPP_URL", "")
    APP_NAME: str = os.environ.get("APP_NAME", "Nexora")
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
     "target": 1, "points": 10, "metric": "checkin"},
    {"key": "follow2", "title": "Follow 2 people", "icon": "👥",
     "target": 2, "points": 20, "metric": "follows"},
    {"key": "comment5", "title": "Write 5 comments", "icon": "💬",
     "target": 5, "points": 20, "metric": "comments"},
]

# Monetization gate (owner request, Oct 31): ALL targets must be met
# before a creator's monetization unlocks. PLACEHOLDER targets — the
# owner can adjust these numbers freely.
MONETIZATION = {
    "followers": 100,        # at least this many followers
    "posts": 25,             # at least this many live posts
    "account_days": 14,      # account at least this many days old
    "lifetime_points": 500,  # at least this many points earned in total
}
