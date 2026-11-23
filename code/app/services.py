"""Shared post/points logic used by BOTH the API (app/main.py) and the bot
(app/bot.py), so a post made by sending a photo to the bot follows exactly
the same rules as one made in the Mini App (PRD sections 4-5)."""
import re

from . import models
from .config import POINTS

HASHTAG_RE = re.compile(r"#(\w+)")


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
                  thumb_file_id=None, via_inbox=False):
    """Create a post for author (a models.User). Returns
    (post, is_first_post, referral_qualified_now). via_inbox
    marks posts written in the Nexora Inbox page's own box
    (Phase 168) — they are normal posts, so they show in
    the feed and on the Nexora Inbox page.
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
                       hashtags=extract_hashtags(caption or ""),
                       via_inbox=via_inbox)
    db.add(post)
    db.commit()
    db.refresh(post)
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
