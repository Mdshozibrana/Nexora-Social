"""Phase-164 tests: fix ALL 2026-11-21 production security audit
findings (owner, Nov 21: "fix everything").

- P1: /media token is user-bound (user id + issue time + expiry,
  1 hour), honours revocation, and the handler enforces file
  visibility (same rules as the feed) + a 60/min per-user budget.
- H1: admin step-up — mutating /admin/* calls need initData no
  older than 5 minutes; read-only admin calls keep 24h. Per-admin
  TOTP (pyotp, env secret, 12-hour session flag) + status/setup/
  verify endpoints + Admin Panel gate.
- H2: _client_ip takes the LAST X-Forwarded-For hop; /media has a
  dedicated 60/min per-user bucket.
- H3: bot-token rotation runbook in SECURITY.md.
- H4: RLS policies + nexora_app role written (code/migrations/) —
  ready, NOT live-enabled (no local Postgres to test against).
- M1: Dependabot config + monthly pip-audit documented (pip-audit
  run 21 Nov 2026: no known vulnerabilities).
- M2: Fernet backup encryption (env key) — download/send/auto all
  encrypted when the key is set; restore accepts both formats.
- L1: single-instance limiter assumption already recorded.
"""
import base64
import hashlib
import hmac
import io
import json
import os
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase164.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402
from app.main import app  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import models, ratelimit  # noqa: E402
from app.main import _media_token, _media_token_ok, _backup_pack  # noqa: E402
from app.main import _backup_unpack, _backup_payload, _client_ip  # noqa: E402
from app.main import _TOTP_VERIFIED  # noqa: E402
from app.config import settings, RATE_LIMITS  # noqa: E402


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
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name},
                                          auth_date=auth_date)}


def mint_token(uid, iat, exp):
    sig = hmac.new(settings.BOT_TOKEN.encode(),
                   f"nexora-media:{uid}:{iat}:{exp}".encode(),
                   hashlib.sha256).hexdigest()
    raw = f"{uid}.{iat}.{exp}.{sig}".encode()
    return base64.urlsafe_b64encode(raw).decode()


ADMIN, MOD, AMY, BOB, CAROL, DAVE = (
    H(999, "Admin"), H(888, "Mod"), H(111, "Amy"), H(222, "Bob"),
    H(333, "Carol"), H(444, "Dave"))

# Fake Telegram file transport for /media (copied from Phase 16):
# getFile answers a fixed path, the download streams fixed bytes.


class FakeGetFileResp:
    status_code = 200

    def json(self):
        return {"result": {"file_path": "photos/file_1.jpg"}}


class FakeStreamResp:
    status_code = 200
    headers = {"content-type": "image/jpeg", "content-length": "5"}

    async def aiter_bytes(self):
        yield b"ab"
        yield b"cde"

    async def aclose(self):
        pass


class Fake404Resp:
    status_code = 404
    headers = {"content-type": "application/json"}

    async def aiter_bytes(self):
        yield b'{"ok":false}'

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
        token = os.environ["BOT_TOKEN"]
        assert url == f"https://api.telegram.org/bot{token}/getFile", url
        assert params and params.get("file_id"), params
        return FakeGetFileResp()

    def build_request(self, method, url, headers=None):
        return (method, url, headers)

    async def send(self, req, stream=False):
        token = os.environ["BOT_TOKEN"]
        expected = f"https://api.telegram.org/file/bot{token}/photos/file_1.jpg"
        if req[1] != expected:
            return Fake404Resp()
        return FakeStreamResp()

    async def aclose(self):
        pass


httpx.AsyncClient = FakeAsyncClient


def decode_token(tok):
    user_s, iat_s, exp_s, sig = base64.urlsafe_b64decode(
        tok.encode()).decode().split(".", 3)
    return int(user_s), int(iat_s), int(exp_s), sig


def token_for(c, headers):
    r = c.post("/auth", json={"initData": headers["X-Init-Data"]})
    assert r.status_code == 200, r.text
    tok = r.json()["media_token"]
    assert tok
    return tok


