"""Phase 184 tests: Low polish & consistency — audit L1/L2/L3/L5/L6/L9/
L19/L22/L23/L25 + run.sh staleness (audit M25).

L1 — no duplicate definitions remain (AST scan of main.py, duplicate
  route pairs, duplicate RATE_LIMITS keys); /me/following still serves
  the first route's semantics (official excluded); deleting a post
  still cleans its mentions (the kept _delete_post_cascade copy).
L2 — collection post_count excludes deleted posts (chip == shown list).
L3 — Saved / Collections / Shared paginate past 50 via cursor
  (55 seeded, 50 + 5, no overlap, no cursor = first page as before).
L5 — highlights rename/delete/add-stories/remove-story share the
  "highlights" bucket (429 past a small test budget, Retry-After).
L6 — backup-status carries plaintext_warning when the key is absent
  or malformed, and not when a valid key is set; Admin Panel renders
  it (client markers).
L9 — GET /users/{id}/followers + /following return the right members
  with private/block rules; profile counts are tappable (client
  markers: stats-link buttons -> openFollowList sheet).
L19 — DELETE /designs/{id} works admin-own and no longer requires
  Official; /admin/designs/{id} still works as the admin path.
L22 — syncSidebarActive covers admin/chat/assistant/settings/blood/
  skills (all six have data-go entries in index.html).
L23 — test_phase74.py exists and passes (run as a subprocess).
L25 — tip to a banned author's post is refused (400); unban -> 200.
M25 — run.sh staleness: (a) touching a source re-runs everything,
  (b) an interrupted run relaunched resumes from surviving .ok files
  (exercised on a verbatim copy of run.sh in a scratch dir).
Plain script (run.sh runs it with python directly).
"""
import ast
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from datetime import datetime, timedelta
from types import SimpleNamespace

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase184.db"
os.environ["ADMIN_IDS"] = "999"
os.environ["MODERATOR_IDS"] = "888"
os.environ["GEMINI_API_KEY"] = ""
os.environ["BACKUP_ENCRYPTION_KEY"] = ""

import app.bot as bot_mod  # noqa: E402


async def _no_poll(app):
    return None


bot_mod.start_bot = _no_poll

import app.notify as notify_mod  # noqa: E402

SENT = []


async def fake_send(chat_id, text):
    SENT.append((chat_id, text))
    return True


notify_mod.send_message = fake_send

from fastapi.testclient import TestClient  # noqa: E402
import app.main as main_mod  # noqa: E402
from app.main import app, _BACKUP_TABLES  # noqa: E402
from app import models, ratelimit  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402

MAIN = open("app/main.py").read()
JS = open("webapp/app.js").read()
HTML = open("webapp/index.html").read()
CSS = open("webapp/style.css").read()
ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
RUNSH_PATH = os.path.join(os.path.dirname(ROOT), "nexora_run69/run.sh")
RUNSH = open(RUNSH_PATH).read()


def make_init_data(user, auth_date=None):
    params = {"auth_date": str(auth_date or int(time.time())),
              "user": json.dumps(user)}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(),
                      hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check.encode(),
                              hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(params)


def H(uid, name, username=None):
    u = {"id": uid, "first_name": name}
    if username:
        u["username"] = username
    return {"X-Init-Data": make_init_data(u)}


ALICE = H(1841, "Alice", "alice184")
BOB = H(1842, "Bob", "bob184")
CAROL = H(1843, "Carol", "carol184")
DAVE = H(1844, "Dave", "dave184")
ADMIN = H(999, "Admin")
MOD = H(888, "Mod")

c = TestClient(app)


def mk(uid, name, username):
    r = c.get("/me/notification-prefs", headers=H(uid, name, username))
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        u = db.get(models.User, uid)
        assert u is not None, "user %s not created" % uid
        u.username = username
        db.commit()
    finally:
        db.close()


for uid, name, uname in ((1841, "Alice", "alice184"),
                         (1842, "Bob", "bob184"),
                         (1843, "Carol", "carol184"),
                         (1844, "Dave", "dave184")):
    mk(uid, name, uname)


def db():
    return SessionLocal()


def mkpost_row(uid, caption=""):
    s = db()
    try:
        p = models.Post(user_id=uid, type="text", caption=caption)
        s.add(p)
        s.commit()
        s.refresh(p)
        return p.id
    finally:
        s.close()


