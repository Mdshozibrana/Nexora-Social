"""Phase-129 tests: Members browse in the Admin Panel.

The Members section was search-only — the admin could only find a
member by typing a name/@username/ID. GET /admin/users now also
browses (no `q`): sort points|followers|joined|name, order
desc|asc, filter all|verified|banned, limit (default 20, max 100)
+ offset paging, response gains `total` + `next_offset`, each dict
gains `lifetime_points` (sum of positive ledger rows — the same
figure the admin detail and monetization gate use) + `followers`.
Search mode (q present) is byte-identical: same dicts, no
total/next_offset. Client: sort dropdown + All/Verified/Banned
chips (Phase 124 chip pattern) + Show more button; searching
still shows search results, clearing the search returns to
browse. No migration change.
"""
import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase129.db"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from app import notify

SENT = []


async def fake_send(chat_id, text):
    SENT.append((chat_id, text))
    return True


notify.send_message = fake_send

import app.main as main_mod
from app.db import SessionLocal
from app import models

from fastapi.testclient import TestClient
from app.main import app

def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, auth_date=None):
    return {"X-Init-Data": make_init_data(
        {"id": uid, "first_name": name}, auth_date)}


ADMIN = 999
HA = H(ADMIN, "Admin")
HB = H(882, "Mona")

AARON, MONA, ZED, KIM = 881, 882, 883, 884
NOW = datetime.utcnow()

BASE = os.path.dirname(os.path.abspath(__file__))
HTML = open(os.path.join(BASE, "webapp", "index.html")).read()
JS = open(os.path.join(BASE, "webapp", "app.js")).read()
SRC = open(os.path.join(BASE, "app", "main.py")).read()


def seed():
    db = SessionLocal()
    db.add(models.User(telegram_id=AARON, first_name="Aaron",
                       username="aaron", is_verified=True,
                       created_at=NOW - timedelta(days=10)))
    db.add(models.User(telegram_id=MONA, first_name="Mona",
                       username="mona",
                       created_at=NOW - timedelta(days=5)))
    db.add(models.User(telegram_id=ZED, first_name="Zed",
                       username="zed", is_banned=True,
                       created_at=NOW - timedelta(days=1)))
    db.add(models.User(telegram_id=KIM, first_name="Kim",
                       username="kim",
                       created_at=NOW - timedelta(days=2)))
    # Followers: Mona 5, Zed 2, Aaron 1, Kim 0.
    for i in range(5):
        fid = 910001 + i
        db.add(models.User(telegram_id=fid, first_name="Follower",
                           username=f"follower{i}",
                           created_at=NOW - timedelta(days=3)))
        db.add(models.Follow(follower_id=fid, following_id=MONA))
    db.add(models.Follow(follower_id=910001, following_id=ZED))
    db.add(models.Follow(follower_id=910002, following_id=ZED))
    db.add(models.Follow(follower_id=910001, following_id=AARON))
    # Lifetime points: Mona 300, Zed 200, Aaron 100, Kim 0.
    db.add(models.PointsLedger(user_id=MONA, amount=300, reason="bonus"))
    db.add(models.PointsLedger(user_id=ZED, amount=200, reason="bonus"))
    db.add(models.PointsLedger(user_id=AARON, amount=100, reason="bonus"))
    db.commit()
    db.close()


def user_count():
    db = SessionLocal()
    n = db.query(models.User).count()
    db.close()
    return n


def browse(c, **params):
    r = c.get("/admin/users", params=params, headers=HA)
    assert r.status_code == 200, r.text
    return r.json()


def assert_relative_order(data, wanted):
    got = [u["telegram_id"] for u in data["users"]]
    pos = [got.index(w) for w in wanted]
    assert pos == sorted(pos), (wanted, got)
    return got


def test_source_guards():
    # Phase 126 lesson: no integer default on a boolean column in
    # raw migration SQL (Postgres rejects it, SQLite accepts it).
    assert "BOOLEAN DEFAULT 0" not in SRC, "boolean DEFAULT 0 present"
    assert "_BROWSE_SORTS" in SRC and "_BROWSE_FILTERS" in SRC
    assert "lifetime_points" in SRC and "next_offset" in SRC
    print("source guards OK (no BOOLEAN DEFAULT 0, browse mode present)")


def test_client_markers():
    assert HTML.count("?v=184") == 10, HTML.count("?v=184")
    assert "?v=128" not in HTML
    for marker in ("admin-browse", "admin-browse-sort",
                   "admin-browse-chips", "admin-browse-more",
                   "cp-sec-members", "Show more"):
        assert marker in HTML, marker
    for marker in ("loadAdminBrowse", "adminBrowse", "adminBrowseOrder",
                   "adminMemberRow", "refreshAdminMembers",
                   "admin-browse-sort", "admin-browse-more"):
        assert marker in JS, marker
    css = open(os.path.join(BASE, "webapp", "style.css")).read()
    assert ".admin-browse" in css
    # Phase 123-128 markers intact.
    for marker in ("topScroller", "pollBlock", "loadDrafts",
                   "renderPh", "goFeedTo", "loadTrending",
                   "loadSecurityLog", "renderSecLog",
                   "loadPayoutBox", "loadPayoutList", "loadPayouts",
                   "decidePayout", "markPayoutPaid",
                   "loadVerifications", "repost-banner"):
        assert marker in JS, marker
    print("client markers OK (?v=184, browse controls, 123-128 intact)")


