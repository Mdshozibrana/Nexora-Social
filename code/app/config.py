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
    # Phase 149: Mapillary (free street-level imagery for
    # Nearby Street View). A free read-only CLIENT token from
    # mapillary.com/dashboard/developers — designed for
    # browser use, it ships to the client via /auth (like the
    # AdsGram block id). Empty = Street View shows the honest
    # "not set up yet" line. Never hardcode a token value.
    MAPILLARY_CLIENT_TOKEN: str = os.environ.get("MAPILLARY_CLIENT_TOKEN", "")
    # Phase 69: Nexa, the AI assistant. One free Gemini API key
    # (aistudio.google.com) powers her chat brain AND her voice.
    # Empty = she runs on the built-in guide brain and the phone's
    # own speech voice. Secret: env only, never sent to clients.
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
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
    # Phase 164 (M2): owner-held Fernet key for backup encryption.
    # Empty = backups stay plaintext (logged loudly). Losing the key
    # makes encrypted backups unrestorable — keep it in Render env
    # only, never in code.
    BACKUP_ENCRYPTION_KEY: str = os.environ.get("BACKUP_ENCRYPTION_KEY", "")
    # Phase 164 (H1): per-admin TOTP secret (base32) for the
    # authenticator second factor. Empty = TOTP off; step-up freshness
    # still applies. The owner enrolls it via GET /admin/totp/setup.
    ADMIN_TOTP_SECRET: str = os.environ.get("ADMIN_TOTP_SECRET", "")


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
    # Phase 118: reposting a post to your own feed.
    "repost": (120, 3600),
    "design_like": (600, 3600),
    "message": (300, 3600),
    "search": (240, 3600),
    "auth_ip": (120, 60),
    # Phase 164 (H2): /media was unthrottled — one token holder could
    # hammer the Telegram proxy without limit.
    "media": (60, 60),
    # Second-pass audit (R3): analytics reporters get budgets too —
    # the real client beats ~every 30s and sees a handful of ads.
    "heartbeat": (240, 3600),
    "ad_shown": (60, 3600),
    "view": (300, 3600),
    # Phase 69: Nexa's chat budget (a Gemini key is shared by
    # the whole platform, so a per-member cap protects the
    # quota). Phase 183 (audit M15): the assistant_speak
    # bucket is gone with the voice routes — Nexa is TEXT-ONLY.
    "assistant_chat": (30, 3600),
    "location": (300, 3600),
    # Phase 97 (audit): the two newest endpoints get budgets too —
    # suggestions run the heaviest read queries in the app, and a
    # theme save writes the member's row.
    "suggested": (120, 3600),
    # Phase 122: the Trending page (posts + hashtags).
    "trending": (120, 3600),
    # Phase 123: creator tools — pin, drafts, comment likes,
    # poll votes. Comment likes share the post-like budget.
    "pin": (120, 3600),
    "draft": (120, 3600),
    "comment_like": (600, 3600),
    "poll_vote": (120, 3600),
    "theme": (120, 3600),
    # Phase 100: data export (download + send-to-Telegram) — a full
    # account dump is heavy and sensitive; a small hourly budget.
    "export": (10, 3600),
    # Phase 107: full-site backup (admin-only download/send) and
    # restore — the backup is the whole database, and restore
    # rewrites everything, so both budgets stay small.
    "backup": (10, 3600),
    "restore": (3, 3600),
    # Phase 127: crypto payouts — a member may ask for a payout at
    # most 10 times an hour (validation rejects nearly all of them);
    # the admin's decide/paid calls get a separate, larger budget.
    "payout": (10, 3600),
    # Phase 133: Stars tip-invoice requests.
    "tip": (120, 3600),
    # Phase 134: post insights (creator analytics).
    "insights": (120, 3600),
    # Phase 135: scheduled posts — queueing + cancelling.
    "scheduled": (120, 3600),
    # Phase 136: private-account toggle.
    "privacy": (120, 3600),
    # Phase 144: notification-preference saves.
    "notif_prefs": (120, 3600),
    # Phase 138: DM message reactions.
    "dm_react": (120, 3600),
    # Phase 140: hashtag follows.
    "hashtag_follow": (120, 3600),
    # Phase 151: blood donors + requests.
    "blood": (120, 3600),
    # Phase 158: skill swap — add/remove/connect.
    "skills": (120, 3600),
    "payout_admin": (120, 3600),
    # Phase 181 (audit H10/M10): TOTP verify attempts — 5 per
    # 15 min per admin; the sliding window IS the lockout (it
    # expires on its own, so the owner can never be locked out
    # permanently) — plus one shared budget for every mutating
    # admin endpoint.
    "totp_verify": (5, 900),
    "admin_mutation": (120, 3600),
    # Phase 172: story highlights — create/rename/delete/add.
    "highlights": (120, 3600),
    # Phase 199: portfolio edits (upsert / items / reorder).
    "portfolio": (120, 3600),
    # Phase 201: museum edits (hang a photo / place furniture /
    # remove an item).
    "museum": (120, 3600),
    # Phase 179 (audit M4): read/discovery budgets. Generous on
    # purpose — the feed is the hottest path (Explore/Following/
    # hashtag tabs, pull-to-refresh, "Load more" paging and the
    # Videos tab all call /feed; comments load per post open;
    # highlights load per profile open). A normal session stays
    # far below these; they exist to stop scripts, not people.
    # feed covers /feed + /feed/hashtags; saved covers /me/saved,
    # /saved/collections* reads and /me/shared; post_read covers
    # GET /posts/{id} + GET /posts/{id}/comments; stories covers
    # GET /stories; highlight_read covers the highlight reads;
    # user_posts covers GET /users/{id}/posts + the portfolio reads.
    "feed": (600, 3600),
    "saved": (240, 3600),
    "post_read": (600, 3600),
    "stories": (240, 3600),
    "highlight_read": (240, 3600),
    "user_posts": (240, 3600),
}

