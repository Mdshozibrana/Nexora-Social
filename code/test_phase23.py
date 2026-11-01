"""Phase-23 tests: (A) the scroll-proof app shell — the document no
longer scrolls; #app-scroll owns scrolling so the fixed bottom nav
cannot be dragged away by the webview, Telegram's vertical swipes
are disabled, views reset the shell scroll, and /webapp assets are
served no-cache so new features are never hidden by a stale shell.
(B) All six nav tabs fit one screen: compact icon-over-label
buttons with min-width 0 and matching pill geometry. (C) Official
posting is findable: drawer item + composer switch join the Admin
Panel button, all through one startActAs/stopActAs pair. (D) Log
out FULLY returns to the owner's own ID — it now clears the act-as
session keys, so a later login is never a leftover identity.
"""
import hashlib, hmac, json, os, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase23.db"
os.environ["ADMIN_IDS"] = "777"

import app.bot as bot_mod

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient
from app.main import app


def make_init_data(user):
    params = {"auth_date": "1730000000", "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


with TestClient(app) as c:
    html = open("webapp/index.html").read()
    css = open("webapp/style.css").read()
    js = open("webapp/app.js").read()

    # --- (A) app shell ------------------------------------------------------
    assert "#app-scroll { position: fixed; inset: 0; overflow-y: auto;" in css
    assert "body { padding: 0; overflow: hidden; }" in css
    i_open = html.index('id="app-scroll"')
    i_head = html.index("<header")
    i_close = html.index("/#app-scroll")
    i_drawer = html.index('id="drawer-wrap"')
    i_nav = html.index('class="bottom-nav"')
    assert i_open < i_head < i_close < i_drawer < i_nav, \
        (i_open, i_head, i_close, i_drawer, i_nav)
    # #status moved inside the shell (it renders under the hero now)
    assert html.count('id="status"') == 1
    assert i_open < html.index('id="status"') < i_close
    assert "disableVerticalSwipes" in js
    assert "sc.scrollTop = 0" in js
    r = c.get("/webapp/app.js")
    assert r.status_code == 200, r.status_code
    assert "no-cache" in r.headers.get("cache-control", ""), r.headers
    r = c.get("/webapp/")
    assert "no-cache" in r.headers.get("cache-control", ""), r.headers
    print("app shell + no-cache OK")

    # --- (B) six tabs, one screen -------------------------------------------
    assert "flex-direction: column" in css
    assert "min-width: 0" in css
    # Phase 25 supersedes the divisor: the Design tab made it 7.
    assert "width: calc((100% - 10px) / 7)" in css
    assert "white-space: nowrap" in css
    print("nav fit locks OK")

    # --- (C) official posting doors -------------------------------------------
    assert 'id="drawer-official"' in html
    assert 'id="composer-as"' in html
    assert "function startActAs" in js and "function stopActAs" in js
    assert '$("drawer-official").onclick' in js
    assert '$("composer-as-btn").onclick' in js
    assert "function paintComposerAs" in js
    print("official posting doors OK")

    # --- (D) logout fully clears act-as ---------------------------------------
    assert js.count('removeItem("nx_actas")') >= 2, \
        js.count('removeItem("nx_actas")')
    logout_at = js.index('$("drawer-logout").onclick')
    clear_at = js.index('removeItem("nx_actas")', logout_at)
    entry_at = js.index('$("entry-screen").hidden = false', logout_at)
    assert logout_at < clear_at < entry_at
    print("logout clears act-as OK")

    # --- smoke: the API is untouched ------------------------------------------
    init = make_init_data({"id": 777, "first_name": "Owner"})
    r = c.post("/auth", json={"initData": init})
    assert r.status_code == 200, r.text
    r = c.get("/feed", headers={"X-Init-Data": init})
    assert r.status_code == 200, r.text
    print("api smoke OK")

print("PHASE 23 ALL OK")
