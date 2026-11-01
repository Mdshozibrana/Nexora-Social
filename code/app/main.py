"""FastAPI backend: auth, feed, posts, likes, comments, profiles, follow,
referrals, points, search, reports, media proxy, and the Mini App host.
Only the PRD section-8 admin endpoints remain for a later phase."""
import asyncio
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import (Depends, FastAPI, File, Form, Header, HTTPException,
                     Request, UploadFile)
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, inspect, or_, text
from sqlalchemy.orm import Session

from datetime import datetime, timedelta

from . import geoip, imgconv, models, notify, tgupload, videoutil
from .config import (DAILY_TASKS, MONETIZATION, OFFICIAL_FOLLOWER_BASE,
                     OFFICIAL_ID, OFFICIAL_NAME,
                     VERIFICATION_MIN_FOLLOWERS, settings)
from .db import Base, SessionLocal, engine, get_db
from .security import validate_init_data
from .services import award_points, register_post
from .users import get_or_create_user

Base.metadata.create_all(bind=engine)


def _migrate():
    """create_all never alters existing tables, so columns added after
    the first deploy (Phase 19: country / language_code / last_seen_at
    on users) are added here, once, on whichever dialect is live."""
    existing = {c["name"] for c in inspect(engine).get_columns("users")}
    wanted = {"country": "VARCHAR(64)", "language_code": "VARCHAR(16)",
              "last_seen_at": "TIMESTAMP", "is_managed": "BOOLEAN"}
    with engine.begin() as conn:
        for name, ddl in wanted.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))


_migrate()

app = FastAPI(title=settings.APP_NAME)


@app.middleware("http")
async def webapp_no_cache(request, call_next):
    """Phase 23: the Mini App shell must never be served stale from a
    webview cache — the owner repeatedly missed new features because
    Telegram kept the old app.js. no-cache forces revalidation on
    every open while keeping etags, so loads stay fast."""
    response = await call_next(request)
    if request.url.path.startswith("/webapp"):
        response.headers["Cache-Control"] = "no-cache"
    return response
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
    initData: str


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
        raise HTTPException(401, "Invalid Telegram login")
    user, _ = get_or_create_user(db, tg_user)
    if user.is_banned:
        raise HTTPException(403, "Account suspended")
    # Phase 19: "last seen" powers the admin dashboard's activity
    # figures. Written at most once a minute per member, so the extra
    # UPDATE stays negligible.
    now = datetime.utcnow()
    if user.last_seen_at is None or (now - user.last_seen_at).total_seconds() >= 60:
        user.last_seen_at = now
        db.commit()
    user = _resolve_act_as(db, user, x_act_as)
    if user.last_seen_at is None or (now - user.last_seen_at).total_seconds() >= 60:
        user.last_seen_at = now
        db.commit()
    return user


@app.get("/health")
def health():
    return {"ok": True, "app": settings.APP_NAME}


@app.post("/auth")
async def auth(body: AuthIn, request: Request,
               x_act_as: str = Header(default=""),
               db: Session = Depends(get_db)):
    tg_user = validate_init_data(body.initData, settings.BOT_TOKEN)
    if not tg_user:
        raise HTTPException(401, "Invalid Telegram login")
    user, is_new = get_or_create_user(db, tg_user)
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
        "adsgram_block_id": settings.ADSGRAM_BLOCK_ID,
    }


