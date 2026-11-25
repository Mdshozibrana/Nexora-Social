"""Phase 181 tests: Admin security & media — audit H10/H11/M6/M7/M8/M9/M10/M11/M14.

H10 — TOTP verify: 5 bad codes -> 400 each + totp_verify_failed
  audit rows; the 6th attempt (even the RIGHT code) -> 429 lockout;
  after the window resets, the right code -> 200. Setup fetch still
  returns the secret (owner recovery path) and is audit-logged as
  totp_setup_fetch with the secret NEVER in the log detail.
H11 — GET /admin/backup with stale (>5 min) initData -> 401/step-up,
  fresh -> 200; GET /admin/health with stale initData stays 200
  (other admin GETs keep the 24 h window).
M8 — Backup status reflects auto-backup recency: manual rows
  backdated 10 days + a fresh auto_backup_send -> last_backup_at is
  now, kind "auto" (no false ">7 days" warning).
M9 — Broadcast: the row is committed before delivery; a resume
  (broadcast_id) skips already-delivered targets (no double DM, no
  duplicate in-app rows); the shared admin_mutation budget is
  consumed by broadcast calls.
M14 — Broadcast respects the System toggle for in-app rows: a
  member with System off gets no DM AND no announcement row; a
  member whose DM fails still gets the in-app row.
M11 — _client_ip and geoip._public_ip agree on ONE rule: last hop.
  In-repo evidence for keeping last-hop (not flipping to first):
  SECURITY.md documents last-hop as the Phase 164 rule and
  test_phase164 pins it; the first XFF entry is attacker-controlled
  whenever the edge does not strip client-sent XFF, and Render sits
  behind Cloudflare, which appends without stripping — flipping to
  first-public would reopen the exact /auth-budget bypass H2 closed.
  Residual: members behind one Cloudflare edge share one auth_ip key.
M6 — Media proxy (Telegram upstream mocked): malformed getFile JSON
  / ok:false / missing result -> 404 (not 500); transport failure
  on the stream send -> clean 502; mid-stream failure -> 200 with
  the clean short body, not a reset.
M10 — Mutating admin endpoints share one admin_mutation bucket
  (120/h): 1 broadcast + 119 bans -> 200 each; the 121st call ->
  429; admin GETs are unaffected.
M7 — Restore: plaintext accepted with NO key configured; rejected
  (400) while a key is configured; Fernet accepted while keyed;
  the rate limit fires BEFORE any decrypt work (4th restore -> 429
  even for a valid payload; garbage payload -> 400 once the budget
  allows); 50 MB limit on BOTH paths (oversized encrypted string
  and oversized plaintext dict -> 413).
Plain script (run.sh runs it with python directly).
"""
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase181.db"
os.environ["ADMIN_IDS"] = "1909"
os.environ["MODERATOR_IDS"] = "1908"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

import app.notify as notify_mod  # noqa: E402
import httpx  # noqa: E402

SENT = []
FAIL = set()


async def fake_send(chat_id, text):
    if chat_id in FAIL:
        return False
    SENT.append((chat_id, text))
    return True


notify_mod.send_message = fake_send

# --- M6: fake Telegram upstream for /media ------------------------------
MEDIA_MODE = {"getfile": "ok", "send": "ok"}


class FakeGetFileResp:
    status_code = 200
    headers = {"content-type": "application/json"}

    def json(self):
        mode = MEDIA_MODE["getfile"]
        if mode == "malformed":
            raise ValueError("not json")
        if mode == "ok_false":
            return {"ok": False}
        if mode == "no_result":
            return {"ok": True}
        return {"ok": True, "result": {"file_path": "photos/file_1.jpg"}}


