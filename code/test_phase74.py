"""Phase 74 tests: Nexa's 10 activities (PRD:604).

Phase 74 added 4 scenes to Nexa's day (garden, painting, guitar,
yoga) on top of Phase 73's 6 (work, cooking, study, gym, cleaning,
run) — 10 activities total, rotating every 6 s while she is idle.
The 4 further planned activities (dancing, kitten, cycling, tea)
were NOT built in this round (the character reference snapshot had
expired) and remain unbuilt — this suite asserts exactly the 10
built ones and the absence of the 4 unbuilt ones. Client-side
feature: no server route involved, so this is a static suite over
webapp/app.js + the webp assets + the PRD text.
"""
import os

ROOT = os.path.expanduser("~/workspace/friendline_tg_project")
JS = open(os.path.join(ROOT, "code/webapp/app.js")).read()
NEXA = os.path.join(ROOT, "code/webapp/nexa")
PRD = open(os.path.join(ROOT, "PRD_Telegram_Social_Platform_BN.md")).read()

# The 10 built activities, in rotation order (app.js NEXA_LIFE).
BUILT = [
    ("life-work", "Nexa is working 💻"),
    ("life-cooking", "Nexa is cooking 🍳"),
    ("life-study", "Nexa is studying 📚"),
    ("life-gym", "Nexa is at the gym 🏋️"),
    ("life-cleaning", "Nexa is cleaning her room 🧹"),
    ("life-run", "Nexa is out running 🏃‍♀️"),
    ("life-garden", "Nexa is watering her plants 🌿"),
    ("life-painting", "Nexa is painting 🎨"),
    ("life-guitar", "Nexa is playing guitar 🎸"),
    ("life-yoga", "Nexa is doing yoga 🧘"),
]

# 1. All 10 activities are in the rotation, in order, with labels.
seg = JS[JS.index("const NEXA_LIFE = ["):JS.index("];", JS.index("const NEXA_LIFE = ["))]
for img, label in BUILT:
    assert f'{{ img: "{img}", label: "{label}" }}' in seg, (img, label)
assert seg.count("{ img:") == 10, seg.count("{ img:")
print("10 activities in NEXA_LIFE, in order, with labels OK")

# 2. Every activity has a real asset on disk (non-empty, WEBP magic).
for img, _label in BUILT:
    p = os.path.join(NEXA, img + ".webp")
    assert os.path.isfile(p), p
    with open(p, "rb") as fh:
        head = fh.read(12)
    assert len(head) == 12 and head[:4] == b"RIFF" and head[8:] == b"WEBP", p
    assert os.path.getsize(p) > 1000, (p, os.path.getsize(p))
print("10 life-*.webp assets present, valid WEBP, non-trivial OK")

# 3. Rotation mechanics (Phase 73, kept by 74): 6 s tick, paused
# while she thinks/talks (nexaBusy), stopped when leaving the view.
assert "setInterval(nexaLifeTick, 6000)" in JS
assert "function nexaLifeTick()" in JS
tick = JS[JS.index("function nexaLifeTick()"):]
tick = tick[:tick.index("function nexaLifeStart()")]
assert "if (nexaBusy) return;" in tick
assert "nexaPose(step.img)" in tick and "nexa-status" in tick
assert "function nexaLifeStop()" in JS
assert "nexaLifeStop()" in JS
assert 'if (name !== "assistant") nexaStop();' in JS
assert "nexaLifeStart()" in JS
print("rotation: 6s tick, nexaBusy pause, stop on leaving OK")

# 4. The 4 planned-but-unbuilt activities are still absent — no
# scene, no asset, no rotation entry (owner decision, PRD Phase 74).
for img in ("life-dance", "life-dancing", "life-kitten", "life-cycle",
            "life-cycling", "life-tea"):
    assert img not in JS, img
    assert not os.path.exists(os.path.join(NEXA, img + ".webp")), img
for word in ("dancing", "kitten", "cycling"):
    assert word not in seg, word
print("4 unbuilt activities (dancing/kitten/cycling/tea) absent OK")

# 5. PRD documents both the 10 built activities and the 4 unbuilt
# ones as not built in this round.
assert "১০টি কাজে" in PRD
assert "বাকি পরিকল্পিত ৪টি" in PRD
print("PRD documents 10 built + 4 unbuilt OK")

print("PHASE 74 OK")
