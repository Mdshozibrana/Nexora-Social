"""FastAPI backend: auth, feed, posts, likes, comments, profiles, follow,
referrals, points, search, reports, media proxy, and the Mini App host.
Only the PRD section-8 admin endpoints remain for a later phase."""
import asyncio
import contextvars
from decimal import Decimal, InvalidOperation
import html
import json
import logging
import os
import random
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import (Depends, FastAPI, File, Form, Header, HTTPException,
                     Query, Request, UploadFile)
from fastapi.responses import HTMLResponse, JSONResponse, \
    RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, inspect, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from telegram import LabeledPrice

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import filesig, geoip, imgconv, models, moderation, notify, \
    ratelimit, \
    tgupload, videoutil
from .config import (ADS_PROVIDER_LIVE, DAILY_TASKS, MONETIZATION,
                     OFFICIAL_FOLLOWER_BASE,
                     OFFICIAL_ID, OFFICIAL_NAME, PAYOUT_NETWORKS,
                     RATE_LIMITS, VERIFICATION_MIN_FOLLOWERS,
                     VERIFICATION_MIN_REFERRALS, settings)
from .db import Base, SessionLocal, engine, get_db
from .security import init_data_auth_date, validate_init_data
from .services import (BANNED_WORD_MESSAGE, award_points,
                      banned_word_in, extract_hashtags, register_post,
                      sync_mentions)
from .users import get_or_create_user

# Phase 28 (security §13): security events go to the service log —
# rejected logins, admin denials, rate-limit hits, admin actions.
# NEVER log initData, tokens or message content.
sec_log = logging.getLogger("nexora.security")

# Phase 130: process start time, for the System Health card.
_STARTED_AT = time.time()

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
              "lon": "FLOAT", "loc_at": "TIMESTAMP",
              # Phase 144: notification prefs JSON (one TEXT
              # column, no new table — backup was 42 at Phase 144).
              "notif_prefs": "TEXT"}
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
    # Phase 118: reposts on posts, replies on comments.
    with engine.begin() as conn:
        if "repost_of_id" not in post_cols:
            conn.execute(text(
                "ALTER TABLE posts ADD COLUMN repost_of_id INTEGER"))
        if "repost_count" not in post_cols:
            conn.execute(text(
                "ALTER TABLE posts ADD COLUMN "
                "repost_count INTEGER DEFAULT 0"))
    comment_cols = {c["name"]
                  for c in inspect(engine).get_columns("comments")}
    with engine.begin() as conn:
        if "parent_id" not in comment_cols:
            conn.execute(text(
                "ALTER TABLE comments ADD COLUMN parent_id INTEGER"))
    # Phase 118: reposts on posts, replies on comments.
    with engine.begin() as conn:
        if "repost_of_id" not in post_cols:
            conn.execute(text(
                "ALTER TABLE posts ADD COLUMN repost_of_id INTEGER"))
        if "repost_count" not in post_cols:
            conn.execute(text(
                "ALTER TABLE posts ADD COLUMN "
                "repost_count INTEGER DEFAULT 0"))
    comment_cols = {c["name"]
                  for c in inspect(engine).get_columns("comments")}
    with engine.begin() as conn:
        if "parent_id" not in comment_cols:
            conn.execute(text(
                "ALTER TABLE comments ADD COLUMN parent_id INTEGER"))
    # Phase 123: creator tools — one pinned post per author.
    with engine.begin() as conn:
        if "is_pinned" not in post_cols:
            conn.execute(text(
                "ALTER TABLE posts ADD COLUMN is_pinned BOOLEAN DEFAULT FALSE"))
    # Phase 167: inbox posts. Phase 169 removed the Nexora
    # Inbox page; the column is RETAINED (unused) so old posts
    # keep their flag — never drop it. (Postgres-legal DEFAULT
    # FALSE; the Phase 126 lesson: never a 0 default on a
    # boolean in raw SQL).
    with engine.begin() as conn:
        if "via_inbox" not in post_cols:
            conn.execute(text(
                "ALTER TABLE posts ADD COLUMN via_inbox BOOLEAN DEFAULT FALSE"))
    # Phase 127: crypto payout wallet columns on users (plain
    # VARCHAR, no default — the Phase 126 lesson: never a BOOLEAN
    # DEFAULT 0 in raw migration SQL; SQLite accepts it, Postgres
    # does not).
    with engine.begin() as conn:
        if "wallet_address" not in existing:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN wallet_address VARCHAR(256)"))
        if "wallet_network" not in existing:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN wallet_network VARCHAR(16)"))
    # Phase 136: private accounts — posts visible only to
    # approved followers (Postgres-legal DEFAULT FALSE; the
    # Phase 126 lesson: never a 0 default on a boolean in raw SQL).
    with engine.begin() as conn:
        if "is_private" not in existing:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN is_private BOOLEAN DEFAULT FALSE"))
    # Phase 151: blood donors — group + opt-in flag on users
    # (Postgres-legal DEFAULT FALSE; the Phase 126 lesson:
    # never a 0 default on a boolean in raw SQL).
    with engine.begin() as conn:
        if "blood_group" not in existing:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN blood_group VARCHAR(3)"))
        if "blood_donor" not in existing:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN blood_donor BOOLEAN DEFAULT FALSE"))
    # Phase 138: DM photos — media columns on messages (plain
    # VARCHAR, nullable; create_all never alters existing tables).
    msg_cols = {c["name"] for c in inspect(engine).get_columns("messages")}
    with engine.begin() as conn:
        if "media_file_id" not in msg_cols:
            conn.execute(text(
                "ALTER TABLE messages ADD COLUMN media_file_id VARCHAR(256)"))
        if "media_type" not in msg_cols:
            conn.execute(text(
                "ALTER TABLE messages ADD COLUMN media_type VARCHAR(16)"))
        if "media_duration" not in msg_cols:
            conn.execute(text(
                "ALTER TABLE messages ADD COLUMN media_duration INTEGER"))
    # Phase 139: story replies — story_id on messages (plain
    # INTEGER, nullable, no FK: a reply outlives its story, and
    # deleting the story must never fail on the reference).
    with engine.begin() as conn:
        if "story_id" not in msg_cols:
            conn.execute(text(
                "ALTER TABLE messages ADD COLUMN story_id INTEGER"))
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
# Phase 147: the 3D Nearby map (MapLibre) fetches vector tiles,
# glyphs and sprites from tiles.openfreemap.org (connect-src)
# and runs its renderer in a blob: Web Worker (worker-src) —
# without worker-src the worker falls back to script-src,
# which has no blob:, and the 3D map would fail silently.
# Phase 149: Nearby Street View (Mapillary) fetches the
# nearest image from graph.mapillary.com and its pixels from
# images.mapillary.com (connect-src); thumbs also load as
# <img> (img-src already allows https:).
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
    "connect-src 'self' https://sad.adsgram.ai https://api.adsgram.ai https://routing.openstreetmap.de https://tiles.openfreemap.org https://graph.mapillary.com https://images.mapillary.com; "
    "worker-src 'self' blob:; "
    "font-src 'self' data:; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'self' https://web.telegram.org "
    "https://web-a.telegram.org https://*.telegram.org"
)


def _maintenance_on_db() -> bool:
    """Phase 119: runtime maintenance flag (Control Panel toggle),
    stored in app_settings as key "maintenance" = "1". A DB failure
    falls back to the env flag only — the panel toggle never breaks
    the API by itself."""
    try:
        db = SessionLocal()
        try:
            row = db.get(models.AppSetting, "maintenance")
            return bool(row is not None and row.value == "1")
        finally:
            db.close()
    except Exception:
        return False


@app.middleware("http")
async def security_middleware(request, call_next):
    # Emergency maintenance mode (§14): the API pauses with 503 while
    # the shell and /health stay up, so the platform can be frozen
    # during an incident without stopping the service.
    # Phase 119: the env flag still wins, but the owner can also flip
    # maintenance from the Control Panel (the app_settings row
    # "maintenance"). /admin/maintenance itself stays reachable so
    # the panel can always switch the site back on.
    if (settings.MAINTENANCE_MODE == "1" or _maintenance_on_db()) \
            and request.url.path != "/health" \
            and request.url.path != "/admin/maintenance" \
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
    log_security_event(None, "server_error", detail=
                       f"{request.method} {request.url.path} "
                       f"({type(exc).__name__})")
    return JSONResponse(status_code=500,
                        content={"detail": "Something went wrong — "
                                           "please try again"})


def _client_ip(request) -> str:
    # Phase 164 (H2): Render appends the real client IP as the LAST
    # X-Forwarded-For entry — the first entry is client-chosen and
    # spoofable, so trusting it let anyone dodge the per-IP /auth
    # budget by rotating fake values.
    fwd = request.headers.get("x-forwarded-for") or ""
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _enforce_rate(bucket: str, key: str):
    """Raise 429 when the (owner-adjustable) budget for an action is
    exhausted — security §3/§6 rate limiting."""
    limit, window = RATE_LIMITS[bucket]
    if not ratelimit.hit(bucket, key, limit, window):
        sec_log.warning("rate limit hit: %s key=%s", bucket, key)
        actor = None
        if key.startswith("u") and key[1:].isdigit():
            actor = int(key[1:])
        log_security_event(None, "rate_limit", actor_id=actor,
                           detail=f"bucket {bucket} key {key}")
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


_SECURITY_KINDS = ("screen_reject", "rate_limit", "auth_reject",
                   "admin_denied", "server_error", "account_delete")
_SECURITY_EVENT_MAX = 1000


def log_security_event(db, kind, actor_id=None, target_id=None,
                       detail=""):
    """Phase 128: persist one security event. The write rides its
    OWN session when no db is passed — and commits at once even
    when one is: most call sites raise right after logging, which
    would roll a caller-bound row back, and the middleware has no
    db at all. A failure to log must never break the request, so
    every error is swallowed. Details are one-line summaries only
    — never a traceback."""
    try:
        own = db is None
        s = SessionLocal() if own else db
        try:
            s.add(models.SecurityEvent(
                kind=kind, actor_id=actor_id, target_id=target_id,
                detail=(detail or "")[:512]))
            s.flush()
            n = s.query(models.SecurityEvent).count()
            if n > _SECURITY_EVENT_MAX:
                old = s.query(models.SecurityEvent) \
                    .order_by(models.SecurityEvent.id.asc()) \
                    .limit(n - _SECURITY_EVENT_MAX).all()
                for row in old:
                    s.delete(row)
            s.commit()
        finally:
            if own:
                s.close()
    except Exception:
        pass


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


def _media_token(user_id: int) -> str:
    """Phase 164 (P1): user-bound signed capability for /media URLs
    (HMAC over user id + issue time + expiry, 1 hour), so the token
    alone never opens another member's media. <img> and <video> tags
    cannot send the X-Init-Data header, so the capability rides in
    the URL; the app fetches a fresh one at every open via /auth and
    refreshes it while open (see refreshMediaToken). The issue time
    lets the handler honour session revocation."""
    import base64
    import hashlib as _hl
    import hmac as _hm
    iat = int(time.time())
    exp = iat + 3600
    sig = _hm.new(settings.BOT_TOKEN.encode(),
                  f"nexora-media:{user_id}:{iat}:{exp}".encode(),
                  _hl.sha256).hexdigest()
    raw = f"{user_id}.{iat}.{exp}.{sig}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def _profile_link(telegram_id: int) -> str:
    """Phase 114: the deep link a member's QR code carries — the bot
    deep link, mirroring the referral link (?start=ref_<id>)."""
    return (f"https://t.me/{settings.BOT_USERNAME}"
            f"?start=profile_{telegram_id}")


def _qr_token(user_id: int) -> str:
    """Phase 114: user-bound signed capability for /me/qr — same
    shape as _media_token (HMAC over user id + expiry, 7 days), so
    the QR image URL carries its own auth and <img> tags work."""
    import base64
    import hashlib as _hl
    import hmac as _hm
    exp = int(time.time()) + 7 * 86400
    sig = _hm.new(settings.BOT_TOKEN.encode(),
                  f"nexora-qr:{user_id}:{exp}".encode(),
                  _hl.sha256).hexdigest()
    raw = f"{user_id}.{exp}.{sig}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def _qr_token_ok(token: str):
    """Phase 114: verify a QR token; returns the user id, or None."""
    import base64
    import hashlib as _hl
    import hmac as _hm
    if not token or not settings.BOT_TOKEN:
        return None
    try:
        decoded = base64.urlsafe_b64decode(
            token.encode()).decode()
        user_s, exp_s, sig = decoded.split(".", 2)
        user_id, exp = int(user_s), int(exp_s)
    except Exception:
        return None
    if exp < int(time.time()):
        return None
    expected = _hm.new(settings.BOT_TOKEN.encode(),
                       f"nexora-qr:{user_id}:{exp}".encode(),
                       _hl.sha256).hexdigest()
    if not _hm.compare_digest(expected, sig):
        return None
    return user_id


def _build_profile_qr_png(link: str) -> bytes:
    """Phase 114: the branded QR image — error-correction Q, a
    white quiet zone on all sides, and NEXORA SOCIAL in bold ink in
    the free space at the bottom (owner's design). DejaVu Bold is
    tried first (present on the sandbox and Render's Debian image);
    PIL's built-in font is the fallback so the label never vanishes.
    """
    import io as _io
    import qrcode
    from PIL import Image, ImageDraw, ImageFont
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_Q,
                       box_size=10, border=1)
    qr.add_data(link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black",
                        back_color="white").convert("RGB")
    side, top, bottom = 40, 40, 140
    canvas = Image.new("RGB", (img.size[0] + side * 2,
                               img.size[1] + top + bottom), "white")
    canvas.paste(img, (side, top))
    font = None
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(path, 30)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(canvas)
    draw.text((canvas.size[0] / 2, img.size[1] + top + 45),
              "NEXORA SOCIAL", fill=(58, 46, 51), font=font, anchor="mm")
    buf = _io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def _media_token_ok(token: str):
    """Phase 164 (P1): verify a media token; returns (user_id,
    issued_at) or None. Mirrors _qr_token_ok (Phase 114)."""
    import base64
    import hashlib as _hl
    import hmac as _hm
    if not token or not settings.BOT_TOKEN:
        return None
    try:
        decoded = base64.urlsafe_b64decode(
            token.encode()).decode()
        user_s, iat_s, exp_s, sig = decoded.split(".", 3)
        user_id, iat, exp = int(user_s), int(iat_s), int(exp_s)
    except Exception:
        return None
    if exp < int(time.time()):
        return None
    expected = _hm.new(settings.BOT_TOKEN.encode(),
                       f"nexora-media:{user_id}:{iat}:{exp}".encode(),
                       _hl.sha256).hexdigest()
    if not _hm.compare_digest(expected, sig):
        return None
    return user_id, iat


def _story_in_visible_highlight(db, viewer_id, story_id):
    """Phase 172: True when the story sits in a highlight whose
    owner the viewer may see (private-account + block rules apply;
    the story author IS the highlight owner, and the block check
    already ran in the caller). Phase 179 (audit M2): a muted
    highlight owner stays hidden too — muted members' stories
    disappear from the muter's views (PRD Phase 174)."""
    rows = db.query(models.HighlightStory).filter_by(
        story_id=story_id).all()
    for row in rows:
        h = db.get(models.StoryHighlight, row.highlight_id)
        if (h is not None
                and not _muted_by(db, viewer_id, h.user_id)
                and _can_see_posts(db, viewer_id, h.user_id)):
            return True
    return False


def _media_visible(db, viewer_id: int, file_id: str) -> bool:
    """Phase 164 (P1): may viewer_id see this Telegram file_id?
    The file's owner is resolved from the tables that hold it, and
    the same visibility rules the feed uses apply — private-account
    + block rules for posts/profiles, participants-only for DM
    photos, live-only for stories. Phase 179 (audit M1): mute
    joins them — a muted author's media never loads for the
    muter (the muted author's own view of their own media still
    passes: mute is one-directional). Unknown file_ids fail
    closed (404): a token alone never opens a file."""
    if not file_id:
        return False
    post = db.query(models.Post).filter(
        (models.Post.media_file_id == file_id)
        | (models.Post.thumb_file_id == file_id),
        models.Post.is_deleted == False).first()  # noqa: E712
    if post is not None:
        if _blocked_by(db, post.user_id, viewer_id) or _blocked_by(
                db, viewer_id, post.user_id):
            return False
        # Phase 179 (audit M1): muted author's media is hidden.
        if (post.user_id != viewer_id
                and _muted_by(db, viewer_id, post.user_id)):
            return False
        return _can_see_posts(db, viewer_id, post.user_id)
    pm = db.query(models.PostMedia).filter_by(file_id=file_id).first()
    if pm is not None:
        post = db.get(models.Post, pm.post_id)
        if post is not None and not post.is_deleted:
            if _blocked_by(db, post.user_id, viewer_id) or _blocked_by(
                    db, viewer_id, post.user_id):
                return False
            # Phase 179 (audit M1): muted author's album media
            # is hidden too (own media still passes).
            if (post.user_id != viewer_id
                    and _muted_by(db, viewer_id, post.user_id)):
                return False
            return _can_see_posts(db, viewer_id, post.user_id)
    story = db.query(models.Story).filter_by(
        media_file_id=file_id).first()
    if story is not None:
        if _blocked_by(db, story.user_id, viewer_id) or _blocked_by(
                db, viewer_id, story.user_id):
            return False
        # Phase 179 (audit M1): a muted author's story media is
        # hidden too (own stories still pass).
        if (story.user_id != viewer_id
                and _muted_by(db, viewer_id, story.user_id)):
            return False
        if story.created_at is not None and (
                datetime.utcnow() - story.created_at).total_seconds() > 86400:
            # Phase 172: an expired story stays viewable only inside
            # a highlight the viewer may see — nowhere else.
            return _story_in_visible_highlight(db, viewer_id, story.id)
        return _can_see_posts(db, viewer_id, story.user_id)
    msg = db.query(models.Message).filter_by(
        media_file_id=file_id).first()
    if msg is not None:
        return viewer_id in (msg.sender_id, msg.recipient_id)
    design = db.query(models.Design).filter_by(
        image_file_id=file_id).first()
    if design is not None:
        return True  # designs are the public official gallery
    owner = db.query(models.User).filter(
        (models.User.photo_file_id == file_id)
        | (models.User.cover_file_id == file_id)).first()
    if owner is not None:
        if _blocked_by(db, owner.telegram_id, viewer_id) or _blocked_by(
                db, viewer_id, owner.telegram_id):
            return False
        # Phase 179 (audit M1): a muted member's profile photo /
        # cover is hidden too (own photo still passes).
        if (owner.telegram_id != viewer_id
                and _muted_by(db, viewer_id, owner.telegram_id)):
            return False
        return _can_see_posts(db, viewer_id, owner.telegram_id)
    draft = db.query(models.Draft).filter_by(
        media_file_id=file_id).first()
    if draft is not None:
        return draft.user_id == viewer_id
    sched = db.query(models.ScheduledPost).filter_by(
        media_file_id=file_id).first()
    if sched is not None:
        return sched.user_id == viewer_id
    return False


def _like_pattern(q: str) -> str:
    """Escape LIKE wildcards in user search text (M3) — pair with
    .ilike(pattern, escape="\\\\") at the call site."""
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%") \
        .replace("_", "\\_") + "%"
WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"

_bot_app = None


@app.on_event("startup")
async def _startup():
    global _bot_app, _sweeper_task, _auto_backup_task
    if settings.BOT_TOKEN:
        from .bot import build_bot_app, start_bot
        _bot_app = build_bot_app()
        await start_bot(_bot_app)

    _sweeper_task = asyncio.create_task(_scheduled_posts_loop())
    _auto_backup_task = asyncio.create_task(_auto_backup_loop())


@app.on_event("shutdown")
async def _shutdown():
    global _sweeper_task, _auto_backup_task
    if _sweeper_task is not None:
        _sweeper_task.cancel()
        try:
            await _sweeper_task
        except asyncio.CancelledError:
            pass
        _sweeper_task = None
    if _auto_backup_task is not None:
        _auto_backup_task.cancel()
        try:
            await _auto_backup_task
        except asyncio.CancelledError:
            pass
        _auto_backup_task = None
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
        log_security_event(db, "auth_reject", detail=
                           "Invalid initData on API request")
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
        log_security_event(db, "auth_reject", detail=
                           "Invalid initData at /auth")
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
        # Phase 164 (H2): the country lookup uses the same
        # proxy-appended IP as the rate limiter — never a
        # client-supplied first hop.
        country = await geoip.lookup_country(_client_ip(request))
        if country:
            user.country = country
            db.commit()
    followers = db.query(models.Follow).filter_by(following_id=user.telegram_id).count()
    following = db.query(models.Follow).filter_by(follower_id=user.telegram_id).count()
    posts = db.query(models.Post).filter_by(user_id=user.telegram_id, is_deleted=False).filter(models.Post.type != "repost").count()
    level_badges = _level_and_badges(db, user)
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
        "media_token": _media_token(user.telegram_id),
        "adsgram_block_id": settings.ADSGRAM_BLOCK_ID,
        "mapillary_client_token": settings.MAPILLARY_CLIENT_TOKEN,
        # Phase 151: the caller's own blood-donor status.
        "blood_group": user.blood_group,
        "blood_donor": bool(getattr(user, "blood_donor", False)),
        # Phase 137: level (from lifetime points) + badges.
        "level": level_badges["level"],
        "badges": level_badges["badges"],
    }