with TestClient(app) as c:
    # --- seed: users via /auth, then rows via the DB ---
    for h in (AMY, BOB, CAROL, DAVE, ADMIN, MOD):
        r = c.post("/auth", json={"initData": h["X-Init-Data"]})
        assert r.status_code == 200, r.text
    db = SessionLocal()
    amy = db.get(models.User, 111)
    amy.is_private = True
    amy.photo_file_id = "AMY_PHOTO"
    amy.cover_file_id = "AMY_COVER"
    db.add(models.Post(user_id=111, type="photo", media_file_id="AMY_POST",
                       caption="private"))
    db.add(models.Post(user_id=111, type="photo", media_file_id="AMY_PUBLIC",
                       caption="public"))
    # Amy's public post must stay public: privacy is per-account, so
    # use Bob's post for the public-media case instead (below).
    db.add(models.Post(user_id=222, type="photo", media_file_id="BOB_POST",
                       caption="bob"))
    db.add(models.Story(user_id=111, media_file_id="AMY_STORY"))
    db.add(models.Story(user_id=111, media_file_id="AMY_OLD_STORY",
                        created_at=datetime.utcnow() - timedelta(hours=25)))
    db.add(models.Message(sender_id=111, recipient_id=222,
                          media_file_id="DM_AB", text=""))
    db.add(models.Design(image_file_id="DESIGN_1", prompt="seed"))
    db.add(models.Draft(user_id=111, media_file_id="AMY_DRAFT", text="d"))
    db.add(models.ScheduledPost(
        user_id=111, media_file_id="AMY_SCHED",
        scheduled_at=datetime.utcnow() + timedelta(hours=1),
        status="pending"))
    db.add(models.Follow(follower_id=222, following_id=111))
    db.add(models.UserBlock(blocker_id=111, blocked_id=333))
    db.commit()
    db.close()

    tok_amy = token_for(c, AMY)
    tok_bob = token_for(c, BOB)
    tok_carol = token_for(c, CAROL)

    def get_media(tok, fid):
        return c.get("/media/" + fid + ("?mt=" + tok if tok else ""))

    # --- P1: the token is user-bound, 1 hour, revocation-aware ---
    uid, iat, exp, _sig = decode_token(tok_amy)
    assert uid == 111, uid
    assert exp - iat == 3600, exp - iat
    assert _media_token_ok(tok_amy) == (111, iat)
    print("P1 token shape OK (user-bound, 1h, iat carried)")

    r = get_media(None, "BOB_POST")
    assert r.status_code == 401, r.status_code
    r = get_media("garbage.token", "BOB_POST")
    assert r.status_code == 401, r.status_code
    print("P1 no token / garbage token -> 401 OK")

    # Expired token (minted with a past window) is rejected.
    now = int(time.time())
    r = get_media(mint_token(111, now - 7200, now - 3600), "BOB_POST")
    assert r.status_code == 401, r.status_code
    # A token minted for another user cannot be replayed as mine:
    # Bob's token carries Bob's id; the handler resolves Amy's files
    # as Bob — private ones 404.
    r = get_media(tok_bob, "AMY_POST")
    assert r.status_code == 200, r.status_code  # Bob follows Amy
    r = get_media(tok_carol, "AMY_POST")
    assert r.status_code == 404, r.status_code  # Carol does not follow
    print("P1 expired + cross-user tokens OK")

    # Revocation kills the token: revoke Amy after minting, her own
    # token (issued before the revocation) must fail.
    db = SessionLocal()
    db.get(models.User, 111).auth_revoked_at = datetime.utcnow() + timedelta(seconds=5)
    db.commit()
    db.close()
    r = get_media(tok_amy, "BOB_POST")
    assert r.status_code == 401, r.status_code
    db = SessionLocal()
    db.get(models.User, 111).auth_revoked_at = None
    db.commit()
    db.close()
    print("P1 revoked token -> 401 OK")

    # --- P1: visibility is enforced per file, same rules as feed ---
    r = get_media(tok_bob, "BOB_POST")
    assert r.status_code == 200 and r.content == b"abcde", r.status_code
    assert r.headers["cache-control"] == "private, max-age=3600, immutable"
    r = get_media(tok_carol, "BOB_POST")
    assert r.status_code == 200, r.status_code  # public post
    r = get_media(tok_amy, "AMY_POST")
    assert r.status_code == 200, r.status_code  # own private post
    r = get_media(tok_carol, "AMY_PUBLIC")
    assert r.status_code == 404, r.status_code  # Amy is private: ALL her posts need follow
    r = get_media(tok_bob, "AMY_STORY")
    assert r.status_code == 200, r.status_code  # live story, follower
    r = get_media(tok_carol, "AMY_STORY")
    assert r.status_code == 404, r.status_code  # live story, stranger
    r = get_media(tok_amy, "AMY_OLD_STORY")
    assert r.status_code == 404, r.status_code  # expired story
    r = get_media(tok_bob, "DM_AB")
    assert r.status_code == 200, r.status_code  # DM participant
    r = get_media(tok_amy, "DM_AB")
    assert r.status_code == 200, r.status_code  # DM participant
    r = get_media(tok_carol, "DM_AB")
    assert r.status_code == 404, r.status_code  # not a participant
    r = get_media(tok_carol, "DESIGN_1")
    assert r.status_code == 200, r.status_code  # public design gallery
    r = get_media(tok_bob, "AMY_PHOTO")
    assert r.status_code == 200, r.status_code  # follower sees photo
    r = get_media(tok_carol, "AMY_PHOTO")
    assert r.status_code == 404, r.status_code  # stranger, private
    r = get_media(tok_bob, "AMY_COVER")
    assert r.status_code == 200, r.status_code
    r = get_media(tok_amy, "AMY_DRAFT")
    assert r.status_code == 200, r.status_code  # own draft
    r = get_media(tok_bob, "AMY_DRAFT")
    assert r.status_code == 404, r.status_code  # another member's draft
    r = get_media(tok_amy, "AMY_SCHED")
    assert r.status_code == 200, r.status_code  # own scheduled post
    r = get_media(tok_bob, "AMY_SCHED")
    assert r.status_code == 404, r.status_code
    r = get_media(tok_amy, "NO_SUCH_FILE")
    assert r.status_code == 404, r.status_code  # unknown fails closed
    # Blocked either way: Amy blocked Carol, so even Bob's public
    # post is not the issue — Amy's own public-visibility file is;
    # use her cover (already 404 above) and her post: Carol is
    # blocked by Amy, so AMY_POST is 404 for Carol even though Bob
    # (a follower) sees it.
    r = get_media(tok_carol, "AMY_POST")
    assert r.status_code == 404, r.status_code
    print("P1 visibility matrix OK (posts/stories/DMs/designs/photos/drafts)")

    # --- H1: admin step-up — stale initData fails mutations only ---
    stale_admin = H(999, "Admin", auth_date=int(time.time()) - 301)
    r = c.post("/admin/ban", headers=stale_admin,
               json={"telegram_id": 222, "banned": True})
    assert r.status_code == 401, r.status_code
    assert "5 minutes" in r.json()["detail"], r.text
    r = c.post("/admin/ban", headers=ADMIN,
               json={"telegram_id": 222, "banned": True})
    assert r.status_code == 200, r.text
    assert r.json()["is_banned"] is True
    r = c.post("/admin/ban", headers=ADMIN,
               json={"telegram_id": 222, "banned": False})
    assert r.status_code == 200, r.text
    # Read-only admin calls are unaffected by the 5-minute rule.
    r = c.get("/admin/health", headers=stale_admin)
    assert r.status_code == 200, r.text
    # Moderator mutations step up too.
    stale_mod = H(888, "Mod", auth_date=int(time.time()) - 301)
    r = c.post("/admin/ban", headers=stale_mod,
               json={"telegram_id": 333, "banned": True})
    assert r.status_code == 401, r.status_code
    r = c.post("/admin/ban", headers=MOD,
               json={"telegram_id": 333, "banned": True})
    assert r.status_code == 200, r.text
    r = c.post("/admin/ban", headers=MOD,
               json={"telegram_id": 333, "banned": False})
    assert r.status_code == 200, r.text
    print("H1 step-up OK (mutations 401 stale / 200 fresh; reads unaffected)")

    # --- H2: client IP is the last X-Forwarded-For hop ---
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
    assert RATE_LIMITS["media"] == (60, 60), RATE_LIMITS.get("media")
    print("H2 _client_ip OK (last hop) + media bucket (60, 60) OK")

    # --- H2: /media is rate-limited per user ---
    ratelimit.reset()
    tok_dave = token_for(c, DAVE)
    for _i in range(60):
        r = get_media(tok_dave, "DESIGN_1")
        assert r.status_code == 200, (_i, r.status_code)
    r = get_media(tok_dave, "DESIGN_1")
    assert r.status_code == 429, r.status_code
    print("H2 /media rate limit OK (60/min, 61st is 429)")

    # --- M2: backup encryption round-trip ---
    from cryptography.fernet import Fernet  # noqa: E402
    from app.main import _build_auto_backup  # noqa: E402
    key = Fernet.generate_key().decode()
    settings.BACKUP_ENCRYPTION_KEY = key
    db = SessionLocal()
    payload = _backup_payload(db)
    db.close()
    data, fname, enc = _backup_pack(payload)
    assert enc is True and fname.endswith(".json.enc"), fname
    assert _backup_unpack(data) == payload
    assert _backup_unpack(json.dumps(payload).encode()) == payload
    settings.BACKUP_ENCRYPTION_KEY = Fernet.generate_key().decode()
    try:
        _backup_unpack(data)
        raise AssertionError("wrong key must fail")
    except HTTPException as e:
        assert e.status_code == 400, e.status_code
    settings.BACKUP_ENCRYPTION_KEY = key
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.content[:6] == b"gAAAAA"
    fname2, data2, total2 = _build_auto_backup()
    assert fname2.startswith("nexora-auto-backup-") and data2[:6] == b"gAAAAA"
    r = c.post("/admin/restore", headers=ADMIN,
               json={"confirm": "RESTORE", "backup_encrypted": data.decode()})
    assert r.status_code == 200, r.text
    assert r.json()["restored"]["users"] >= 6, r.json()
    r = c.post("/admin/restore", headers=ADMIN,
               json={"confirm": "RESTORE", "backup": payload})
    assert r.status_code == 200, r.text
    enc_path = "/tmp/phase164_test_backup.json.enc"
    out_path = "/tmp/phase164_test_backup.json"
    open(enc_path, "wb").write(data)
    helper = os.path.expanduser("~/workspace/nexora_designs/decrypt_backup.py")
    res = subprocess.run([sys.executable, helper, enc_path, "--key", key,
                          "-o", out_path], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert json.load(open(out_path)) == payload
    settings.BACKUP_ENCRYPTION_KEY = ""
    data3, fname3, enc3 = _backup_pack(payload)
    assert enc3 is False and fname3.endswith(".json"), fname3
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert "application/json" in r.headers["content-type"]
    print("M2 backup encryption OK (pack/unpack/restore/helper/plain fallback)")

    # --- H1: TOTP (per-admin second factor) ---
    import pyotp  # noqa: E402
    assert settings.ADMIN_TOTP_SECRET == ""
    r = c.get("/admin/totp/status", headers=ADMIN)
    assert r.json() == {"configured": False, "verified": True}, r.json()
    r = c.get("/admin/health", headers=ADMIN)
    assert r.status_code == 200, r.text
    secret = pyotp.random_base32()
    settings.ADMIN_TOTP_SECRET = secret
    r = c.get("/admin/totp/status", headers=ADMIN)
    assert r.json() == {"configured": True, "verified": False}, r.json()
    r = c.get("/admin/health", headers=ADMIN)
    assert r.status_code == 403, r.status_code
    assert "Admin verification required" in r.json()["detail"], r.text
    real = pyotp.TOTP(secret).now()
    wrong = "000000" if real != "000000" else "111111"
    r = c.post("/admin/totp/verify", headers=ADMIN, json={"code": wrong})
    assert r.status_code == 400, r.text
    r = c.post("/admin/totp/verify", headers=ADMIN, json={"code": real})
    assert r.status_code == 200 and r.json()["verified"] is True, r.text
    r = c.get("/admin/health", headers=ADMIN)
    assert r.status_code == 200, r.text
    r = c.get("/admin/totp/setup", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["secret"] == secret
    assert r.json()["otpauth_url"].startswith("otpauth://totp/"), r.json()
    r = c.get("/admin/totp/setup", headers=stale_admin)
    assert r.status_code == 401, r.status_code
    _TOTP_VERIFIED[999] = time.time() - 1
    r = c.get("/admin/health", headers=ADMIN)
    assert r.status_code == 403, r.status_code
    settings.ADMIN_TOTP_SECRET = ""
    _TOTP_VERIFIED.clear()
    r = c.get("/admin/health", headers=ADMIN)
    assert r.status_code == 200, r.text
    print("H1 TOTP OK (status/setup/verify/expiry; dormant without secret)")

    # --- M1 / H4 / L1: docs + files, no live wiring ---
    ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
    dep = open(os.path.join(ROOT, ".github/dependabot.yml")).read()
    assert 'package-ecosystem: "pip"' in dep and '"/code"' in dep
    sec = open(os.path.join(ROOT, "SECURITY.md")).read()
    assert "pip-audit" in sec and "phase164_rls" in sec
    assert "ADMIN_TOTP_SECRET" in sec and "BACKUP_ENCRYPTION_KEY" in sec
    rls = open(os.path.join(ROOT, "code/migrations/phase164_rls.sql")).read()
    assert "CREATE POLICY" in rls and "FORCE ROW LEVEL SECURITY" in rls
    assert "app.current_user_id" in rls and "app.is_admin" in rls
    role = open(os.path.join(ROOT, "code/migrations/phase164_rls_role.sql")).read()
    assert "nexora_app" in role
    assert "GRANT SELECT, INSERT, UPDATE, DELETE" in role
    main_src = open(os.path.join(ROOT, "code/app/main.py")).read()
    assert "phase164_rls" not in main_src  # not wired into _migrate
    rl_src = open(os.path.join(ROOT, "code/app/ratelimit.py")).read()
    assert "single instance" in rl_src.lower()
    print("M1/H4/L1 OK (dependabot, RLS files ready-not-live, limiter note)")

    # --- neighbours + version + routes ---
    html = c.get("/webapp/").text
    assert html.count("?v=164") == 10, html.count("?v=164")
    assert "?v=16" + "3" not in html
    assert "app.js?v=164" in html and "style.css?v=164" in html
    js = c.get("/webapp/app.js").text
    for marker in ("vname-text", "fitVerifiedNames", "totpGateAdmin",
                   "refreshMediaToken", "bloodDistance", "photo_file_id",
                   "MASCOT_TIPS_BY_VIEW", "loadSkills"):
        assert marker in js, marker
    seg = js[js.index("async function loadBloodDonors"):
             js.index("async function loadBloodRequests")]
    assert "verifiedBadge" in seg, "Phase 163 Blood donor tick gone"
    games = c.get("/webapp/games.js").text
    assert "arch-remote" not in games and "arch-shoot" not in games
    css = c.get("/webapp/style.css").text
    assert "composer-row" in css
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 166, len(paths)
    for p in ("/admin/totp/status", "/admin/totp/setup",
              "/admin/totp/verify"):
        assert p in paths, p
    h = c.get("/admin/health", headers=ADMIN).json()
    assert h["version"] == 164, h
    print("neighbours + version + routes OK (166 routes, ?v=164)")

print("PHASE 164 OK")
