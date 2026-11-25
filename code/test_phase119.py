"""Phase-119 tests: Admin Control Panel.

One unified home inside the Admin view: a section nav with live
counts (Reports / Members / Verifications badges), Site Controls
(maintenance toggle + app-wide announcement banner), the design
list under Content, and an Audit Log viewer. All the other panel
pieces (backup, earnings, reports, members, verifications, posts,
comments, broadcast) are reused as-is — this suite proves the new
bits and that the reused ones still answer.

Server: /admin/stats gains designs + pending_verifications;
GET /admin/designs lists the gallery for the admin; the maintenance
toggle flips the runtime flag in app_settings (the env flag still
wins, and /admin/maintenance stays reachable so the panel can
always switch it back off — while ON the API answers 503 except
/health, /webapp and /admin/maintenance); GET /announcement is
public, POST /admin/announcement sets/clears the banner.
"""
import hashlib
import hmac
import json
import os
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase119.db"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
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


ADMIN = 999
HA = H(ADMIN, "Admin")
HB = H(882, "Bob")


def test_client_markers():
    html = open("webapp/index.html").read()
    assert html.count("?v=179") == 10, html.count("?v=179")
    assert "?v=118" not in html
    for marker in ("cp-nav", "cp-sec-overview", "cp-sec-site",
                   "cp-sec-backup", "cp-sec-earnings", "cp-sec-reports",
                   "cp-sec-members", "cp-sec-verifs", "cp-sec-content",
                   "cp-sec-broadcast", "cp-sec-audit",
                   "announce-bar", "ah-designs", "ah-verifs",
                   "admin-designs", "admin-audit-log", "maint-toggle",
                   "announce-text", "audit-refresh", "cp-count-reports",
                   "cp-count-members", "cp-count-verifs"):
        assert marker in html, marker
    js = open("webapp/app.js").read()
    for marker in ("wireControlPanel", "wireCpButtons", "loadSiteControls",
                   "toggleMaintenance", "saveAnnouncement",
                   "clearAnnouncement", "loadAuditLog", "loadAdminDesigns",
                   "loadAnnouncementBar", "cp-count-reports",
                   "ah-designs", "pending_verifications"):
        assert marker in js, marker
    css = open("webapp/style.css").read()
    for marker in (".cp-nav", ".cp-count", ".announce-bar", ".audit-row"):
        assert marker in css, marker
    # Phase 118 markers intact — repost + comment replies untouched.
    assert "repost-banner" in js and "Replying to" in js
    assert "comment-replies" in css or "comment-reply-btn" in css
    print("client markers OK (?v=179, nav, site controls, audit, designs)")


def test_stats_gains_counts():
    c = TestClient(app)
    r = c.get("/admin/stats", headers=HB)
    assert r.status_code == 403, r.status_code
    s = c.get("/admin/stats", headers=HA).json()
    assert "designs" in s and "pending_verifications" in s, s
    assert s["designs"] == 0 and s["pending_verifications"] == 0, s
    for key in ("users", "posts", "comments", "open_reports",
                "banned_users", "total_points"):
        assert key in s, key
    print("stats gains designs + pending_verifications OK")


def test_admin_designs_list():
    c = TestClient(app)
    r = c.get("/admin/designs", headers=HB)
    assert r.status_code == 403, r.status_code
    assert c.get("/admin/designs", headers=HA).json()["designs"] == []
    db = SessionLocal()
    d1 = models.Design(image_file_id="AgACone", prompt="first design",
                       like_count=3)
    d2 = models.Design(image_file_id="AgACtwo", prompt="second design",
                       like_count=0)
    db.add_all([d1, d2])
    db.commit()
    ids = (d1.id, d2.id)
    db.close()
    rows = c.get("/admin/designs", headers=HA).json()["designs"]
    assert [d["id"] for d in rows] == [ids[1], ids[0]], rows  # newest first
    assert rows[0]["prompt"] == "second design"
    assert rows[1]["like_count"] == 3
    r = c.delete(f"/admin/designs/{ids[0]}", headers=HA)
    assert r.status_code == 200, r.text
    rows = c.get("/admin/designs", headers=HA).json()["designs"]
    assert [d["id"] for d in rows] == [ids[1]], rows
    s = c.get("/admin/stats", headers=HA).json()
    assert s["designs"] == 1, s
    print("admin designs list + remove OK")


