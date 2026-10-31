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

from datetime import datetime, timedelta

from . import models, notify
from .config import (DAILY_TASKS, MONETIZATION, OFFICIAL_FOLLOWER_BASE,
                     OFFICIAL_ID, settings)
from .db import Base, engine, get_db
from .security import validate_init_data
from .services import award_points, register_post
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
        "is_verified": bool(user.is_verified),
        "followers": followers,
        "following": following,
        "posts": posts,
        "bot_username": settings.BOT_USERNAME,
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
            "is_verified": bool(u.is_verified)} for i, u in enumerate(rows)]
    mine = next((r for r in out if r["telegram_id"] == user.telegram_id), None)
    if mine is None:
        higher = db.query(models.User).filter(
            models.User.points_balance > user.points_balance).count()
        mine = {"rank": higher + 1, "telegram_id": user.telegram_id,
                "first_name": user.first_name, "username": user.username,
                "points": user.points_balance,
                "is_verified": bool(user.is_verified)}
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
    targets = db.query(models.User).filter_by(is_banned=False) \
        .filter(models.User.telegram_id != OFFICIAL_ID).all()
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
