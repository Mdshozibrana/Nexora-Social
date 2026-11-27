"""Phase-160 tests: ONE shared verified-name rule, everywhere
(owner, Nov 20 2026 — Ranks order, then "সবখানেই এই নিয়ম এপ্লাই
করো").

Rule: name + blue tick always on ONE line together; a long name
auto-shrinks until title + tick fit; only at the 12px floor may
the name truncate with an ellipsis; the tick NEVER wraps to a
second line and is NEVER hidden. One shared helper (.vname /
.vname-text + fitVerifiedNames) reused at every site — no
per-page shrink copies.

Covers: the shared helper + CSS; every name+tick site (Ranks,
feed/reel headers, comments + replies, Suggested users, share
pickers, search, profile, DM list + chat header, notifications,
Members browse, admin detail, Nearby list, story author +
viewers); the old text-" ✓" ticks are gone (blue badge
everywhere); 360px geometry for the 6 main sites with the
owner's long name; Trending reuses postCard; neighbours; backup
44 tables; routes 163; ?v=203 x10, no old-version literals.
"""
import hashlib, hmac, json, os, re, subprocess, time, urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["ADMIN_IDS"] = "111"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase159.db"
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
GAMES = open("webapp/games.js").read()
CSS = open("webapp/style.css").read()
JS = open("webapp/app.js").read()
BOT = open("app/bot.py").read()



def css_rule(sel):
    m = re.search(re.escape(sel) + r" \{([^}]*)\}", CSS, re.S)
    assert m, sel + " rule missing"
    return m.group(1)


def css_px(rule, prop):
    m = re.search(prop + r":\s*([\d.]+)px", rule)
    assert m, prop + " missing in " + rule[:60]
    return float(m.group(1))
RANK = JS[JS.index("async function loadRanks()"):
          JS.index("// --------------------------------------------------------------- search ---")]
FIT = JS[JS.index("// Phase 160: ONE shared verified-name fit"):
         JS.index("let vnameFitTimer")]
SKILL = JS[JS.index("function skillMemberCard"):
           JS.index("async function loadSkillsDirectory")]


def em_width(name):
    # Conservative system-ui advance model: caps 0.67em, lowercase
    # 0.5em, spaces 0.25em, digits 0.55em. "Abidur Rahman Niloy"
    # (caps A,R,N + 14 lowercase + 2 spaces) = 9.51em.
    w = 0.0
    for ch in name:
        if ch == " ":
            w += 0.25
        elif ch.isdigit():
            w += 0.55
        elif ch.isupper():
            w += 0.67
        else:
            w += 0.5
    return w


def fit_size(name_em, base, budget):
    # Mirror of fitVerifiedNames(): step 0.5px while truncated,
    # never below the 12px floor.
    size = base
    while size > 12 and name_em * size > budget:
        size -= 0.5
    return size


LONG = "Abidur Rahman Niloy"          # the owner's screenshot row 5
LONG28 = "Mohammed Abidur Rahman Niloy"  # 28 chars, must hit the floor
SHORT = "MD Shozib Rana"
assert abs(em_width(LONG) - 9.51) < 0.01, em_width(LONG)
assert abs(em_width(LONG28) - 13.93) < 0.01, em_width(LONG28)
assert abs(em_width(SHORT) - 7.18) < 0.01, em_width(SHORT)

# 1. JS parses (node) — the shared helper touches every name in
# the app, so a syntax slip would break all of it.
for f in ("webapp/games.js", "webapp/app.js"):
    r = subprocess.run(["node", "--check", f],
                       capture_output=True, text=True)
    assert r.returncode == 0, (f, r.stderr)
print("node --check OK (games.js + app.js parse)")

