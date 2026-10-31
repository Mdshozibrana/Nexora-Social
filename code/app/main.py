"""FastAPI backend: auth, feed, posts, likes, comments, profiles, follow,
referrals, points, search, reports, media proxy, and the Mini App host.
Only the PRD section-8 admin endpoints remain for a later phase."""
from pathlib import Path
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import models, notify
from .config import settings
from .db import Base, engine, get_db
from .security import validate_init_data
from .services import register_post
from .users import get_or_create_user

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.APP_NAME)
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


def current_user(x_init_data: str = Header(default=""), db: Session = Depends(get_db)):
    tg_user = validate_init_data(x_init_data, settings.BOT_TOKEN)
    if not tg_user:
        raise HTTPException(401, "Invalid Telegram login")
    user, _ = get_or_create_user(db, tg_user)
    if user.is_banned:
        raise HTTPException(403, "Account suspended")
    return user


@app.get("/health")
def health():
    return {"ok": True, "app": settings.APP_NAME}


@app.post("/auth")
def auth(body: AuthIn, db: Session = Depends(get_db)):
    tg_user = validate_init_data(body.initData, settings.BOT_TOKEN)
    if not tg_user:
        raise HTTPException(401, "Invalid Telegram login")
    user, _ = get_or_create_user(db, tg_user)
    followers = db.query(models.Follow).filter_by(following_id=user.telegram_id).count()
    following = db.query(models.Follow).filter_by(follower_id=user.telegram_id).count()
    posts = db.query(models.Post).filter_by(user_id=user.telegram_id, is_deleted=False).count()
    return {
        "telegram_id": user.telegram_id,
        "first_name": user.first_name,
        "username": user.username,
        "bio": user.bio,
        "points": user.points_balance,
        "followers": followers,
        "following": following,
        "posts": posts,
        "bot_username": settings.BOT_USERNAME,
    }


@app.get("/feed")
def feed(tab: str = "explore", cursor: int = 0,
         user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(models.Post).filter_by(is_deleted=False)
    if tab == "following":
        ids = [f.following_id for f in
               db.query(models.Follow).filter_by(follower_id=user.telegram_id)]
        q = q.filter(models.Post.user_id.in_(ids or [-1]))
    if cursor:
        q = q.filter(models.Post.id < cursor)
    rows = q.order_by(models.Post.id.desc()).limit(20).all()
    liked = liked_ids(db, user.telegram_id, rows)
    out = [post_dict(db, p, liked=p.id in liked) for p in rows]
    return {"posts": out, "next_cursor": rows[-1].id if len(rows) == 20 else None}


# ---------------------------------------------------------------------------
# Posts, likes, comments (PRD section 4, MVP items 3-5)
# ---------------------------------------------------------------------------

def post_dict(db, p, liked=False):
    author = db.get(models.User, p.user_id)
    return {
        "id": p.id, "type": p.type, "media_file_id": p.media_file_id,
        "caption": p.caption, "hashtags": p.hashtags,
        "like_count": p.like_count, "comment_count": p.comment_count,
        "liked": liked,
        "author_id": p.user_id,
        "author_name": author.first_name if author else "",
        "author_username": author.username if author else None,
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
    return {"liked": liked, "like_count": p.like_count}


class CommentIn(BaseModel):
    text: str


def comment_dict(db, cm):
    author = db.get(models.User, cm.user_id)
    return {
        "id": cm.id, "post_id": cm.post_id, "user_id": cm.user_id,
        "author_name": author.first_name if author else "",
        "author_username": author.username if author else None,
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
    if existing:
        db.delete(existing)
        now_following = False
    else:
        db.add(models.Follow(follower_id=user.telegram_id,
                             following_id=telegram_id))
        now_following = True
    db.commit()
    followers = db.query(models.Follow).filter_by(following_id=telegram_id).count()
    if now_following:
        await notify.notify_user(
            db, telegram_id, "follow",
            f"\U0001F465 {user.first_name} started following you.")
    return {"following": now_following, "followers": followers}


# ---------------------------------------------------------------------------
# Referrals, points, search, reports (PRD sections 4-5, MVP items 8-10)
# ---------------------------------------------------------------------------

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
        return {"users": [], "posts": [post_dict(db, p, liked=p.id in liked)
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
    return {"posts": [post_dict(db, p, liked=p.id in liked) for p in rows],
            "next_cursor": rows[-1].id if len(rows) == 20 else None}


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
    target = db.get(models.User, body.telegram_id)
    if target is None:
        raise HTTPException(404, "User not found")
    target.is_banned = body.banned
    db.commit()
    return {"telegram_id": target.telegram_id, "is_banned": target.is_banned}


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
    targets = db.query(models.User).filter_by(is_banned=False).all()
    sent = 0
    for u in targets:
        if await notify.send_message(u.telegram_id, text):
            sent += 1
            db.add(models.NotificationLog(user_id=u.telegram_id,
                                           type="broadcast"))
    db.commit()
    return {"recipients": len(targets), "sent": sent}


@app.get("/media/{file_id}")
async def media_proxy(file_id: str):
    """Stream a Telegram-hosted file to the Mini App. The bot token is used
    only in server-side requests and never appears in a client-visible URL.
    file_id values are long unguessable strings, the same protection
    Telegram's own file links rely on. Needs a live token, so this path is
    verified at deploy time; without a token it answers 503."""
    if not settings.BOT_TOKEN:
        raise HTTPException(503, "Media unavailable until the bot is live")
    api = f"https://api.telegram.org/bot{settings.BOT_TOKEN}"
    async with httpx.AsyncClient(timeout=30) as client:
        info = await client.get(f"{api}/getFile", params={"file_id": file_id})
        if info.status_code != 200:
            raise HTTPException(404, "File not found")
        file_path = info.json()["result"]["file_path"]
        req = client.build_request("GET", f"{api}/file/{file_path}")
        resp = await client.send(req, stream=True)
        if resp.status_code != 200:
            raise HTTPException(404, "File not found")
        headers = {}
        if resp.headers.get("content-type"):
            headers["content-type"] = resp.headers["content-type"]
        if resp.headers.get("content-length"):
            headers["content-length"] = resp.headers["content-length"]
        return StreamingResponse(resp.aiter_bytes(), headers=headers,
                                 media_type=resp.headers.get("content-type"))


if WEBAPP_DIR.exists():
    app.mount("/webapp", StaticFiles(directory=WEBAPP_DIR, html=True), name="webapp")
