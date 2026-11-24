"""Shared post/points logic used by BOTH the API (app/main.py) and the bot
(app/bot.py), so a post made by sending a photo to the bot follows exactly
the same rules as one made in the Mini App (PRD sections 4-5)."""
import re

from sqlalchemy import func

from . import models, notify
from .config import POINTS

HASHTAG_RE = re.compile(r"#(\w+)")

MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{3,32})")


def extract_mentions(text):
    """'@alice and @Bob!' -> ['alice', 'bob'] (lowercase, deduped,
    order preserved). Unknown names are kept here — resolution
    against real usernames happens in sync_mentions."""
    seen = []
    for name in MENTION_RE.findall(text or ""):
        low = name.lower()
        if low not in seen:
            seen.append(low)
    return seen


def _mention_visible(db, mentioned_id, post_author_id):
    """Phase 136: a mention inside a private author's post is
    only real for followers (and the author themself)."""
    if mentioned_id == post_author_id:
        return True
    author = db.get(models.User, post_author_id)
    if author is None or not getattr(author, "is_private", False):
        return True
    return db.query(models.Follow).filter_by(
        follower_id=mentioned_id,
        following_id=post_author_id).first() is not None


def _mention_blocked(db, a, b):
    return db.query(models.UserBlock).filter_by(
        blocker_id=a, blocked_id=b).first() is not None


def sync_mentions(db, author_id, post_id, comment_id, text,
                  post_author_id):
    """Phase 170: reconcile the Mention rows for one post (or one
    comment) with the @usernames in text, and write an in-app
    notification for each NEW mention. Returns the list of newly
    mentioned user ids — callers send the bot push for those.
    Exactly one of post_id / comment_id is set. Rules: only
    existing usernames count (case-insensitive lookup); unknown
    names stay plain text; self-mentions get a row but no
    notification; blocked either way and private-invisible
    mentions are ignored entirely; a re-edit notifies only the
    mentions that are new. The bot push is the caller's job —
    this also runs in sync contexts (scheduled-post sweeper)."""
    if post_id is not None:
        rows = db.query(models.Mention).filter_by(
            post_id=post_id).all()
    else:
        rows = db.query(models.Mention).filter_by(
            comment_id=comment_id).all()
    existing = {r.mentioned_id for r in rows}
    notif_post_id = post_id
    if comment_id is not None:
        cm = db.get(models.Comment, comment_id)
        notif_post_id = cm.post_id if cm else None
    targets = []
    seen = set()
    for name in extract_mentions(text):
        u = db.query(models.User).filter(
            func.lower(models.User.username) == name).first()
        if u is None or u.telegram_id in seen:
            continue
        seen.add(u.telegram_id)
        if u.telegram_id == author_id:
            targets.append(u)
            continue
        if _mention_blocked(db, author_id, u.telegram_id) or \
                _mention_blocked(db, u.telegram_id, author_id):
            continue
        if not _mention_visible(db, u.telegram_id, post_author_id):
            continue
        targets.append(u)
    wanted = {u.telegram_id for u in targets}
    for r in rows:
        if r.mentioned_id not in wanted:
            db.delete(r)
    new_ids = []
    for u in targets:
        if u.telegram_id not in existing:
            db.add(models.Mention(
                post_id=post_id, comment_id=comment_id,
                mentioned_id=u.telegram_id))
            new_ids.append(u.telegram_id)
            if u.telegram_id != author_id:
                notify.record(
                    db, u.telegram_id, "mention", actor_id=author_id,
                    post_id=notif_post_id,
                    text=("mentioned you in a comment: "
                          if comment_id is not None
                          else "mentioned you in a post: ")
                    + (text or "")[:80])
    db.commit()
    return new_ids


def extract_hashtags(caption: str) -> str:
    """'#Hello #world #hello' -> 'hello world' (lowercase, deduped, no #)."""
    seen = []
    for tag in HASHTAG_RE.findall(caption or ""):
        t = tag.lower()
        if t not in seen:
            seen.append(t)
    return " ".join(seen)


BANNED_WORD_MESSAGE = "This text contains a word that isn't allowed here."


def banned_word_in(db, text):
    """Phase 142: return the banned word found in text (a
    case-insensitive substring match on the lowercased text),
    else None. The list is admin-managed and small, so a full
    read per check is fine."""
    low = (text or "").lower()
    if not low:
        return None
    for row in db.query(models.BannedWord).all():
        w = (row.word or "").strip().lower()
        if w and w in low:
            return w
    return None


def award_points(db, user_id, amount, reason, ref_id=None):
    """Every points change writes a ledger row AND updates the balance —
    the ledger is the auditable record (PRD section 5)."""
    db.add(models.PointsLedger(user_id=user_id, amount=amount,
                               reason=reason, ref_id=ref_id))
    u = db.get(models.User, user_id)
    if u is not None:
        u.points_balance = (u.points_balance or 0) + amount


def register_post(db, author, ptype, media_file_id, caption,
                  thumb_file_id=None, extra_media=None):
    """extra_media (Phase 171): the FULL ordered album list of
    (file_id, media_type) — position 0 is media_file_id itself.
    Single-media posts pass None and get no rows."""
    """Create a post for author (a models.User). Returns
    (post, is_first_post, referral_qualified_now).
    Every post earns post points (Phase 113); on the author's FIRST
    post ever a pending referral qualifies, paying the referrer
    (PRD section 5). Soft-deleted posts still count toward
    'first ever'."""
    author_id = author.telegram_id
    is_first = db.query(models.Post).filter_by(user_id=author_id).count() == 0
    post = models.Post(user_id=author_id, type=ptype,
                       media_file_id=media_file_id,
                       thumb_file_id=thumb_file_id,
                       caption=caption or "",
                       hashtags=extract_hashtags(caption or ""))
    db.add(post)
    db.commit()
    db.refresh(post)
    if extra_media:
        for i, (fid, mtype) in enumerate(extra_media):
            db.add(models.PostMedia(post_id=post.id, file_id=fid,
                                    media_type=mtype, position=i))
        db.commit()
    qualified = False
    # Phase 113 (owner): every post earns 10 points, not just the
    # first. Referral qualification stays first-post-only below.
    award_points(db, author_id, POINTS["post"], "post", ref_id=post.id)
    if is_first:
        ref = db.query(models.Referral).filter_by(new_user_id=author_id).first()
        if ref is not None and not ref.qualified:
            ref.qualified = True
            qualified = True
            award_points(db, ref.referrer_id, POINTS["referral"],
                         "referral", ref_id=ref.id)
    db.commit()
    return post, is_first, qualified
