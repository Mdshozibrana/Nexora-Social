"""FastAPI backend: auth, feed, posts, likes, comments, profiles, follow,
referrals, points, search, reports, media proxy, and the Mini App host.
Only the PRD section-8 admin endpoints remain for a later phase."""
import asyncio
import contextvars
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import (Depends, FastAPI, File, Form, Header, HTTPException,
                     Request, UploadFile)
from fastapi.responses import JSONResponse, RedirectResponse, \
    StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, inspect, or_, text
from sqlalchemy.orm import Session

from datetime import datetime, timedelta

from . import filesig, geoip, imgconv, models, moderation, notify, \
    ratelimit, \
    tgupload, videoutil
from .config import (DAILY_TASKS, MONETIZATION, OFFICIAL_FOLLOWER_BASE,
                     OFFICIAL_ID, OFFICIAL_NAME, RATE_LIMITS,
                     VERIFICATION_MIN_FOLLOWERS, settings)
from .db import Base, SessionLocal, engine, get_db
from .security import init_data_auth_date, validate_init_data
from .services import award_points, extract_hashtags, register_post
from .users import get_or_create_user

# Phase 28 (security §13): security events go to the service log —
# rejected logins, admin denials, rate-limit hits, admin actions.
# NEVER log initData, tokens or message content.
sec_log = logging.getLogger("nexora.security")

Base.metadata.create_all(bind=engine)


def _migrate():
    """create_all never alters existing tables, so columns added after
    the first deploy (Phase 19: country / language_code / last_seen_at
    on users) are added here, once, on whichever dialect is live."""
    existing = {c["name"] for c in inspect(engine).get_columns("users")}
    wanted = {"country": "VARCHAR(64)", "language_code": "VARCHAR(16)",
              "last_seen_at": "TIMESTAMP", "is_managed": "BOOLEAN",
              "auth_revoked_at": "TIMESTAMP",
              "cover_file_id": "VARCHAR(256)",
              "name_changed_at": "TIMESTAMP",
              "share_location": "BOOLEAN", "lat": "FLOAT",
              "theme": "VARCHAR(256)",
              "lon": "FLOAT", "loc_at": "TIMESTAMP"}
    with engine.begin() as conn:
        for name, ddl in wanted.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))
    # Phase 51: video preview thumbnails on posts.
    post_cols = {c["name"] for c in inspect(engine).get_columns("posts")}
    with engine.begin() as conn:
        if "thumb_file_id" not in post_cols:
            conn.execute(text(
                "ALTER TABLE posts ADD COLUMN thumb_file_id VARCHAR(256)"))
    # Phase 60: a managed account created as "@name" stored the @
    # IN the username, so every "@" + username render showed
    # "@@name". Strip stray leading @s once (idempotent — later
    # runs match nothing). Write paths strip too, so it cannot
    # come back.
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT telegram_id, username FROM users "
            "WHERE username LIKE '@%'")).fetchall()
        for tid, uname in rows:
            conn.execute(text(
                "UPDATE users SET username = :u "
                "WHERE telegram_id = :t"),
                {"u": uname.lstrip("@"), "t": tid})


_migrate()

app = FastAPI(title=settings.APP_NAME)


@app.middleware("http")
async def webapp_no_cache(request, call_next):
    """Phase 23: the Mini App shell must never be served stale from a
    webview cache — the owner repeatedly missed new features because
    Telegram kept the old app.js. no-cache forces revalidation on
    every open while keeping etags, so loads stay fast.

    Phase 38 (owner: make the site smooth and fast): two upgrades.
    (a) Versioned assets: index.html loads the JS/CSS with ?v=N, so
    those URLs may cache hard for a week — a deploy bumps N in the
    no-cache shell, which makes a stale asset impossible.
    (b) gzip: JSON API responses and the webapp text assets are
    compressed when the client accepts it (~3x smaller on mobile
    data). Streaming responses outside /webapp (the /media proxy)
    are never touched, so video delivery keeps its range/streaming
    behaviour."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/webapp"):
        if path.endswith((".js", ".css")):
            response.headers["Cache-Control"] = \
                "public, max-age=604800"
        else:
            response.headers["Cache-Control"] = "no-cache"
    if "gzip" in request.headers.get("accept-encoding", "") \
            and request.method in ("GET", "POST") \
            and response.status_code == 200 \
            and "content-encoding" not in response.headers \
            and not path.startswith("/media"):
        ctype = response.headers.get("content-type", "")
        if ctype.startswith(("application/json", "text/",
                             "application/javascript")):
            from starlette.responses import Response as _Resp
            if hasattr(response, "body"):
                body = response.body
                buffered = False
            else:
                # BaseHTTPMiddleware hands back a streaming wrapper
                # even for plain JSON; buffer it (payloads here are
                # small — the media proxy is excluded above). A
                # buffered body MUST be re-wrapped before returning:
                # the drained original would stream nothing.
                body = b"".join([chunk async for chunk
                                 in response.body_iterator])
                buffered = True
            headers = {k: v for k, v in response.headers.items()
                       if k.lower() not in
                       ("content-length", "content-encoding")}
            background = getattr(response, "background", None)
            if len(body) >= 1024:
                import gzip as _gz
                packed = _gz.compress(body, compresslevel=6)
                if len(packed) < len(body):
                    if "etag" in headers:
                        headers["etag"] = headers["etag"] + "-gz"
                    headers["Content-Encoding"] = "gzip"
                    headers["Content-Length"] = str(len(packed))
                    headers["Vary"] = "Accept-Encoding"
                    return _Resp(content=packed,
                                 status_code=response.status_code,
                                 headers=headers,
                                 background=background)
            if buffered:
                headers["Content-Length"] = str(len(body))
                return _Resp(content=body,
                             status_code=response.status_code,
                             headers=headers,
                             background=background)
    return response


# --- Phase 28: security middleware (requirements §3/§4/§14) --------------
# Content-Security-Policy notes: script sources stay strict ('self' +
# Telegram + the AdsGram SDK host). Image/media sources allow https:
# because ad creatives are served from rotating ad-network CDNs —
# scripts, the dangerous vector, remain locked down. Framing is
# restricted to Telegram's own web clients (frame-ancestors): the Mini
# App MUST be framable by Telegram, so X-Frame-Options is deliberately
# NOT set (SAMEORIGIN/DENY would break the app inside Telegram).
_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://telegram.org https://sad.adsgram.ai; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; "
    "media-src 'self' blob: https:; "
    "connect-src 'self' https://sad.adsgram.ai https://api.adsgram.ai https://routing.openstreetmap.de; "
    "font-src 'self' data:; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'self' https://web.telegram.org "
    "https://web-a.telegram.org https://*.telegram.org"
)


@app.middleware("http")
async def security_middleware(request, call_next):
    # Emergency maintenance mode (§14): the API pauses with 503 while
    # the shell and /health stay up, so the platform can be frozen
    # during an incident without stopping the service.
    if settings.MAINTENANCE_MODE == "1" \
            and request.url.path != "/health" \
            and not request.url.path.startswith("/webapp"):
        return JSONResponse(
            status_code=503,
            content={"detail": "Nexora Social is briefly down for "
                               "maintenance — please try again soon"})
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = _CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = \
        "camera=(), microphone=(), geolocation=()"
    response.headers["Strict-Transport-Security"] = \
        "max-age=31536000; includeSubDomains"
    return response


@app.exception_handler(Exception)
async def unhandled_error(request, exc):
    """§3 secure error handling: clients get a generic message, the
    detail stays in the server log. (HTTPException keeps its own,
    more specific handler and never lands here.)"""
    sec_log.exception("unhandled error on %s %s",
                      request.method, request.url.path)
    return JSONResponse(status_code=500,
                        content={"detail": "Something went wrong — "
                                           "please try again"})


def _client_ip(request) -> str:
    fwd = request.headers.get("x-forwarded-for") or ""
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_rate(bucket: str, key: str):
    """Raise 429 when the (owner-adjustable) budget for an action is
    exhausted — security §3/§6 rate limiting."""
    limit, window = RATE_LIMITS[bucket]
    if not ratelimit.hit(bucket, key, limit, window):
        sec_log.warning("rate limit hit: %s key=%s", bucket, key)
        raise HTTPException(
            429, "Too many requests — please slow down a little",
            headers={"Retry-After": str(min(window, 300))})


def _audit(db, admin, action, target_id=None, detail=""):
    """Append one admin-action record (§10/§13). The row rides the
    caller's transaction, so it commits or rolls back with the action
    itself — an action that failed leaves no false record."""
    db.add(models.AdminAuditLog(
        admin_id=admin.telegram_id, action=action,
        target_id=target_id, detail=(detail or "")[:512]))
    sec_log.info("admin action: %s by %s target=%s",
                 action, admin.telegram_id, target_id)


def _check_revoked(user, init_data: str):
    """Phase 28 (H5): reject initData issued before the member's
    revocation moment. Reopening the app issues fresh initData, so
    the member recovers instantly while leaked strings stay dead."""
    if user.auth_revoked_at is None:
        return
    auth_date = init_data_auth_date(init_data)
    # auth_revoked_at is stored naive-UTC (datetime.utcnow); read it
    # back as UTC for the epoch comparison.
    from datetime import timezone as _tz
    revoked_ts = int(user.auth_revoked_at.replace(
        tzinfo=_tz.utc).timestamp())
    if auth_date is not None and auth_date < revoked_ts:
        raise HTTPException(
            401, "This login was revoked — please reopen the app")


def _media_token() -> str:
    """Short-lived signed capability for /media URLs (H2). <img> and
    <video> tags cannot send the X-Init-Data header, so media access
    rides on this token instead: HMAC over an expiry, keyed by the
    bot token (server-side only). 7 days covers a long-open WebView;
    the app fetches a fresh one at every open via /auth."""
    import base64
    import hashlib as _hl
    import hmac as _hm
    exp = int(time.time()) + 7 * 86400
    sig = _hm.new(settings.BOT_TOKEN.encode(),
                  f"nexora-media:{exp}".encode(),
                  _hl.sha256).hexdigest()
    raw = f"{exp}.{sig}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def _media_token_ok(token: str) -> bool:
    import base64
    import hashlib as _hl
    import hmac as _hm
    if not token or not settings.BOT_TOKEN:
        return False
    try:
        decoded = base64.urlsafe_b64decode(
            token.encode()).decode()
        exp_s, sig = decoded.split(".", 1)
        exp = int(exp_s)
    except Exception:
        return False
    if exp < int(time.time()):
        return False
    expected = _hm.new(settings.BOT_TOKEN.encode(),
                       f"nexora-media:{exp}".encode(),
                       _hl.sha256).hexdigest()
    return _hm.compare_digest(expected, sig)


def _like_pattern(q: str) -> str:
    """Escape LIKE wildcards in user search text (M3) — pair with
    .ilike(pattern, escape="\\\\") at the call site."""
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%") \
        .replace("_", "\\_") + "%"
WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"

_bot_app = None


@app.on_event("startup")
async def _startup():
    global _bot_app
    if settings.BOT_TOKEN:
        from .bot import build_bot_app, start_bot
        _bot_app = build_bot_app()
        await start_bot(_bot_app)


@app.on_event("shutdown")
async def _shutdown():
    if _bot_app:
        try:
            await _bot_app.updater.stop()
            await _bot_app.stop()
            await _bot_app.shutdown()
        except RuntimeError:
            pass  # updater was not running (e.g. startup had failed)


class AuthIn(BaseModel):
    initData: str = Field(max_length=16384)


_THEME_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def _theme_picks(user):
    """Phase 96: the member's own Theme Colours picks, or all-null.
    Stored per account (users.theme JSON) so one member's theme can
    never change another member's app."""
    picks = {"bg": None, "card": None, "accent": None}
    raw = getattr(user, "theme", None)
    if raw:
        try:
            saved = json.loads(raw)
            if isinstance(saved, dict):
                for zone in picks:
                    v = saved.get(zone)
                    if isinstance(v, str) and _THEME_ID_RE.match(v):
                        picks[zone] = v
        except Exception:
            pass
    return picks


class ThemeIn(BaseModel):
    picks: dict = Field(default_factory=dict)


def _resolve_act_as(db, real_user, x_act_as):
    """Phase 20: the owner can operate a MANAGED account (one he
    created in the Admin Panel) as if he were that member. Hard rules:
    only admins may act as anyone, and the target must be a managed
    account — impersonating a real member is impossible by design."""
    if not x_act_as:
        return real_user
    if real_user.telegram_id not in settings.ADMIN_IDS:
        raise HTTPException(403, "Only the admin can act as a managed user")
    try:
        target_id = int(x_act_as)
    except (TypeError, ValueError):
        raise HTTPException(400, "Bad act-as id")
    target = db.get(models.User, target_id)
    # Legal targets: admin-created managed accounts — and the official
    # system account, which is not a real member either; the owner
    # must be able to post and manage the platform's own page. A real
    # member's account can NEVER be resolved here.
    if target is None or (not target.is_managed
                          and target_id != OFFICIAL_ID):
        raise HTTPException(403, "Act-as target must be a managed user")
    if target.is_banned:
        raise HTTPException(403, "Account suspended")
    return target


def current_user(x_init_data: str = Header(default=""),
                 x_act_as: str = Header(default=""),
                 db: Session = Depends(get_db)):
    tg_user = validate_init_data(x_init_data, settings.BOT_TOKEN)
    if not tg_user:
        sec_log.warning("rejected initData on API request")
        raise HTTPException(401, "Invalid Telegram login")
    user, _ = get_or_create_user(db, tg_user)
    if user.is_banned:
        raise HTTPException(403, "Account suspended")
    _check_revoked(user, x_init_data)
    # Phase 19: "last seen" powers the admin dashboard's activity
    # figures. Written at most once a minute per member, so the extra
    # UPDATE stays negligible.
    now = datetime.utcnow()
    if user.last_seen_at is None or (now - user.last_seen_at).total_seconds() >= 60:
        user.last_seen_at = now
        db.commit()
    real_id = user.telegram_id
    user = _resolve_act_as(db, user, x_act_as)
    # Phase 32: remember the REAL caller on the resolved identity.
    # Managed accounts and the official account have no Telegram
    # chat of their own (chat 1 can never press Start), so uploads
    # and bot DMs must travel via the real caller's chat — see
    # _send_chat_id. Without act-as this is simply the member's id.
    user._real_id = real_id
    if user.last_seen_at is None or (now - user.last_seen_at).total_seconds() >= 60:
        user.last_seen_at = now
        db.commit()
    return user


@app.get("/")
def root():
    return RedirectResponse(url="/webapp/", status_code=302)


@app.get("/health")
def health():
    return {"ok": True, "app": settings.APP_NAME}


@app.post("/auth")
async def auth(body: AuthIn, request: Request,
               x_act_as: str = Header(default=""),
               db: Session = Depends(get_db)):
    _enforce_rate("auth_ip", f"ip:{_client_ip(request)}")
    tg_user = validate_init_data(body.initData, settings.BOT_TOKEN)
    if not tg_user:
        sec_log.warning("rejected initData at /auth from %s",
                        _client_ip(request))
        raise HTTPException(401, "Invalid Telegram login")
    user, is_new = get_or_create_user(db, tg_user)
    _check_revoked(user, body.initData)
    user.last_seen_at = datetime.utcnow()
    db.commit()
    # Phase 20: an admin acting as a managed user sees the app as that
    # member (the response below is then the managed member's).
    if x_act_as:
        user = _resolve_act_as(db, user, x_act_as)
        is_new = False
    # Phase 19: Telegram never reveals a member's country, so it is
    # approximated ONCE from the sign-in IP (only the name is stored).
    if not user.country:
        raw_ip = request.headers.get("x-forwarded-for") or (
            request.client.host if request.client else "")
        country = await geoip.lookup_country(raw_ip)
        if country:
            user.country = country
            db.commit()
    followers = db.query(models.Follow).filter_by(following_id=user.telegram_id).count()
    following = db.query(models.Follow).filter_by(follower_id=user.telegram_id).count()
    posts = db.query(models.Post).filter_by(user_id=user.telegram_id, is_deleted=False).count()
    return {
        "telegram_id": user.telegram_id,
        "first_name": user.first_name,
        "username": user.username,
        "bio": user.bio,
        "points": user.points_balance,
        "is_verified": bool(user.is_verified),
        "is_new": is_new,
        "photo_file_id": user.photo_file_id,
        "followers": followers,
        "following": following,
        "posts": posts,
        "bot_username": settings.BOT_USERNAME,
        "is_admin": user.telegram_id in settings.ADMIN_IDS,
        "is_moderator": user.telegram_id in settings.MODERATOR_IDS,
        "theme": _theme_picks(user),
        "media_token": _media_token(),
        "adsgram_block_id": settings.ADSGRAM_BLOCK_ID,
    }


