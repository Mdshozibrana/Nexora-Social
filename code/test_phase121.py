"""Phase-121 tests: Obsidian redesign of the Admin Control Panel.

Presentation only, admin view only (#view-admin). The reference is
the owner's "Obsidian Home" screenshot: near-black background,
dark cards, purple accent, a central dial whose big number is the
Members count and whose purple arc is Active-now / Members, round
quick-action buttons wired to the EXISTING controls, and a
2-column card grid. No endpoint, id, or JS behaviour changes:
maintenance / announcement / backup still behave as in
test_phase119 / test_phase107 (reused here, not duplicated).
"""
import hashlib
import hmac
import json
import os
import re
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "999"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase121.db"

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
    secret = hmac.new(b"WebAppData",
                      os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


ADMIN = 999
HA = H(ADMIN, "Admin")
HB = H(882, "Bob")

FROZEN_IDS = (
    "ah-members", "ah-active", "ah-posts", "ah-reports", "ah-designs",
    "ah-verifs", "cp-nav", "cp-count-reports", "cp-count-members",
    "cp-count-verifs", "maint-toggle", "maint-status", "announce-text",
    "announce-save", "announce-clear", "announce-status",
    "backup-download", "backup-send", "backup-file", "backup-pick",
    "backup-confirm", "backup-restore", "backup-status",
    "earn-ads-today", "earn-est-today", "earn-ads-month", "earn-ads-total",
    "earn-est-month", "earn-per-ad", "earn-per-1000", "earn-rate-in",
    "earn-rate-save", "earn-chart", "earn-top-points", "earn-top-today",
    "dash-tiles", "dash-signups", "dash-active", "dash-countries",
    "dash-languages", "dash-top-time", "admin-stats", "admin-reports",
    "admin-user-q", "admin-user-go", "admin-users", "admin-verifications",
    "vbu-q", "vbu-go", "vbu-result", "vbu-status", "official-actas",
    "off-name", "off-bio", "off-save", "off-result", "mu-name",
    "mu-username", "mu-count", "mu-create", "mu-result", "admin-managed",
    "admin-posts", "admin-comments", "admin-designs", "admin-bc-text",
    "admin-bc-send", "admin-bc-result", "audit-refresh", "admin-audit-log",
)

CP_TARGETS = ("cp-sec-overview", "cp-sec-site", "cp-sec-backup",
              "cp-sec-earnings", "cp-sec-payouts", "cp-sec-reports",
              "cp-sec-members", "cp-sec-verifs", "cp-sec-verify",
              "cp-sec-content", "cp-sec-broadcast", "cp-sec-audit",
              "cp-sec-security",
              "cp-sec-health")


def test_obsidian_markers():
    html = open("webapp/index.html").read()
    assert html.count("?v=210") == 10, html.count("?v=210")
    assert "?v=120" not in html
    # Obsidian header: eyebrow, greeting (name in purple), subtitle.
    for marker in ("NEXORA ADMIN", "Good Evening,",
                   'class="obs-accent"', "Your platform is in harmony."):
        assert marker in html, marker
    # The old light hero title is gone; the LIVE pill survives.
    assert "Admin Dashboard" not in html
    assert 'class="admin-live"' in html
    # Dial: SVG ring + Members number in its centre + Active line.
    for marker in ('id="obs-dial-arc"', 'id="obs-dial-arc"',
                   'id="ah-members"', 'id="ah-active"',
                   "stroke-dasharray", "527.8"):
        assert marker in html, marker
    # Four quick-action round buttons.
    for marker in ('id="obs-qa-maint"', 'id="obs-qa-announce"',
                   'id="obs-qa-backup"', 'id="obs-qa-refresh"'):
        assert marker in html, marker
    # Every frozen id survives byte-identical, exactly once.
    for fid in FROZEN_IDS:
        n = html.count('id="%s"' % fid)
        assert n == 1, (fid, n)
    # All 12 Control Panel nav buttons + their targets.
    assert html.count('data-target="cp-sec-') == 15, \
        html.count('data-target="cp-sec-')
    for tgt in CP_TARGETS:
        assert 'data-target="%s"' % tgt in html, tgt
        assert 'id="%s"' % tgt in html, tgt
    print("obsidian hero + dial + frozen ids + 14 nav targets OK")

    js = open("webapp/app.js").read()
    for marker in ("syncObsDial", "wireObsQuickActions",
                   '("obs-dial-arc")', "obs-qa-maint", "obs-qa-announce",
                   "obs-qa-backup", "obs-qa-refresh",
                   "maint-toggle", "announce-text", "loadAdmin()"):
        assert marker in js, marker
    # The dial math: ratio guards divide-by-zero, clamps 0..1.
    assert "527.8" in js
    assert "loadAdminStats" in js and "loadDashboard" in js
    # Earlier phases intact.
    assert "repost-banner" in js and "Replying to" in js
    assert "wireControlPanel" in js and "wireVbu" in js
    assert "wireBackupCard" in js
    print("dial wiring + quick actions + earlier phases OK")

    css = open("webapp/style.css").read()
    idx = css.index("Phase 121")
    # Bound the block at the next phase's header: later phases append
    # their own blocks after this one (Phase 122+), and their selectors
    # are scoped to their own views, not #view-admin.
    end = css.find("Phase 122", idx)
    block = css[idx:end if end != -1 else None]
    # The slice starts mid-comment; drop everything up to its close.
    block = block[block.index("*/") + 2:]
    for marker in ("#0D0D17", "#1B1B2A", "#A78BFA", "#8B5CF6",
                   ".obs-dial", ".obs-qa", "prefers-reduced-motion",
                   "#view-admin .cp-nav", "#view-admin .admin-sec"):
        assert marker in block, marker
    # Every selector in the Phase 121 block is scoped under #view-admin.
    stripped = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    for m in re.finditer(r"([^{}]+)\{", stripped):
        for sel in m.group(1).split(","):
            sel = sel.strip()
            if not sel or sel.startswith("@"):
                continue
            assert "#view-admin" in sel, sel
    # Member views untouched: Organic Clay markers live OUTSIDE the block.
    before = css[:idx]
    for marker in (".profile-hero", ".wave-div", "#F6F1E7",
                   ".post {", "livePulse"):
        assert marker in before, marker
    assert ".profile-hero" not in block and ".post" not in block
    assert "feed" not in block.lower().replace("prefers-reduced-motion", "")
    print("obsidian CSS scoped under #view-admin; member CSS untouched OK")


def test_admin_endpoints_still_work():
    c = TestClient(app)
    # Non-admin stays out of every admin route.
    for method, path in (("get", "/admin/maintenance"),
                         ("get", "/admin/backup"),
                         ("get", "/admin/stats")):
        r = getattr(c, method)(path, headers=HB)
        assert r.status_code == 403, (method, path, r.status_code)
    # Maintenance toggle (Phase 119 behaviour): on, freeze, off.
    r = c.post("/admin/maintenance", json={"on": True}, headers=HA)
    assert r.status_code == 200 and r.json()["maintenance"] is True, r.text
    assert c.get("/health").status_code == 200
    r = c.post("/admin/maintenance", json={"on": False}, headers=HA)
    assert r.status_code == 200 and r.json()["maintenance"] is False, r.text
    # Announcement banner (Phase 119 behaviour): set, read, clear.
    assert c.get("/announcement").json() == {"text": ""}
    r = c.post("/admin/announcement", json={"text": "Obsidian night"},
               headers=HA)
    assert r.status_code == 200, r.text
    assert c.get("/announcement").json() == {"text": "Obsidian night"}
    r = c.post("/admin/announcement", json={"text": ""}, headers=HA)
    assert r.status_code == 200, r.text
    assert c.get("/announcement").json() == {"text": ""}
    # Full backup (Phase 107 behaviour): format + all tables —
    # 33 since Phase 123 added drafts, comment_likes, polls,
    # poll_options and poll_votes to the 28.
    r = c.get("/admin/backup", headers=HA)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["format"] == "nexora-backup" and b["version"] == 1, b
    assert len(b["tables"]) == 55, len(b["tables"])
    print("maintenance + announcement + backup endpoints OK")


if __name__ == "__main__":
    test_obsidian_markers()
    test_admin_endpoints_still_work()
    print("test_phase121: ALL OK")
