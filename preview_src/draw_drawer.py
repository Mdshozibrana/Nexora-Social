"""Preview: side drawer menu (owner's panel design) + pill bottom nav."""
from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 2
W, H = 420, 780
NOTO = "/usr/share/fonts/truetype/noto/NotoSans-{}.ttf"
DEJA = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
PAGE = (233, 235, 243)
TEXT = (38, 38, 46)
GREY = (107, 107, 118)
FAINT = (154, 154, 165)
GA, GB, GC = (79, 70, 229), (124, 58, 237), (219, 39, 119)


def F(style, size):
    return ImageFont.truetype(NOTO.format(style), int(size * S))


def D(size):
    return ImageFont.truetype(DEJA, int(size * S))


def tw(d, s, f):
    return d.textlength(s, font=f) / S


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
            col = tuple(int(GA[k] + (GB[k] - GA[k]) * u) for k in range(3))
        else:
            u = (t - 0.5) * 2
            col = tuple(int(GB[k] + (GC[k] - GB[k]) * u) for k in range(3))
        gd.line([(i, 0), (i, h)], fill=col)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w, h], radius=radius * S, fill=255)
    img.paste(grad, (int(x0), int(y0)), mask)
    return ImageDraw.Draw(img)


img = Image.new("RGB", (W * S, H * S), PAGE)
d = gradient(img, [-8, -8, 428, 96], radius=24)
d = ImageDraw.Draw(img)
text(d, 52, 14, "Nexora Social", F("Bold", 24), (255, 255, 255))
text(d, 16, 16, "☰", D(20), (255, 255, 255))
rr(d, [16, 120, 404, 300], 16, fill=(255, 255, 255))
rr(d, [16, 316, 404, 496], 16, fill=(255, 255, 255))
d.ellipse([30 * S, 136 * S, 62 * S, 168 * S], fill=(16, 185, 129))
# dim everything behind the drawer
dim = Image.new("RGBA", img.size, (24, 18, 46, 84))
img = Image.alpha_composite(img.convert("RGBA"), dim).convert("RGB")
d = ImageDraw.Draw(img)

# panel shadow + panel
sh = Image.new("L", img.size, 0)
ImageDraw.Draw(sh).rounded_rectangle([26 * S, 22 * S, 318 * S, 782 * S], radius=28 * S, fill=110)
img.paste((60, 55, 100), (0, 0), sh.filter(ImageFilter.GaussianBlur(14 * S)))
d = ImageDraw.Draw(img)
rr(d, [10, 10, 312, 770], 28, fill=(248, 248, 251))

# head
d = gradient(img, [24, 26, 68, 70], radius=14)
d = ImageDraw.Draw(img)
text(d, 46 - tw(d, "N", F("Bold", 21)) / 2, 36, "N", F("Bold", 21), (255, 255, 255))
text(d, 78, 32, "Nexora Social", F("Bold", 16.5))
text(d, 78, 54, "CONNECT ANYWHERE", F("Regular", 9.5), FAINT)
d.ellipse([262 * S, 28 * S, 296 * S, 62 * S], fill=(255, 255, 255))
text(d, 279 - tw(d, "‹", D(19)) / 2, 33, "‹", D(19), GREY)