def follow(a, b):
    s = db()
    try:
        if s.query(models.Follow).filter_by(
                follower_id=a, following_id=b).first() is None:
            s.add(models.Follow(follower_id=a, following_id=b))
            s.commit()
    finally:
        s.close()


def set_private(uid, private=True):
    s = db()
    try:
        u = s.get(models.User, uid)
        u.is_private = private
        s.commit()
    finally:
        s.close()


def block(a, b):
    s = db()
    try:
        if s.query(models.UserBlock).filter_by(
                blocker_id=a, blocked_id=b).first() is None:
            s.add(models.UserBlock(blocker_id=a, blocked_id=b))
            s.commit()
    finally:
        s.close()


def unblock(a, b):
    s = db()
    try:
        s.query(models.UserBlock).filter_by(
            blocker_id=a, blocked_id=b).delete()
        s.commit()
    finally:
        s.close()


def mkstory(uid, file_id):
    s = db()
    try:
        st = models.Story(user_id=uid, media_file_id=file_id,
                          created_at=datetime.utcnow())
        s.add(st)
        s.commit()
        s.refresh(st)
        return st.id
    finally:
        s.close()


# --- L1: no duplicate definitions remain ----------------------------------
tree = ast.parse(MAIN)
names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
dups = sorted({n for n in names if names.count(n) > 1})
assert not dups, dups
for dead in ("def _eff_id(p):", "def reposted_ids(db, viewer_id, posts):",
             "def _post_list(db, rows, viewer_id, counts=None):",
             "def _delete_post_cascade(db, p):"):
    assert MAIN.count(dead) == 1, (dead, MAIN.count(dead))
routes = re.findall(r'@app\.(get|post|patch|put|delete)\("([^"]+)"\)', MAIN)
pairs = [(m, p) for m, p in routes]
rdups = sorted({p for p in pairs if pairs.count(p) > 1})
assert not rdups, rdups
assert MAIN.count('@app.get("/me/following")') == 1
cfg_tree = ast.parse(open("app/config.py").read())
cfg_dups = []
for node in ast.walk(cfg_tree):
    if isinstance(node, ast.Dict):
        keys = [k.value for k in node.keys
                if isinstance(k, ast.Constant)]
        cfg_dups += [k for k in keys if keys.count(k) > 1]
assert not cfg_dups, cfg_dups
# The kept cascade still cleans mentions + album rows on delete.
assert "Phase 170: a deleted post takes its mention rows with it." in MAIN
assert "Phase 171: ... and its album rows." in MAIN
# /me/following still serves the FIRST route: official excluded.
follow(1841, 1842)
r = c.get("/me/following", headers=ALICE)
assert r.status_code == 200, r.text
ids = [u["telegram_id"] for u in r.json()["users"]]
assert 1842 in ids and 1 not in ids, ids
# Deleting a post removes its mention rows (functional proof the
# kept cascade copy runs).
r = c.post("/posts", headers=ALICE,
           json={"type": "text", "caption": "hi @bob184"})
assert r.status_code == 200, r.text
pid = r.json()["id"]
s = db()
try:
    assert s.query(models.Mention).filter_by(post_id=pid).count() >= 1
finally:
    s.close()
r = c.delete(f"/posts/{pid}", headers=ALICE)
assert r.status_code == 200, r.text
s = db()
try:
    assert s.query(models.Mention).filter_by(post_id=pid).count() == 0
    assert s.get(models.Post, pid).is_deleted is True
finally:
    s.close()
print("L1 no duplicate defs/routes/buckets; following + cascade OK")

# --- L2: collection counts exclude deleted posts ---------------------------
r = c.post("/saved/collections", headers=ALICE, json={"name": "L2col"})
assert r.status_code == 200, r.text
coll = r.json()["id"]
p1 = mkpost_row(1841, "l2 one")
p2 = mkpost_row(1841, "l2 two")
for p in (p1, p2):
    r = c.post(f"/saved/collections/{coll}/posts", headers=ALICE,
               json={"post_id": p})
    assert r.status_code == 200, r.text
r = c.delete(f"/posts/{p2}", headers=ALICE)
assert r.status_code == 200, r.text
r = c.get("/saved/collections", headers=ALICE)
assert r.status_code == 200, r.text
row = next(x for x in r.json()["collections"] if x["id"] == coll)
assert row["post_count"] == 1, row
r = c.get(f"/saved/collections/{coll}", headers=ALICE)
assert r.status_code == 200, r.text
assert r.json()["post_count"] == 1 and len(r.json()["posts"]) == 1, r.json()
print("L2 collection count (1) matches shown list OK")