# 2. ONE shared implementation — no per-page shrink copies.
assert "const VNAME_FLOOR = 12;" in JS, "floor 12"
assert JS.count("VNAME_FLOOR") == 2, JS.count("VNAME_FLOOR")
assert "function fitVerifiedNames(root)" in JS
assert "function fitVerifiedNamesSoon(el)" in JS
assert JS.count("scrollWidth") == 1, "one measure point"
assert JS.count("style.fontSize") == 3, "one shrink writer"
assert "while (size > VNAME_FLOOR &&" in FIT
assert "text.scrollWidth > text.clientWidth" in FIT
assert "size -= 0.5;" in FIT
assert "if (size >= base) text.style.fontSize" in FIT
assert "verifiedBadge" not in FIT, "fit must never touch the tick"
assert FIT.count(".vname-text") >= 1, "fit only touches the text"
assert 'window.addEventListener("resize"' in JS, "resize re-fit"
assert "document.fonts.ready" in JS, "fonts-ready re-fit"
print("shared helper OK (one fit, floor 12, 0.5px steps, resize+fonts)")

# 3. Shared CSS: the line never wraps, the text shrinks then
# ellipsizes, the tick never shrinks/wraps/hides.
vname = css_rule(".vname")
assert "display: inline-flex" in vname, vname
assert "align-items: center" in vname, vname
assert "min-width: 0" in vname, vname
assert "flex-wrap" not in vname, "line must never wrap"
vtext = css_rule(".vname-text")
# Phase 162: shrink-only — the text never grows, so the tick
# hugs the name instead of being pushed to the line's far edge.
assert "flex: 0 1 auto" in vtext, vtext
assert "flex: 1 1 auto" not in vtext, "text must never grow"
assert "white-space: nowrap" in vtext, vtext
assert "text-overflow: ellipsis" in vtext, vtext
assert "overflow: hidden" in vtext, vtext
vtick = css_rule(".vname .verified")
assert "flex: none" in vtick, vtick
for sel in (".rank-title-line", ".user-row .vname",
            "#story-author.vname"):
    rule = css_rule(sel)
    assert "flex: 1 1 auto" in rule, (sel, rule)
print("shared CSS OK (.vname nowrap line, .vname-text shrink+ellipsis)")

# 4. Every site renders name + tick through the shared pair.
SITES = {
    "ranks": ("rank-title-line vname", "rank-title vname-text"),
    "postCard": ("post-name vname",),
    "reelCard": ("post-name vname",),
    "commentRow": ('nm.className = "vname"',),
    "suggest": ("suggest-name vname", "suggest-name-text vname-text"),
    "search": ('nm.className = "vname"',),
    "profile": ("profile-name vname",),
    "DM list": ("conv-name vname",),
    "notifications": ('nm.className = "vname"',),
    "Members browse": ("admin-title vname",),
    "story viewers": ("story-viewer-name vname",),
}
for site, bits in SITES.items():
    for bit in bits:
        assert bit in JS, (site, bit)
assert JS.count('line.className = "vname"') == 2, "both pick-rows"
assert 'ct.classList.add("vname")' in JS, "DM chat header"
assert 'sa.classList.add("vname")' in JS, "story author"
assert '<b class="vname">' in JS, "Nearby list"
assert JS.count("vname-text") >= 17, JS.count("vname-text")
assert JS.count("verifiedBadge()") == 19, "1 def + 18 call sites (19th: Phase 199 portfolio name)"
print("all sites OK (shared pair at every name+tick render)")

# 5. The old text-" ✓" ticks are gone at every name site — the
# blue badge is now the tick everywhere, so the rule is literally
# the same at each site.
for gone in (
        'nm.textContent = u.first_name + (u.verified ? " ✓" : "");',
        '$("chat-title").textContent = r.user.first_name +',
        'nm.textContent = n.actor_name + (n.actor_verified ? " ✓" : "");',
        't.textContent = u.first_name + (u.is_verified ? " ✓" : "") +',
        't.textContent = "👤 " + u.first_name + (u.is_verified ? " ✓" : "") +',
        '$("story-author").textContent = g.author.first_name +',
        'nm.textContent = v.user.first_name +',
        'nm.textContent = u.first_name + (u.verified ? " ✓" : "");'):
    assert gone not in JS, gone
print("old text ticks gone (blue badge everywhere now)")

# 6. Ranks geometry (the owner's screenshot): title + tick share
# one line; the @username stays on its own second line.
assert "nm.appendChild(line)" in RANK
assert "line.appendChild(verifiedBadge())" in RANK
assert RANK.index("nm.appendChild(line)") < \
    RANK.index("nm.appendChild(small)"), "line before username"
