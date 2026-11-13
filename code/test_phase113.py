"""Phase-113 tests: NEW POINTS RULES (owner, Nov 13).

- Follow 3 people -> 10 pts (was follow-2 -> 5).
- Every post -> 10 pts (was first post only -> 5).
- React to 6 posts -> 10 pts (new daily task, Like rows today).
- Watch an ad -> 20 pts, once a day (new daily task, AdEvent rows
  today — only real completed shows, reported via /ads/shown).
- Check-in 20 and comment-5 (5 pts) unchanged (covered by test_phase6).
"""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase113.db"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


def make_init_data(user):
    params = {"auth_date": str(int(__import__("time").time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


CAROL, DAVE = H(333, "Carol"), H(444, "Dave")


def tasks(c, h):
    return {t["key"]: t
            for t in c.get("/me/tasks", headers=h).json()["tasks"]}


with TestClient(app) as c:
    for h in (CAROL, DAVE):
        r = c.post("/auth", json={"initData": h["X-Init-Data"]})
        assert r.status_code == 200

    # Task list: five tasks, new values.
    t = tasks(c, CAROL)
    assert set(t) == {"checkin", "follow3", "react6", "comment5",
                      "adwatch"}, t
    assert t["checkin"]["points"] == 20
    assert t["follow3"]["points"] == 10 and t["follow3"]["target"] == 3
    assert t["comment5"]["points"] == 5
    assert t["react6"]["points"] == 10 and t["react6"]["target"] == 6
    assert t["adwatch"]["points"] == 20 and t["adwatch"]["target"] == 1
    assert t["react6"]["claimable"] is False
    assert t["adwatch"]["claimable"] is False
    print("task list + new point values OK")

    # Every post pays 10: two posts -> balance 20, two ledger rows.
    for i in range(2):
        r = c.post("/posts", headers=CAROL,
                   json={"type": "text", "caption": f"post {i}"})
        assert r.status_code == 200, r.text
    pts = c.get("/me/points", headers=CAROL).json()
    assert pts["balance"] == 20, pts
    assert [e["amount"] for e in pts["entries"]] == [10, 10], pts
    print("every post pays 10 OK")

    # React-6: 6 distinct post likes -> claimable -> +10, once a day.
    ids = []
    for i in range(6):
        r = c.post("/posts", headers=DAVE,
                   json={"type": "text", "caption": f"dave {i}"})
        ids.append(r.json()["id"])
    for pid in ids[:5]:
        r = c.post(f"/posts/{pid}/like", headers=CAROL)
        assert r.status_code == 200, r.text
    t = tasks(c, CAROL)
    assert t["react6"]["progress"] == 5 and t["react6"]["claimable"] is False
    c.post(f"/posts/{ids[5]}/like", headers=CAROL)
    t = tasks(c, CAROL)
    assert t["react6"]["progress"] == 6 and t["react6"]["claimable"] is True
    r = c.post("/me/tasks/react6/claim", headers=CAROL)
    assert r.json()["points_awarded"] == 10, r.json()
    assert r.json()["balance"] == 30, r.json()
    r = c.post("/me/tasks/react6/claim", headers=CAROL)
    assert r.status_code == 400, "second react claim must be refused"
    print("react-6 (+10) once a day OK")

    # Ad-watch: no show yet -> not claimable; one real /ads/shown
    # report -> claimable -> +20, once a day.
    r = c.post("/me/tasks/adwatch/claim", headers=CAROL)
    assert r.status_code == 400
    r = c.post("/ads/shown", headers=CAROL)
    assert r.json() == {"ok": True, "counted": True}, r.json()
    t = tasks(c, CAROL)
    assert t["adwatch"]["progress"] == 1 and t["adwatch"]["claimable"] is True
    r = c.post("/me/tasks/adwatch/claim", headers=CAROL)
    assert r.json()["points_awarded"] == 20, r.json()
    assert r.json()["balance"] == 50, r.json()
    r = c.post("/me/tasks/adwatch/claim", headers=CAROL)
    assert r.status_code == 400, "second ad claim must be refused"
    print("ad-watch (+20) once a day OK")

    # Client: Watch-ad button + showTaskAd wiring, history labels.
    js = c.get("/webapp/app.js").text
    assert 't.key === "adwatch"' in js, "ad button branch gone"
    assert '"▶️ Watch ad"' in js, "ad button label gone"
    assert "async function showTaskAd(btn)" in js, "showTaskAd gone"
    assert 'await api("/ads/shown", { method: "POST" })' in js
    assert '"task:follow3"' in js and '"task:react6"' in js
    assert '"task:adwatch"' in js and '"task:follow2"' in js
    print("Tasks-page ad button + history labels OK")

    # Phase 111/112 survive.
    html = c.get("/webapp/").text
    assert 'id="photo-viewer"' in html, "Phase 112 viewer gone"
    assert "openPhotoViewer" in js, "Phase 112 wiring gone"
    main = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "app", "main.py")).read()
    assert 'headers["cache-control"] = "private, max-age=604800' in main, \
        "Phase 111 cache gone"
    assert "A post earns 10 points." in main, "Nexa manual post value stale"
    assert "the follow task 10" in main, "Nexa manual task values stale"
    print("Phase 111/112 markers OK")

    for asset in ("style.css?v=118", "app.js?v=118", "games.js?v=118"):
        assert asset in html, asset
    print("asset version ?v=118 OK")

print("PHASE 113 OK")