@app.get("/feed")
def feed(tab: str = "explore", type: str = "", cursor: int = 0,
         user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(models.Post).filter_by(is_deleted=False)
    hidden = _block_related_ids(db, user.telegram_id)
    if hidden:
        q = q.filter(~models.Post.user_id.in_(hidden))
    if type in ("photo", "video", "text"):
        q = q.filter_by(type=type)
    else:
        # Phase 35 (owner directive): the Feed page shows statuses
        # and photos only — videos live on the Videos page, whose
        # loader always asks with type=video explicitly.
        q = q.filter(models.Post.type != "video")
    if tab == "following":
        ids = [f.following_id for f in
               db.query(models.Follow).filter_by(follower_id=user.telegram_id)]
        q = q.filter(models.Post.user_id.in_(ids or [-1]))
    if cursor:
        q = q.filter(models.Post.id < cursor)
    rows = q.order_by(models.Post.id.desc()).limit(20).all()
    liked = liked_ids(db, user.telegram_id, rows)
    saved = saved_ids(db, user.telegram_id, rows)
    counts = _post_view_counts(db, rows)
    _warm_authors(db, rows)
    out = [post_dict(db, p, liked=p.id in liked, saved=p.id in saved,
                     views=counts.get(p.id, 0))
           for p in rows]
    return {"posts": out, "next_cursor": rows[-1].id if len(rows) == 20 else None}


@app.get("/suggested-users")
def suggested_users(limit: int = 10, user: models.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    """Phase 95 (owner): the bot suggests people to follow,
    a little way down the Feed while scrolling. Candidates are
    members the viewer does NOT follow yet (never the viewer,
    never banned, never anyone in a block relation either way).
    Ranking: people followed by people YOU follow first
    (mutual connections), then most followers, then most
    posts, then most points — so the card feels personal,
    not just a popularity list. The reason string says WHY
    each person is suggested, in plain words."""
    _enforce_rate("suggested", f"u{user.telegram_id}")
    limit = max(1, min(int(limit or 10), 20))
    hidden = _block_related_ids(db, user.telegram_id)
    following_ids = {f.following_id for f in db.query(models.Follow)
                     .filter_by(follower_id=user.telegram_id).all()}
    rows = db.query(models.User).filter_by(is_banned=False).all()
    out = []
    for cand in rows:
        if cand.telegram_id == user.telegram_id:
            continue
        if cand.telegram_id in following_ids:
            continue
        if cand.telegram_id in hidden:
            continue
        followers = db.query(models.Follow).filter_by(
            following_id=cand.telegram_id).count()
        if cand.telegram_id == OFFICIAL_ID:
            followers += OFFICIAL_FOLLOWER_BASE
        posts = db.query(models.Post).filter_by(
            user_id=cand.telegram_id, is_deleted=False).count()
        mutual_ids = []
        if following_ids:
            mutual_ids = [f.follower_id for f in db.query(models.Follow)
                          .filter_by(following_id=cand.telegram_id).all()
                          if f.follower_id in following_ids]
        mutual_name = ""
        if mutual_ids:
            mu = db.get(models.User, mutual_ids[0])
            mutual_name = mu.first_name if mu else ""
        if mutual_ids and mutual_name:
            reason = ("Followed by " + mutual_name
                      if len(mutual_ids) == 1 else
                      f"Followed by {mutual_name} +{len(mutual_ids) - 1}")
        elif cand.is_verified:
            reason = "Verified member"
        elif followers >= 10:
            reason = "Popular on Nexora"
        elif posts > 0:
            reason = "Active on Nexora"
        else:
            reason = "New on Nexora"
        out.append({
            "telegram_id": cand.telegram_id,
            "first_name": cand.first_name,
            "username": cand.username,
            "bio": cand.bio or "",
            "is_verified": bool(cand.is_verified),
            "is_official": cand.telegram_id == OFFICIAL_ID,
            "photo_file_id": cand.photo_file_id,
            "followers": followers,
            "posts": posts,
            "points": cand.points_balance or 0,
            "mutual_count": len(mutual_ids),
            "reason": reason,
        })
    out.sort(key=lambda u: (-u["mutual_count"], -u["followers"],
                            -u["posts"], -u["points"], u["telegram_id"]))
    return {"users": out[:limit]}


# ---------------------------------------------------------------------------
# Posts, likes, comments (PRD section 4, MVP items 3-5)
# ---------------------------------------------------------------------------

def post_dict(db, p, liked=False, saved=False, views=None):
    author = db.get(models.User, p.user_id)
    if views is None:
        # Phase 31: unique-view count (post_views), shown on reels.
        views = db.query(models.PostView).filter_by(
            post_id=p.id).count()
    return {
        "id": p.id, "type": p.type, "media_file_id": p.media_file_id,
        "thumb_file_id": getattr(p, "thumb_file_id", None),
        "caption": p.caption, "hashtags": p.hashtags,
        "like_count": p.like_count, "comment_count": p.comment_count,
        "views": views,
        "liked": liked,
        "saved": saved,
        "author_id": p.user_id,
        "author_name": author.first_name if author else "",
        "author_username": author.username if author else None,
        "author_verified": bool(author and author.is_verified),
        "author_photo": author.photo_file_id if author else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _post_view_counts(db, posts):
    """Phase 38 (speed): ONE grouped query returns the unique-view
    counts for a whole page of posts, instead of one count query
    per post (the feed was making 20+ extra round trips)."""
    ids = [p.id for p in posts]
    if not ids:
        return {}
    rows = db.query(models.PostView.post_id, func.count()).filter(
        models.PostView.post_id.in_(ids)).group_by(
        models.PostView.post_id).all()
    return {pid: n for pid, n in rows}


def _warm_authors(db, posts):
    """Phase 38: batch-load the page's authors into the session so
    post_dict's per-post author lookup never hits the database."""
    ids = {p.user_id for p in posts}
    if ids:
        db.query(models.User).filter(
            models.User.telegram_id.in_(ids)).all()


def liked_ids(db, viewer_id, posts):
    """Which of these posts has the viewer liked (for the heart state)."""
    ids = [p.id for p in posts]
    if not ids:
        return set()
    rows = db.query(models.Like.post_id).filter(
        models.Like.user_id == viewer_id,
        models.Like.post_id.in_(ids)).all()
    return {r[0] for r in rows}


def saved_ids(db, viewer_id, posts):
    """Which of these posts has the viewer bookmarked."""
    ids = [p.id for p in posts]
    if not ids:
        return set()
    rows = db.query(models.SavedPost.post_id).filter(
        models.SavedPost.user_id == viewer_id,
        models.SavedPost.post_id.in_(ids)).all()
    return {r[0] for r in rows}


def get_live_post(db, post_id):
    p = db.get(models.Post, post_id)
    if p is None or p.is_deleted:
        raise HTTPException(404, "Post not found")
    return p


def _block_related_ids(db, user_id):
    """Everyone in a block relation with user_id, in either
    direction (second-pass audit R5, security §5/§6)."""
    rows = db.query(models.UserBlock).filter(or_(
        models.UserBlock.blocker_id == user_id,
        models.UserBlock.blocked_id == user_id)).all()
    out = set()
    for r in rows:
        out.add(r.blocker_id)
        out.add(r.blocked_id)
    out.discard(user_id)
    return out


def _blocked_by(db, blocker_id, user_id):
    """True when blocker_id has blocked user_id."""
    return db.query(models.UserBlock).filter_by(
        blocker_id=blocker_id, blocked_id=user_id).first() is not None


class PostIn(BaseModel):
    type: str = Field(default="text", max_length=16)
    media_file_id: Optional[str] = Field(default=None, max_length=256)
    caption: str = Field(default="", max_length=2000)


@app.post("/posts")
def create_post(body: PostIn, user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
    _enforce_rate("post", f"u{user.telegram_id}")
    if body.type not in ("photo", "video", "text"):
        raise HTTPException(400, "type must be photo, video or text")
    # Phase 81: a media post carries a Telegram file_id the server
    # never saw uploaded — fetch and screen it, so this endpoint
    # cannot bypass the screening every upload goes through.
    if moderation.active() and body.type in ("photo", "video") \
            and body.media_file_id:
        verdict = _screen_file_id(body.type, body.media_file_id)
        if verdict != "clean":
            raise HTTPException(
                400, moderation.block_message(body.type, verdict))
    post, _, _ = register_post(db, user, body.type, body.media_file_id,
                               body.caption)
    return post_dict(db, post)


def _screen_file_id(kind, file_id):
    """Phase 81: fetch a Telegram file's bytes and screen them
    (photo: classify directly; video: three frames)."""
    data = moderation.fetch_file_bytes(file_id)
    if data is None:
        return "error"
    if kind == "photo":
        return moderation.classify_image(data)
    with tempfile.NamedTemporaryFile(delete=False,
                                     suffix=".src") as f:
        f.write(data)
        path = f.name
    try:
        return moderation.screen_video(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _send_chat_id(user):
    """The Telegram chat an upload is sent through (Phase 32).
    Normally the member's own bot chat. While the owner acts as a
    managed or the official account, that identity has no bot chat
    (the official id 1 can never press Start — every upload died
    with the misleading 'press Start' message), so the file travels
    via the REAL caller's chat instead. Telegram file_ids are
    bot-scoped, not chat-scoped: the post still belongs entirely
    to the acting identity."""
    return getattr(user, "_real_id", None) or user.telegram_id


async def _send_to_telegram(user, filename, data, content_type):
    try:
        kind, file_id, _thumb = await tgupload.upload_media(
            _send_chat_id(user), filename, data, content_type)
        return kind, file_id
    except tgupload.TelegramUploadError as e:
        if e.kind == "not_started":
            raise HTTPException(
                400, "Open @NexoraSocial_bot once and press Start, "
                     "then try uploading again")
        raise HTTPException(502, "Upload failed — please try again")


# --- Phase 19.1: background video processing ------------------------------
# The first cut transcoded inside the upload request; a 105-second
# 1080p clip outlasted the connection on the free instance and the
# post died with it. Now the request only receives the file: the
# transcode + Telegram send run as a background job (one at a time —
# the free instance has ~512 MB), and the member hears the outcome
# from the bot. The post, with its +5 points, appears when it is ready.
_video_jobs = set()
_transcode_sem = asyncio.Semaphore(1)


def _schedule_video_job(coro):
    task = asyncio.get_running_loop().create_task(coro)
    _video_jobs.add(task)
    task.add_done_callback(_video_jobs.discard)
    return task


async def _finish_video_post(author_id, send_chat_id, src_path,
                             caption):
    """Phase 32: author and send-chat are separate ids. Normally
    they are the same member; while acting as Official/managed,
    the post belongs to the acting identity (author_id) but the
    Telegram send and the result DM use the real caller's chat
    (send_chat_id) — the acting identity has no chat of its own."""
    dst = src_path + ".mp4"
    try:
        async with _transcode_sem:
            await asyncio.to_thread(videoutil.transcode_to_mp4,
                                    src_path, dst)
        # Phase 81: screen frames of the finished MP4 first — a
        # video that fails never reaches Telegram or the feed;
        # the member hears why from the bot instead.
        if moderation.active():
            verdict = await asyncio.to_thread(
                moderation.screen_video, dst)
            if verdict != "clean":
                sec_log.warning(
                    "video screened out (%s) for user %s",
                    verdict, author_id)
                await notify.send_message(
                    send_chat_id,
                    moderation.block_message("video", verdict))
                return
        with open(dst, "rb") as f:
            mp4 = f.read()
        _, file_id, thumb_id = await tgupload.upload_media(
            send_chat_id, "video.mp4", mp4, "video/mp4")
        db = SessionLocal()
        try:
            user = db.get(models.User, author_id)
            if user is not None and not user.is_banned:
                post, _, _ = register_post(db, user, "video", file_id,
                                           caption,
                                           thumb_file_id=thumb_id)
                notify.record(db, author_id, "post_live",
                              post_id=post.id,
                              text="Your video is now live on "
                                   "Nexora Social!")
        finally:
            db.close()
        await notify.send_message(
            send_chat_id, "✅ Your video is now live on Nexora Social!")
    except tgupload.TelegramUploadError as e:
        msg = ("Open @NexoraSocial_bot once and press Start, then try "
               "uploading your video again"
               if e.kind == "not_started" else
               "Your video could not be posted — please try again")
        await notify.send_message(send_chat_id, "⚠️ " + msg)
    except videoutil.VideoError as e:
        await notify.send_message(
            send_chat_id, "⚠️ Your video could not be posted: " + str(e))
    except Exception:
        await notify.send_message(
            send_chat_id, "⚠️ Your video could not be posted — please try again")
    finally:
        for p in (src_path, dst):
            try:
                os.unlink(p)
            except OSError:
                pass


# Phase 81: design uploads (admin-only, owner-trusted) opt out of
# media screening through this context flag; the upload helper's
# signature stays exactly as it was so callers are untouched.
_upload_screen = contextvars.ContextVar("nexora_upload_screen",
                                         default=True)


async def _telegram_upload_or_400(user, file: UploadFile, caption=""):
    """Validate an uploaded file and push it to Telegram; returns
    (kind, file_id) — or ("processing", None) for a video that needs
    transcoding, which then finishes as a background job (the caller
    answers 202). Errors are user-facing HTTPExceptions.

    Phase 19: videos no longer die on the old "MP4 only, max 20 MB"
    rule — real phone clips are bigger and often .mov/.webm. A small
    MP4 still goes straight through; anything else is transcoded to a
    compact MP4 (max 720p, sized to fit Telegram) in the background."""
    kind = tgupload.classify(file.content_type or "",
                             file.filename or "")
    if kind is None:
        raise HTTPException(
            400, "Only photos (JPG, PNG, WebP, HEIC) and videos "
                 "(MP4, MOV, WebM) are supported")
    # Phase 28 (C3): read with a hard cap. The old code buffered the
    # whole body and only then checked its length, so a single huge
    # upload could exhaust the instance's memory — the read now
    # aborts the moment the cap for the kind is exceeded.
    cap = tgupload.MAX_MEDIA_BYTES if kind == "photo" \
        else tgupload.RAW_VIDEO_MAX_BYTES
    chunks, total = [], 0
    while True:
        chunk = await file.read(256 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            raise HTTPException(
                400, "File is too large — maximum "
                     + ("20 MB" if kind == "photo" else "60 MB"))
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(400, "Empty file")
    # Phase 28 (H3): the claimed type must agree with the file's
    # actual signature (magic bytes) before anything is sent on —
    # a renamed file no longer passes as a photo or video.
    if not filesig.matches(kind, data):
        raise HTTPException(
            400, "That file's content does not match its type — "
                 "please pick a real photo or video file")
    if kind == "photo":
        if len(data) > tgupload.MAX_MEDIA_BYTES:
            raise HTTPException(400, "File is too large — maximum 20 MB")
        filename = file.filename or "upload"
        content_type = file.content_type
        # Phase 26: phone HEIC/HEIF photos become JPEG before the
        # Telegram send (sendPhoto and browsers can't use HEIC).
        if imgconv.is_heif(content_type or "", filename):
            try:
                data = imgconv.to_jpeg(data)
            except Exception:
                raise HTTPException(
                    400, "That photo could not be read — please pick "
                         "a JPG or PNG version of it")
            filename = filename.rsplit(".", 1)[0] + ".jpg"
            content_type = "image/jpeg"
        # Phase 81: screen the exact bytes that would be posted
        # (designs skip this — admin-only, owner-trusted uploads).
        if _upload_screen.get() and moderation.active():
            verdict = await asyncio.to_thread(
                moderation.classify_image, data, content_type)
            if verdict != "clean":
                sec_log.warning(
                    "media screened out (%s) for user %s",
                    verdict, user.telegram_id)
                raise HTTPException(
                    400, moderation.block_message("photo", verdict))
        return await _send_to_telegram(
            user, filename, data, content_type)
    # --- video ---
    if len(data) > tgupload.RAW_VIDEO_MAX_BYTES:
        raise HTTPException(
            400, "Video is too large — the maximum upload is 60 MB. "
                 "Please trim it or record at a lower resolution")
    # Phase 27: EVERY video takes the background path now. The old
    # small-MP4 fast path kept the phone's request open through the
    # Telegram send, and the Telegram WebView dropped such requests
    # at network level (the owner hit xhr.onerror with the file
    # already uploaded). Answering 202 the moment the bytes arrive
    # keeps the request as short as the upload itself; the job
    # transcodes (or passes through), posts, and DMs the result.
    with tempfile.NamedTemporaryFile(delete=False, suffix=".src") as f:
        f.write(data)
        src = f.name
    _schedule_video_job(_finish_video_post(
        user.telegram_id, _send_chat_id(user), src, caption))
    return "processing", None


# Phase 27: upload dedupe. When the WebView drops an upload at
# network level, the client retries once over fetch with the same
# X-Upload-Id; if the first attempt actually landed, the stored
# result is replayed instead of creating a duplicate post/design.
_upload_results = {}
_UPLOAD_TTL = 600


def _dedupe_get(user_id, upload_id):
    if not upload_id:
        return None
    hit = _upload_results.get((user_id, upload_id))
    if hit and time.time() - hit[0] < _UPLOAD_TTL:
        return hit[1], hit[2]
    _upload_results.pop((user_id, upload_id), None)
    return None


def _dedupe_put(user_id, upload_id, status_code, body):
    if upload_id:
        # Second-pass audit (R4): expired entries used to keep their
        # keys forever in this long-lived process — sweep them when
        # the store grows past a few hundred entries.
        if len(_upload_results) > 500:
            now = time.time()
            for k in [k for k, v in _upload_results.items()
                      if now - v[0] >= _UPLOAD_TTL]:
                _upload_results.pop(k, None)
        _upload_results[(user_id, upload_id)] = (
            time.time(), status_code, body)


@app.post("/posts/upload")
async def upload_post(caption: str = Form(""),
                      file: UploadFile = File(...),
                      x_upload_id: str = Header(default=""),
                      user: models.User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """Post a photo/video picked inside the app. The file is sent to
    Telegram (as the bot) to obtain its file_id, then the post is created
    exactly like a bot-submitted media post. Videos are accepted
    with 202 instead: the post (and a bot message to the member)
    follow when the background job finishes."""
    hit = _dedupe_get(user.telegram_id, x_upload_id)
    if hit:
        return JSONResponse(status_code=hit[0], content=hit[1])
    _enforce_rate("upload", f"u{user.telegram_id}")
    kind, file_id = await _telegram_upload_or_400(
        user, file, caption.strip()[:2000])
    if kind == "processing":
        body = {"status": "processing",
                "detail": "Video received — it will appear in Videos "
                          "shortly, and the bot will message you"}
        _dedupe_put(user.telegram_id, x_upload_id, 202, body)
        return JSONResponse(status_code=202, content=body)
    post, _, _ = register_post(db, user, kind, file_id,
                               caption.strip()[:2000])
    body = post_dict(db, post)
    _dedupe_put(user.telegram_id, x_upload_id, 200, body)
    return body


@app.delete("/posts/{post_id}")
def delete_post(post_id: int, user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
    p = db.get(models.Post, post_id)
    if p is None or p.is_deleted or p.user_id != user.telegram_id:
        raise HTTPException(404, "Post not found")
    p.is_deleted = True
    db.commit()
    return {"ok": True, "id": p.id}


class PostEditIn(BaseModel):
    caption: str = Field(default="", max_length=2000)


@app.post("/posts/{post_id}/edit")
def edit_post(post_id: int, body: PostEditIn,
              user: models.User = Depends(current_user),
              db: Session = Depends(get_db)):
    """Phase 59 (owner: the post ⋮ menu has no Edit). The
    author can fix the caption after posting; hashtags are
    re-extracted from the new text. Media, likes, comments,
    views and points stay untouched. Same ownership rule as
    delete: anyone else's post reads as not found."""
    p = db.get(models.Post, post_id)
    if p is None or p.is_deleted or p.user_id != user.telegram_id:
        raise HTTPException(404, "Post not found")
    p.caption = body.caption.strip()[:2000]
    p.hashtags = extract_hashtags(p.caption or "")
    db.commit()
    db.refresh(p)
    return post_dict(db, p)


@app.post("/posts/{post_id}/like")
async def toggle_like(post_id: int, user: models.User = Depends(current_user),
                      db: Session = Depends(get_db)):
    _enforce_rate("like", f"u{user.telegram_id}")
    p = get_live_post(db, post_id)
    if p.user_id != user.telegram_id and (
            _blocked_by(db, p.user_id, user.telegram_id)
            or _blocked_by(db, user.telegram_id, p.user_id)):
        raise HTTPException(403, "This member is not available")
    existing = db.query(models.Like).filter_by(
        post_id=p.id, user_id=user.telegram_id).first()
    if existing:
        db.delete(existing)
        p.like_count = max(0, (p.like_count or 0) - 1)
        liked = False
    else:
        db.add(models.Like(post_id=p.id, user_id=user.telegram_id))
        p.like_count = (p.like_count or 0) + 1
        liked = True
    db.commit()
    if liked and p.user_id != user.telegram_id:
        await notify.notify_user(
            db, p.user_id, "like",
            f"\u2764\ufe0f {user.first_name} liked your post.")
        notify.record(db, p.user_id, "like",
                      actor_id=user.telegram_id, post_id=p.id)
    return {"liked": liked, "like_count": p.like_count}


@app.post("/posts/{post_id}/view")
def view_post(post_id: int, user: models.User = Depends(current_user),
              db: Session = Depends(get_db)):
    """Phase 31 (owner request): record a UNIQUE view of a post —
    the client fires this when a video actually starts playing.
    One row per (post, viewer): rewatches never inflate the count."""
    _enforce_rate("view", f"u{user.telegram_id}")
    p = get_live_post(db, post_id)
    counted = _record_view(db, models.PostView, p.id, user.telegram_id)
    return {"views": db.query(models.PostView).filter_by(
        post_id=p.id).count(), "counted": counted}


def _record_view(db, model, fk_value, user_id):
    """Insert a unique-view row unless this viewer already has one.
    The model names its FK column after the content kind
    (post_id / design_id — the only non-user column besides id
    and created_at), which keeps this helper two lines long.
    Returns True when this call added the view."""
    fk_name = "post_id" if model is models.PostView else "design_id"
    existing = db.query(model).filter_by(
        **{fk_name: fk_value, "user_id": user_id}).first()
    if existing:
        return False
    db.add(model(**{fk_name: fk_value, "user_id": user_id}))
    try:
        db.commit()
    except Exception:
        db.rollback()
        return False
    return True


@app.post("/posts/{post_id}/save")
def toggle_save(post_id: int, user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
    """Bookmark toggle behind the video/post options menu (Save)."""
    p = get_live_post(db, post_id)
    existing = db.query(models.SavedPost).filter_by(
        post_id=p.id, user_id=user.telegram_id).first()
    if existing:
        db.delete(existing)
        saved = False
    else:
        db.add(models.SavedPost(post_id=p.id, user_id=user.telegram_id))
        saved = True
    db.commit()
    return {"saved": saved, "post_id": p.id}


@app.get("/me/saved")
def my_saved(user: models.User = Depends(current_user),
             db: Session = Depends(get_db)):
    rows = db.query(models.Post).join(
        models.SavedPost, models.SavedPost.post_id == models.Post.id) \
        .filter(models.SavedPost.user_id == user.telegram_id,
                models.Post.is_deleted == False) \
        .order_by(models.SavedPost.id.desc()).limit(50).all()
    liked = liked_ids(db, user.telegram_id, rows)
    return {"posts": [post_dict(db, p, liked=p.id in liked, saved=True)
                      for p in rows]}


@app.get("/me/following")
def my_following(user: models.User = Depends(current_user),
                 db: Session = Depends(get_db)):
    """People the viewer follows — the share picker's default list."""
    rows = db.query(models.User).join(
        models.Follow, models.Follow.following_id == models.User.telegram_id) \
        .filter(models.Follow.follower_id == user.telegram_id,
                models.User.telegram_id != OFFICIAL_ID) \
        .order_by(models.User.first_name).limit(100).all()
    return {"users": [{
        "telegram_id": u.telegram_id, "first_name": u.first_name,
        "username": u.username, "is_verified": bool(u.is_verified),
        "photo_file_id": u.photo_file_id,
    } for u in rows]}


class ShareIn(BaseModel):
    to_user_id: int


@app.post("/posts/{post_id}/share")
async def share_post(post_id: int, body: ShareIn,
                     user: models.User = Depends(current_user),
                     db: Session = Depends(get_db)):
    _enforce_rate("share", f"u{user.telegram_id}")
    """Send a post to another member inside the app (owner request,
    Oct 31): it lands in their 'Shared with me' inbox and they get a
    bot notification."""
    p = get_live_post(db, post_id)
    if body.to_user_id == user.telegram_id:
        raise HTTPException(400, "You cannot share to yourself")
    target = db.get(models.User, body.to_user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    if _blocked_by(db, body.to_user_id, user.telegram_id) \
            or _blocked_by(db, user.telegram_id, body.to_user_id):
        raise HTTPException(403, "This member is not available")
    db.add(models.PostShare(post_id=p.id, from_user_id=user.telegram_id,
                            to_user_id=body.to_user_id))
    db.commit()
    snippet = (p.caption or "")[:80]
    await notify.notify_user(
        db, body.to_user_id, "share",
        f"\U0001F4E4 {user.first_name} shared a "
        f"{'video' if p.type == 'video' else 'post'} with you in "
        f"Nexora Social{f': {snippet}' if snippet else ''}")
    notify.record(db, body.to_user_id, "share",
                  actor_id=user.telegram_id, post_id=p.id)
    return {"ok": True, "post_id": p.id, "to_user_id": body.to_user_id}


@app.get("/me/shared")
def my_shared(user: models.User = Depends(current_user),
              db: Session = Depends(get_db)):
    shares = db.query(models.PostShare).filter_by(
        to_user_id=user.telegram_id) \
        .order_by(models.PostShare.id.desc()).limit(50).all()
    out = []
    for s in shares:
        p = db.get(models.Post, s.post_id)
        if p is None or p.is_deleted:
            continue
        sender = db.get(models.User, s.from_user_id)
        d = post_dict(db, p,
                      liked=s.post_id in liked_ids(db, user.telegram_id, [p]),
                      saved=s.post_id in saved_ids(db, user.telegram_id, [p]))
        d["shared_by_id"] = s.from_user_id
        d["shared_by_name"] = sender.first_name if sender else ""
        d["shared_at"] = s.created_at.isoformat() if s.created_at else None
        out.append(d)
    return {"posts": out}


class CommentIn(BaseModel):
    text: str = Field(max_length=1000)


def comment_dict(db, cm):
    author = db.get(models.User, cm.user_id)
    return {
        "id": cm.id, "post_id": cm.post_id, "user_id": cm.user_id,
        "author_name": author.first_name if author else "",
        "author_username": author.username if author else None,
        "author_verified": bool(author and author.is_verified),
        "author_photo": author.photo_file_id if author else None,
        "text": cm.text,
        "created_at": cm.created_at.isoformat() if cm.created_at else None,
    }


@app.get("/posts/{post_id}/comments")
def list_comments(post_id: int, user: models.User = Depends(current_user),
                  db: Session = Depends(get_db)):
    p = get_live_post(db, post_id)
    # Second-pass audit (R1): this was the one unbounded list in the
    # API — a post with tens of thousands of comments returned all
    # of them at once. Now the LATEST 500, in reading order.
    rows = db.query(models.Comment).filter_by(post_id=p.id) \
        .order_by(models.Comment.id.desc()).limit(500).all()
    rows.reverse()
    return {"comments": [comment_dict(db, cm) for cm in rows]}


@app.post("/posts/{post_id}/comments")
async def add_comment(post_id: int, body: CommentIn,
                      user: models.User = Depends(current_user),
                      db: Session = Depends(get_db)):
    _enforce_rate("comment", f"u{user.telegram_id}")
    p = get_live_post(db, post_id)
    if p.user_id != user.telegram_id and (
            _blocked_by(db, p.user_id, user.telegram_id)
            or _blocked_by(db, user.telegram_id, p.user_id)):
        raise HTTPException(403, "This member is not available")
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Comment text is empty")
    cm = models.Comment(post_id=p.id, user_id=user.telegram_id, text=text)
    db.add(cm)
    p.comment_count = (p.comment_count or 0) + 1
    db.commit()
    db.refresh(cm)
    if p.user_id != user.telegram_id:
        await notify.notify_user(
            db, p.user_id, "comment",
            f"\U0001F4AC {user.first_name} commented on your post: {text[:80]}")
        notify.record(db, p.user_id, "comment",
                      actor_id=user.telegram_id, post_id=p.id)
    return comment_dict(db, cm)


# ---------------------------------------------------------------------------
# Profiles and follows (PRD section 4, MVP items 2 and 6)
# ---------------------------------------------------------------------------

@app.get("/users/{telegram_id}")
def public_profile(telegram_id: int, user: models.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    target = db.get(models.User, telegram_id)
    if target is None:
        raise HTTPException(404, "User not found")
    # R5: a member who blocked you cannot be viewed by you — the
    # profile simply does not exist from your side.
    if _blocked_by(db, telegram_id, user.telegram_id):
        raise HTTPException(404, "User not found")
    followers = db.query(models.Follow).filter_by(following_id=telegram_id).count()
    if telegram_id == OFFICIAL_ID:
        followers += OFFICIAL_FOLLOWER_BASE  # official account starts at 10k
    following_count = db.query(models.Follow).filter_by(follower_id=telegram_id).count()
    posts = db.query(models.Post).filter_by(
        user_id=telegram_id, is_deleted=False).count()
    is_following = db.query(models.Follow).filter_by(
        follower_id=user.telegram_id, following_id=telegram_id).first() is not None
    # Phase 42: for your own profile, the days left on the
    # 60-day name-change lock (0 = the name can change now).
    name_locked_days = 0
    if telegram_id == user.telegram_id and target.name_changed_at:
        left = 60 * 86400 - (datetime.utcnow()
                             - target.name_changed_at).total_seconds()
        if left > 0:
            name_locked_days = int(left // 86400) + 1
    return {
        "telegram_id": target.telegram_id,
        "first_name": target.first_name,
        "username": target.username,
        "bio": target.bio,
        "photo_file_id": target.photo_file_id,
        "cover_file_id": target.cover_file_id,
        "points": target.points_balance,
        "is_verified": bool(target.is_verified),
        "is_official": telegram_id == OFFICIAL_ID,
        "posts": posts,
        "followers": followers,
        "following_count": following_count,
        # "following" is the flag: does the current user follow this profile.
        "following": is_following,
        # R5: whether the viewer has blocked this member (the
        # profile offers Block/Unblock from this flag).
        "blocked_by_me": _blocked_by(db, user.telegram_id, telegram_id),
        "name_locked_days": name_locked_days,
    }


@app.post("/users/{telegram_id}/follow")
async def toggle_follow(telegram_id: int, user: models.User = Depends(current_user),
                        db: Session = Depends(get_db)):
    _enforce_rate("follow", f"u{user.telegram_id}")
    if telegram_id == user.telegram_id:
        raise HTTPException(400, "You cannot follow yourself")
    if db.get(models.User, telegram_id) is None:
        raise HTTPException(404, "User not found")
    if _blocked_by(db, telegram_id, user.telegram_id) \
            or _blocked_by(db, user.telegram_id, telegram_id):
        raise HTTPException(403, "This member is not available")
    existing = db.query(models.Follow).filter_by(
        follower_id=user.telegram_id, following_id=telegram_id).first()
    if telegram_id == OFFICIAL_ID and existing:
        raise HTTPException(
            400, "The official Nexora Social account cannot be unfollowed")
    if existing:
        db.delete(existing)
        now_following = False
    else:
        db.add(models.Follow(follower_id=user.telegram_id,
                             following_id=telegram_id))
        now_following = True
    db.commit()
    followers = db.query(models.Follow).filter_by(following_id=telegram_id).count()
    if telegram_id == OFFICIAL_ID:
        followers += OFFICIAL_FOLLOWER_BASE
    if now_following:
        await notify.notify_user(
            db, telegram_id, "follow",
            f"\U0001F465 {user.first_name} started following you.")
        notify.record(db, telegram_id, "follow",
                      actor_id=user.telegram_id)
    return {"following": now_following, "followers": followers}


# ---------------------------------------------------------------------------
# Blocking (second-pass audit R5, security §5/§6): a member's
# self-help control against harassment. Blocking hides both sides'
# content from each other, removes follows in both directions, and
# refuses new follows/comments/likes/shares between the two.
# ---------------------------------------------------------------------------

@app.post("/users/{telegram_id}/block")
def toggle_block(telegram_id: int,
                 user: models.User = Depends(current_user),
                 db: Session = Depends(get_db)):
    if telegram_id == user.telegram_id:
        raise HTTPException(400, "You cannot block yourself")
    if telegram_id == OFFICIAL_ID:
        raise HTTPException(
            400, "The official Nexora Social account cannot be blocked")
    if db.get(models.User, telegram_id) is None:
        raise HTTPException(404, "User not found")
    existing = db.query(models.UserBlock).filter_by(
        blocker_id=user.telegram_id, blocked_id=telegram_id).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"blocked": False}
    db.add(models.UserBlock(blocker_id=user.telegram_id,
                            blocked_id=telegram_id))
    # A block ends the follow relationship in both directions.
    db.query(models.Follow).filter(or_(
        (models.Follow.follower_id == user.telegram_id)
        & (models.Follow.following_id == telegram_id),
        (models.Follow.follower_id == telegram_id)
        & (models.Follow.following_id == user.telegram_id),
    )).delete(synchronize_session=False)
    db.commit()
    return {"blocked": True}


@app.get("/me/blocked")
def my_blocked(user: models.User = Depends(current_user),
               db: Session = Depends(get_db)):
    rows = db.query(models.UserBlock).filter_by(
        blocker_id=user.telegram_id) \
        .order_by(models.UserBlock.id.desc()).limit(200).all()
    out = []
    for r in rows:
        bu = db.get(models.User, r.blocked_id)
        out.append({
            "telegram_id": r.blocked_id,
            "first_name": bu.first_name if bu else "",
            "username": bu.username if bu else None,
            "photo_file_id": bu.photo_file_id if bu else None,
        })
    return {"blocked": out}


# ---------------------------------------------------------------------------
# Referrals, points, search, reports (PRD sections 4-5, MVP items 8-10)
# ---------------------------------------------------------------------------

@app.post("/me/photo/sync")
async def sync_photo(user: models.User = Depends(current_user),
                     db: Session = Depends(get_db)):
    """Pull the member's Telegram profile picture (file_id) so profiles
    show the real photo. Runs when the app opens and no photo is stored
    yet; the actual Bot API fetch needs the live token."""
    from . import photosync
    if not user.photo_file_id:
        fid = await photosync.fetch_telegram_photo_file_id(user.telegram_id)
        if fid:
            user.photo_file_id = fid
            db.commit()
    return {"photo_file_id": user.photo_file_id}


@app.post("/me/photo/upload")
async def upload_my_photo(file: UploadFile = File(...),
                          user: models.User = Depends(current_user),
                          db: Session = Depends(get_db)):
    """Set the member's profile picture from a photo picked in the app.
    The upload goes to Telegram (as the bot) for its file_id; the new
    photo then appears everywhere avatars render."""
    if tgupload.classify(file.content_type or "",
                         file.filename or "") != "photo":
        raise HTTPException(400, "Please choose a photo (JPG, PNG, WebP or HEIC)")
    _enforce_rate("upload", f"u{user.telegram_id}")
    _, file_id = await _telegram_upload_or_400(user, file)
    user.photo_file_id = file_id
    db.commit()
    return {"photo_file_id": file_id}


@app.post("/me/cover/upload")
async def upload_my_cover(file: UploadFile = File(...),
                          user: models.User = Depends(current_user),
                          db: Session = Depends(get_db)):
    """Phase 40 (owner: a cover photo option on the profile).
    Mirrors the profile-photo upload: the image goes to Telegram
    for its file_id and shows as the banner atop the profile."""
    if tgupload.classify(file.content_type or "",
                         file.filename or "") != "photo":
        raise HTTPException(400, "Please choose a photo (JPG, PNG, WebP or HEIC)")
    _enforce_rate("upload", f"u{user.telegram_id}")
    _, file_id = await _telegram_upload_or_400(user, file)
    user.cover_file_id = file_id
    db.commit()
    return {"cover_file_id": file_id}


class MyProfileIn(BaseModel):
    first_name: Optional[str] = Field(default=None, max_length=128)
    bio: Optional[str] = Field(default=None, max_length=500)


@app.post("/me/profile")
def edit_my_profile(body: MyProfileIn,
                    user: models.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    """Phase 40 (owner: the bio must be writable by the member).
    Self-service name + bio editing — until now only an admin
    could change a bio (Phase 24).

    Phase 42 (owner): the name may change only ONCE every 60
    days. An unchanged name never trips (or consumes) the rule,
    so bio-only edits stay free at all times; the admin panel
    keeps its unrestricted override."""
    if body.first_name is not None:
        name = body.first_name.strip()
        if not name:
            raise HTTPException(400, "Name can't be empty")
        if name != (user.first_name or ""):
            if user.name_changed_at is not None:
                elapsed = (datetime.utcnow()
                           - user.name_changed_at).total_seconds()
                wait = 60 * 86400 - elapsed
                if wait > 0:
                    days = int(wait // 86400) + 1
                    raise HTTPException(
                        400, "Name can be changed once every 60 days"
                             f" — try again in {days} day"
                             f"{'s' if days != 1 else ''}")
            user.first_name = name
            user.name_changed_at = datetime.utcnow()
    if body.bio is not None:
        user.bio = body.bio.strip()
    db.commit()
    return {"first_name": user.first_name, "bio": user.bio or ""}


@app.get("/me/referrals")
def my_referrals(user: models.User = Depends(current_user),
                 db: Session = Depends(get_db)):
    # Second-pass audit (R2): cap the page at the newest 200 and
    # report the true total from a count, not from the page length.
    total = db.query(models.Referral).filter_by(
        referrer_id=user.telegram_id).count()
    rows = db.query(models.Referral).filter_by(
        referrer_id=user.telegram_id) \
        .order_by(models.Referral.id.desc()).limit(200).all()
    rows.reverse()
    out = []
    for r in rows:
        nu = db.get(models.User, r.new_user_id)
        out.append({
            "new_user_id": r.new_user_id,
            "first_name": nu.first_name if nu else "",
            "username": nu.username if nu else None,
            "qualified": bool(r.qualified),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {"referrals": out, "total": total}


@app.get("/me/points")
def my_points(user: models.User = Depends(current_user),
              db: Session = Depends(get_db)):
    me = db.get(models.User, user.telegram_id)
    rows = db.query(models.PointsLedger).filter_by(user_id=user.telegram_id) \
        .order_by(models.PointsLedger.id.desc()).limit(20).all()
    return {
        "balance": me.points_balance if me else 0,
        "entries": [{
            "id": e.id, "amount": e.amount, "reason": e.reason,
            "ref_id": e.ref_id,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e in rows],
    }


@app.get("/search")
def search(q: str = "", user: models.User = Depends(current_user),
           db: Session = Depends(get_db)):
    _enforce_rate("search", f"u{user.telegram_id}")
    q = q.strip()[:100]
    hidden = _block_related_ids(db, user.telegram_id)
    if q.startswith("#"):
        tag = q[1:].lower()
        if not tag:
            return {"users": [], "posts": []}
        rows = db.query(models.Post).filter_by(is_deleted=False) \
            .order_by(models.Post.id.desc()).limit(100).all()
        matched = [p for p in rows
                   if tag in (p.hashtags or "").split()
                   and p.user_id not in hidden][:20]
        liked = liked_ids(db, user.telegram_id, matched)
        saved = saved_ids(db, user.telegram_id, matched)
        return {"users": [], "posts": [post_dict(db, p, liked=p.id in liked,
                                                 saved=p.id in saved)
                                       for p in matched]}
    if not q:
        return {"users": [], "posts": []}
    like = _like_pattern(q)
    users = db.query(models.User).filter(
        (models.User.first_name.ilike(like, escape="\\"))
        | (models.User.username.ilike(like, escape="\\"))).limit(20).all()
    if hidden:
        users = [u for u in users if u.telegram_id not in hidden]
    return {
        "users": [{
            "telegram_id": u.telegram_id, "first_name": u.first_name,
            "username": u.username, "bio": u.bio,
            "is_verified": bool(u.is_verified),
            "photo_file_id": u.photo_file_id,
        } for u in users],
        "posts": [],
    }


class ReportIn(BaseModel):
    post_id: int
    reason: str = Field(default="", max_length=256)


@app.post("/reports")
def create_report(body: ReportIn, user: models.User = Depends(current_user),
                  db: Session = Depends(get_db)):
    _enforce_rate("report", f"u{user.telegram_id}")
    p = db.get(models.Post, body.post_id)
    if p is None or p.is_deleted:
        raise HTTPException(404, "Post not found")
    rep = models.Report(post_id=p.id, reporter_id=user.telegram_id,
                        reason=body.reason)
    db.add(rep)
    db.commit()
    db.refresh(rep)
    return {
        "id": rep.id, "post_id": rep.post_id, "reporter_id": rep.reporter_id,
        "reason": rep.reason, "status": rep.status,
    }


@app.get("/users/{telegram_id}/posts")
def user_posts(telegram_id: int, cursor: int = 0,
               user: models.User = Depends(current_user),
               db: Session = Depends(get_db)):
    if db.get(models.User, telegram_id) is None \
            or _blocked_by(db, telegram_id, user.telegram_id):
        raise HTTPException(404, "User not found")
    q = db.query(models.Post).filter_by(user_id=telegram_id, is_deleted=False)
    if cursor:
        q = q.filter(models.Post.id < cursor)
    rows = q.order_by(models.Post.id.desc()).limit(20).all()
    liked = liked_ids(db, user.telegram_id, rows)
    saved = saved_ids(db, user.telegram_id, rows)
    counts = _post_view_counts(db, rows)
    _warm_authors(db, rows)
    return {"posts": [post_dict(db, p, liked=p.id in liked,
                                saved=p.id in saved,
                                views=counts.get(p.id, 0))
                      for p in rows],
            "next_cursor": rows[-1].id if len(rows) == 20 else None}


@app.get("/leaderboard")
def leaderboard(user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
    rows = db.query(models.User).filter_by(is_banned=False) \
        .order_by(models.User.points_balance.desc(),
                  models.User.telegram_id).limit(50).all()
    out = [{"rank": i + 1, "telegram_id": u.telegram_id,
            "first_name": u.first_name, "username": u.username,
            "points": u.points_balance,
            "is_verified": bool(u.is_verified),
            "photo_file_id": u.photo_file_id} for i, u in enumerate(rows)]
    mine = next((r for r in out if r["telegram_id"] == user.telegram_id), None)
    if mine is None:
        higher = db.query(models.User).filter(
            models.User.points_balance > user.points_balance).count()
        mine = {"rank": higher + 1, "telegram_id": user.telegram_id,
                "first_name": user.first_name, "username": user.username,
                "points": user.points_balance,
                "is_verified": bool(user.is_verified),
                "photo_file_id": user.photo_file_id}
    return {"leaders": out, "me": mine}


# ---------------------------------------------------------------------------
# Daily tasks (owner request, Oct 31): small daily goals that pay points,
# each claimable ONCE per day. Progress is counted from today's real
# activity; the claim is guarded by the daily_claims unique row.
# ---------------------------------------------------------------------------

def _today():
    now = datetime.utcnow()
    return now.date().isoformat(), now.replace(hour=0, minute=0, second=0,
                                               microsecond=0)


def _task_progress(db, user_id, task, day_start, claimed):
    metric = task["metric"]
    if metric == "checkin":
        return 1 if claimed else 0
    if metric == "follows":
        return db.query(models.Follow).filter(
            models.Follow.follower_id == user_id,
            models.Follow.created_at >= day_start).count()
    if metric == "comments":
        return db.query(models.Comment).filter(
            models.Comment.user_id == user_id,
            models.Comment.created_at >= day_start).count()
    return 0


def _checkin_streak(db, user_id):
    """Consecutive days with a check-in claim, ending today (or yesterday
    if today is not claimed yet — the streak is still alive until the day
    ends). One missed day breaks it: the count simply stops there."""
    days = {r[0] for r in db.query(models.DailyClaim.day).filter_by(
        user_id=user_id, task_key="checkin").all()}
    cur = datetime.utcnow().date()
    if cur.isoformat() not in days:
        cur -= timedelta(days=1)
    streak = 0
    while cur.isoformat() in days:
        streak += 1
        cur -= timedelta(days=1)
    return streak


def _task_state(db, user, task):
    day, day_start = _today()
    claimed = db.query(models.DailyClaim).filter_by(
        user_id=user.telegram_id, task_key=task["key"], day=day).first()
    progress = _task_progress(db, user.telegram_id, task, day_start,
                              bool(claimed))
    state = {
        "key": task["key"], "title": task["title"], "icon": task["icon"],
        "target": task["target"], "points": task["points"],
        "progress": min(progress, task["target"]),
        "claimed": bool(claimed),
        "claimable": (not claimed) and (
            task["metric"] == "checkin" or progress >= task["target"]),
    }
    if task["metric"] == "checkin":
        state["streak"] = _checkin_streak(db, user.telegram_id)
    return state


@app.get("/me/tasks")
def my_tasks(user: models.User = Depends(current_user),
             db: Session = Depends(get_db)):
    return {"tasks": [_task_state(db, user, t) for t in DAILY_TASKS]}


@app.post("/me/tasks/{key}/claim")
def claim_task(key: str, user: models.User = Depends(current_user),
               db: Session = Depends(get_db)):
    task = next((t for t in DAILY_TASKS if t["key"] == key), None)
    if task is None:
        raise HTTPException(404, "Unknown task")
    state = _task_state(db, user, task)
    if state["claimed"]:
        raise HTTPException(400, "Already claimed today")
    if not state["claimable"]:
        raise HTTPException(400, "Task not completed yet")
    day, _ = _today()
    db.add(models.DailyClaim(user_id=user.telegram_id, task_key=key, day=day))
    award_points(db, user.telegram_id, task["points"], f"task:{key}")
    db.commit()
    db.refresh(user)
    return {"ok": True, "points_awarded": task["points"],
            "balance": user.points_balance}


# ---------------------------------------------------------------------------
# Monetization gate (owner request, Oct 31): a creator unlocks monetization
# only after meeting every target in config.MONETIZATION. This endpoint is
# the status/checklist; payouts themselves are a later phase.
# ---------------------------------------------------------------------------

@app.get("/me/monetization")
def my_monetization(user: models.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    followers = db.query(models.Follow).filter_by(
        following_id=user.telegram_id).count()
    # Phase 58 (owner): a 6th gate target — QUALIFIED referrals
    # only (a referral qualifies when the new member posts,
    # the same rule that pays the referral points).
    referrals = db.query(models.Referral).filter_by(
        referrer_id=user.telegram_id, qualified=True).count()
    posts = db.query(models.Post).filter_by(
        user_id=user.telegram_id, is_deleted=False).count()
    age_days = (datetime.utcnow() - user.created_at).days \
        if user.created_at else 0
    # SQL aggregate instead of loading the member's whole ledger
    # into Python to sum it (second-pass audit, perf hygiene).
    earned = db.query(func.coalesce(func.sum(
        models.PointsLedger.amount), 0)).filter(
        models.PointsLedger.user_id == user.telegram_id,
        models.PointsLedger.amount > 0).scalar()
    checks = [
        {"key": "followers", "label": "Followers",
         "current": followers, "required": MONETIZATION["followers"]},
        {"key": "referrals", "label": "Referrals",
         "current": referrals, "required": MONETIZATION["referrals"]},
        {"key": "posts", "label": "Posts published",
         "current": posts, "required": MONETIZATION["posts"]},
        {"key": "account_days", "label": "Account age (days)",
         "current": age_days, "required": MONETIZATION["account_days"]},
        {"key": "lifetime_points", "label": "Total points earned",
         "current": earned, "required": MONETIZATION["lifetime_points"]},
        {"key": "checkin_streak", "label": "Check-in streak (days, no misses)",
         "current": _checkin_streak(db, user.telegram_id),
         "required": MONETIZATION["checkin_streak"]},
    ]
    for c in checks:
        c["done"] = c["current"] >= c["required"]
    return {"unlocked": all(c["done"] for c in checks), "checks": checks}


# ---------------------------------------------------------------------------
# Phase 22: verification (blue tick) applications. A member with at
# least VERIFICATION_MIN_FOLLOWERS followers may apply from their Me
# page; the admin reviews applications in the Admin Panel.
# ---------------------------------------------------------------------------

def _followers_count(db, telegram_id):
    return db.query(models.Follow).filter_by(
        following_id=telegram_id).count()


def _pending_verification(db, telegram_id):
    return db.query(models.VerificationRequest).filter_by(
        user_id=telegram_id, status="pending") \
        .order_by(models.VerificationRequest.id.desc()).first()


@app.get("/me/verification")
def my_verification(user: models.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    followers = _followers_count(db, user.telegram_id)
    latest = db.query(models.VerificationRequest).filter_by(
        user_id=user.telegram_id) \
        .order_by(models.VerificationRequest.id.desc()).first()
    pending = latest if latest and latest.status == "pending" else None
    return {
        "followers": followers,
        "required": VERIFICATION_MIN_FOLLOWERS,
        "is_verified": bool(user.is_verified),
        "pending": pending is not None,
        "last_status": latest.status if latest else None,
        "can_apply": (not user.is_verified and pending is None
                      and followers >= VERIFICATION_MIN_FOLLOWERS),
    }


@app.post("/me/verification/apply")
def apply_verification(user: models.User = Depends(current_user),
                       db: Session = Depends(get_db)):
    if user.is_verified:
        raise HTTPException(400, "Your account is already verified")
    followers = _followers_count(db, user.telegram_id)
    if followers < VERIFICATION_MIN_FOLLOWERS:
        raise HTTPException(
            400, f"You need {VERIFICATION_MIN_FOLLOWERS} followers to "
                 f"apply for the blue tick (you have {followers})")
    if _pending_verification(db, user.telegram_id):
        raise HTTPException(400, "Your application is already pending")
    db.add(models.VerificationRequest(user_id=user.telegram_id))
    db.commit()
    return {"ok": True, "status": "pending"}


# ---------------------------------------------------------------------------
# Phase 19: usage analytics — heartbeat time tracking + ad impressions.
# The dashboard reads user_activity / ad_events; see /admin/dashboard.
# ---------------------------------------------------------------------------

@app.post("/me/theme")
def save_my_theme(body: ThemeIn, user: models.User = Depends(current_user),
                  db: Session = Depends(get_db)):
    """Phase 96: save THIS member's Theme Colours picks on their own
    account. Only the caller's row is touched."""
    _enforce_rate("theme", f"u{user.telegram_id}")
    picks = {"bg": None, "card": None, "accent": None}
    incoming = body.picks or {}
    for zone in picks:
        v = incoming.get(zone)
        if v is None:
            continue
        if not isinstance(v, str) or not _THEME_ID_RE.match(v):
            raise HTTPException(422, "Invalid theme shade")
        picks[zone] = v
    user.theme = None if not any(picks.values()) else json.dumps(picks)
    db.commit()
    return {"ok": True, "theme": picks}


@app.post("/me/heartbeat")
def heartbeat(user: models.User = Depends(current_user),
              db: Session = Depends(get_db)):
    """The Mini App beats every ~30s while open. Each beat credits the
    seconds since the previous beat (capped at 120s, so a forgotten
    background tab cannot inflate the numbers); a beat after a longer
    gap starts a new session instead of crediting the gap."""
    _enforce_rate("heartbeat", f"u{user.telegram_id}")
    now = datetime.utcnow()
    user.last_seen_at = now
    day = now.date().isoformat()
    row = db.query(models.UserActivity).filter_by(
        user_id=user.telegram_id, day=day).first()
    if row is None:
        row = models.UserActivity(user_id=user.telegram_id, day=day,
                                  seconds=0, sessions=1, last_beat_at=now)
        db.add(row)
    else:
        if row.last_beat_at is not None:
            delta = (now - row.last_beat_at).total_seconds()
            if 0 <= delta <= 120:
                row.seconds += int(delta)
            elif delta > 120:
                row.sessions += 1
        row.last_beat_at = now
    db.commit()
    return {"ok": True, "seconds_today": row.seconds,
            "sessions_today": row.sessions}


@app.post("/ads/shown")
def ad_shown(user: models.User = Depends(current_user),
             db: Session = Depends(get_db)):
    """The Mini App reports each interstitial that actually finished
    showing. Reports closer than 5s together count once (SDK retries
    and double-fires must not inflate the owner's ad figures)."""
    _enforce_rate("ad_shown", f"u{user.telegram_id}")
    now = datetime.utcnow()
    last = db.query(models.AdEvent).filter_by(
        user_id=user.telegram_id) \
        .order_by(models.AdEvent.id.desc()).first()
    if last is not None and (now - last.created_at).total_seconds() < 5:
        return {"ok": True, "counted": False}
    db.add(models.AdEvent(user_id=user.telegram_id))
    db.commit()
    return {"ok": True, "counted": True}


# ---------------------------------------------------------------------------
# Phase 20: in-app notifications (the 🔔 list). Until now members only
# got bot DMs; this is the same events, readable inside the app.
# ---------------------------------------------------------------------------

_NOTIF_PHRASES = {
    "like": "liked your post",
    "comment": "commented on your post",
    "follow": "started following you",
    "share": "shared a post with you",
    "post_live": "Your video is now live",
    "announcement": "Announcement",
    "verification": "Verification update",
}


@app.get("/me/notifications")
def my_notifications(cursor: int = 0, limit: int = 30,
                     user: models.User = Depends(current_user),
                     db: Session = Depends(get_db)):
    unread = db.query(models.Notification).filter_by(
        user_id=user.telegram_id, is_read=False).count()
    q = db.query(models.Notification).filter_by(
        user_id=user.telegram_id)
    if cursor:
        q = q.filter(models.Notification.id < cursor)
    rows = q.order_by(models.Notification.id.desc()) \
        .limit(max(1, min(limit, 50))).all()
    out = []
    for n in rows:
        actor = db.get(models.User, n.actor_id) if n.actor_id else None
        out.append({
            "id": n.id, "type": n.type, "post_id": n.post_id,
            "text": n.text or _NOTIF_PHRASES.get(n.type, ""),
            "is_read": bool(n.is_read),
            "actor_id": n.actor_id,
            "actor_name": actor.first_name if actor else None,
            "actor_username": actor.username if actor else None,
            "actor_photo": actor.photo_file_id if actor else None,
            "actor_verified": bool(actor.is_verified) if actor else False,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        })
    return {"notifications": out, "unread_count": unread,
            "next_cursor": rows[-1].id if len(rows) == limit else None}


@app.post("/me/notifications/read")
def my_notifications_read(user: models.User = Depends(current_user),
                          db: Session = Depends(get_db)):
    db.query(models.Notification).filter_by(
        user_id=user.telegram_id, is_read=False) \
        .update({"is_read": True})
    db.commit()
    return {"ok": True, "unread_count": 0}


# ---------------------------------------------------------------------------
# Admin and moderation (PRD section 4, MVP item 10). Admins are the
# telegram ids listed in the ADMIN_IDS env var.
# ---------------------------------------------------------------------------

def admin_user(user: models.User = Depends(current_user)):
    if user.telegram_id not in settings.ADMIN_IDS:
        sec_log.warning("admin route denied for user %s",
                        user.telegram_id)
        raise HTTPException(403, "Admins only")
    return user


def moderator_user(user: models.User = Depends(current_user)):
    """Phase 28 (M1, least privilege): moderators get the moderation
    subset only — reports, comment/post removal, bans. Points, verify
    grants, profile edits, member deletion, broadcasts, managed
    users and verification decisions stay ADMIN_IDS-only."""
    if user.telegram_id not in settings.ADMIN_IDS \
            and user.telegram_id not in settings.MODERATOR_IDS:
        sec_log.warning("moderator route denied for user %s",
                        user.telegram_id)
        raise HTTPException(403, "Moderators only")
    return user


class BanIn(BaseModel):
    telegram_id: int
    banned: bool = True


@app.post("/admin/ban")
def admin_ban(body: BanIn, admin: models.User = Depends(moderator_user),
              db: Session = Depends(get_db)):
    if body.banned and (body.telegram_id == OFFICIAL_ID
                        or body.telegram_id in settings.ADMIN_IDS):
        raise HTTPException(400, "The official account and admins cannot be banned")
    if body.banned and body.telegram_id in settings.MODERATOR_IDS \
            and admin.telegram_id not in settings.ADMIN_IDS:
        raise HTTPException(403, "Only an admin can ban a moderator")
    target = db.get(models.User, body.telegram_id)
    if target is None:
        raise HTTPException(404, "User not found")
    target.is_banned = body.banned
    _audit(db, admin, "ban" if body.banned else "unban",
           target_id=target.telegram_id)
    db.commit()
    return {"telegram_id": target.telegram_id, "is_banned": target.is_banned}


@app.get("/admin/dashboard")
def admin_dashboard(admin: models.User = Depends(admin_user),
                    db: Session = Depends(get_db)):
    """Phase 19 owner dashboard: member totals, signups, who is active
    and when, time-in-app, countries/languages and ad impressions.
    The official account is excluded from member figures. Country is
    IP-approximated at sign-in (Telegram shares only the language);
    time and ads are counted from Phase 19 onward — no backfill."""
    now = datetime.utcnow()
    today = now.date()
    today_start = datetime(today.year, today.month, today.day)
    members = db.query(models.User).filter(
        models.User.telegram_id != OFFICIAL_ID)

    def day_series(model_col, rows_by_day, days=14):
        out = []
        for i in range(days - 1, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            out.append({"day": d, "count": rows_by_day.get(d, 0)})
        return out

    signup_rows = db.query(models.User).filter(
        models.User.telegram_id != OFFICIAL_ID,
        models.User.created_at >= today_start - timedelta(days=14)).all()
    signups_by_day = {}
    for u in signup_rows:
        if u.created_at:
            k = u.created_at.date().isoformat()
            signups_by_day[k] = signups_by_day.get(k, 0) + 1
    act_rows = db.query(models.UserActivity).filter(
        models.UserActivity.day >= (today - timedelta(days=14)).isoformat(),
        models.UserActivity.user_id != OFFICIAL_ID).all()
    active_by_day = {}
    for r in act_rows:
        active_by_day[r.day] = active_by_day.get(r.day, 0) + 1

    def grouped(col):
        rows = db.query(col, func.count()).filter(
            models.User.telegram_id != OFFICIAL_ID) \
            .group_by(col).order_by(func.count().desc()).limit(12).all()
        return [{"name": (name or "Unknown"), "count": n}
                for name, n in rows]

    today_key = today.isoformat()
    act_today = [r for r in act_rows if r.day == today_key]
    time_today = sum(r.seconds for r in act_today)
    top_time = []
    for r in sorted(act_today, key=lambda r: -r.seconds)[:5]:
        u = db.get(models.User, r.user_id)
        if u:
            top_time.append({"telegram_id": u.telegram_id,
                             "first_name": u.first_name,
                             "username": u.username,
                             "seconds": r.seconds,
                             "sessions": r.sessions})
    return {
        "total_members": members.count(),
        "managed_members": members.filter(
            models.User.is_managed.is_(True)).count(),
        "new_today": members.filter(
            models.User.created_at >= today_start).count(),
        "active_now": members.filter(
            models.User.last_seen_at >= now - timedelta(minutes=10)).count(),
        "active_last_hour": members.filter(
            models.User.last_seen_at >= now - timedelta(minutes=60)).count(),
        "active_today": members.filter(
            models.User.last_seen_at >= today_start).count(),
        "posts": db.query(models.Post).filter_by(is_deleted=False).count(),
        "ads_today": db.query(models.AdEvent).filter(
            models.AdEvent.created_at >= today_start).count(),
        "ads_total": db.query(models.AdEvent).count(),
        "time_today_seconds": time_today,
        "avg_time_today_seconds":
            time_today // len(act_today) if act_today else 0,
        "countries": grouped(models.User.country),
        "languages": grouped(models.User.language_code),
        "signups_14d": day_series(None, signups_by_day),
        "active_14d": day_series(None, active_by_day),
        "top_time_today": top_time,
    }


def _ad_rate(db: Session) -> float:
    """The owner-set earnings rate (BDT per 1000 ad impressions),
    0 until the owner sets it in the Earning Panel."""
    row = db.get(models.AppSetting, "ad_rate_per_1000")
    try:
        return float(row.value) if row and row.value else 0.0
    except (TypeError, ValueError):
        return 0.0


@app.get("/admin/earnings")
def admin_earnings(admin: models.User = Depends(admin_user),
                   db: Session = Depends(get_db)):
    """Phase 44 — the Earning Panel (owner's spec): today's and
    this month's ad impressions, member points (top balances and
    today's top earners). The impression and points figures are
    REAL platform data. The money figures are ESTIMATES —
    impressions × the owner-set rate — because the actual ad
    revenue lives only in the owner's AdsGram partner panel; this
    app never sees it."""
    now = datetime.utcnow()
    today = now.date()
    today_start = datetime(today.year, today.month, today.day)
    month_start = datetime(today.year, today.month, 1)
    rate = _ad_rate(db)
    ads_q = db.query(models.AdEvent)
    ads_today = ads_q.filter(models.AdEvent.created_at >= today_start).count()
    ads_month = ads_q.filter(models.AdEvent.created_at >= month_start).count()
    ads_total = ads_q.count()
    recent = ads_q.filter(
        models.AdEvent.created_at >= today_start - timedelta(days=13)).all()
    by_day = {}
    for r in recent:
        k = r.created_at.date().isoformat()
        by_day[k] = by_day.get(k, 0) + 1
    daily = [{"day": (today - timedelta(days=i)).isoformat(),
              "ads": by_day.get((today - timedelta(days=i)).isoformat(), 0)}
             for i in range(13, -1, -1)]
    top_points = [{
        "telegram_id": u.telegram_id, "first_name": u.first_name,
        "username": u.username, "points": u.points_balance,
    } for u in db.query(models.User).filter(
        models.User.telegram_id != OFFICIAL_ID)
        .order_by(models.User.points_balance.desc()).limit(10).all()]
    earn_rows = db.query(
        models.PointsLedger.user_id,
        func.coalesce(func.sum(models.PointsLedger.amount), 0)) \
        .filter(models.PointsLedger.amount > 0,
                models.PointsLedger.created_at >= today_start) \
        .group_by(models.PointsLedger.user_id) \
        .order_by(func.sum(models.PointsLedger.amount).desc()) \
        .limit(10).all()
    names = {u.telegram_id: u for u in db.query(models.User).filter(
        models.User.telegram_id.in_([uid for uid, _ in earn_rows])).all()} \
        if earn_rows else {}
    top_earners = [{
        "telegram_id": uid,
        "first_name": names[uid].first_name if uid in names else "Member",
        "username": names[uid].username if uid in names else None,
        "earned": int(total),
    } for uid, total in earn_rows]
    return {
        "ads_today": ads_today, "ads_month": ads_month,
        "ads_total": ads_total,
        "rate_per_1000": rate, "rate_per_ad": rate / 1000.0,
        "est_today": round(ads_today * rate / 1000.0, 2),
        "est_month": round(ads_month * rate / 1000.0, 2),
        "daily_14d": daily,
        "top_points": top_points,
        "top_earners_today": top_earners,
    }


class RateIn(BaseModel):
    rate_per_1000: float = Field(ge=0, le=1000000)


@app.post("/admin/earnings/rate")
def set_earnings_rate(body: RateIn,
                      admin: models.User = Depends(admin_user),
                      db: Session = Depends(get_db)):
    """Save the owner-set rate the Earning Panel estimates with."""
    row = db.get(models.AppSetting, "ad_rate_per_1000")
    if row is None:
        row = models.AppSetting(key="ad_rate_per_1000")
        db.add(row)
    row.value = str(body.rate_per_1000)
    _audit(db, admin, "earnings_rate",
           detail=f"rate_per_1000={body.rate_per_1000}")
    db.commit()
    return {"rate_per_1000": body.rate_per_1000}


@app.get("/admin/stats")
def admin_stats(admin: models.User = Depends(admin_user),
                db: Session = Depends(get_db)):
    return {
        "users": db.query(models.User).count(),
        "posts": db.query(models.Post).filter_by(is_deleted=False).count(),
        "comments": db.query(models.Comment).count(),
        "open_reports": db.query(models.Report).filter_by(status="open").count(),
        "banned_users": db.query(models.User).filter_by(is_banned=True).count(),
        "total_points": db.query(models.User).with_entities(
            func.coalesce(func.sum(models.User.points_balance), 0)).scalar(),
    }


@app.get("/admin/users")
def admin_users(q: str = "", limit: int = 50, managed: int = 0,
                admin: models.User = Depends(admin_user),
                db: Session = Depends(get_db)):
    query = db.query(models.User)
    if managed:
        query = query.filter(models.User.is_managed.is_(True))
    if q:
        like = _like_pattern(q)
        query = query.filter(or_(
            models.User.first_name.ilike(like, escape="\\"),
            models.User.username.ilike(like, escape="\\"),
            models.User.telegram_id == (int(q) if q.isdigit() else -1)))
    rows = query.order_by(models.User.telegram_id.desc()) \
        .limit(max(1, min(limit, 100))).all()
    return {"users": [{
        "telegram_id": u.telegram_id, "first_name": u.first_name,
        "username": u.username, "is_banned": bool(u.is_banned),
        "is_verified": bool(u.is_verified), "points": u.points_balance,
        "is_managed": bool(u.is_managed),
        "country": u.country, "language_code": u.language_code,
        "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    } for u in rows]}


@app.get("/admin/users/{telegram_id}")
def admin_user_detail(telegram_id: int,
                      admin: models.User = Depends(admin_user),
                      db: Session = Depends(get_db)):
    """Phase 19: everything the owner asked to see about one member —
    joined/last seen, country, language, posts, points, ads watched
    and total time spent in the app."""
    u = db.get(models.User, telegram_id)
    if u is None:
        raise HTTPException(404, "User not found")
    today = datetime.utcnow().date().isoformat()
    act = db.query(models.UserActivity).filter_by(
        user_id=telegram_id).all()
    act_today = next((r for r in act if r.day == today), None)
    earned = db.query(models.PointsLedger).with_entities(
        func.coalesce(func.sum(models.PointsLedger.amount), 0)).filter(
        models.PointsLedger.user_id == telegram_id,
        models.PointsLedger.amount > 0).scalar()
    return {
        "telegram_id": u.telegram_id, "first_name": u.first_name,
        "username": u.username, "bio": u.bio,
        "photo_file_id": u.photo_file_id,
        "is_banned": bool(u.is_banned), "is_verified": bool(u.is_verified),
        "is_managed": bool(u.is_managed),
        "country": u.country, "language_code": u.language_code,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
        "referrer_id": u.referrer_id,
        "points": u.points_balance, "points_earned_total": int(earned),
        "posts": db.query(models.Post).filter_by(
            user_id=telegram_id, is_deleted=False).count(),
        "comments": db.query(models.Comment).filter_by(
            user_id=telegram_id).count(),
        "followers": db.query(models.Follow).filter_by(
            following_id=telegram_id).count(),
        "following": db.query(models.Follow).filter_by(
            follower_id=telegram_id).count(),
        "ads_watched": db.query(models.AdEvent).filter_by(
            user_id=telegram_id).count(),
        "seconds_total": sum(r.seconds for r in act),
        "seconds_today": act_today.seconds if act_today else 0,
        "sessions_today": act_today.sessions if act_today else 0,
        "active_days": len(act),
    }


class FakeUserIn(BaseModel):
    first_name: str = Field(max_length=128)
    username: Optional[str] = Field(default=None, max_length=64)
    bio: Optional[str] = Field(default=None, max_length=1000)
    country: Optional[str] = Field(default=None, max_length=64)
    language_code: Optional[str] = Field(default=None, max_length=16)
    count: int = 1


@app.post("/admin/fake-users")
def admin_create_fake_users(body: FakeUserIn,
                            admin: models.User = Depends(admin_user),
                            db: Session = Depends(get_db)):
    """Phase 20: the owner can create managed accounts — members with
    no Telegram account behind them, which he alone can operate via
    Act-as (see _resolve_act_as). IDs live in a reserved 9.000.000.00x
    range that real Telegram accounts do not use, so a managed account
    can never collide with, or be confused for, a real member."""
    name = body.first_name.strip()
    if not name:
        raise HTTPException(400, "A name is required")
    count = max(1, min(body.count or 1, 20))
    from .users import _follow_official
    top = db.query(func.max(models.User.telegram_id)).filter(
        models.User.is_managed.is_(True)).scalar()
    next_id = max(top or 0, 9_000_000_000) + 1
    created = []
    for i in range(count):
        while db.get(models.User, next_id) is not None:
            next_id += 1
        uname = body.username.strip().lstrip("@") if body.username else None
        if uname and count > 1:
            uname = f"{uname}{i + 1}"
        u = models.User(
            telegram_id=next_id,
            first_name=name if count == 1 else f"{name} {i + 1}",
            username=uname, bio=body.bio or "",
            country=body.country or None,
            language_code=body.language_code or None,
            is_managed=True)
        db.add(u)
        db.commit()
        _follow_official(db, u)
        created.append({"telegram_id": u.telegram_id,
                        "first_name": u.first_name,
                        "username": u.username})
        next_id += 1
    _audit(db, admin, "managed_create",
           detail=f"{len(created)} account(s): "
                  + ",".join(str(x["telegram_id"]) for x in created))
    db.commit()
    return {"created": created}


@app.delete("/admin/fake-users/{telegram_id}")
def admin_delete_fake_user(telegram_id: int,
                           admin: models.User = Depends(admin_user),
                           db: Session = Depends(get_db)):
    """Remove a managed account completely. Since Phase 24 (full
    admin control) this wipes its posts and every other trace too —
    see _wipe_member."""
    u = db.get(models.User, telegram_id)
    if u is None or not u.is_managed:
        raise HTTPException(404, "Managed user not found")
    _wipe_member(db, u)
    _audit(db, admin, "managed_delete", target_id=telegram_id)
    db.commit()
    return {"deleted": telegram_id}


@app.get("/admin/posts")
def admin_posts(limit: int = 30, admin: models.User = Depends(moderator_user),
                db: Session = Depends(get_db)):
    rows = db.query(models.Post).order_by(models.Post.id.desc()) \
        .limit(max(1, min(limit, 100))).all()
    out = []
    for p in rows:
        author = db.get(models.User, p.user_id)
        out.append({
            "id": p.id, "type": p.type,
            "caption": (p.caption or "")[:120],
            "is_deleted": bool(p.is_deleted),
            "author_id": p.user_id,
            "author_name": author.first_name if author else "",
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })
    return {"posts": out}


@app.post("/admin/posts/{post_id}/remove")
def admin_remove_post(post_id: int, admin: models.User = Depends(moderator_user),
                      db: Session = Depends(get_db)):
    p = db.get(models.Post, post_id)
    if p is None or p.is_deleted:
        raise HTTPException(404, "Post not found")
    p.is_deleted = True
    _audit(db, admin, "post_remove", target_id=p.user_id,
           detail=f"post {p.id}")
    db.commit()
    return {"ok": True, "id": p.id}


@app.get("/admin/reports")
def admin_reports(status: str = "open",
                  admin: models.User = Depends(moderator_user),
                  db: Session = Depends(get_db)):
    rows = db.query(models.Report).filter_by(status=status) \
        .order_by(models.Report.id.desc()).limit(100).all()
    out = []
    for r in rows:
        p = db.get(models.Post, r.post_id)
        reporter = db.get(models.User, r.reporter_id)
        out.append({
            "id": r.id, "post_id": r.post_id, "reason": r.reason,
            "status": r.status,
            "reporter_id": r.reporter_id,
            "reporter_name": reporter.first_name if reporter else "",
            "post_caption": (p.caption[:120] if p else None),
            "post_deleted": bool(p.is_deleted) if p else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {"reports": out}


class ResolveIn(BaseModel):
    action: str  # "remove_post" | "dismiss"


@app.post("/admin/reports/{report_id}/resolve")
def admin_resolve_report(report_id: int, body: ResolveIn,
                         admin: models.User = Depends(moderator_user),
                         db: Session = Depends(get_db)):
    r = db.get(models.Report, report_id)
    if r is None:
        raise HTTPException(404, "Report not found")
    if body.action not in ("remove_post", "dismiss"):
        raise HTTPException(400, "action must be remove_post or dismiss")
    if body.action == "remove_post":
        p = db.get(models.Post, r.post_id)
        if p is not None:
            p.is_deleted = True
    r.status = "resolved"
    _audit(db, admin, "report_resolve", target_id=r.reporter_id,
           detail=f"report {r.id}: {body.action}")
    db.commit()
    return {"ok": True, "id": r.id, "status": r.status}


class BroadcastIn(BaseModel):
    text: str = Field(max_length=4000)


@app.post("/admin/broadcast")
async def admin_broadcast(body: BroadcastIn,
                          admin: models.User = Depends(admin_user),
                          db: Session = Depends(get_db)):
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Broadcast text is empty")
    targets = db.query(models.User).filter_by(is_banned=False) \
        .filter(models.User.telegram_id != OFFICIAL_ID).all()
    sent = 0
    for u in targets:
        if await notify.send_message(u.telegram_id, text):
            sent += 1
            db.add(models.NotificationLog(user_id=u.telegram_id,
                                           type="broadcast"))
        # Phase 20: the announcement also lands in the in-app 🔔 list,
        # including for managed accounts (they have no Telegram chat
        # to DM) — recorded for every target, DM or not.
        db.add(models.Notification(
            user_id=u.telegram_id, type="announcement",
            text=text[:250]))
    _audit(db, admin, "broadcast",
           detail=f"{len(targets)} recipients")
    db.commit()
    return {"recipients": len(targets), "sent": sent}


# ---------------------------------------------------------------------------
# Phase 22 (admin side): review blue-tick applications.
# ---------------------------------------------------------------------------

class VerifyDecideIn(BaseModel):
    approve: bool


@app.get("/admin/verifications")
def admin_verifications(admin: models.User = Depends(admin_user),
                        db: Session = Depends(get_db)):
    rows = db.query(models.VerificationRequest) \
        .order_by(models.VerificationRequest.id.desc()).limit(100).all()
    out = []
    for r in rows:
        u = db.get(models.User, r.user_id)
        if u is None:
            continue
        out.append({
            "id": r.id, "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
            "telegram_id": u.telegram_id, "first_name": u.first_name,
            "username": u.username, "photo_file_id": u.photo_file_id,
            "is_verified": bool(u.is_verified),
            "followers": _followers_count(db, u.telegram_id),
            "posts": db.query(models.Post).filter_by(
                user_id=u.telegram_id, is_deleted=False).count(),
            "joined": u.created_at.isoformat() if u.created_at else None,
        })
    return {"requests": out,
            "pending_count": sum(1 for r in out if r["status"] == "pending")}


@app.post("/admin/verifications/{request_id}/decide")
async def admin_verification_decide(
        request_id: int, body: VerifyDecideIn,
        admin: models.User = Depends(admin_user),
        db: Session = Depends(get_db)):
    req = db.get(models.VerificationRequest, request_id)
    if req is None:
        raise HTTPException(404, "Application not found")
    if req.status != "pending":
        raise HTTPException(400, "This application was already decided")
    applicant = db.get(models.User, req.user_id)
    req.status = "approved" if body.approve else "rejected"
    req.decided_at = datetime.utcnow()
    req.decided_by = admin.telegram_id
    if body.approve and applicant is not None:
        applicant.is_verified = True
    _audit(db, admin, "verification_decide",
           target_id=req.user_id,
           detail=f"request {req.id}: {req.status}")
    db.commit()
    if applicant is not None:
        if body.approve:
            text = ("Your verification application was approved — "
                    "the blue tick is now live on your profile ✓")
        else:
            text = ("Your verification application was not approved "
                    "this time. You can apply again from your Me page.")
        notify.record(db, applicant.telegram_id, "verification",
                      actor_id=None, text=text)
        await notify.notify_user(db, applicant.telegram_id,
                                 "verification", "🛡️ Nexora Social\n" + text)
    return {"ok": True, "status": req.status,
            "is_verified": bool(applicant.is_verified) if applicant else False}


# ---------------------------------------------------------------------------
# Phase 24: FULL admin control (owner: "Admin Panel-এ সবকিছুর
# পারমিশন দাও"). The Admin Panel can now adjust any member's points,
# grant or revoke verification directly, edit any profile (including
# the official account's name/bio), moderate comments, and delete a
# member completely. Two safety rails stay: the official system
# account can never be deleted or unverified, and an admin cannot
# delete his own account (he would lock himself out for good).
# ---------------------------------------------------------------------------

def _wipe_member(db, target):
    """Delete every trace of a member: their posts (with all likes,
    comments, saves, shares, reports and notifications on them),
    their engagement on other posts (denormalized counters repaired
    first), follows, referrals, points, claims, activity and the
    user row itself."""
    tid = target.telegram_id
    post_ids = [p.id for p in
                db.query(models.Post).filter_by(user_id=tid).all()]
    if post_ids:
        for model in (models.Like, models.Comment, models.SavedPost,
                      models.PostShare, models.Report,
                      models.Notification, models.PostView):
            db.query(model).filter(model.post_id.in_(post_ids)) \
                .delete(synchronize_session=False)
        db.query(models.Post).filter(models.Post.id.in_(post_ids)) \
            .delete(synchronize_session=False)
    for like in db.query(models.Like).filter_by(user_id=tid).all():
        post = db.get(models.Post, like.post_id)
        if post is not None and post.like_count > 0:
            post.like_count -= 1
    db.query(models.Like).filter_by(user_id=tid) \
        .delete(synchronize_session=False)
    for cm in db.query(models.Comment).filter_by(user_id=tid).all():
        post = db.get(models.Post, cm.post_id)
        if post is not None and post.comment_count > 0:
            post.comment_count -= 1
    db.query(models.Comment).filter_by(user_id=tid) \
        .delete(synchronize_session=False)
    db.query(models.Follow).filter(or_(
        models.Follow.follower_id == tid,
        models.Follow.following_id == tid)) \
        .delete(synchronize_session=False)
    db.query(models.UserBlock).filter(or_(
        models.UserBlock.blocker_id == tid,
        models.UserBlock.blocked_id == tid)) \
        .delete(synchronize_session=False)
    db.query(models.Referral).filter(or_(
        models.Referral.referrer_id == tid,
        models.Referral.new_user_id == tid)) \
        .delete(synchronize_session=False)
    db.query(models.User).filter_by(referrer_id=tid) \
        .update({"referrer_id": None}, synchronize_session=False)
    db.query(models.Report).filter_by(reporter_id=tid) \
        .delete(synchronize_session=False)
    db.query(models.Notification).filter(or_(
        models.Notification.user_id == tid,
        models.Notification.actor_id == tid)) \
        .delete(synchronize_session=False)
    db.query(models.PostShare).filter(or_(
        models.PostShare.from_user_id == tid,
        models.PostShare.to_user_id == tid)) \
        .delete(synchronize_session=False)
    for model in (models.PointsLedger, models.NotificationLog,
                  models.SavedPost, models.DailyClaim,
                  models.UserActivity, models.AdEvent,
                  models.VerificationRequest, models.DesignLike,
                  models.PostView, models.DesignView):
        db.query(model).filter_by(user_id=tid) \
            .delete(synchronize_session=False)
    # Phase 36: messages both ways, their stories (+ views on
    # them), and their views of other members' stories.
    db.query(models.Message).filter(or_(
        models.Message.sender_id == tid,
        models.Message.recipient_id == tid)) \
        .delete(synchronize_session=False)
    story_ids = [s.id for s in
                 db.query(models.Story).filter_by(user_id=tid).all()]
    if story_ids:
        db.query(models.StoryView) \
            .filter(models.StoryView.story_id.in_(story_ids)) \
            .delete(synchronize_session=False)
        db.query(models.Story) \
            .filter(models.Story.id.in_(story_ids)) \
            .delete(synchronize_session=False)
    db.query(models.StoryView).filter_by(viewer_id=tid) \
        .delete(synchronize_session=False)
    db.delete(target)


class PointsAdjustIn(BaseModel):
    delta: int = Field(ge=-1000000, le=1000000)


class VerifyToggleIn(BaseModel):
    verified: bool


class ProfileEditIn(BaseModel):
    first_name: Optional[str] = Field(default=None, max_length=128)
    bio: Optional[str] = Field(default=None, max_length=1000)


@app.post("/admin/users/{telegram_id}/points")
def admin_adjust_points(telegram_id: int, body: PointsAdjustIn,
                        admin: models.User = Depends(admin_user),
                        db: Session = Depends(get_db)):
    u = db.get(models.User, telegram_id)
    if u is None:
        raise HTTPException(404, "Member not found")
    if body.delta == 0:
        raise HTTPException(400, "Delta must not be zero")
    new_balance = max(0, u.points_balance + body.delta)
    applied = new_balance - u.points_balance
    u.points_balance = new_balance
    if applied:
        db.add(models.PointsLedger(user_id=telegram_id,
                                   amount=applied,
                                   reason="admin_adjust"))
    _audit(db, admin, "points_adjust", target_id=telegram_id,
           detail=f"delta {applied:+d} -> {new_balance}")
    db.commit()
    return {"telegram_id": telegram_id, "points": new_balance,
            "applied": applied}


@app.post("/admin/users/{telegram_id}/verify")
def admin_verify_toggle(telegram_id: int, body: VerifyToggleIn,
                        admin: models.User = Depends(admin_user),
                        db: Session = Depends(get_db)):
    if telegram_id == OFFICIAL_ID:
        raise HTTPException(
            400, "The official account is always verified")
    u = db.get(models.User, telegram_id)
    if u is None:
        raise HTTPException(404, "Member not found")
    u.is_verified = bool(body.verified)
    _audit(db, admin, "verify_grant" if body.verified else "verify_revoke",
           target_id=telegram_id)
    db.commit()
    return {"telegram_id": telegram_id,
            "is_verified": bool(u.is_verified)}


@app.post("/admin/users/{telegram_id}/profile")
def admin_edit_profile(telegram_id: int, body: ProfileEditIn,
                       admin: models.User = Depends(admin_user),
                       db: Session = Depends(get_db)):
    u = db.get(models.User, telegram_id)
    if u is None:
        raise HTTPException(404, "Member not found")
    if body.first_name is not None:
        name = body.first_name.strip()
        if not name:
            raise HTTPException(400, "Name cannot be empty")
        if name[:128] != (u.first_name or ""):
            u.first_name = name[:128]
            # Phase 42: mark the name app-managed so the Telegram
            # sync stops overwriting it; the member's 60-day
            # clock starts from this change too.
            u.name_changed_at = datetime.utcnow()
    if body.bio is not None:
        u.bio = body.bio.strip()[:1000]
    _audit(db, admin, "profile_edit", target_id=telegram_id)
    db.commit()
    return {"telegram_id": telegram_id, "first_name": u.first_name,
            "bio": u.bio}


@app.delete("/admin/users/{telegram_id}")
def admin_delete_member(telegram_id: int,
                        admin: models.User = Depends(admin_user),
                        db: Session = Depends(get_db)):
    if telegram_id == OFFICIAL_ID:
        raise HTTPException(
            400, "The official account cannot be deleted")
    if telegram_id == admin.telegram_id:
        raise HTTPException(
            400, "You cannot delete your own admin account")
    u = db.get(models.User, telegram_id)
    if u is None:
        raise HTTPException(404, "Member not found")
    _wipe_member(db, u)
    _audit(db, admin, "member_delete", target_id=telegram_id)
    db.commit()
    return {"deleted": telegram_id}


@app.get("/admin/comments")
def admin_comments(admin: models.User = Depends(moderator_user),
                   db: Session = Depends(get_db)):
    rows = db.query(models.Comment) \
        .order_by(models.Comment.id.desc()).limit(50).all()
    out = []
    for cm in rows:
        author = db.get(models.User, cm.user_id)
        out.append({
            "id": cm.id, "post_id": cm.post_id, "text": cm.text,
            "created_at": cm.created_at.isoformat()
            if cm.created_at else None,
            "author_id": cm.user_id,
            "author_name": author.first_name if author else "?",
            "author_photo": author.photo_file_id if author else None,
        })
    return {"comments": out}


@app.post("/admin/comments/{comment_id}/remove")
def admin_comment_remove(comment_id: int,
                         admin: models.User = Depends(moderator_user),
                         db: Session = Depends(get_db)):
    cm = db.get(models.Comment, comment_id)
    if cm is None:
        raise HTTPException(404, "Comment not found")
    post = db.get(models.Post, cm.post_id)
    if post is not None and post.comment_count > 0:
        post.comment_count -= 1
    _audit(db, admin, "comment_remove", target_id=cm.user_id,
           detail=f"comment {cm.id} on post {cm.post_id}")
    db.delete(cm)
    db.commit()
    return {"ok": True, "removed": comment_id}


# ---------------------------------------------------------------------------
# Phase 25: the Design gallery (owner: a Design tab in the nav,
# Pinterest-style premium). Posting rule since Phase 34: ONLY the
# admin's own account can post (no acting-as), and the gallery
# shows no poster identity — designs carry the platform identity.
# Members browse, open, like and copy prompts like any post.
# ---------------------------------------------------------------------------

def _design_dict(db, design, user, views=None, liked=None, saved=None):
    if liked is None:
        liked = db.query(models.DesignLike).filter_by(
            design_id=design.id, user_id=user.telegram_id).first() \
            is not None
    if saved is None:
        # Phase 66: the popup rail's 📌 state.
        saved = db.query(models.DesignSave).filter_by(
            design_id=design.id, user_id=user.telegram_id).first() \
            is not None
    if views is None:
        # Phase 31: unique-view count (design_views).
        views = db.query(models.DesignView).filter_by(
            design_id=design.id).count()
    return {"id": design.id, "image_file_id": design.image_file_id,
            "prompt": design.prompt,
            "like_count": design.like_count, "liked": liked,
            "saved": saved,
            "views": views,
            "author_id": OFFICIAL_ID, "author_name": OFFICIAL_NAME,
            "created_at": design.created_at.isoformat()
            if design.created_at else None}


def _remove_design(db, design):
    db.query(models.DesignLike).filter_by(
        design_id=design.id).delete(synchronize_session=False)
    db.query(models.DesignView).filter_by(
        design_id=design.id).delete(synchronize_session=False)
    # Phase 66: saves and shares of a removed design go with it.
    db.query(models.DesignSave).filter_by(
        design_id=design.id).delete(synchronize_session=False)
    db.query(models.DesignShare).filter_by(
        design_id=design.id).delete(synchronize_session=False)
    db.delete(design)


# Phase 61 (owner: pull-to-refresh must surface NEW results, ordered
# by interest): the member's taste profile is built from the prompts
# of designs they LIKED (weight 2) and OPENED (weight 1). Generic
# filler words carry no taste signal and are dropped.
_INTEREST_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "into",
    "over", "under", "a", "an", "of", "in", "on", "at", "to", "by",
    "is", "are", "was", "were", "be", "it", "its", "as", "or",
    "style", "design", "image", "photo", "picture", "art", "prompt",
}


def _interest_words(text):
    import re
    return {w for w in re.findall(r"[a-z0-9]{3,}", (text or "").lower())
            if w not in _INTEREST_STOPWORDS}


@app.get("/designs")
def list_designs(cursor: int = 0, limit: int = 20, similar_to: int = 0,
                 user: models.User = Depends(current_user),
                 db: Session = Depends(get_db)):
    limit = max(1, min(limit, 40))
    liked_ids = {l.design_id for l in db.query(models.DesignLike)
                 .filter_by(user_id=user.telegram_id).all()}
    viewed_ids = {v.design_id for v in db.query(models.DesignView)
                  .filter_by(user_id=user.telegram_id).all()}
    seed = db.get(models.Design, similar_to) if similar_to else None
    if seed is not None:
        # Phase 66 (the popup rail's 🔍 "More like this"): rank every
        # OTHER design by prompt-word overlap with the seed design —
        # the Phase 61 taste words, pointed at one design. Offset
        # cursor, same as personalised mode.
        seed_words = _interest_words(seed.prompt)

        def sim_key(d):
            match = len(seed_words & _interest_words(d.prompt))
            return (match, min(d.like_count or 0, 20), d.id)

        ranked = sorted(
            (d for d in db.query(models.Design).all()
             if d.id != seed.id), key=sim_key, reverse=True)
        rows = ranked[cursor:cursor + limit]
        next_cursor = cursor + limit \
            if cursor + limit < len(ranked) else None
    elif not liked_ids and not viewed_ids:
        # No taste signals yet — the exact legacy behaviour:
        # newest first, keyset pagination on the design id.
        q = db.query(models.Design)
        if cursor:
            q = q.filter(models.Design.id < cursor)
        rows = q.order_by(models.Design.id.desc()).limit(limit).all()
        next_cursor = rows[-1].id if len(rows) == limit else None
    else:
        # Personalised order: unseen designs whose prompts match the
        # member's taste rank first; already-seen designs stay in the
        # list but sink, so a refresh surfaces fresh picks. The
        # cursor is an offset into this ranked list.
        weights = {}
        seeds = db.query(models.Design).filter(
            models.Design.id.in_(liked_ids | viewed_ids)).all()
        for d in seeds:
            w = 2 if d.id in liked_ids else 1
            for word in _interest_words(d.prompt):
                weights[word] = weights.get(word, 0) + w

        def rank_key(d):
            # Unseen designs first (a refresh surfaces fresh picks),
            # within each tier by taste match, then popularity, then
            # newest. Seen designs stay listed — they just sink.
            match = sum(weights.get(w, 0)
                        for w in _interest_words(d.prompt))
            unseen = 0 if (d.id in liked_ids or d.id in viewed_ids) \
                else 1
            return (unseen, match, min(d.like_count or 0, 20), d.id)

        ranked = sorted(db.query(models.Design).all(),
                        key=rank_key, reverse=True)
        rows = ranked[cursor:cursor + limit]
        next_cursor = cursor + limit \
            if cursor + limit < len(ranked) else None
    # Phase 38: batched view counts + liked set for the whole page.
    counts = {}
    liked_set = set()
    saved_set = set()
    if rows:
        ids = [d.id for d in rows]
        counts = {did: n for did, n in db.query(
            models.DesignView.design_id, func.count()).filter(
            models.DesignView.design_id.in_(ids)).group_by(
            models.DesignView.design_id).all()}
        liked_set = {l.design_id for l in db.query(
            models.DesignLike).filter_by(
            user_id=user.telegram_id).filter(
            models.DesignLike.design_id.in_(ids)).all()}
        saved_set = {s.design_id for s in db.query(
            models.DesignSave).filter_by(
            user_id=user.telegram_id).filter(
            models.DesignSave.design_id.in_(ids)).all()}
    return {"designs": [_design_dict(db, d, user,
                                     views=counts.get(d.id, 0),
                                     liked=d.id in liked_set,
                                     saved=d.id in saved_set)
                        for d in rows],
            "next_cursor": next_cursor}


@app.post("/designs/upload")
async def upload_design(prompt: str = Form(""),
                        file: UploadFile = File(...),
                        x_upload_id: str = Header(default=""),
                        user: models.User = Depends(current_user),
                        db: Session = Depends(get_db)):
    hit = _dedupe_get(user.telegram_id, x_upload_id)
    if hit:
        return JSONResponse(status_code=hit[0], content=hit[1])
    # Phase 34 (owner directive, supersedes the Phase 25 rule):
    # designs are posted ONLY from the admin's own account — no
    # acting-as, not even as Official. The gallery never shows who
    # posted: _design_dict reports only the platform identity, and
    # the Design row stores no uploader at all, so the admin's
    # personal id and name appear nowhere in the Design tab.
    real_id = getattr(user, "_real_id", user.telegram_id)
    if user.telegram_id not in settings.ADMIN_IDS \
            or real_id != user.telegram_id:
        raise HTTPException(
            403, "Designs can be posted only from the admin account")
    _enforce_rate("upload", f"u{user.telegram_id}")
    _tok = _upload_screen.set(False)
    try:
        kind, file_id = await _telegram_upload_or_400(
            user, file, prompt.strip())
    finally:
        _upload_screen.reset(_tok)
    if kind != "photo":
        raise HTTPException(400, "Designs must be images only")
    design = models.Design(image_file_id=file_id,
                           prompt=prompt.strip()[:10000])
    db.add(design)
    db.commit()
    db.refresh(design)
    body = _design_dict(db, design, user)
    _dedupe_put(user.telegram_id, x_upload_id, 200, body)
    return body


@app.post("/designs/{design_id}/edit")
async def edit_design(design_id: int,
                      prompt: str = Form(None),
                      file: UploadFile = File(None),
                      user: models.User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """Phase 46 (owner: designs must be editable as needed).
    The admin — from his own account only, the same Phase 34
    rule as posting — can fix a design's prompt text and/or
    replace its image after posting. Likes and views stay."""
    real_id = getattr(user, "_real_id", user.telegram_id)
    if user.telegram_id not in settings.ADMIN_IDS \
            or real_id != user.telegram_id:
        raise HTTPException(
            403, "Designs can be edited only from the admin account")
    design = db.get(models.Design, design_id)
    if design is None:
        raise HTTPException(404, "Design not found")
    if prompt is None and file is None:
        raise HTTPException(400, "Nothing to change")
    if file is not None:
        _enforce_rate("upload", f"u{user.telegram_id}")
        _tok = _upload_screen.set(False)
        try:
            kind, file_id = await _telegram_upload_or_400(
                user, file, (prompt or design.prompt or "")[:10000])
        finally:
            _upload_screen.reset(_tok)
        if kind != "photo":
            raise HTTPException(400, "Designs must be images only")
        design.image_file_id = file_id
    if prompt is not None:
        design.prompt = prompt.strip()[:10000]
    _audit(db, user, "design_edit", detail=f"design {design_id}")
    db.commit()
    db.refresh(design)
    return _design_dict(db, design, user)


@app.post("/designs/{design_id}/like")
def like_design(design_id: int,
                user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
    _enforce_rate("design_like", f"u{user.telegram_id}")
    design = db.get(models.Design, design_id)
    if design is None:
        raise HTTPException(404, "Design not found")
    existing = db.query(models.DesignLike).filter_by(
        design_id=design_id, user_id=user.telegram_id).first()
    if existing:
        db.delete(existing)
        design.like_count = max(0, design.like_count - 1)
        liked = False
    else:
        db.add(models.DesignLike(design_id=design_id,
                                 user_id=user.telegram_id))
        design.like_count += 1
        liked = True
    db.commit()
    return {"liked": liked, "like_count": design.like_count}


@app.post("/designs/{design_id}/view")
def view_design(design_id: int,
                user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
    """Phase 31: record a UNIQUE design view — fired when a member
    opens the detail sheet. One row per (design, viewer)."""
    _enforce_rate("view", f"u{user.telegram_id}")
    design = db.get(models.Design, design_id)
    if design is None:
        raise HTTPException(404, "Design not found")
    counted = _record_view(db, models.DesignView, design.id,
                           user.telegram_id)
    return {"views": db.query(models.DesignView).filter_by(
        design_id=design.id).count(), "counted": counted}


@app.post("/designs/{design_id}/save")
def toggle_design_save(design_id: int,
                       user: models.User = Depends(current_user),
                       db: Session = Depends(get_db)):
    """Phase 66: the 📌 button of the long-press popup — save /
    unsave a design. Saved designs appear in the Saved view."""
    design = db.get(models.Design, design_id)
    if design is None:
        raise HTTPException(404, "Design not found")
    row = db.query(models.DesignSave).filter_by(
        design_id=design_id, user_id=user.telegram_id).first()
    if row is not None:
        db.delete(row)
        saved = False
    else:
        db.add(models.DesignSave(design_id=design_id,
                                 user_id=user.telegram_id))
        saved = True
    db.commit()
    return {"saved": saved, "design_id": design_id}


@app.get("/me/design-saved")
def my_design_saved(user: models.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    rows = db.query(models.Design).join(
        models.DesignSave,
        models.DesignSave.design_id == models.Design.id) \
        .filter(models.DesignSave.user_id == user.telegram_id) \
        .order_by(models.DesignSave.id.desc()).limit(50).all()
    return {"designs": [_design_dict(db, d, user, saved=True)
                        for d in rows]}


@app.post("/designs/{design_id}/share")
async def share_design(design_id: int, body: ShareIn,
                       user: models.User = Depends(current_user),
                       db: Session = Depends(get_db)):
    """Phase 66: the 📤 button of the long-press popup — send a
    design to another member in-app (their Shared view + a bot
    notification), mirroring the post share."""
    _enforce_rate("share", f"u{user.telegram_id}")
    design = db.get(models.Design, design_id)
    if design is None:
        raise HTTPException(404, "Design not found")
    if body.to_user_id == user.telegram_id:
        raise HTTPException(400, "You cannot share to yourself")
    target = db.get(models.User, body.to_user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    if _blocked_by(db, body.to_user_id, user.telegram_id) \
            or _blocked_by(db, user.telegram_id, body.to_user_id):
        raise HTTPException(403, "This member is not available")
    db.add(models.DesignShare(design_id=design.id,
                              from_user_id=user.telegram_id,
                              to_user_id=body.to_user_id))
    db.commit()
    snippet = (design.prompt or "")[:80]
    await notify.notify_user(
        db, body.to_user_id, "share",
        f"\U0001F3A8 {user.first_name} shared a design with you in "
        f"Nexora Social{f': {snippet}' if snippet else ''}")
    notify.record(db, body.to_user_id, "share",
                  actor_id=user.telegram_id,
                  text=f"{user.first_name} shared a design with you")
    return {"ok": True, "design_id": design.id,
            "to_user_id": body.to_user_id}


@app.get("/me/design-shared")
def my_design_shared(user: models.User = Depends(current_user),
                     db: Session = Depends(get_db)):
    shares = db.query(models.DesignShare).filter_by(
        to_user_id=user.telegram_id) \
        .order_by(models.DesignShare.id.desc()).limit(50).all()
    out = []
    for s in shares:
        d = db.get(models.Design, s.design_id)
        if d is None:
            continue
        sender = db.get(models.User, s.from_user_id)
        dd = _design_dict(db, d, user)
        dd["shared_by_id"] = s.from_user_id
        dd["shared_by_name"] = sender.first_name if sender else ""
        dd["shared_at"] = s.created_at.isoformat() \
            if s.created_at else None
        out.append(dd)
    return {"designs": out}


@app.delete("/designs/{design_id}")
def delete_design(design_id: int,
                  user: models.User = Depends(current_user),
                  db: Session = Depends(get_db)):
    if user.telegram_id != OFFICIAL_ID:
        raise HTTPException(
            403, "Only the Official account can remove designs")
    design = db.get(models.Design, design_id)
    if design is None:
        raise HTTPException(404, "Design not found")
    _remove_design(db, design)
    db.commit()
    return {"ok": True, "removed": design_id}


@app.delete("/admin/designs/{design_id}")
def admin_delete_design(design_id: int,
                        admin: models.User = Depends(moderator_user),
                        db: Session = Depends(get_db)):
    design = db.get(models.Design, design_id)
    if design is None:
        raise HTTPException(404, "Design not found")
    _remove_design(db, design)
    _audit(db, admin, "design_remove", detail=f"design {design_id}")
    db.commit()
    return {"ok": True, "removed": design_id}


# ---------------------------------------------------------------------------
# Phase 28: session revocation, audit-log view, member data rights
# (security §5/§10/§11/§13/§14)
# ---------------------------------------------------------------------------

@app.post("/admin/users/{telegram_id}/revoke-sessions")
def admin_revoke_sessions(telegram_id: int,
                          admin: models.User = Depends(admin_user),
                          db: Session = Depends(get_db)):
    """Invalidate every initData issued to this member so far (a
    leaked login string dies immediately) without banning them:
    reopening the app issues fresh initData and they are back in."""
    u = db.get(models.User, telegram_id)
    if u is None:
        raise HTTPException(404, "Member not found")
    u.auth_revoked_at = datetime.utcnow()
    _audit(db, admin, "sessions_revoke", target_id=telegram_id)
    db.commit()
    return {"ok": True, "telegram_id": telegram_id}


@app.get("/admin/audit-log")
def admin_audit_log(limit: int = 100,
                    admin: models.User = Depends(admin_user),
                    db: Session = Depends(get_db)):
    rows = db.query(models.AdminAuditLog) \
        .order_by(models.AdminAuditLog.id.desc()) \
        .limit(max(1, min(limit, 200))).all()
    return {"entries": [{
        "id": r.id, "admin_id": r.admin_id, "action": r.action,
        "target_id": r.target_id, "detail": r.detail,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]}


def _export_payload(db: Session, user: models.User) -> dict:
    """Everything the platform holds about the caller (§11),
    shared by the download and send-to-Telegram routes."""
    me = db.get(models.User, user.telegram_id)
    posts = db.query(models.Post).filter_by(
        user_id=user.telegram_id).order_by(models.Post.id).all()
    ledger = db.query(models.PointsLedger).filter_by(
        user_id=user.telegram_id).order_by(
        models.PointsLedger.id).all()
    comments = db.query(models.Comment).filter_by(
        user_id=user.telegram_id).order_by(models.Comment.id).all()
    payload = {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "profile": {
            "telegram_id": me.telegram_id, "username": me.username,
            "first_name": me.first_name, "bio": me.bio,
            "points_balance": me.points_balance,
            "is_verified": bool(me.is_verified),
            "country": me.country, "language_code": me.language_code,
            "created_at": me.created_at.isoformat()
            if me.created_at else None,
        },
        "posts": [{
            "id": p.id, "type": p.type, "caption": p.caption,
            "media_file_id": p.media_file_id,
            "like_count": p.like_count,
            "comment_count": p.comment_count,
            "is_deleted": bool(p.is_deleted),
            "created_at": p.created_at.isoformat()
            if p.created_at else None,
        } for p in posts],
        "comments": [{
            "id": cm.id, "post_id": cm.post_id, "text": cm.text,
            "created_at": cm.created_at.isoformat()
            if cm.created_at else None,
        } for cm in comments],
        "points_ledger": [{
            "id": e.id, "amount": e.amount, "reason": e.reason,
            "ref_id": e.ref_id,
            "created_at": e.created_at.isoformat()
            if e.created_at else None,
        } for e in ledger],
        "following": [f.following_id for f in db.query(
            models.Follow).filter_by(follower_id=user.telegram_id)],
        "followers": [f.follower_id for f in db.query(
            models.Follow).filter_by(following_id=user.telegram_id)],
    }
    return payload


@app.get("/me/export")
def my_export(user: models.User = Depends(current_user),
              db: Session = Depends(get_db)):
    """The member's copy of their own data, as a JSON download."""
    _enforce_rate("export", f"u{user.telegram_id}")
    return JSONResponse(
        content=_export_payload(db, user),
        headers={"Content-Disposition":
                 "attachment; filename=nexora-export.json"})


@app.post("/me/export/send")
async def my_export_send(user: models.User = Depends(current_user),
                         db: Session = Depends(get_db)):
    """Phase 100 (owner: "Data Control থেকে ডাটা এক্সপোর্ট হয়না"):
    the export endpoints existed since Phase 28 but the app never
    had a single export button — this route plus the Download
    button in the new Data Control card are the member-facing fix.
    Sending the file through the bot chat is the reliable route on
    phones, where a WebView blob download can silently fail."""
    _enforce_rate("export", f"u{user.telegram_id}")
    data = json.dumps(_export_payload(db, user), ensure_ascii=False,
                      indent=1).encode("utf-8")
    sent = await notify.send_document(
        user.telegram_id, "nexora-export.json", data,
        caption="🗂️ Your Nexora data export — everything Nexora "
                "holds about your account.")
    return {"sent": bool(sent)}


# --------------------------------------------------------- Phase 107 --
# Full-site backup + restore (owner: "Admin আইডিতে ... পুরো সাইটের
# এটুজেড ডাটা ডাউনলোডও আপলোড করে রাখা যাবে"). Admin-only. The
# backup is every row of every table, IDs preserved, so a restore
# brings back the same users (names, bios, points), posts, comments,
# likes, follows, designs and messages — A to Z. Media bytes live
# on Telegram's servers (PRD §7); the backup keeps the file_ids,
# so photos/videos come back through those references.
_BACKUP_TABLES = [
    ("users", models.User),
    ("posts", models.Post),
    ("designs", models.Design),
    ("likes", models.Like),
    ("comments", models.Comment),
    ("follows", models.Follow),
    ("referrals", models.Referral),
    ("points_ledger", models.PointsLedger),
    ("reports", models.Report),
    ("notifications_log", models.NotificationLog),
    ("saved_posts", models.SavedPost),
    ("post_shares", models.PostShare),
    ("daily_claims", models.DailyClaim),
    ("user_activity", models.UserActivity),
    ("ad_events", models.AdEvent),
    ("app_settings", models.AppSetting),
    ("notifications", models.Notification),
    ("verification_requests", models.VerificationRequest),
    ("design_likes", models.DesignLike),
    ("admin_audit_logs", models.AdminAuditLog),
    ("user_blocks", models.UserBlock),
    ("post_views", models.PostView),
    ("design_views", models.DesignView),
    ("design_saves", models.DesignSave),
    ("design_shares", models.DesignShare),
    ("messages", models.Message),
    ("stories", models.Story),
    ("story_views", models.StoryView),
]
_BACKUP_MODELS = {name: m for name, m in _BACKUP_TABLES}
_BACKUP_MAX_BYTES = 50 * 1024 * 1024


def _row_to_dict(row):
    out = {}
    for c in row.__table__.columns:
        v = getattr(row, c.name)
        if isinstance(v, datetime):
            v = v.isoformat()
        out[c.name] = v
    return out


def _backup_payload(db: Session) -> dict:
    tables = {}
    for name, model in _BACKUP_TABLES:
        pk = list(model.__table__.primary_key.columns)[0].name
        rows = db.query(model).order_by(getattr(model, pk)).all()
        tables[name] = [_row_to_dict(r) for r in rows]
    return {
        "format": "nexora-backup",
        "version": 1,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "tables": tables,
    }


def _restore_backup(db: Session, payload: dict) -> dict:
    """Validate, then wipe + re-insert every table in one
    transaction. Raises HTTPException on any bad input; the caller
    rolls back on failure, so a bad file never half-restores."""
    if not isinstance(payload, dict):
        raise HTTPException(400, "Backup must be a JSON object")
    if payload.get("format") != "nexora-backup":
        raise HTTPException(400, "Not a Nexora backup file")
    if payload.get("version") != 1:
        raise HTTPException(400, "Unsupported backup version")
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise HTTPException(400, "Backup has no tables")
    unknown = set(tables) - set(_BACKUP_MODELS)
    if unknown:
        raise HTTPException(
            400, "Unknown tables in backup: " + ", ".join(sorted(unknown)))
    # Validate every row before touching the database.
    cleaned = {}
    for name, rows in tables.items():
        model = _BACKUP_MODELS[name]
        cols = {c.name: c for c in model.__table__.columns}
        pk = list(model.__table__.primary_key.columns)[0].name
        if not isinstance(rows, list):
            raise HTTPException(400, f"Table {name} must be a list")
        out_rows = []
        for r in rows:
            if not isinstance(r, dict) or pk not in r:
                raise HTTPException(
                    400, f"Table {name}: every row needs its id ({pk})")
            extra = set(r) - set(cols)
            if extra:
                raise HTTPException(
                    400, "Table " + name + ": unknown columns "
                         + ", ".join(sorted(extra)))
            row = {}
            for k, v in r.items():
                col = cols[k]
                if col.type.python_type is datetime and isinstance(v, str):
                    dt = datetime.fromisoformat(
                        v[:-1] + "+00:00") if v.endswith("Z") \
                        else datetime.fromisoformat(v)
                    row[k] = dt.replace(tzinfo=None)
                else:
                    row[k] = v
            out_rows.append(row)
        cleaned[name] = out_rows
    counts = {}
    # Delete children first, then parents.
    for name, model in reversed(_BACKUP_TABLES):
        db.query(model).delete()
    # Insert parents first (users before everything that references
    # them; rows are PK-ordered, so a referrer with a smaller id
    # always lands before the member who named them).
    for name, model in _BACKUP_TABLES:
        if cleaned.get(name):
            db.execute(model.__table__.insert(), cleaned[name])
        counts[name] = len(cleaned.get(name, []))
    # Postgres sequences sit behind explicit ids — move them past
    # the restored max, or the next insert collides. (SQLite tracks
    # the max itself, so this runs on Postgres only.)
    if db.bind.dialect.name == "postgresql":
        for name, model in _BACKUP_TABLES:
            pk = list(model.__table__.primary_key.columns)[0]
            if pk.type.python_type is int:
                db.execute(text(
                    "SELECT setval(pg_get_serial_sequence("
                    f"'{model.__tablename__}', '{pk.name}'), "
                    f"COALESCE((SELECT MAX({pk.name}) "
                    f"FROM {model.__tablename__}), 0))"))
    return counts


@app.get("/admin/backup")
def admin_backup(admin: models.User = Depends(admin_user),
                 db: Session = Depends(get_db)):
    """Admin-only full-site backup download (Phase 107)."""
    _enforce_rate("backup", f"a{admin.telegram_id}")
    payload = _backup_payload(db)
    total = sum(len(v) for v in payload["tables"].values())
    _audit(db, admin, "backup_download",
           detail=f"{total} rows across {len(payload['tables'])} tables")
    db.commit()
    fname = ("nexora-full-backup-"
             + datetime.utcnow().strftime("%Y-%m-%d") + ".json")
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f"attachment; filename={fname}"})


@app.post("/admin/backup/send")
async def admin_backup_send(admin: models.User = Depends(admin_user),
                            db: Session = Depends(get_db)):
    """Send the full backup to the admin's bot chat (Phase 107) —
    the reliable route on phones, same as the Phase 100 export."""
    _enforce_rate("backup", f"a{admin.telegram_id}")
    payload = _backup_payload(db)
    data = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
    fname = ("nexora-full-backup-"
             + datetime.utcnow().strftime("%Y-%m-%d") + ".json")
    sent = await notify.send_document(
        admin.telegram_id, fname, data,
        caption="💾 Nexora full-site backup — every user, post, "
                "comment, like, follow, design and message. Keep "
                "this file safe: anyone holding it holds the whole "
                "database.")
    return {"sent": bool(sent)}


class RestoreIn(BaseModel):
    confirm: str
    backup: dict


@app.post("/admin/restore")
def admin_restore(body: RestoreIn,
                  x_act_as: str = Header(default=""),
                  admin: models.User = Depends(admin_user),
                  db: Session = Depends(get_db)):
    """Restore the whole site from a backup file (Phase 107).
    Guarded: admin-only, never while acting as another account,
    typed RESTORE, format/version/column validation up front, one
    transaction (a bad file rolls back clean), audit-logged."""
    if x_act_as:
        raise HTTPException(
            400, "Switch back to your own account to restore")
    if body.confirm != "RESTORE":
        raise HTTPException(400, "Type RESTORE to confirm the restore")
    if len(json.dumps(body.backup, ensure_ascii=False)) > _BACKUP_MAX_BYTES:
        raise HTTPException(413, "Backup file is too large (max 50 MB)")
    _enforce_rate("restore", f"a{admin.telegram_id}")
    try:
        counts = _restore_backup(db, body.backup)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(400, "Restore failed — nothing was changed")
    total = sum(counts.values())
    _audit(db, admin, "backup_restore",
           detail=f"{total} rows across {len(counts)} tables")
    db.commit()
    return {"restored": counts}


class DeleteAccountIn(BaseModel):
    confirm: str


@app.post("/me/delete-account")
def my_delete_account(body: DeleteAccountIn,
                      x_act_as: str = Header(default=""),
                      user: models.User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """Permanent self-service account deletion (§5/§11): the same
    complete wipe the admin delete performs. Guarded three ways: an
    explicit typed confirmation, never while acting as another
    account, and never for the official account."""
    if x_act_as:
        raise HTTPException(
            400, "Switch back to your own account to delete it")
    if user.telegram_id == OFFICIAL_ID:
        raise HTTPException(
            400, "The official account cannot be deleted")
    if body.confirm != "DELETE":
        raise HTTPException(
            400, "Type DELETE to confirm account deletion")
    target = db.get(models.User, user.telegram_id)
    _wipe_member(db, target)
    db.commit()
    sec_log.warning("member self-deleted account %s",
                    user.telegram_id)
    return {"ok": True, "deleted": user.telegram_id}


@app.get("/media/{file_id}")
async def media_proxy(file_id: str, request: Request):
    """Stream a Telegram-hosted file to the Mini App. The bot token is used
    only in server-side requests and never appears in a client-visible URL.
    file_id values are long unguessable strings, the same protection
    Telegram's own file links rely on. Needs a live token, so this path is
    verified at deploy time; without a token it answers 503.

    The upstream response is opened HERE (not inside an `async with` that
    exits before the body streams — that closed-client bug silently broke
    every posted image) and its lifetime is tied to the body generator.
    Range requests are forwarded so video seeking works in reels."""
    if not settings.BOT_TOKEN:
        raise HTTPException(503, "Media unavailable until the bot is live")
    # Phase 28 (H2): a bare file_id is no longer enough — media
    # requires the short-lived signed token the app receives at
    # /auth (image/video tags cannot send the login header, so the
    # capability rides in the URL and expires).
    if not _media_token_ok(request.query_params.get("mt", "")):
        raise HTTPException(401, "Media token missing or expired")
    api = f"https://api.telegram.org/bot{settings.BOT_TOKEN}"
    async with httpx.AsyncClient(timeout=30) as client:
        info = await client.get(f"{api}/getFile", params={"file_id": file_id})
        if info.status_code != 200:
            raise HTTPException(404, "File not found")
        file_path = info.json()["result"]["file_path"]
    fwd = {}
    if request.headers.get("range"):
        fwd["Range"] = request.headers["range"]
    stream_client = httpx.AsyncClient(timeout=60)
    # Telegram file downloads live at /file/bot<token>/<file_path> — the
    # /file/ segment comes BEFORE /bot<token>. Building it as
    # /bot<token>/file/... (the phase-16 bug) makes Telegram answer 404
    # for every file, which is why posted photos never displayed.
    file_url = f"https://api.telegram.org/file/bot{settings.BOT_TOKEN}/{file_path}"
    req = stream_client.build_request("GET", file_url, headers=fwd)
    resp = await stream_client.send(req, stream=True)
    if resp.status_code not in (200, 206):
        await resp.aclose()
        await stream_client.aclose()
        raise HTTPException(404, "File not found")

    async def body():
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()
            await stream_client.aclose()

    headers = {}
    for key in ("content-type", "content-length", "content-range",
                "accept-ranges"):
        if resp.headers.get(key):
            headers[key] = resp.headers[key]
    # Phase 111 (owner: Design page loads slowly): /media never sent
    # a Cache-Control, so every Design visit re-downloaded every
    # image from Telegram through this proxy. A file_id's bytes never
    # change, and the signed ?mt= token already bounds access to 7
    # days, so a private 7-day cache is safe: repeat visits serve
    # from the browser cache instead of re-fetching.
    headers["cache-control"] = "private, max-age=604800, immutable"
    return StreamingResponse(body(), status_code=resp.status_code,
                             headers=headers,
                             media_type=resp.headers.get("content-type"))


if WEBAPP_DIR.exists():
    app.mount("/webapp", StaticFiles(directory=WEBAPP_DIR, html=True), name="webapp")


# ---------------------------------------------------------------------------
# Phase 36: Messages + Stories (owner: a Facebook-style messenger
# in the top corner of the header — a conversation list, chat
# threads, and a stories strip where members post 24-hour photo
# stories). Text messages are rows in the DB (no media, so the
# fragile upload path is never involved); stories are photos on
# Telegram's servers, exactly like feed photos.
# ---------------------------------------------------------------------------

STORY_TTL = timedelta(hours=24)


def _brief_user(u):
    return {"telegram_id": u.telegram_id, "first_name": u.first_name,
            "username": u.username, "verified": bool(u.is_verified),
            "photo_file_id": u.photo_file_id}


def _message_dict(m, me_id):
    return {"id": m.id, "mine": m.sender_id == me_id, "text": m.text,
            "created_at": m.created_at.isoformat() if m.created_at
            else None,
            "read": m.read_at is not None}


@app.get("/messages/unread")
def messages_unread(user: models.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    n = db.query(models.Message).filter_by(
        recipient_id=user.telegram_id).filter(
        models.Message.read_at.is_(None)).count()
    return {"count": n}


@app.get("/messages")
def conversations(user: models.User = Depends(current_user),
                  db: Session = Depends(get_db)):
    me = user.telegram_id
    hidden = _block_related_ids(db, me)
    rows = db.query(models.Message).filter(
        or_(models.Message.sender_id == me,
            models.Message.recipient_id == me)
    ).order_by(models.Message.id.desc()).limit(1000).all()
    convs = {}
    order = []
    for m in rows:
        other = m.recipient_id if m.sender_id == me else m.sender_id
        if other in hidden:
            continue
        c = convs.get(other)
        if c is None:
            u = db.get(models.User, other)
            if u is None:
                continue
            c = {"user": _brief_user(u), "last": _message_dict(m, me),
                 "unread": 0}
            convs[other] = c
            order.append(other)
        if m.recipient_id == me and m.read_at is None:
            c["unread"] += 1
    return {"conversations": [convs[o] for o in order]}


@app.get("/me/following")
def my_following(user: models.User = Depends(current_user),
                 db: Session = Depends(get_db)):
    """The people the member follows — the Messages view's
    start-a-chat list."""
    ids = [f.following_id for f in db.query(models.Follow).filter_by(
        follower_id=user.telegram_id).all()]
    out = []
    for i in ids:
        u = db.get(models.User, i)
        if u is not None:
            out.append(_brief_user(u))
    return {"users": out}


@app.get("/messages/{uid}")
def message_thread(uid: int,
                   user: models.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    me = user.telegram_id
    other = db.get(models.User, uid)
    if other is None or uid in _block_related_ids(db, me):
        raise HTTPException(404, "User not found")
    rows = db.query(models.Message).filter(
        or_((models.Message.sender_id == me) &
            (models.Message.recipient_id == uid),
            (models.Message.sender_id == uid) &
            (models.Message.recipient_id == me))
    ).order_by(models.Message.id.desc()).limit(200).all()
    rows.reverse()
    db.query(models.Message).filter_by(
        sender_id=uid, recipient_id=me).filter(
        models.Message.read_at.is_(None)).update(
        {"read_at": datetime.utcnow()})
    db.commit()
    return {"user": _brief_user(other),
            "messages": [_message_dict(m, me) for m in rows]}


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@app.post("/messages/{uid}")
def send_message(uid: int, body: MessageIn,
                 user: models.User = Depends(current_user),
                 db: Session = Depends(get_db)):
    me = user.telegram_id
    if uid == me:
        raise HTTPException(400, "You can't message yourself")
    other = db.get(models.User, uid)
    if other is None:
        raise HTTPException(404, "User not found")
    if uid in _block_related_ids(db, me):
        raise HTTPException(403, "You can't message this user")
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Message is empty")
    _enforce_rate("message", f"u{me}")
    m = models.Message(sender_id=me, recipient_id=uid, text=text)
    db.add(m)
    db.commit()
    db.refresh(m)
    notify.record(db, uid, "message", actor_id=me,
                  text=f"{user.first_name} sent you a message")
    return _message_dict(m, me)


def _story_dict(db, s, viewer_id):
    views = db.query(models.StoryView).filter_by(story_id=s.id).count()
    viewed = db.query(models.StoryView).filter_by(
        story_id=s.id, viewer_id=viewer_id).first() is not None
    return {"id": s.id, "media_file_id": s.media_file_id,
            "created_at": s.created_at.isoformat() if s.created_at
            else None,
            "views": views, "viewed": viewed,
            "mine": s.user_id == viewer_id}


@app.post("/stories/upload")
async def upload_story(request: Request,
                       file: UploadFile = File(...),
                       x_upload_id: Optional[str] = Header(None),
                       user: models.User = Depends(current_user),
                       db: Session = Depends(get_db)):
    hit = _dedupe_get(user.telegram_id, x_upload_id)
    if hit:
        return JSONResponse(status_code=hit[0], content=hit[1])
    _enforce_rate("upload", f"u{user.telegram_id}")
    kind, file_id = await _telegram_upload_or_400(user, file)
    if kind != "photo":
        raise HTTPException(400, "Stories must be photos")
    s = models.Story(user_id=user.telegram_id, media_file_id=file_id)
    db.add(s)
    db.commit()
    db.refresh(s)
    body = _story_dict(db, s, user.telegram_id)
    _dedupe_put(user.telegram_id, x_upload_id, 200, body)
    return body


@app.get("/stories")
def list_stories(user: models.User = Depends(current_user),
                 db: Session = Depends(get_db)):
    me = user.telegram_id
    cutoff = datetime.utcnow() - STORY_TTL
    author_ids = {me, OFFICIAL_ID}
    author_ids.update(f.following_id for f in
                      db.query(models.Follow).filter_by(
                          follower_id=me).all())
    author_ids -= _block_related_ids(db, me)
    rows = db.query(models.Story).filter(
        models.Story.created_at > cutoff,
        models.Story.user_id.in_(author_ids)
    ).order_by(models.Story.id.asc()).all()
    groups = {}
    for s in rows:
        groups.setdefault(s.user_id, []).append(s)
    out = []
    for uid_, ss in groups.items():
        u = db.get(models.User, uid_)
        if u is None:
            continue
        dicts = [_story_dict(db, s, me) for s in ss]
        out.append({"author": _brief_user(u), "stories": dicts,
                    "has_unviewed": any(
                        not d["viewed"] and not d["mine"]
                        for d in dicts)})
    out.sort(key=lambda g: (g["author"]["telegram_id"] != me,
                            not g["has_unviewed"],
                            -g["stories"][-1]["id"]))
    return {"groups": out}


@app.post("/stories/{sid}/view")
def view_story(sid: int, user: models.User = Depends(current_user),
               db: Session = Depends(get_db)):
    s = db.get(models.Story, sid)
    if s is None or s.created_at <= datetime.utcnow() - STORY_TTL:
        raise HTTPException(404, "Story not found")
    _enforce_rate("view", f"u{user.telegram_id}")
    counted = False
    if s.user_id != user.telegram_id:
        exists = db.query(models.StoryView).filter_by(
            story_id=sid, viewer_id=user.telegram_id).first()
        if exists is None:
            db.add(models.StoryView(
                story_id=sid, viewer_id=user.telegram_id))
            db.commit()
            counted = True
    views = db.query(models.StoryView).filter_by(story_id=sid).count()
    return {"views": views, "counted": counted}


@app.delete("/stories/{sid}")
def delete_story(sid: int, user: models.User = Depends(current_user),
                 db: Session = Depends(get_db)):
    s = db.get(models.Story, sid)
    if s is None:
        raise HTTPException(404, "Story not found")
    real_id = getattr(user, "_real_id", user.telegram_id)
    admin_own = user.telegram_id in settings.ADMIN_IDS \
        and real_id == user.telegram_id
    if s.user_id != user.telegram_id and not admin_own:
        raise HTTPException(403, "Not your story")
    db.query(models.StoryView).filter_by(story_id=sid).delete()
    db.delete(s)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Phase 69: Nexa, the 3D AI assistant. She appears only when a member
# opens the sidebar and taps her card. Brain + voice = Google Gemini
# when GEMINI_API_KEY is set (one free key powers both); without a
# key she answers from a built-in Nexora guide brain and /speak
# returns no audio, so the client uses the phone's own voice. The
# key never leaves the server.
# ---------------------------------------------------------------------------
import base64 as _b64
import io as _io
import wave as _wave


class AssistantChatIn(BaseModel):
    message: str = Field(default="", max_length=500)
    history: list = Field(default_factory=list)


class AssistantSpeakIn(BaseModel):
    text: str = Field(default="", max_length=700)


_NEXA_SYSTEM = (
    "You are Nexa, the cute 3D AI assistant girl inside Nexora "
    "Social, a social app that runs as a Telegram Mini App "
    "(bot @NexoraSocial_bot). You chat with members like a "
    "friendly companion, and you are the app's guide — you know "
    "everything below about how Nexora Social works. "
    "NAVIGATION: the bottom tabs are Feed, Videos, Design, "
    "Games, Tasks, Ranks and Profile. A floating glass button "
    "opens the sidebar, which holds Search, Messages, "
    "Notifications, Saved, Shared with me, the Admin Panel "
    "(owner only — it has a Site Backup card to download the "
    "whole site's data as one file, or restore it from a backup "
    "file by typing RESTORE) and Nexa herself — that is where members "
    "find you. Every main page can be refreshed by pulling "
    "down from the top. "
    "FEED: Explore shows everyone, Following shows people you "
    "follow. Like with the heart (likes give no points), "
    "comment, save, or open the menu for Share, Copy link, "
    "Download, View profile, Follow, Not interested or Report; "
    "your own posts also have Edit and Delete there. Views "
    "count once per person. A little way down the Explore "
    "feed, a Suggested for you card suggests people to "
    "follow — tap Follow on anyone there, or tap their "
    "photo or name to open their profile first; the cross "
    "hides the card for now. "
    "POSTING: write from the Feed composer, or send a photo or "
    "video directly to @NexoraSocial_bot in chat with a "
    "caption and it becomes your post — the most reliable way "
    "to post videos. A post earns 5 points. "
    "VIDEOS: the Videos tab is full-screen reels — swipe to "
    "move, tap to pause, the speaker button toggles sound; "
    "liking, commenting and the menu work like the Feed. "
    "DESIGN: a gallery of designs with their prompts. Tap a "
    "design to read its prompt and copy it; HOLD a design for "
    "Similar, WhatsApp, Share and Save. Pull down to refresh — "
    "designs are ordered by your taste. Only the admin adds "
    "designs. "
    "POINTS: daily tasks on the Tasks page — check-in 20 "
    "points, the follow task 5, the comment task 5, each once "
    "a day, press Claim. The balance and history are on the "
    "profile in the My Points card. A referral earns 20 points "
    "when the friend makes their first post. "
    "REFERRALS: your invite link is on your profile. A "
    "referral is qualified when the friend joins AND makes a "
    "first post. "
    "MONETIZATION: the profile card shows 6 targets — 500 "
    "followers, 12 qualified referrals, 25 posts, an account "
    "14 days old, 5000 lifetime points, and a 30-day check-in "
    "streak (one missed day resets it). Payouts are a later "
    "step; never promise money or dates. "
    "VERIFICATION: the blue badge. Members with at least 1000 "
    "followers can apply from their profile; the admin "
    "approves applications. "
    "MESSAGES AND STORIES: the message button opens chats and "
    "stories; members can message anyone from their profile. "
    "Stories are photos that live for 24 hours, seen by "
    "followers and the official account. "
    "GAMES: open the Games page and pull the lamp cord to "
    "light the room, then play 11 games — Snake, Tetris, "
    "Breakout, Memory Match, Pong, Space Invaders, "
    "Minesweeper, Flappy Bird, 2048, Pac-Man and Archery "
    "(drag to aim past the drifting bars at the SUCCESS "
    "target; solo is a level climb — score the quota in 10 "
    "arrows to advance, each level has a new sky and gets "
    "harder with faster bars, a smaller moving target and "
    "wind; your level and total are saved, so a solo run "
    "resumes where you left it, and the New run button "
    "starts over; also two players on one phone, or invite a "
    "friend with a challenge message). Games give "
    "no points, they are just for fun. "
    "PROFILE: the round camera badges change your photo and "
    "cover. A bio can be up to 500 characters. Your name can "
    "change once every 60 days; the @username belongs to "
    "Telegram and cannot be changed here. Profiles show "
    "followers and following counts. "
    "THEME COLOURS: on your own profile, the Theme Colours "
    "card lets you pick a colour shade — one shade can "
    "recolour the whole app, or you can assign different "
    "shades to the background, the cards and the accent "
    "buttons. Text colours adjust automatically so they "
    "never blend into the background. Your theme is saved "
    "on your own account only — changing yours never "
    "changes anyone else's app, and theirs never changes "
    "yours. "
    "SEARCH: from the sidebar or the search button — type and "
    "press Enter. Usernames are shown so members with the "
    "same name can be told apart. "
    "SAVED AND SHARED: in the sidebar Library — posts and "
    "designs you saved, and things others shared with you. "
    "SAFETY: from any profile you can block or mute a member "
    "and you will stop seeing each other; report bad posts "
    "from their menu. The official account Nexora Social "
    "(@nexora, verified) is followed by everyone and cannot "
    "be unfollowed or blocked. "
    "ACCOUNT: your profile has a Data Control card — there "
    "you can download everything Nexora holds about you as a "
    "JSON file, or have the bot send that file to your Telegram "
    "chat (best on phones). Deleting your account is asked "
    "there too, by typing DELETE. Under it sits the After "
    "Rain Effect card: turning it on covers your own Me "
    "screen with gentle raindrops on glass — it is only a "
    "decoration, only on that screen, and only you see it. "
    "Log out is in the sidebar. "
    "YOU: you live in the sidebar; members chat with you by text. "
    "RULES: reply in the same language the member writes in "
    "(English or Bengali). Keep answers short and friendly: "
    "1-3 sentences of plain text, no markdown and no lists; "
    "for how-to questions, give the key steps inside those "
    "sentences. Never promise earnings, money, prizes or "
    "dates. If something is not covered above, say you are "
    "not sure and point to the closest page."
)


def _nexa_is_bn(text):
    return any("\u0980" <= c <= "\u09ff" for c in text)


def _nexa_fallback(text):
    """Built-in guide brain (no API key): friendly, bilingual,
    and honest that full AI chat needs the owner's Gemini key."""
    t = text.lower()
    bn = _nexa_is_bn(text)

    def has(*words):
        return any(w in t for w in words)

    if has("hi", "hello", "hey", "salam", "হাই", "হ্যালো", "সালাম",
           "আসসালামু"):
        return ("হাই! আমি Nexa, Nexora Social-এর AI বন্ধু। পোস্ট, "
                "পয়েন্ট, টাস্ক বা ডিজাইন — যেকোনো বিষয়ে জিজ্ঞেস "
                "করো!" if bn else
                "Hi! I'm Nexa, your AI friend inside Nexora Social. "
                "Ask me about posts, points, tasks or designs!")
    if has("নাম", "name", "কে তুমি", "who are you"):
        return ("আমি Nexa! Nexora Social-এর ভেতরেই থাকি — সাইডবার "
                "খুললেই আমাকে পাবে।" if bn else
                "I'm Nexa! I live inside Nexora Social — you will "
                "find me whenever you open the sidebar.")
    if has("point", "পয়েন্ট", "স্টার", "star"):
        return ("প্রতিদিনের টাস্কে পয়েন্ট মেলে: চেক-ইনে ২০, ফলো "
                "টাস্কে ৫, কমেন্ট টাস্কে ৫। Tasks পেজে গিয়ে Claim "
                "করো!" if bn else
                "You earn points from daily tasks: 20 for check-in, "
                "5 for the follow task and 5 for the comment task. "
                "Open the Tasks page and claim yours!")
    if has("verif", "ব্যাজ", "badge", "ভেরিফাই", "নীল টিক"):
        return ("নীল ব্যাজ পেতে কমপক্ষে ১০০০ ফলোয়ার লাগে — "
                "প্রোফাইল থেকে আবেদন করো, অ্যাডমিন অনুমোদন "
                "দেবে।" if bn else
                "The blue badge needs at least 1000 followers — "
                "apply from your profile and the admin approves "
                "it.")
    if has("story", "স্টোরি"):
        return ("স্টোরি হলো ২৪ ঘণ্টার ছবি — Messages পেজ থেকে "
                "দাও, ফলোয়াররা দেখতে পাবে।" if bn else
                "Stories are photos that live 24 hours — post "
                "one from the Messages page and your followers "
                "will see it.")
    if has("profile", "প্রোফাইল", "cover", "কভার", "bio",
           "বায়ো", "নাম বদল", "change name", "ছবি বদল"):
        return ("প্রোফাইলে ক্যামেরা ব্যাজ চাপলেই ছবি আর কভার "
                "বদলাতে পারবে; বায়ো ৫০০ অক্ষর পর্যন্ত, আর নাম "
                "৬০ দিনে একবার বদলানো যায়।" if bn else
                "Tap the camera badges on your profile to change "
                "your photo and cover; a bio can be 500 "
                "characters, and your name can change once every "
                "60 days.")
    if has("block", "ব্লক", "mute", "মিউট"):
        return ("কারো প্রোফাইল খুলে Block করো — তারপর থেকে "
                "তোমরা কেউ কাউকে দেখতে পাবে না।" if bn else
                "Open their profile and tap Block — from then on "
                "you will not see each other at all.")
    if has("post", "পোস্ট", "upload", "আপলোড", "ভিডিও", "video",
           "ছবি", "photo"):
        return ("পোস্ট করা সহজ: Feed-এ গিয়ে লেখো, অথবা ছবি/ভিডিও "
                "সরাসরি @NexoraSocial_bot-এর চ্যাটে পাঠিয়ে দাও — "
                "সেটাই ফিডে পোস্ট হয়ে যাবে!" if bn else
                "Posting is easy: write from the Feed, or send a "
                "photo or video straight to @NexoraSocial_bot in "
                "chat and it becomes your feed post!")
    if has("design", "ডিজাইন"):
        return ("Design ট্যাবে সুন্দর সব ডিজাইন আর তাদের প্রম্পট "
                "আছে — যেকোনো ডিজাইনে হোল্ড করলেই Save, Share আর "
                "Similar অপশন আসবে!" if bn else
                "The Design tab is full of pretty designs with "
                "their prompts — hold any design to save, share "
                "or find similar ones!")
    if has("money", "টাকা", "withdraw", "monet", "মনিটাইজ",
           "আয়", "income", "earn"):
        return ("মনিটাইজেশন খুলতে ৬টা লক্ষ্য লাগে: ৫০০ ফলোয়ার, "
                "১২ জন যোগ্য রেফারেল, ২৫ পোস্ট, ১৪ দিন বয়স, "
                "৫০০০ পয়েন্ট আর টানা ৩০ দিনের চেক-ইন স্ট্রিক। "
                "নিজের অগ্রগতি প্রোফাইলেই দেখতে পারো!" if bn else
                "Monetization unlocks at 6 targets: 500 followers, "
                "12 qualified referrals, 25 posts, 14 days old, "
                "5000 points and a 30-day check-in streak. Track "
                "your progress on your profile!")
    if has("game", "গেম", "খেল"):
        return ("Games পেজে ১১টা গেম আছে — Snake, 2048, "
                "Pac-Man, Archery আরো অনেক! ল্যাম্পটা টেনে আলো জ্বালাও "
                "প্রথমে।" if bn else
                "The Games page has 11 games — Snake, 2048, "
                "Pac-Man, Archery and more! Pull the lamp cord to light "
                "the room first.")
    if has("suggest", "who to follow", "কাকে ফলো", "সাজেস্ট",
           "follow করব", "new people"):
        return ("Feed-টা একটু নিচে স্ক্রল করলেই 'Suggested for "
                "you' কার্ডে ফলো করার মতো মানুষ পাবে — Follow "
                "চাপলেই হয়ে যাবে!" if bn else
                "Scroll a little way down the Feed and the "
                "Suggested for you card shows people to follow "
                "— just tap Follow on anyone there!")
    if has("refer", "রেফার", "invite", "বন্ধু"):
        return ("তোমার রেফারেল লিংক প্রোফাইল থেকে শেয়ার করো — "
                "বন্ধু যোগ দিয়ে প্রথম পোস্ট করলেই তুমি ২০ "
                "পয়েন্ট পাবে!" if bn else
                "Share your referral link from your profile — when "
                "a friend joins and makes their first post, you "
                "earn 20 points!")
    if has("thank", "ধন্যবাদ", "শুকরিয়া"):
        return ("তোমাকেও ধন্যবাদ! আর কিছু জানতে চাইলে আমি "
                "এখানেই আছি।" if bn else
                "You're welcome! I'm right here if you need "
                "anything else.")
    if has("bye", "বিদায়", "যাই"):
        return ("বিদায়! আবার এসো — সাইডবার খুললেই আমাকে পাবে।"
                if bn else
                "Bye! Come back soon — open the sidebar and I'll "
                "be here.")
    if has("সাহায্য", "help", "হেল্প"):
        return ("আমি পোস্ট, পয়েন্ট, টাস্ক, রেফারেল, ডিজাইন, "
                "গেম আর মনিটাইজেশন নিয়ে সাহায্য করতে পারি — "
                "একটা বিষয় লিখে পাঠাও!" if bn else
                "I can help with posts, points, tasks, referrals, "
                "designs, games and monetization — just type a "
                "topic!")
    return ("ভালো প্রশ্ন! আমি এখনো শিখছি — পোস্ট, পয়েন্ট, "
            "টাস্ক, ডিজাইন বা মনিটাইজেশন নিয়ে জিজ্ঞেস করলে "
            "ঠিকঠাক বলতে পারব।" if bn else
            "Good question! I'm still learning — ask me about "
            "posts, points, tasks, designs or monetization and "
            "I'll do my best.")


# Google retires/renames Gemini models quickly (checked live
# 2026-11-03: 2.0-flash gone, 2.5-flash closed to new keys,
# 3.8-flash intermittently 503) — try in order, first win works.
_NEXA_CHAT_MODELS = ("gemini-3-flash-preview", "gemini-3.8-flash",
                     "gemini-flash-latest")
_NEXA_TTS_MODELS = ("gemini-2.5-flash-preview-tts",
                    "gemini-3.8-flash-tts")


def _gemini_chat(message, history):
    key = settings.GEMINI_API_KEY
    if not key:
        return None
    contents = []
    for h in (history or [])[-6:]:
        if not isinstance(h, dict):
            continue
        txt = str(h.get("text", ""))[:500].strip()
        if txt:
            contents.append({
                "role": "model" if h.get("role") == "nexa" else "user",
                "parts": [{"text": txt}]})
    contents.append({"role": "user", "parts": [{"text": message}]})
    # Phase 72 (owner: she answers too slowly): the flash models
    # spent 300+ tokens "thinking" before every short reply.
    # thinkingBudget 0 turns that off (verified live: full answer,
    # zero thought tokens). If a model ever rejects the field with
    # a 400, the same model is retried once without it.
    gen = {"maxOutputTokens": 1500, "temperature": 0.7,
           "thinkingConfig": {"thinkingBudget": 0}}
    body = {
        "system_instruction": {"parts": [{"text": _NEXA_SYSTEM}]},
        "contents": contents,
        "generationConfig": gen,
    }
    for model in _NEXA_CHAT_MODELS:
        for attempt in (gen, {"maxOutputTokens": 1500,
                              "temperature": 0.7}):
            body["generationConfig"] = attempt
            try:
                r = httpx.post(
                    "https://generativelanguage.googleapis.com/"
                    "v1beta/"
                    f"models/{model}:generateContent",
                    headers={"x-goog-api-key": key}, json=body,
                    timeout=20)
            except Exception:
                break
            if r.status_code == 400 and attempt is gen:
                continue
            if r.status_code != 200:
                break
            try:
                parts = r.json()["candidates"][0]["content"]["parts"]
                out = "".join(p.get("text", "")
                              for p in parts).strip()
            except Exception:
                break
            if out:
                return out[:900]
            break
    return None


def _gemini_tts(text):
    """Gemini TTS with the youthful 'Leda' voice. Returns base64
    WAV bytes, or None (client then uses the phone's own voice)."""
    key = settings.GEMINI_API_KEY
    if not key:
        return None
    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {
                "voiceName": "Leda"}}},
        },
    }
    for model in _NEXA_TTS_MODELS:
        try:
            r = httpx.post(
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/{model}:generateContent",
                headers={"x-goog-api-key": key}, json=body, timeout=25)
            if r.status_code != 200:
                continue
            data = r.json()["candidates"][0]["content"]["parts"][0]
            pcm = _b64.b64decode(data["inlineData"]["data"])
            buf = _io.BytesIO()
            with _wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(pcm)
            return _b64.b64encode(buf.getvalue()).decode()
        except Exception:
            continue
    return None



# --- Phase 78: Nearby — an opt-in live map of members around you --
# A member appears ONLY while sharing is on and their fix is fresh
# (<= 10 min, i.e. their app is open). To see others you must share
# yourself. Mutual follows get the exact spot; everyone else is
# shown fuzzed by a stable 50-100 m offset (same all day, so the
# dot does not jump) — close enough to meet, never a stranger's
# doorstep. Blocked pairs never see each other.

class LocationIn(BaseModel):
    lat: float
    lon: float
    share: bool = True


def _haversine_m(lat1, lon1, lat2, lon2):
    from math import asin, cos, radians, sin, sqrt
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (sin(dlat / 2) ** 2
         + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2)
    return 6371000 * 2 * asin(sqrt(a))


def _bearing_deg(lat1, lon1, lat2, lon2):
    from math import atan2, cos, degrees, radians, sin
    dlon = radians(lon2 - lon1)
    x = sin(dlon) * cos(radians(lat2))
    y = (cos(radians(lat1)) * sin(radians(lat2))
         - sin(radians(lat1)) * cos(radians(lat2)) * cos(dlon))
    return (degrees(atan2(x, y)) + 360) % 360


def _fuzz(lat, lon, tid):
    """A stable 50-100 m offset for one member for one day."""
    import hashlib
    from math import cos, pi, radians, sin
    seed = int(hashlib.sha256(
        f"nx-fuzz:{tid}:{datetime.utcnow():%Y-%m-%d}".encode()
    ).hexdigest()[:8], 16)
    ang = (seed % 360) * pi / 180.0
    dist = 50 + (seed >> 9) % 51
    dlat = dist * cos(ang) / 111320.0
    dlon = dist * sin(ang) / (111320.0 * max(0.2, cos(radians(lat))))
    return lat + dlat, lon + dlon


@app.post("/me/location")
def update_location(body: LocationIn,
                    user: models.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    _enforce_rate("location", f"u{user.telegram_id}")
    if not body.share:
        user.share_location = False
        user.lat = None
        user.lon = None
        user.loc_at = None
        db.commit()
        return {"ok": True, "sharing": False}
    if not (-90 <= body.lat <= 90 and -180 <= body.lon <= 180):
        raise HTTPException(400, "Invalid coordinates")
    user.share_location = True
    user.lat = body.lat
    user.lon = body.lon
    user.loc_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "sharing": True}


@app.get("/me/nearby")
def nearby(user: models.User = Depends(current_user),
           db: Session = Depends(get_db)):
    fresh = datetime.utcnow() - timedelta(minutes=10)
    if (not user.share_location or user.lat is None or user.lon is None
            or user.loc_at is None or user.loc_at < fresh):
        return {"sharing": False, "people": []}
    blocked = _block_related_ids(db, user.telegram_id)
    rows = (db.query(models.User)
            .filter(models.User.share_location.is_(True),
                    models.User.loc_at >= fresh,
                    models.User.telegram_id != user.telegram_id,
                    models.User.is_banned.is_(False))
            .all())
    i_follow = {f.following_id for f in db.query(models.Follow)
                .filter_by(follower_id=user.telegram_id).all()}
    follows_me = {f.follower_id for f in db.query(models.Follow)
                  .filter_by(following_id=user.telegram_id).all()}
    people = []
    for u in rows:
        if u.telegram_id in blocked or u.lat is None or u.lon is None:
            continue
        if _haversine_m(user.lat, user.lon, u.lat, u.lon) > 500:
            continue
        mutual = (u.telegram_id in i_follow
                  and u.telegram_id in follows_me)
        dlat, dlon = ((u.lat, u.lon) if mutual
                      else _fuzz(u.lat, u.lon, u.telegram_id))
        people.append({
            "id": u.telegram_id,
            "name": u.first_name or "Member",
            "username": u.username or "",
            "verified": bool(u.is_verified),
            "photo_file_id": u.photo_file_id,
            "lat": round(dlat, 6), "lon": round(dlon, 6),
            "distance_m": int(round(
                _haversine_m(user.lat, user.lon, dlat, dlon))),
            "bearing": int(round(
                _bearing_deg(user.lat, user.lon, dlat, dlon))),
            "mutual": mutual,
        })
    people.sort(key=lambda q: q["distance_m"])
    return {"sharing": True,
            "me": {"lat": user.lat, "lon": user.lon},
            "people": people}


@app.get("/assistant/status")
def assistant_status(user: models.User = Depends(current_user)):
    return {"name": "Nexa", "ai": bool(settings.GEMINI_API_KEY)}


@app.post("/assistant/chat")
def assistant_chat(body: AssistantChatIn,
                   user: models.User = Depends(current_user)):
    _enforce_rate("assistant_chat", f"u{user.telegram_id}")
    msg = (body.message or "").strip()
    if not msg:
        raise HTTPException(400, "Say something first")
    reply = _gemini_chat(msg, body.history) or _nexa_fallback(msg)
    return {"reply": reply, "ai": bool(settings.GEMINI_API_KEY)}


@app.post("/assistant/reply")
def assistant_reply(body: AssistantChatIn,
                    user: models.User = Depends(current_user)):
    """Phase 71: chat + voice in ONE call. Two sequential calls
    (chat, then speak) made playback start seconds after the
    member's tap, and the WebView then refused to play the audio
    at all — Nexa seemed to answer in text only."""
    _enforce_rate("assistant_chat", f"u{user.telegram_id}")
    _enforce_rate("assistant_speak", f"u{user.telegram_id}")
    msg = (body.message or "").strip()
    if not msg:
        raise HTTPException(400, "Say something first")
    reply = _gemini_chat(msg, body.history) or _nexa_fallback(msg)
    audio = _gemini_tts(reply[:650])
    return {"reply": reply, "audio": audio,
            "mime": "audio/wav" if audio else None,
            "ai": bool(settings.GEMINI_API_KEY)}


@app.post("/assistant/speak")
def assistant_speak(body: AssistantSpeakIn,
                    user: models.User = Depends(current_user)):
    _enforce_rate("assistant_speak", f"u{user.telegram_id}")
    text = (body.text or "").strip()[:650]
    if not text:
        raise HTTPException(400, "Nothing to say")
    audio = _gemini_tts(text)
    if audio is None:
        return {"audio": None}
    return {"audio": audio, "mime": "audio/wav"}
