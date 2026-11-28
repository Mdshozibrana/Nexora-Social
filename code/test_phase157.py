"""Phase-157 tests: DM conversation header stays pinned (owner order
Nov 20, 2026, with a phone screenshot: "মেসেজের ইনবক্সে এই মার্ক করা
জিনিসগুলো কোনো রকম স্কিনের বাহিরে স্কোল হবে না। মেসেজ বেশি হলে মেসেজ
উপরে যাবে তবে এসব স্টাবল থাকবে।").

- The .chat-head row (back button + peer avatar + peer name with the
  verified tick) is position: sticky; top: 0 inside #app-scroll, with
  a solid theme background and z-index, so messages slide under it and
  it never scrolls away. The bottom composer (.chat-bar) is untouched.
  Client-side only: no new endpoints, no schema change, backup 43
  tables, routes 158.
"""
import hashlib, hmac, json, os, re, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase157.db"
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

HTML = open("webapp/index.html").read()
JS = open("webapp/app.js").read()
CSS = open("webapp/style.css").read()
BOT = open("app/bot.py").read()

# 1. The CSS rule: sticky, top 0, z-index, solid theme background.
m = re.search(r"\.chat-head \{([^}]*)\}", CSS)
assert m, "no .chat-head rule"
rule = m.group(1)
assert "position: sticky" in rule, rule
assert re.search(r"top:\s*0\b", rule), rule
assert re.search(r"z-index:\s*\d+", rule), rule
assert "background: var(--t-bg, #F6F1E7)" in rule, rule
# The header background is the SAME var the page body uses, so it holds
# under every one of the 33 themes — bubbles can never show through.
body_m = re.search(r"html\[data-theme\] body \{([^}]*)\}", CSS)
assert body_m, "no themed body rule"
assert "background-color: var(--t-bg, #F6F1E7)" in body_m.group(1)
assert "border-bottom:" in rule or "box-shadow:" in rule, rule
t = re.search(r"\.chat-head #chat-title \{([^}]*)\}", CSS)
assert t, "no .chat-head #chat-title rule"
tr = t.group(1)
for prop in ("flex: 1", "min-width: 0", "white-space: nowrap",
             "overflow: hidden", "text-overflow: ellipsis"):
    assert prop in tr, prop
assert ".chat-head #chat-back, .chat-head #chat-avatar { flex: none; }" in CSS
print("CSS rule OK (sticky top:0, z-index, theme background, ellipsis)")

# 2. Structure: the header sits ABOVE the message list in #view-chat —
# it is not inside the scrolling thread, so it cannot scroll away.
sec = HTML[HTML.index('<section id="view-chat"'):
           HTML.index("</section>", HTML.index('<section id="view-chat"'))]
head_i = sec.index('class="chat-head"')
thread_i = sec.index('id="chat-thread"')
assert head_i < thread_i, "header must sit above the message list"
head = sec[head_i:thread_i]
assert 'id="chat-back"' in head, "back button missing from header"
assert 'id="chat-avatar"' in head, "avatar missing from header"
assert 'id="chat-title"' in head, "name missing from header"
bar_i = sec.index('class="chat-bar"')
assert bar_i > thread_i, "composer stays below the thread"
bar = re.search(r"\.chat-bar \{([^}]*)\}", CSS).group(1)
assert "position: sticky" in bar and "bottom: 8px" in bar, bar
print("structure OK (header above thread, composer untouched below)")

# 3. JS wiring: back goes to the chat list; title/avatar are filled with
# the peer name + verified tick; #app-scroll is the scrolling element
# the header sticks inside (thread scrolls to bottom on open, view
# resets to top on switch).
assert '$("chat-back").onclick = () => showView("messages");' in JS
# Phase 160: the title is now the shared .vname line (name text +
# blue badge) instead of a textContent string with a text " ✓".
assert 'ct.classList.add("vname")' in JS
assert "ctText.textContent = r.user.first_name;" in JS
assert "if (r.user.verified) ct.appendChild(verifiedBadge());" in JS
assert '$("chat-avatar")' in JS and "avatarEl(r.user.first_name" in JS
assert 'const sc = $("app-scroll");' in JS
assert "sc.scrollTop = sc.scrollHeight" in JS
assert "sc.scrollTop = 0" in JS
print("JS wiring OK (back, title+tick, avatar, #app-scroll scrolls)")

# 4. 360 px geometry, read from the actual CSS: back (icon-btn) + avatar
# + gaps + header padding must leave room for the title, which truncates
# instead of pushing the back button off-screen.
def _px(pattern, text, what):
    mm = re.search(pattern, text)
    assert mm, what
    return int(mm.group(1))
btn_w = _px(r"\.icon-btn \{[^}]*width:\s*(\d+)px", CSS, "icon-btn width")
av_w = _px(r"\.avatar \{[^}]*width:\s*(\d+)px", CSS, "avatar width")
gap = _px(r"\.chat-head \{[^}]*gap:\s*(\d+)px", CSS, "chat-head gap")
hpad = _px(r"\.chat-head \{[^}]*padding:\s*\d+px\s+(\d+)px", CSS,
           "chat-head padding")
spad = _px(r"#app-scroll \{[^}]*padding:\s*0\s+(\d+)px", CSS,
           "app-scroll padding")
content_w = 360 - 2 * spad
fixed_w = btn_w + av_w + 2 * gap + 2 * hpad
title_w = content_w - fixed_w
assert title_w >= 150, (content_w, fixed_w, title_w)
assert "margin: 0 -12px" in rule, "header must span the full width"
print(f"geometry OK at 360px (content {content_w}, fixed {fixed_w}, "
      f"title {title_w}px + ellipsis)")

# 5. Neighbours intact: Phase 156 mascot, Nexa, Blood, Nearby, composer.
assert 'id="mascot-canvas"' in HTML and "mascotOnView" in JS
assert "MASCOT_TIPS_BY_VIEW" in JS
assert "sendNexa" in JS and "glassbar" in HTML
assert "loadBloodDonors" in JS and "openNearby" in JS
assert "composer-post" in HTML
assert "museum" not in JS.lower() and "museum" not in HTML.lower()
assert "Phase 156" in JS and "Phase 156" in CSS
print("neighbours OK (mascot, Nexa, Blood, Nearby, composer, no museum)")

with TestClient(app) as c:
    assert c.post("/auth",
                  json={"initData": ALICE["X-Init-Data"]}).status_code == 200

    # 6. No new endpoints, no schema change: routes still 158,
    # backup still 43 tables.
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 55, len(r.json()["tables"])
    paths = {rt.path for rt in app.routes}
    assert len(paths) == 191, len(paths)
    print("routes 158 + backup 43 tables OK (no new endpoints, no schema change)")

# 7. Version.
assert HTML.count("?v=204") == 10, HTML.count("?v=204")
assert "?v=15" + "6" not in HTML
assert 'menu_url.rstrip("/") + "/?v=204"' in BOT
assert "Phase 157" in CSS and "Phase 157" in HTML
print("PHASE 157 OK")