def item(y, icon_kind, label, active=False, badge=None):
    d2 = d
    if active:
        d2 = gradient(img, [22, y, 300, y + 44], radius=15)
    col = (255, 255, 255) if active else (85, 85, 95)
    cx = 52
    if icon_kind == "home":
        text(d2, cx - tw(d2, "⌂", D(17)) / 2, y + 12, "⌂", D(17), col)
    elif icon_kind == "play":
        text(d2, cx - tw(d2, "▶", D(14)) / 2, y + 14, "▶", D(14), col)
    elif icon_kind == "star":
        text(d2, cx - tw(d2, "★", D(15)) / 2, y + 13, "★", D(15), col)
    elif icon_kind == "cup":
        text(d2, cx - tw(d2, "♛", D(16)) / 2, y + 12, "♛", D(16), col)
    elif icon_kind == "me":
        text(d2, cx - tw(d2, "☺", D(16)) / 2, y + 12, "☺", D(16), col)
    elif icon_kind == "games":
        rr(d2, [cx - 11, y + 14, cx + 11, y + 30], 7, outline=col, width=2 * S)
        d2.line([(cx - 6) * S, (y + 22) * S, (cx - 1) * S, (y + 22) * S], fill=col, width=2 * S)
        d2.line([(cx - 3.5) * S, (y + 19.5) * S, (cx - 3.5) * S, (y + 24.5) * S], fill=col, width=2 * S)
        d2.ellipse([(cx + 3) * S, (y + 19) * S, (cx + 6) * S, (y + 22) * S], fill=col)
        d2.ellipse([(cx + 6) * S, (y + 23) * S, (cx + 9) * S, (y + 26) * S], fill=col)
    elif icon_kind == "saved":
        d2.polygon([(cx - 6) * S, (y + 12) * S, (cx + 6) * S, (y + 12) * S,
                    (cx + 6) * S, (y + 30) * S, (cx) * S, (y + 24) * S,
                    (cx - 6) * S, (y + 30) * S], outline=col, width=2 * S)
    elif icon_kind == "inbox":
        rr(d2, [cx - 10, y + 16, cx + 10, y + 29], 3, outline=col, width=2 * S)
        d2.line([(cx) * S, (y + 12) * S, (cx) * S, (y + 21) * S], fill=col, width=2 * S)
        d2.polygon([(cx - 3.5) * S, (y + 18) * S, (cx + 3.5) * S, (y + 18) * S, (cx) * S, (y + 23) * S], fill=col)
    elif icon_kind == "search":
        d2.ellipse([(cx - 7) * S, (y + 13) * S, (cx + 3) * S, (y + 23) * S], outline=col, width=2 * S)
        d2.line([(cx + 2) * S, (y + 22) * S, (cx + 8) * S, (y + 28) * S], fill=col, width=2 * S)
    elif icon_kind == "logout":
        d2.rectangle([(cx - 3) * S, (y + 13) * S, (cx + 8) * S, (y + 29) * S], outline=col, width=2 * S)
        d2.line([(cx - 9) * S, (y + 21) * S, (cx + 2) * S, (y + 21) * S], fill=col, width=2 * S)
        d2.polygon([(cx) * S, (y + 17.5) * S, (cx) * S, (y + 24.5) * S, (cx + 5) * S, (y + 21) * S], fill=col)
    text(d2, 74, y + 12, label, F("SemiBold", 14.5), col)
    if badge:
        d2.ellipse([(268) * S, (y + 12) * S, (289) * S, (y + 33) * S], fill=(225, 29, 72))
        text(d2, 278.5 - tw(d2, badge, F("Bold", 11)) / 2, y + 16, badge, F("Bold", 11), (255, 255, 255))
    return d2


def sec(y, label):
    text(d, 32, y, label, F("Bold", 11.5), FAINT)


def div(y):
    d.line([30 * S, y * S, 292 * S, y * S], fill=(205, 206, 218), width=S)


y = 92
sec(y, "M e n u"); y += 26
d = item(y, "home", "Home", active=True); y += 50
d = item(y, "play", "Videos"); y += 50
d = item(y, "games", "Games"); y += 50
d = item(y, "star", "Daily Tasks"); y += 50
d = item(y, "cup", "Leaderboard"); y += 54
div(y); y += 12
sec(y, "L i b r a r y"); y += 26
d = item(y, "saved", "Saved", badge="3"); y += 50
d = item(y, "inbox", "Shared with me", badge="2"); y += 54
div(y); y += 12
sec(y, "A c c o u n t"); y += 26
d = item(y, "me", "My Profile"); y += 50
d = item(y, "search", "Search"); y += 50
d = item(y, "logout", "Log out")

# pill bottom nav (behind drawer bottom is fine — draw at right sliver)
img.save("/tmp/nexora_drawer.png")
print("drawer ok")