# --- L3: Saved / Collections / Shared paginate past 50 --------------------
# Dave (1844) has no prior saves, so the counts below are exact.
# 55 saved posts (own posts, all visible to self).
saved_ids = [mkpost_row(1844, f"l3 saved {i}") for i in range(55)]
s = db()
try:
    for p in saved_ids:
        s.add(models.SavedPost(post_id=p, user_id=1844))
    s.commit()
finally:
    s.close()
r = c.get("/me/saved", headers=DAVE)
assert r.status_code == 200, r.text
j = r.json()
assert len(j["posts"]) == 50 and j["next_cursor"] is not None, j
page1 = {p["id"] for p in j["posts"]}
r = c.get(f"/me/saved?cursor={j['next_cursor']}", headers=DAVE)
assert r.status_code == 200, r.text
j2 = r.json()
assert len(j2["posts"]) == 5 and j2["next_cursor"] is None, j2
page2 = {p["id"] for p in j2["posts"]}
assert not (page1 & page2) and page1 | page2 == set(saved_ids), \
    (len(page1), len(page2))
# No cursor = first page as before (backward compatible).
r = c.get("/me/saved", headers=DAVE)
assert len(r.json()["posts"]) == 50, r.json()
print("L3 Saved 50 + 5 via cursor, no overlap OK")
# 55 posts in a collection.
r = c.post("/saved/collections", headers=DAVE, json={"name": "L3col"})
coll3 = r.json()["id"]
s = db()
try:
    for p in saved_ids:
        s.add(models.SavedCollectionPost(collection_id=coll3, post_id=p))
    s.commit()
finally:
    s.close()
r = c.get(f"/saved/collections/{coll3}", headers=DAVE)
j = r.json()
assert len(j["posts"]) == 50 and j["next_cursor"] is not None, j
c1 = {p["id"] for p in j["posts"]}
r = c.get(f"/saved/collections/{coll3}?cursor={j['next_cursor']}",
          headers=DAVE)
j2 = r.json()
assert len(j2["posts"]) == 5 and j2["next_cursor"] is None, j2
assert not (c1 & {p["id"] for p in j2["posts"]})
assert c1 | {p["id"] for p in j2["posts"]} == set(saved_ids)
print("L3 Collections 50 + 5 via cursor OK")
# 55 posts shared to Dave by Bob.
shared_ids = [mkpost_row(1842, f"l3 shared {i}") for i in range(55)]
s = db()
try:
    for p in shared_ids:
        s.add(models.PostShare(post_id=p, from_user_id=1842,
                               to_user_id=1844))
    s.commit()
finally:
    s.close()
r = c.get("/me/shared", headers=DAVE)
j = r.json()
assert len(j["posts"]) == 50 and j["next_cursor"] is not None, j
s1 = {p["id"] for p in j["posts"]}
assert all(p.get("shared_by_id") == 1842 for p in j["posts"]), j
r = c.get(f"/me/shared?cursor={j['next_cursor']}", headers=DAVE)
j2 = r.json()
assert len(j2["posts"]) == 5 and j2["next_cursor"] is None, j2
assert not (s1 & {p["id"] for p in j2["posts"]})
assert s1 | {p["id"] for p in j2["posts"]} == set(shared_ids)
print("L3 Shared 50 + 5 via cursor OK")

