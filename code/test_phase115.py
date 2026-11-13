"""Phase-115 tests: Pinterest-style related designs under an opened
design (owner, Nov 13).

- The sheet gains a "More like this" section below the Close
  button; it reuses the server's existing similar_to ranking
  (prompt-word overlap — the same engine as the Similar button),
  rendered as image-only thumbnails; tapping one opens that design
  in the sheet (which reloads its own related set).
- A NEW design scrolls the sheet to the top and loads its set; a
  refresh of the SAME design keeps its scroll place and its set.
"""
import hashlib
import hmac
import json
import os
import time
import urllib.parse

os.environ["BOT_TOKEN"] = "123456789:AAE" + "x" * 32
os.environ["BOT_USERNAME"] = "NexoraSocial_bot"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase115.db"

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


with TestClient(app) as c:
    r = c.post("/auth", json={"initData": H(555, "Eve")["X-Init-Data"]})
    assert r.status_code == 200
    hdr = H(555, "Eve")

    # Three designs, straight into the DB: a seed, one sharing its
    # prompt words, one sharing none.
    db = SessionLocal()
    db.add_all([
        models.Design(image_file_id="IMG_SEED",
                      prompt="cozy autumn cabin wooden house"),
        models.Design(image_file_id="IMG_CLOSE",
                      prompt="wooden house in the forest cabin"),
        models.Design(image_file_id="IMG_FAR",
                      prompt="neon cyberpunk city robot"),
    ])
    db.commit()
    seed = db.query(models.Design).filter_by(
        image_file_id="IMG_SEED").one()
    close = db.query(models.Design).filter_by(
        image_file_id="IMG_CLOSE").one()
    far = db.query(models.Design).filter_by(
        image_file_id="IMG_FAR").one()
    db.close()

    # similar_to ranks by prompt-word overlap, seed excluded.
    r = c.get(f"/designs?similar_to={seed.id}&limit=20", headers=hdr)
    assert r.status_code == 200, r.text
    got = [d["id"] for d in r.json()["designs"]]
    assert seed.id not in got, "seed must not list itself"
    assert got[0] == close.id, f"closest design first, got {got}"
    assert got[1] == far.id, f"unrelated design after, got {got}"
    assert r.json()["next_cursor"] is None
    print("similar_to ranking: closest first, seed excluded OK")

    # Client: the related section, loader, and new-design behaviour.
    html = c.get("/webapp/").text
    assert 'id="ds-related"' in html, "related section gone"
    assert 'id="ds-related-grid"' in html, "related grid gone"
    assert "MORE LIKE THIS" in html, "related label gone"
    js = c.get("/webapp/app.js").text
    for bit in ("async function loadRelatedDesigns(d)",
                "let dsRelatedSeq = 0",
                '/designs?similar_to=" + d.id',
                "openDesignSheet(rel)",
                "$(\"design-sheet\").scrollTop = 0",
                "const isNew = !currentDesign"):
        assert bit in js, bit
    assert "loadRelatedDesigns(d);" in js
    css = c.get("/webapp/style.css").text
    assert "#ds-related" in css and "#ds-related-grid" in css
    for asset in ("style.css?v=117", "app.js?v=117", "games.js?v=117"):
        assert asset in html, asset
    # Earlier phases intact.
    assert "openPhotoViewer" in js, "Phase 112 wiring gone"
    assert "showTaskAd" in js, "Phase 113 wiring gone"
    assert "loadMyQr" in js, "Phase 114 wiring gone"
    print("client: related section, loader, scroll-top, ?v=117 OK")

print("PHASE 115 OK")
