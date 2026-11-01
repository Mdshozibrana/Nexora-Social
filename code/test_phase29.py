"""Phase-29 tests: second-pass security audit fixes (R1–R5).
R1 comment list capped at the latest 500 · R2 referral list capped
with a true total · R3 rate budgets on /ads/shown + /me/heartbeat ·
R5 member blocking: mutual invisibility, follow removal, and
interaction refusals, with unblock restoring access."""
import hashlib, hmac, json, os, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase29.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app
from app import models, ratelimit
from app.config import RATE_LIMITS
from app.db import SessionLocal


def make_init_data(user):
    params = {"auth_date": str(int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    d = make_init_data({"id": uid, "first_name": name})
    return {"X-Init-Data": d}, d


def auth(c, h):
    c.post("/auth", json={"initData": h[1]})


with TestClient(app) as c:
    # --- R1: comment list capped at the latest 500 ---
    h640, _ = H(640, "Poster")
    auth(c, (h640, h640["X-Init-Data"]))
    r = c.post("/posts", headers=h640,
               json={"type": "text", "caption": "busy post"})
    pid = r.json()["id"]
    db = SessionLocal()
    db.add_all([models.Comment(post_id=pid, user_id=640,
                                text=f"c{i}") for i in range(505)])
    db.commit(); db.close()
    r = c.get(f"/posts/{pid}/comments", headers=h640)
    comments = r.json()["comments"]
    assert len(comments) == 500, len(comments)
    assert comments[0]["text"] == "c5", comments[0]["text"]
    assert comments[-1]["text"] == "c504", comments[-1]["text"]
    print("R1 comment cap OK")

    # --- R2: referral list capped, total stays true ---
    h650, d650 = H(650, "Referrer")
    auth(c, (h650, d650))
    db = SessionLocal()
    for i in range(205):
        db.add(models.User(telegram_id=20000 + i,
                           first_name=f"Ref{i}"))
        db.add(models.Referral(referrer_id=650,
                               new_user_id=20000 + i))
    db.commit(); db.close()
    r = c.get("/me/referrals", headers=h650)
    assert r.json()["total"] == 205, r.json()["total"]
    assert len(r.json()["referrals"]) == 200, len(r.json()["referrals"])
    print("R2 referral cap OK")

    # --- R3: analytics endpoints have rate budgets ---
    h660, d660 = H(660, "Analytic")
    auth(c, (h660, d660))
    saved_ads, saved_hb = RATE_LIMITS["ad_shown"], RATE_LIMITS["heartbeat"]
    RATE_LIMITS["ad_shown"] = (3, 3600)
    RATE_LIMITS["heartbeat"] = (2, 3600)
    ratelimit.reset()
    try:
        for _ in range(3):
            r = c.post("/ads/shown", headers=h660)
            assert r.status_code == 200, r.text
        r = c.post("/ads/shown", headers=h660)
        assert r.status_code == 429, r.status_code
        for _ in range(2):
            r = c.post("/me/heartbeat", headers=h660)
            assert r.status_code == 200, r.text
        r = c.post("/me/heartbeat", headers=h660)
        assert r.status_code == 429, r.status_code
    finally:
        RATE_LIMITS["ad_shown"], RATE_LIMITS["heartbeat"] = \
            saved_ads, saved_hb
        ratelimit.reset()
    print("R3 analytics budgets OK")

    # --- R5: blocking ---
    hA, dA = H(611, "Asha")
    hB, dB = H(622, "Boris")
    hC, dC = H(633, "Cleo")
    for h, d in ((hA, dA), (hB, dB), (hC, dC)):
        auth(c, (h, d))
    pa = c.post("/posts", headers=hA,
                json={"type": "text", "caption": "Asha post"}).json()
    pb = c.post("/posts", headers=hB,
                json={"type": "text", "caption": "Boris post"}).json()
    r = c.post("/users/622/follow", headers=hA)
    assert r.json()["following"] is True
    # Sanity: before the block, each sees the other's post.
    feed_a = [p["id"] for p in c.get("/feed", headers=hA).json()["posts"]]
    assert pb["id"] in feed_a
    # Guards: self + official cannot be blocked.
    r = c.post("/users/611/block", headers=hA)
    assert r.status_code == 400, r.status_code
    r = c.post("/users/1/block", headers=hA)
    assert r.status_code == 400, r.status_code
    # Block.
    r = c.post("/users/622/block", headers=hA)
    assert r.status_code == 200 and r.json()["blocked"] is True, r.text
    # Mutual invisibility in feeds.
    feed_a = [p["id"] for p in c.get("/feed", headers=hA).json()["posts"]]
    feed_b = [p["id"] for p in c.get("/feed", headers=hB).json()["posts"]]
    assert pb["id"] not in feed_a and pa["id"] in feed_a
    assert pa["id"] not in feed_b and pb["id"] in feed_b
    # A third member is unaffected.
    feed_c = [p["id"] for p in c.get("/feed", headers=hC).json()["posts"]]
    assert pa["id"] in feed_c and pb["id"] in feed_c
    # The follow was removed; the blocker still sees the profile
    # (with the flag), the blocked side gets a plain 404.
    prof = c.get("/users/622", headers=hA)
    assert prof.status_code == 200, prof.status_code
    assert prof.json()["blocked_by_me"] is True
    assert prof.json()["following"] is False
    r = c.get("/users/611", headers=hB)
    assert r.status_code == 404, r.status_code
    r = c.get("/users/611/posts", headers=hB)
    assert r.status_code == 404, r.status_code
    # Interactions refused both ways.
    r = c.post(f"/posts/{pa['id']}/comments", headers=hB,
               json={"text": "hello?"})
    assert r.status_code == 403, r.status_code
    r = c.post(f"/posts/{pa['id']}/like", headers=hB)
    assert r.status_code == 403, r.status_code
    r = c.post("/users/611/follow", headers=hB)
    assert r.status_code == 403, r.status_code
    r = c.post("/users/622/follow", headers=hA)
    assert r.status_code == 403, r.status_code
    r = c.post(f"/posts/{pa['id']}/share", headers=hB,
               json={"to_user_id": 611})
    assert r.status_code == 403, r.status_code
    # The block list shows the entry for the blocker only.
    mine = c.get("/me/blocked", headers=hA).json()["blocked"]
    assert [x["telegram_id"] for x in mine] == [622], mine
    theirs = c.get("/me/blocked", headers=hB).json()["blocked"]
    assert theirs == [], theirs
    # Unblock restores visibility.
    r = c.post("/users/622/block", headers=hA)
    assert r.json()["blocked"] is False, r.text
    r = c.get("/users/611", headers=hB)
    assert r.status_code == 200, r.status_code
    feed_a = [p["id"] for p in c.get("/feed", headers=hA).json()["posts"]]
    assert pb["id"] in feed_a
    print("R5 blocking OK")

print("PHASE-29 TESTS PASSED")
