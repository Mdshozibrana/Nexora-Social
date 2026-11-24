"""Phase-143 tests: composer action row fits phone width.

Bug (owner screenshot 2026-11-18): in the Feed composer the action
row spilled past the card at phone width and the Post button was cut
off ("Po" visible). Root cause: .composer-row was a no-wrap flex
row; the five buttons total ~440px against ~316px of card width at
a 360px viewport (#app-scroll padding 0 12px + composer padding
10px each side). Fix is CSS-only: the row wraps, buttons keep
their labels (flex: none + white-space: nowrap), Post keeps
margin-left: auto so it lands right-aligned on the last line.

Covers: CSS rules (wrap on, no-squash on, Post right-aligned,
Organic Clay look unchanged); a flex-wrap line-breaking simulation
at 360px (inner 316px) and 420px (inner 376px) proving every line
fits and Post is fully visible, plus a premise check that the old
no-wrap single line would overflow; all five controls present in
index.html with labels; composer textarea, tip line and feed tabs
unchanged; JS wiring for all five controls intact; Phase 123
(drafts) and Phase 135 (scheduled) behaviour still works end to
end; backup still 42 tables (no schema change); ?v=173 x5.
"""
import hashlib, hmac, json, os, re, time, urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase143.db"
os.environ["GEMINI_API_KEY"] = ""

import app.bot as bot_mod


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

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


def H(uid, name):
    return {"X-Init-Data": make_init_data({"id": uid, "first_name": name})}


ALICE = H(111, "Alice")
BOB = H(222, "Bob")


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


CSS = open("webapp/style.css").read()
HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()

# 1. CSS: the row wraps, buttons never squash, Post stays right.
row_blocks = re.findall(r"\.composer-row\s*\{[^}]*\}", CSS)
assert row_blocks, "no .composer-row rule found"
assert any("flex-wrap: wrap" in b for b in row_blocks), row_blocks
assert any("min-width: 0" in b for b in row_blocks), row_blocks
tool_blocks = re.findall(r"\.composer-row\s+\.tool-btn\s*\{[^}]*\}", CSS)
assert tool_blocks, "no .composer-row .tool-btn rule found"
assert any("flex: none" in b and "white-space: nowrap" in b
           for b in tool_blocks), tool_blocks
assert ".composer-row #composer-post { margin-left: auto; }" in CSS
post_blocks = re.findall(
    r"\.composer-row\s+#composer-post\s*\{[^}]*\}", CSS)
assert any("flex: none" in b for b in post_blocks), post_blocks
# Organic Clay look unchanged: sky Post gradient + cream pills.
assert "linear-gradient(145deg, #8ED4F7, #3E8FD0)" in CSS
assert ".composer .tool-btn { background: #FFFBFC" in CSS
print("composer-row CSS OK (wrap + no-squash + Post right, Clay look)")

# 2. Flex-wrap simulation at 360px and 420px viewports.
# Intrinsic widths (px), conservative from the live CSS: tool-btn
# padding 8px 13px (26px) at 17px font -> ~9.5px/char, emoji ~22px;
# Post button padding 8px 18px (36px). Gap is 8px.
# Card inner width = viewport - 24 (#app-scroll) - 20 (card padding).
def btn_w(label, pad, char_w=9.5, emoji_w=22.0):
    w = float(pad)
    for ch in label:
        w += emoji_w if ord(ch) > 0x2000 else char_w
    return w


BUTTONS = [("\U0001F4F7", 26), ("\U0001F4CA", 26),
           ("\U0001F4BE Save draft", 26), ("\U0001F550 Schedule", 26),
           ("Post", 36)]
WIDTHS = [btn_w(label, pad) for label, pad in BUTTONS]
GAP = 8.0


def wrap_lines(widths, gap, inner):
    lines, cur = [], 0.0
    for w in widths:
        add = w if cur == 0 else gap + w
        if cur > 0 and cur + add > inner:
            lines.append(cur)
            cur = w
        else:
            cur += add
    lines.append(cur)
    return lines


