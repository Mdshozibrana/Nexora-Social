"""Smoke test for the backend: runs the API with a dummy bot token
(polling disabled), verifies /health, signed /auth, /feed, referral
recording, posts, first-post points, likes, comments, follows, search,
reports, deletes, and the Mini App host."""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["DATABASE_URL"] = "sqlite:///./test_smoke.db"

import app.bot as bot_mod

async def _no_poll(app):  # test double: never touch the Telegram network
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app import models


def make_init_data(user):
    params = {"auth_date": "1730000000", "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


with TestClient(app) as c:
    r = c.get("/health"); assert r.status_code == 200, r.text
    print("health:", r.json())

    d1 = make_init_data({"id": 111, "first_name": "Alice", "username": "alice"})
    r = c.post("/auth", json={"initData": d1}); assert r.status_code == 200, r.text
    print("auth alice:", r.json())

    bad = c.post("/auth", json={"initData": d1 + "tamper"})
    assert bad.status_code == 401, bad.status_code
    print("tampered initData rejected: 401 OK")

    r = c.get("/feed", headers={"X-Init-Data": d1}); assert r.status_code == 200
    assert r.json()["posts"] == []
    print("empty feed OK")

    db = SessionLocal()
    db.add(models.Post(user_id=111, type="text", caption="Hello world #first"))
    db.commit(); db.close()

    r = c.get("/feed", headers={"X-Init-Data": d1}); assert r.status_code == 200
    posts = r.json()["posts"]
    assert len(posts) == 1 and posts[0]["caption"] == "Hello world #first", posts
    print("feed with post OK:", posts[0]["author_name"], "| likes:", posts[0]["like_count"])

    r = c.get("/webapp/"); assert r.status_code == 200 and "Nexora" in r.text
    print("webapp host OK")

from app.users import get_or_create_user
db = SessionLocal()
u2, new2 = get_or_create_user(db, {"id": 222, "first_name": "Bob"}, referrer_id=111)
assert new2 and u2.referrer_id == 111
ref = db.query(models.Referral).filter_by(new_user_id=222).one()
assert ref.referrer_id == 111 and ref.qualified is False
u3, new3 = get_or_create_user(db, {"id": 222, "first_name": "Bob"}, referrer_id=111)
assert new3 is False
assert db.query(models.Referral).filter_by(new_user_id=222).count() == 1
db.close()
print("referral recorded once, unqualified until first post: OK")

# ---------------------------------------------------------------------------
# Phase tests: posts, first-post points, likes, comments, follows, search,
# reports, deletes. Bob (222) was referred by Alice (111) above; Carol (333)
# is an unrelated third user.
# ---------------------------------------------------------------------------
with TestClient(app) as c:
    d2 = make_init_data({"id": 222, "first_name": "Bob", "username": "bob"})
    d3 = make_init_data({"id": 333, "first_name": "Carol", "username": "carol"})
    H1 = {"X-Init-Data": d1}
    H2 = {"X-Init-Data": d2}
    H3 = {"X-Init-Data": d3}

    # Bob's FIRST post: hashtags parsed lowercase/deduped, points awarded.
    r = c.post("/posts", headers=H2, json={
        "type": "text", "caption": "My first post #Hello #World #hello"})
    assert r.status_code == 200, r.text
    p1 = r.json()
    assert p1["hashtags"] == "hello world", p1
    assert p1["author_name"] == "Bob", p1
    pid1 = p1["id"]
    print("post created, hashtags parsed:", p1["hashtags"])

    # Author post points (5) + ledger row.
    r = c.get("/me/points", headers=H2); assert r.status_code == 200, r.text
    pts = r.json()
    assert pts["balance"] == 5, pts
    assert len(pts["entries"]) == 1, pts
    assert pts["entries"][0]["reason"] == "post" and pts["entries"][0]["amount"] == 5, pts

    # Referrer referral points (20) + ledger row; referral now qualified.
    r = c.get("/me/points", headers=H1); assert r.status_code == 200, r.text
    pts = r.json()
    assert pts["balance"] == 20, pts
    assert len(pts["entries"]) == 1, pts
    assert pts["entries"][0]["reason"] == "referral" and pts["entries"][0]["amount"] == 20, pts

    r = c.get("/me/referrals", headers=H1); assert r.status_code == 200, r.text
    refs = r.json()
    assert refs["total"] == 1, refs
    assert refs["referrals"][0]["new_user_id"] == 222, refs
    assert refs["referrals"][0]["qualified"] is True, refs
    r = c.get("/me/referrals", headers=H2)
    assert r.json()["total"] == 0, r.json()
    print("first post qualified the referral; balances Bob=5, Alice=20: OK")

    # Bob's SECOND post: no re-qualification, no further points.
    r = c.post("/posts", headers=H2, json={
        "type": "text", "caption": "Second post #hello"})
    assert r.status_code == 200, r.text
    pid2 = r.json()["id"]
    assert c.get("/me/points", headers=H2).json()["balance"] == 5
    assert len(c.get("/me/points", headers=H2).json()["entries"]) == 1
    assert c.get("/me/points", headers=H1).json()["balance"] == 20
    assert len(c.get("/me/points", headers=H1).json()["entries"]) == 1
    print("second post did not re-qualify or re-pay: OK")

    # Like toggle by Carol, then a like by Alice.
    r = c.post(f"/posts/{pid1}/like", headers=H3); assert r.status_code == 200, r.text
    assert r.json() == {"liked": True, "like_count": 1}, r.json()
    r = c.post(f"/posts/{pid1}/like", headers=H3)
    assert r.json() == {"liked": False, "like_count": 0}, r.json()
    r = c.post(f"/posts/{pid1}/like", headers=H1)
    assert r.json() == {"liked": True, "like_count": 1}, r.json()
    print("like toggle on/off with counts: OK")

    # Comments: add two, list them back chronologically with author names.
    r = c.post(f"/posts/{pid1}/comments", headers=H3, json={"text": "Nice one!"})
    assert r.status_code == 200, r.text
    assert r.json()["author_name"] == "Carol", r.json()
    r = c.post(f"/posts/{pid1}/comments", headers=H1, json={"text": "Welcome!"})
    assert r.status_code == 200, r.text
    r = c.get(f"/posts/{pid1}/comments", headers=H2); assert r.status_code == 200, r.text
    comments = r.json()["comments"]
    assert len(comments) == 2, comments
    assert comments[0]["text"] == "Nice one!" and comments[0]["author_name"] == "Carol", comments
    assert comments[1]["text"] == "Welcome!" and comments[1]["author_name"] == "Alice", comments
    feed = c.get("/feed", headers=H1).json()["posts"]
    by_id = {p["id"]: p for p in feed}
    assert by_id[pid1]["comment_count"] == 2, by_id[pid1]
    assert by_id[pid1]["like_count"] == 1, by_id[pid1]
    print("comments add + chronological list + counts: OK")

    # Follow toggle, profile counts and the following flag; self-follow 400.
    r = c.post("/users/222/follow", headers=H3); assert r.status_code == 200, r.text
    assert r.json() == {"following": True, "followers": 1}, r.json()
    r = c.get("/users/222", headers=H3); assert r.status_code == 200, r.text
    prof = r.json()
    assert prof["first_name"] == "Bob" and prof["followers"] == 1, prof
    assert prof["posts"] == 2 and prof["following"] is True, prof
    r = c.post("/users/222/follow", headers=H3)
    assert r.json() == {"following": False, "followers": 0}, r.json()
    r = c.get("/users/222", headers=H3)
    assert r.json()["following"] is False, r.json()
    r = c.post("/users/333/follow", headers=H3)
    assert r.status_code == 400, r.status_code
    r = c.get("/users/99999", headers=H3)
    assert r.status_code == 404, r.status_code
    print("follow toggle + profile counts + following flag: OK")

    # Search by name (case-insensitive) and by hashtag.
    r = c.get("/search", headers=H1, params={"q": "bob"}); assert r.status_code == 200, r.text
    found = r.json()
    assert [u["telegram_id"] for u in found["users"]] == [222], found
    assert found["posts"] == [], found
    r = c.get("/search", headers=H1, params={"q": "#hello"})
    found = r.json()
    assert found["users"] == [], found
    assert len(found["posts"]) == 2, found
    assert all("hello" in p["hashtags"].split() for p in found["posts"]), found
    print("search by name and by hashtag: OK")

    # Report creation.
    r = c.post("/reports", headers=H3, json={"post_id": pid1, "reason": "spam"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "open" and r.json()["post_id"] == pid1, r.json()
    db = SessionLocal()
    reps = db.query(models.Report).filter_by(post_id=pid1).all()
    assert len(reps) == 1 and reps[0].reporter_id == 333 and reps[0].reason == "spam"
    db.close()
    print("report created: OK")

    # Delete: someone else's post -> 404; own post -> 200 and gone from feed.
    r = c.delete(f"/posts/{pid2}", headers=H3)
    assert r.status_code == 404, r.status_code
    r = c.delete(f"/posts/{pid2}", headers=H2); assert r.status_code == 200, r.text
    feed = c.get("/feed", headers=H1).json()["posts"]
    assert all(p["id"] != pid2 for p in feed), feed
    r = c.delete(f"/posts/{pid2}", headers=H2)
    assert r.status_code == 404, r.status_code
    r = c.delete("/posts/99999", headers=H2)
    assert r.status_code == 404, r.status_code
    print("delete own post (others get 404): OK")

    # Photo post keeps type and media_file_id.
    r = c.post("/posts", headers=H3, json={
        "type": "photo", "media_file_id": "FILEID123", "caption": "Pic #hello"})
    assert r.status_code == 200, r.text
    assert r.json()["type"] == "photo" and r.json()["media_file_id"] == "FILEID123", r.json()
    print("photo post type/media passthrough: OK")

print("SMOKE TEST PASSED")