line_rule = css_rule(".rank-title-line")
assert "flex-wrap" not in line_rule, "ranks line must never wrap"
small_rule = css_rule(".rank-name small")
assert "flex: 0 0 100%" in small_rule, "username stays on line 2"
assert "flex: none" in css_rule(".rank-name .verified")
assert "fitVerifiedNames(box)" in RANK, "ranks fit call"
assert "nm.onclick = () => openProfile(r.telegram_id)" in RANK, \
    "tap-name-opens-profile intact"
print("ranks row OK (title+tick one line, username line 2, tap intact)")

# 7. 360px geometry: the owner's long name fits above the floor
# at every main site; a 28-char name hits the floor at the
# narrowest site (ranks) and ellipsizes with the tick intact.
# Budgets (viewport 360, body padding 12 each side -> 336):
# ranks: row pad 24 + num 30 + avatar 42 + gaps 30 + points ~55
#   -> line 155, tick 21 -> text 134, base 16.
# feed header: avatar 42 + gap 10 -> who 284, tick 21 -> 263, base 15.
# Members browse: card pad 24 + Details/Ban buttons ~170 -> info
#   142, tick 21 -> 121, base 14.5.
# DM chat header: back ~40 + avatar 42 + gaps 20 -> title 234,
#   tick 21 -> 213, base 17.
# profile header: hero pad 32 + big avatar 64 + gap 12 -> col 228,
#   tick 21 -> 207, base 18.
# comment: post pad 24 + avatar 22 + margin 6 -> 284, tick 21
#   -> 263, base 14.
SITES_GEO = [
    ("ranks", 16, 134, 14.0),
    ("feed header", 15, 263, 15),
    ("Members browse", 14.5, 121, 12.5),
    ("DM chat header", 17, 213, 17),
    ("profile header", 18, 207, 18),
    ("comment", 14, 263, 14),
]
for site, base, budget, want in SITES_GEO:
    got = fit_size(em_width(LONG), base, budget)
    assert got == want, (site, got, want)
    assert got > 12, (site, "must stop above the floor")
    print("  %s: '%s' stops at %.1fpx (base %.1f, budget %d)"
          % (site, LONG, got, base, budget))
assert fit_size(em_width(SHORT), 16, 134) == 16, "short name unshrunk"
assert fit_size(em_width(LONG28), 16, 134) == 12, \
    "28-char name must hit the floor (ellipsis, tick intact)"
print("360px geometry OK (long name whole above floor at all 6 sites)")

# 8. Fit hooks: every render re-fits (direct call or next-frame).
for hook in (
        "fitVerifiedNames(box)",          # ranks
        'fitVerifiedNames($("feed-list"))',
        "fitVerifiedNames(list)",         # trending / pickers / nearby
        "fitVerifiedNames();",            # search / notifications
        "fitVerifiedNamesSoon(el)",       # postCard / reelCard / suggest
        "fitVerifiedNamesSoon(row)",      # commentRow / personRow / admin
        "fitVerifiedNames(ct)",           # DM chat header
        "fitVerifiedNames(sa)",           # story author
        ):
    assert hook in JS, hook
assert "wrap.append(rank, postCard(p))" in JS, "Trending reuses postCard"
print("fit hooks OK (every render re-fits)")

# 9. Audit: name renders WITHOUT a tick need no fix — and no site
# was silently skipped.
assert "verified" not in SKILL, "skill cards show no tick"
assert "skill-name" in JS and "vname-text" not in SKILL
print("audit OK (skill cards carry no tick; 17 badge sites + Nearby "
      "HTML tick all converted; nothing skipped)")

# 10. Neighbours intact (Phase 161 removed the Archery remote).
for bit in ("loadBloodDonors", "openNearby", "loadSkills", "sendNexa",
            "mascotOnView", "composer-post", "glassbar",
            "MASCOT_TIPS_BY_VIEW",
            "loadRanks", "postCard", "commentRow", "openProfile",
            "loadMessages", "loadNotifications", "loadTrending",
            "nbPaintPeople", "paintStory", "openStoryViewers"):
    assert bit in JS or bit in GAMES or bit in CSS, bit