class FakeStreamResp:
    status_code = 200

    @property
    def headers(self):
        # A mid-stream failure must end cleanly: no content-length,
        # so the short body is legal instead of a length mismatch.
        if MEDIA_MODE["send"] == "midfail":
            return {"content-type": "image/jpeg"}
        return {"content-type": "image/jpeg", "content-length": "5"}

    async def aiter_bytes(self):
        if MEDIA_MODE["send"] == "midfail":
            yield b"ab"
            raise httpx.HTTPError("mid-stream boom")
        yield b"ab"
        yield b"cde"

    async def aclose(self):
        pass


class FakeAsyncClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        return FakeGetFileResp()

    def build_request(self, method, url, headers=None):
        return (method, url, headers)

    async def send(self, req, stream=False):
        if MEDIA_MODE["send"] == "raise":
            raise httpx.ConnectError("connect boom")
        return FakeStreamResp()

    async def aclose(self):
        pass


httpx.AsyncClient = FakeAsyncClient

from fastapi.testclient import TestClient  # noqa: E402
import app.main as main_mod  # noqa: E402
from app.main import (  # noqa: E402
    _BACKUP_MAX_BYTES, _BACKUP_TABLES, _backup_pack, _backup_payload,
    _backup_unpack, _client_ip, app)
from app import models  # noqa: E402
from app.config import RATE_LIMITS, settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.geoip import _public_ip  # noqa: E402
from app import ratelimit  # noqa: E402
from starlette.requests import Request  # noqa: E402


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


ADMIN = H(1909, "Admin")
MOD = H(1908, "Mod")
ALICE = H(1901, "Alice")
BOB = H(1902, "Bob")
CAROL = H(1903, "Carol")

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
HTML = open(os.path.join(ROOT, "code/webapp/index.html")).read()
MAIN = open(os.path.join(ROOT, "code/app/main.py")).read()
GEOIP = open(os.path.join(ROOT, "code/app/geoip.py")).read()


def audit_actions(action=None):
    with SessionLocal() as db:
        q = db.query(models.AdminAuditLog)
        if action:
            q = q.filter_by(action=action)
        return [(r.action, r.detail) for r in
                q.order_by(models.AdminAuditLog.id).all()]


def token_for(c, headers):
    r = c.post("/auth", json={"initData": headers["X-Init-Data"]})
    assert r.status_code == 200, r.text
    tok = r.json()["media_token"]
    assert tok
    return tok


