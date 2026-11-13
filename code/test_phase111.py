"""Phase-111 tests: /media CACHE-CONTROL (owner, Nov 13).

Owner report: the Design page takes a long time to load. Measured:
a 20-image first page is ~2 MB, and /media responses carried NO
Cache-Control — every Design visit re-downloaded every image from
Telegram through the proxy. The grid already lazy-loads; the
/designs API is not the bottleneck.

Fix: media_proxy now sends `Cache-Control: private, max-age=604800,
immutable` on every /media response. A file_id's bytes never change,
and the signed ?mt= token already bounds access to 7 days (see
_media_token: exp = now + 7 * 86400), so a 7-day private cache is
safe — repeat visits serve images from the browser cache.

Note: the 200 path needs a live bot token, so this suite cannot
assert the header on a live response (the test token is fake and
/media answers 503 without a live token). It asserts the header
wiring in the handler source, that the middleware cannot override
it (its Cache-Control branch only touches /webapp paths), that the
token TTL matches the 7-day max-age, and that the media gate still
answers 401 without a token. The header itself is live-verified
after deploy with a real media token.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase111.db"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "app", "main.py")).read()

# The cache header lives in media_proxy, on every response.
mi = src.index("async def media_proxy")
mj = src.index("if WEBAPP_DIR.exists():", mi)
proxy = src[mi:mj]
assert 'headers["cache-control"] = "private, max-age=604800, immutable"' \
    in proxy, proxy
print("media_proxy cache-control wiring OK")

# The 7-day max-age matches the signed media token's lifetime.
ti = src.index("def _media_token()")
assert "7 * 86400" in src[ti:ti + 700], "token TTL is not 7 days"
print("media token TTL 7 days OK")

# The middleware's Cache-Control branch only touches /webapp paths,
# so it can never strip or replace the /media header: the guard
# precedes the first Cache-Control assignment with no /media mention
# between them, and both middleware assignments sit inside the guard.
gi = src.index('if path.startswith("/webapp"):')
ci = src.index('Cache-Control', gi)
assert "/media" not in src[gi:ci], src[gi:ci]
assert src.count('response.headers["Cache-Control"]') == 2
print("middleware cannot override /media cache OK")

with TestClient(app) as c:
    # The media gate still works: no token -> 401, bogus token -> 401.
    r = c.get("/media/somefileid")
    assert r.status_code == 401, r.status_code
    r = c.get("/media/somefileid?mt=bogus")
    assert r.status_code == 401, r.status_code
    print("media gate 401 OK")

    # Phase 108/109/110 survive.
    html = c.get("/webapp/").text
    assert 'id="ds-download"' in html, "Phase 109 button gone"
    js = c.get("/webapp/app.js").text
    assert "tg.downloadFile" in js, "Phase 110 wiring gone"
    css = c.get("/webapp/style.css").text
    assert "#app-scroll.sheet-open" in css, "Phase 108 lock gone"
    print("Phase 108/109/110 markers OK")

    for asset in ("style.css?v=112", "app.js?v=112", "games.js?v=112"):
        assert asset in html, asset
    print("asset version ?v=112 OK")

print("PHASE 111 OK")