def test_browse_points(c):
    # Default sort is points desc (richest first).
    d = browse(c)
    assert d["total"] == user_count(), (d["total"], user_count())
    assert d["next_offset"] is None  # fewer users than the default 20
    by_id = {u["telegram_id"]: u for u in d["users"]}
    assert by_id[MONA]["lifetime_points"] == 300
    assert by_id[MONA]["followers"] == 5
    assert by_id[ZED]["lifetime_points"] == 200
    assert by_id[ZED]["followers"] == 2
    assert by_id[AARON]["lifetime_points"] == 100
    assert by_id[AARON]["followers"] == 1
    assert by_id[KIM]["lifetime_points"] == 0
    assert by_id[KIM]["followers"] == 0
    assert_relative_order(d, [MONA, ZED, AARON, KIM])
    d = browse(c, sort="points", order="asc")
    assert_relative_order(d, [KIM, AARON, ZED, MONA])
    print("browse sort=points desc/asc OK (lifetime, not balance)")


def test_browse_followers(c):
    d = browse(c, sort="followers", order="desc")
    assert_relative_order(d, [MONA, ZED, AARON, KIM])
    d = browse(c, sort="followers", order="asc")
    assert_relative_order(d, [KIM, AARON, ZED, MONA])
    print("browse sort=followers desc/asc OK")


def test_browse_joined(c):
    d = browse(c, sort="joined", order="desc")
    assert_relative_order(d, [ZED, KIM, MONA, AARON])
    d = browse(c, sort="joined", order="asc")
    assert_relative_order(d, [AARON, MONA, KIM, ZED])
    print("browse sort=joined desc/asc OK")


def test_browse_name(c):
    d = browse(c, sort="name", order="asc")
    assert_relative_order(d, [AARON, KIM, MONA, ZED])
    d = browse(c, sort="name", order="desc")
    assert_relative_order(d, [ZED, MONA, KIM, AARON])
    print("browse sort=name asc/desc OK")


def test_browse_filters(c):
    d = browse(c, filter="verified")
    got = [u["telegram_id"] for u in d["users"]]
    assert AARON in got, got
    assert all(u["is_verified"] for u in d["users"]), got
    d = browse(c, filter="banned")
    got = [u["telegram_id"] for u in d["users"]]
    assert ZED in got, got
    assert all(u["is_banned"] for u in d["users"]), got
    d = browse(c, filter="all")
    got = [u["telegram_id"] for u in d["users"]]
    for uid in (AARON, MONA, ZED, KIM):
        assert uid in got, got
    print("browse filters verified/banned/all OK")


def test_browse_pagination(c):
    total = user_count()
    seen = []
    offset = 0
    pages = 0
    while True:
        d = browse(c, limit=2, offset=offset)
        assert d["total"] == total, (d["total"], total)
        pages += 1
        assert pages <= total + 1, "paging loop did not terminate"
        ids = [u["telegram_id"] for u in d["users"]]
        assert not (set(ids) & set(seen)), (ids, seen)
        seen.extend(ids)
        if d["next_offset"] is None:
            break
        offset = d["next_offset"]
    assert len(seen) == total, (len(seen), total)
    assert len(set(seen)) == total
    # Offset beyond the total: empty page, total still correct.
    d = browse(c, limit=2, offset=total + 50)
    assert d["users"] == [] and d["total"] == total
    assert d["next_offset"] is None
    print(f"browse pagination OK ({pages} pages of 2, union == total {total})")


def test_search_unchanged(c):
    r = c.get("/admin/users", params={"q": "mona"}, headers=HA)
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d.keys()) == {"users"}, d.keys()
    assert [u["telegram_id"] for u in d["users"]] == [MONA], d
    # Search dicts keep the old shape (no browse-only keys).
    assert "lifetime_points" not in d["users"][0]
    assert "total" not in d and "next_offset" not in d
    r = c.get("/admin/users", params={"q": "881"}, headers=HA)
    assert [u["telegram_id"] for u in r.json()["users"]] == [AARON]
    r = c.get("/admin/users", params={"q": "zzz-no-such-name"}, headers=HA)
    assert r.json()["users"] == []
    # A sort param must not change search results.
    r = c.get("/admin/users", params={"q": "mona", "sort": "name"},
              headers=HA)
    assert [u["telegram_id"] for u in r.json()["users"]] == [MONA]
    print("search mode byte-identical OK (dict shape, q, id lookup)")


def test_managed_still_works(c):
    db = SessionLocal()
    db.add(models.User(telegram_id=777001, first_name="Managed One",
                       username="managed1", is_managed=True))
    db.commit()
    db.close()
    r = c.get("/admin/users", params={"managed": 1, "limit": 100},
              headers=HA)
    assert r.status_code == 200, r.text
    got = r.json()["users"]
    assert got and all(u["is_managed"] for u in got), got
    assert 777001 in [u["telegram_id"] for u in got]
    print("managed=1 list still works OK")


def test_auth_and_validation(c):
    r = c.get("/admin/users", headers=HB)
    assert r.status_code == 403, r.status_code
    r = c.get("/admin/users", headers={})
    assert r.status_code == 401, r.status_code
    for bad in ({"sort": "nope"}, {"filter": "nope"},
                {"order": "sideways"}):
        r = c.get("/admin/users", params=bad, headers=HA)
        assert r.status_code == 400, (bad, r.status_code)
    print("auth 403/401 + invalid sort/filter/order 400 OK")


if __name__ == "__main__":
    seed()
    with TestClient(app) as c:
        r = c.get("/health")
        assert r.status_code == 200, r.text
        # Warm-up: settle lazy user creation (admin + official)
        # before counting users for pagination totals.
        browse(c)
        test_source_guards()
        test_client_markers()
        test_browse_points(c)
        test_browse_followers(c)
        test_browse_joined(c)
        test_browse_name(c)
        test_browse_filters(c)
        test_browse_pagination(c)
        test_search_unchanged(c)
        test_managed_still_works(c)
        test_auth_and_validation(c)
    print("test_phase129: ALL OK")