# Points economy (PRD section 5). PLACEHOLDER defaults — these are product
# policy numbers the owner can adjust freely, not secrets. Likes deliberately
# earn nothing here (anti-farming rule for this phase).
POINTS = {"post": 10, "referral": 20}

# Phase 180 (audit H14): NO ad provider is live — AdsGram DECLINED
# the platform (54173, unit int-57207), so no ad can ever play.
# While this is False, POST /ads/shown answers 410 and creates no
# AdEvent row, and the adwatch task reports available=False. Flip to
# True — and only then — when a provider returns AND its shows are
# verified server-side.
ADS_PROVIDER_LIVE = False


# Daily tasks (owner request, Oct 31; values revised Nov 13, Phase 113):
# each can be claimed ONCE per day.
# metric = how progress is counted for the current day:
#   checkin   -> the claim itself is the check-in
#   follows   -> Follow rows the user created today
#   comments  -> Comment rows the user wrote today
#   reactions -> Like rows the user created today (one per post)
#   ads       -> AdEvent rows today (only real completed ad shows)
DAILY_TASKS = [
    {"key": "checkin", "title": "Daily check-in", "icon": "📅",
     "target": 1, "points": 20, "metric": "checkin"},
    {"key": "follow3", "title": "Follow 3 people", "icon": "👥",
     "target": 3, "points": 10, "metric": "follows"},
    {"key": "comment5", "title": "Write 5 comments", "icon": "💬",
     "target": 5, "points": 5, "metric": "comments"},
    {"key": "react6", "title": "React to 6 posts", "icon": "❤️",
     "target": 6, "points": 10, "metric": "reactions"},
    {"key": "adwatch", "title": "Watch an ad", "icon": "📺",
     "target": 1, "points": 20, "metric": "ads"},
]

# Monetization gate (owner request, Oct 31): ALL targets must be met
# before a creator's monetization unlocks. Numbers set by the owner:
# followers 500, lifetime points 5000, and a 30-day UNBROKEN check-in
# streak (one missed day resets the streak to zero). Owner added a
# 6th target on Nov 2: 12 qualified referrals.
MONETIZATION = {
    "followers": 500,        # at least this many followers
    "referrals": 12,         # at least this many QUALIFIED referrals
    "posts": 25,             # at least this many live posts
    "account_days": 14,      # account at least this many days old
    "lifetime_points": 5000,  # at least this many points earned in total
    "checkin_streak": 30,    # consecutive daily check-ins, no misses
}

# Phase 127: crypto payout networks — the only wallets a member may
# save. The admin sets the crypto amount at approval; no
# points->money rate is hardcoded anywhere.
PAYOUT_NETWORKS = ("TON", "Gram", "USDT")

# Official account (owner request, Oct 31): a system account named
# "Nexora Social" with a verified mark. Every member follows it
# automatically (and cannot unfollow), and its displayed follower count
# starts from a 10,000 base — real followers are added on top.
OFFICIAL_ID = 1  # reserved system id; no real Telegram account uses it
OFFICIAL_NAME = "Nexora Social"
OFFICIAL_USERNAME = "nexora"
OFFICIAL_FOLLOWER_BASE = 10000

# Verification (owner request, Nov 1; Phase 117: TWO conditions,
# either one qualifies): a member may APPLY for the verified blue
# tick once they reach this many followers OR this many QUALIFIED
# referrals (the referred member has posted — the monetization
# gate's definition). The admin reviews each application in the
# Admin Panel and approves/rejects.
VERIFICATION_MIN_FOLLOWERS = 1000
VERIFICATION_MIN_REFERRALS = 50
