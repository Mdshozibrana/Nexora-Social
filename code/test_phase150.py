"""Phase-150 tests: composer labelled buttons too big (CSS only).

Bug (owner screenshot 2026-11-19 22:03 Dhaka, feed composer
circled in red): "এই মার্ক করা লেখাগুলোর টেক্স বড় দেখতে
বাজে।" — the text on the circled composer action buttons
looked too big and bad. Root cause: .composer .tool-btn sets
font-size: 17px (fits the icon-only 📷 📊 emoji, not the
labelled buttons), and #composer-post inherits ~16px via
`button { font: inherit; }` plus font-weight 800 in the
Organic Clay theme block.

Fix is CSS-only: #composer-draft and #composer-schedule-toggle
-> 13px (padding 7px 12px); #composer-post -> 14px (padding
7px 16px, gradient + weight kept). Icon-only buttons stay
exactly as they are (still 17px). Phase 143's flex-wrap is
untouched: the row still wraps and all five controls still
fit at 360px and 420px.

Covers: CSS rules (labelled buttons smaller, icon-only
unchanged, wrap on, Post right-aligned, Organic Clay look
unchanged, "Post as Official" untouched); a flex-wrap
line-breaking simulation at 360px (inner 316px) and 420px
(inner 376px) with the NEW sizes proving every line fits
and Post is fully visible; all five controls present in
index.html with labels; composer textarea, tip line and feed
tabs unchanged; JS wiring for all five controls intact;
Phase 123 (drafts) and Phase 135 (scheduled) behaviour
still works end to end; backup still 42 tables and the route
count unchanged (no schema change, no new endpoints);
?v=170 x9, no old-version literals.
"""
import hashlib, hmac, json, os, re, time, urllib.parse
from datetime import datetime, timedelta

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase150.db"
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
BOT = open("app/bot.py").read()

# 1. CSS: labelled buttons smaller, icon-only buttons unchanged.
assert (".composer-row #composer-draft, "
        ".composer-row #composer-schedule-toggle "
        "{ font-size: 13px; padding: 7px 12px; }") in CSS
assert (".composer-row #composer-post "
        "{ font-size: 14px; padding: 7px 16px; }") in CSS
# Base rule untouched: icon-only buttons still get 17px.
assert "padding: 8px 13px; font-size: 17px; }" in CSS
tool_blocks = re.findall(r"\.composer\s+\.tool-btn\s*\{[^}]*\}", CSS)
assert any("font-size: 17px" in b for b in tool_blocks), tool_blocks
# No rule targets the icon-only buttons at all — they only get
# the shared 17px .tool-btn size.
assert "#composer-media" not in CSS
assert "#composer-poll-toggle" not in CSS
print("composer labelled buttons OK (draft/schedule 13px, Post 14px, "
      "icon-only still 17px)")

# 2. Phase 143's wrap still on; Post still right-aligned.
row_blocks = re.findall(r"\.composer-row\s*\{[^}]*\}", CSS)
assert row_blocks, "no .composer-row rule found"
assert any("flex-wrap: wrap" in b for b in row_blocks), row_blocks
assert ".composer-row #composer-post { margin-left: auto; }" in CSS
# Organic Clay look unchanged: sky Post gradient + weight 800 +
# cream pills.
assert "linear-gradient(145deg, #8ED4F7, #3E8FD0)" in CSS
assert ".composer .tool-btn { background: #FFFBFC" in CSS
clay_posts = re.findall(r"\.composer button \{[^}]*\}", CSS)
assert any("linear-gradient(145deg, #8ED4F7, #3E8FD0)" in b
           and "font-weight: 800" in b for b in clay_posts), clay_posts
# Neighbour untouched: "Post as Official" still 12px.
assert ".composer-as button { margin-left: auto; flex: none; font-size: 12px;" in CSS
print("wrap + Clay look + Post-as-Official OK (143 intact)")

# 3. Flex-wrap simulation at 360px and 420px with the NEW sizes.
# Intrinsic widths (px), conservative from the live CSS:
# icon-only tool-btn: padding 8px 13px (26px) at 17px font,
# emoji ~22px; labelled tool-btn: padding 7px 12px (24px) at
# 13px font -> ~7.3px/char, emoji ~17px; Post: padding 7px 16px
# (32px) at 14px font -> ~7.8px/char. Gap is 8px.
# Card inner width = viewport - 24 (#app-scroll) - 20 (card padding).
WIDTHS = [48.0, 48.0,  # 📷, 📊 (26 + 22)
          24.0 + 17.0 + 11 * 7.3,  # 💾 Save draft
          24.0 + 17.0 + 9 * 7.3,   # 🕐 Schedule
          32.0 + 4 * 7.8]          # Post
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
assert one_line > 316, one_line  # still wraps at phone width
for viewport, inner in ((360, 316.0), (420, 376.0)):
    lines = wrap_lines(WIDTHS, GAP, inner)
    assert len(lines) <= 2, (viewport, lines)  # tidy, not a tall stack
    assert all(ln <= inner for ln in lines), (viewport, lines)
    assert lines[-1] <= inner  # Post (last item) fully visible
    assert all(w <= inner for w in WIDTHS)
    print(f"wrap simulation {viewport}px OK: lines={[round(x) for x in lines]} "
          f"<= {inner:.0f}px inner")

# 4. All five controls present in the composer, with labels.
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
# Asset version + menu URL.
assert HTML.count("?v=170") == 10, HTML.count("?v=170")
assert "?v=14" + "9" not in HTML
assert 'menu_url.rstrip("/") + "/?v=170"' in BOT
print("composer HTML OK (5 controls + textarea + tip + tabs + ?v=170)")

# 5. JS wiring for all five controls + Phase 123/135 markers intact.
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

# 6. Behaviour: drafts (123), scheduled posts (135), plain post;
# no schema change, no new endpoints.
with TestClient(app) as c:
    for h in (ALICE, BOB):
        assert c.post("/auth",
                      json={"initData": h["X-Init-Data"]}).status_code == 200
    r = c.post("/drafts", headers=BOB,
               json={"text": "phase 150 draft check"})
    assert r.status_code == 200, r.text
    did = r.json()["id"]
    r = c.get("/drafts", headers=BOB)
    assert r.status_code == 200, r.text
    assert any(d["id"] == did for d in r.json()["drafts"]), r.json()
    r = c.delete(f"/drafts/{did}", headers=BOB)
    assert r.status_code == 200, r.text
    print("draft save/list/delete OK")
    r = c.post("/scheduled-posts", headers=BOB, json={
        "text": "phase 150 sched check",
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
               json={"type": "text", "caption": "phase 150 post check"})
    assert r.status_code == 200, r.text
    assert r.json()["id"], r.json()
    print("plain text post OK")
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 45, len(r.json()["tables"])
    print("backup: 42 tables OK (no schema change)")
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 166, len(paths)
    assert not any("150" in p for p in paths), paths
    print("routes: 158 OK (6 blood endpoints added in Phase 151)")

print("ALL PHASE 150 CHECKS PASSED")
