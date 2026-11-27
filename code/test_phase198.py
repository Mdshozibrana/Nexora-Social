"""Phase-198 tests: clear recognizable game icons (owner, Nov 27, 15:37).

Every game's icon must say what the game is at a glance, without its
label. The 13 registerGame defs moved from a single emoji to a small
inline-SVG mini-scene tile (viewBox 0 0 64 64): snake, tetromino
stack, bricks + ball + paddle, two cards, paddles + ball, pixel
alien, mine grid + bomb, bird + pipes, numbered tiles, pac with
mouth, target + arrow, jeep on a road, bike + carrot. The games list
(.g-icon) and the game head (#game-title) both render the same SVG;
titles are plain names now. No game names, mechanics, scoring or
list order change. No backend/schema change.

Checks: per-game icon SVG + scene markers + XML well-formedness,
no old emoji icon anywhere in games.js, titles plain, list renders
all 13 cards with the SVG icon, openGame renders icon + title in
the head, version ?v=202 everywhere, CSS sizing rules present.
"""
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.abspath(__file__))

OLD_EMOJI = ["🐍", "🧱", "🏓", "🃏", "🎾", "👾", "💣", "🐦",
             "🔢", "🟡", "🏹", "🌲", "🏁"]

# id -> (expected plain title, scene markers that must be in the SVG)
EXPECTED = {
    "snake": ("Snake", ["2FA84F", "E5484D", "<path"]),
    "tetris": ("Tetris", ["7C5CFF", "FFC53D", "22B8CF"]),
    "breakout": ("Breakout", ["E5484D", "FFC53D", "<circle", 'rx="3"']),
    "memory": ("Memory Match", ["3E8FD0", "FFC53D", "<path"]),
    "pong": ("Pong", ["9DB8C6", "E5484D", "dasharray"]),
    "invaders": ("Space Invaders", ["2FA84F", "<rect"]),
    "mines": ("Minesweeper", ["B9C2CC", "1F2937"]),
    "flappy": ("Flappy Bird", ["2FA84F", "FFC53D", "<circle"]),
    "g2048": ("2048", ["776E65", "F59563", ">2<", ">4<", ">8<", ">16<"]),
    "pacman": ("Pac-Man", ["232946", "FFD93D", "<path"]),
    "archery": ("Archery — Aim Less, Shoot More", ["E5484D", "8B5E34"]),
    "forest-drive": ("Forest Drive", ["E5484D", "6B7280", "BFE3F2"]),
    "runner-rush": ("Runner Rush", ["F97316", "1F2937"]),
}


def _extract_defs():
    js = open(os.path.join(ROOT, "webapp/games.js"), encoding="utf-8").read()
    pat = re.compile(
        r'id: "([\w-]+)", icon: \'(<svg.*?</svg>)\', name: "([^"]+)",'
        r'\s*title: "([^"]+)",', re.DOTALL)
    defs = pat.findall(js)
    assert len(defs) == 13, "13 game defs, got %d" % len(defs)
    return js, defs


def test_icons_static():
    js, defs = _extract_defs()
    assert [d[0] for d in defs] == list(EXPECTED), "game ids/order changed"
    for gid, icon, name, title in defs:
        exp_title, markers = EXPECTED[gid]
        assert title == exp_title, "%s title %r, want %r" % (gid, title, exp_title)
        assert icon.startswith("<svg") and 'viewBox="0 0 64 64"' in icon, \
            "%s icon is not a 64x64 svg tile" % gid
        assert "<image" not in icon and "http" not in icon, \
            "%s icon must be self-contained (no external art)" % gid
        ET.fromstring(icon)  # well-formed XML
        for m in markers:
            assert m in icon, "%s icon missing scene marker %r" % (gid, m)
    # No old emoji on any icon/title surface. (Emoji still legitimately
    # appears INSIDE gameplay — invader sprites, mine cells, score
    # prefixes — those are game content, not the game's icon.)
    for line in js.splitlines():
        if "icon:" in line or "title:" in line:
            for e in OLD_EMOJI:
                assert e not in line, "old emoji icon %r on %r" % (e, line[:60])
    assert "ic.innerHTML = g.icon;" in js, "list must render the SVG icon"
    assert '_gi.innerHTML = def.icon;' in js, "head must render the SVG icon"
    assert '$("game-title").textContent = def.title;' not in js, \
        "head must not render emoji text title"
    print("icons static OK (13 SVG tiles, no old emoji)")


def test_version():
    html = open(os.path.join(ROOT, "webapp/index.html"),
                encoding="utf-8").read()
    assert html.count("?v=202") == 10, html.count("?v=202")
    assert "app.js?v=202" in html and "games.js?v=202" in html
    assert "?v=19" + "7" not in html, "stale ?v=202 in shell"
    bot = open(os.path.join(ROOT, "app/bot.py"), encoding="utf-8").read()
    assert '/?v=202' in bot, "menu button URL not ?v=202"
    assert "?v=19" + "7" not in bot, "stale ?v=202 in bot.py"
    print("version ?v=202 OK")