@app.get("/feed")
def feed(tab: str = "explore", type: str = "", cursor: int = 0,
         user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    # Phase 179 (audit M4): the feed is the hottest read path —
    # tabs, pull-to-refresh, "Load more" paging and the Videos
    # tab all call it. 600/h per member is far above a normal
    # session; it exists to stop scripts, not people.
    _enforce_rate("feed", f"u{user.telegram_id}")
    q = db.query(models.Post).filter_by(is_deleted=False)
    hidden = _block_related_ids(db, user.telegram_id)
    if hidden:
        q = q.filter(~models.Post.user_id.in_(hidden))
    # Phase 174: a muted member's posts never reach the muter's
    # feed — Explore, Following and (via the same filter) the
    # hashtag feed below.
    muted = _muted_ids(db, user.telegram_id)
    if muted:
        q = q.filter(~models.Post.user_id.in_(muted))
    # Phase 136: a private account's posts reach only its
    # followers (and itself) — everyone else never sees them.
    blocked_private = set()
    private_ids = _private_author_ids(db)
    if private_ids:
        followed = {f.following_id for f in
                    db.query(models.Follow).filter_by(
                        follower_id=user.telegram_id)}
        blocked_private = private_ids - followed - {user.telegram_id}
        if blocked_private:
            q = q.filter(~models.Post.user_id.in_(blocked_private))
    if type in ("photo", "video", "text"):
        # Phase 118: repost rows carry type "repost" — they ride
        # along and are matched against the ORIGINAL's type below.
        q = q.filter(or_(models.Post.type == type,
                         models.Post.type == "repost"))
    else:
        # Phase 35 (owner directive): the Feed page shows statuses
        # and photos only — videos live on the Videos page, whose
        # loader always asks with type=video explicitly.
        q = q.filter(models.Post.type != "video")
    if tab == "following":
        ids = [f.following_id for f in
               db.query(models.Follow).filter_by(follower_id=user.telegram_id)]
        q = q.filter(models.Post.user_id.in_(ids or [-1]))
    # Phase 179 (audit M5): the cursor used to be set from
    # the pre-filter page, so a page could return 0 posts with a
    # non-null cursor. Fetch-then-filter in a loop instead: keep
    # pulling 20-row source batches until the page holds 20 kept
    # posts or the source is exhausted — keeping one row past
    # the page as a peek, so the cursor is non-null ONLY when a
    # 21st kept post exists (the client never gets an empty page,
    # not even a trailing one when the total is an exact multiple
    # of 20; the peeked row is not shown, it leads the next page).
    # Ids strictly decrease, so the loop always terminates.
    # Cursor format is unchanged (a post id, as the client
    # already understands).
    keep = []
    next_cursor = None
    last_examined = cursor
    exhausted = False
    while len(keep) < 21 and not exhausted:
        page_q = q
        if last_examined:
            page_q = page_q.filter(models.Post.id < last_examined)
        batch = page_q.order_by(models.Post.id.desc()).limit(20).all()
        if not batch:
            break
        if len(batch) < 20:
            exhausted = True
        # Phase 118: a repost shows its original — and a repost of
        # a video belongs on the Videos tab, not the main feed
        # (the Phase 35 rule, applied to the original's type).
        for p in batch:
            last_examined = p.id
            if not getattr(p, "repost_of_id", None):
                keep.append(p)
            else:
                orig = db.get(models.Post, p.repost_of_id)
                if orig is None or orig.is_deleted:
                    continue
                # Phase 136: a repost must not leak a private author's post.
                if orig.user_id in blocked_private:
                    continue
                # Phase 174: nor a muted author's post, reposted by
                # someone else.
                if orig.user_id in muted:
                    continue
                # Phase 177: nor a blocked author's post, reposted by
                # someone else (either block direction).
                if orig.user_id in hidden:
                    continue
                if type in ("photo", "video", "text"):
                    if orig.type == type:
                        keep.append(p)
                elif orig.type != "video":
                    keep.append(p)
            if len(keep) >= 21:
                break
    if len(keep) > 20:
        next_cursor = keep[19].id
        keep = keep[:20]
    rows = keep
    counts = _post_view_counts(db, rows)
    _warm_authors(db, rows)
    out = _post_list(db, rows, user.telegram_id, counts=counts)
    return {"posts": out, "next_cursor": next_cursor}


@app.get("/feed/hashtags")
def hashtag_feed(cursor: int = 0,
                 user: models.User = Depends(current_user),
                 db: Session = Depends(get_db)):
    """Phase 140: posts carrying ANY hashtag the caller follows —
    newest first, cursor-paged like /feed. Only originals match:
    repost rows carry no hashtags of their own (Phase 118), so a
    repost of a #tech post does not appear here — exactly like
    the #tag search. Private authors' posts reach only their
    followers (Phase 136); blocked authors stay hidden; videos
    are excluded, as on the main feed (Phase 35)."""
    # Phase 179 (audit M4): same "feed" budget as /feed —
    # the hashtag tab is the same loader, same call pattern.
    _enforce_rate("feed", f"u{user.telegram_id}")
    tags = {f.tag for f in db.query(models.HashtagFollow).filter_by(
        user_id=user.telegram_id)}
    if not tags:
        return {"posts": [], "next_cursor": None}
    hidden = _block_related_ids(db, user.telegram_id)
    private_ids = _private_author_ids(db)
    followed = {f.following_id for f in
                db.query(models.Follow).filter_by(
                    follower_id=user.telegram_id)} if private_ids else set()
    blocked_private = private_ids - followed - {user.telegram_id}

    def _tag_filter(col, tag):
        # A tag sits at the start, in the middle, at the end, or
        # alone in the space-joined hashtags column.
        return or_(col == tag,
                   col.like(tag + " %"),
                   col.like("% " + tag + " %"),
                   col.like("% " + tag))

    q = db.query(models.Post).filter_by(is_deleted=False).filter(
        models.Post.type != "repost",
        models.Post.type != "video",
        or_(*[_tag_filter(models.Post.hashtags, t)
              for t in sorted(tags)]))
    if hidden:
        q = q.filter(~models.Post.user_id.in_(hidden))
    # Phase 174: muted authors stay out of the hashtag feed too.
    muted = _muted_ids(db, user.telegram_id)
    if muted:
        q = q.filter(~models.Post.user_id.in_(muted))
    if blocked_private:
        q = q.filter(~models.Post.user_id.in_(blocked_private))
    # Phase 179 (audit M5): same fetch-then-filter loop as
    # /feed, so the cursor reflects the post-filter page (with
    # the same 21st-row peek: non-null only when another kept
    # post exists). (No Python filter runs here — block/mute/
    # private are all query-level — so the loop normally ends
    # after one batch; the shape is kept uniform with /feed.)
    rows = []
    next_cursor = None
    last_examined = cursor
    exhausted = False
    while len(rows) < 21 and not exhausted:
        page_q = q
        if last_examined:
            page_q = page_q.filter(models.Post.id < last_examined)
        batch = page_q.order_by(models.Post.id.desc()).limit(20).all()
        if not batch:
            break
        if len(batch) < 20:
            exhausted = True
        for p in batch:
            last_examined = p.id
            rows.append(p)
            if len(rows) >= 21:
                break
    if len(rows) > 20:
        next_cursor = rows[19].id
        rows = rows[:20]
    counts = _post_view_counts(db, rows)
    _warm_authors(db, rows)
    out = _post_list(db, rows, user.telegram_id, counts=counts)
    return {"posts": out, "next_cursor": next_cursor}


# ---------------------------------------------------------------------------
# Phase 122 — Trending: what is hot right now.
#
# VELOCITY FORMULA (PRD Phase 122 addendum, test_phase122):
#   score = (3 * likes_7d + 5 * comments_7d + 1 * views_7d)
#           / (1 + age_days)
# likes_7d / comments_7d / views_7d count only engagement from
# the last 7 days (Like/Comment/PostView.created_at); age_days
# is (now - post.created_at) in days, so a fresh post with the
# same engagement outranks an old one. Only score > 0 trends;
# ties break by newer post id; top 20. Repost rows are never
# entries — engagement keys off the original id, so a reposted
# post trends once, as its original. Blocked authors hidden,
# deleted posts excluded, all types share one list. No points
# are paid for trending views; opening a post counts its unique
# view exactly as the feed does (POST /posts/{id}/view).
# ---------------------------------------------------------------------------


def _engagement_counts(db, model, ids, since):
    """{post_id: n} rows of `model` (Like/Comment/PostView)
    created since `since`, grouped by post."""
    if not ids:
        return {}
    rows = db.query(model.post_id, func.count()).filter(
        model.post_id.in_(ids),
        model.created_at >= since).group_by(model.post_id).all()
    return {pid: n for pid, n in rows}


def _trending_ranked(db, user, limit=20):
    """(posts, extra) — non-deleted originals ranked by the
    velocity formula, plus per-post trend_24h / trend_7d
    counts for the rank line. `extra` maps post id to
    {"trend_score": float, "trend_24h": int, "trend_7d": int}."""
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    day_ago = now - timedelta(days=1)
    hidden = _block_related_ids(db, user.telegram_id)
    q = db.query(models.Post).filter_by(is_deleted=False).filter(
        models.Post.type != "repost")
    if hidden:
        q = q.filter(~models.Post.user_id.in_(hidden))
    # Phase 174: muted authors never trend for the muter.
    muted = _muted_ids(db, user.telegram_id)
    if muted:
        q = q.filter(~models.Post.user_id.in_(muted))
    # Phase 136: private accounts' posts never trend — Trending
    # is a public surface.
    private_ids = _private_author_ids(db)
    if private_ids:
        q = q.filter(~models.Post.user_id.in_(private_ids))
    rows = q.all()
    ids = [p.id for p in rows]
    likes7 = _engagement_counts(db, models.Like, ids, week_ago)
    comments7 = _engagement_counts(db, models.Comment, ids, week_ago)
    views7 = _engagement_counts(db, models.PostView, ids, week_ago)
    likes24 = _engagement_counts(db, models.Like, ids, day_ago)
    comments24 = _engagement_counts(db, models.Comment, ids, day_ago)
    views24 = _engagement_counts(db, models.PostView, ids, day_ago)
    scored = []
    for p in rows:
        l7 = likes7.get(p.id, 0)
        c7 = comments7.get(p.id, 0)
        v7 = views7.get(p.id, 0)
        if not (l7 or c7 or v7):
            continue
        age_days = max(0.0, (now - (p.created_at or now))
                       .total_seconds() / 86400.0)
        score = (3 * l7 + 5 * c7 + 1 * v7) / (1.0 + age_days)
        if score <= 0:
            continue
        scored.append((score, p.id, p,
                       likes24.get(p.id, 0)
                       + comments24.get(p.id, 0)
                       + views24.get(p.id, 0),
                       l7 + c7 + v7))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    top = scored[:limit]
    extra = {p.id: {"trend_score": round(score, 2),
                    "trend_24h": n24, "trend_7d": n7}
             for score, _pid, p, n24, n7 in top}
    return [p for _s, _i, p, _a, _b in top], extra


@app.get("/trending/posts")
def trending_posts(limit: int = 20,
                   user: models.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """Phase 122: posts ranked by recent engagement velocity."""
    _enforce_rate("trending", f"u{user.telegram_id}")
    limit = max(1, min(int(limit or 20), 20))
    rows, extra = _trending_ranked(db, user, limit=limit)
    counts = _post_view_counts(db, rows)
    _warm_authors(db, rows)
    out = _post_list(db, rows, user.telegram_id, counts=counts)
    for d in out:
        d.update(extra.get(d["id"], {}))
    return {"posts": out}


@app.get("/trending/hashtags")
def trending_hashtags(limit: int = 10,
                      user: models.User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """Phase 122: most-used hashtags on posts from the last
    7 days, most-used first (ties: alphabetical, so the order
    is deterministic). Blocked, muted and private authors are
    excluded, as are deleted posts; repost rows carry no
    hashtags of their own."""
    _enforce_rate("trending", f"u{user.telegram_id}")
    limit = max(1, min(int(limit or 10), 20))
    hidden = _block_related_ids(db, user.telegram_id)
    q = db.query(models.Post).filter_by(is_deleted=False).filter(
        models.Post.type != "repost",
        models.Post.created_at >= datetime.utcnow() - timedelta(days=7))
    if hidden:
        q = q.filter(~models.Post.user_id.in_(hidden))
    # Phase 179 (audit H8): the same exclusions _trending_ranked
    # applies to posts — muted authors never trend for the muter,
    # and private accounts' posts never trend (Trending is a
    # public surface), so neither inflates tag counts.
    muted = _muted_ids(db, user.telegram_id)
    if muted:
        q = q.filter(~models.Post.user_id.in_(muted))
    private_ids = _private_author_ids(db)
    if private_ids:
        q = q.filter(~models.Post.user_id.in_(private_ids))
    counts = {}
    for p in q.all():
        for tag in (p.hashtags or "").split():
            counts[tag] = counts.get(tag, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"hashtags": [{"tag": tag, "count": n}
                         for tag, n in ranked[:limit]]}


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
            user_id=cand.telegram_id, is_deleted=False).filter(models.Post.type != "repost").count()
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

def _poll_dict(db, p, viewer_id=None):
    """Phase 123: a post's poll, if any — options with live vote
    counts, the total, and which option the viewer picked."""
    poll = db.query(models.Poll).filter_by(post_id=p.id).first()
    if poll is None:
        return None
    opts = db.query(models.PollOption).filter_by(
        poll_id=poll.id).order_by(models.PollOption.position).all()
    counts = {}
    if opts:
        rows = db.query(models.PollVote.option_id, func.count()).filter(
            models.PollVote.option_id.in_([o.id for o in opts])).group_by(
            models.PollVote.option_id).all()
        counts = {oid: n for oid, n in rows}
    voted = None
    if viewer_id is not None and opts:
        v = db.query(models.PollVote).filter(
            models.PollVote.option_id.in_([o.id for o in opts]),
            models.PollVote.user_id == viewer_id).first()
        voted = v.option_id if v else None
    return {"id": poll.id, "question": poll.question,
            "options": [{"id": o.id, "text": o.text,
                         "votes": counts.get(o.id, 0)} for o in opts],
            "total_votes": sum(counts.values()),
            "voted_option_id": voted}


def _post_media_list(db, p):
    """Phase 171: the album items of a post, in position order.
    Single-media posts have no rows — the client falls back to
    media_file_id."""
    return [{"file_id": m.file_id, "media_type": m.media_type,
             "position": m.position}
            for m in db.query(models.PostMedia).filter_by(
                post_id=p.id).order_by(models.PostMedia.position).all()]


def _mention_list(db, p):
    """Phase 170: the @mentions on a post — username + id, for
    the tappable links the client renders in the caption."""
    out = []
    for m in db.query(models.Mention).filter_by(post_id=p.id).all():
        u = db.get(models.User, m.mentioned_id)
        if u is not None and u.username:
            out.append({"telegram_id": u.telegram_id,
                        "username": u.username})
    return out


def _comment_mention_list(db, cm):
    """Phase 170: same, for a comment."""
    out = []
    for m in db.query(models.Mention).filter_by(
            comment_id=cm.id).all():
        u = db.get(models.User, m.mentioned_id)
        if u is not None and u.username:
            out.append({"telegram_id": u.telegram_id,
                        "username": u.username})
    return out


def post_dict(db, p, liked=False, saved=False, views=None,
              reposted_by_me=False, viewer_id=None):
    # Phase 118: a repost row shows its ORIGINAL — the card's
    # id, likes, comments and views all belong to the original;
    # the repost itself only adds who shared it and when.
    if getattr(p, "repost_of_id", None):
        orig = db.get(models.Post, p.repost_of_id)
        if orig is None or orig.is_deleted:
            return None
        # Phase 178 (audit H3): a repost must not leak a
        # private or muted author's post either — the same
        # three rules the /feed keep-loop already applies to
        # repost originals (block either way, muted, private
        # non-followed), now in the one place every display
        # surface shares. The repost row is never deleted;
        # unblocking / unmuting / following restores it.
        if viewer_id is not None and not _post_visible_to(
                db, viewer_id, orig):
            return None
        d = post_dict(db, orig, liked=liked, saved=saved,
                      views=views, reposted_by_me=reposted_by_me,
                      viewer_id=viewer_id)
        reposter = db.get(models.User, p.user_id)
        d["reposted"] = True
        d["repost_id"] = p.id
        d["reposted_by_id"] = p.user_id
        d["reposted_by_name"] = (reposter.first_name
                                 if reposter else "")
        d["reposted_by_photo"] = (reposter.photo_file_id
                                  if reposter else None)
        d["reposted_at"] = (p.created_at.isoformat()
                            if p.created_at else None)
        return d
    author = db.get(models.User, p.user_id)
    if views is None:
        # Phase 31: unique-view count (post_views), shown on reels.
        views = db.query(models.PostView).filter_by(
            post_id=p.id).count()
    return {
        "id": p.id, "type": p.type, "media_file_id": p.media_file_id,
        "thumb_file_id": getattr(p, "thumb_file_id", None),
        "caption": p.caption, "hashtags": p.hashtags,
        "mentions": _mention_list(db, p),
        "media": _post_media_list(db, p),
        "like_count": p.like_count, "comment_count": p.comment_count,
        "repost_count": p.repost_count or 0,
        "is_pinned": bool(getattr(p, "is_pinned", False)),
        "poll": _poll_dict(db, p, viewer_id),
        "views": views,
        "liked": liked,
        "saved": saved,
        "reposted": False,
        "repost_of_id": None,
        "repost_id": None,
        "reposted_by_id": None,
        "reposted_by_name": "",
        "reposted_by_photo": None,
        "reposted_at": None,
        "reposted_by_me": bool(reposted_by_me),
        "author_id": p.user_id,
        "author_name": author.first_name if author else "",
        "author_username": author.username if author else None,
        "author_verified": bool(author and author.is_verified),
        "author_photo": author.photo_file_id if author else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _eff_id(p):
    """The post a card actually shows: a repost resolves to
    its original, so likes/saves/views/repost state all key
    off the original's id."""
    return getattr(p, "repost_of_id", None) or p.id


def reposted_ids(db, viewer_id, posts):
    """Which of these posts (by original id) the viewer
    reposted — the 🔁 button's active state."""
    ids = [_eff_id(p) for p in posts]
    if not ids:
        return set()
    rows = db.query(models.Post.repost_of_id).filter(
        models.Post.user_id == viewer_id,
        models.Post.repost_of_id.in_(ids),
        models.Post.is_deleted == False).all()
    return {r[0] for r in rows}


def _post_list(db, rows, viewer_id, counts=None):
    """post_dict for a page of rows: reposts resolve to their
    originals, and reposts whose original is gone are dropped."""
    liked = liked_ids(db, viewer_id, rows)
    saved = saved_ids(db, viewer_id, rows)
    reposted = reposted_ids(db, viewer_id, rows)
    out = []
    for p in rows:
        d = post_dict(db, p, liked=_eff_id(p) in liked,
                      saved=_eff_id(p) in saved,
                      views=(counts.get(_eff_id(p), 0)
                             if counts is not None else None),
                      reposted_by_me=_eff_id(p) in reposted,
                      viewer_id=viewer_id)
        if d is not None:
            out.append(d)
    return out


def _eff_id(p):
    """The post a card actually shows: a repost resolves to
    its original, so likes/saves/views/repost state all key
    off the original's id."""
    return getattr(p, "repost_of_id", None) or p.id


def reposted_ids(db, viewer_id, posts):
    """Which of these posts (by original id) the viewer
    reposted — the 🔁 button's active state."""
    ids = [_eff_id(p) for p in posts]
    if not ids:
        return set()
    rows = db.query(models.Post.repost_of_id).filter(
        models.Post.user_id == viewer_id,
        models.Post.repost_of_id.in_(ids),
        models.Post.is_deleted == False).all()
    return {r[0] for r in rows}


def _post_list(db, rows, viewer_id, counts=None):
    """post_dict for a page of rows: reposts resolve to their
    originals, and reposts whose original is gone are dropped."""
    liked = liked_ids(db, viewer_id, rows)
    saved = saved_ids(db, viewer_id, rows)
    reposted = reposted_ids(db, viewer_id, rows)
    out = []
    for p in rows:
        d = post_dict(db, p, liked=_eff_id(p) in liked,
                      saved=_eff_id(p) in saved,
                      views=(counts.get(_eff_id(p), 0)
                             if counts is not None else None),
                      reposted_by_me=_eff_id(p) in reposted,
                      viewer_id=viewer_id)
        if d is not None:
            out.append(d)
    return out


def _post_view_counts(db, posts):
    """Phase 38 (speed): ONE grouped query returns the unique-view
    counts for a whole page of posts, instead of one count query
    per post (the feed was making 20+ extra round trips)."""
    ids = [_eff_id(p) for p in posts]
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
    ids = [_eff_id(p) for p in posts]
    if not ids:
        return set()
    rows = db.query(models.Like.post_id).filter(
        models.Like.user_id == viewer_id,
        models.Like.post_id.in_(ids)).all()
    return {r[0] for r in rows}


def saved_ids(db, viewer_id, posts):
    """Which of these posts has the viewer bookmarked."""
    ids = [_eff_id(p) for p in posts]
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


def _muted_ids(db, user_id):
    """Phase 174: ids user_id has muted (one direction —
    unlike block, mute is not mutual)."""
    return {r[0] for r in db.query(models.Mute.muted_id).filter_by(
        muter_id=user_id).all()}


# ---------------------------------------------------------------------------
# Phase 136: private accounts — who may see whose posts.
# ---------------------------------------------------------------------------

def _private_author_ids(db):
    """Ids of members whose posts only followers may see."""
    return {r[0] for r in db.query(models.User.telegram_id).filter(
        models.User.is_private == True).all()}


def _can_see_posts(db, viewer_id, author_id):
    """A private account's posts are visible only to its
    followers and itself; everyone else's posts are public."""
    if viewer_id == author_id:
        return True
    author = db.get(models.User, author_id)
    if author is None or not getattr(author, "is_private", False):
        return True
    return db.query(models.Follow).filter_by(
        follower_id=viewer_id, following_id=author_id).first() is not None


def _blocked_by(db, blocker_id, user_id):
    """True when blocker_id has blocked user_id."""
    return db.query(models.UserBlock).filter_by(
        blocker_id=blocker_id, blocked_id=user_id).first() is not None


def _muted_by(db, muter_id, user_id):
    """Phase 174: True when muter_id has muted user_id."""
    return db.query(models.Mute).filter_by(
        muter_id=muter_id, muted_id=user_id).first() is not None


def _post_visible_to(db, viewer_id, p):
    """Phase 178: does viewer_id see this post card at all?
    The EFFECTIVE author (a repost resolves to its
    original) must not be block-related to the viewer in
    either direction, must not be muted by the viewer, and
    — for a private author — must be followed by the viewer.
    viewer_id None means no viewer context (bot/admin echo
    paths): visible. Own posts always pass: _can_see_posts
    is True for self, and nobody blocks or mutes themself."""
    if viewer_id is None:
        return True
    eff_id = getattr(p, "repost_of_id", None) or p.id
    eff = db.get(models.Post, eff_id) if eff_id != p.id else p
    if eff is None or eff.is_deleted:
        return False
    author_id = eff.user_id
    if author_id == viewer_id:
        return True
    if (_blocked_by(db, author_id, viewer_id)
            or _blocked_by(db, viewer_id, author_id)):
        return False
    if _muted_by(db, viewer_id, author_id):
        return False
    return _can_see_posts(db, viewer_id, author_id)


def _require_post_visible(db, viewer_id, p):
    """Phase 179 (audit H2): refuse an ACTION on a post the
    viewer may not see — the EFFECTIVE author (a repost resolves
    to its original) decides. Blocked either way -> 403 "This
    member is not available" (the write paths' existing
    convention); private-and-not-followed or muted -> 403 "This
    post is not available". Own posts always pass; a repost
    whose original is gone/deleted 404s, like the single-post
    view. The like/save/repost rows are never deleted, so
    unblocking / unmuting / following restores the toggle."""
    eff_id = getattr(p, "repost_of_id", None) or p.id
    eff = db.get(models.Post, eff_id) if eff_id != p.id else p
    if eff is None or eff.is_deleted:
        raise HTTPException(404, "Post not found")
    if eff.user_id != viewer_id and (
            _blocked_by(db, eff.user_id, viewer_id)
            or _blocked_by(db, viewer_id, eff.user_id)):
        raise HTTPException(403, "This member is not available")
    if not _post_visible_to(db, viewer_id, p):
        raise HTTPException(403, "This post is not available")


class PollIn(BaseModel):
    """Phase 123: an optional poll on a new post — a question
    plus 2 to 4 options."""
    question: str = Field(default="", max_length=200)
    options: list = Field(default_factory=list)


class PostIn(BaseModel):
    type: str = Field(default="text", max_length=16)
    media_file_id: Optional[str] = Field(default=None, max_length=256)
    # Phase 171: album — ordered staged photo file_ids, max 10.
    # Wins over media_file_id when both are given.
    media_file_ids: Optional[list] = None
    caption: str = Field(default="", max_length=2000)
    poll: Optional[PollIn] = None


def _validate_poll(poll):
    """Phase 123: a poll is a question + 2-4 non-empty options.
    Returns the cleaned (question, [options]) or None."""
    if poll is None:
        return None
    q = (poll.question or "").strip()
    opts = [str(o).strip() for o in (poll.options or []) if str(o).strip()]
    if not q:
        raise HTTPException(400, "Poll needs a question")
    if len(opts) < 2 or len(opts) > 4:
        raise HTTPException(400, "A poll needs 2 to 4 options")
    return q, opts


@app.post("/posts")
async def create_post(body: PostIn,
                      user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
    _enforce_rate("post", f"u{user.telegram_id}")
    poll = _validate_poll(body.poll)
    if body.type not in ("photo", "video", "text"):
        raise HTTPException(400, "type must be photo, video or text")
    # Phase 171: albums — media_file_ids is the ordered list of
    # staged photo file_ids (1..10). Each one is screened, exactly
    # like a single photo post (a client-invented file_id must not
    # slip through unscreened).
    album_ids = None
    if body.media_file_ids is not None:
        if not isinstance(body.media_file_ids, list) \
                or not 1 <= len(body.media_file_ids) <= 10:
            raise HTTPException(
                400, "An album holds 1 to 10 photos")
        if body.type != "photo":
            raise HTTPException(400, "Albums hold photos only")
        for fid in body.media_file_ids:
            if not isinstance(fid, str) or not fid or len(fid) > 256:
                raise HTTPException(400, "Bad photo in album")
        album_ids = body.media_file_ids
        if moderation.active():
            for fid in album_ids:
                verdict = _screen_file_id("photo", fid)
                if verdict != "clean":
                    log_security_event(
                        db, "screen_reject",
                        actor_id=user.telegram_id, detail=
                        f"album photo screened out ({verdict})")
                    raise HTTPException(
                        400, moderation.block_message("photo", verdict))
    # Phase 142: banned-word list — a post carrying a banned word
    # is refused before it exists (never echo the word itself).
    if banned_word_in(db, body.caption):
        raise HTTPException(400, BANNED_WORD_MESSAGE)
    # Phase 81: a media post carries a Telegram file_id the server
    # never saw uploaded — fetch and screen it, so this endpoint
    # cannot bypass the screening every upload goes through.
    if album_ids is None and moderation.active() \
            and body.type in ("photo", "video") \
            and body.media_file_id:
        verdict = _screen_file_id(body.type, body.media_file_id)
        if verdict != "clean":
            log_security_event(db, "screen_reject",
                               actor_id=user.telegram_id, detail=
                               f"{body.type} screened out ({verdict})")
            raise HTTPException(
                400, moderation.block_message(body.type, verdict))
    if album_ids:
        post, _, _ = register_post(
            db, user, "photo", album_ids[0], body.caption,
            extra_media=[(fid, "photo") for fid in album_ids])
    else:
        post, _, _ = register_post(db, user, body.type, body.media_file_id,
                                   body.caption)
    if poll:
        q, opts = poll
        db.add(models.Poll(post_id=post.id, question=q))
        db.commit()
        prow = db.query(models.Poll).filter_by(
            post_id=post.id).first()
        for i, t in enumerate(opts):
            db.add(models.PollOption(poll_id=prow.id, text=t,
                                   position=i))
        db.commit()
        db.refresh(post)
    # Phase 170: @mentions in the caption — rows + in-app record
    # (sync_mentions) plus the bot push for each new mention.
    for uid in sync_mentions(db, user.telegram_id, post.id, None,
                             body.caption, post.user_id):
        await notify.notify_user(
            db, uid, "mention",
            f"📣 @{user.username or user.first_name} mentioned you "
            f"in a post: {(body.caption or '')[:80]}")
    return post_dict(db, post, viewer_id=user.telegram_id)


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


async def _send_voice_to_telegram(user, data, content_type, filename):
    """Phase 173: transcode a recorded voice note to OGG Opus and
    send it with Telegram sendVoice; returns the file_id. An OGG
    upload goes straight through; anything else needs ffmpeg
    (bundled via imageio-ffmpeg on Render — the same source as
    video transcoding). Audio is NOT Gemini-screened."""
    ogg = data
    is_ogg = (content_type or "").lower() == "audio/ogg" or \
        (filename or "").lower().endswith(".ogg")
    if is_ogg:
        if not data.startswith(b"OggS"):
            raise HTTPException(
                400, "That recording is not a valid OGG file")
    else:
        ffmpeg = videoutil.find_ffmpeg()
        if not ffmpeg:
            raise HTTPException(
                502, "Voice upload is unavailable right now")

        def _transcode():
            with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".src") as f:
                f.write(data)
                src = f.name
            dst = src + ".ogg"
            try:
                r = subprocess.run(
                    [ffmpeg, "-y", "-i", src, "-vn", "-c:a", "libopus",
                     "-b:a", "32k", dst],
                    capture_output=True, timeout=60)
                if r.returncode != 0 or not os.path.exists(dst):
                    raise RuntimeError("transcode failed")
                with open(dst, "rb") as fh:
                    return fh.read()
            finally:
                for p in (src, dst):
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

        try:
            ogg = await asyncio.to_thread(_transcode)
        except Exception:
            raise HTTPException(
                502, "That recording could not be processed")
    try:
        kind, file_id, _thumb = await tgupload.upload_voice(
            _send_chat_id(user), "voice.ogg", ogg)
        return file_id
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
# from the bot. The post, with its +10 points, appears when it is ready.
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
                log_security_event(None, "screen_reject",
                                   actor_id=author_id, detail=
                                   f"video screened out ({verdict})")
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
                log_security_event(None, "screen_reject",
                                   actor_id=user.telegram_id, detail=
                                   f"photo screened out ({verdict})")
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


@app.post("/posts/upload-media")
async def upload_media_staged(file: UploadFile = File(...),
                              user: models.User = Depends(current_user),
                              db: Session = Depends(get_db)):
    """Phase 171: stage ONE photo for an album — upload it to
    Telegram (screened, exactly like a post) and hand back its
    file_id WITHOUT creating a post. The composer stages up to 10
    photos this way, then creates the album with POST /posts
    {media_file_ids}. Videos are refused here BEFORE any upload
    (albums hold photos only — a video still goes through
    /posts/upload on its own), so no stray video job is scheduled."""
    kind = tgupload.classify(file.content_type or "",
                             file.filename or "")
    if kind != "photo":
        raise HTTPException(
            400, "Albums hold photos — post a video on its own")
    _enforce_rate("upload", f"u{user.telegram_id}")
    kind, file_id = await _telegram_upload_or_400(user, file)
    return {"file_id": file_id, "kind": kind}


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


def _delete_post_cascade(db, p):
    """Phase 118: deleting a repost takes one off the
    original's count; deleting an original takes its live
    reposts with it, so no orphan card can surface."""
    if getattr(p, "repost_of_id", None):
        orig = db.get(models.Post, p.repost_of_id)
        if orig is not None:
            orig.repost_count = max(0, (orig.repost_count or 0) - 1)
    else:
        for rp in db.query(models.Post).filter_by(
                repost_of_id=p.id, is_deleted=False).all():
            rp.is_deleted = True


def _delete_post_cascade(db, p):
    """Phase 118: deleting a repost takes one off the
    original's count; deleting an original takes its live
    reposts with it, so no orphan card can surface."""
    if getattr(p, "repost_of_id", None):
        orig = db.get(models.Post, p.repost_of_id)
        if orig is not None:
            orig.repost_count = max(0, (orig.repost_count or 0) - 1)
    else:
        for rp in db.query(models.Post).filter_by(
                repost_of_id=p.id, is_deleted=False).all():
            rp.is_deleted = True
    # Phase 170: a deleted post takes its mention rows with it.
    db.query(models.Mention).filter_by(post_id=p.id).delete()
    # Phase 171: ... and its album rows.
    db.query(models.PostMedia).filter_by(post_id=p.id).delete()


@app.delete("/posts/{post_id}")
def delete_post(post_id: int, user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
    p = db.get(models.Post, post_id)
    if p is None or p.is_deleted or p.user_id != user.telegram_id:
        raise HTTPException(404, "Post not found")
    p.is_deleted = True
    _delete_post_cascade(db, p)
    db.commit()
    return {"ok": True, "id": p.id}


class PostEditIn(BaseModel):
    caption: str = Field(default="", max_length=2000)


@app.post("/posts/{post_id}/edit")
async def edit_post(post_id: int, body: PostEditIn,
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
    # Phase 170: re-editing re-syncs mentions — only NEW names
    # notify (dedupe), removed names lose their row.
    for uid in sync_mentions(db, user.telegram_id, p.id, None,
                             p.caption, p.user_id):
        await notify.notify_user(
            db, uid, "mention",
            f"📣 @{user.username or user.first_name} mentioned you "
            f"in a post: {(p.caption or '')[:80]}")
    return post_dict(db, p)


@app.post("/posts/{post_id}/like")
async def toggle_like(post_id: int, user: models.User = Depends(current_user),
                      db: Session = Depends(get_db)):
    _enforce_rate("like", f"u{user.telegram_id}")
    p = get_live_post(db, post_id)
    # Phase 179 (audit H2): liking needs the same visibility as
    # reading — blocked either way, muted, or private-and-not-
    # followed (effective author: a repost resolves to its
    # original). Self-likes still pass: own posts are visible.
    _require_post_visible(db, user.telegram_id, p)
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


@app.post("/posts/{post_id}/repost")
async def toggle_repost(post_id: int, user: models.User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """Phase 118: repost a post to your own feed (toggle).
    Reposting a repost resolves to the original; your own post
    cannot be reposted; reposts earn no points and never count
    toward the post totals."""
    _enforce_rate("repost", f"u{user.telegram_id}")
    p = get_live_post(db, post_id)
    if getattr(p, "repost_of_id", None):
        p = get_live_post(db, p.repost_of_id)
    if p.user_id == user.telegram_id:
        raise HTTPException(400, "You cannot repost your own post")
    # Phase 179 (audit H2): reposting needs the same visibility
    # as reading — a private post cannot be reposted by a
    # non-follower, nor a muted author's post (p is already
    # resolved to the original above).
    _require_post_visible(db, user.telegram_id, p)
    existing = db.query(models.Post).filter_by(
        user_id=user.telegram_id, repost_of_id=p.id,
        is_deleted=False).first()
    if existing:
        existing.is_deleted = True
        p.repost_count = max(0, (p.repost_count or 0) - 1)
        reposted = False
    else:
        db.add(models.Post(user_id=user.telegram_id, type="repost",
                           repost_of_id=p.id, caption="", hashtags=""))
        p.repost_count = (p.repost_count or 0) + 1
        reposted = True
    db.commit()
    if reposted:
        await notify.notify_user(
            db, p.user_id, "repost",
            f"\U0001F501 {user.first_name} reposted your post.")
        notify.record(db, p.user_id, "repost",
                      actor_id=user.telegram_id, post_id=p.id)
    return {"reposted": reposted, "repost_count": p.repost_count}


# ---------------------------------------------------------------------------
# Phase 123 — Creator tools: pinned posts, drafts, polls.
# ---------------------------------------------------------------------------


@app.post("/posts/{post_id}/pin")
def toggle_pin(post_id: int, user: models.User = Depends(current_user),
               db: Session = Depends(get_db)):
    """Pin ONE of your own posts — it shows first on your profile
    (📌 badge). Pinning a second post unpins the first; a repost
    cannot be pinned (only your own originals)."""
    _enforce_rate("pin", f"u{user.telegram_id}")
    p = db.get(models.Post, post_id)
    if p is None or p.is_deleted:
        raise HTTPException(404, "Post not found")
    if p.user_id != user.telegram_id:
        raise HTTPException(403, "Only the author can pin this post")
    if getattr(p, "repost_of_id", None):
        raise HTTPException(400, "A repost cannot be pinned")
    if getattr(p, "is_pinned", False):
        p.is_pinned = False
        pinned = False
    else:
        for other in db.query(models.Post).filter_by(
                user_id=user.telegram_id, is_pinned=True,
                is_deleted=False).all():
            other.is_pinned = False
        p.is_pinned = True
        pinned = True
    db.commit()
    return {"pinned": pinned, "post_id": p.id}


class DraftIn(BaseModel):
    text: str = Field(default="", max_length=2000)
    media_file_id: Optional[str] = Field(default=None, max_length=256)
    media_type: Optional[str] = Field(default=None, max_length=16)


def draft_dict(d):
    return {"id": d.id, "text": d.text,
            "media_file_id": d.media_file_id,
            "media_type": d.media_type,
            "created_at": d.created_at.isoformat()
            if d.created_at else None,
            "updated_at": d.updated_at.isoformat()
            if d.updated_at else None}


@app.post("/drafts")
def save_draft(body: DraftIn, user: models.User = Depends(current_user),
               db: Session = Depends(get_db)):
    """Save an unfinished post as a draft — text plus an optional
    already-uploaded media reference — and finish it later from
    the drafts list."""
    _enforce_rate("draft", f"u{user.telegram_id}")
    if body.media_type is not None \
            and body.media_type not in ("photo", "video"):
        raise HTTPException(400, "media_type must be photo or video")
    if not (body.text or "").strip() and not body.media_file_id:
        raise HTTPException(400, "A draft needs text or media")
    d = models.Draft(user_id=user.telegram_id,
                     text=(body.text or "").strip(),
                     media_file_id=body.media_file_id,
                     media_type=body.media_type)
    db.add(d)
    db.commit()
    db.refresh(d)
    return draft_dict(d)


@app.get("/drafts")
def list_drafts(user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
    rows = db.query(models.Draft).filter_by(
        user_id=user.telegram_id).order_by(
        models.Draft.updated_at.desc()).limit(50).all()
    return {"drafts": [draft_dict(d) for d in rows]}


@app.delete("/drafts/{draft_id}")
def delete_draft(draft_id: int, user: models.User = Depends(current_user),
                 db: Session = Depends(get_db)):
    d = db.get(models.Draft, draft_id)
    if d is None or d.user_id != user.telegram_id:
        raise HTTPException(404, "Draft not found")
    db.delete(d)
    db.commit()
    return {"ok": True, "id": draft_id}


@app.post("/drafts/{draft_id}/publish")
def publish_draft(draft_id: int, user: models.User = Depends(current_user),
                  db: Session = Depends(get_db)):
    """Publish a draft through the normal post path — it earns its
    10 points like any post — then the draft is gone."""
    _enforce_rate("draft", f"u{user.telegram_id}")
    d = db.get(models.Draft, draft_id)
    if d is None or d.user_id != user.telegram_id:
        raise HTTPException(404, "Draft not found")
    ptype = d.media_type or "text"
    if ptype not in ("photo", "video", "text"):
        ptype = "text"
    if moderation.active() and ptype in ("photo", "video") \
            and d.media_file_id:
        verdict = _screen_file_id(ptype, d.media_file_id)
        if verdict != "clean":
            log_security_event(db, "screen_reject",
                               actor_id=user.telegram_id, detail=
                               f"{ptype} screened out ({verdict})")
            raise HTTPException(
                400, moderation.block_message(ptype, verdict))
    post, _, _ = register_post(db, user, ptype, d.media_file_id,
                               d.text or "")
    db.delete(d)
    db.commit()
    return post_dict(db, post, viewer_id=user.telegram_id)


# Phase 135 — Scheduled posts: a member picks a date + time and
# the post goes out then, through the normal post path (points,
# hashtags, screening — exactly like posting now). The sweeper
# below wakes every 60 seconds; on the free Render plan the
# service sleeps when idle, so a scheduled post can land up to
# ~10 minutes late (the keepalive ping keeps it warm) — the PRD
# says so plainly, and the client never promises exact timing.
# Polls are NOT scheduled (they live on a live post); text +
# media only.
_SCHEDULER_INTERVAL_S = 60
_sweeper_task = None
_auto_backup_task = None


class ScheduledPostIn(BaseModel):
    text: str = Field(default="", max_length=2000)
    media_file_id: Optional[str] = Field(default=None, max_length=256)
    media_type: Optional[str] = Field(default=None, max_length=16)
    scheduled_at: str = Field(max_length=64)


def _parse_scheduled_at(value):
    """Parse an ISO date-time (with or without a zone) into a
    naive UTC datetime, or 400."""
    v = (value or "").strip()
    if not v:
        raise HTTPException(400, "scheduled_at is required")
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "scheduled_at must be an ISO date-time")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def scheduled_dict(r):
    return {"id": r.id, "text": r.text,
            "media_file_id": r.media_file_id,
            "media_type": r.media_type,
            "scheduled_at": r.scheduled_at.isoformat()
            if r.scheduled_at else None,
            "status": r.status,
            "created_at": r.created_at.isoformat()
            if r.created_at else None,
            "posted_post_id": r.posted_post_id,
            "error": r.error}


@app.post("/scheduled-posts")
def create_scheduled_post(body: ScheduledPostIn,
                          user: models.User = Depends(current_user),
                          db: Session = Depends(get_db)):
    """Queue a post for a future time — at least 5 minutes from
    now, at most 90 days out. No poll: polls belong to a live post."""
    _enforce_rate("scheduled", f"u{user.telegram_id}")
    if body.media_type is not None \
            and body.media_type not in ("photo", "video"):
        raise HTTPException(400, "media_type must be photo or video")
    if not (body.text or "").strip() and not body.media_file_id:
        raise HTTPException(400, "A scheduled post needs text or media")
    at = _parse_scheduled_at(body.scheduled_at)
    now = datetime.utcnow()
    if at < now + timedelta(minutes=5):
        raise HTTPException(400,
                            "Pick a time at least 5 minutes from now")
    if at > now + timedelta(days=90):
        raise HTTPException(400,
                            "You can schedule up to 90 days ahead")
    row = models.ScheduledPost(
        user_id=user.telegram_id,
        text=(body.text or "").strip(),
        media_file_id=body.media_file_id,
        media_type=body.media_type, scheduled_at=at)
    db.add(row)
    db.commit()
    db.refresh(row)
    return scheduled_dict(row)


@app.get("/scheduled-posts")
def list_scheduled_posts(user: models.User = Depends(current_user),
                         db: Session = Depends(get_db)):
    rows = db.query(models.ScheduledPost).filter_by(
        user_id=user.telegram_id).order_by(
        models.ScheduledPost.created_at.desc()).limit(50).all()
    return {"scheduled_posts": [scheduled_dict(r) for r in rows]}


@app.delete("/scheduled-posts/{row_id}")
def cancel_scheduled_post(row_id: int,
                          user: models.User = Depends(current_user),
                          db: Session = Depends(get_db)):
    """Cancel a pending scheduled post. Posted, failed and already
    cancelled rows cannot be cancelled."""
    row = db.get(models.ScheduledPost, row_id)
    if row is None or row.user_id != user.telegram_id:
        raise HTTPException(404, "Scheduled post not found")
    if row.status != "pending":
        raise HTTPException(400,
                            "Only a pending post can be cancelled")
    row.status = "cancelled"
    db.commit()
    return {"ok": True, "id": row_id, "status": "cancelled"}


def _find_adoptable_post(db, row):
    """Phase 180 (audit H9): the post a crashed sweep already
    created for this row — same author, same text and media,
    created at/after the scheduled time, and not already claimed
    by another scheduled row. None when no such post exists."""
    claimed = {r[0] for r in db.query(
        models.ScheduledPost.posted_post_id).filter(
        models.ScheduledPost.posted_post_id.isnot(None)).all()}
    q = db.query(models.Post).filter(
        models.Post.user_id == row.user_id,
        models.Post.caption == (row.text or ""),
        models.Post.is_deleted == False,
        models.Post.created_at >= row.scheduled_at)
    if row.media_file_id:
        q = q.filter(models.Post.media_file_id == row.media_file_id)
    else:
        q = q.filter(models.Post.media_file_id.is_(None))
    for post in q.order_by(models.Post.created_at.desc(),
                           models.Post.id.desc()).all():
        if post.id not in claimed:
            return post
    return None


def _publish_scheduled_row(db, row):
    """Publish one due row through the normal post path. On
    success the row is posted with its post id; on a screening
    rejection or any other failure it is failed with a short
    human message — and never retried automatically.

    Phase 180 (audit H9): crash-safe. The row is CLAIMED first
    (status -> "publishing", committed BEFORE register_post()),
    so a crash between the post commit and the row commit leaves
    a "publishing" row the next sweep ADOPTS (its post already
    exists — no second post, no second +10) instead of
    publishing again. A row whose post was never created is
    published for real. sync_mentions() is best-effort: the post
    is live by then, so a mention failure logs and the row still
    posts instead of failing a live post."""
    if row.status == "posted":
        return
    if row.status not in ("pending", "publishing"):
        return
    if row.status == "publishing":
        # A previous sweep crashed after the post was created:
        # adopt it (no additional points — register_post already
        # paid them) instead of publishing again.
        adopted = _find_adoptable_post(db, row)
        if adopted is not None:
            row.status = "posted"
            row.posted_post_id = adopted.id
            row.error = None
            db.commit()
            return
        # No post exists: the crash happened before
        # register_post() committed — publish for real below.
    else:
        row.status = "publishing"
        db.commit()
    user = db.get(models.User, row.user_id)
    if user is None:
        row.status = "failed"
        row.error = "Account no longer exists."
        db.commit()
        return
    ptype = row.media_type or "text"
    if ptype not in ("photo", "video", "text"):
        ptype = "text"
    # Phase 142: banned-word list — a scheduled post carrying
    # one fails with the same plain message (never auto-retried).
    if banned_word_in(db, row.text or ""):
        row.status = "failed"
        row.error = BANNED_WORD_MESSAGE
        db.commit()
        return
    try:
        if moderation.active() and ptype in ("photo", "video") \
                and row.media_file_id:
            verdict = _screen_file_id(ptype, row.media_file_id)
            if verdict != "clean":
                log_security_event(db, "screen_reject",
                                   actor_id=row.user_id, detail=
                                   f"{ptype} screened out ({verdict})")
                row.status = "failed"
                row.error = moderation.block_message(ptype, verdict)[:256]
                db.commit()
                return
        post, _, _ = register_post(db, user, ptype,
                                   row.media_file_id, row.text or "")
    except Exception:
        # register_post() threw — but it commits the post row
        # first, so the post may already be live. Adopt it when
        # it is; only fail the row when no post was created.
        # A failed row is never retried: the member sees the
        # reason and can delete or re-schedule it.
        db.rollback()
        adopted = _find_adoptable_post(db, row)
        if adopted is not None:
            row.status = "posted"
            row.posted_post_id = adopted.id
            row.error = None
            db.commit()
            return
        row.status = "failed"
        row.error = "Could not publish this post."
        db.commit()
        return
    # Phase 170: @mentions in a scheduled post — rows +
    # in-app record only; the bot push needs an async caller,
    # so a scheduled post's mention lands in the 🔔 list,
    # not as a bot message. (See PRD Phase 170.)
    # Phase 180: best-effort — the post is live, so a mention
    # failure must not fail the row (the old code did, leaving
    # a live post + a failed row).
    try:
        sync_mentions(db, row.user_id, post.id, None,
                      row.text or "", row.user_id)
    except Exception:
        logging.exception("scheduled post mentions failed for row %s",
                          row.id)
    row.status = "posted"
    row.posted_post_id = post.id
    row.error = None
    db.commit()


def _run_scheduled_sweep():
    """One sweep: publish every pending row whose time has come.
    Sync — the loop runs it in a thread so screening network
    calls never block the event loop. Phase 180 (audit H9):
    "publishing" rows are swept too — a crashed sweep's claimed
    row is adopted (its post exists) or published (it does not)
    on the next sweep, never duplicated."""
    now = datetime.utcnow()
    with SessionLocal() as db:
        rows = db.query(models.ScheduledPost).filter(
            models.ScheduledPost.status.in_(["pending", "publishing"]),
            models.ScheduledPost.scheduled_at <= now).order_by(
            models.ScheduledPost.scheduled_at.asc()).all()
        for row in rows:
            _publish_scheduled_row(db, row)


async def _scheduled_posts_loop():
    """Wake every 60 seconds and sweep due scheduled posts."""
    while True:
        try:
            await asyncio.sleep(_SCHEDULER_INTERVAL_S)
            await asyncio.to_thread(_run_scheduled_sweep)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.exception("scheduled-posts sweep failed")
            # Phase 180 (audit M13): a sweep that dies before any
            # row is processed left no trace the admin could see —
            # only the server log. Persist it in the security log
            # so the Admin Panel shows it (one line, no traceback).
            await asyncio.to_thread(
                log_security_event, None, "server_error", None, None,
                f"scheduled-posts sweep failed: {exc}"[:512])


# ---------------------------------------------------------------------------
# Phase 141: weekly auto-backup — the full-site backup (Phase 107)
# sends itself to the owner's Telegram chat once a week, so the
# site is never more than 7 days from a restorable copy even if
# nobody remembers to take one by hand. An asyncio task wakes
# every hour and sends only when >= 7 days passed since the last
# successful auto send. The toggle + last-run timestamp live in
# app_settings (keys auto_backup_enabled / auto_backup_last_run),
# so they ride the normal backup and survive restarts — no new
# table, backup stays at 41 tables. The auto send never touches
# the manual backup rate limit ("backup" 10/h): it is a separate
# path. A failed send is logged (server_error + audit
# auto_backup_failed) and retried on the next hourly check —
# never a tight loop, never a crash. On the free Render plan the
# service sleeps when idle, so a due backup can land up to
# ~10 minutes late (the keepalive ping keeps it warm).
# ---------------------------------------------------------------------------
_AUTO_BACKUP_INTERVAL_S = 3600
_AUTO_BACKUP_PERIOD = timedelta(days=7)


def _set_app_setting(db, key, value):
    row = db.get(models.AppSetting, key)
    if row is None:
        row = models.AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value


def _auto_backup_enabled(db):
    """Default ON — the owner ordered the feature; the backup
    goes only to his own Telegram chat."""
    row = db.get(models.AppSetting, "auto_backup_enabled")
    return row is None or row.value != "0"


def _auto_backup_last_run(db):
    """Datetime of the last successful auto send, or None."""
    row = db.get(models.AppSetting, "auto_backup_last_run")
    if row is None or not row.value:
        return None
    try:
        return datetime.fromisoformat(row.value)
    except ValueError:
        return None


def _last_manual_backup_at(db):
    """Newest manual backup (download or Telegram send) from
    the audit log, or None. Phase 180 (audit M12): a manual
    backup taken minutes before a deploy must not trigger an
    auto-backup ~1 h later — the manual copy already covers
    the week."""
    row = db.query(models.AdminAuditLog).filter(
        models.AdminAuditLog.action.in_(
            ("backup_download", "backup_send"))).order_by(
        models.AdminAuditLog.id.desc()).first()
    return row.created_at if row is not None else None


def _auto_backup_due(db):
    if not _auto_backup_enabled(db):
        return False
    now = datetime.utcnow()
    last = _auto_backup_last_run(db)
    if last is not None and now - last < _AUTO_BACKUP_PERIOD:
        return False
    manual = _last_manual_backup_at(db)
    if manual is not None and now - manual < _AUTO_BACKUP_PERIOD:
        return False
    return True


def _auto_backup_next_due(db):
    cands = [d for d in (_auto_backup_last_run(db),
                         _last_manual_backup_at(db)) if d is not None]
    if not cands:
        return datetime.utcnow()
    return max(cands) + _AUTO_BACKUP_PERIOD


def _build_auto_backup():
    """Sync (runs in a thread): build the full backup bytes.
    Phase 164: encrypted when BACKUP_ENCRYPTION_KEY is set."""
    with SessionLocal() as db:
        payload = _backup_payload(db)
    data, fname, encrypted = _backup_pack(payload, prefix="nexora-auto-backup")
    if not encrypted:
        sec_log.warning("auto-backup built UNENCRYPTED — set "
                        "BACKUP_ENCRYPTION_KEY")
    total = sum(len(v) for v in payload["tables"].values())
    return fname, data, total


def _record_auto_backup(sent, size, total, detail=None):
    """Sync (runs in a thread): record an auto-backup attempt."""
    owner_tid = settings.ADMIN_IDS[0] if settings.ADMIN_IDS else None
    with SessionLocal() as db:
        if sent:
            _set_app_setting(db, "auto_backup_last_run",
                             datetime.utcnow().isoformat())
            owner = db.get(models.User, owner_tid) if owner_tid else None
            if owner is not None:
                _audit(db, owner, "auto_backup_send",
                       detail=f"{size} bytes, {total} rows")
            else:
                db.add(models.AdminAuditLog(
                    admin_id=owner_tid or 0, action="auto_backup_send",
                    detail=f"{size} bytes, {total} rows"))
        else:
            log_security_event(db, "server_error",
                               detail=detail or "Auto-backup send failed")
            db.add(models.AdminAuditLog(
                admin_id=owner_tid or 0, action="auto_backup_failed",
                detail=detail or "Telegram send failed"))
        db.commit()


def _stamp_auto_backup_attempt():
    """Sync (runs in a thread): stamp the auto-backup run BEFORE
    building/sending and return the PREVIOUS stamp (or None).
    Phase 180 (audit M12): a crash between the send and the
    success record then cannot re-send the same backup on the
    next hourly check — the stamp already says it ran."""
    with SessionLocal() as db:
        prev = _auto_backup_last_run(db)
        _set_app_setting(db, "auto_backup_last_run",
                         datetime.utcnow().isoformat())
        db.commit()
        return prev


def _restore_auto_backup_stamp(prev):
    """Sync (runs in a thread): put auto_backup_last_run back to
    its previous value (or delete the key when there was none)
    after a failed build or send, so the next hourly check
    retries instead of waiting 7 days."""
    with SessionLocal() as db:
        row = db.get(models.AppSetting, "auto_backup_last_run")
        if prev is None:
            if row is not None:
                db.delete(row)
        elif row is None:
            db.add(models.AppSetting(
                key="auto_backup_last_run", value=prev.isoformat()))
        else:
            row.value = prev.isoformat()
        db.commit()


async def _maybe_auto_backup(send_fn=None):
    """One auto-backup check: if due, build the full backup and
    send it to the owner's Telegram chat. True only when a backup
    was actually sent. Never raises.

    Phase 180 (audit M12): the run is stamped BEFORE building /
    sending, so a crash between the send and the success record
    cannot re-send the same backup; a failed build or send
    restores the previous stamp, so the next hourly check
    retries. A build crash is admin-visible (M13): it records
    auto_backup_failed + a server_error security-log row."""
    with SessionLocal() as db:
        due = _auto_backup_due(db)
    if not due:
        return False
    owner_tid = settings.ADMIN_IDS[0] if settings.ADMIN_IDS else None
    if owner_tid is None:
        return False
    prev = await asyncio.to_thread(_stamp_auto_backup_attempt)
    try:
        fname, data, total = await asyncio.to_thread(_build_auto_backup)
    except Exception:
        await asyncio.to_thread(_restore_auto_backup_stamp, prev)
        await asyncio.to_thread(_record_auto_backup, False, 0, 0,
                                "Auto-backup build failed")
        return False
    send = send_fn or notify.send_document
    try:
        sent = await send(
            owner_tid, fname, data,
            caption="\U0001f4be Nexora weekly auto-backup — every user, "
                    "post, comment, like, follow, design and message. "
                    "Keep this file safe: anyone holding it holds the "
                    "whole database.")
    except Exception:
        sent = False
    if not sent:
        await asyncio.to_thread(_restore_auto_backup_stamp, prev)
    await asyncio.to_thread(_record_auto_backup, sent, len(data), total)
    return bool(sent)


async def _auto_backup_loop():
    """Wake every hour and send the weekly backup when due."""
    while True:
        try:
            await asyncio.sleep(_AUTO_BACKUP_INTERVAL_S)
            await _maybe_auto_backup()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.exception("auto-backup sweep failed")
            # Phase 180 (audit M13): same rule as the scheduled
            # sweep — a loop-level failure belongs in the security
            # log the Admin Panel shows, not just the server log.
            await asyncio.to_thread(
                log_security_event, None, "server_error", None, None,
                f"auto-backup loop failed: {exc}"[:512])


class PollVoteIn(BaseModel):
    option_id: int


@app.post("/posts/{post_id}/poll/vote")
def vote_poll(post_id: int, body: PollVoteIn,
              user: models.User = Depends(current_user),
              db: Session = Depends(get_db)):
    """Vote once in a post's poll. A vote is final — members
    cannot change it once cast (documented in the PRD)."""
    _enforce_rate("poll_vote", f"u{user.telegram_id}")
    p = get_live_post(db, post_id)
    # Phase 179 (audit H2): voting needs the same visibility as
    # reading — blocked, muted, or private-and-not-followed.
    _require_post_visible(db, user.telegram_id, p)
    poll = db.query(models.Poll).filter_by(post_id=p.id).first()
    if poll is None:
        raise HTTPException(404, "This post has no poll")
    opt = db.get(models.PollOption, body.option_id)
    if opt is None or opt.poll_id != poll.id:
        raise HTTPException(400, "That poll option does not exist")
    existing = db.query(models.PollVote).filter_by(
        poll_id=poll.id, user_id=user.telegram_id).first()
    if existing is not None:
        raise HTTPException(400, "You have already voted in this poll")
    db.add(models.PollVote(poll_id=poll.id, option_id=opt.id,
                           user_id=user.telegram_id))
    db.commit()
    return _poll_dict(db, p, viewer_id=user.telegram_id)


@app.post("/posts/{post_id}/view")
def view_post(post_id: int, user: models.User = Depends(current_user),
              db: Session = Depends(get_db)):
    """Phase 31 (owner request): record a UNIQUE view of a post —
    the client fires this when a video actually starts playing.
    One row per (post, viewer): rewatches never inflate the count."""
    _enforce_rate("view", f"u{user.telegram_id}")
    p = get_live_post(db, post_id)
    # Phase 179 (audit H2): a view is only recorded when the
    # viewer may see the post — otherwise Trending velocity
    # could be inflated by viewers who cannot see it. Checked
    # before recording, so a refused view leaves no PostView row.
    _require_post_visible(db, user.telegram_id, p)
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
    # Phase 179 (audit H2): saving needs the same visibility as
    # reading — blocked, muted, or private-and-not-followed
    # (effective author: a repost resolves to its original).
    _require_post_visible(db, user.telegram_id, p)
    existing = db.query(models.SavedPost).filter_by(
        post_id=p.id, user_id=user.telegram_id).first()
    if existing:
        db.delete(existing)
        # Phase 175: unsaving also drops the post from every
        # collection of the saver — it is no longer saved.
        my_colls = [r[0] for r in db.query(
            models.SavedCollection.id).filter_by(
            user_id=user.telegram_id).all()]
        if my_colls:
            db.query(models.SavedCollectionPost).filter(
                models.SavedCollectionPost.post_id == p.id,
                models.SavedCollectionPost.collection_id.in_(
                    my_colls)).delete(synchronize_session=False)
        saved = False
    else:
        db.add(models.SavedPost(post_id=p.id, user_id=user.telegram_id))
        saved = True
    db.commit()
    return {"saved": saved, "post_id": p.id}


@app.get("/me/saved")
def my_saved(user: models.User = Depends(current_user),
             db: Session = Depends(get_db)):
    # Phase 179 (audit M4): 240/h per member — the Saved view
    # loads once per visit, far below this.
    _enforce_rate("saved", f"u{user.telegram_id}")
    rows = db.query(models.Post).join(
        models.SavedPost, models.SavedPost.post_id == models.Post.id) \
        .filter(models.SavedPost.user_id == user.telegram_id,
                models.Post.is_deleted == False) \
        .order_by(models.SavedPost.id.desc()).limit(50).all()
    # Phase 178 (audit H5): saved ORIGINAL posts get the
    # same visibility rules as the feed — blocked (either
    # way), muted, or private-and-not-followed authors stay
    # hidden. (Repost rows are covered by post_dict's own
    # check; _media_visible alone is not relied on — it
    # gates media, not text.)
    rows = [p for p in rows
            if _post_visible_to(db, user.telegram_id, p)]
    return {"posts": _post_list(db, rows, user.telegram_id)}


class CollectionIn(BaseModel):
    name: str = Field(default="", max_length=50)


class CollectionPostIn(BaseModel):
    post_id: int = 0


def _get_my_collection(db, user_id, cid):
    """Phase 175: the caller's own collection, or 404 — a missing
    id and someone else's id look the same."""
    coll = db.get(models.SavedCollection, cid)
    if coll is None or coll.user_id != user_id:
        raise HTTPException(404, "Collection not found")
    return coll


def _clean_collection_name(db, user_id, name, exclude_id=None):
    """Phase 175: a trimmed 1-50 char name, unique per member
    (case-insensitive)."""
    name = (name or "").strip()
    if not name or len(name) > 50:
        raise HTTPException(
            400, "Collection name must be 1–50 characters")
    q = db.query(models.SavedCollection).filter_by(user_id=user_id)
    if exclude_id is not None:
        q = q.filter(models.SavedCollection.id != exclude_id)
    for c in q.all():
        if c.name.lower() == name.lower():
            raise HTTPException(
                400, "You already have a collection with that name")
    return name


def _collection_dict(db, coll, has_post=None):
    n = db.query(models.SavedCollectionPost).filter_by(
        collection_id=coll.id).count()
    d = {"id": coll.id, "name": coll.name, "post_count": n,
         "created_at": coll.created_at.isoformat()
         if coll.created_at else None}
    if has_post is not None:
        d["has_post"] = coll.id in has_post
    return d


@app.post("/saved/collections")
def create_collection(body: CollectionIn,
                      user: models.User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """Phase 175: create a collection (max 20 per member)."""
    me = user.telegram_id
    if db.query(models.SavedCollection).filter_by(
            user_id=me).count() >= 20:
        raise HTTPException(
            400, "You can have up to 20 collections")
    name = _clean_collection_name(db, me, body.name)
    coll = models.SavedCollection(user_id=me, name=name)
    db.add(coll)
    db.commit()
    db.refresh(coll)
    return _collection_dict(db, coll)


@app.get("/saved/collections")
def list_collections(post_id: int = 0,
                     user: models.User = Depends(current_user),
                     db: Session = Depends(get_db)):
    """Phase 175: my collections, newest first. With ?post_id=N
    each entry also says whether that post is in it (the
    save-to-collection picker)."""
    # Phase 179 (audit M4): "saved" budget, shared with /me/saved
    # and /me/shared — the picker loads it per post open.
    _enforce_rate("saved", f"u{user.telegram_id}")
    rows = db.query(models.SavedCollection).filter_by(
        user_id=user.telegram_id) \
        .order_by(models.SavedCollection.id.desc()).all()
    has_post = None
    if post_id:
        has_post = {r[0] for r in db.query(
            models.SavedCollectionPost.collection_id).filter(
            models.SavedCollectionPost.post_id == post_id,
            models.SavedCollectionPost.collection_id.in_(
                [c.id for c in rows] or [-1])).all()}
    return {"collections": [_collection_dict(db, c, has_post)
                            for c in rows]}


@app.get("/saved/collections/{cid}")
def get_collection(cid: int,
                   user: models.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """Phase 175: one collection with its posts (most recently
    added first, deleted posts excluded)."""
    # Phase 179 (audit M4): "saved" budget (see list_collections).
    _enforce_rate("saved", f"u{user.telegram_id}")
    coll = _get_my_collection(db, user.telegram_id, cid)
    rows = db.query(models.Post).join(
        models.SavedCollectionPost,
        models.SavedCollectionPost.post_id == models.Post.id) \
        .filter(models.SavedCollectionPost.collection_id == cid,
                models.Post.is_deleted == False) \
        .order_by(models.SavedCollectionPost.id.desc()).limit(50).all()
    # Phase 178 (audit H5): same visibility filter as Saved —
    # a collection must not resurrect a post the viewer may
    # no longer see (blocked / muted / private author).
    rows = [p for p in rows
            if _post_visible_to(db, user.telegram_id, p)]
    out = _collection_dict(db, coll)
    out["posts"] = _post_list(db, rows, user.telegram_id)
    return out


@app.patch("/saved/collections/{cid}")
def rename_collection(cid: int, body: CollectionIn,
                      user: models.User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """Phase 175: rename my collection."""
    coll = _get_my_collection(db, user.telegram_id, cid)
    coll.name = _clean_collection_name(
        db, user.telegram_id, body.name, exclude_id=cid)
    db.commit()
    db.refresh(coll)
    return _collection_dict(db, coll)


@app.delete("/saved/collections/{cid}")
def delete_collection(cid: int,
                      user: models.User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """Phase 175: delete my collection — its posts stay bookmarked
    in All saved; only the membership rows go."""
    coll = _get_my_collection(db, user.telegram_id, cid)
    db.query(models.SavedCollectionPost).filter_by(
        collection_id=cid).delete(synchronize_session=False)
    db.delete(coll)
    db.commit()
    return {"deleted": True}


@app.post("/saved/collections/{cid}/posts")
def add_to_collection(cid: int, body: CollectionPostIn,
                      user: models.User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """Phase 175: save a post into my collection. Saving to a
    collection also bookmarks the post (a duplicate add is a
    no-op, not an error)."""
    coll = _get_my_collection(db, user.telegram_id, cid)
    p = get_live_post(db, body.post_id)
    # Phase 179 (audit H2): filing needs the same visibility as
    # reading — checked before the already-filed early return,
    # so an invisible post cannot be (re-)confirmed as saved.
    _require_post_visible(db, user.telegram_id, p)
    existing = db.query(models.SavedCollectionPost).filter_by(
        collection_id=cid, post_id=p.id).first()
    if existing:
        return {"added": False, "saved": True}
    if db.query(models.SavedPost).filter_by(
            post_id=p.id, user_id=user.telegram_id).first() is None:
        db.add(models.SavedPost(post_id=p.id,
                                user_id=user.telegram_id))
    db.add(models.SavedCollectionPost(collection_id=cid, post_id=p.id))
    db.commit()
    return {"added": True, "saved": True}


@app.delete("/saved/collections/{cid}/posts/{post_id}")
def remove_from_collection(cid: int, post_id: int,
                           user: models.User = Depends(current_user),
                           db: Session = Depends(get_db)):
    """Phase 175: remove a post from my collection. The post stays
    bookmarked in All saved. Removing a post that is not in the
    collection is a no-op."""
    coll = _get_my_collection(db, user.telegram_id, cid)
    n = db.query(models.SavedCollectionPost).filter_by(
        collection_id=cid, post_id=post_id) \
        .delete(synchronize_session=False)
    db.commit()
    return {"removed": n > 0}


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
    # Phase 179 (audit H4): the SHARER must see the post too —
    # sharing by ID was a complete bypass (only the sharer/
    # recipient block was checked). A sharer who cannot see the
    # post cannot share it, whatever the recipient may see.
    _require_post_visible(db, user.telegram_id, p)
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
    # Phase 179 (audit M4): "saved" budget (see list_collections).
    # Phase 179 (audit H4): post_dict hides a shared repost of an
    # invisible original, but a shared ORIGINAL renders
    # unconditionally — hence the _post_visible_to filter below.
    # The test proves it end to end.
    _enforce_rate("saved", f"u{user.telegram_id}")
    shares = db.query(models.PostShare).filter_by(
        to_user_id=user.telegram_id) \
        .order_by(models.PostShare.id.desc()).limit(50).all()
    out = []
    for s in shares:
        p = db.get(models.Post, s.post_id)
        if p is None or p.is_deleted:
            continue
        # Phase 179 (audit H4): post_dict hides only reposts of
        # invisible originals — a shared ORIGINAL needs the same
        # visibility check here (as /me/saved does), or a private
        # post shared by a follower to a non-follower displays.
        if not _post_visible_to(db, user.telegram_id, p):
            continue
        sender = db.get(models.User, s.from_user_id)
        # Phase 177: resolve reposts with the viewer, so a
        # shared repost of a blocked author stays hidden.
        d = post_dict(db, p,
                      liked=_eff_id(p) in liked_ids(db, user.telegram_id, [p]),
                      saved=_eff_id(p) in saved_ids(db, user.telegram_id, [p]),
                      reposted_by_me=_eff_id(p) in reposted_ids(db, user.telegram_id, [p]),
                      viewer_id=user.telegram_id)
        if d is None:
            continue
        d["shared_by_id"] = s.from_user_id
        d["shared_by_name"] = sender.first_name if sender else ""
        d["shared_at"] = s.created_at.isoformat() if s.created_at else None
        out.append(d)
    return {"posts": out}


class CommentIn(BaseModel):
    text: str = Field(max_length=1000)
    parent_id: Optional[int] = None  # Phase 118: reply target


def comment_dict(db, cm, reply_count=0, replies=None,
                 like_count=0, liked_by_me=False):
    author = db.get(models.User, cm.user_id)
    return {
        "id": cm.id, "post_id": cm.post_id, "user_id": cm.user_id,
        "like_count": like_count, "liked_by_me": liked_by_me,
        "parent_id": getattr(cm, "parent_id", None),
        "author_name": author.first_name if author else "",
        "author_username": author.username if author else None,
        "author_verified": bool(author and author.is_verified),
        "author_photo": author.photo_file_id if author else None,
        "text": cm.text,
        "mentions": _comment_mention_list(db, cm),
        "reply_count": reply_count,
        "replies": replies or [],
        "created_at": cm.created_at.isoformat() if cm.created_at else None,
    }


@app.get("/posts/{post_id}/comments")
def list_comments(post_id: int, user: models.User = Depends(current_user),
                  db: Session = Depends(get_db)):
    # Phase 179 (audit M4): "post_read" budget, shared with
    # GET /posts/{id} — comments load once per post open.
    _enforce_rate("post_read", f"u{user.telegram_id}")
    p = get_live_post(db, post_id)
    # Phase 178 (audit H5): comments are readable only when
    # the post itself is visible to the viewer — a blocked
    # author (either direction) or a private author the
    # viewer does not follow 404s, exactly like the
    # single-post view (effective author for repost rows).
    eff_id = p.repost_of_id or p.id
    eff = db.get(models.Post, eff_id) if eff_id != p.id else p
    if (eff is None or eff.is_deleted
            or _blocked_by(db, eff.user_id, user.telegram_id)
            or _blocked_by(db, user.telegram_id, eff.user_id)
            or not _can_see_posts(db, user.telegram_id,
                                  eff.user_id)):
        raise HTTPException(404, "Post not found")
    # Second-pass audit (R1): this was the one unbounded list in the
    # API — a post with tens of thousands of comments returned all
    # of them at once. Now the LATEST 500, in reading order.
    tops = db.query(models.Comment).filter_by(
        post_id=p.id, parent_id=None) \
        .order_by(models.Comment.id.desc()).limit(500).all()
    tops.reverse()
    # Phase 118: replies — one level deep, oldest first, in one
    # extra query for the whole post.
    replies = db.query(models.Comment).filter_by(post_id=p.id) \
        .filter(models.Comment.parent_id.isnot(None)) \
        .order_by(models.Comment.id.asc()).limit(2000).all()
    # Phase 174: a muted member's comments (and their replies)
    # do not show for the muter. A muted parent takes its
    # replies with it — they are attached to that comment.
    muted = _muted_ids(db, user.telegram_id)
    if muted:
        tops = [cm for cm in tops if cm.user_id not in muted]
        replies = [r for r in replies if r.user_id not in muted]
    # Phase 178: comments by a member block-related to the
    # viewer (either direction) are hidden too — a blocked
    # parent takes its replies with it, as muted parents do.
    hidden = _block_related_ids(db, user.telegram_id)
    if hidden:
        tops = [cm for cm in tops if cm.user_id not in hidden]
        replies = [r for r in replies if r.user_id not in hidden]
    by_parent = {}
    for r in replies:
        by_parent.setdefault(r.parent_id, []).append(r)
    # Phase 123: comment likes — one grouped count query for
    # the whole post, plus which comments the viewer liked.
    all_ids = [cm.id for cm in tops] + [r.id for r in replies]
    like_counts = {}
    liked_cm = set()
    if all_ids:
        rows = db.query(models.CommentLike.comment_id,
                      func.count()).filter(
            models.CommentLike.comment_id.in_(all_ids)).group_by(
            models.CommentLike.comment_id).all()
        like_counts = {cid: n for cid, n in rows}
        liked_cm = {r[0] for r in db.query(
            models.CommentLike.comment_id).filter(
            models.CommentLike.comment_id.in_(all_ids),
            models.CommentLike.user_id == user.telegram_id).all()}
    out = []
    for cm in tops:
        rs = by_parent.get(cm.id, [])
        out.append(comment_dict(
            db, cm, reply_count=len(rs),
            replies=[comment_dict(db, r,
                                  like_count=like_counts.get(r.id, 0),
                                  liked_by_me=r.id in liked_cm)
                     for r in rs[:50]],
            like_count=like_counts.get(cm.id, 0),
            liked_by_me=cm.id in liked_cm))
    return {"comments": out}


@app.post("/posts/{post_id}/comments")
async def add_comment(post_id: int, body: CommentIn,
                      user: models.User = Depends(current_user),
                      db: Session = Depends(get_db)):
    _enforce_rate("comment", f"u{user.telegram_id}")
    p = get_live_post(db, post_id)
    # Phase 179 (audit H2): commenting needs the same visibility
    # as reading — blocked, muted, or private-and-not-followed
    # (effective author: a repost resolves to its original).
    # Self-comments still pass: own posts are visible.
    _require_post_visible(db, user.telegram_id, p)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Comment text is empty")
    # Phase 142: banned-word list (posts + comments only — DMs are
    # private conversations and are not checked).
    if banned_word_in(db, text):
        raise HTTPException(400, BANNED_WORD_MESSAGE)
    # Phase 118: a reply targets a comment on this post; a
    # reply to a reply answers its top comment instead.
    parent = None
    if body.parent_id is not None:
        parent = db.get(models.Comment, body.parent_id)
        if parent is None or parent.post_id != p.id:
            raise HTTPException(400, "That comment does not exist here")
        if parent.parent_id is not None:
            parent = db.get(models.Comment, parent.parent_id)
    cm = models.Comment(post_id=p.id, user_id=user.telegram_id, text=text,
                      parent_id=parent.id if parent else None)
    db.add(cm)
    p.comment_count = (p.comment_count or 0) + 1
    db.commit()
    db.refresh(cm)
    # Phase 170: @mentions in the comment.
    for uid in sync_mentions(db, user.telegram_id, None, cm.id,
                             text, p.user_id):
        await notify.notify_user(
            db, uid, "mention",
            f"📣 @{user.username or user.first_name} mentioned you "
            f"in a comment: {text[:80]}")
    if p.user_id != user.telegram_id:
        await notify.notify_user(
            db, p.user_id, "comment",
            f"\U0001F4AC {user.first_name} commented on your post: {text[:80]}")
        notify.record(db, p.user_id, "comment",
                      actor_id=user.telegram_id, post_id=p.id)
    # Phase 118: the parent comment's author hears about the
    # reply — unless they are the post author (already told)
    # or the replier themself.
    if parent is not None and parent.user_id != user.telegram_id \
            and parent.user_id != p.user_id:
        await notify.notify_user(
            db, parent.user_id, "reply",
            f"\U0001F4AC {user.first_name} replied to your comment: {text[:80]}")
        notify.record(db, parent.user_id, "reply",
                      actor_id=user.telegram_id, post_id=p.id)
    return comment_dict(db, cm)


@app.post("/posts/{post_id}/comments/{comment_id}/like")
def toggle_comment_like(post_id: int, comment_id: int,
                        user: models.User = Depends(current_user),
                        db: Session = Depends(get_db)):
    """Phase 123: like/unlike one comment (toggle). Same blocked-
    author guard as commenting: a comment on a blocked member's
    post cannot be liked."""
    _enforce_rate("comment_like", f"u{user.telegram_id}")
    p = get_live_post(db, post_id)
    cm = db.get(models.Comment, comment_id)
    if cm is None or cm.post_id != p.id:
        raise HTTPException(404, "Comment not found")
    if p.user_id != user.telegram_id and (
            _blocked_by(db, p.user_id, user.telegram_id)
            or _blocked_by(db, user.telegram_id, p.user_id)):
        raise HTTPException(403, "This member is not available")
    existing = db.query(models.CommentLike).filter_by(
        comment_id=cm.id, user_id=user.telegram_id).first()
    if existing:
        db.delete(existing)
        liked = False
    else:
        db.add(models.CommentLike(comment_id=cm.id,
                                  user_id=user.telegram_id))
        liked = True
    db.commit()
    count = db.query(models.CommentLike).filter_by(
        comment_id=cm.id).count()
    return {"liked": liked, "like_count": count,
            "comment_id": cm.id}


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
    # Phase 178 (audit H1): same the other way — a viewer who
    # blocked the target gets a plain 404, not the full
    # profile (bio, points, blood group, skills, photo/cover
    # all stay hidden). A minimal flag-only 200 was
    # considered and rejected: openProfile reads first_name /
    # followers / following_count unconditionally, so it
    # would render a blank name and "undefined followers"
    # before the Unblock button; Unblock stays available via
    # Settings -> blocked list (GET /me/blocked).
    if (_blocked_by(db, telegram_id, user.telegram_id)
            or _blocked_by(db, user.telegram_id, telegram_id)):
        raise HTTPException(404, "User not found")
    followers = db.query(models.Follow).filter_by(following_id=telegram_id).count()
    if telegram_id == OFFICIAL_ID:
        followers += OFFICIAL_FOLLOWER_BASE  # official account starts at 10k
    following_count = db.query(models.Follow).filter_by(follower_id=telegram_id).count()
    posts = db.query(models.Post).filter_by(
        user_id=telegram_id, is_deleted=False).filter(models.Post.type != "repost").count()
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
    level_badges = _level_and_badges(db, target)
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
        # Phase 136: private-account state for the profile view
        # (lock notice + Follow/Requested button).
        "is_private": bool(getattr(target, "is_private", False)),
        # Phase 151: blood group is health-adjacent — shown
        # only when the member opted in as a donor.
        "blood_group": (target.blood_group
                      if bool(getattr(target, "blood_donor", False))
                      else None),
        # Phase 158: skills the member teaches / wants to
        # learn — shown only when the viewer may see this
        # profile (the Phase 136 rule); strangers of a
        # private account get empty lists.
        "skills": _skills_for_user(db, target.telegram_id)
        if _can_see_posts(db, user.telegram_id, telegram_id)
        else {"teach": [], "learn": []},
        "has_pending_request": db.query(models.FollowRequest).filter_by(
            requester_id=user.telegram_id, target_id=telegram_id,
            status="pending").first() is not None,
        # R5: whether the viewer has blocked this member (the
        # profile offers Block/Unblock from this flag).
        "blocked_by_me": _blocked_by(db, user.telegram_id, telegram_id),
        # Phase 174: whether the viewer has muted this member.
        "muted_by_me": _muted_by(db, user.telegram_id, telegram_id),
        "name_locked_days": name_locked_days,
        # Phase 137: level (from lifetime points) + badges.
        "level": level_badges["level"],
        "badges": level_badges["badges"],
    }


@app.post("/users/{telegram_id}/follow")
async def toggle_follow(telegram_id: int, user: models.User = Depends(current_user),
                        db: Session = Depends(get_db)):
    _enforce_rate("follow", f"u{user.telegram_id}")
    if telegram_id == user.telegram_id:
        raise HTTPException(400, "You cannot follow yourself")
    target = db.get(models.User, telegram_id)
    if target is None:
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
        requested = False
    else:
        # Phase 136: following a private account asks first — a
        # pending request instead of an instant follow. Asking
        # again while one is pending is a 400; cancelling it is
        # DELETE /users/{id}/follow-request.
        pending = db.query(models.FollowRequest).filter_by(
            requester_id=user.telegram_id, target_id=telegram_id,
            status="pending").first()
        if pending:
            raise HTTPException(
                400, "Follow request already pending")
        elif getattr(target, "is_private", False):
            db.add(models.FollowRequest(
                requester_id=user.telegram_id, target_id=telegram_id))
            now_following = False
            requested = True
        else:
            db.add(models.Follow(follower_id=user.telegram_id,
                                 following_id=telegram_id))
            _record_follow_task_event(db, user.telegram_id, telegram_id)
            now_following = True
            requested = False
    db.commit()
    followers = db.query(models.Follow).filter_by(following_id=telegram_id).count()
    if telegram_id == OFFICIAL_ID:
        followers += OFFICIAL_FOLLOWER_BASE
    if requested:
        await notify.notify_user(
            db, telegram_id, "follow_request",
            f"\U0001F465 {user.first_name} wants to follow you.")
        notify.record(db, telegram_id, "follow_request",
                      actor_id=user.telegram_id,
                      text="wants to follow you")
    elif now_following:
        await notify.notify_user(
            db, telegram_id, "follow",
            f"\U0001F465 {user.first_name} started following you.")
        notify.record(db, telegram_id, "follow",
                      actor_id=user.telegram_id)
    return {"following": now_following, "requested": requested,
            "followers": followers}


# ---------------------------------------------------------------------------
# Phase 136: private accounts — a follow request the owner
# approves, instead of an instant follow. Visibility is enforced
# in feed / profile posts / GET /posts/{id} / Trending (above);
# the toggle itself lives on /me/privacy and the official
# account can never be private.
# ---------------------------------------------------------------------------

class PrivacyIn(BaseModel):
    is_private: bool = False


@app.post("/me/privacy")
def set_privacy(body: PrivacyIn, user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
    """Flip your own account private or public. The official
    account stays public — it is the platform's front door."""
    _enforce_rate("privacy", f"u{user.telegram_id}")
    if user.telegram_id == OFFICIAL_ID:
        raise HTTPException(
            400, "The official Nexora Social account cannot be private")
    user.is_private = bool(body.is_private)
    db.commit()
    return {"is_private": bool(user.is_private)}


def _notif_prefs_dict(user):
    """Phase 144: the member's effective notification prefs —
    every key present, missing keys ON. A member who never opened
    Settings gets today's behaviour (all on)."""
    prefs = {k: True for k in notify.NOTIF_PREF_KEYS}
    raw = getattr(user, "notif_prefs", None)
    if raw:
        try:
            saved = json.loads(raw)
            if isinstance(saved, dict):
                for k in prefs:
                    if isinstance(saved.get(k), bool):
                        prefs[k] = saved[k]
        except Exception:
            pass
    return prefs


@app.get("/me/notification-prefs")
def my_notification_prefs(user: models.User = Depends(current_user)):
    """Your own notification toggles. There is deliberately no
    /users/{id}/notification-prefs route — nobody, not even an
    admin, can read or change another member's prefs here."""
    return {"prefs": _notif_prefs_dict(user)}


@app.post("/me/notification-prefs")
def save_notification_prefs(body: dict,
                            user: models.User = Depends(current_user),
                            db: Session = Depends(get_db)):
    """Save your own notification toggles. Unknown keys and
    non-boolean values are 400; the body merges over the stored
    prefs, so sending one toggle never resets the others. Only
    the caller's own row is ever written."""
    if not isinstance(body, dict):
        raise HTTPException(400, "Expected an object of toggles")
    prefs = _notif_prefs_dict(user)
    for key, val in body.items():
        if key not in notify.NOTIF_PREF_KEYS:
            raise HTTPException(400, f"Unknown notification type: {key}")
        if not isinstance(val, bool):
            raise HTTPException(
                400, f'"{key}" must be true or false')
        prefs[key] = val
    _enforce_rate("notif_prefs", f"u{user.telegram_id}")
    user.notif_prefs = json.dumps(prefs)
    db.commit()
    return {"prefs": prefs}

def follow_request_dict(db, r):
    ru = db.get(models.User, r.requester_id)
    return {
        "id": r.id,
        "requester_id": r.requester_id,
        "first_name": ru.first_name if ru else "",
        "username": ru.username if ru else None,
        "photo_file_id": ru.photo_file_id if ru else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@app.get("/me/follow-requests")
def my_follow_requests(user: models.User = Depends(current_user),
                       db: Session = Depends(get_db)):
    """Incoming pending follow requests, newest first."""
    rows = db.query(models.FollowRequest).filter_by(
        target_id=user.telegram_id, status="pending") \
        .order_by(models.FollowRequest.id.desc()).all()
    return {"follow_requests": [follow_request_dict(db, r) for r in rows]}


def _pending_request_for(db, request_id, target_id):
    req = db.get(models.FollowRequest, request_id)
    if req is None or req.target_id != target_id \
            or req.status != "pending":
        raise HTTPException(404, "Follow request not found")
    return req


@app.post("/follow-requests/{request_id}/accept")
async def accept_follow_request(request_id: int,
                                user: models.User = Depends(current_user),
                                db: Session = Depends(get_db)):
    """Approve a follow request: the requester becomes a
    follower and hears about it."""
    _enforce_rate("follow", f"u{user.telegram_id}")
    req = _pending_request_for(db, request_id, user.telegram_id)
    if db.query(models.Follow).filter_by(
            follower_id=req.requester_id,
            following_id=user.telegram_id).first() is None:
        db.add(models.Follow(follower_id=req.requester_id,
                             following_id=user.telegram_id))
        _record_follow_task_event(db, req.requester_id, user.telegram_id)
    req.status = "accepted"
    db.commit()
    await notify.notify_user(
        db, req.requester_id, "follow",
        f"\u2705 {user.first_name} accepted your follow request.")
    notify.record(db, req.requester_id, "follow",
                  actor_id=user.telegram_id,
                  text="accepted your follow request")
    return {"accepted": True, "request_id": req.id}


@app.post("/follow-requests/{request_id}/reject")
def reject_follow_request(request_id: int,
                          user: models.User = Depends(current_user),
                          db: Session = Depends(get_db)):
    """Turn a follow request away: no follow row, no message."""
    _enforce_rate("follow", f"u{user.telegram_id}")
    req = _pending_request_for(db, request_id, user.telegram_id)
    req.status = "rejected"
    db.commit()
    return {"rejected": True, "request_id": req.id}


@app.delete("/users/{telegram_id}/follow-request")
def cancel_follow_request(telegram_id: int,
                          user: models.User = Depends(current_user),
                          db: Session = Depends(get_db)):
    """Cancel your own pending follow request to this member —
    the profile button's "Requested — tap to cancel" action.
    A second POST /follow while one is pending is a 400, so the
    cancel has its own call."""
    _enforce_rate("follow", f"u{user.telegram_id}")
    req = db.query(models.FollowRequest).filter_by(
        requester_id=user.telegram_id, target_id=telegram_id,
        status="pending").first()
    if req is None:
        raise HTTPException(404, "No pending follow request")
    db.delete(req)
    db.commit()
    return {"cancelled": True}


# ---------------------------------------------------------------------------
# Phase 140: hashtag follows — follow a #tag and its posts show
# up in the Hashtags feed (GET /feed/hashtags, above). No
# notifications: a hashtag is not a person, and nobody needs a
# ping for every new #tech post.
# ---------------------------------------------------------------------------


def _clean_tag(raw: str):
    """'#Tech' -> 'tech'; None when the tag is not usable
    (1-50 word characters, after stripping the leading '#')."""
    tag = (raw or "").strip().lstrip("#").lower()
    if not tag or not re.fullmatch(r"\w{1,50}", tag):
        return None
    return tag


@app.post("/hashtags/{tag}/follow")
def follow_hashtag(tag: str, user: models.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    _enforce_rate("hashtag_follow", f"u{user.telegram_id}")
    clean = _clean_tag(tag)
    if clean is None:
        raise HTTPException(400, "Not a valid hashtag")
    existing = db.query(models.HashtagFollow).filter_by(
        user_id=user.telegram_id, tag=clean).first()
    if existing:
        raise HTTPException(400, "Already following this hashtag")
    db.add(models.HashtagFollow(user_id=user.telegram_id, tag=clean))
    db.commit()
    return {"following": True, "tag": clean}


@app.delete("/hashtags/{tag}/follow")
def unfollow_hashtag(tag: str, user: models.User = Depends(current_user),
                     db: Session = Depends(get_db)):
    _enforce_rate("hashtag_follow", f"u{user.telegram_id}")
    clean = _clean_tag(tag)
    if clean is None:
        raise HTTPException(400, "Not a valid hashtag")
    existing = db.query(models.HashtagFollow).filter_by(
        user_id=user.telegram_id, tag=clean).first()
    if existing is None:
        raise HTTPException(404, "Not following this hashtag")
    db.delete(existing)
    db.commit()
    return {"following": False, "tag": clean}


@app.get("/me/hashtags")
def my_hashtags(user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
    """Tags the caller follows, newest first, each with the
    number of live original posts carrying it."""
    rows = db.query(models.HashtagFollow).filter_by(
        user_id=user.telegram_id).order_by(
            models.HashtagFollow.id.desc()).all()
    out = []
    for f in rows:
        n = db.query(models.Post).filter_by(is_deleted=False).filter(
            models.Post.type != "repost",
            or_(models.Post.hashtags == f.tag,
                models.Post.hashtags.like(f.tag + " %"),
                models.Post.hashtags.like("% " + f.tag + " %"),
                models.Post.hashtags.like("% " + f.tag))).count()
        out.append({"tag": f.tag, "count": n,
                    "created_at": (f.created_at.isoformat()
                                   if f.created_at else None)})
    return {"hashtags": out}


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Phase 151: blood donors — a life-or-death community need in
# Bangladesh, built on profiles / Settings / DMs / notifications.
# Text-only, no media, no phone numbers anywhere: a donor opts in
# with a blood group (Settings), requests list open calls, a donor
# taps "আমি দেবো" and the requester is notified — contact is then
# an in-app DM. No points, no payments, no in-app upload.
# Privacy: a private donor appears only to followers/self (the
# Phase 136 rule, reused via _can_see_posts), and a private
# author's requests reach only followers too; blocked pairs never
# see each other (feed rule). The GEMINI media screening
# (moderation.py) is image-only and never touches this text flow;
# the banned-word check (Phase 142) still runs on request text.
# ---------------------------------------------------------------------------

BLOOD_GROUPS = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")


def _blood_donor_out(u, distance_km=None):
    """A directory row: name + group + country + profile photo —
    never a phone number, never a precise location. distance_km
    is included ONLY when both viewer and donor share location
    (Phase 152); it is a rounded distance, never coordinates.
    Phase 154: photo_file_id lets the donor card render the real
    photo (avatarEl falls back to initials when it is None).
    Phase 163: is_verified (same bool(u.is_verified) every
    other endpoint returns) lets the donor card show the
    blue tick."""
    row = {"telegram_id": u.telegram_id,
           "first_name": u.first_name,
           "username": u.username,
           "blood_group": u.blood_group,
           "country": u.country,
           "photo_file_id": u.photo_file_id,
           "is_verified": bool(u.is_verified)}
    if distance_km is not None:
        row["distance_km"] = distance_km
    return row


def _blood_visible_donors(db, viewer_id):
    """Opted-in donors the viewer may see, newest first: private
    donors only to their followers (Phase 136), never anyone in
    a block pair (feed rule)."""
    hidden = _block_related_ids(db, viewer_id)
    rows = db.query(models.User).filter(
        models.User.blood_donor == True,
        models.User.blood_group.isnot(None)).all()
    visible = [u for u in rows
               if u.telegram_id not in hidden
               and _can_see_posts(db, viewer_id, u.telegram_id)]
    visible.sort(key=lambda u: (u.created_at or datetime.min,
                                u.telegram_id), reverse=True)
    return visible


def _blood_request_out(db, r, viewer_id):
    author = db.get(models.User, r.author_id)
    return {"id": r.id,
            "author_id": r.author_id,
            "author_name": author.first_name if author else "?",
            "author_username": author.username if author else None,
            "blood_group": r.blood_group,
            "hospital": r.hospital,
            "city": r.city,
            "units": r.units,
            "note": r.note or "",
            "contact": r.contact or "",
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "fulfilled_at": (r.fulfilled_at.isoformat()
                             if r.fulfilled_at else None),
            "mine": r.author_id == viewer_id}


class BloodGroupIn(BaseModel):
    blood_group: Optional[str] = None
    is_donor: bool = False


@app.post("/me/blood-group")
def set_blood_group(body: BloodGroupIn,
                    user: models.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    """Set or clear your own donor status. The group must be one
    of the 8, or null to clear it. Opting in as a donor needs a
    group; clearing removes the member from the directory."""
    _enforce_rate("blood", f"u{user.telegram_id}")
    group = (body.blood_group or "").strip().upper() or None
    if group is not None and group not in BLOOD_GROUPS:
        raise HTTPException(400, "Not a valid blood group")
    if body.is_donor and group is None:
        raise HTTPException(
            400, "Choose a blood group to become a donor")
    user.blood_group = group
    user.blood_donor = bool(body.is_donor) and group is not None
    db.commit()
    return {"blood_group": user.blood_group,
            "blood_donor": bool(user.blood_donor)}


@app.get("/blood/donors")
def list_blood_donors(group: str = "",
                      user: models.User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """Opted-in donors only — nobody appears here until they opt
    in. Optional group filter; newest members first."""
    g = (group or "").strip().upper() or None
    if g is not None and g not in BLOOD_GROUPS:
        raise HTTPException(400, "Not a valid blood group")
    donors = _blood_visible_donors(db, user.telegram_id)
    if g is not None:
        donors = [u for u in donors if u.blood_group == g]
    # Phase 152: distance (haversine, same math as Nearby) — only
    # when BOTH viewer and donor share location; otherwise the
    # key is absent and the card shows just the country. Never
    # any donor lat/lon in the response.
    me_shares = bool(user.share_location) and user.lat is not None \
        and user.lon is not None
    out = []
    for u in donors:
        dist = None
        if me_shares and u.share_location and u.lat is not None \
                and u.lon is not None:
            dist = round(_haversine_m(user.lat, user.lon,
                                      u.lat, u.lon) / 1000.0, 2)
        out.append(_blood_donor_out(u, distance_km=dist))
    return {"donors": out}


class BloodRequestIn(BaseModel):
    blood_group: str = Field(default="", max_length=3)
    hospital: str = Field(default="", max_length=200)
    city: str = Field(default="", max_length=100)
    units: int = 1
    note: str = Field(default="", max_length=500)
    contact: Optional[str] = Field(default=None, max_length=200)


@app.post("/blood/requests")
async def create_blood_request(body: BloodRequestIn,
                               user: models.User = Depends(current_user),
                               db: Session = Depends(get_db)):
    """An open call for blood — text only. The banned-word check
    runs on the typed text (Phase 142); "blood" / "রক্ত" itself
    is not a banned word, so an ordinary request always passes.
    Matching donors are notified — ONLY the opted-in donors of
    this exact group who can see the requester, never every
    donor and never other groups."""
    _enforce_rate("blood", f"u{user.telegram_id}")
    group = (body.blood_group or "").strip().upper()
    if group not in BLOOD_GROUPS:
        raise HTTPException(400, "Not a valid blood group")
    hospital = (body.hospital or "").strip()
    city = (body.city or "").strip()
    if not hospital or not city:
        raise HTTPException(400, "Hospital and city are required")
    units = body.units
    if not isinstance(units, int) or units < 1 or units > 10:
        raise HTTPException(400, "Units must be 1-10")
    note = (body.note or "").strip()
    contact = (body.contact or "").strip() or None
    bad = banned_word_in(db, " ".join(
        [hospital, city, note, contact or ""]))
    if bad:
        raise HTTPException(400, BANNED_WORD_MESSAGE)
    req = models.BloodRequest(author_id=user.telegram_id,
                              blood_group=group, hospital=hospital,
                              city=city, units=units, note=note,
                              contact=contact)
    db.add(req)
    db.commit()
    db.refresh(req)
    hidden = _block_related_ids(db, user.telegram_id)
    donors = db.query(models.User).filter(
        models.User.blood_donor == True,
        models.User.blood_group == group).all()
    for donor in donors:
        if donor.telegram_id == user.telegram_id:
            continue
        if donor.telegram_id in hidden:
            continue
        if not _can_see_posts(db, donor.telegram_id,
                              user.telegram_id):
            continue
        await notify.notify_user(
            db, donor.telegram_id, "blood_request",
            f"🩸 Blood needed: {group} at {hospital}, {city} — "
            f"{units} unit(s). Open the Blood page to respond.")
        notify.record(db, donor.telegram_id, "blood_request",
                      actor_id=user.telegram_id,
                      text=f"blood needed: {group} at {hospital}, {city}")
    return _blood_request_out(db, req, user.telegram_id)


@app.get("/blood/requests")
def list_blood_requests(group: str = "", status: str = "open",
                        user: models.User = Depends(current_user),
                        db: Session = Depends(get_db)):
    """Open requests, newest first; optional group filter and
    status filter (open | fulfilled | cancelled). A private
    author's requests reach only followers (Phase 136)."""
    g = (group or "").strip().upper() or None
    if g is not None and g not in BLOOD_GROUPS:
        raise HTTPException(400, "Not a valid blood group")
    st = (status or "open").strip().lower()
    if st not in ("open", "fulfilled", "cancelled"):
        raise HTTPException(400, "Not a valid status")
    q = db.query(models.BloodRequest).filter(
        models.BloodRequest.status == st)
    if g is not None:
        q = q.filter(models.BloodRequest.blood_group == g)
    rows = q.order_by(models.BloodRequest.id.desc()).all()
    hidden = _block_related_ids(db, user.telegram_id)
    out = []
    for r in rows:
        if r.author_id in hidden:
            continue
        if not _can_see_posts(db, user.telegram_id, r.author_id):
            continue
        out.append(_blood_request_out(db, r, user.telegram_id))
    return {"requests": out}


@app.post("/blood/requests/{req_id}/respond")
async def respond_blood_request(req_id: int,
                                user: models.User = Depends(current_user),
                                db: Session = Depends(get_db)):
    """'আমি দেবো' — the requester is notified; the client then
    opens a DM with the requester. No responses table: the
    notification + the DM IS the response."""
    _enforce_rate("blood", f"u{user.telegram_id}")
    req = db.get(models.BloodRequest, req_id)
    if req is None:
        raise HTTPException(404, "Blood request not found")
    if req.author_id == user.telegram_id:
        raise HTTPException(400, "You cannot respond to your own request")
    if req.status != "open":
        raise HTTPException(400, "This request is no longer open")
    await notify.notify_user(
        db, req.author_id, "blood_respond",
        f"🩸 {user.first_name} wants to donate {req.blood_group} "
        f"blood for your request at {req.hospital}.")
    notify.record(db, req.author_id, "blood_respond",
                  actor_id=user.telegram_id,
                  text="wants to donate blood for your request")
    return {"ok": True, "author_id": req.author_id}


def _blood_request_for_author(req_id, user, db):
    req = db.get(models.BloodRequest, req_id)
    if req is None:
        raise HTTPException(404, "Blood request not found")
    if req.author_id != user.telegram_id:
        raise HTTPException(403, "Only the requester can do this")
    return req


@app.post("/blood/requests/{req_id}/fulfill")
def fulfill_blood_request(req_id: int,
                          user: models.User = Depends(current_user),
                          db: Session = Depends(get_db)):
    """The author marks their request fulfilled (blood found)."""
    _enforce_rate("blood", f"u{user.telegram_id}")
    req = _blood_request_for_author(req_id, user, db)
    if req.status != "open":
        raise HTTPException(400, "This request is no longer open")
    req.status = "fulfilled"
    req.fulfilled_at = datetime.utcnow()
    db.commit()
    return _blood_request_out(db, req, user.telegram_id)


@app.post("/blood/requests/{req_id}/cancel")
def cancel_blood_request(req_id: int,
                         user: models.User = Depends(current_user),
                         db: Session = Depends(get_db)):
    """The author withdraws their request."""
    _enforce_rate("blood", f"u{user.telegram_id}")
    req = _blood_request_for_author(req_id, user, db)
    if req.status != "open":
        raise HTTPException(400, "This request is no longer open")
    req.status = "cancelled"
    db.commit()
    return _blood_request_out(db, req, user.telegram_id)

# ---------------------------------------------------------------------------
# Phase 158: Skill Swap (দক্ষতা বিনিময়) — owner pick #7 from the Nov 20
# global-problems proposal. Teach what you know, learn what you don't —
# language, coding, cooking, music. No money, no scheduling inside the
# app, no ratings in v1: the swap itself is arranged in a DM. A member
# lists skills (teach and/or learn, free text); matching is computed,
# not stored — teach X matches learn X. A "connect" notifies the other
# member (new 9th notification toggle "skills") and the client opens
# a DM, mirroring Blood's "আমি দেবো" pattern. Privacy reuses the
# Phase 136 rule via _can_see_posts + block-pair exclusion, same as
# Blood. The Phase 142 banned-word check runs on skill names/notes.
# ---------------------------------------------------------------------------

SKILL_KINDS = ("teach", "learn")
SKILL_MAX_LEN = 80
SKILL_NOTE_MAX_LEN = 200
SKILL_MAX_PER_USER = 20


def _norm_skill(name):
    return " ".join((name or "").split())


def _skill_entry_out(e):
    return {"id": e.id,
            "skill": e.skill,
            "kind": e.kind,
            "note": e.note or "",
            "created_at": e.created_at.isoformat() if e.created_at else None}


def _skills_for_user(db, user_id):
    """{"teach": [names], "learn": [names]} — alphabetical, for
    profile display. An empty list means the member lists nothing."""
    rows = db.query(models.SkillEntry).filter_by(user_id=user_id).all()
    out = {"teach": [], "learn": []}
    for e in rows:
        if e.kind in out:
            out[e.kind].append(e.skill)
    out["teach"].sort(key=str.lower)
    out["learn"].sort(key=str.lower)
    return out


def _skill_members(db, viewer_id, q=None, kind=None, skill=None):
    """Members with listed skills the viewer may see, newest
    skill first: private members only to their followers
    (Phase 136), never anyone in a block pair (feed rule). q is a
    case-insensitive substring on the skill name; skill is an
    exact (case-insensitive) skill name; kind restricts to teach
    or learn entries. Returns [(user, [entries])]."""
    hidden = _block_related_ids(db, viewer_id)
    rows = db.query(models.SkillEntry).order_by(
        models.SkillEntry.id.desc()).all()
    qlow = (q or "").strip().lower() or None
    slow = (skill or "").strip().lower() or None
    by_user = {}
    for e in rows:
        if kind is not None and e.kind != kind:
            continue
        if qlow is not None and qlow not in e.skill.lower():
            continue
        if slow is not None and e.skill.lower() != slow:
            continue
        by_user.setdefault(e.user_id, []).append(e)
    out = []
    for user_id, entries in by_user.items():
        if user_id in hidden:
            continue
        if not _can_see_posts(db, viewer_id, user_id):
            continue
        u = db.get(models.User, user_id)
        if u is None:
            continue
        out.append((u, entries))
    out.sort(key=lambda t: max(e.id for e in t[1]), reverse=True)
    return out


def _skill_member_out(u, entries):
    return {"telegram_id": u.telegram_id,
            "first_name": u.first_name,
            "username": u.username,
            "photo_file_id": u.photo_file_id,
            "country": u.country,
            "teach": [e.skill for e in entries if e.kind == "teach"],
            "learn": [e.skill for e in entries if e.kind == "learn"]}


def _skill_match(db, viewer_id, user_id):
    """Overlap between two members' lists: skills the viewer
    wants to learn that the other teaches, and skills the viewer
    teaches that the other wants to learn. Case-insensitive."""
    mine = _skills_for_user(db, viewer_id)
    theirs = _skills_for_user(db, user_id)
    my_learn = {s.lower(): s for s in mine["learn"]}
    their_teach = {s.lower(): s for s in theirs["teach"]}
    teach_for_me = sorted({their_teach[k] for k in my_learn
                           if k in their_teach}, key=str.lower)
    my_teach = {s.lower(): s for s in mine["teach"]}
    their_learn = {s.lower(): s for s in theirs["learn"]}
    learn_from_me = sorted({their_learn[k] for k in my_teach
                            if k in their_learn}, key=str.lower)
    return {"teach_for_me": teach_for_me,
            "learn_from_me": learn_from_me}


class SkillIn(BaseModel):
    skill: str = ""
    kind: str = ""
    note: str = ""


@app.post("/me/skills")
def add_my_skill(body: SkillIn,
                 user: models.User = Depends(current_user),
                 db: Session = Depends(get_db)):
    """List one skill you teach or want to learn. Free text, no
    money, no scheduling — the swap is arranged in a DM."""
    _enforce_rate("skills", f"u{user.telegram_id}")
    skill = _norm_skill(body.skill)
    kind = (body.kind or "").strip().lower()
    note = (body.note or "").strip()
    if kind not in SKILL_KINDS:
        raise HTTPException(400, "kind must be teach or learn")
    if not skill or len(skill) > SKILL_MAX_LEN:
        raise HTTPException(400, "Skill name must be 1-80 characters")
    if len(note) > SKILL_NOTE_MAX_LEN:
        raise HTTPException(400, "Note must be at most 200 characters")
    bad = banned_word_in(db, skill + " " + note)
    if bad:
        raise HTTPException(400, BANNED_WORD_MESSAGE)
    mine = db.query(models.SkillEntry).filter_by(
        user_id=user.telegram_id).all()
    if len(mine) >= SKILL_MAX_PER_USER:
        raise HTTPException(400, "You can list up to 20 skills")
    for e in mine:
        if e.kind == kind and e.skill.lower() == skill.lower():
            raise HTTPException(400, "You already listed this skill")
    e = models.SkillEntry(user_id=user.telegram_id, skill=skill,
                          kind=kind, note=note)
    db.add(e)
    db.commit()
    db.refresh(e)
    return _skill_entry_out(e)


@app.get("/me/skills")
def my_skills(user: models.User = Depends(current_user),
              db: Session = Depends(get_db)):
    rows = db.query(models.SkillEntry).filter_by(
        user_id=user.telegram_id).order_by(
        models.SkillEntry.id.desc()).all()
    return {"skills": [_skill_entry_out(e) for e in rows]}


@app.delete("/me/skills/{entry_id}")
def remove_my_skill(entry_id: int,
                    user: models.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    _enforce_rate("skills", f"u{user.telegram_id}")
    e = db.get(models.SkillEntry, entry_id)
    if e is None:
        raise HTTPException(404, "Skill not found")
    if e.user_id != user.telegram_id:
        raise HTTPException(403, "Only the owner can remove this skill")
    db.delete(e)
    db.commit()
    return {"ok": True}


@app.get("/skills/directory")
def list_skill_directory(q: str = "", kind: str = "", skill: str = "",
                        user: models.User = Depends(current_user),
                        db: Session = Depends(get_db)):
    """Members with listed skills — search by skill name (q),
    filter teach/learn, or match one exact skill. Removing all
    of your skills removes you from this directory."""
    k = (kind or "").strip().lower() or None
    if k is not None and k not in SKILL_KINDS:
        raise HTTPException(400, "kind must be teach or learn")
    members = _skill_members(db, user.telegram_id, q=q, kind=k,
                             skill=skill)
    return {"members": [_skill_member_out(u, entries)
                        for u, entries in members]}


@app.get("/skills/matches")
def my_skill_matches(user: models.User = Depends(current_user),
                     db: Session = Depends(get_db)):
    """Computed matches: members who teach what I want to learn,
    or want to learn what I teach. Nothing is stored — the
    overlap is computed from the two lists on every call."""
    mine = _skills_for_user(db, user.telegram_id)
    if not mine["teach"] and not mine["learn"]:
        return {"matches": []}
    members = _skill_members(db, user.telegram_id)
    out = []
    for u, entries in members:
        if u.telegram_id == user.telegram_id:
            continue
        match = _skill_match(db, user.telegram_id, u.telegram_id)
        if not match["teach_for_me"] and not match["learn_from_me"]:
            continue
        row = _skill_member_out(u, entries)
        row["match"] = match
        out.append(row)
    return {"matches": out}


@app.post("/skills/{user_id}/connect")
async def connect_skill_member(user_id: int,
                              user: models.User = Depends(current_user),
                              db: Session = Depends(get_db)):
    """Connect — the other member is notified and the client
    opens a DM with them. No connect-requests table: the
    notification + the DM IS the connection (Blood's respond
    pattern). The swap itself (time, place, how) is arranged
    in that DM, never in the app."""
    _enforce_rate("skills", f"u{user.telegram_id}")
    if user_id == user.telegram_id:
        raise HTTPException(400, "You cannot connect with yourself")
    target = db.get(models.User, user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    if _blocked_by(db, user_id, user.telegram_id) or _blocked_by(
            db, user.telegram_id, user_id):
        raise HTTPException(403, "This member is not available")
    if not _can_see_posts(db, user.telegram_id, user_id):
        raise HTTPException(403, "This member is not available")
    if not db.query(models.SkillEntry).filter_by(
            user_id=user_id).first():
        raise HTTPException(400, "This member has no skills listed")
    match = _skill_match(db, user.telegram_id, user_id)
    parts = []
    if match["teach_for_me"]:
        parts.append("they teach " + ", ".join(match["teach_for_me"])
                     + " — you want to learn it")
    if match["learn_from_me"]:
        parts.append("they want to learn " + ", ".join(match["learn_from_me"])
                     + " — you teach it")
    detail = (" (" + "; ".join(parts) + ")") if parts else ""
    await notify.notify_user(
        db, user_id, "skill_connect",
        f"🤝 {user.first_name} wants to swap skills with you{detail}. "
        f"Open your chat with them to arrange it.")
    notify.record(db, user_id, "skill_connect",
                  actor_id=user.telegram_id,
                  text="wants to swap skills with you" + detail)
    return {"ok": True, "user_id": user_id, "match": match}


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


@app.post("/users/{telegram_id}/mute")
def toggle_mute(telegram_id: int,
                user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
    """Phase 174: mute is a one-way, silent hide. No notification
    is sent, follows stay as they are, DMs are untouched, and a
    blocked member stays hidden even if unmuted (block is checked
    separately everywhere mute is). The official account cannot
    be muted, mirroring the block rule."""
    if telegram_id == user.telegram_id:
        raise HTTPException(400, "You cannot mute yourself")
    if telegram_id == OFFICIAL_ID:
        raise HTTPException(
            400, "The official Nexora Social account cannot be muted")
    if db.get(models.User, telegram_id) is None:
        raise HTTPException(404, "User not found")
    existing = db.query(models.Mute).filter_by(
        muter_id=user.telegram_id, muted_id=telegram_id).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"muted": False}
    db.add(models.Mute(muter_id=user.telegram_id, muted_id=telegram_id))
    db.commit()
    return {"muted": True}


@app.get("/me/muted")
def my_muted(user: models.User = Depends(current_user),
             db: Session = Depends(get_db)):
    rows = db.query(models.Mute).filter_by(
        muter_id=user.telegram_id) \
        .order_by(models.Mute.id.desc()).limit(200).all()
    out = []
    for r in rows:
        mu = db.get(models.User, r.muted_id)
        out.append({
            "telegram_id": r.muted_id,
            "first_name": mu.first_name if mu else "",
            "username": mu.username if mu else None,
            "photo_file_id": mu.photo_file_id if mu else None,
        })
    return {"muted": out}


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
              db: Session = Depends(get_db), before: int = 0):
    # Phase 124: keyset paging for the points-history "Show more"
    # button — before=<oldest id seen> returns the next 20 older
    # rows; before=0 (default) is the latest 20, as before.
    me = db.get(models.User, user.telegram_id)
    q = db.query(models.PointsLedger).filter_by(user_id=user.telegram_id)
    if before > 0:
        q = q.filter(models.PointsLedger.id < before)
    rows = q.order_by(models.PointsLedger.id.desc()).limit(20).all()
    return {
        "balance": me.points_balance if me else 0,
        "entries": [{
            "id": e.id, "amount": e.amount, "reason": e.reason,
            "ref_id": e.ref_id,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e in rows],
    }


@app.get("/me/qr-token")
def my_qr_token(user: models.User = Depends(current_user)):
    """Phase 114: mint the caller's QR capability token."""
    return {"token": _qr_token(user.telegram_id)}


@app.get("/me/qr")
def my_qr(qt: str = ""):
    """Phase 114: the caller's branded profile QR as a PNG. The
    user-bound token in ?qt= is the auth (no header on <img>)."""
    user_id = _qr_token_ok(qt)
    if user_id is None:
        raise HTTPException(401, "Invalid QR token")
    if not settings.BOT_USERNAME:
        raise HTTPException(503, "Bot username is not configured")
    png = _build_profile_qr_png(_profile_link(user_id))
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=86400"})


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
        # Phase 179 (audit H7): the tag match is a DB-level
        # predicate now, not a fetch-newest-100-then-filter in
        # Python — a post with the tag older than the 100 newest
        # was silently unfindable. hashtags is a space-joined,
        # lowercased, deduped column (extract_hashtags), so the
        # tag must match a whole token: start, middle, end, or
        # alone — #art never matches #artist. LIKE wildcards in
        # the tag are escaped with "!" so "_" cannot match any
        # character. Muted authors are excluded too (the feed
        # and hashtag feed already were); private stays
        # follower-only (Phase 136).
        private_ids = _private_author_ids(db)
        followed = set()
        if private_ids:
            followed = {f.following_id for f in
                        db.query(models.Follow).filter_by(
                            follower_id=user.telegram_id)}
        muted = _muted_ids(db, user.telegram_id)
        esc = tag.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        col = models.Post.hashtags
        pred = or_(col == tag,
                   col.like(esc + " %", escape="!"),
                   col.like("% " + esc + " %", escape="!"),
                   col.like("% " + esc, escape="!"))
        rows = (db.query(models.Post).filter_by(is_deleted=False)
                .filter(pred)
                .order_by(models.Post.id.desc()).limit(100).all())
        matched = [p for p in rows
                   if p.user_id not in hidden
                   and p.user_id not in muted
                   and (p.user_id not in private_ids
                        or p.user_id in followed
                        or p.user_id == user.telegram_id)][:20]
        return {"users": [], "posts": _post_list(db, matched, user.telegram_id)}
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
    # Phase 179 (audit M4): 240/h per member — profile browsing
    # opens one list per profile view, far below this.
    _enforce_rate("user_posts", f"u{user.telegram_id}")
    # Phase 178 (audit H1): the guard was one-direction —
    # a viewer who blocked the target still got the full
    # post list. Both directions 404 now.
    if db.get(models.User, telegram_id) is None \
            or _blocked_by(db, telegram_id, user.telegram_id) \
            or _blocked_by(db, user.telegram_id, telegram_id):
        raise HTTPException(404, "User not found")
    # Phase 136: a private account's posts are locked to
    # non-followers — the list comes back empty with a flag.
    if telegram_id != user.telegram_id and not _can_see_posts(
            db, user.telegram_id, telegram_id):
        return {"posts": [], "next_cursor": None, "locked": True}
    # Phase 179 (audit M5): fetch-then-filter loop, as in
    # /feed — the cursor used to come from the pre-filter page,
    # so a page could return 0 posts with a non-null cursor when
    # post_dict dropped reposts of invisible originals. One row
    # past the page is kept as a peek: the cursor is non-null
    # ONLY when a 21st kept post exists. Ids strictly decrease,
    # so the loop always terminates. Page one still leads with
    # the pinned post (Phase 123); later pages exclude it, as
    # before.
    rows = []
    next_cursor = None
    last_examined = cursor
    exhausted = False
    while len(rows) < 21 and not exhausted:
        qq = db.query(models.Post).filter_by(
            user_id=telegram_id, is_deleted=False)
        if cursor == 0 and last_examined == 0:
            # Phase 123: the author's pinned post leads page one.
            qq = qq.order_by(models.Post.is_pinned.desc(),
                             models.Post.id.desc())
        else:
            # Later pages are plain newest-first, and the pinned
            # post (already shown first on page one) is excluded
            # so it never appears twice.
            qq = qq.filter(models.Post.id < last_examined,
                           models.Post.is_pinned == False)
            qq = qq.order_by(models.Post.id.desc())
        batch = qq.limit(20).all()
        if not batch:
            break
        if len(batch) < 20:
            exhausted = True
        for p in batch:
            last_examined = p.id
            if getattr(p, "repost_of_id", None):
                orig = db.get(models.Post, p.repost_of_id)
                if orig is None or orig.is_deleted:
                    continue
                if not _post_visible_to(db, user.telegram_id, orig):
                    continue
            rows.append(p)
            if len(rows) >= 21:
                break
    if len(rows) > 20:
        next_cursor = rows[19].id
        rows = rows[:20]
    counts = _post_view_counts(db, rows)
    _warm_authors(db, rows)
    return {"posts": _post_list(db, rows, user.telegram_id, counts=counts),
            "next_cursor": next_cursor}


@app.get("/leaderboard")
def leaderboard(user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
    # Phase 180 (audit M23): rank by LIFETIME points (positive
    # ledger sum) — the same figure the gate, levels and the
    # Members-browse sort use — not the spendable balance, so a
    # creator who cashes out a payout keeps their rank. Rank is
    # 1 + the count of members strictly above; ties share a rank
    # (in the top-50 list and in the outsider "me" rank alike).
    lifetime_sq = db.query(
        models.PointsLedger.user_id.label("uid"),
        func.coalesce(func.sum(models.PointsLedger.amount), 0).label(
            "pts")).filter(models.PointsLedger.amount > 0) \
        .group_by(models.PointsLedger.user_id).subquery()
    lp = func.coalesce(lifetime_sq.c.pts, 0)
    rows = db.query(models.User, lp.label("lifetime")) \
        .outerjoin(lifetime_sq,
                   lifetime_sq.c.uid == models.User.telegram_id) \
        .filter(models.User.is_banned == False) \
        .order_by(lp.desc(), models.User.telegram_id).limit(50).all()
    out = []
    for u, lifetime in rows:
        pts = int(lifetime or 0)
        rank = 1 + sum(1 for r in out if r["points"] > pts)
        out.append({"rank": rank, "telegram_id": u.telegram_id,
                    "first_name": u.first_name, "username": u.username,
                    "points": pts,
                    "is_verified": bool(u.is_verified),
                    "photo_file_id": u.photo_file_id})
    mine = next((r for r in out if r["telegram_id"] == user.telegram_id), None)
    if mine is None:
        my_points = _lifetime_points(db, user.telegram_id)
        higher = db.query(models.User).join(
            lifetime_sq,
            lifetime_sq.c.uid == models.User.telegram_id).filter(
            models.User.is_banned == False,
            lifetime_sq.c.pts > my_points).count()
        mine = {"rank": higher + 1, "telegram_id": user.telegram_id,
                "first_name": user.first_name, "username": user.username,
                "points": my_points,
                "is_verified": bool(user.is_verified),
                "photo_file_id": user.photo_file_id}
    return {"leaders": out, "me": mine}


# ---------------------------------------------------------------------------
# Daily tasks (owner request, Oct 31): small daily goals that pay points,
# each claimable ONCE per day. Progress is counted from today's real
# activity; the claim is guarded by the daily_claims unique row.
# ---------------------------------------------------------------------------

_DHAKA_TZ = ZoneInfo("Asia/Dhaka")


def _dhaka_now():
    """Now in Asia/Dhaka — the day the user experiences."""
    return datetime.now(_DHAKA_TZ)


def _today():
    """Phase 180 (audit M22): the daily boundary is Asia/Dhaka,
    not UTC. Returns (Dhaka ISO date, naive-UTC datetime of Dhaka
    midnight) — created_at rows are stored as naive UTC, so the
    cutoff is midnight-Dhaka expressed in UTC."""
    now = _dhaka_now()
    start_dhaka = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_dhaka.astimezone(timezone.utc).replace(tzinfo=None)
    return now.date().isoformat(), start_utc


def _record_follow_task_event(db, follower_id, target_id):
    """Phase 180 (audit M24): a durable follow record for the
    daily follow3 task. Follow rows are hard-deleted on unfollow,
    so counting them lets unfollow + re-follow re-farm the task;
    this row survives unfollow and is unique per (follower,
    target, day), so each distinct target counts once a day."""
    day, _ = _today()
    exists = db.query(models.TaskFollowEvent).filter_by(
        user_id=follower_id, target_id=target_id, day=day).first()
    if exists is None:
        db.add(models.TaskFollowEvent(
            user_id=follower_id, target_id=target_id, day=day))


def _task_progress(db, user_id, task, day, day_start, claimed):
    metric = task["metric"]
    if metric == "checkin":
        return 1 if claimed else 0
    if metric == "follows":
        # Phase 180 (audit M24): distinct targets followed today,
        # from the durable event rows — unfollow + re-follow the
        # same person cannot count twice.
        return db.query(models.TaskFollowEvent).filter_by(
            user_id=user_id, day=day).count()
    if metric == "comments":
        # Phase 180 (audit M24): commenting your own post does
        # not count — only comments on other members' posts.
        return db.query(models.Comment).join(
            models.Post, models.Comment.post_id == models.Post.id
        ).filter(models.Comment.user_id == user_id,
                 models.Comment.created_at >= day_start,
                 models.Post.user_id != user_id).count()
    if metric == "reactions":
        # Phase 180 (audit M24): liking your own post does not
        # count — only likes on other members' posts.
        return db.query(models.Like).join(
            models.Post, models.Like.post_id == models.Post.id
        ).filter(models.Like.user_id == user_id,
                 models.Like.created_at >= day_start,
                 models.Post.user_id != user_id).count()
    if metric == "ads":
        # Phase 180 (audit H14): paused while no ad provider is
        # live — no AdEvent row can unlock the task.
        if not ADS_PROVIDER_LIVE:
            return 0
        return db.query(models.AdEvent).filter(
            models.AdEvent.user_id == user_id,
            models.AdEvent.created_at >= day_start).count()
    return 0


def _checkin_streak(db, user_id):
    """Consecutive days with a check-in claim, ending today (or yesterday
    if today is not claimed yet — the streak is still alive until the day
    ends). One missed day breaks it: the count simply stops there."""
    days = {r[0] for r in db.query(models.DailyClaim.day).filter_by(
        user_id=user_id, task_key="checkin").all()}
    # Phase 180 (audit M22): the streak walks Dhaka dates, so a
    # 05:00-Dhaka Monday + 07:00-Dhaka Tuesday check-in keeps the
    # streak (UTC saw Sun 23:00 + Tue 01:00 and reset it).
    cur = _dhaka_now().date()
    if cur.isoformat() not in days:
        cur -= timedelta(days=1)
    streak = 0
    while cur.isoformat() in days:
        streak += 1
        cur -= timedelta(days=1)
    return streak


# Phase 137: Levels & badges — computed from data the app
# already has (lifetime points, post/follower counts,
# verification, join date, tips, check-in streak). Nothing is
# stored: a member's level and badges always reflect their
# current numbers.
LEVELS = (
    (0, "Newcomer"),
    (100, "Rising"),
    (500, "Active"),
    (1000, "Creator"),
    (2500, "Influencer"),
    (5000, "Star"),
    (10000, "Legend"),
    (20000, "Nexora Elite"),
)


def _lifetime_points(db, user_id):
    """Sum of positive ledger rows — the same figure the
    monetization gate and the Members sort use."""
    return int(db.query(func.coalesce(func.sum(
        models.PointsLedger.amount), 0)).filter(
        models.PointsLedger.user_id == user_id,
        models.PointsLedger.amount > 0).scalar() or 0)


def level_for(points):
    """Pure: lifetime points -> {level, name, points, next_level,
    progress}. L6 Star at 5000 deliberately matches the
    monetization gate's 5000 lifetime-points requirement."""
    points = max(0, int(points))
    idx = 0
    for i, (threshold, _name) in enumerate(LEVELS):
        if points >= threshold:
            idx = i
    threshold, name = LEVELS[idx]
    if idx + 1 < len(LEVELS):
        nxt_threshold, nxt_name = LEVELS[idx + 1]
        progress = (points - threshold) / (nxt_threshold - threshold)
        nxt = {"level": idx + 2, "name": nxt_name,
               "points_needed": nxt_threshold - points}
    else:
        progress = 1.0
        nxt = None
    return {"level": idx + 1, "name": name, "points": points,
            "next_level": nxt, "progress": round(progress, 4)}


# Badge catalogue: (id, icon, name, hint). Earned is computed per
# member in badges_for(); the list always shows locked badges too,
# greyed, with the requirement as the hint.
BADGE_DEFS = (
    ("first-post", "\U0001f4dd", "First Post", "Publish your first post"),
    ("25-posts", "\u270d\ufe0f", "25 Posts", "Publish 25 posts"),
    ("100-posts", "\U0001f525", "100 Posts", "Publish 100 posts"),
    ("500-followers", "\U0001f465", "500 Followers", "Reach 500 followers"),
    ("1000-followers", "\U0001f31f", "1000 Followers", "Reach 1000 followers"),
    ("verified", "\u2705", "Verified", "Earn the blue tick"),
    ("tips-10", "\u2b50", "10 Tips", "Receive 10 Stars tips"),
    ("streak-30", "\U0001f4c5", "30-Day Streak", "Check in 30 days in a row"),
    ("pioneer", "\U0001f680", "Pioneer", "Joined before Dec 2026"),
)


def badges_for(db, user):
    """Computed badges for one member. Counts use the same rules
    as the rest of the app: original posts only (no reposts), the
    displayed follower count (official account starts at 10,000),
    completed tips only, and the monetization gate's streak
    (computed from DailyClaim rows by _checkin_streak)."""
    posts = db.query(models.Post).filter_by(
        user_id=user.telegram_id, is_deleted=False).filter(
        models.Post.type != "repost").count()
    followers = db.query(models.Follow).filter_by(
        following_id=user.telegram_id).count()
    if user.telegram_id == OFFICIAL_ID:
        followers += OFFICIAL_FOLLOWER_BASE
    tips = db.query(models.Tip).filter_by(
        to_user_id=user.telegram_id, status="completed").count()
    streak = _checkin_streak(db, user.telegram_id)
    pioneer = bool(user.created_at) and \
        user.created_at < datetime(2026, 12, 1)
    earned = {
        "first-post": posts >= 1,
        "25-posts": posts >= 25,
        "100-posts": posts >= 100,
        "500-followers": followers >= 500,
        "1000-followers": followers >= 1000,
        "verified": bool(user.is_verified),
        "tips-10": tips >= 10,
        "streak-30": streak >= 30,
        "pioneer": pioneer,
    }
    return [{"id": bid, "icon": icon, "name": name, "hint": hint,
             "earned": earned[bid]}
            for bid, icon, name, hint in BADGE_DEFS]


def _level_and_badges(db, user):
    """One call for endpoints that show a member: level (from
    lifetime points) + computed badges."""
    return {"level": level_for(_lifetime_points(db, user.telegram_id)),
            "badges": badges_for(db, user)}


def _task_state(db, user, task):
    day, day_start = _today()
    claimed = db.query(models.DailyClaim).filter_by(
        user_id=user.telegram_id, task_key=task["key"], day=day).first()
    progress = _task_progress(db, user.telegram_id, task, day, day_start,
                              bool(claimed))
    # Phase 180 (audit H14): the ad task is unavailable while no
    # ad provider is live — it shows as unavailable in the client,
    # never claimable, whatever old AdEvent rows exist.
    available = not (task["metric"] == "ads" and not ADS_PROVIDER_LIVE)
    state = {
        "key": task["key"], "title": task["title"], "icon": task["icon"],
        "target": task["target"], "points": task["points"],
        "progress": min(progress, task["target"]),
        "claimed": bool(claimed),
        "claimable": available and (not claimed) and (
            task["metric"] == "checkin" or progress >= task["target"]),
        "available": available,
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
    try:
        db.add(models.DailyClaim(user_id=user.telegram_id, task_key=key,
                                 day=day))
        award_points(db, user.telegram_id, task["points"], f"task:{key}")
        db.commit()
    except IntegrityError:
        # Phase 180 (audit M26): two parallel claims race past the
        # check-then-insert above; the unique row saves the points,
        # and the loser gets the clean 400, not an unhandled 500.
        db.rollback()
        raise HTTPException(400, "Already claimed today")
    db.refresh(user)
    return {"ok": True, "points_awarded": task["points"],
            "balance": user.points_balance}


# ---------------------------------------------------------------------------
# Monetization gate (owner request, Oct 31): a creator unlocks monetization
# only after meeting every target in config.MONETIZATION. This endpoint is
# the status/checklist; payouts themselves are a later phase.
# ---------------------------------------------------------------------------

def _monetization_checks(db, user):
    """The six gate checks, shared by /me/monetization and the
    payout request (Phase 127) — one definition, so the gate can
    never drift between the two."""
    followers = db.query(models.Follow).filter_by(
        following_id=user.telegram_id).count()
    # Phase 58 (owner): a 6th gate target — QUALIFIED referrals
    # only (a referral qualifies when the new member posts,
    # the same rule that pays the referral points).
    referrals = db.query(models.Referral).filter_by(
        referrer_id=user.telegram_id, qualified=True).count()
    posts = db.query(models.Post).filter_by(
        user_id=user.telegram_id, is_deleted=False).filter(models.Post.type != "repost").count()
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
    return all(c["done"] for c in checks), checks


@app.get("/me/monetization")
def my_monetization(user: models.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    unlocked, checks = _monetization_checks(db, user)
    return {"unlocked": unlocked, "checks": checks}

# ---------------------------------------------------------------------------
# Phase 127: crypto payouts (owner, Nov 14). Monetization-unlocked
# members save a wallet (TON / Gram / USDT), request a payout in
# points — one pending request at a time — and the admin reviews it:
# approve (sets the crypto amount, points leave the balance), reject,
# then mark paid with the transaction reference once the crypto is
# sent manually. NO points->money rate is hardcoded anywhere; the
# admin sets the amount at approval from real income.
# ---------------------------------------------------------------------------


class WalletIn(BaseModel):
    network: str = ""
    address: str = ""


class PayoutRequestIn(BaseModel):
    points: int = 0


class PayoutDecideIn(BaseModel):
    action: str = ""
    amount: Optional[str] = None
    currency: Optional[str] = None


class PayoutPaidIn(BaseModel):
    tx_ref: str = ""


def _payout_dict(req, user=None):
    return {
        "id": req.id,
        "user_id": req.user_id,
        "first_name": user.first_name if user else None,
        "username": user.username if user else None,
        "wallet_address": req.wallet_address,
        "wallet_network": req.wallet_network,
        "points": req.points,
        "status": req.status,
        "amount": req.amount,
        "currency": req.currency,
        "tx_ref": req.tx_ref,
        "requested_at": req.requested_at.isoformat()
            if req.requested_at else None,
        "decided_at": req.decided_at.isoformat()
            if req.decided_at else None,
        "decided_by": req.decided_by,
        "paid_at": req.paid_at.isoformat() if req.paid_at else None,
    }


def _ledger_balance(db, user_id):
    """Spendable points, summed from the ledger (the same aggregate
    style the monetization endpoint uses) — the single source of
    truth for payout checks."""
    return db.query(func.coalesce(func.sum(
        models.PointsLedger.amount), 0)).filter(
        models.PointsLedger.user_id == user_id).scalar() or 0


@app.post("/me/wallet")
def save_wallet(body: WalletIn,
                user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
    network = (body.network or "").strip()
    address = (body.address or "").strip()
    if network not in PAYOUT_NETWORKS:
        raise HTTPException(400, "Network must be TON, Gram or USDT")
    if not address or len(address) > 256:
        raise HTTPException(
            400, "Enter your wallet address (max 256 characters)")
    user.wallet_network = network
    user.wallet_address = address
    db.commit()
    return {"ok": True, "wallet_network": network,
            "wallet_address": address}


@app.get("/me/wallet")
def my_wallet(user: models.User = Depends(current_user)):
    return {"wallet_network": user.wallet_network,
            "wallet_address": user.wallet_address}


@app.post("/me/payout/request")
def request_payout(body: PayoutRequestIn,
                   user: models.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    _enforce_rate("payout", str(user.telegram_id))
    points = body.points or 0
    if points <= 0:
        raise HTTPException(400, "Points must be more than 0")
    if not user.wallet_address or not user.wallet_network:
        raise HTTPException(400, "Save your crypto wallet first")
    unlocked, _checks = _monetization_checks(db, user)
    if not unlocked:
        raise HTTPException(
            403, "Monetization is locked — meet every target first")
    if points > _ledger_balance(db, user.telegram_id):
        raise HTTPException(400, "Not enough points for that payout")
    pending = db.query(models.PayoutRequest).filter_by(
        user_id=user.telegram_id, status="pending").first()
    if pending is not None:
        raise HTTPException(
            400, "You already have a payout request waiting")
    req = models.PayoutRequest(
        user_id=user.telegram_id,
        wallet_address=user.wallet_address,
        wallet_network=user.wallet_network,
        points=points, status="pending")
    db.add(req)
    db.commit()
    db.refresh(req)
    return _payout_dict(req, user)


@app.get("/me/payouts")
def my_payouts(user: models.User = Depends(current_user),
               db: Session = Depends(get_db)):
    rows = db.query(models.PayoutRequest).filter_by(
        user_id=user.telegram_id).order_by(
        models.PayoutRequest.id.desc()).limit(50).all()
    return {"requests": [_payout_dict(r, user) for r in rows]}


# ---------------------------------------------------------------------------
# Phase 133: Telegram Stars tipping — a member tips a creator with
# Stars. A Mini App cannot take a Stars payment itself, so the flow
# is: the app asks the bot to send an XTR invoice into the tipper's
# Telegram chat; the tipper pays there; the bot's PreCheckoutQuery
# + successful_payment handlers record the tip. A tip row exists
# ONLY once the payment has landed — never at invoice time. Stars
# land in the BOT's Stars balance (the owner withdraws them via
# BotFather/Fragment); the app tracks per-creator totals so the
# admin knows who earned what. Paying creators out reuses the
# Phase 127 crypto payout flow — this phase builds no Stars-to-
# creator transfer.
# ---------------------------------------------------------------------------


def _tip_payload(from_id, to_id, post_id, amount):
    """Phase 133: tip:<from>:<to>:<post>:<amount> — post 0 means
    the tip was on a profile, not a post."""
    return f"tip:{from_id}:{to_id}:{post_id or 0}:{amount}"


class TipCreateIn(BaseModel):
    post_id: Optional[int] = None
    user_id: Optional[int] = None
    amount_stars: int = 0


@app.post("/tips/create")
async def create_tip(body: TipCreateIn,
                     user: models.User = Depends(current_user),
                     db: Session = Depends(get_db)):
    _enforce_rate("tip", f"u{user.telegram_id}")
    amount = body.amount_stars or 0
    if not 1 <= amount <= 10000:
        raise HTTPException(400, "Tip must be 1–10000 Stars")
    if bool(body.post_id) == bool(body.user_id):
        raise HTTPException(400, "Tip a post or a member, not both")
    post_id = None
    if body.post_id:
        post = db.get(models.Post, body.post_id)
        if post is None or post.is_deleted:
            raise HTTPException(404, "Unknown post")
        # A repost card tips the ORIGINAL author, not the reposter.
        orig = db.get(models.Post, _eff_id(post))
        if orig is None or orig.is_deleted:
            raise HTTPException(404, "Unknown post")
        to_id = orig.user_id
        post_id = orig.id
    else:
        target = db.get(models.User, body.user_id)
        if target is None:
            raise HTTPException(404, "Unknown member")
        if target.is_banned:
            raise HTTPException(400, "That member is unavailable")
        to_id = target.telegram_id
    to_user = db.get(models.User, to_id)
    to_name = to_user.first_name if to_user else "Nexora member"
    if to_id == user.telegram_id:
        raise HTTPException(400, "You cannot tip yourself")
    if _blocked_by(db, user.telegram_id, to_id) or _blocked_by(
            db, to_id, user.telegram_id):
        raise HTTPException(403, "You cannot tip this member")
    if _bot_app is None:
        raise HTTPException(
            503, "Tip invoices are unavailable right now")
    payload = _tip_payload(user.telegram_id, to_id, post_id, amount)
    title = f"Tip for {to_name}"
    desc = (f"Send {amount} Telegram Stars to {to_name} on "
            "Nexora Social"
            + (f" for post #{post_id}." if post_id else "."))
    try:
        await _bot_app.bot.send_invoice(
            chat_id=user.telegram_id, title=title, description=desc,
            payload=payload, currency="XTR",
            prices=[LabeledPrice("Tip", amount)])
    except Exception:
        raise HTTPException(
            503, "Could not send the invoice — try again")
    return {"invoice": True, "amount_stars": amount,
            "to_name": to_name,
            "bot_username": settings.BOT_USERNAME}


def _tip_dict(t, db):
    frm = db.get(models.User, t.from_user_id)
    to = db.get(models.User, t.to_user_id)
    return {
        "id": t.id,
        "from_user_id": t.from_user_id,
        "from_name": frm.first_name if frm else None,
        "to_user_id": t.to_user_id,
        "to_name": to.first_name if to else None,
        "post_id": t.post_id,
        "amount_stars": t.amount_stars,
        "created_at": t.created_at.isoformat()
            if t.created_at else None,
    }


@app.get("/me/tips")
def my_tips(user: models.User = Depends(current_user),
            db: Session = Depends(get_db)):
    sent = db.query(models.Tip).filter_by(
        from_user_id=user.telegram_id).order_by(
        models.Tip.id.desc()).limit(50).all()
    received = db.query(models.Tip).filter_by(
        to_user_id=user.telegram_id).order_by(
        models.Tip.id.desc()).limit(50).all()
    return {"sent": [_tip_dict(t, db) for t in sent],
            "received": [_tip_dict(t, db) for t in received]}


@app.get("/users/{telegram_id}/tips")
def user_tips(telegram_id: int, db: Session = Depends(get_db)):
    """Public tip totals for a profile — the total and the
    count, plus recent tippers' names (no per-tip amounts)."""
    total = db.query(func.coalesce(
        func.sum(models.Tip.amount_stars), 0)).filter(
        models.Tip.to_user_id == telegram_id).scalar() or 0
    count = db.query(models.Tip).filter_by(
        to_user_id=telegram_id).count()
    rows = db.query(models.Tip).filter_by(
        to_user_id=telegram_id).order_by(
        models.Tip.id.desc()).limit(10).all()
    recent = []
    for t in rows:
        frm = db.get(models.User, t.from_user_id)
        recent.append({
            "from_name": frm.first_name if frm else None,
            "created_at": t.created_at.isoformat()
                if t.created_at else None,
        })
    return {"telegram_id": telegram_id,
            "total_stars_received": int(total),
            "tip_count": count, "recent": recent}


# ---------------------------------------------------------------------------
# Phase 134: post insights (creator analytics). Everything is
# computed from existing tables — PostView / Like / Comment /
# Tip all carry created_at, so the 14-day daily series is exact.
# (Views are UNIQUE views: one PostView row per viewer, so a
# viewer counts on the day they first saw the post.)
# ---------------------------------------------------------------------------

def _insights_daily(db, post_id, start):
    """Per-day {views, likes, comments} for the 14 days from
    `start` (a UTC date) — days with no activity get zeros."""
    days = [start + timedelta(days=i) for i in range(14)]
    out = {d: {"date": d.isoformat(), "views": 0, "likes": 0,
               "comments": 0} for d in days}
    start_dt = datetime(start.year, start.month, start.day)
    for model, key in ((models.PostView, "views"),
                       (models.Like, "likes"),
                       (models.Comment, "comments")):
        for (ts,) in db.query(model.created_at).filter(
                model.post_id == post_id,
                model.created_at >= start_dt).all():
            if ts is None:
                continue
            d = ts.date()
            if d in out:
                out[d][key] += 1
    return [out[d] for d in days]


def _post_insights_totals(db, post):
    """All-time totals for one post (by original id)."""
    pid = post.id
    return {
        "views": db.query(models.PostView).filter_by(
            post_id=pid).count(),
        "likes": db.query(models.Like).filter_by(
            post_id=pid).count(),
        "comments": db.query(models.Comment).filter_by(
            post_id=pid).count(),
        "reposts": post.repost_count or 0,
        "tips_stars": int(db.query(func.coalesce(
            func.sum(models.Tip.amount_stars), 0)).filter(
            models.Tip.post_id == pid).scalar() or 0),
        "tips_count": db.query(models.Tip).filter_by(
            post_id=pid).count(),
    }


@app.get("/posts/{post_id}/insights")
def post_insights(post_id: int,
                  user: models.User = Depends(current_user),
                  db: Session = Depends(get_db)):
    """Author-only analytics for one post: all-time totals +
    the last 14 days of daily views/likes/comments (UTC dates,
    newest last) + the best (highest-view) day."""
    _enforce_rate("insights", f"u{user.telegram_id}")
    p = db.get(models.Post, post_id)
    if p is None or p.is_deleted:
        raise HTTPException(404, "Post not found")
    eff_id = p.repost_of_id or p.id
    eff = db.get(models.Post, eff_id) if eff_id != p.id else p
    if eff is None or eff.is_deleted:
        raise HTTPException(404, "Post not found")
    if eff.user_id != user.telegram_id:
        raise HTTPException(403, "Only the author can see insights")
    totals = _post_insights_totals(db, eff)
    today = datetime.utcnow().date()
    daily = _insights_daily(db, eff_id, today - timedelta(days=13))
    best = None
    for d in daily:
        if d["views"] and (best is None or d["views"] > best["views"]):
            best = {"date": d["date"], "views": d["views"]}
    return {"post_id": eff_id, "totals": totals,
            "best_day": best, "daily": daily}


@app.get("/me/insights")
def my_insights(user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
    """The author's own overview: totals across their original
    posts + the top 5 posts by views."""
    _enforce_rate("insights", f"u{user.telegram_id}")
    mine = db.query(models.Post).filter(
        models.Post.user_id == user.telegram_id,
        models.Post.is_deleted == False,
        models.Post.type != "repost").all()
    ids = [p.id for p in mine]

    def _counts(model):
        if not ids:
            return {}
        rows = db.query(model.post_id, func.count()).filter(
            model.post_id.in_(ids)).group_by(model.post_id).all()
        return {pid: n for pid, n in rows}

    views = _counts(models.PostView)
    likes = _counts(models.Like)
    comments = _counts(models.Comment)
    totals = {
        "views": sum(views.values()),
        "likes": sum(likes.values()),
        "comments": sum(comments.values()),
        "posts": len(mine),
        "tips_stars": int(db.query(func.coalesce(
            func.sum(models.Tip.amount_stars), 0)).filter(
            models.Tip.to_user_id == user.telegram_id).scalar() or 0),
    }
    top = sorted(mine, key=lambda p: views.get(p.id, 0),
                 reverse=True)[:5]
    return {"totals": totals,
            "top_posts": [{"id": p.id,
                           "caption_excerpt": (p.caption or "")[:60],
                           "views": views.get(p.id, 0),
                           "likes": likes.get(p.id, 0),
                           "comments": comments.get(p.id, 0)}
                          for p in top]}


@app.get("/posts/{post_id}")
def get_post(post_id: int,
             user: models.User = Depends(current_user),
             db: Session = Depends(get_db)):
    # Phase 179 (audit M4): "post_read" budget, shared with
    # GET /posts/{id}/comments — a single-post view per tap.
    _enforce_rate("post_read", f"u{user.telegram_id}")
    """One post as a feed-shaped card (Phase 134: the My-insights
    top-posts tap target — the app has no single-post view, so
    the card itself is the view). Any signed-in member may read
    a post; a deleted post or a gone original is a 404."""
    p = db.get(models.Post, post_id)
    if p is None or p.is_deleted:
        raise HTTPException(404, "Post not found")
    # Phase 136: a private account's post — even via a repost —
    # is visible only to its followers and itself.
    eff_id = p.repost_of_id or p.id
    eff = db.get(models.Post, eff_id) if eff_id != p.id else p
    if eff is None or eff.is_deleted:
        raise HTTPException(404, "Post not found")
    # Phase 178 (audit H1): a blocked author's post 404s for
    # both sides — the blocker and the blocked — same as a
    # deleted post. Checked before the private rule so a
    # blocked private author 404s instead of 403ing.
    if (_blocked_by(db, eff.user_id, user.telegram_id)
            or _blocked_by(db, user.telegram_id, eff.user_id)):
        raise HTTPException(404, "Post not found")
    if not _can_see_posts(db, user.telegram_id, eff.user_id):
        raise HTTPException(403, "This account is private")
    counts = _post_view_counts(db, [p])
    out = _post_list(db, [p], user.telegram_id, counts=counts)
    if not out:
        raise HTTPException(404, "Post not found")
    return out[0]




# ---------------------------------------------------------------------------
# Phase 176 — Public post link: a shareable page outside Telegram.
#
# GET /p/{post_id} serves a lightweight public HTML page (no auth)
# with Open Graph meta + the post content + an "Open in Nexora"
# button. Privacy is the point: deleted posts 404; private-account
# posts show only a generic notice; and when the opener is
# identified (a valid Telegram X-Init-Data header — the page opened
# from inside the app), a post by an author who blocked that viewer
# also shows only the notice. An anonymous browser carries no
# identity, so no block can be checked for it — the page never
# exposes media (post photos live behind the authenticated,
# user-bound /media token) or any API data beyond the single post:
# no counts, no comments, no usernames.
# ---------------------------------------------------------------------------


def _public_base_url():
    """Phase 176: the app origin for public links (WEBAPP_URL is
    the /webapp/ URL; /p/ lives at the origin)."""
    base = (settings.WEBAPP_URL or "").rstrip("/")
    if base.endswith("/webapp"):
        base = base[: -len("/webapp")]
    return base


def _public_page_html(*, title, description, body, post_url, image_url):
    """Phase 176: one tiny page shell for /p/{id} — everything
    user-supplied arrives already escaped."""
    return ("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{title}</title>"
            f"<meta name=\"description\" content=\"{description}\">"
            "<meta property=\"og:type\" content=\"website\">"
            f"<meta property=\"og:title\" content=\"{title}\">"
            f"<meta property=\"og:description\" content=\"{description}\">"
            f"<meta property=\"og:image\" content=\"{image_url}\">"
            f"<meta property=\"og:url\" content=\"{post_url}\">"
            "<style>body{font-family:system-ui,sans-serif;margin:0;"
            "background:#F6F1E7;color:#3A2E33;padding:24px 16px;}"
            ".card{max-width:560px;margin:0 auto;background:#fff;"
            "border-radius:16px;padding:20px;box-shadow:0 2px 12px rgba(0,0,0,.08);}"
            "h1{font-size:18px;margin:0 0 4px}.meta{color:#888;font-size:13px;"
            "margin-bottom:12px}p{white-space:pre-wrap;line-height:1.5;}"
            ".btn{display:inline-block;margin-top:16px;background:#3E8FD0;"
            "color:#fff;padding:10px 18px;border-radius:999px;"
            "text-decoration:none;font-weight:700}</style></head><body>"
            f"<div class=\"card\">{body}</div></body></html>")


def _open_in_nexora_button(post_id):
    bot = settings.BOT_USERNAME or "NexoraSocial_bot"
    href = f"https://t.me/{bot}?start=post_{post_id}"
    return f"<a class=\"btn\" href=\"{href}\">Open in Nexora</a>"


def _public_not_found(post_id, post_url, image_url):
    return HTMLResponse(
        content=_public_page_html(
            title="Nexora Social", description="Post not found.",
            body=("<h1>Post not found.</h1><p>This post may have "
                  "been deleted.</p>"
                  + _open_in_nexora_button(post_id)),
            post_url=post_url, image_url=image_url),
        status_code=404)


def _public_notice(post_id, post_url, image_url):
    return HTMLResponse(content=_public_page_html(
        title="Nexora Social", description="This post isn't public.",
        body=("<h1>This post isn't public.</h1>"
              "<p>The post may have been deleted, or its author "
              "keeps it private.</p>"
              + _open_in_nexora_button(post_id)),
        post_url=post_url, image_url=image_url))


@app.get("/p/{post_id}")
def public_post_page(post_id: int, request: Request,
                     x_init_data: str = Header(default=""),
                     db: Session = Depends(get_db)):
    """Phase 176: the public post page (see the block comment above)."""
    base = _public_base_url()
    post_url = (base + f"/p/{post_id}") if base else f"/p/{post_id}"
    image_url = (base + "/webapp/og-image.png") if base \
        else "/webapp/og-image.png"
    p = db.get(models.Post, post_id)
    if p is None or p.is_deleted:
        return _public_not_found(post_id, post_url, image_url)
    eff = db.get(models.Post, p.repost_of_id) \
        if getattr(p, "repost_of_id", None) else p
    if eff is None or eff.is_deleted:
        return _public_not_found(post_id, post_url, image_url)
    author = db.get(models.User, eff.user_id)
    if author is None:
        return _public_not_found(post_id, post_url, image_url)
    viewer_id = None
    if x_init_data:
        # Phase 179 (audit M3): a PRESENT-but-invalid/expired
        # header is a 401, not a silent fall back to anonymous —
        # a forged or stale identity must not degrade to the
        # anonymous path. An ABSENT header stays anonymous
        # (public browsers carry no identity).
        tg = validate_init_data(x_init_data, settings.BOT_TOKEN)
        if tg is None:
            raise HTTPException(401, "Invalid Telegram login")
        viewer_id = tg.get("id")
    if not _can_see_posts(db, viewer_id or -1, author.telegram_id):
        return _public_notice(post_id, post_url, image_url)
    # Phase 177: either block direction hides the post on the
    # public page — a viewer who blocked the author sees the
    # notice too, same as an author who blocked the viewer.
    if viewer_id and (_blocked_by(db, author.telegram_id, viewer_id)
                      or _blocked_by(db, viewer_id, author.telegram_id)):
        return _public_notice(post_id, post_url, image_url)
    # Phase 179 (audit M3): an identified viewer who muted the
    # author gets the generic notice too — mute hides the post
    # for the muter on every surface, including this one.
    if viewer_id and _muted_by(db, viewer_id, author.telegram_id):
        return _public_notice(post_id, post_url, image_url)
    name = html.escape(author.first_name or "Nexora member")
    caption = html.escape(eff.caption or "")
    desc = (caption[:197] + "…") if len(caption) > 200 else caption
    if not desc:
        desc = "A post on Nexora Social"
    body = (f"<h1>{name} on Nexora Social</h1>"
            "<p class=\"meta\">Nexora Social</p>"
            f"<p>{caption.replace(chr(10), '<br>')}</p>"
            + _open_in_nexora_button(post_id))
    return HTMLResponse(content=_public_page_html(
        title=f"{name} on Nexora Social", description=desc,
        body=body, post_url=post_url, image_url=image_url))


@app.get("/posts/{post_id}/share-link")
def post_share_link(post_id: int,
                    user: models.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    """Phase 176: the public URL for a post the caller may see
    (same visibility as GET /posts/{id}: deleted 404, private 403)."""
    p = db.get(models.Post, post_id)
    if p is None or p.is_deleted:
        raise HTTPException(404, "Post not found")
    eff_id = p.repost_of_id or p.id
    eff = db.get(models.Post, eff_id) if eff_id != p.id else p
    if eff is None or eff.is_deleted:
        raise HTTPException(404, "Post not found")
    if not _can_see_posts(db, user.telegram_id, eff.user_id):
        raise HTTPException(403, "This account is private")
    base = _public_base_url()
    url = (base + f"/p/{p.id}") if base else f"/p/{p.id}"
    return {"share_link": url}


# ---------------------------------------------------------------------------
# Phase 22: verification (blue tick) applications. Phase 117
# (owner): TWO conditions, either one qualifies — 50 QUALIFIED
# referrals or 1,000 followers. The admin reviews applications in
# the Admin Panel.
# ---------------------------------------------------------------------------

def _followers_count(db, telegram_id):
    return db.query(models.Follow).filter_by(
        following_id=telegram_id).count()


def _qualified_referrals_count(db, telegram_id):
    # Phase 117: the monetization gate's definition — a referral
    # qualifies only once the referred member has posted.
    return db.query(models.Referral).filter_by(
        referrer_id=telegram_id, qualified=True).count()


def _verification_met(db, telegram_id):
    followers = _followers_count(db, telegram_id)
    referrals = _qualified_referrals_count(db, telegram_id)
    met = []
    if followers >= VERIFICATION_MIN_FOLLOWERS:
        met.append("followers")
    if referrals >= VERIFICATION_MIN_REFERRALS:
        met.append("referrals")
    return followers, referrals, met


def _pending_verification(db, telegram_id):
    return db.query(models.VerificationRequest).filter_by(
        user_id=telegram_id, status="pending") \
        .order_by(models.VerificationRequest.id.desc()).first()


@app.get("/me/verification")
def my_verification(user: models.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    followers, referrals, met = _verification_met(
        db, user.telegram_id)
    latest = db.query(models.VerificationRequest).filter_by(
        user_id=user.telegram_id) \
        .order_by(models.VerificationRequest.id.desc()).first()
    pending = latest if latest and latest.status == "pending" else None
    return {
        "followers": followers,
        "required": VERIFICATION_MIN_FOLLOWERS,
        "referrals": referrals,
        "referrals_required": VERIFICATION_MIN_REFERRALS,
        "met": met,
        "is_verified": bool(user.is_verified),
        "pending": pending is not None,
        "last_status": latest.status if latest else None,
        "can_apply": (not user.is_verified and pending is None
                      and bool(met)),
    }


@app.post("/me/verification/apply")
def apply_verification(user: models.User = Depends(current_user),
                       db: Session = Depends(get_db)):
    if user.is_verified:
        raise HTTPException(400, "Your account is already verified")
    followers, referrals, met = _verification_met(
        db, user.telegram_id)
    if not met:
        raise HTTPException(
            400, f"You need {VERIFICATION_MIN_FOLLOWERS} followers or "
                 f"{VERIFICATION_MIN_REFERRALS} referrals to apply for "
                 f"the blue tick (you have {followers} followers and "
                 f"{referrals} referrals)")
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
    and double-fires must not inflate the owner's ad figures).

    Phase 180 (audit H14): while no ad provider is live (AdsGram
    declined), a bare client POST must NOT create a point-unlocking
    AdEvent — 410 Gone, nothing recorded. The rate budget still
    runs first, so the budget wiring stays provable. The endpoint
    and the AdEvent model stay for a provider's return."""
    _enforce_rate("ad_shown", f"u{user.telegram_id}")
    if not ADS_PROVIDER_LIVE:
        raise HTTPException(410, "Ads are not available right now")
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
    "follow_request": "wants to follow you",
    "share": "shared a post with you",
    "repost": "reposted your post",
    "reply": "replied to your comment",
    "tip": "tipped you ⭐",
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

# Phase 164 (H1): admin step-up — a stolen initData stays dangerous
# for 24h, so MUTATING admin calls need fresh proof the owner just
# opened the app: auth_date within the last 5 minutes. Read-only
# admin calls keep the 24h window. Automated server-side jobs (the
# Phase 141 auto-backup loop, the scheduled-post sweeper) never go
# through HTTP, so this cannot lock them out.
ADMIN_STEP_UP_SECONDS = 300


def _require_admin_fresh(request, x_init_data: str, force=False):
    """Raise 401 when a sensitive admin request rides on stale
    initData. The client surfaces the detail and the admin reopens
    the app for a fresh initData. `force` covers secret-revealing
    GETs (the TOTP setup endpoint) where the method alone does not
    convey the sensitivity."""
    method = getattr(request, "method", "GET") or "GET"
    if not force and method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    auth_date = init_data_auth_date(x_init_data)
    if auth_date is None or int(time.time()) - auth_date > ADMIN_STEP_UP_SECONDS:
        raise HTTPException(
            401, "Admin session is older than 5 minutes — please close "
                 "and reopen the app, then try again")


# Phase 164 (H1): per-admin TOTP verification flags — in-memory,
# 12 hours per verified code. Single instance only (same assumption
# as the rate limiter); a restart simply asks for the code again.
_TOTP_VERIFIED = {}
_TOTP_VERIFIED_LOCK = threading.Lock()
_TOTP_SESSION_SECONDS = 12 * 3600


def _totp_verified(user_id: int) -> bool:
    with _TOTP_VERIFIED_LOCK:
        until = _TOTP_VERIFIED.get(user_id)
    return bool(until and until > time.time())


def _totp_mark_verified(user_id: int):
    with _TOTP_VERIFIED_LOCK:
        _TOTP_VERIFIED[user_id] = time.time() + _TOTP_SESSION_SECONDS


def _admin_check(user: models.User):
    if user.telegram_id not in settings.ADMIN_IDS:
        sec_log.warning("admin route denied for user %s",
                        user.telegram_id)
        log_security_event(None, "admin_denied",
                           actor_id=user.telegram_id,
                           detail="Admin route denied")
        raise HTTPException(403, "Admins only")
    return user


def admin_user(user: models.User = Depends(current_user),
               request: Request = None,
               x_init_data: str = Header(default="")):
    _admin_check(user)
    # Phase 164 (H1): when an authenticator secret is configured,
    # admin calls need a verified TOTP code for this session.
    if getattr(settings, "ADMIN_TOTP_SECRET", ""):
        if not _totp_verified(user.telegram_id):
            raise HTTPException(
                403, "Admin verification required — enter the code "
                     "from your authenticator app")
    if request is not None:
        _require_admin_fresh(request, x_init_data)
    return user


def admin_user_bootstrap(user: models.User = Depends(current_user),
                         request: Request = None,
                         x_init_data: str = Header(default="")):
    """Admin check + step-up WITHOUT the TOTP gate — used only by
    the TOTP status/setup/verify endpoints themselves, so the owner
    can never lock himself out of enrolling."""
    _admin_check(user)
    if request is not None:
        _require_admin_fresh(request, x_init_data)
    return user


def moderator_user(user: models.User = Depends(current_user),
                   request: Request = None,
                   x_init_data: str = Header(default="")):
    """Phase 28 (M1, least privilege): moderators get the moderation
    subset only — reports, comment/post removal, bans. Points, verify
    grants, profile edits, member deletion, broadcasts, managed
    users and verification decisions stay ADMIN_IDS-only."""
    if user.telegram_id not in settings.ADMIN_IDS \
            and user.telegram_id not in settings.MODERATOR_IDS:
        sec_log.warning("moderator route denied for user %s",
                        user.telegram_id)
        log_security_event(None, "admin_denied",
                           actor_id=user.telegram_id,
                           detail="Moderator route denied")
        raise HTTPException(403, "Moderators only")
    if request is not None:
        _require_admin_fresh(request, x_init_data)
    return user


class TotpVerifyIn(BaseModel):
    code: str = Field(default="", max_length=16)


@app.get("/admin/totp/status")
def admin_totp_status(admin: models.User = Depends(admin_user_bootstrap)):
    """Phase 164 (H1): is authenticator verification configured,
    and is this admin verified for the session?"""
    configured = bool(getattr(settings, "ADMIN_TOTP_SECRET", ""))
    return {"configured": configured,
            "verified": _totp_verified(admin.telegram_id) if configured else True}


@app.get("/admin/totp/setup")
def admin_totp_setup(request: Request,
                     x_init_data: str = Header(default=""),
                     admin: models.User = Depends(admin_user_bootstrap)):
    """Phase 164 (H1): enrollment — returns the otpauth URL for the
    env-stored secret so the owner can add it to his authenticator
    app. A secret-revealing GET, so it needs fresh initData even
    though it is a GET."""
    secret = getattr(settings, "ADMIN_TOTP_SECRET", "")
    if not secret:
        raise HTTPException(
            400, "Authenticator verification is not set up — set "
                 "ADMIN_TOTP_SECRET in Render first")
    _require_admin_fresh(request, x_init_data, force=True)
    import pyotp
    uri = pyotp.TOTP(secret).provisioning_uri(
        name="Nexora Admin", issuer_name="Nexora Social")
    return {"otpauth_url": uri, "secret": secret}


@app.post("/admin/totp/verify")
def admin_totp_verify(body: TotpVerifyIn,
                      admin: models.User = Depends(admin_user_bootstrap),
                      db: Session = Depends(get_db)):
    """Phase 164 (H1): check one TOTP code; success marks this admin
    verified for 12 hours (in-memory, per process)."""
    secret = getattr(settings, "ADMIN_TOTP_SECRET", "")
    if not secret:
        raise HTTPException(400, "Authenticator verification is not set up")
    import pyotp
    code = (body.code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "Enter the 6-digit code")
    if not pyotp.TOTP(secret).verify(code, valid_window=1):
        sec_log.warning("totp verify failed for admin %s", admin.telegram_id)
        log_security_event(db, "auth_reject", actor_id=admin.telegram_id,
                           detail="TOTP code rejected")
        raise HTTPException(400, "Wrong code — try again")
    _totp_mark_verified(admin.telegram_id)
    _audit(db, admin, "totp_verified", detail="Admin TOTP verified")
    db.commit()
    return {"verified": True}


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
        # Phase 119 (Control Panel Overview): designs + pending
        # blue-tick applications, so the panel nav shows live counts.
        "designs": db.query(models.Design).count(),
        "pending_verifications": db.query(models.VerificationRequest)
            .filter_by(status="pending").count(),
        # Phase 127: pending payout requests, for the nav badge.
        "pending_payouts": db.query(models.PayoutRequest)
            .filter_by(status="pending").count(),
    }


# Phase 129: Members browse — the Members section was search-only.
# Without `q` the endpoint now browses: sort (points|followers|
# joined|name), order (desc|asc), filter (all|verified|banned),
# limit (default 20, max 100) + offset paging, with `total` and
# `next_offset`. Search mode (q present) is byte-identical to
# before: same dicts, no total/next_offset. Points sort uses
# lifetime points (sum of positive ledger rows — the same figure
# the admin detail and monetization gate use), not the balance.
_BROWSE_SORTS = ("points", "followers", "joined", "name")
_BROWSE_FILTERS = ("all", "verified", "banned")


@app.get("/admin/users")
def admin_users(q: str = "", limit: Optional[int] = None, managed: int = 0,
                sort: str = "points", order: str = "desc",
                filter: str = "all", offset: int = 0,
                admin: models.User = Depends(admin_user),
                db: Session = Depends(get_db)):
    def _user_dict(u):
        return {
            "telegram_id": u.telegram_id, "first_name": u.first_name,
            "username": u.username, "is_banned": bool(u.is_banned),
            "is_verified": bool(u.is_verified), "points": u.points_balance,
            "is_managed": bool(u.is_managed),
            "country": u.country, "language_code": u.language_code,
            "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }

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
            .limit(max(1, min(limit if limit is not None else 50, 100))).all()
        return {"users": [_user_dict(u) for u in rows]}

    if sort not in _BROWSE_SORTS:
        raise HTTPException(400, "Unknown sort")
    if order not in ("desc", "asc"):
        raise HTTPException(400, "Unknown order")
    if filter not in _BROWSE_FILTERS:
        raise HTTPException(400, "Unknown filter")
    limit = max(1, min(limit if limit is not None else 20, 100))
    offset = max(0, offset)
    lifetime_sq = db.query(
        models.PointsLedger.user_id.label("uid"),
        func.coalesce(func.sum(models.PointsLedger.amount), 0).label("pts")) \
        .filter(models.PointsLedger.amount > 0) \
        .group_by(models.PointsLedger.user_id).subquery()
    followers_sq = db.query(
        models.Follow.following_id.label("uid"),
        func.count().label("cnt")) \
        .group_by(models.Follow.following_id).subquery()
    lp = func.coalesce(lifetime_sq.c.pts, 0)
    fc = func.coalesce(followers_sq.c.cnt, 0)
    bquery = db.query(models.User, lp.label("lifetime_points"),
                      fc.label("followers")) \
        .outerjoin(lifetime_sq,
                   lifetime_sq.c.uid == models.User.telegram_id) \
        .outerjoin(followers_sq,
                   followers_sq.c.uid == models.User.telegram_id)
    if managed:
        bquery = bquery.filter(models.User.is_managed.is_(True))
    if filter == "verified":
        bquery = bquery.filter(models.User.is_verified.is_(True))
    elif filter == "banned":
        bquery = bquery.filter(models.User.is_banned.is_(True))
    total = bquery.count()
    if sort == "points":
        key = lp
    elif sort == "followers":
        key = fc
    elif sort == "joined":
        key = models.User.created_at
    else:
        key = func.lower(models.User.first_name)
    if sort == "name":
        cols = [key, func.lower(models.User.username)]
    else:
        cols = [key, models.User.telegram_id]
    cols = [c.desc() if order == "desc" else c.asc() for c in cols]
    rows = bquery.order_by(*cols).offset(offset).limit(limit).all()
    users = []
    for u, lifetime, nfollowers in rows:
        d = _user_dict(u)
        d["lifetime_points"] = int(lifetime or 0)
        d["followers"] = int(nfollowers or 0)
        users.append(d)
    nxt = offset + len(users) if offset + len(users) < total else None
    return {"users": users, "total": total, "next_offset": nxt}


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
            user_id=telegram_id, is_deleted=False).filter(models.Post.type != "repost").count(),
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
    _delete_post_cascade(db, p)
    _audit(db, admin, "post_remove", target_id=p.user_id,
           detail=f"post {p.id}")
    db.commit()
    return {"ok": True, "id": p.id}


@app.get("/admin/content/search")
def admin_content_search(q: str = "", limit: int = 20, offset: int = 0,
                         admin: models.User = Depends(admin_user),
                         db: Session = Depends(get_db)):
    """Phase 142: search posts by text/caption or author
    name/username (case-insensitive), newest first, with
    limit/offset paging. Admin only. Search does NOT add a
    delete action — results reuse the Content section's
    existing Remove button."""
    q = (q or "").strip()
    if not q:
        raise HTTPException(400, "Search text is empty")
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    like = _like_pattern(q)
    query = db.query(models.Post, models.User).join(
        models.User, models.User.telegram_id == models.Post.user_id
    ).filter(or_(
        models.Post.caption.ilike(like, escape="\\"),
        models.User.first_name.ilike(like, escape="\\"),
        models.User.username.ilike(like, escape="\\")))
    total = query.count()
    rows = query.order_by(models.Post.id.desc()) \
        .offset(offset).limit(limit).all()
    out = []
    for p, author in rows:
        out.append({
            "id": p.id, "type": p.type,
            "caption": (p.caption or "")[:120],
            "is_deleted": bool(p.is_deleted),
            "author_id": p.user_id,
            "author_name": author.first_name if author else "",
            "author_username": author.username if author else "",
            "author_photo": author.photo_file_id if author else None,
            "has_media": bool(p.media_file_id),
            "created_at": p.created_at.isoformat()
            if p.created_at else None,
        })
    nxt = offset + len(out) if offset + len(out) < total else None
    return {"posts": out, "total": total, "next_offset": nxt}


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
            _delete_post_cascade(db, p)
    r.status = "resolved"
    _audit(db, admin, "report_resolve", target_id=r.reporter_id,
           detail=f"report {r.id}: {body.action}")
    db.commit()
    return {"ok": True, "id": r.id, "status": r.status}


# Phase 131: broadcast history + targeting. Targets: all (every
# member), verified (blue-tick members only), new_7d (joined in the
# last 7 days), inactive_30d (no post AND no app activity in the
# last 30 days — activity comes from the per-day UserActivity rows,
# which carry last_beat_at; a brand-new member with no activity yet
# matches inactive_30d too, by that definition).
_BROADCAST_TARGETS = ("all", "verified", "new_7d", "inactive_30d")


def _broadcast_targets(db, target):
    now = datetime.utcnow()
    q = db.query(models.User).filter_by(is_banned=False) \
        .filter(models.User.telegram_id != OFFICIAL_ID)
    if target == "verified":
        q = q.filter(models.User.is_verified.is_(True))
    elif target == "new_7d":
        q = q.filter(models.User.created_at >= now - timedelta(days=7))
    elif target == "inactive_30d":
        cutoff = now - timedelta(days=30)
        recent_post = db.query(models.Post.id).filter(
            models.Post.user_id == models.User.telegram_id,
            models.Post.created_at >= cutoff).exists()
        recent_app = db.query(models.UserActivity.id).filter(
            models.UserActivity.user_id == models.User.telegram_id,
            models.UserActivity.last_beat_at >= cutoff).exists()
        q = q.filter(~recent_post).filter(~recent_app)
    return q.all()


class BroadcastIn(BaseModel):
    text: str = Field(max_length=4000)
    target: str = "all"


@app.post("/admin/broadcast")
async def admin_broadcast(body: BroadcastIn,
                          admin: models.User = Depends(admin_user),
                          db: Session = Depends(get_db)):
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Broadcast text is empty")
    if body.target not in _BROADCAST_TARGETS:
        raise HTTPException(400, "Unknown broadcast target")
    targets = _broadcast_targets(db, body.target)
    # The history row is recorded first, so a broadcast is never
    # lost even if sending fails part-way through.
    row = models.Broadcast(text=text, target=body.target,
                           sent_by=admin.telegram_id,
                           total_count=len(targets))
    db.add(row)
    db.flush()
    sent = 0
    for u in targets:
        # Phase 144: a member who turned off System
        # notifications does not get the admin broadcast (they
        # still count in total_count — they were a target,
        # just not sent).
        if not notify.notif_allowed(db, u.telegram_id,
                                   "broadcast"):
            continue
        try:
            ok = await notify.send_message(u.telegram_id, text)
        except Exception:
            ok = False
        if ok:
            sent += 1
            db.add(models.NotificationLog(user_id=u.telegram_id,
                                           type="broadcast"))
        # Phase 20: the announcement also lands in the in-app 🔔 list,
        # including for managed accounts (they have no Telegram chat
        # to DM) — recorded for every target, DM or not.
        db.add(models.Notification(
            user_id=u.telegram_id, type="announcement",
            text=text[:250]))
    row.delivered_count = sent
    _audit(db, admin, "broadcast",
           detail=f"{body.target}: {sent}/{len(targets)} delivered")
    db.commit()
    return {"recipients": len(targets), "sent": sent,
            "broadcast_id": row.id}


@app.get("/admin/broadcasts")
def admin_broadcasts(limit: int = 20,
                     admin: models.User = Depends(admin_user),
                     db: Session = Depends(get_db)):
    rows = db.query(models.Broadcast) \
        .order_by(models.Broadcast.id.desc()) \
        .limit(max(1, min(limit, 100))).all()
    return {"broadcasts": [{
        "id": r.id, "text": r.text, "target": r.target,
        "sent_by": r.sent_by,
        "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        "delivered_count": r.delivered_count,
        "total_count": r.total_count,
    } for r in rows]}


@app.get("/admin/tips")
def admin_tips(admin: models.User = Depends(admin_user),
               db: Session = Depends(get_db)):
    total = db.query(func.coalesce(
        func.sum(models.Tip.amount_stars), 0)).scalar() or 0
    count = db.query(models.Tip).count()
    tops = db.query(models.Tip.to_user_id,
                    func.sum(models.Tip.amount_stars).label("total")) \
        .group_by(models.Tip.to_user_id) \
        .order_by(func.sum(models.Tip.amount_stars).desc()) \
        .limit(10).all()
    top = []
    for uid, tot in tops:
        u = db.get(models.User, uid)
        top.append({"user_id": uid,
                    "name": u.first_name if u else None,
                    "total_stars": int(tot)})
    rows = db.query(models.Tip).order_by(
        models.Tip.id.desc()).limit(50).all()
    return {"total_stars": int(total), "tip_count": count,
            "top": top,
            "recent": [_tip_dict(t, db) for t in rows]}


# ---------------------------------------------------------------------------
# Phase 22 (admin side): review blue-tick applications.
# ---------------------------------------------------------------------------

class VerifyDecideIn(BaseModel):
    approve: bool


@app.get("/admin/payouts")
def admin_payouts(status: str = "",
                  admin: models.User = Depends(admin_user),
                  db: Session = Depends(get_db)):
    q = db.query(models.PayoutRequest).order_by(
        models.PayoutRequest.id.desc())
    if status:
        if status not in ("pending", "approved", "rejected", "paid"):
            raise HTTPException(400, "Unknown payout status")
        q = q.filter_by(status=status)
    rows = q.limit(100).all()
    out = []
    for r in rows:
        out.append(_payout_dict(r, db.get(models.User, r.user_id)))
    return {"requests": out,
            "pending_count": sum(1 for r in out
                                 if r["status"] == "pending")}


@app.post("/admin/payouts/{request_id}/decide")
async def admin_payout_decide(
        request_id: int, body: PayoutDecideIn,
        admin: models.User = Depends(admin_user),
        db: Session = Depends(get_db)):
    _enforce_rate("payout_admin", str(admin.telegram_id))
    req = db.get(models.PayoutRequest, request_id)
    if req is None:
        raise HTTPException(404, "Payout request not found")
    if req.status != "pending":
        raise HTTPException(400, "This payout request was already decided")
    action = (body.action or "").strip().lower()
    if action not in ("approve", "reject"):
        raise HTTPException(400, "Action must be approve or reject")
    member = db.get(models.User, req.user_id)
    if action == "approve":
        amount = (body.amount or "").strip()
        currency = (body.currency or "").strip()
        if not amount or currency not in PAYOUT_NETWORKS:
            raise HTTPException(
                400, "Approving needs an amount and a network "
                     "(TON, Gram or USDT)")
        try:
            dec = Decimal(amount)
        except InvalidOperation:
            raise HTTPException(400, "Amount must be a number")
        if dec <= 0:
            raise HTTPException(400, "Amount must be more than 0")
        if req.points > _ledger_balance(db, req.user_id):
            raise HTTPException(
                400, "The member no longer has enough points")
        req.status = "approved"
        req.amount = str(dec)
        req.currency = currency
        # The points leave the balance now — a rejected request
        # costs nothing, and approved points cannot be requested
        # a second time.
        award_points(db, req.user_id, -req.points, "payout",
                     ref_id=req.id)
        text = (f"Your payout request for {req.points} points was "
                f"approved — {req.amount} {req.currency} is on its way. "
                "You will get the transaction reference once it is paid.")
        audit_action = "payout_approve"
    else:
        req.status = "rejected"
        text = (f"Your payout request for {req.points} points was not "
                "approved this time. Your points were not spent — you "
                "can request again from your Me page.")
        audit_action = "payout_reject"
    req.decided_at = datetime.utcnow()
    req.decided_by = admin.telegram_id
    _audit(db, admin, audit_action, target_id=req.user_id,
           detail=f"request {req.id}: {req.status} {req.points} points")
    db.commit()
    if member is not None:
        notify.record(db, member.telegram_id, "payout",
                      actor_id=None, text=text)
        await notify.notify_user(db, member.telegram_id,
                                 "payout", "💸 Nexora Social\n" + text)
    return {"ok": True, **_payout_dict(req, member)}


@app.post("/admin/payouts/{request_id}/paid")
async def admin_payout_paid(
        request_id: int, body: PayoutPaidIn,
        admin: models.User = Depends(admin_user),
        db: Session = Depends(get_db)):
    _enforce_rate("payout_admin", str(admin.telegram_id))
    req = db.get(models.PayoutRequest, request_id)
    if req is None:
        raise HTTPException(404, "Payout request not found")
    if req.status != "approved":
        raise HTTPException(
            400, "Only an approved payout can be marked paid")
    tx_ref = (body.tx_ref or "").strip()
    if not tx_ref or len(tx_ref) > 256:
        raise HTTPException(
            400, "Enter the transaction reference (max 256 characters)")
    req.status = "paid"
    req.tx_ref = tx_ref
    req.paid_at = datetime.utcnow()
    member = db.get(models.User, req.user_id)
    _audit(db, admin, "payout_paid", target_id=req.user_id,
           detail=f"request {req.id}: paid {req.amount} "
                  f"{req.currency} tx {tx_ref}")
    db.commit()
    if member is not None:
        text = (f"Your payout of {req.amount} {req.currency} was paid. "
                f"Transaction reference: {tx_ref}")
        notify.record(db, member.telegram_id, "payout",
                      actor_id=None, text=text)
        await notify.notify_user(db, member.telegram_id,
                                 "payout", "💸 Nexora Social\n" + text)
    return {"ok": True, **_payout_dict(req, member)}
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
            "referrals": _qualified_referrals_count(db, u.telegram_id),
            "met": _verification_met(db, u.telegram_id)[2],
            "posts": db.query(models.Post).filter_by(
                user_id=u.telegram_id, is_deleted=False).filter(models.Post.type != "repost").count(),
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
    _set_user_verified(db, admin, u, bool(body.verified))
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
                 shuffle: str = "",
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
        if shuffle:
            # Phase 116: a shuffled load pages by OFFSET over the
            # shuffled newest-first list — keyset paging cannot
            # shuffle, and the seed keeps one load stable.
            ranked = sorted(db.query(models.Design).all(),
                            key=lambda d: d.id, reverse=True)
            random.Random(shuffle).shuffle(ranked)
            rows = ranked[cursor:cursor + limit]
            next_cursor = cursor + limit \
                if cursor + limit < len(ranked) else None
        else:
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
        if shuffle:
            # Phase 116: refresh reshuffles (similar_to is exempt —
            # its ranking is the point there).
            random.Random(shuffle).shuffle(ranked)
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


def _parse_audit_date(value, name):
    """Parse an audit-log ?from=/?to= value (YYYY-MM-DD or full
    ISO). A bare date means the start of that day; the ?to= side
    adds a day and compares with <, so the whole day is included.
    A timezone-aware value is treated as UTC and made naive (the
    log stores naive UTC datetimes)."""
    raw = (value or "").strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, f"Invalid {name} date")
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


@app.get("/admin/audit-log")
def admin_audit_log(action: str = "", actor: str = "",
                    from_: str = Query(default="", alias="from"),
                    to: str = "",
                    limit: int = 100, offset: int = 0,
                    admin: models.User = Depends(admin_user),
                    db: Session = Depends(get_db)):
    """Phase 142: the audit log filters by action (exact), actor
    (a Telegram id, or a username/first-name substring) and date
    range (inclusive), with limit/offset paging. All filters
    combine (AND). Invalid dates are a 400."""
    q = db.query(models.AdminAuditLog) \
        .order_by(models.AdminAuditLog.id.desc())
    if action:
        q = q.filter(models.AdminAuditLog.action == action)
    if actor:
        actor = actor.strip()
        if actor.isdigit():
            q = q.filter(models.AdminAuditLog.admin_id == int(actor))
        else:
            like = _like_pattern(actor)
            sub = db.query(models.User.telegram_id).filter(or_(
                models.User.username.ilike(like, escape="\\"),
                models.User.first_name.ilike(like, escape="\\")))
            q = q.filter(models.AdminAuditLog.admin_id.in_(sub))
    if from_:
        start = _parse_audit_date(from_, "from")
        q = q.filter(models.AdminAuditLog.created_at >= start)
    if to:
        end = _parse_audit_date(to, "to")
        if "T" not in to:
            end = end + timedelta(days=1)
            q = q.filter(models.AdminAuditLog.created_at < end)
        else:
            q = q.filter(models.AdminAuditLog.created_at <= end)
    total = q.count()
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    rows = q.offset(offset).limit(limit).all()
    nxt = offset + len(rows) if offset + len(rows) < total else None
    return {"entries": [{
        "id": r.id, "admin_id": r.admin_id, "action": r.action,
        "target_id": r.target_id, "detail": r.detail,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows], "total": total, "next_offset": nxt}


class BannedWordIn(BaseModel):
    """Phase 142: one word for the banned-word list."""
    word: str = Field(default="", max_length=64)


@app.get("/admin/banned-words")
def admin_banned_words(admin: models.User = Depends(admin_user),
                       db: Session = Depends(get_db)):
    """Phase 142: the admin-managed banned-word list, newest
    first. Admin only."""
    rows = db.query(models.BannedWord) \
        .order_by(models.BannedWord.id.desc()).all()
    return {"words": [{
        "id": r.id, "word": r.word, "added_by": r.added_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]}


@app.post("/admin/banned-words")
def admin_banned_word_add(body: BannedWordIn,
                          admin: models.User = Depends(admin_user),
                          db: Session = Depends(get_db)):
    """Phase 142: ban one word (lowercased, stripped). The add
    is audit-logged; a duplicate is a 400."""
    word = (body.word or "").strip().lower()
    if not word:
        raise HTTPException(400, "A word is required")
    if len(word) > 64:
        raise HTTPException(400, "Word is too long")
    if db.query(models.BannedWord).filter_by(word=word).first():
        raise HTTPException(400, "That word is already banned")
    row = models.BannedWord(word=word, added_by=admin.telegram_id)
    db.add(row)
    _audit(db, admin, "banned_word_add", detail=f"word {word}")
    db.commit()
    db.refresh(row)
    return {"id": row.id, "word": row.word, "added_by": row.added_by,
            "created_at": row.created_at.isoformat()
            if row.created_at else None}


@app.delete("/admin/banned-words/{word_id}")
def admin_banned_word_remove(word_id: int,
                             admin: models.User = Depends(admin_user),
                             db: Session = Depends(get_db)):
    """Phase 142: unban one word (audit-logged)."""
    row = db.get(models.BannedWord, word_id)
    if row is None:
        raise HTTPException(404, "Word not found")
    _audit(db, admin, "banned_word_remove", detail=f"word {row.word}")
    db.delete(row)
    db.commit()
    return {"ok": True, "removed": word_id}


# ---------------------------------------------------------------------------
# Phase 128: Security Log — persistent security events for the Admin
# Panel (screening rejections, rate-limit hits, rejected logins,
# denied admin routes, server errors, self-deletions).
# ---------------------------------------------------------------------------

@app.get("/admin/security-log")
def admin_security_log(kind: str = "", limit: int = 100,
                       admin: models.User = Depends(admin_user),
                       db: Session = Depends(get_db)):
    """Newest first; ?kind= filters to one of the six kinds."""
    if kind and kind not in _SECURITY_KINDS:
        raise HTTPException(400, "Unknown security kind")
    q = db.query(models.SecurityEvent) \
        .order_by(models.SecurityEvent.id.desc())
    if kind:
        q = q.filter(models.SecurityEvent.kind == kind)
    rows = q.limit(max(1, min(limit, 200))).all()
    return {"entries": [{
        "id": r.id, "kind": r.kind, "actor_id": r.actor_id,
        "target_id": r.target_id, "detail": r.detail,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]}


# ---------------------------------------------------------------------------
# Phase 130: System Health — one admin-only snapshot: live version,
# commit, uptime, database size, row counts for the key tables, and
# recent server errors (reusing the Phase 128 security_events table).
# ---------------------------------------------------------------------------
_HEALTH_TABLES = [
    ("users", models.User),
    ("posts", models.Post),
    ("designs", models.Design),
    ("comments", models.Comment),
    ("likes", models.Like),
    ("points_ledger", models.PointsLedger),
    ("messages", models.Message),
    ("security_events", models.SecurityEvent),
    ("payout_requests", models.PayoutRequest),
]


def _health_db_size_bytes():
    """Database size in bytes. Postgres: pg_database_size. SQLite:
    the size of the DATABASE_URL file. Anything else: None."""
    if engine.dialect.name == "postgresql":
        try:
            with engine.connect() as conn:
                return int(conn.execute(
                    text("SELECT pg_database_size(current_database())"))
                    .scalar())
        except Exception:
            return None
    url = settings.DATABASE_URL
    if url.startswith("sqlite:///"):
        try:
            return os.path.getsize(url[len("sqlite:///"):])
        except OSError:
            return None
    return None


def _health_version():
    """Live asset version: the first ?v=NN in the deployed
    webapp/index.html on disk (the served shell IS that file)."""
    try:
        html = (Path(__file__).resolve().parent.parent
                / "webapp" / "index.html").read_text()
    except OSError:
        return None
    m = re.search(r"\?v=(\d+)", html)
    return int(m.group(1)) if m else None


@app.get("/admin/health")
def admin_health(admin: models.User = Depends(admin_user),
                 db: Session = Depends(get_db)):
    """System Health card: version, commit, uptime, DB size, row
    counts, server errors in the last 24h + the last 5 of them."""
    commit = os.environ.get("RENDER_GIT_COMMIT") or None
    if commit:
        commit = commit[:7]
    since = datetime.utcnow() - timedelta(hours=24)
    tables = {}
    for name, model in _HEALTH_TABLES:
        tables[name] = db.query(model).count()
    errors = db.query(models.SecurityEvent) \
        .filter(models.SecurityEvent.kind == "server_error",
                models.SecurityEvent.created_at >= since) \
        .count()
    recent = db.query(models.SecurityEvent) \
        .filter(models.SecurityEvent.kind == "server_error") \
        .order_by(models.SecurityEvent.id.desc()).limit(5).all()
    return {
        "version": _health_version(),
        "commit": commit,
        "uptime_seconds": int(time.time() - _STARTED_AT),
        "db_size_bytes": _health_db_size_bytes(),
        "tables": tables,
        "errors_24h": errors,
        "recent_errors": [{
            "id": e.id, "detail": e.detail,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e in recent],
    }


# ---------------------------------------------------------------------------
# Phase 119: Control Panel — admin design list, maintenance toggle,
# app-wide announcement banner (admin-only writes, public read).
# ---------------------------------------------------------------------------

@app.get("/admin/designs")
def admin_designs(limit: int = 30,
                  admin: models.User = Depends(admin_user),
                  db: Session = Depends(get_db)):
    """Control Panel → Content: the design gallery for the admin —
    newest first, with prompts and like counts, so a design can be
    reviewed and removed from the panel. Removing still goes
    through DELETE /admin/designs/{id}."""
    rows = db.query(models.Design).order_by(models.Design.id.desc()) \
        .limit(max(1, min(limit, 50))).all()
    return {"designs": [{
        "id": d.id, "prompt": d.prompt, "like_count": d.like_count,
        "image_file_id": d.image_file_id,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    } for d in rows]}


class MaintenanceIn(BaseModel):
    on: bool


@app.get("/admin/maintenance")
def admin_maintenance_state(admin: models.User = Depends(admin_user),
                            db: Session = Depends(get_db)):
    """Control Panel → Site controls: is the site in maintenance?
    env_locked means the MAINTENANCE_MODE env var is "1" — the
    panel toggle cannot switch that off."""
    return {"maintenance": settings.MAINTENANCE_MODE == "1"
            or _maintenance_on_db(),
            "env_locked": settings.MAINTENANCE_MODE == "1"}


@app.post("/admin/maintenance")
def admin_maintenance_set(body: MaintenanceIn,
                          admin: models.User = Depends(admin_user),
                          db: Session = Depends(get_db)):
    """Flip the runtime maintenance flag (app_settings row
    "maintenance"). The env flag still wins when set; the
    middleware exempts this route, so the panel can always switch
    the site back on."""
    row = db.get(models.AppSetting, "maintenance")
    if row is None:
        row = models.AppSetting(key="maintenance", value="")
        db.add(row)
    row.value = "1" if body.on else "0"
    _audit(db, admin, "maintenance_on" if body.on else "maintenance_off")
    db.commit()
    return {"maintenance": settings.MAINTENANCE_MODE == "1"
            or _maintenance_on_db(),
            "env_locked": settings.MAINTENANCE_MODE == "1"}


class AnnouncementIn(BaseModel):
    text: str = Field(default="", max_length=256)


@app.get("/announcement")
def public_announcement(db: Session = Depends(get_db)):
    """Control Panel → Site controls: the app-wide banner text the
    admin set, or "" when none. Public — the client reads it at
    boot and shows the banner on the feed."""
    row = db.get(models.AppSetting, "announcement")
    return {"text": (row.value if row is not None else "") or ""}


@app.post("/admin/announcement")
def admin_announcement_set(body: AnnouncementIn,
                           admin: models.User = Depends(admin_user),
                           db: Session = Depends(get_db)):
    """Set (or clear, with empty text) the app-wide announcement
    banner. Shown on every member's feed until cleared."""
    text = (body.text or "").strip()
    row = db.get(models.AppSetting, "announcement")
    if row is None:
        row = models.AppSetting(key="announcement", value="")
        db.add(row)
    row.value = text
    _audit(db, admin,
           "announcement_set" if text else "announcement_cleared",
           detail=text[:200])
    db.commit()
    return {"text": text}


# ---------------------------------------------------------------------------
# Phase 120: Verify by Username — the Control Panel section where
# the admin grants or removes the blue tick for one person by
# @username. Lookup is exact and case-insensitive, @ optional.
# ---------------------------------------------------------------------------

def _normalize_username(raw) -> str:
    """Strip whitespace and one leading @, lowercase for lookup."""
    name = (raw or "").strip()
    if name.startswith("@"):
        name = name[1:]
    return name.strip().lower()


def _set_user_verified(db, admin, user, verified):
    """Shared grant/revoke core: flip the flag, audit the action.
    Used by the member toggle and by Verify by Username alike."""
    user.is_verified = bool(verified)
    _audit(db, admin, "verify_grant" if verified else "verify_revoke",
           target_id=user.telegram_id)


@app.get("/admin/users/by-username/{username}")
def admin_user_by_username(username: str,
                           admin: models.User = Depends(admin_user),
                           db: Session = Depends(get_db)):
    """Control Panel -> Verify by Username: exact (case-insensitive)
    lookup for the user card — name, photo, tick status, followers,
    posts. 404 when nobody has that username."""
    name = _normalize_username(username)
    if not name:
        raise HTTPException(400, "Username cannot be empty")
    u = db.query(models.User).filter(
        func.lower(models.User.username) == name).first()
    if u is None:
        raise HTTPException(404, "No member with that username")
    return {
        "telegram_id": u.telegram_id, "first_name": u.first_name,
        "username": u.username, "photo_file_id": u.photo_file_id,
        "is_verified": bool(u.is_verified),
        "followers": _followers_count(db, u.telegram_id),
        "posts": db.query(models.Post).filter_by(
            user_id=u.telegram_id, is_deleted=False).filter(
            models.Post.type != "repost").count(),
    }


class VerifyByUsernameIn(BaseModel):
    username: str = Field(max_length=64)
    action: str = Field(max_length=16)


@app.post("/admin/verify-by-username")
async def admin_verify_by_username(body: VerifyByUsernameIn,
                                   admin: models.User = Depends(admin_user),
                                   db: Session = Depends(get_db)):
    """Control Panel -> Verify by Username: grant or remove the blue
    tick for one person by @username. A grant/revoke that changes
    nothing is a harmless no-op (changed: False) — no audit row, no
    notification. The official account (@nexora) can never change
    through here. A real change notifies the member, like the
    verification-approval grant does."""
    if body.action not in ("grant", "revoke"):
        raise HTTPException(400, "Action must be 'grant' or 'revoke'")
    name = _normalize_username(body.username)
    if not name:
        raise HTTPException(400, "Username cannot be empty")
    u = db.query(models.User).filter(
        func.lower(models.User.username) == name).first()
    if u is None:
        raise HTTPException(404, "No member with that username")
    if u.telegram_id == OFFICIAL_ID:
        raise HTTPException(400, "The official account is always verified")
    verified = body.action == "grant"
    if bool(u.is_verified) == verified:
        return {"telegram_id": u.telegram_id, "username": u.username,
                "first_name": u.first_name,
                "is_verified": bool(u.is_verified), "changed": False}
    _set_user_verified(db, admin, u, verified)
    db.commit()
    if verified:
        text = ("The admin gave you the blue tick — it now shows "
                "on your profile \u2713")
    else:
        text = "The admin removed the blue tick from your profile."
    notify.record(db, u.telegram_id, "verification",
                  actor_id=None, text=text)
    await notify.notify_user(db, u.telegram_id,
                             "verification", "\U0001f6e1\ufe0f Nexora Social\n" + text)
    return {"telegram_id": u.telegram_id, "username": u.username,
            "first_name": u.first_name,
            "is_verified": bool(u.is_verified), "changed": True}


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
    ("saved_collections", models.SavedCollection),
    ("saved_collection_posts", models.SavedCollectionPost),
    ("post_shares", models.PostShare),
    ("daily_claims", models.DailyClaim),
    # Phase 180 (audit M24): durable follow records for follow3.
    ("task_follow_events", models.TaskFollowEvent),
    ("user_activity", models.UserActivity),
    ("ad_events", models.AdEvent),
    ("app_settings", models.AppSetting),
    ("notifications", models.Notification),
    ("verification_requests", models.VerificationRequest),
    ("design_likes", models.DesignLike),
    ("admin_audit_logs", models.AdminAuditLog),
    ("user_blocks", models.UserBlock),
    ("mutes", models.Mute),
    ("post_views", models.PostView),
    ("design_views", models.DesignView),
    ("design_saves", models.DesignSave),
    ("design_shares", models.DesignShare),
    ("messages", models.Message),
    ("stories", models.Story),
    ("story_views", models.StoryView),
    # Phase 123: creator tools — drafts, comment likes, polls.
    ("drafts", models.Draft),
    ("comment_likes", models.CommentLike),
    ("polls", models.Poll),
    ("poll_options", models.PollOption),
    ("poll_votes", models.PollVote),
    # Phase 127: crypto payout requests.
    ("payout_requests", models.PayoutRequest),
    # Phase 128: persistent security log.
    ("security_events", models.SecurityEvent),
    # Phase 131: broadcast history.
    ("broadcasts", models.Broadcast),
    # Phase 133: Stars tips.
    ("tips", models.Tip),
    # Phase 135: scheduled posts.
    ("scheduled_posts", models.ScheduledPost),
    # Phase 136: private-account follow requests.
    ("follow_requests", models.FollowRequest),
    # Phase 138: DM message reactions.
    ("message_reactions", models.MessageReaction),
    # Phase 140: hashtag follows.
    ("hashtag_follows", models.HashtagFollow),
    # Phase 142: banned-word list.
    ("banned_words", models.BannedWord),
    # Phase 151: blood requests.
    ("blood_requests", models.BloodRequest),
    # Phase 158: skill swap entries.
    ("skill_entries", models.SkillEntry),
    # Phase 170: @mentions.
    ("mentions", models.Mention),
    ("post_media", models.PostMedia),
    # Phase 172: story highlights.
    ("story_highlights", models.StoryHighlight),
    ("highlight_stories", models.HighlightStory),
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


def _backup_fernet():
    """Phase 164 (M2): Fernet cipher for backup payloads, keyed by
    the owner-held BACKUP_ENCRYPTION_KEY env var. None when the key
    is absent or malformed — backups then stay plaintext (loudly)."""
    key = getattr(settings, "BACKUP_ENCRYPTION_KEY", "") or ""
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode())
    except Exception:
        sec_log.warning("BACKUP_ENCRYPTION_KEY is set but not a valid "
                        "Fernet key — backups stay unencrypted")
        return None


def _backup_pack(payload: dict, prefix="nexora-full-backup"):
    """Phase 164 (M2): serialize a backup payload; encrypt it when a
    key is configured. Returns (bytes, filename, encrypted)."""
    data = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
    cipher = _backup_fernet()
    stamp = datetime.utcnow().strftime("%Y-%m-%d")
    if cipher is None:
        return data, prefix + "-" + stamp + ".json", False
    return cipher.encrypt(data), prefix + "-" + stamp + ".json.enc", True


def _backup_unpack(raw):
    """Phase 164 (M2): accept both encrypted and plaintext backups.
    Fernet tokens start with the version byte 0x80 (base64 'gAAAAA');
    anything else parses as plain JSON. Raises 400 on bad input."""
    if isinstance(raw, str):
        raw = raw.encode()
    if raw[:6] == b"gAAAAA":
        cipher = _backup_fernet()
        if cipher is None:
            raise HTTPException(
                400, "This backup is encrypted — set "
                     "BACKUP_ENCRYPTION_KEY on the server to restore it")
        try:
            raw = cipher.decrypt(raw)
        except Exception:
            raise HTTPException(400, "Could not decrypt this backup — "
                                     "wrong key?")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "Backup must be a JSON object")
    if not isinstance(payload, dict):
        raise HTTPException(400, "Backup must be a JSON object")
    return payload


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
    """Admin-only full-site backup download (Phase 107; Phase 164:
    encrypted with BACKUP_ENCRYPTION_KEY when configured)."""
    _enforce_rate("backup", f"a{admin.telegram_id}")
    payload = _backup_payload(db)
    total = sum(len(v) for v in payload["tables"].values())
    data, fname, encrypted = _backup_pack(payload)
    _audit(db, admin, "backup_download",
           detail=f"{total} rows across {len(payload['tables'])} tables"
                  + (" (encrypted)" if encrypted else " (plaintext — no key)"))
    db.commit()
    if encrypted:
        return Response(content=data, media_type="application/octet-stream",
                        headers={"Content-Disposition":
                                 f"attachment; filename={fname}"})
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f"attachment; filename={fname}"})


@app.post("/admin/backup/send")
async def admin_backup_send(admin: models.User = Depends(admin_user),
                            db: Session = Depends(get_db)):
    """Send the full backup to the admin's bot chat (Phase 107) —
    the reliable route on phones, same as the Phase 100 export.
    Phase 164: encrypted with BACKUP_ENCRYPTION_KEY when configured."""
    _enforce_rate("backup", f"a{admin.telegram_id}")
    payload = _backup_payload(db)
    data, fname, encrypted = _backup_pack(payload)
    if not encrypted:
        sec_log.warning("backup sent UNENCRYPTED to admin %s — set "
                        "BACKUP_ENCRYPTION_KEY", admin.telegram_id)
    sent = await notify.send_document(
        admin.telegram_id, fname, data,
        caption="💾 Nexora full-site backup — every user, post, "
                "comment, like, follow, design and message. Keep "
                "this file safe: anyone holding it holds the whole "
                "database." + (" 🔐 Encrypted — keep your key safe."
                               if encrypted else ""))
    if sent:
        # Phase 132: a backup sent to Telegram counts as a backup
        # taken — the backup-status endpoint reads the audit log.
        _audit(db, admin, "backup_send",
               detail=f"{len(data)} bytes"
                      + (" (encrypted)" if encrypted else ""))
        db.commit()
    return {"sent": bool(sent)}


class RestoreIn(BaseModel):
    confirm: str
    backup: Optional[dict] = None
    # Phase 164: an encrypted backup file's raw text (a Fernet token).
    backup_encrypted: Optional[str] = None


@app.post("/admin/restore")
def admin_restore(body: RestoreIn,
                  x_act_as: str = Header(default=""),
                  admin: models.User = Depends(admin_user),
                  db: Session = Depends(get_db)):
    """Restore the whole site from a backup file (Phase 107).
    Guarded: admin-only, never while acting as another account,
    typed RESTORE, format/version/column validation up front, one
    transaction (a bad file rolls back clean), audit-logged.
    Phase 164: accepts encrypted backups too (decrypted server-side
    with BACKUP_ENCRYPTION_KEY)."""
    if x_act_as:
        raise HTTPException(
            400, "Switch back to your own account to restore")
    if body.confirm != "RESTORE":
        raise HTTPException(400, "Type RESTORE to confirm the restore")
    if body.backup_encrypted:
        if len(body.backup_encrypted) > 70_000_000:
            raise HTTPException(413, "Backup file is too large (max 50 MB)")
        payload = _backup_unpack(body.backup_encrypted)
    elif body.backup is not None:
        if len(json.dumps(body.backup, ensure_ascii=False)) > _BACKUP_MAX_BYTES:
            raise HTTPException(413, "Backup file is too large (max 50 MB)")
        payload = body.backup
    else:
        raise HTTPException(400, "Pick a backup file first")
    _enforce_rate("restore", f"a{admin.telegram_id}")
    try:
        counts = _restore_backup(db, payload)
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


@app.get("/admin/backup-status")
def admin_backup_status(admin: models.User = Depends(admin_user),
                        db: Session = Depends(get_db)):
    """Phase 132: when was the last backup / restore? Derived from
    the audit log — the newest backup_download / backup_send entry
    (kind download or send) and the newest backup_restore entry.
    Each is null when no such entry exists yet. No new table."""
    last_backup = db.query(models.AdminAuditLog) \
        .filter(models.AdminAuditLog.action.in_(
            ("backup_download", "backup_send"))) \
        .order_by(models.AdminAuditLog.id.desc()).first()
    last_restore = db.query(models.AdminAuditLog) \
        .filter(models.AdminAuditLog.action == "backup_restore") \
        .order_by(models.AdminAuditLog.id.desc()).first()
    return {
        "last_backup_at": last_backup.created_at.isoformat()
            if last_backup and last_backup.created_at else None,
        "last_backup_kind": (
            "download" if last_backup.action == "backup_download"
            else "send") if last_backup else None,
        "last_restore_at": last_restore.created_at.isoformat()
            if last_restore and last_restore.created_at else None,
        "last_auto_backup_at": (
            _auto_backup_last_run(db).isoformat()
            if _auto_backup_last_run(db) else None),
    }


class AutoBackupIn(BaseModel):
    enabled: bool


@app.get("/admin/auto-backup")
def admin_auto_backup_status(admin: models.User = Depends(admin_user),
                             db: Session = Depends(get_db)):
    """Phase 141: auto-backup status — enabled, last successful
    auto send, next due time. Admin-only."""
    last = _auto_backup_last_run(db)
    enabled = _auto_backup_enabled(db)
    nxt = _auto_backup_next_due(db) if enabled else None
    return {
        "enabled": enabled,
        "last_auto_backup_at": last.isoformat() if last else None,
        "next_due_at": nxt.isoformat() if nxt else None,
    }


@app.post("/admin/auto-backup")
def admin_auto_backup_set(body: AutoBackupIn,
                          admin: models.User = Depends(admin_user),
                          db: Session = Depends(get_db)):
    """Phase 141: flip the weekly auto-backup on/off (admin-only).
    The setting lives in app_settings, so it rides the normal
    backup and survives restarts."""
    _set_app_setting(db, "auto_backup_enabled",
                     "1" if body.enabled else "0")
    _audit(db, admin,
           "auto_backup_enabled" if body.enabled
           else "auto_backup_disabled")
    db.commit()
    return admin_auto_backup_status(admin, db)


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
    log_security_event(db, "account_delete",
                       actor_id=user.telegram_id,
                       detail=f"Member {user.telegram_id} deleted "
                              "their account")
    return {"ok": True, "deleted": user.telegram_id}


@app.get("/media/{file_id}")
async def media_proxy(file_id: str, request: Request,
                      db: Session = Depends(get_db)):
    """Stream a Telegram-hosted file to the Mini App. The bot token is used
    only in server-side requests and never appears in a client-visible URL.
    Phase 164 (P1): access needs a user-bound 1-hour token AND the
    file must be visible to that member (same rules as the feed) —
    a bare file_id, or another member's token, answers 404. Needs a
    live token, so this path is verified at deploy time; without a
    token it answers 503.

    The upstream response is opened HERE (not inside an `async with` that
    exits before the body streams — that closed-client bug silently broke
    every posted image) and its lifetime is tied to the body generator.
    Range requests are forwarded so video seeking works in reels."""
    if not settings.BOT_TOKEN:
        raise HTTPException(503, "Media unavailable until the bot is live")
    # Phase 164 (P1): the token is bound to one member and one hour,
    # and it honours revocation — a leaked token dies with the session.
    checked = _media_token_ok(request.query_params.get("mt", ""))
    if checked is None:
        raise HTTPException(401, "Media token missing or expired")
    viewer_id, issued_at = checked
    viewer = db.get(models.User, viewer_id)
    if viewer is None or viewer.is_banned:
        raise HTTPException(401, "Media token missing or expired")
    if viewer.auth_revoked_at is not None:
        revoked_ts = int(viewer.auth_revoked_at.replace(
            tzinfo=timezone.utc).timestamp())
        if issued_at < revoked_ts:
            raise HTTPException(401, "Media token missing or expired")
    # Phase 164 (H2): /media was unthrottled — one token holder could
    # hammer the Telegram proxy without limit.
    _enforce_rate("media", f"u{viewer_id}")
    # Phase 164 (P1): the file's owner/visibility decides — a token
    # alone never opens another member's private media.
    if not _media_visible(db, viewer_id, file_id):
        raise HTTPException(404, "File not found")
    api = f"https://api.telegram.org/bot{settings.BOT_TOKEN}"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            info = await client.get(f"{api}/getFile",
                                    params={"file_id": file_id})
        except httpx.HTTPError:
            raise HTTPException(404, "File not found")
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
    # change, and the signed ?mt= token bounds access to 1 hour
    # (Phase 164), so a private 1-hour cache is safe: repeat visits
    # serve from the browser cache instead of re-fetching.
    headers["cache-control"] = "private, max-age=3600, immutable"
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


# Phase 138: the six DM reaction emojis — one reaction per
# member per message; tapping your own emoji again removes it.
DM_REACTIONS = ("❤️", "👍", "😂", "😮", "😢", "🔥")


def _thread_reactions(db, message_ids, me_id):
    """{message_id: {"reactions": {emoji: count}, "my_reaction": ...}}
    for one thread — a single query, not one per bubble."""
    out = {mid: {"reactions": {}, "my_reaction": None}
           for mid in message_ids}
    if not message_ids:
        return out
    rows = db.query(models.MessageReaction).filter(
        models.MessageReaction.message_id.in_(message_ids)).all()
    for r in rows:
        d = out[r.message_id]
        d["reactions"][r.emoji] = d["reactions"].get(r.emoji, 0) + 1
        if r.user_id == me_id:
            d["my_reaction"] = r.emoji
    return out


def _message_dict(m, me_id, reactions=None, stories=None):
    d = {"id": m.id, "mine": m.sender_id == me_id, "text": m.text,
         "media_file_id": m.media_file_id,
         "media_type": m.media_type,
         "media_duration": m.media_duration,
         "story_id": m.story_id,
         "created_at": m.created_at.isoformat() if m.created_at
         else None,
         "read": m.read_at is not None}
    if m.story_id is not None and stories is not None:
        # A deleted/expired story still gets a preview with
        # live False, so the reply never dangles.
        d["story"] = stories.get(m.story_id) or {"id": m.story_id,
                                                 "live": False}
    if reactions is not None:
        d["reactions"] = reactions["reactions"]
        d["my_reaction"] = reactions["my_reaction"]
    return d


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
    react = _thread_reactions(db, [m.id for m in rows], me)
    previews = _story_previews(
        db, [m.story_id for m in rows if m.story_id is not None])
    return {"user": _brief_user(other),
            "messages": [_message_dict(m, me, react.get(m.id), previews)
                         for m in rows]}


class MessageIn(BaseModel):
    text: str = Field(default="", max_length=2000)
    media_file_id: Optional[str] = None
    media_type: Optional[str] = None
    media_duration: Optional[int] = None


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
    text = (body.text or "").strip()
    media_file_id = (body.media_file_id or "").strip() or None
    media_type = (body.media_type or "").strip() or None
    if not text and not media_file_id:
        raise HTTPException(400, "Message is empty")
    secs = None
    if media_file_id:
        # Phase 173: DMs carry photos and voice notes. A video
        # file_id is refused before anything is fetched or
        # screened. Audio is NOT Gemini-screened (Vision cannot
        # hear it) — report + block are the backstop.
        if media_type is None:
            media_type = "photo"
        if media_type == "voice":
            secs = body.media_duration or 0
            if secs < 1 or secs > 120:
                raise HTTPException(
                    400, "Voice messages are 1–120 seconds")
        elif media_type == "photo":
            if moderation.active():
                verdict = _screen_file_id("photo", media_file_id)
                if verdict != "clean":
                    log_security_event(db, "screen_reject",
                                       actor_id=me, detail=
                                       f"DM photo screened out ({verdict})")
                    raise HTTPException(
                        400, moderation.block_message("photo", verdict))
        else:
            raise HTTPException(
                400, "DMs support photos and voice only")
    _enforce_rate("message", f"u{me}")
    m = models.Message(sender_id=me, recipient_id=uid, text=text,
                       media_file_id=media_file_id,
                       media_type=media_type if media_file_id else None,
                       media_duration=secs)
    db.add(m)
    db.commit()
    db.refresh(m)
    notify.record(db, uid, "message", actor_id=me,
                  text=(f"{user.first_name} sent you a voice message"
                        if media_type == "voice" and media_file_id else
                        f"{user.first_name} sent you a photo"
                        if media_file_id else
                        f"{user.first_name} sent you a message"))
    return _message_dict(m, me, {"reactions": {}, "my_reaction": None})


@app.post("/messages/{uid}/upload")
async def upload_dm_photo(uid: int, request: Request,
                          file: UploadFile = File(...),
                          text: str = Form(""),
                          x_upload_id: Optional[str] = Header(None),
                          user: models.User = Depends(current_user),
                          db: Session = Depends(get_db)):
    """Phase 138: a photo in a DM, through the same in-app upload
    path as stories and posts (_telegram_upload_or_400 — the
    photo is screened inline by Phase 81 before it is sent on).
    Videos are refused up front: the helper would otherwise
    schedule its background video job, which posts to the feed."""
    hit = _dedupe_get(user.telegram_id, x_upload_id)
    if hit:
        return JSONResponse(status_code=hit[0], content=hit[1])
    me = user.telegram_id
    if uid == me:
        raise HTTPException(400, "You can't message yourself")
    other = db.get(models.User, uid)
    if other is None:
        raise HTTPException(404, "User not found")
    if uid in _block_related_ids(db, me):
        raise HTTPException(403, "You can't message this user")
    kind = tgupload.classify(file.content_type or "",
                             file.filename or "")
    if kind != "photo":
        raise HTTPException(400, "DMs support photos only")
    _enforce_rate("upload", f"u{me}")
    kind, file_id = await _telegram_upload_or_400(user, file)
    if kind != "photo":
        raise HTTPException(400, "DMs support photos only")
    m = models.Message(sender_id=me, recipient_id=uid,
                       text=(text or "").strip()[:2000],
                       media_file_id=file_id, media_type="photo")
    db.add(m)
    db.commit()
    db.refresh(m)
    notify.record(db, uid, "message", actor_id=me,
                  text=f"{user.first_name} sent you a photo")
    body = _message_dict(m, me, {"reactions": {}, "my_reaction": None})
    _dedupe_put(user.telegram_id, x_upload_id, 200, body)
    return body


@app.post("/messages/{uid}/upload-voice")
async def upload_dm_voice(uid: int, request: Request,
                          file: UploadFile = File(...),
                          duration: str = Form(""),
                          x_upload_id: Optional[str] = Header(None),
                          user: models.User = Depends(current_user),
                          db: Session = Depends(get_db)):
    """Phase 173: a voice note in a DM. The recording is transcoded
    to OGG Opus and sent with sendVoice, so the file lives on
    Telegram like every other DM media. The 120 s / 5 MB caps keep
    a single note cheap; the client enforces 120 s too."""
    hit = _dedupe_get(user.telegram_id, x_upload_id)
    if hit:
        return JSONResponse(status_code=hit[0], content=hit[1])
    me = user.telegram_id
    if uid == me:
        raise HTTPException(400, "You can't message yourself")
    other = db.get(models.User, uid)
    if other is None:
        raise HTTPException(404, "User not found")
    if uid in _block_related_ids(db, me):
        raise HTTPException(403, "You can't message this user")
    try:
        secs = int((duration or "").strip())
    except (TypeError, ValueError):
        raise HTTPException(400, "Voice duration is missing")
    if secs < 1 or secs > 120:
        raise HTTPException(400, "Voice messages are 1–120 seconds")
    ctype = (file.content_type or "").lower()
    name = (file.filename or "").lower()
    if not (ctype.startswith("audio/") or name.endswith(
            (".webm", ".ogg", ".m4a", ".mp3", ".wav"))):
        raise HTTPException(400, "That is not an audio recording")
    _enforce_rate("upload", f"u{me}")
    chunks, total = [], 0
    while True:
        chunk = await file.read(256 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > 5 * 1024 * 1024:
            raise HTTPException(
                400, "Voice message is too large (max 5 MB)")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(400, "Empty recording")
    file_id = await _send_voice_to_telegram(user, data, ctype, name)
    m = models.Message(sender_id=me, recipient_id=uid, text="",
                       media_file_id=file_id, media_type="voice",
                       media_duration=secs)
    db.add(m)
    db.commit()
    db.refresh(m)
    notify.record(db, uid, "message", actor_id=me,
                  text=f"{user.first_name} sent you a voice message")
    body = _message_dict(m, me, {"reactions": {}, "my_reaction": None})
    _dedupe_put(user.telegram_id, x_upload_id, 200, body)
    return body


class ReactIn(BaseModel):
    emoji: str = ""


@app.post("/dm/messages/{message_id}/react")
def react_message(message_id: int, body: ReactIn,
                  user: models.User = Depends(current_user),
                  db: Session = Depends(get_db)):
    """Phase 138: one emoji reaction per member per DM message.
    The same emoji again removes it; a different emoji replaces
    it. Only the two people in the thread may react."""
    _enforce_rate("dm_react", f"u{user.telegram_id}")
    m = db.get(models.Message, message_id)
    if m is None:
        raise HTTPException(404, "Message not found")
    me = user.telegram_id
    if me not in (m.sender_id, m.recipient_id):
        raise HTTPException(403, "Not your message")
    other = m.recipient_id if m.sender_id == me else m.sender_id
    if other in _block_related_ids(db, me):
        raise HTTPException(403, "You can't message this user")
    emoji = (body.emoji or "").strip()
    if emoji not in DM_REACTIONS:
        raise HTTPException(400, "Unknown reaction")
    existing = db.query(models.MessageReaction).filter_by(
        message_id=m.id, user_id=me).first()
    if existing and existing.emoji == emoji:
        db.delete(existing)
        reacted, mine = False, None
    elif existing:
        existing.emoji = emoji
        reacted, mine = True, emoji
    else:
        db.add(models.MessageReaction(message_id=m.id, user_id=me,
                                      emoji=emoji))
        reacted, mine = True, emoji
    db.commit()
    counts = {}
    for r in db.query(models.MessageReaction).filter_by(
            message_id=m.id).all():
        counts[r.emoji] = counts.get(r.emoji, 0) + 1
    return {"message_id": m.id, "reacted": reacted, "emoji": mine,
            "reactions": counts, "my_reaction": mine}


def _story_previews(db, story_ids):
    """{story_id: preview} for DM story replies — one query for
    the whole thread. A deleted/expired story is simply absent
    here, and _message_dict falls back to a live-False stub."""
    out = {}
    ids = [i for i in dict.fromkeys(story_ids) if i is not None]
    if not ids:
        return out
    cutoff = datetime.utcnow() - STORY_TTL
    for s in db.query(models.Story).filter(
            models.Story.id.in_(ids)).all():
        u = db.get(models.User, s.user_id)
        out[s.id] = {"id": s.id, "media_file_id": s.media_file_id,
                     "author": u.first_name if u else "",
                     "created_at": s.created_at.isoformat()
                     if s.created_at else None,
                     "live": s.created_at > cutoff}
    return out


def _story_dict(db, s, viewer_id):
    views = db.query(models.StoryView).filter_by(story_id=s.id).count()
    viewed = db.query(models.StoryView).filter_by(
        story_id=s.id, viewer_id=viewer_id).first() is not None
    return {"id": s.id, "media_file_id": s.media_file_id,
            "created_at": s.created_at.isoformat() if s.created_at
            else None,
            "views": views, "viewed": viewed,
            # Phase 139: the viewer count is the owner's alone.
            "viewer_count": views if s.user_id == viewer_id else None,
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


@app.get("/stories/mine")
def my_stories(user: models.User = Depends(current_user),
               db: Session = Depends(get_db)):
    """Phase 172: the member's own stories, active AND expired,
    newest first — the highlight picker source."""
    rows = db.query(models.Story).filter_by(
        user_id=user.telegram_id).order_by(
            models.Story.id.desc()).limit(100).all()
    cutoff = datetime.utcnow() - STORY_TTL
    out = []
    for s in rows:
        d = _story_dict(db, s, user.telegram_id)
        d["expired"] = bool(
            s.created_at is not None and s.created_at <= cutoff)
        out.append(d)
    return {"stories": out}


@app.get("/stories")
def list_stories(user: models.User = Depends(current_user),
                 db: Session = Depends(get_db)):
    # Phase 179 (audit M4): 240/h per member — the strip loads
    # once per Messages view, far below this.
    _enforce_rate("stories", f"u{user.telegram_id}")
    me = user.telegram_id
    cutoff = datetime.utcnow() - STORY_TTL
    author_ids = {me, OFFICIAL_ID}
    author_ids.update(f.following_id for f in
                      db.query(models.Follow).filter_by(
                          follower_id=me).all())
    author_ids -= _block_related_ids(db, me)
    # Phase 174: muted members' stories do not show either.
    author_ids -= _muted_ids(db, me)
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
    # Phase 179 (audit H6): a story is only view-countable when
    # its author is visible to the viewer — blocked either way
    # or muted -> 404 (the story does not exist for that viewer),
    # private-and-not-followed -> 403, matching reply_story /
    # list_stories. Checked BEFORE the rate limit and before any
    # StoryView row is written, so a refused viewer never lands
    # in the owner's viewer list. Own stories pass untouched.
    if s.user_id != user.telegram_id:
        if (_blocked_by(db, s.user_id, user.telegram_id)
                or _blocked_by(db, user.telegram_id, s.user_id)
                or _muted_by(db, user.telegram_id, s.user_id)):
            raise HTTPException(404, "Story not found")
        if not _can_see_posts(db, user.telegram_id, s.user_id):
            raise HTTPException(403, "This account is private")
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
    # Phase 172: a deleted story leaves every highlight it was in.
    db.query(models.HighlightStory).filter_by(story_id=sid).delete()
    db.delete(s)
    db.commit()
    return {"ok": True}


@app.get("/stories/{sid}/viewers")
def story_viewers(sid: int, user: models.User = Depends(current_user),
                  db: Session = Depends(get_db)):
    """Phase 139: who viewed a story — the owner only, newest
    first. A view row exists only for a live story, so an expired
    or deleted story is a 404 here."""
    s = db.get(models.Story, sid)
    if s is None or s.created_at <= datetime.utcnow() - STORY_TTL:
        raise HTTPException(404, "Story not found")
    if s.user_id != user.telegram_id:
        raise HTTPException(403, "Only the story owner sees viewers")
    rows = db.query(models.StoryView).filter_by(
        story_id=sid).order_by(models.StoryView.id.desc()).all()
    out = []
    for v in rows:
        u = db.get(models.User, v.viewer_id)
        if u is None:
            continue
        out.append({"user": _brief_user(u),
                    "viewed_at": v.created_at.isoformat()
                    if v.created_at else None})
    return {"story_id": sid, "viewers": out}


class StoryReplyIn(BaseModel):
    text: str = Field(default="", max_length=2000)


@app.post("/stories/{sid}/reply")
def reply_story(sid: int, body: StoryReplyIn,
                user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
    """Phase 139: a text reply to a story lands as a DM to the
    story owner, carrying story_id so the thread can show the
    story preview. Text only — no photo replies in this phase."""
    s = db.get(models.Story, sid)
    if s is None or s.created_at <= datetime.utcnow() - STORY_TTL:
        raise HTTPException(404, "Story not found")
    me = user.telegram_id
    if s.user_id == me:
        raise HTTPException(400, "You can't reply to your own story")
    if s.user_id in _block_related_ids(db, me):
        raise HTTPException(403, "You can't message this user")
    if not _can_see_posts(db, me, s.user_id):
        raise HTTPException(403, "This account is private")
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "Reply is empty")
    _enforce_rate("message", f"u{me}")
    m = models.Message(sender_id=me, recipient_id=s.user_id,
                       text=text, story_id=sid)
    db.add(m)
    db.commit()
    db.refresh(m)
    notify.record(db, s.user_id, "message", actor_id=me,
                  text=f"{user.first_name} replied to your story")
    previews = _story_previews(db, [sid])
    return _message_dict(m, me, {"reactions": {}, "my_reaction": None},
                         previews)



# ---------------------------------------------------------------------------
# Phase 172: Story Highlights — a member pins their own stories
# (active AND expired) into named collections on their profile.
# Stories are never copied and never deleted for expiry; a highlight
# replays the originals in position order. Private-account + block
# rules reuse Phase 136; only the owner manages a highlight.
# ---------------------------------------------------------------------------
class HighlightIn(BaseModel):
    title: str = Field(default="", max_length=50)
    story_ids: list = Field(default_factory=list)


def _highlight_visible(db, viewer_id, owner_id):
    if _blocked_by(db, owner_id, viewer_id) or _blocked_by(
            db, viewer_id, owner_id):
        return False
    # Phase 179 (audit M2): a muted member's highlight circles
    # disappear for the muter — highlights are a story view
    # (PRD Phase 174). Own highlights pass: nobody mutes self.
    if _muted_by(db, viewer_id, owner_id):
        return False
    return _can_see_posts(db, viewer_id, owner_id)


def _highlight_out(db, h, viewer_id):
    rows = db.query(models.HighlightStory).filter_by(
        highlight_id=h.id).order_by(
            models.HighlightStory.position.asc()).all()
    cover = None
    if rows:
        first = db.get(models.Story, rows[0].story_id)
        if first is not None:
            cover = first.media_file_id
    return {"id": h.id, "user_id": h.user_id, "title": h.title,
            "story_count": len(rows), "cover_media_file_id": cover,
            "created_at": h.created_at.isoformat() if h.created_at
            else None}


def _highlight_story_ids(body):
    ids = []
    for sid in (body.story_ids or []):
        try:
            sid = int(sid)
        except (TypeError, ValueError):
            continue
        if sid not in ids:
            ids.append(sid)
    return ids


@app.post("/highlights")
def create_highlight(body: HighlightIn,
                     user: models.User = Depends(current_user),
                     db: Session = Depends(get_db)):
    _enforce_rate("highlights", f"u{user.telegram_id}")
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(400, "A highlight needs a title")
    ids = _highlight_story_ids(body)
    if not ids:
        raise HTTPException(400, "Pick at least one story")
    if len(ids) > 50:
        raise HTTPException(400, "At most 50 stories per highlight")
    if db.query(models.StoryHighlight).filter_by(
            user_id=user.telegram_id).count() >= 20:
        raise HTTPException(400, "At most 20 highlights")
    found = db.query(models.Story).filter(
        models.Story.id.in_(ids),
        models.Story.user_id == user.telegram_id).all()
    if len({s.id for s in found}) != len(ids):
        raise HTTPException(400, "Only your own stories can be added")
    h = models.StoryHighlight(user_id=user.telegram_id, title=title)
    db.add(h)
    db.flush()
    for pos, sid in enumerate(ids):
        db.add(models.HighlightStory(
            highlight_id=h.id, story_id=sid, position=pos))
    db.commit()
    db.refresh(h)
    return _highlight_out(db, h, user.telegram_id)


@app.get("/highlights/user/{user_id}")
def list_highlights(user_id: int,
                    user: models.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    # Phase 179 (audit M4): "highlight_read" budget — circles
    # load once per profile open.
    _enforce_rate("highlight_read", f"u{user.telegram_id}")
    if not _highlight_visible(db, user.telegram_id, user_id):
        return {"highlights": []}
    rows = db.query(models.StoryHighlight).filter_by(
        user_id=user_id).order_by(
            models.StoryHighlight.id.asc()).all()
    return {"highlights": [_highlight_out(db, h, user.telegram_id)
                           for h in rows]}


@app.get("/highlights/{hid}")
def get_highlight(hid: int, user: models.User = Depends(current_user),
                  db: Session = Depends(get_db)):
    # Phase 179 (audit M4): "highlight_read" budget (see
    # list_highlights) — one replay load per tap.
    _enforce_rate("highlight_read", f"u{user.telegram_id}")
    h = db.get(models.StoryHighlight, hid)
    if h is None:
        raise HTTPException(404, "Highlight not found")
    if not _highlight_visible(db, user.telegram_id, h.user_id):
        raise HTTPException(404, "Highlight not found")
    rows = db.query(models.HighlightStory).filter_by(
        highlight_id=h.id).order_by(
            models.HighlightStory.position.asc()).all()
    cutoff = datetime.utcnow() - STORY_TTL
    stories = []
    for row in rows:
        s = db.get(models.Story, row.story_id)
        if s is None:
            continue
        d = _story_dict(db, s, user.telegram_id)
        d["expired"] = bool(
            s.created_at is not None and s.created_at <= cutoff)
        stories.append(d)
    owner = db.get(models.User, h.user_id)
    return {"highlight": _highlight_out(db, h, user.telegram_id),
            "owner": _brief_user(owner) if owner else None,
            "stories": stories}


@app.post("/highlights/{hid}/rename")
def rename_highlight(hid: int, body: HighlightIn,
                     user: models.User = Depends(current_user),
                     db: Session = Depends(get_db)):
    h = db.get(models.StoryHighlight, hid)
    if h is None:
        raise HTTPException(404, "Highlight not found")
    if h.user_id != user.telegram_id:
        raise HTTPException(403, "Not your highlight")
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(400, "A highlight needs a title")
    h.title = title
    db.commit()
    return _highlight_out(db, h, user.telegram_id)


@app.delete("/highlights/{hid}")
def delete_highlight(hid: int, user: models.User = Depends(current_user),
                     db: Session = Depends(get_db)):
    h = db.get(models.StoryHighlight, hid)
    if h is None:
        raise HTTPException(404, "Highlight not found")
    real_id = getattr(user, "_real_id", user.telegram_id)
    admin_own = user.telegram_id in settings.ADMIN_IDS \
        and real_id == user.telegram_id
    if h.user_id != user.telegram_id and not admin_own:
        raise HTTPException(403, "Not your highlight")
    db.query(models.HighlightStory).filter_by(
        highlight_id=h.id).delete()
    db.delete(h)
    db.commit()
    return {"ok": True}


@app.post("/highlights/{hid}/stories")
def add_highlight_stories(hid: int, body: HighlightIn,
                          user: models.User = Depends(current_user),
                          db: Session = Depends(get_db)):
    h = db.get(models.StoryHighlight, hid)
    if h is None:
        raise HTTPException(404, "Highlight not found")
    if h.user_id != user.telegram_id:
        raise HTTPException(403, "Not your highlight")
    ids = _highlight_story_ids(body)
    if not ids:
        raise HTTPException(400, "Pick at least one story")
    existing = db.query(models.HighlightStory).filter_by(
        highlight_id=h.id).all()
    have = {r.story_id for r in existing}
    if len(have) + len([s for s in ids if s not in have]) > 50:
        raise HTTPException(400, "At most 50 stories per highlight")
    found = db.query(models.Story).filter(
        models.Story.id.in_(ids),
        models.Story.user_id == user.telegram_id).all()
    if len({s.id for s in found}) != len(ids):
        raise HTTPException(400, "Only your own stories can be added")
    pos = max([r.position for r in existing], default=-1) + 1
    for sid in ids:
        if sid in have:
            continue
        db.add(models.HighlightStory(
            highlight_id=h.id, story_id=sid, position=pos))
        pos += 1
    db.commit()
    return _highlight_out(db, h, user.telegram_id)


@app.delete("/highlights/{hid}/stories/{sid}")
def remove_highlight_story(hid: int, sid: int,
                           user: models.User = Depends(current_user),
                           db: Session = Depends(get_db)):
    h = db.get(models.StoryHighlight, hid)
    if h is None:
        raise HTTPException(404, "Highlight not found")
    if h.user_id != user.telegram_id:
        raise HTTPException(403, "Not your highlight")
    db.query(models.HighlightStory).filter_by(
        highlight_id=h.id, story_id=sid).delete()
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
    "your own posts also have Edit and Delete there. Tap Repost "
    "to share a post to your own feed, and Reply under any "
    "comment to answer it directly. Views "
    "count once per person. A little way down the Explore "
    "feed, a Suggested for you card suggests people to "
    "follow — tap Follow on anyone there, or tap their "
    "photo or name to open their profile first; the cross "
    "hides the card for now. "
    "TRENDING: the sidebar has a Trending page — the hottest "
    "posts of the last 7 days, ranked by recent likes, comments "
    "and views, with the top hashtags on top; tap a hashtag to "
    "see every post with that tag. "
    "CREATOR TOOLS: pin one of your own posts from its menu "
    "and it shows first on your profile with a 📌 badge; save "
    "an unfinished post as a draft from the composer and finish "
    "it later from My drafts in your profile extras; like any "
    "comment with the little heart under it; and add a poll to "
    "a post from the composer — members vote once, and the "
    "results show live as percentages. "
    "POSTING: write from the Feed composer, or send a photo or "
    "video directly to @NexoraSocial_bot in chat with a "
    "caption and it becomes your post — the most reliable way "
    "to post videos. A post earns 10 points. "
    "VIDEOS: the Videos tab is full-screen reels — swipe to "
    "move, tap to pause, the speaker button toggles sound; "
    "liking, commenting and the menu work like the Feed. "
    "DESIGN: a gallery of designs with their prompts. Tap a "
    "design to read its prompt and copy it; HOLD a design for "
    "Similar, WhatsApp, Share and Save. Pull down to refresh — "
    "designs are ordered by your taste. Only the admin adds "
    "designs. "
    "POINTS: daily tasks on the Tasks page — check-in 20 "
    "points, the follow task 10, the comment task 5, the react "
    "task 10, the ad task 20, each once a day, press Claim. The "
    "balance and history are on the profile in the My Points "
    "card. A referral earns 20 points when the friend makes "
    "their first post. "
    "REFERRALS: your invite link is on your profile. A "
    "referral is qualified when the friend joins AND makes a "
    "first post. "
    "MONETIZATION: the profile card shows 6 targets — 500 "
    "followers, 12 qualified referrals, 25 posts, an account "
    "14 days old, 5000 lifetime points, and a 30-day check-in "
    "streak (one missed day resets it). Once unlocked, the member "
    "can request a crypto payout from the same card. "
    "PAYOUT: once monetization is unlocked, save your crypto "
    "wallet (TON, Gram or USDT) in the Monetization card on your "
    "profile, then request a payout in points — one request at a "
    "time. The admin reviews it, sets the crypto amount, pays it "
    "manually in crypto and records the transaction; the points "
    "leave your balance when the request is approved. Never quote "
    "a points-to-money rate — the admin sets the amount. "
    "TIPS: tap the ⭐ Tip button on any post or profile to tip "
    "its creator with Telegram Stars (10, 50, 100, 250 or a "
    "custom amount up to 10000). The invoice arrives in the "
    "member's Telegram chat with the bot — the payment happens "
    "there, not inside the app. Stars land in the bot's balance; "
    "creators are paid out through the crypto payout flow. "
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