with TestClient(app) as c:
    for h in (ADMIN, MOD, ALICE, BOB, CAROL):
        r = c.post("/auth", json={"initData": h["X-Init-Data"]})
        assert r.status_code == 200, r.text

    # --- 1. H10: TOTP verify rate limit + lockout + audit --------------
    import pyotp  # noqa: E402
    secret = pyotp.random_base32()
    settings.ADMIN_TOTP_SECRET = secret
    real = pyotp.TOTP(secret).now()
    wrong = "000000" if real != "000000" else "111111"
    for i in range(5):
        r = c.post("/admin/totp/verify", headers=ADMIN,
                   json={"code": wrong})
        assert r.status_code == 400, (i, r.status_code, r.text)
    failed = audit_actions("totp_verify_failed")
    assert len(failed) == 5, failed
    assert all("TOTP code rejected" in d for _a, d in failed)
    # 6th attempt — even the RIGHT code — is locked out (429).
    r = c.post("/admin/totp/verify", headers=ADMIN,
               json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 429, (r.status_code, r.text)
    # The lockout is the 15-min window, never permanent: a fresh
    # budget verifies fine.
    ratelimit.reset()
    r = c.post("/admin/totp/verify", headers=ADMIN,
               json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200 and r.json()["verified"] is True, r.text
    print("H10 TOTP verify 5x400 audit-logged + 6th 429 + reset 200 OK")

    # --- 2. H10: setup still returns the secret; fetch audit-logged ---
    r = c.get("/admin/totp/setup", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["secret"] == secret, r.json()
    assert r.json()["otpauth_url"].startswith("otpauth://totp/"), r.json()
    fetches = audit_actions("totp_setup_fetch")
    assert len(fetches) == 1, fetches
    assert all(secret not in (d or "") for _a, d in
               audit_actions()), "secret must never appear in the audit log"
    print("H10 TOTP setup still returns secret + fetch audit-logged OK")

    # --- 3. H11: GET /admin/backup forces step-up; other GETs don't ----
    stale_admin = H(1909, "Admin", auth_date=int(time.time()) - 301)
    r = c.get("/admin/backup", headers=stale_admin)
    assert r.status_code == 401, (r.status_code, r.text)
    assert "5 minutes" in r.json()["detail"], r.text
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    r = c.get("/admin/health", headers=stale_admin)
    assert r.status_code == 200, r.text
    print("H11 backup GET 401 stale / 200 fresh; health GET unaffected OK")

    # --- 4. M8: auto-backup counts in last_backup_at --------------------
    with SessionLocal() as db:
        db.query(models.AdminAuditLog).filter(
            models.AdminAuditLog.action.in_(
                ("backup_download", "backup_send"))).update(
            {"created_at": datetime.utcnow() - timedelta(days=10)})
        db.commit()
    main_mod._record_auto_backup(True, 100, 3)
    r = c.get("/admin/backup-status", headers=ADMIN)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["last_backup_kind"] == "auto", s
    last = datetime.fromisoformat(s["last_backup_at"])
    assert (datetime.utcnow() - last).total_seconds() < 120, s
    assert s["last_auto_backup_at"] is not None, s
    days = (datetime.utcnow() - last).days
    assert days <= 7, "auto-backup must stop the >7 days warning"
    print("M8 backup-status reflects auto-backup (kind auto, fresh) OK")

    # --- 5. M9+M14: broadcast commit-first, resume, System toggle ------
    FAIL.add(1902)  # Bob's DM fails: counts, never aborts the rest
    with SessionLocal() as db:
        carol = db.get(models.User, 1903)
        carol.notif_prefs = json.dumps({"system": False})
        db.commit()
    SENT.clear()
    r = c.post("/admin/broadcast", headers=ADMIN,
               json={"text": "Hello 181", "target": "all"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["recipients"] == 5 and b["sent"] == 3, b
    assert {cid for cid, _ in SENT} == {1901, 1908, 1909}, SENT
    bid = b["broadcast_id"]
    assert isinstance(bid, int), b
    with SessionLocal() as db:
        row = db.get(models.Broadcast, bid)
        assert row is not None, "row must be committed before delivery"
        assert sorted(json.loads(row.delivered_targets)) == \
            [1901, 1902, 1903, 1908, 1909], row.delivered_targets
        assert row.delivered_count == 3, row.delivered_count
        got = {n.user_id for n in db.query(models.Notification)
               .filter_by(type="announcement", text="Hello 181").all()}
    # M14: System-off Carol gets NO in-app row; DM-failed Bob still
    # gets one (System on); everyone else gets one.
    assert got == {1901, 1902, 1908, 1909}, got
    print("M9+M14 broadcast 3/5, row committed, System toggle honoured OK")

    # Retry/resume: no double DM, no duplicate in-app rows.
    SENT.clear()
    r = c.post("/admin/broadcast", headers=ADMIN,
               json={"text": "Hello 181", "target": "all",
                     "broadcast_id": bid})
    assert r.status_code == 200, r.text
    assert r.json()["sent"] == 0 and SENT == [], r.json()
    with SessionLocal() as db:
        n = db.query(models.Notification).filter_by(
            type="announcement", text="Hello 181").count()
    assert n == 4, n
    r = c.post("/admin/broadcast", headers=ADMIN,
               json={"text": "x", "broadcast_id": 999999})
    assert r.status_code == 404, r.status_code
    print("M9 resume skips delivered targets (no double DM/row) OK")

    # --- 6. M11: _client_ip and geoip agree on ONE rule (last hop) -----
    def _req(xff=None, host="9.9.9.9"):
        headers = []
        if xff is not None:
            headers.append((b"x-forwarded-for", xff.encode()))
        return Request({"type": "http", "method": "GET", "path": "/",
                        "headers": headers, "query_string": b"",
                        "server": ("testserver", 80), "scheme": "http",
                        "client": (host, 1234)})

    assert _client_ip(_req("1.1.1.1, 2.2.2.2")) == "2.2.2.2"
    assert _client_ip(_req("3.3.3.3")) == "3.3.3.3"
    assert _client_ip(_req()) == "9.9.9.9"
    assert _public_ip("1.1.1.1, 2.2.2.2") == "2.2.2.2"
    assert _public_ip("10.0.0.1, 8.8.8.8") == "8.8.8.8"
    assert _public_ip("10.0.0.1") is None
    assert _public_ip("") is None
    assert _client_ip(_req("1.1.1.1, 2.2.2.2")) == \
        _public_ip("1.1.1.1, 2.2.2.2"), "both helpers must agree"
    assert RATE_LIMITS["totp_verify"] == (5, 900), RATE_LIMITS
    assert RATE_LIMITS["admin_mutation"] == (120, 3600), RATE_LIMITS
    print("M11 _client_ip + geoip agree on last-hop OK")

    # --- 7. M6: media proxy upstream failures ---------------------------
    with SessionLocal() as db:
        db.add(models.Design(image_file_id="MEDIA_DESIGN",
                             prompt="seed"))
        db.commit()
    tok_alice = token_for(c, ALICE)

    def get_media(fid):
        return c.get("/media/" + fid + "?mt=" + tok_alice)

    MEDIA_MODE["getfile"] = "ok"
    MEDIA_MODE["send"] = "ok"
    r = get_media("MEDIA_DESIGN")
    assert r.status_code == 200 and r.content == b"abcde", \
        (r.status_code, r.content)
    for mode in ("malformed", "ok_false", "no_result"):
        MEDIA_MODE["getfile"] = mode
        MEDIA_MODE["send"] = "ok"
        r = get_media("MEDIA_DESIGN")
        assert r.status_code == 404, (mode, r.status_code)
    MEDIA_MODE["getfile"] = "ok"
    MEDIA_MODE["send"] = "raise"
    r = get_media("MEDIA_DESIGN")
    assert r.status_code == 502, (r.status_code, r.text)
    MEDIA_MODE["send"] = "midfail"
    r = get_media("MEDIA_DESIGN")
    assert r.status_code == 200 and r.content == b"ab", \
        (r.status_code, r.content)
    MEDIA_MODE["getfile"] = "ok"
    MEDIA_MODE["send"] = "ok"
    print("M6 media proxy malformed->404, send fail->502, mid-stream "
          "clean short body OK")

    # --- 8. M10: shared admin-mutation bucket (120/h) -------------------
    ratelimit.reset()
    r = c.post("/admin/broadcast", headers=ADMIN,
               json={"text": "bucket probe", "target": "all"})
    assert r.status_code == 200, r.text
    for i in range(119):
        r = c.post("/admin/ban", headers=ADMIN,
                   json={"telegram_id": 1903, "banned": True})
        assert r.status_code == 200, (i, r.status_code, r.text)
    r = c.post("/admin/ban", headers=ADMIN,
               json={"telegram_id": 1903, "banned": True})
    assert r.status_code == 429, (r.status_code, r.text)
    r = c.get("/admin/health", headers=ADMIN)
    assert r.status_code == 200, r.text
    print("M10 shared bucket: 1 broadcast + 119 bans OK, 121st 429, "
          "admin GET unaffected OK")

    # --- 9. M7: restore — encrypted-only when keyed, limit first -------
    from cryptography.fernet import Fernet  # noqa: E402
    settings.BACKUP_ENCRYPTION_KEY = ""
    db = SessionLocal()
    payload = _backup_payload(db)
    db.close()
    # No key: plaintext restores.
    r = c.post("/admin/restore", headers=ADMIN,
               json={"confirm": "RESTORE", "backup": payload})
    assert r.status_code == 200, r.text
    assert r.json()["restored"]["users"] >= 5, r.json()
    key = Fernet.generate_key().decode()
    settings.BACKUP_ENCRYPTION_KEY = key
    # Keyed: plaintext rejected, Fernet accepted.
    r = c.post("/admin/restore", headers=ADMIN,
               json={"confirm": "RESTORE", "backup": payload})
    assert r.status_code == 400, r.text
    assert "Encrypted backup required" in r.json()["detail"], r.text
    data, fname, enc = _backup_pack(payload)
    assert enc is True and fname.endswith(".json.enc"), fname
    assert _backup_unpack(data) == payload
    try:
        _backup_unpack(json.dumps(payload).encode())
        raise AssertionError("plaintext unpack must fail while keyed")
    except Exception as e:
        assert getattr(e, "status_code", None) == 400, e
    r = c.post("/admin/restore", headers=ADMIN,
               json={"confirm": "RESTORE",
                     "backup_encrypted": data.decode()})
    assert r.status_code == 200, r.text
    # Rate limit fires BEFORE any decrypt work: the 4th restore in
    # the hour is a 429 even for a perfectly valid payload.
    r = c.post("/admin/restore", headers=ADMIN,
               json={"confirm": "RESTORE",
                     "backup_encrypted": data.decode()})
    assert r.status_code == 429, (r.status_code, r.text)
    # With budget available, a garbage payload fails in unpack (400),
    # not in the limiter.
    ratelimit.reset()
    r = c.post("/admin/restore", headers=ADMIN,
               json={"confirm": "RESTORE",
                     "backup_encrypted": "not-a-backup"})
    assert r.status_code == 400, (r.status_code, r.text)
    # 50 MB on BOTH paths.
    ratelimit.reset()
    r = c.post("/admin/restore", headers=ADMIN,
               json={"confirm": "RESTORE",
                     "backup_encrypted": "x" * (_BACKUP_MAX_BYTES + 1)})
    assert r.status_code == 413, (r.status_code, r.text)
    assert "max 50 MB" in r.json()["detail"], r.text
    # Plaintext size limit is checked where plaintext is allowed:
    # with a key configured the encrypted-only rule fires first, so
    # clear the key for this leg.
    settings.BACKUP_ENCRYPTION_KEY = ""
    ratelimit.reset()
    big = {"format": "nexora-backup", "version": 1, "tables": {},
           "pad": "x" * (_BACKUP_MAX_BYTES + 1)}
    r = c.post("/admin/restore", headers=ADMIN,
               json={"confirm": "RESTORE", "backup": big})
    assert r.status_code == 413, (r.status_code, r.text)
    assert "max 50 MB" in r.json()["detail"], r.text
    settings.BACKUP_ENCRYPTION_KEY = ""
    print("M7 restore encrypted-only when keyed, limit first, 50 MB "
          "both paths OK")

    # --- 10. Backup tables (52), markers, asset version ----------------
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    bk = r.json()
    assert len(bk["tables"]) == 52, len(bk["tables"])
    assert len(_BACKUP_TABLES) == 52, len(_BACKUP_TABLES)
    assert HTML.count("?v=185") == 10, HTML.count("?v=185")
    assert "?v=18" + "0" not in HTML
    for m in ("totp_verify_failed", "totp_setup_fetch",
              "delivered_targets", "Encrypted backup required",
              "auto_backup_send", "admin_mutation",
              "Media upstream unavailable"):
        assert m in MAIN, m
    assert "Last public IP" in GEOIP and "_public_ip" in GEOIP, GEOIP
    r = c.get("/admin/health", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 185, r.json()
    print("backup 52 tables + markers + ?v=185 OK")

print("PHASE 181 OK")
