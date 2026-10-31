"""Standalone preview drawings: Games grid + Snake gameplay.
(Original draw_preview2.py lived in /tmp and was lost in a VM swap;
this script is self-contained and kept with the project.)"""
from PIL import Image, ImageDraw, ImageFont

S = 2
W = 420 * S
NOTO = "/usr/share/fonts/truetype/noto/NotoSans-{}.ttf"
DEJA = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
PAGE = (248, 234, 241)
CARD = (255, 251, 252)
TEXT = (71, 42, 62)
GREY = (150, 97, 126)
GRAD_A, GRAD_B, GRAD_C = (236, 72, 153), (219, 39, 119), (190, 24, 93)


def F(style, size):
    return ImageFont.truetype(NOTO.format(style), int(size * S))


def D(size):
    return ImageFont.truetype(DEJA, int(size * S))


def tw(d, s, f):
    return d.textlength(s, font=f)


def text(d, x, y, s, f, col=TEXT):
    d.text((x * S, y * S), s, font=f, fill=col)


def rr(d, box, r, **kw):
    d.rounded_rectangle([box[0] * S, box[1] * S, box[2] * S, box[3] * S],
                        radius=r * S, **kw)


def gradient(img, box, radius=12):
    x0, y0, x1, y1 = [v * S for v in box]
    w, h = int(x1 - x0), int(y1 - y0)
    grad = Image.new("RGB", (max(w, 1), max(h, 1)))
    gd = ImageDraw.Draw(grad)
    for i in range(w):
        t = i / max(w - 1, 1)
        if t < 0.5:
            u = t * 2
            col = tuple(int(GRAD_A[k] + (GRAD_B[k] - GRAD_A[k]) * u) for k in range(3))
        else:
            u = (t - 0.5) * 2
            col = tuple(int(GRAD_B[k] + (GRAD_C[k] - GRAD_B[k]) * u) for k in range(3))
        gd.line([(i, 0), (i, h)], fill=col)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w, h], radius=radius * S, fill=255)
    img.paste(grad, (int(x0), int(y0)), mask)
    return ImageDraw.Draw(img)


def hero(img):
    d = gradient(img, [-8, -8, 428, 96], radius=24)
    d = ImageDraw.Draw(img)
    text(d, 16, 14, "Nexora Social", F("Bold", 24), (255, 255, 255))
    d.ellipse([372 * S, 12 * S, 404 * S, 44 * S], fill=(255, 251, 252), outline=(255, 255, 255), width=S)
    d.ellipse([382 * S, 21 * S, 394 * S, 33 * S], outline=(71, 42, 62), width=2 * S)
    d.line([392 * S, 31 * S, 398 * S, 37 * S], fill=(71, 42, 62), width=2 * S)
    avatar(d, 40, 68, 22, "MD Shozib Rana", 150)
    text(d, 72, 56, "MD Shozib Rana @shozib", F("SemiBold", 14.5), (255, 255, 255))
    text(d, 72, 76, "1 posts · 1 followers · 1 following", F("Regular", 11.5), (255, 220, 238))
    chip = "★ 25"
    cw = tw(d, chip, D(13)) + 20
    rr(d, [404 - cw, 54, 404, 82], 14, fill=(255, 251, 252))
    text(d, 404 - cw + 10, 60, chip, D(13), (236, 72, 153))
    return 108


def avatar(d, cx, cy, r, name, hue):
    import colorsys
    def hsl(h, s_, l):
        rr_, gg, bb = colorsys.hls_to_rgb((h % 360) / 360, l, s_)
        return (int(rr_ * 255), int(gg * 255), int(bb * 255))
    d.ellipse([(cx - r) * S, (cy - r) * S, cx * S, (cy + r) * S], fill=hsl(hue, .65, .42))
    d.pieslice([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], -90, 90, fill=hsl(hue + 40, .7, .52))
    parts = name.split()
    ini = parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")
    f = F("Bold", r * 0.82)
    text(d, cx - tw(d, ini, f) / 2, cy - r * 0.42, ini, f, (255, 255, 255))