@app.get("/feed")
def feed(tab: str = "explore", type: str = "", cursor: int = 0,
         user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(models.Post).filter_by(is_deleted=False)
    if type in ("photo", "video", "text"):
        q = q.filter_by(type=type)
    if tab == "following":
        ids = [f.following_id for f in
               db.query(models.Follow).filter_by(follower_id=user.telegram_id)]
        q = q.filter(models.Post.user_id.in_(ids or [-1]))
    if cursor:
        q = q.filter(models.Post.id < cursor)
    rows = q.order_by(models.Post.id.desc()).limit(20).all()
    liked = liked_ids(db, user.telegram_id, rows)
    saved = saved_ids(db, user.telegram_id, rows)
    out = [post_dict(db, p, liked=p.id in liked, saved=p.id in saved)
           for p in rows]
    return {"posts": out, "next_cursor": rows[-1].id if len(rows) == 20 else None}


# ---------------------------------------------------------------------------
# Posts, likes, comments (PRD section 4, MVP items 3-5)
# ---------------------------------------------------------------------------

def post_dict(db, p, liked=False, saved=False):
    author = db.get(models.User, p.user_id)
    return {
        "id": p.id, "type": p.type, "media_file_id": p.media_file_id,
        "caption": p.caption, "hashtags": p.hashtags,
        "like_count": p.like_count, "comment_count": p.comment_count,
        "liked": liked,
        "saved": saved,
        "author_id": p.user_id,
        "author_name": author.first_name if author else "",
        "author_username": author.username if author else None,
        "author_verified": bool(author and author.is_verified),
        "author_photo": author.photo_file_id if author else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


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


class PostIn(BaseModel):
    type: str = "text"
    media_file_id: Optional[str] = None
    caption: str = ""


@app.post("/posts")
def create_post(body: PostIn, user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
    if body.type not in ("photo", "video", "text"):
        raise HTTPException(400, "type must be photo, video or text")
    post, _, _ = register_post(db, user, body.type, body.media_file_id,
                               body.caption)
    return post_dict(db, post)


async def _send_to_telegram(user, filename, data, content_type):
    try:
        return await tgupload.upload_media(
            user.telegram_id, filename, data, content_type)
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


async def _finish_video_post(user_id, src_path, caption):
    dst = src_path + ".mp4"
    try:
        async with _transcode_sem:
            await asyncio.to_thread(videoutil.transcode_to_mp4,
                                    src_path, dst)
        with open(dst, "rb") as f:
            mp4 = f.read()
        _, file_id = await tgupload.upload_media(
            user_id, "video.mp4", mp4, "video/mp4")
        db = SessionLocal()
        try:
            user = db.get(models.User, user_id)
            if user is not None and not user.is_banned:
                post, _, _ = register_post(db, user, "video", file_id,
                                           caption)
                notify.record(db, user_id, "post_live", post_id=post.id,
                              text="Your video is now live on "
                                   "Nexora Social!")
        finally:
            db.close()
        await notify.send_message(
            user_id, "✅ Your video is now live on Nexora Social!")
    except tgupload.TelegramUploadError as e:
        msg = ("Open @NexoraSocial_bot once and press Start, then try "
               "uploading your video again"
               if e.kind == "not_started" else
               "Your video could not be posted — please try again")
        await notify.send_message(user_id, "⚠️ " + msg)
    except videoutil.VideoError as e:
        await notify.send_message(
            user_id, "⚠️ Your video could not be posted: " + str(e))
    except Exception:
        await notify.send_message(
            user_id, "⚠️ Your video could not be posted — please try again")
    finally:
        for p in (src_path, dst):
            try:
                os.unlink(p)
            except OSError:
                pass


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
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
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
        user.telegram_id, src, caption))
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
    kind, file_id = await _telegram_upload_or_400(
        user, file, caption.strip())
    if kind == "processing":
        body = {"status": "processing",
                "detail": "Video received — it will appear in the feed "
                          "shortly, and the bot will message you"}
        _dedupe_put(user.telegram_id, x_upload_id, 202, body)
        return JSONResponse(status_code=202, content=body)
    post, _, _ = register_post(db, user, kind, file_id, caption.strip())
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


@app.post("/posts/{post_id}/like")
async def toggle_like(post_id: int, user: models.User = Depends(current_user),
                      db: Session = Depends(get_db)):
    p = get_live_post(db, post_id)
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
    """Send a post to another member inside the app (owner request,
    Oct 31): it lands in their 'Shared with me' inbox and they get a
    bot notification."""
    p = get_live_post(db, post_id)
    if body.to_user_id == user.telegram_id:
        raise HTTPException(400, "You cannot share to yourself")
    target = db.get(models.User, body.to_user_id)
    if target is None:
        raise HTTPException(404, "User not found")
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
    text: str


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
    rows = db.query(models.Comment).filter_by(post_id=p.id) \
        .order_by(models.Comment.id.asc()).all()
    return {"comments": [comment_dict(db, cm) for cm in rows]}


@app.post("/posts/{post_id}/comments")
async def add_comment(post_id: int, body: CommentIn,
                      user: models.User = Depends(current_user),
                      db: Session = Depends(get_db)):
    p = get_live_post(db, post_id)
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
    followers = db.query(models.Follow).filter_by(following_id=telegram_id).count()
    if telegram_id == OFFICIAL_ID:
        followers += OFFICIAL_FOLLOWER_BASE  # official account starts at 10k
    following_count = db.query(models.Follow).filter_by(follower_id=telegram_id).count()
    posts = db.query(models.Post).filter_by(
        user_id=telegram_id, is_deleted=False).count()
    is_following = db.query(models.Follow).filter_by(
        follower_id=user.telegram_id, following_id=telegram_id).first() is not None
    return {
        "telegram_id": target.telegram_id,
        "first_name": target.first_name,
        "username": target.username,
        "bio": target.bio,
        "photo_file_id": target.photo_file_id,
        "points": target.points_balance,
        "is_verified": bool(target.is_verified),
        "is_official": telegram_id == OFFICIAL_ID,
        "posts": posts,
        "followers": followers,
        "following_count": following_count,
        # "following" is the flag: does the current user follow this profile.
        "following": is_following,
    }


@app.post("/users/{telegram_id}/follow")
async def toggle_follow(telegram_id: int, user: models.User = Depends(current_user),
                        db: Session = Depends(get_db)):
    if telegram_id == user.telegram_id:
        raise HTTPException(400, "You cannot follow yourself")
    if db.get(models.User, telegram_id) is None:
        raise HTTPException(404, "User not found")
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
    _, file_id = await _telegram_upload_or_400(user, file)
    user.photo_file_id = file_id
    db.commit()
    return {"photo_file_id": file_id}


@app.get("/me/referrals")
def my_referrals(user: models.User = Depends(current_user),
                 db: Session = Depends(get_db)):
    rows = db.query(models.Referral).filter_by(referrer_id=user.telegram_id) \
        .order_by(models.Referral.id.asc()).all()
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
    return {"referrals": out, "total": len(out)}


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
    q = q.strip()
    if q.startswith("#"):
        tag = q[1:].lower()
        if not tag:
            return {"users": [], "posts": []}
        rows = db.query(models.Post).filter_by(is_deleted=False) \
            .order_by(models.Post.id.desc()).limit(100).all()
        matched = [p for p in rows if tag in (p.hashtags or "").split()][:20]
        liked = liked_ids(db, user.telegram_id, matched)
        saved = saved_ids(db, user.telegram_id, matched)
        return {"users": [], "posts": [post_dict(db, p, liked=p.id in liked,
                                                 saved=p.id in saved)
                                       for p in matched]}
    if not q:
        return {"users": [], "posts": []}
    like = f"%{q}%"
    users = db.query(models.User).filter(
        (models.User.first_name.ilike(like))
        | (models.User.username.ilike(like))).limit(20).all()
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
    reason: str = ""


@app.post("/reports")
def create_report(body: ReportIn, user: models.User = Depends(current_user),
                  db: Session = Depends(get_db)):
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
    if db.get(models.User, telegram_id) is None:
        raise HTTPException(404, "User not found")
    q = db.query(models.Post).filter_by(user_id=telegram_id, is_deleted=False)
    if cursor:
        q = q.filter(models.Post.id < cursor)
    rows = q.order_by(models.Post.id.desc()).limit(20).all()
    liked = liked_ids(db, user.telegram_id, rows)
    saved = saved_ids(db, user.telegram_id, rows)
    return {"posts": [post_dict(db, p, liked=p.id in liked,
                                saved=p.id in saved) for p in rows],
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
    posts = db.query(models.Post).filter_by(
        user_id=user.telegram_id, is_deleted=False).count()
    age_days = (datetime.utcnow() - user.created_at).days \
        if user.created_at else 0
    earned = sum(e.amount for e in db.query(models.PointsLedger).filter_by(
        user_id=user.telegram_id).all() if e.amount > 0)
    checks = [
        {"key": "followers", "label": "Followers",
         "current": followers, "required": MONETIZATION["followers"]},
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

@app.post("/me/heartbeat")
def heartbeat(user: models.User = Depends(current_user),
              db: Session = Depends(get_db)):
    """The Mini App beats every ~30s while open. Each beat credits the
    seconds since the previous beat (capped at 120s, so a forgotten
    background tab cannot inflate the numbers); a beat after a longer
    gap starts a new session instead of crediting the gap."""
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
        raise HTTPException(403, "Admins only")
    return user


class BanIn(BaseModel):
    telegram_id: int
    banned: bool = True


@app.post("/admin/ban")
def admin_ban(body: BanIn, admin: models.User = Depends(admin_user),
              db: Session = Depends(get_db)):
    if body.banned and (body.telegram_id == OFFICIAL_ID
                        or body.telegram_id in settings.ADMIN_IDS):
        raise HTTPException(400, "The official account and admins cannot be banned")
    target = db.get(models.User, body.telegram_id)
    if target is None:
        raise HTTPException(404, "User not found")
    target.is_banned = body.banned
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
        like = f"%{q}%"
        query = query.filter(or_(
            models.User.first_name.ilike(like),
            models.User.username.ilike(like),
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
    first_name: str
    username: Optional[str] = None
    bio: Optional[str] = None
    country: Optional[str] = None
    language_code: Optional[str] = None
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
        uname = body.username.strip() if body.username else None
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
    db.commit()
    return {"deleted": telegram_id}


@app.get("/admin/posts")
def admin_posts(limit: int = 30, admin: models.User = Depends(admin_user),
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
def admin_remove_post(post_id: int, admin: models.User = Depends(admin_user),
                      db: Session = Depends(get_db)):
    p = db.get(models.Post, post_id)
    if p is None or p.is_deleted:
        raise HTTPException(404, "Post not found")
    p.is_deleted = True
    db.commit()
    return {"ok": True, "id": p.id}


@app.get("/admin/reports")
def admin_reports(status: str = "open",
                  admin: models.User = Depends(admin_user),
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
                         admin: models.User = Depends(admin_user),
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
    db.commit()
    return {"ok": True, "id": r.id, "status": r.status}


class BroadcastIn(BaseModel):
    text: str


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
                      models.Notification):
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
                  models.VerificationRequest, models.DesignLike):
        db.query(model).filter_by(user_id=tid) \
            .delete(synchronize_session=False)
    db.delete(target)


class PointsAdjustIn(BaseModel):
    delta: int


class VerifyToggleIn(BaseModel):
    verified: bool


class ProfileEditIn(BaseModel):
    first_name: Optional[str] = None
    bio: Optional[str] = None


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
        u.first_name = name[:128]
    if body.bio is not None:
        u.bio = body.bio.strip()[:1000]
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
    db.commit()
    return {"deleted": telegram_id}


@app.get("/admin/comments")
def admin_comments(admin: models.User = Depends(admin_user),
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
                         admin: models.User = Depends(admin_user),
                         db: Session = Depends(get_db)):
    cm = db.get(models.Comment, comment_id)
    if cm is None:
        raise HTTPException(404, "Comment not found")
    post = db.get(models.Post, cm.post_id)
    if post is not None and post.comment_count > 0:
        post.comment_count -= 1
    db.delete(cm)
    db.commit()
    return {"ok": True, "removed": comment_id}


# ---------------------------------------------------------------------------
# Phase 25: the Design gallery (owner: a Design tab in the nav,
# Pinterest-style premium). Designs are posted ONLY as the official
# account — the admin switches to Official (composer switch, drawer
# or Admin Panel) and uploads image + prompt here. Members browse
# and like.
# ---------------------------------------------------------------------------

def _design_dict(db, design, user):
    liked = db.query(models.DesignLike).filter_by(
        design_id=design.id, user_id=user.telegram_id).first() \
        is not None
    return {"id": design.id, "image_file_id": design.image_file_id,
            "prompt": design.prompt,
            "like_count": design.like_count, "liked": liked,
            "author_id": OFFICIAL_ID, "author_name": OFFICIAL_NAME,
            "created_at": design.created_at.isoformat()
            if design.created_at else None}


def _remove_design(db, design):
    db.query(models.DesignLike).filter_by(
        design_id=design.id).delete(synchronize_session=False)
    db.delete(design)


@app.get("/designs")
def list_designs(cursor: int = 0, limit: int = 20,
                 user: models.User = Depends(current_user),
                 db: Session = Depends(get_db)):
    q = db.query(models.Design)
    if cursor:
        q = q.filter(models.Design.id < cursor)
    rows = q.order_by(models.Design.id.desc()) \
        .limit(max(1, min(limit, 40))).all()
    return {"designs": [_design_dict(db, d, user) for d in rows],
            "next_cursor": rows[-1].id if len(rows) == limit else None}


@app.post("/designs/upload")
async def upload_design(prompt: str = Form(""),
                        file: UploadFile = File(...),
                        x_upload_id: str = Header(default=""),
                        user: models.User = Depends(current_user),
                        db: Session = Depends(get_db)):
    hit = _dedupe_get(user.telegram_id, x_upload_id)
    if hit:
        return JSONResponse(status_code=hit[0], content=hit[1])
    if user.telegram_id != OFFICIAL_ID:
        raise HTTPException(
            403, "Designs are posted as the Official account — "
                 "switch to Official first")
    kind, file_id = await _telegram_upload_or_400(
        user, file, prompt.strip())
    if kind != "photo":
        raise HTTPException(400, "Designs must be images only")
    design = models.Design(image_file_id=file_id,
                           prompt=prompt.strip()[:2000])
    db.add(design)
    db.commit()
    db.refresh(design)
    body = _design_dict(db, design, user)
    _dedupe_put(user.telegram_id, x_upload_id, 200, body)
    return body


@app.post("/designs/{design_id}/like")
def like_design(design_id: int,
                user: models.User = Depends(current_user),
                db: Session = Depends(get_db)):
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
                        admin: models.User = Depends(admin_user),
                        db: Session = Depends(get_db)):
    design = db.get(models.Design, design_id)
    if design is None:
        raise HTTPException(404, "Design not found")
    _remove_design(db, design)
    db.commit()
    return {"ok": True, "removed": design_id}


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
    return StreamingResponse(body(), status_code=resp.status_code,
                             headers=headers,
                             media_type=resp.headers.get("content-type"))


if WEBAPP_DIR.exists():
    app.mount("/webapp", StaticFiles(directory=WEBAPP_DIR, html=True), name="webapp")