def test_maintenance_toggle():
    c = TestClient(app)
    r = c.get("/admin/maintenance", headers=HB)
    assert r.status_code == 403, r.status_code
    r = c.post("/admin/maintenance", json={"on": True}, headers=HB)
    assert r.status_code == 403, r.status_code
    m = c.get("/admin/maintenance", headers=HA).json()
    assert m == {"maintenance": False, "env_locked": False}, m
    r = c.post("/admin/maintenance", json={"on": True}, headers=HA)
    assert r.status_code == 200, r.text
    assert r.json()["maintenance"] is True
    m = c.get("/admin/maintenance", headers=HA).json()
    assert m["maintenance"] is True, m
    # While maintenance is ON the API freezes — except /health and
    # the toggle itself, so the panel can always switch it off.
    assert c.get("/admin/stats", headers=HA).status_code == 503
    assert c.get("/health").status_code == 200
    assert c.get("/admin/maintenance", headers=HA).status_code == 200
    r = c.post("/admin/maintenance", json={"on": False}, headers=HA)
    assert r.status_code == 200 and r.json()["maintenance"] is False
    assert c.get("/admin/stats", headers=HA).status_code == 200
    # The audit read itself 503s while maintenance is ON, so the
    # entries are checked only after switching back off.
    actions = [e["action"] for e in
               c.get("/admin/audit-log", headers=HA).json()["entries"]]
    assert "maintenance_on" in actions, actions
    assert "maintenance_off" in actions, actions
    print("maintenance toggle + 503 freeze + audit OK")


def test_announcement_banner():
    c = TestClient(app)
    assert c.get("/announcement").json() == {"text": ""}
    r = c.post("/admin/announcement", json={"text": "hi"}, headers=HB)
    assert r.status_code == 403, r.status_code
    r = c.post("/admin/announcement", json={"text": "  "}, headers=HA)
    assert r.status_code == 200 and r.json() == {"text": ""}
    r = c.post("/admin/announcement",
               json={"text": "New feature Friday!"},
               headers=HA)
    assert r.status_code == 200, r.text
    assert r.json() == {"text": "New feature Friday!"}
    assert c.get("/announcement").json() == {"text": "New feature Friday!"}
    actions = [e["action"] for e in
               c.get("/admin/audit-log", headers=HA).json()["entries"]]
    assert "announcement_set" in actions, actions
    r = c.post("/admin/announcement", json={"text": ""}, headers=HA)
    assert r.status_code == 200 and r.json() == {"text": ""}
    assert c.get("/announcement").json() == {"text": ""}
    r = c.post("/admin/announcement",
               json={"text": "x" * 257}, headers=HA)
    assert r.status_code == 422, r.status_code
    print("announcement set / public read / clear / 422 OK")


def test_audit_log_view():
    c = TestClient(app)
    r = c.get("/admin/audit-log", headers=HB)
    assert r.status_code == 403, r.status_code
    entries = c.get("/admin/audit-log", headers=HA).json()["entries"]
    assert isinstance(entries, list)
    assert entries, "expected audit rows from the toggle/banner tests"
    assert entries[0]["id"] > entries[-1]["id"], "newest first"
    for e in entries:
        assert set(e) >= {"id", "admin_id", "action", "created_at"}, e
    # Reused panel reads still answer (nothing they relied on moved).
    assert c.get("/admin/reports", headers=HA).status_code == 200
    assert c.get("/admin/users", headers=HA).status_code == 200
    assert c.get("/admin/posts", headers=HA).status_code == 200
    assert c.get("/admin/comments", headers=HA).status_code == 200
    print("audit-log view + reused panel reads OK")


if __name__ == "__main__":
    test_client_markers()
    test_stats_gains_counts()
    test_admin_designs_list()
    test_maintenance_toggle()
    test_announcement_banner()
    test_audit_log_view()
    print("test_phase119: ALL OK")
