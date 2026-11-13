"""Phase-107 tests: ADMIN-ONLY FULL-SITE BACKUP + RESTORE (owner, Nov 13).

Owner order (Bengali): in the Admin ID keep one system where one
click downloads the whole site's A-to-Z data and it can be uploaded
back; if the site's data is ever removed, uploading that file
brings back the same data with names, A to Z.

Covers: backup shape (all 28 tables, IDs preserved), admin-only
(403 for members), send-to-Telegram without a live token reports
sent:false, restore round-trip (backup -> wipe everything ->
restore -> identical rows), wrong confirm / bad format / unknown
table rejected with data intact, restore while acting as another
account refused, restore audit-logged, Admin Panel wiring.
"""
import hashlib, hmac, json, os, sys, time, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase107.db"

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app, _BACKUP_TABLES  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import models  # noqa: E402

def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)



def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


ADMIN = H(999, "Admin")
MEMBER = H(555, "Member")


def seed():
    db = SessionLocal()
    for _name, model in reversed(_BACKUP_TABLES):
        db.query(model).delete()
    db.add(models.User(telegram_id=1, username="nexora",
                       first_name="Nexora Social", is_verified=True))
    db.add(models.User(telegram_id=999, username="owner",
                       first_name="Admin", is_verified=True))
    db.add(models.User(telegram_id=555, username="member",
                       first_name="Member", bio="Hello Dhaka",
                       points_balance=42))
    db.add(models.Post(id=1, user_id=555, type="text",
                       caption="First post", hashtags="#hello"))
    db.add(models.Post(id=2, user_id=999, type="photo",
                       media_file_id="PHOTOFID", caption="Admin pic"))
    db.add(models.Like(post_id=1, user_id=999))
    db.add(models.Comment(post_id=1, user_id=999, text="Nice one"))
    db.add(models.Follow(follower_id=555, following_id=999))
    db.add(models.PointsLedger(user_id=555, amount=20,
                               reason="checkin", ref_id=None))
    db.add(models.Design(id=1, image_file_id="DESIGNFID",
                         prompt="test prompt", like_count=3))
    db.add(models.Message(sender_id=555, recipient_id=999, text="hi"))
    db.add(models.AppSetting(key="ad_rate", value="0.5"))
    db.add(models.DailyClaim(user_id=555, task_key="checkin",
                             day="2026-11-13"))
    db.commit()
    db.close()


def wipe():
    db = SessionLocal()
    for _name, model in reversed(_BACKUP_TABLES):
        db.query(model).delete()
    db.commit()
    db.close()


def count(model):
    db = SessionLocal()
    n = db.query(model).count()
    db.close()
    return n


with TestClient(app) as c:
    seed()
    # --- backup shape ------------------------------------------
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers.get("content-disposition", "")
    assert "nexora-full-backup-" in r.headers["content-disposition"]
    b = r.json()
    assert b["format"] == "nexora-backup" and b["version"] == 1
    assert set(b["tables"]) == {n for n, _ in _BACKUP_TABLES}
    users = {u["telegram_id"]: u for u in b["tables"]["users"]}
    assert users[555]["bio"] == "Hello Dhaka"
    assert users[555]["points_balance"] == 42
    assert users[1]["username"] == "nexora"
    posts = {p["id"]: p for p in b["tables"]["posts"]}
    assert posts[1]["caption"] == "First post"
    assert posts[2]["media_file_id"] == "PHOTOFID"
    assert b["tables"]["designs"][0]["prompt"] == "test prompt"
    assert b["tables"]["messages"][0]["text"] == "hi"
    assert b["tables"]["app_settings"][0] == {
        "key": "ad_rate", "value": "0.5"}
    print("backup shape OK")

    # --- admin-only ---------------------------------------------
    r = c.get("/admin/backup", headers=MEMBER)
    assert r.status_code == 403, r.status_code
    r = c.post("/admin/restore", headers=MEMBER,
               json={"confirm": "RESTORE", "backup": b})
    assert r.status_code == 403, r.status_code
    print("admin-only OK")

    # --- send without a live token -------------------------------
    r = c.post("/admin/backup/send", headers=ADMIN)
    assert r.status_code == 200 and r.json() == {"sent": False}, r.text
    print("backup send (no live token) OK")

    # --- restore round-trip: wipe everything, bring it back ------
    wipe()
    assert count(models.User) == 0
    r = c.post("/admin/restore", headers=ADMIN,
               json={"confirm": "RESTORE", "backup": b})
    assert r.status_code == 200, r.text
    restored = r.json()["restored"]
    assert restored["users"] == 3 and restored["posts"] == 2
    assert restored["designs"] == 1 and restored["messages"] == 1
    db = SessionLocal()
    m = db.get(models.User, 555)
    assert m.bio == "Hello Dhaka" and m.points_balance == 42
    assert db.get(models.Post, 1).caption == "First post"
    assert db.query(models.Follow).filter_by(
        follower_id=555, following_id=999).first() is not None
    assert db.get(models.Design, 1).prompt == "test prompt"
    assert db.query(models.AdminAuditLog).filter_by(
        action="backup_restore").count() == 1
    db.close()
    print("restore round-trip OK")

    # --- guards: bad input changes nothing -----------------------
    before = count(models.User)
    r = c.post("/admin/restore", headers=ADMIN,
               json={"confirm": "DELETE", "backup": b})
    assert r.status_code == 400, r.status_code
    r = c.post("/admin/restore", headers=ADMIN,
               json={"confirm": "RESTORE",
                     "backup": {"format": "nope", "version": 1,
                                "tables": {}}})
    assert r.status_code == 400, r.status_code
    bad = json.loads(json.dumps(b))
    bad["tables"]["mystery"] = []
    r = c.post("/admin/restore", headers=ADMIN,
               json={"confirm": "RESTORE", "backup": bad})
    assert r.status_code == 400, r.status_code
    assert count(models.User) == before
    print("restore guards OK")

    # --- restore while acting as another account ------------------
    r = c.post("/admin/restore", headers={**ADMIN, "X-Act-As": "555"},
               json={"confirm": "RESTORE", "backup": b})
    assert r.status_code in (400, 403), r.status_code
    print("restore act-as guard OK")

    # --- client wiring: backup card in the Admin Panel -----------
    html = c.get("/webapp/").text
    for marker in ("backup-download", "backup-send", "backup-file",
                   "backup-pick", "backup-confirm", "backup-restore",
                   "Site Backup"):
        assert marker in html, marker
    js = c.get("/webapp/app.js").text
    for marker in ("wireBackupCard", "/admin/backup",
                   "/admin/backup/send", "/admin/restore"):
        assert marker in js, marker
    print("admin backup card wiring OK")

print("PHASE 107 OK")