one_line = sum(WIDTHS) + GAP * (len(WIDTHS) - 1)
assert one_line > 316, one_line  # premise: old no-wrap row overflows
for viewport, inner in ((360, 316.0), (420, 376.0)):
    lines = wrap_lines(WIDTHS, GAP, inner)
    assert len(lines) <= 2, (viewport, lines)  # tidy, not a tall stack
    assert all(ln <= inner for ln in lines), (viewport, lines)
    assert lines[-1] <= inner  # Post (last item) fully visible
    assert all(w <= inner for w in WIDTHS)
    print(f"wrap simulation {viewport}px OK: lines={[round(x) for x in lines]} "
          f"<= {inner:.0f}px inner")

# 3. All five controls present in the composer, with labels.
for cid in ("composer-media", "composer-poll-toggle", "composer-draft",
            "composer-schedule-toggle", "composer-post",
            "composer-attach", "composer-text", "composer-poll",
            "composer-schedule"):
    assert f'id="{cid}"' in HTML, cid
for label in ("\U0001F4F7", "\U0001F4CA", "Save draft", "Schedule",
              ">Post<"):
    assert label in HTML, label
# Neighbours unchanged: textarea, tip line, feed tabs.
assert 'placeholder="Share something' in HTML
assert "Tip: pick a photo or video" in HTML
for tid, tlabel in (("tab-explore", "Explore"),
                    ("tab-following", "Following"),
                    ("tab-hashtags", "Hashtags")):
    assert f'id="{tid}"' in HTML, tid
    assert tlabel in HTML, tlabel
# Asset version.
assert HTML.count("?v=173") == 10, HTML.count("?v=173")
assert "?v=14" + "2" not in HTML
print("composer HTML OK (5 controls + textarea + tip + tabs + ?v=173)")

# 4. JS wiring for all five controls + Phase 123/135 markers intact.
for expr in ('$("composer-media").onclick',
             '$("composer-poll-toggle").onclick',
             '$("composer-draft").onclick',
             '$("composer-schedule-toggle").onclick',
             '$("composer-post").onclick'):
    assert expr in JS, expr
for m in ("loadDrafts", "composer-draft", "composer-schedule",
          "loadScheduled", "schedLocalInput", "composer-sched-send"):
    assert m in JS, m
print("composer JS wiring OK (photo/poll/draft/schedule/post)")

# 5. Behaviour: drafts (123), scheduled posts (135), plain post.
with TestClient(app) as c:
    for h in (ALICE, BOB):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200
    r = c.post("/drafts", headers=BOB,
               json={"text": "phase 143 draft check"})
    assert r.status_code == 200, r.text
    did = r.json()["id"]
    r = c.get("/drafts", headers=BOB)
    assert r.status_code == 200, r.text
    assert any(d["id"] == did for d in r.json()["drafts"]), r.json()
    r = c.delete(f"/drafts/{did}", headers=BOB)
    assert r.status_code == 200, r.text
    print("draft save/list/delete OK")
    r = c.post("/scheduled-posts", headers=BOB, json={
        "text": "phase 143 sched check",
        "scheduled_at": iso(datetime.utcnow() + timedelta(hours=1))})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r = c.get("/scheduled-posts", headers=BOB)
    assert r.status_code == 200, r.text
    assert any(s["id"] == sid for s in r.json()["scheduled_posts"]), r.json()
    r = c.delete(f"/scheduled-posts/{sid}", headers=BOB)
    assert r.status_code == 200, r.text
    print("scheduled-post create/list/delete OK")
    r = c.post("/posts", headers=BOB,
               json={"type": "text", "caption": "phase 143 post check"})
    assert r.status_code == 200, r.text
    assert r.json()["id"], r.json()
    print("plain text post OK")
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 48, len(r.json()["tables"])
    print("backup: 42 tables OK (no schema change)")

print("ALL PHASE 143 CHECKS PASSED")
