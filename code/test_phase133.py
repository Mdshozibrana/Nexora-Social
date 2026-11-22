"""Phase-133 tests: Telegram Stars tipping for creators.

Covers: create-tip validation (bad amount 400, self-tip 400,
blocked author 403, unknown post/user 404, no/both targets 400,
bot unavailable 503, unauthenticated 401); invoice request calls
the bot's send_invoice with currency XTR and the right payload
(repost resolves to the ORIGINAL author); PreCheckoutQuery answers
ok only for tip payloads; successful_payment records exactly one
tip (same charge id twice -> still one row), wrong payer ignored,
creator notified + in-app row; /me/tips sent/received; /users
public totals (names only, no per-tip amounts); /admin/tips totals
+ top + recent and non-admin 403; backup carries 39 tables incl.
tips; ?v=167 x5, no ?v=132; tip client markers + Phase 123-132
markers intact.
"""
import asyncio
import hashlib, hmac, json, os, time, urllib.parse
from types import SimpleNamespace

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase133.db"

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

import app.notify as notify_mod

SENT = []


async def fake_send(chat_id, text):
    SENT.append((chat_id, text))
    return True


notify_mod.send_message = fake_send

import app.main as main_mod
from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app import models

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


ADMIN = H(111, "Alice")
BOB = H(222, "Bob")
CAROL = H(333, "Carol")


class FakeBot:
    def __init__(self):
        self.invoices = []

    async def send_invoice(self, **kw):
        self.invoices.append(kw)
        return SimpleNamespace(message_id=1)


class FakeQuery:
    def __init__(self, payload):
        self.invoice_payload = payload
        self.answers = []

    async def answer(self, ok, error_message=None):
        self.answers.append((ok, error_message))