def test_css():
    css = open(os.path.join(ROOT, "webapp/style.css"), encoding="utf-8").read()
    assert ".game-card .g-icon svg { width: 44px; height: 44px;" in css
    assert ".game-head #game-title .gt-icon svg { width: 22px; height: 22px;" in css
    print("icon CSS OK")


HARNESS_PRELUDE = r'''
function assert(c, m) { if (!c) throw new Error("ASSERT: " + m); }
function makeEl(tag) {
  const el = {
    tagName: (tag || "div").toUpperCase(),
    children: [], className: "", textContent: "", _innerHTML: "",
    style: {}, dataset: {}, hidden: false, onclick: null,
    append(...kids) { kids.forEach(k => { if (k) el.children.push(k); }); },
    appendChild(k) { el.children.push(k); return k; },
    addEventListener() {}, removeEventListener() {},
    setAttribute() {}, getAttribute() { return null; },
    querySelector() { return null; },
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return el._innerHTML; },
    set(v) { el._innerHTML = String(v); if (v === "") el.children = []; },
  });
  return el;
}
const byId = {};
function $(id) { if (!byId[id]) byId[id] = makeEl("div"); return byId[id]; }
const document = {
  createElement: (t) => makeEl(t),
  getElementById: (id) => $(id),
  querySelector: () => null,
  body: makeEl("body"),
};
const sessionStorage = { _s: {}, getItem(k) { return this._s[k] || null; }, setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; } };
const localStorage = { _s: {}, getItem(k) { return this._s[k] || null; }, setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; } };
function showView() {}
'''

HARNESS_MAIN = r'''
assert(GameRegistry.length === 13, "13 games registered, got " + GameRegistry.length);
const grid = $("game-grid");
assert(grid.children.length === 13, "13 cards rendered, got " + grid.children.length);
const EXPECT = {
  "snake": ["2FA84F", "E5484D"], "tetris": ["7C5CFF", "FFC53D"],
  "breakout": ["E5484D", "FFC53D"], "memory": ["3E8FD0", "FFC53D"],
  "pong": ["9DB8C6", "E5484D"], "invaders": ["2FA84F"],
  "mines": ["B9C2CC", "1F2937"], "flappy": ["2FA84F", "FFC53D"],
  "g2048": ["776E65", "F59563"], "pacman": ["232946", "FFD93D"],
  "archery": ["E5484D", "8B5E34"], "forest-drive": ["E5484D", "6B7280"],
  "runner-rush": ["F97316", "1F2937"],
};
GameRegistry.forEach((g, i) => {
  const card = grid.children[i];
  assert(card.className === "game-card", "card class for " + g.id);
  const ic = card.children[0];
  assert(ic.className === "g-icon", "g-icon for " + g.id);
  assert(ic.innerHTML === g.icon, "card icon matches def for " + g.id);
  assert(g.icon.indexOf("<svg") === 0, "icon is svg for " + g.id);
  EXPECT[g.id].forEach((m) => assert(g.icon.indexOf(m) !== -1, g.id + " icon missing " + m));
  assert(card.children[1].textContent === g.name, "card name for " + g.id);
  assert(g.title.indexOf("🐍") === -1 && g.title.indexOf("🌲") === -1
    && g.title.indexOf("🏁") === -1 && g.title.indexOf("🏓") === -1
    && g.title.indexOf("🎾") === -1 && g.title.indexOf("🟡") === -1,
    "title must be plain text for " + g.id);
});
// openGame renders the same SVG + plain name in the head.
["snake", "forest-drive", "runner-rush", "pacman"].forEach((id) => {
  const def = GameRegistry.find((g) => g.id === id);
  def.start = () => null;
  openGame(id);
  const gt = $("game-title");
  assert(gt.children.length === 2, "head has icon + text for " + id);
  assert(gt.children[0].className === "gt-icon", "head icon span for " + id);
  assert(gt.children[0].innerHTML === def.icon, "head icon matches def for " + id);
  assert(gt.children[1].textContent === " " + def.title, "head title for " + id);
});
console.log("HARNESS OK");
'''


def test_node_harness():
    js = open(os.path.join(ROOT, "webapp/games.js"), encoding="utf-8").read()
    path = "/tmp/t198_games_harness.js"
    open(path, "w", encoding="utf-8").write(
        HARNESS_PRELUDE + js + HARNESS_MAIN)
    r = subprocess.run(["node", "--check", path],
                       capture_output=True, text=True)
    assert r.returncode == 0, "node --check failed:\n" + r.stderr
    r = subprocess.run(["node", path], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, "harness failed:\n" + r.stdout + r.stderr
    assert "HARNESS OK" in r.stdout, r.stdout
    print("games node harness OK (13 cards render SVG icons, head icon+title)")


def main():
    test_icons_static()
    test_version()
    test_css()
    test_node_harness()
    print("phase198 OK: 13 clear SVG icons, grid + head render, ?v=202")


if __name__ == "__main__":
    main()