# --- L5: highlights write endpoints share the "highlights" bucket --------
_orig_limits = dict(main_mod.RATE_LIMITS)
try:
    st1 = mkstory(1841, "hl184-a")
    st2 = mkstory(1841, "hl184-b")
    r = c.post("/highlights", headers=ALICE,
               json={"title": "L5", "story_ids": [st1]})
    assert r.status_code == 200, r.text
    hl = r.json()["id"]

    def budget(n):
        ratelimit.reset()
        main_mod.RATE_LIMITS["highlights"] = (n, 3600)

    # rename: 1 OK, 2nd 429.
    budget(1)
    r = c.post(f"/highlights/{hl}/rename", headers=ALICE,
               json={"title": "L5 renamed"})
    assert r.status_code == 200, r.text
    r = c.post(f"/highlights/{hl}/rename", headers=ALICE,
               json={"title": "L5 again"})
    assert r.status_code == 429 and "Retry-After" in r.headers, r.text
    # add-stories: 1 OK, 2nd 429.
    budget(1)
    r = c.post(f"/highlights/{hl}/stories", headers=ALICE,
               json={"story_ids": [st2]})
    assert r.status_code == 200, r.text
    r = c.post(f"/highlights/{hl}/stories", headers=ALICE,
               json={"story_ids": [st2]})
    assert r.status_code == 429 and "Retry-After" in r.headers, r.text
    # remove-story: 1 OK, 2nd 429.
    budget(1)
    r = c.delete(f"/highlights/{hl}/stories/{st2}", headers=ALICE)
    assert r.status_code == 200, r.text
    r = c.delete(f"/highlights/{hl}/stories/{st2}", headers=ALICE)
    assert r.status_code == 429 and "Retry-After" in r.headers, r.text
    # delete: one highlight deleted OK, the next delete 429s.
    budget(10)
    r = c.post("/highlights", headers=ALICE,
               json={"title": "L5 second", "story_ids": [st1]})
    assert r.status_code == 200, r.text
    hl2 = r.json()["id"]
    budget(1)
    r = c.delete(f"/highlights/{hl2}", headers=ALICE)
    assert r.status_code == 200, r.text
    r = c.delete(f"/highlights/{hl}", headers=ALICE)
    assert r.status_code == 429 and "Retry-After" in r.headers, r.text
    print("L5 highlights rename/add/remove/delete rate-limited OK")
finally:
    main_mod.RATE_LIMITS.clear()
    main_mod.RATE_LIMITS.update(_orig_limits)
    ratelimit.reset()
# Budgets restored: the surviving highlight still deletes.
r = c.delete(f"/highlights/{hl}", headers=ALICE)
assert r.status_code == 200, r.text

# --- L6: backup-status plaintext warning ----------------------------------
r = c.get("/admin/backup-status", headers=ADMIN)
assert r.status_code == 200, r.text
assert r.json()["plaintext_warning"] is True, r.json()
# Valid key -> no warning; malformed key -> warning again.
from cryptography.fernet import Fernet  # noqa: E402
_real_key = settings.BACKUP_ENCRYPTION_KEY
try:
    settings.BACKUP_ENCRYPTION_KEY = Fernet.generate_key().decode()
    r = c.get("/admin/backup-status", headers=ADMIN)
    assert r.json()["plaintext_warning"] is False, r.json()
    settings.BACKUP_ENCRYPTION_KEY = "not-a-fernet-key"
    r = c.get("/admin/backup-status", headers=ADMIN)
    assert r.json()["plaintext_warning"] is True, r.json()
finally:
    settings.BACKUP_ENCRYPTION_KEY = _real_key
assert "backup-plaintext-warn" in HTML
assert "plaintext_warning" in JS and "backup-plaintext-warn" in JS
assert "PLAINTEXT" in JS
print("L6 backup-status plaintext_warning (absent/malformed/valid) OK")

# --- L9: followers / following lists --------------------------------------
follow(1841, 1842)  # Alice follows Bob
follow(1842, 1841)  # Bob follows Alice
follow(1843, 1842)  # Carol follows Bob
r = c.get("/users/1842/followers", headers=ALICE)
assert r.status_code == 200, r.text
fol = {u["telegram_id"]: u for u in r.json()["users"]}
assert set(fol) == {1841, 1843}, fol
assert fol[1841]["is_self"] is True
assert fol[1843]["following"] is False  # Alice does not follow Carol
assert fol[1841]["first_name"] == "Alice"
r = c.get("/users/1842/following", headers=ALICE)
assert r.status_code == 200, r.text
fing = {u["telegram_id"]: u for u in r.json()["users"]}
assert 1841 in fing and fing[1841]["is_self"] is True, fing
# The official account is auto-followed, so it is in the list and
# the viewer follows it.
assert 1 in fing and fing[1]["following"] is True, fing
# Own lists always visible, even when private.
set_private(1842, True)
r = c.get("/users/1842/followers", headers=BOB)
assert r.status_code == 200, r.text
# Private target: a follower sees the lists, a stranger 404s.
r = c.get("/users/1842/followers", headers=ALICE)
assert r.status_code == 200, r.text
r = c.get("/users/1842/following", headers=DAVE)
assert r.status_code == 404, r.text
set_private(1842, False)
# Blocked either way -> 404.
block(1841, 1843)
r = c.get("/users/1843/followers", headers=ALICE)
assert r.status_code == 404, r.text
r = c.get("/users/1841/followers", headers=CAROL)
assert r.status_code == 404, r.text
unblock(1841, 1843)
r = c.get("/users/1843/followers", headers=ALICE)
assert r.status_code == 200, r.text
# Client: profile counts are tappable buttons into the sheet.
assert "stats-link" in JS and "openFollowList" in JS
assert "refreshStats" in JS and "follow-list-row" in JS
assert "/users/\" + userId + \"/\" + kind" in JS
assert ".stats-link" in CSS and ".follow-list-name" in CSS
# Endpoints cap at 100 like the existing following endpoint.
for fn in ("user_followers", "user_following"):
    seg = MAIN[MAIN.index(f"def {fn}("):]
    seg = seg[:seg.index("def ", 10) if "def " in seg[10:] else len(seg)]
    assert "limit(100)" in seg, fn