def bottom_nav(img, H, active):
    d = ImageDraw.Draw(img)
    y = H - 64
    rr(d, [10, y + 2, 410, H - 6], 30, fill=(255, 251, 252))
    items = ["house", "videos", "games", "tasks", "ranks", "me"]
    names = ["Feed", "Videos", "Games", "Tasks", "Ranks", "Me"]
    bw = (420 - 20 - 30) / 6
    for i, kind in enumerate(items):
        x = 10 + i * (bw + 6)
        if i == active:
            rr(d, [x, y + 8, x + bw, y + 48], 20, fill=(232, 67, 147),
               outline=(100, 116, 139), width=S)
            tcol = (255, 255, 255)
        else:
            tcol = GREY
        cx = x + bw / 2
        if kind == "house":
            text(d, cx - tw(d, "⌂", D(15)) / 2, y + 11, "⌂", D(15), tcol)
        elif kind == "me":
            text(d, cx - tw(d, "☺", D(15)) / 2, y + 11, "☺", D(15), tcol)
        elif kind == "tasks":
            text(d, cx - tw(d, "★", D(14)) / 2, y + 11, "★", D(14), tcol)
        elif kind == "videos":
            rr(d, [cx - 9, y + 13, cx + 9, y + 27], 4, outline=tcol, width=2 * S)
            d.polygon([(cx - 3) * S, (y + 16.5) * S, (cx - 3) * S, (y + 23.5) * S, (cx + 4) * S, (y + 20) * S], fill=tcol)
        elif kind == "games":
            rr(d, [cx - 11, y + 14, cx + 11, y + 28], 7, outline=tcol, width=2 * S)
            d.line([(cx - 6) * S, (y + 21) * S, (cx - 1) * S, (y + 21) * S], fill=tcol, width=2 * S)
            d.line([(cx - 3.5) * S, (y + 18.5) * S, (cx - 3.5) * S, (y + 23.5) * S], fill=tcol, width=2 * S)
            d.ellipse([(cx + 3) * S, (y + 18) * S, (cx + 6) * S, (y + 21) * S], fill=tcol)
            d.ellipse([(cx + 6) * S, (y + 22) * S, (cx + 9) * S, (y + 25) * S], fill=tcol)
        else:
            d.polygon([(cx - 7) * S, (y + 12) * S, (cx + 7) * S, (y + 12) * S, (cx + 5) * S, (y + 21) * S, (cx - 5) * S, (y + 21) * S], fill=tcol)
            d.rectangle([(cx - 1.5) * S, (y + 21) * S, (cx + 1.5) * S, (y + 25) * S], fill=tcol)
            d.rectangle([(cx - 5) * S, (y + 25) * S, (cx + 5) * S, (y + 27.5) * S], fill=tcol)
        text(d, cx - tw(d, names[i], F("Regular", 10.5)) / 2, y + 33, names[i], F("Regular", 10.5), tcol)


def card(d, x, y, x2, h):
    d.rounded_rectangle([x * S, y * S, x2 * S, (y + h) * S], radius=16 * S,
                        fill=CARD, outline=(228, 228, 238), width=S)


# ------------------------------------------------------------------ GAMES --
H = 700
img = Image.new("RGB", (W, H * S), PAGE)
y = hero(img)
d = ImageDraw.Draw(img)
text(d, 14, y + 8, "Games", F("Bold", 19))
y += 34
for ln in ["Classic button-phone games — the Nokia-era",
           "favourites from the first mobile phones."]:
    text(d, 14, y, ln, F("Regular", 12), GREY)
    y += 20
y += 14


def game_icon(d, kind, x, y):
    if kind == "snake":
        pts = [(x, y + 26), (x + 14, y + 26), (x + 14, y + 10), (x + 30, y + 10), (x + 30, y + 22)]
        for i in range(len(pts) - 1):
            d.line([pts[i][0] * S, pts[i][1] * S, pts[i + 1][0] * S, pts[i + 1][1] * S], fill=(22, 163, 74), width=7 * S)
        d.ellipse([(x + 26) * S, (y + 16) * S, (x + 36) * S, (y + 26) * S], fill=(22, 163, 74))
        d.ellipse([(x + 4) * S, (y + 2) * S, (x + 12) * S, (y + 10) * S], fill=(220, 38, 38))
    elif kind == "tetris":
        cols = [(34, 211, 238), (250, 204, 21), (192, 132, 252), (74, 222, 128)]
        cells = [(0, 0), (1, 0), (2, 0), (1, 1), (0, 2), (0, 3), (1, 3), (2, 3), (2, 2)]
        for i, (cx, cy) in enumerate(cells):
            d.rectangle([(x + cx * 11) * S, (y + cy * 11) * S, (x + cx * 11 + 10) * S, (y + cy * 11 + 10) * S], fill=cols[i % 4])
    elif kind == "breakout":
        for r in range(3):
            for c in range(4):
                d.rectangle([(x + c * 12) * S, (y + r * 8) * S, (x + c * 12 + 10) * S, (y + r * 8 + 6) * S],
                            fill=[(248, 113, 113), (251, 146, 60), (250, 204, 21)][r])
        d.ellipse([(x + 22) * S, (y + 28) * S, (x + 30) * S, (y + 36) * S], fill=TEXT)
        d.rectangle([(x + 14) * S, (y + 40) * S, (x + 38) * S, (y + 44) * S], fill=TEXT)
    else:
        rr(d, [x, y, x + 34, y + 44], 6, fill=(124, 58, 237))
        text(d, x + 17 - tw(d, "✦", D(17)) / 2, y + 12, "✦", D(17), (255, 255, 255))


