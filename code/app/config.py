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