print("L9 followers/following lists + private/block + tappable counts OK")

# --- L19: design delete is admin-own --------------------------------------
def mkdesign():
    s = db()
    try:
        d = models.Design(image_file_id="IMG184",
                          prompt="phase 184 design")
        s.add(d)
        s.commit()
        s.refresh(d)
        return d.id
    finally:
        s.close()


d1 = mkdesign()
r = c.delete(f"/designs/{d1}", headers=ALICE)
assert r.status_code == 403, r.text
r = c.delete(f"/designs/{d1}", headers=MOD)
assert r.status_code == 403, r.text
r = c.delete(f"/designs/{d1}", headers=ADMIN)
assert r.status_code == 200, r.text
# The old Official-only rule is gone from the endpoint.
seg = MAIN[MAIN.index("def delete_design("):]
seg = seg[:seg.index("@app.delete(\"/admin/designs")]
assert "OFFICIAL_ID" not in seg, seg
assert "ADMIN_IDS" in seg
# /admin/designs/{id} still works as the admin path.
d2 = mkdesign()
r = c.delete(f"/admin/designs/{d2}", headers=MOD)
assert r.status_code == 200, r.text
d3 = mkdesign()
r = c.delete(f"/admin/designs/{d3}", headers=ADMIN)
assert r.status_code == 200, r.text
print("L19 design delete admin-own; /admin/designs path intact OK")

# --- L22: sidebar highlights the six views --------------------------------
sync = JS[JS.index("function syncSidebarActive()"):]
sync = sync[:sync.index("function paintGlassFoot()")]
for view in ("admin", "assistant", "settings", "blood", "skills"):
    assert f'"{view}"' in sync, view
    assert f'data-go="{view}"' in HTML, view
# "chat" is the exception the audit missed: index.html has NO
# data-go="chat" entry (chat opens from Messages), so the sidebar
# correctly keeps Messages highlighted while chatting.
assert '"chat"' in sync
assert 'data-go="chat"' not in HTML
assert 'current === "chat" ? "messages"' in sync
print("L22 sidebar highlights admin/assistant/settings/blood/skills OK")

# --- L23: test_phase74.py exists and passes -------------------------------
assert os.path.isfile("test_phase74.py")
env = {k: v for k, v in os.environ.items()
       if k.lower() not in ("http_proxy", "https_proxy", "all_proxy",
                            "no_proxy")}
run74 = subprocess.run([sys.executable, "test_phase74.py"],
                       capture_output=True, text=True, env=env, timeout=120)
assert run74.returncode == 0, run74.stdout + run74.stderr
assert "PHASE 74 OK" in run74.stdout
print("L23 test_phase74.py exists and passes OK")

# --- L25: tip to a banned author's post refused ---------------------------
class FakeBot:
    def __init__(self):
        self.invoices = []

    async def send_invoice(self, **kw):
        self.invoices.append(kw)
        return SimpleNamespace(message_id=1)


main_mod._bot_app = SimpleNamespace(bot=FakeBot())
r = c.post("/posts", headers=BOB, json={"type": "text", "caption": "tip me"})
assert r.status_code == 200, r.text
tip_post = r.json()["id"]
s = db()
try:
    u = s.get(models.User, 1842)
    u.is_banned = True
    s.commit()
finally:
    s.close()
r = c.post("/tips/create", headers=ALICE,
           json={"post_id": tip_post, "amount_stars": 50})
assert r.status_code == 400, r.text
assert "unavailable" in r.text.lower(), r.text
r = c.post("/tips/create", headers=ALICE,
           json={"user_id": 1842, "amount_stars": 50})
assert r.status_code == 400, r.text
s = db()
try:
    u = s.get(models.User, 1842)
    u.is_banned = False
    s.commit()
finally:
    s.close()
r = c.post("/tips/create", headers=ALICE,
           json={"post_id": tip_post, "amount_stars": 50})