GAMES = [("snake", "Snake", "The Nokia classic — eat, grow, don't bite yourself."),
         ("tetris", "Tetris", "The brick-game legend. Stack, clear lines, survive."),
         ("breakout", "Breakout", "Brick-breaker: bounce the ball, smash every brick."),
         ("memory", "Memory Match", "The card-flip memory game from the button-phone days.")]
for i, (kind, name, desc) in enumerate(GAMES):
    gx = 12 + (i % 2) * 202
    gy = y + (i // 2) * 168
    card(d, gx, gy, gx + 190, 158)
    game_icon(d, kind, gx + 14, gy + 14)
    text(d, gx + 14, gy + 66, name, F("Bold", 15))
    lines = []
    cur = ""
    for w_ in desc.split():
        if tw(d, cur + " " + w_, F("Regular", 11)) < 160:
            cur = (cur + " " + w_).strip()
        else:
            lines.append(cur); cur = w_
    lines.append(cur)
    for j, ln in enumerate(lines[:2]):
        text(d, gx + 14, gy + 90 + j * 16, ln, F("Regular", 11), GREY)
    d = gradient(img, [gx + 14, gy + 122, gx + 84, gy + 148], radius=13)
    d = ImageDraw.Draw(img)
    text(d, gx + 14 + (70 - tw(d, "▶ Play", F("SemiBold", 12))) / 2, gy + 128, "▶ Play", F("SemiBold", 12), (255, 255, 255))
bottom_nav(img, H, 2)
img.save("/tmp/nexora_games.png")
print("games ok")

# ------------------------------------------------------------------ SNAKE --
H = 780
img = Image.new("RGB", (W, H * S), PAGE)
d = ImageDraw.Draw(img)
rr(d, [12, 14, 92, 46], 10, fill=(246, 217, 231))
text(d, 24, 22, "← Games", F("SemiBold", 13))
text(d, 104, 20, "Snake", F("Bold", 16))
sc = "Score: 40"
text(d, 408 - tw(d, sc, F("Bold", 14)), 21, sc, F("Bold", 14), (236, 72, 153))
# LCD board
bx, by, cell, N = 60, 70, 15, 20
rr(d, [bx - 6, by - 6, bx + N * cell + 6, by + N * cell + 6], 12, fill=(38, 48, 10))
d.rectangle([bx * S, by * S, (bx + N * cell) * S, (by + N * cell) * S], fill=(183, 194, 94))
snake = [(10, 10), (9, 10), (8, 10), (8, 11), (8, 12), (9, 12)]
for sx, sy in snake:
    d.rectangle([(bx + sx * cell + 1) * S, (by + sy * cell + 1) * S, (bx + sx * cell + cell - 1) * S, (by + sy * cell + cell - 1) * S], fill=(38, 48, 10))
d.rectangle([(bx + 14 * cell + 3) * S, (by + 6 * cell + 3) * S, (bx + 14 * cell + cell - 3) * S, (by + 6 * cell + cell - 3) * S], fill=(38, 48, 10))
# dpad
cx, cy = 210, 470
for (dx, dy, glyph) in [(0, -1, "▲"), (-1, 0, "◀"), (0, 1, "▼"), (1, 0, "▶")]:
    x0 = cx + dx * 64 - 29
    y0 = cy + (0 if dy < 0 else 56) if dx == 0 else cy + 28
    if dx != 0:
        y0 = cy + 28
    rr(d, [x0, y0, x0 + 58, y0 + 48], 12, fill=(51, 65, 85))
    text(d, x0 + 29 - tw(d, glyph, D(16)) / 2, y0 + 14, glyph, D(16))
d = gradient(img, [150, 620, 270, 656], radius=14)
d = ImageDraw.Draw(img)
text(d, 210 - tw(d, "⏸ Pause", F("SemiBold", 14)) / 2, 630, "⏸ Pause", F("SemiBold", 14), (255, 255, 255))
text(d, 210 - tw(d, "Swipe or use the arrow keys.", F("Regular", 11.5)) / 2, 676, "Swipe or use the arrow keys.", F("Regular", 11.5), GREY)
bottom_nav(img, H, 2)
img.save("/tmp/nexora_game_snake.png")
print("snake ok")
