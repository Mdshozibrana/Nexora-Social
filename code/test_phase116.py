"""Phase-116 tests: infinite scroll + refresh reshuffles the Design
gallery (owner, Nov 13).

- No more Load More button: the gallery loads its next page itself
  as you scroll, until every design is shown.
- Every fresh load mints a new shuffle seed, so a refresh shows the
  designs in new positions; pages of one load never repeat or skip
  a design (the seed keeps the shuffled order stable across pages).
- The similar_to ranking is exempt from shuffling; without the
  shuffle param the legacy newest-first order is untouched.
"""
import hashlib
import hmac
import json
import os
import random
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase116.db"

import app.bot as bot_mod  # noqa: E402

async def _no_poll(app):
    return None

bot_mod.start_bot = _no_poll

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app import models  # noqa: E402


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


PROMPTS = [
    "cozy autumn cabin wooden house",
    "wooden house in the forest cabin",
    "neon cyberpunk city robot",
    "golden sunset beach palm",
    "vintage car chrome highway",
    "snow mountain pine lake",
]


def shuffled(ids, seed):
    ids = list(ids)
    random.Random(seed).shuffle(ids)
    return ids


with TestClient(app) as c:
    r = c.post("/auth", json={"initData": H(666, "Fay")["X-Init-Data"]})
    assert r.status_code == 200
    hdr = H(666, "Fay")

    db = SessionLocal()
    db.add_all(models.Design(image_file_id=f"IMG_{i}", prompt=p)
               for i, p in enumerate(PROMPTS))
    db.commit()
    ids = [d.id for d in db.query(models.Design).order_by(
        models.Design.id).all()]
    db.close()
    newest_first = list(reversed(ids))

    # No shuffle param: the exact legacy order, newest first.
    r = c.get("/designs?limit=20", headers=hdr)
    assert [d["id"] for d in r.json()["designs"]] == newest_first
    print("legacy newest-first order untouched OK")

    # A shuffle seed shuffles deterministically; a different seed
    # gives a different order; the same seed repeats its order.
    exp_a = shuffled(newest_first, "111")
    exp_b = shuffled(newest_first, "222")
    assert exp_a != exp_b, "test seeds collide — pick others"
    r = c.get("/designs?shuffle=111&limit=20", headers=hdr)
    assert [d["id"] for d in r.json()["designs"]] == exp_a, r.text
    r = c.get("/designs?shuffle=222&limit=20", headers=hdr)
    assert [d["id"] for d in r.json()["designs"]] == exp_b
    r = c.get("/designs?shuffle=111&limit=20", headers=hdr)
    assert [d["id"] for d in r.json()["designs"]] == exp_a
    print("seeded shuffle: deterministic per seed, differs per seed OK")

    # Paging a shuffled load: no repeats, no skips, ends cleanly.
    seen, cursor = [], 0
    for _ in range(3):
        r = c.get(f"/designs?shuffle=111&limit=2&cursor={cursor}",
                  headers=hdr)
        seen += [d["id"] for d in r.json()["designs"]]
        cursor = r.json()["next_cursor"]
        if cursor is None:
            break
    assert seen == exp_a, seen
    assert cursor is None, "must end after the last design"
    print("shuffled paging: no repeats/skips, ends cleanly OK")

    # similar_to + shuffle: the similarity ranking wins — the
    # closest design still comes first, seed excluded.
    seed = ids[0]
    r = c.get(f"/designs?similar_to={seed}&shuffle=111&limit=20",
              headers=hdr)
    got = [d["id"] for d in r.json()["designs"]]
    assert seed not in got
    assert got[0] == ids[1], f"closest first, got {got}"
    print("similar_to exempt from shuffle OK")

    # Client: seed, infinite scroll, no Load More.
    html = c.get("/webapp/").text
    js = c.get("/webapp/app.js").text
    for bit in ("let designShuffleSeed = 0",
                "let designLoading = false",
                "designShuffleSeed = Math.floor(Math.random() * 1e9)",
                '"&shuffle=" + designShuffleSeed',
                "function maybeLoadMoreDesigns()",
                "scrollHeight - 600",
                "$(\"design-more\").hidden = true",
                "loadDesigns(false)"):
        assert bit in js, bit
    assert 'id="design-more"' in html, "button element must stay in DOM"
    for asset in ("style.css?v=117", "app.js?v=117", "games.js?v=117"):
        assert asset in html, asset
    assert "loadRelatedDesigns" in js, "Phase 115 wiring gone"
    assert "loadMyQr" in js, "Phase 114 wiring gone"
    assert "showTaskAd" in js, "Phase 113 wiring gone"
    assert "openPhotoViewer" in js, "Phase 112 wiring gone"
    print("client: seed, infinite scroll, Load More gone, ?v=117 OK")

print("PHASE 116 OK")