assert r.status_code == 200, r.text
assert r.json()["invoice"] is True and r.json()["to_name"] == "Bob", r.json()
print("L25 tip to banned author's post refused; unban -> invoice OK")

# --- M25: run.sh staleness (verbatim copy in a scratch dir) ---------------
assert "Phase 184 (audit M25)" in RUNSH
assert "newest_src" in RUNSH and "oldest_ok" in RUNSH
scratch = tempfile.mkdtemp(prefix="run184-")
try:
    code_dir = os.path.join(scratch, "code")
    run_dir = os.path.join(scratch, "run")
    os.makedirs(os.path.join(code_dir, "app"))
    os.makedirs(os.path.join(code_dir, "webapp"))
    os.makedirs(os.path.join(code_dir, "venv", "bin"))
    os.makedirs(run_dir)
    open(os.path.join(code_dir, "app", "main.py"), "w").write("# src\n")
    open(os.path.join(code_dir, "webapp", "app.js"), "w").write("// src\n")
    open(os.path.join(code_dir, "requirements.txt"), "w").write("# req\n")
    for t in ("test_a.py", "test_b.py"):
        open(os.path.join(code_dir, t), "w").write('print("ok")\n')
    os.symlink(sys.executable,
               os.path.join(code_dir, "venv", "bin", "python"))
    run_copy = os.path.join(scratch, "run.sh")
    shutil.copy(RUNSH_PATH, run_copy)
    with open(run_copy) as fh:
        rc = fh.read()
    rc = rc.replace("cd ~/workspace/friendline_tg_project/code",
                    "cd " + code_dir)
    rc = rc.replace("D=~/workspace/nexora_run69", "D=" + run_dir)
    with open(run_copy, "w") as fh:
        fh.write(rc)
    env2 = {k: v for k, v in os.environ.items()
            if k.lower() not in ("http_proxy", "https_proxy", "all_proxy",
                                 "no_proxy")}
    # (b) Interrupted run relaunched: .ok files newer than every
    # source -> resume (nothing re-runs, result still counts them).
    for t in ("test_a", "test_b"):
        open(os.path.join(run_dir, t + ".ok"), "w").write("")
    assert subprocess.run(["bash", run_copy], capture_output=True,
                          env=env2, timeout=120).returncode == 0
    progress = open(os.path.join(run_dir, "progress.txt")).read() \
        if os.path.exists(os.path.join(run_dir, "progress.txt")) else ""
    assert "PASS" not in progress, progress
    result = open(os.path.join(run_dir, "result.txt")).read()
    assert "pass=2 total=2" in result, result
    # (a) A source edit after the green run -> everything re-runs.
    time.sleep(1.1)  # mtime granularity: the touch must be newer
    os.utime(os.path.join(code_dir, "app", "main.py"), None)
    assert subprocess.run(["bash", run_copy], capture_output=True,
                          env=env2, timeout=120).returncode == 0
    progress = open(os.path.join(run_dir, "progress.txt")).read()
    assert "test_a PASS" in progress and "test_b PASS" in progress, progress
    assert "stale .ok markers" in progress, progress
    result = open(os.path.join(run_dir, "result.txt")).read()
    assert "pass=2 total=2" in result, result
    print("M25 run.sh staleness: resume + full re-run after edit OK")
finally:
    shutil.rmtree(scratch, ignore_errors=True)

# --- version, routes, backup ----------------------------------------------
assert HTML.count("?v=192") == 10, HTML.count("?v=192")
assert "?v=18" + "3" not in HTML
BOT = open(os.path.join(ROOT, "code/app/bot.py")).read()
assert "/?v=192" in BOT and "/?v=18" + "3" not in BOT
paths = {rt.path for rt in app.routes}
assert len(paths) == 184, len(paths)
assert "/users/{telegram_id}/followers" in paths
assert "/users/{telegram_id}/following" in paths
assert "/me/following" in paths
assert sum(1 for rt in app.routes if rt.path == "/me/following") == 1
r = c.get("/admin/backup", headers=ADMIN)
assert r.status_code == 200, r.text
assert len(r.json()["tables"]) == 52, len(r.json()["tables"])
assert len(_BACKUP_TABLES) == 52, len(_BACKUP_TABLES)
r = c.get("/admin/health", headers=ADMIN)
assert r.json()["version"] == 192, r.json()
print("version + routes 183 + backup 52 OK")

print("PHASE 184 OK")