with TestClient(app) as c:
    for h in (ADMIN, BOB, CAROL):
        assert c.post("/auth", json={"initData": h["X-Init-Data"]}).status_code == 200

    # Bob posts; Carol reposts it (repost row author = Carol).
    r = c.post("/posts", headers=BOB, json={"type": "text", "caption": "hi"})
    assert r.status_code == 200, r.text
    p1 = r.json()["id"]
    r = c.post(f"/posts/{p1}/repost", headers=CAROL)
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        rp = db.query(models.Post).filter_by(
            type="repost", user_id=333).first()
        assert rp is not None
        p2 = rp.id

    # 1. Validation + bot-unavailable guard.
    assert c.post("/tips/create", headers=ADMIN,
                  json={"post_id": p1, "amount_stars": 50}).status_code == 503
    for body, want in (
            ({"post_id": p1, "amount_stars": 0}, 400),
            ({"post_id": p1, "amount_stars": 10001}, 400),
            ({"amount_stars": 50}, 400),
            ({"post_id": p1, "user_id": 222, "amount_stars": 50}, 400),
            ({"post_id": 99999, "amount_stars": 50}, 404),
            ({"user_id": 99999, "amount_stars": 50}, 404),
            ({"user_id": 111, "amount_stars": 50}, 400)):
        rr = c.post("/tips/create", headers=ADMIN, json=body)
        assert rr.status_code == want, (body, rr.status_code, rr.text)
    rr = c.post("/tips/create",
                json={"post_id": p1, "amount_stars": 50})
    assert rr.status_code == 401, rr.status_code
    print("tip validation + bot-unavailable 503 OK")

    # 2. Blocked author: Bob blocks Alice -> Alice cannot tip Bob.
    r = c.post("/users/111/block", headers=BOB)
    assert r.status_code == 200, r.text
    main_mod._bot_app = SimpleNamespace(bot=FakeBot())
    rr = c.post("/tips/create", headers=ADMIN,
                json={"user_id": 222, "amount_stars": 50})
    assert rr.status_code == 403, (rr.status_code, rr.text)
    r = c.post("/users/111/block", headers=BOB)
    assert r.status_code == 200 and r.json()["blocked"] is False, r.text
    print("tip blocked author 403 OK")

    # 3. Invoice: tipping the REPOST resolves to the original author.
    fake_bot = main_mod._bot_app.bot
    r = c.post("/tips/create", headers=ADMIN,
               json={"post_id": p2, "amount_stars": 50})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["invoice"] is True and b["amount_stars"] == 50, b
    assert b["to_name"] == "Bob", b
    assert len(fake_bot.invoices) == 1, fake_bot.invoices
    inv = fake_bot.invoices[0]
    assert inv["chat_id"] == 111 and inv["currency"] == "XTR", inv
    assert inv["payload"] == f"tip:111:222:{p1}:50", inv
    assert inv["prices"][0].label == "Tip", inv["prices"]
    assert inv["prices"][0].amount == 50, inv["prices"]
    assert "Bob" in inv["title"], inv
    # Profile tip: payload post is 0.
    r = c.post("/tips/create", headers=CAROL,
               json={"user_id": 222, "amount_stars": 10})
    assert r.status_code == 200, r.text
    assert fake_bot.invoices[1]["payload"] == "tip:333:222:0:10"
    print("tip invoice XTR + repost resolves to original OK")

    # 4. PreCheckout: ok only for tip payloads.
    q = FakeQuery(f"tip:111:222:{p1}:50")
    asyncio.run(bot_mod.precheckout_handler(
        SimpleNamespace(pre_checkout_query=q), SimpleNamespace()))
    assert q.answers == [(True, None)], q.answers
    q2 = FakeQuery("garbage")
    asyncio.run(bot_mod.precheckout_handler(
        SimpleNamespace(pre_checkout_query=q2), SimpleNamespace()))
    assert q2.answers[0][0] is False and q2.answers[0][1], q2.answers
    print("pre-checkout answers OK")

    # 5. successful_payment: one tip per charge id, wrong payer ignored.
    def pay(payload, charge, payer, name="Alice"):
        sp = SimpleNamespace(
            invoice_payload=payload, telegram_payment_charge_id=charge,
            total_amount=50, currency="XTR")
        upd = SimpleNamespace(
            message=SimpleNamespace(successful_payment=sp),
            effective_user=SimpleNamespace(id=payer, first_name=name))
        asyncio.run(bot_mod.successful_payment_handler(
            upd, SimpleNamespace()))

    SENT.clear()
    pay(f"tip:111:222:{p1}:50", "ch_1", 111)
    pay(f"tip:111:222:{p1}:50", "ch_1", 111)  # duplicate update
    pay("tip:111:222:1:50", "ch_9", 999)  # payer != payload from
    with SessionLocal() as db:
        rows = db.query(models.Tip).all()
        assert len(rows) == 1, len(rows)
        t = rows[0]
        assert (t.from_user_id, t.to_user_id, t.post_id,
                t.amount_stars) == (111, 222, p1, 50), t
        assert t.telegram_payment_charge_id == "ch_1"
        assert t.status == "completed"
        notif = db.query(models.Notification).filter_by(
            user_id=222, type="tip").all()
        assert len(notif) == 1, len(notif)
    assert SENT and SENT[0][0] == 222 and "50" in SENT[0][1], SENT
    pay("tip:333:222:0:10", "ch_2", 333, "Carol")
    print("successful_payment records one tip, duplicate ignored OK")

    # 6. Public totals: names only, no per-tip amounts.
    r = c.get("/users/222/tips")
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["total_stars_received"] == 60 and u["tip_count"] == 2, u
    assert [x["from_name"] for x in u["recent"]] == ["Carol", "Alice"], u
    assert all("amount_stars" not in x for x in u["recent"]), u
    print("public tip totals OK")

    # 7. /me/tips sent/received.
    r = c.get("/me/tips", headers=ADMIN)
    d = r.json()
    assert len(d["sent"]) == 1 and d["sent"][0]["amount_stars"] == 50, d
    assert d["received"] == [], d
    r = c.get("/me/tips", headers=BOB)
    d = r.json()
    assert len(d["received"]) == 2 and d["sent"] == [], d
    assert sum(x["amount_stars"] for x in d["received"]) == 60, d
    print("/me/tips OK")

    # 8. Admin tips: totals + top + recent; non-admin 403.
    r = c.get("/admin/tips", headers=ADMIN)
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["total_stars"] == 60 and a["tip_count"] == 2, a
    assert a["top"][0]["user_id"] == 222, a
    assert a["top"][0]["total_stars"] == 60, a
    assert len(a["recent"]) == 2, a
    r = c.get("/admin/tips", headers=BOB)
    assert r.status_code == 403, r.status_code
    r = c.get("/admin/tips")
    assert r.status_code == 401, r.status_code
    print("admin tips OK")

    # 9. Backup carries 39 tables incl. tips with the rows.
    r = c.get("/admin/backup", headers=ADMIN)
    assert r.status_code == 200, r.status_code
    bk = r.json()
    assert len(bk["tables"]) == 44, len(bk["tables"])
    assert "tips" in bk["tables"], list(bk["tables"])
    assert len(bk["tables"]["tips"]) == 2, len(bk["tables"]["tips"])
    print("backup: 39 tables incl. tips OK")

    # 10. Client markers + asset version.
    html = open("webapp/index.html").read()
    assert html.count("?v=167") == 10, html.count("?v=167")
    assert "?v=132" not in html
    assert 'id="earn-tips-total"' in html
    assert 'id="earn-tips-top"' in html
    js = open("webapp/app.js").read()
    for m in ("openTipSheet", "TIP_AMOUNTS", "tip-btn",
              "tips-card", "earn-tips-total", "Invoice sent",
              "⭐ Tip", "/tips/create", "/me/tips", "/admin/tips"):
        assert m in js, m
    for m in ("topScroller", "pollBlock", "loadDrafts", "renderPh",
              "goFeedTo", "loadTrending", "loadHealth", "loadAdminBrowse",
              "loadSecurityLog", "loadPayouts", "loadBroadcasts",
              "loadBackupStatus"):
        assert m in js, m
    css = open("webapp/style.css").read()
    assert ".tip-chip.active" in css  # Phase 145: .tip-total left with the profile stars line
    print("client markers + ?v=167 OK")

    # Restore the real (absent in tests) bot app so the TestClient
    # shutdown does not touch the fake's missing updater.
    main_mod._bot_app = None

print("PHASE-133 TESTS PASSED")
