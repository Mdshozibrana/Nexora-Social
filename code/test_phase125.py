"""Phase-125 tests: Videos page scroll-up fix.

Root cause: the Phase 72 global pull-to-refresh handler on
#app-scroll armed on every downward finger drag whenever
#app-scroll.scrollTop was 0 — but the Videos page scrolls inside
its own fixed overlay (#view-videos), so #app-scroll never moves
there and the handler's preventDefault() swallowed every attempt
to scroll back up (small drags did nothing, big drags reloaded
the list to the top). Scrolling down worked because dy <= 0
returns early.

Fix (client-only): the guards now read the scroller of the view
that is actually open — #view-videos on Videos, #app-scroll
elsewhere (topScroller helper). Pull-to-refresh at the very top
of the Videos list still works; the Design handler (Phase 61) is
untouched; snap CSS and autoplay are unchanged.

Client assertions read the served files from disk, as in
test_phase123/124. No server change, so the server side is a
/health smoke check only.
"""
import os

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase125.db"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
HTML = open(os.path.join(BASE, "webapp", "index.html")).read()
JS = open(os.path.join(BASE, "webapp", "app.js")).read()
CSS = open(os.path.join(BASE, "webapp", "style.css")).read()

with TestClient(app) as c:
    r = c.get("/health")
    assert r.status_code == 200, r.text

# 1. Asset version bumped to ?v=206 (x5), ?v=124 gone from the shell.
assert HTML.count("?v=206") == 10, HTML.count("?v=206")
assert "?v=124" not in HTML
assert "app.js?v=206" in HTML and "style.css?v=206" in HTML

# 2. The fix: topScroller helper picks the open view's scroller.
assert 'const topScroller = () => current() === "videos"' in JS
assert 'document.getElementById("view-videos") : sc;' in JS
assert JS.count("topScroller().scrollTop > 0") == 2, \
    JS.count("topScroller().scrollTop > 0")

# 3. The buggy pattern is gone from the Phase 72 global PTR slice.
start = JS.index("// Phase 72 (owner): pull-to-refresh on EVERY main page")
end = JS.index("\nfunction openDesignSheet(d) {", start)
slice72 = JS[start:end]
assert "sc.scrollTop > 0" not in slice72
assert "topScroller" in slice72
# Pull-to-refresh itself still exists and still refreshes Videos.
assert 'videos: () => loadVideos(true)' in slice72
assert "Pull to refresh" in JS
assert 'id="ptr-global"' in HTML

# 4. The Phase 61 Design handler is untouched (its scroller really
#    is #app-scroll, so its guard was already correct).
start61 = JS.index("// Phase 61 (owner): pull-to-refresh on the Design gallery")
slice61 = JS[start61:start]
assert '$("view-designs").hidden' in slice61
assert slice61.count("sc.scrollTop > 0") == 2, \
    slice61.count("sc.scrollTop > 0")

# 5. Snap + autoplay + reel structure unchanged.
assert "scroll-snap-type: y mandatory" in CSS
assert "scroll-snap-stop: always" in CSS
assert "height: 100dvh" in CSS
assert "#view-videos" in CSS and "overflow-y: auto" in CSS
assert "reelObserver" in JS and "threshold: 0.6" in JS
assert 'id="video-list"' in HTML
assert 'if (name === "videos") { loadVideos(true); maybeShowAd(); }' in JS

# 6. Earlier reels stay in the DOM: loadVideos only clears the list
#    on reset; paging appends. (Nothing above may scroll back to.)
assert JS.count('$("video-list").innerHTML = ""') == 1
assert "if (reset) {" in JS
assert '$("video-list").appendChild(card);' in JS
assert "$(\"video-more\").hidden = !vCursor;" in JS

# 7. Neighbouring phases' markers intact (118-124).
for marker in ("repost-banner", "loadTrending",
               "pollBlock", "loadDrafts", "renderPh", "goFeedTo",
               "routeStartParam", "loadMyQr", "design-more"):
    assert marker in JS, marker
assert "obs-greet" in HTML  # Phase 121 Obsidian greeting lives in the shell

print("phase125: all checks passed")