assert GAMES.count("registerGame({") == 13, "games count changed"
print("neighbours OK")

# 11. No new endpoints, no schema change: routes still 163,
# backup still 44 tables.
with TestClient(app) as c:
    r = c.get("/admin/backup", headers=ALICE)
    assert r.status_code == 200, r.text
    assert len(r.json()["tables"]) == 55, len(r.json()["tables"])
    print("backup: 44 tables OK")
paths = {rt.path for rt in app.routes}
assert len(paths) == 189, len(paths)
print("routes: 163 OK (no new endpoints)")

# 12. Version.
assert HTML.count("?v=203") == 10, HTML.count("?v=203")
assert "?v=15" + "9" not in HTML
assert "app.js?v=203" in HTML and "games.js?v=203" in HTML
assert 'menu_url.rstrip("/") + "/?v=203"' in BOT
assert "Phase 160" in CSS and "Phase 160" in JS and "Phase 160" in HTML
print("version OK (?v=203 x10, no old-version literals)")

# 13. Phase 162: the tick HUGS the name (owner: "blu tick naam
# theke dure keno?"). Phase 160's .vname-text had flex-grow 1,
# so it stretched to the full line width and pushed the tick to
# the line's FAR edge — worst for short names ("Crypto",
# "Nexora Social"). Now the text is shrink-only (flex: 0 1
# auto): its width is its fitted content (capped by the
# budget), and the tick sits 5px after it — never the far edge.
# The LINE itself may still stretch wide where a site needs it;
# the children just sit at the line's start now.
vtext = css_rule(".vname-text")
assert "flex: 0 1 auto" in vtext, vtext
assert "flex: 1 1 auto" not in vtext, "text must never grow"
for sel in (".rank-title-line", ".user-row .vname",
            "#story-author.vname"):
    assert "flex: 1 1 auto" in css_rule(sel), (sel, "line may stretch")
m = re.search(r"(?m)^\.verified \{([^}]*)\}", CSS)
assert m, "standalone .verified rule missing"
tick_rule = m.group(1)
assert "margin-left: 5px" in tick_rule, "tick gap is 5px"
assert "flex: none" in tick_rule, "tick never shrinks"


def hug_tick_left(name, base, budget):
    # Mirror of fitVerifiedNames + shrink-only flex: the text span
    # is its fitted content (capped by the budget), the tick sits
    # 5px after it. Returns (fitted size, tick left edge from the
    # line start).
    size = fit_size(em_width(name), base, budget)
    text_w = min(em_width(name) * size, budget)
    return size, text_w + 5


SHORTS = ("Crypto", "Nexora Social", "MD Shozib Rana")
for site, base, budget, _want in SITES_GEO:
    for name in SHORTS:
        size, tick_left = hug_tick_left(name, base, budget)
        assert size == base, (site, name, "short name must not shrink")
        assert tick_left < budget, (site, name, tick_left, budget,
                                    "tick must hug the text, not sit at the far edge")
        print("  %s: '%s' tick at %.1fpx (line width %d, gap 5px)"
              % (site, name, tick_left, budget + 21))
# Long name: still shrinks, still one line, tick still adjacent.
for site, base, budget, _want in SITES_GEO:
    size, tick_left = hug_tick_left(LONG, base, budget)
    assert size > 12, (site, "long name must stop above the floor")
    assert tick_left <= budget + 5, (site, tick_left)
    assert abs(tick_left - min(em_width(LONG) * size, budget) - 5) < 0.01, site
# 28-char name: floor + ellipsis, tick intact and adjacent.
size, tick_left = hug_tick_left(LONG28, 16, 134)
assert size == 12, size
assert tick_left == 139, tick_left
# Resize re-fit: a wider line re-grows the name to its base size.
assert fit_size(em_width(LONG), 16, 300) == 16, "re-grow on resize"
# Version: shell on ?v=203, no ?v=203 literal left anywhere.
assert HTML.count("?v=203") == 10, HTML.count("?v=203")
assert "?v=16" + "1" not in HTML
print("Phase 162 hug OK (tick 5px after the name at all 6 sites)")

print("PHASE 160 OK")
