"""Full preview set for Nexora Social in the CURRENT design (glass theme,
capsule pill nav, entry screens, drawer). Self-contained; kept in the
project so it survives VM swaps. Run: python3 preview_src/draw_all.py"""
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import colorsys

S = 2
W = 420
NOTO = "/usr/share/fonts/truetype/noto/NotoSans-{}.ttf"
DEJA = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
PAGE = (233, 235, 243)
CARD = (31, 41, 55)
TEXT = (241, 245, 249)
GREY = (168, 182, 200)
FAINT = (126, 147, 171)
PINK = (236, 72, 153)
GA, GB, GC = (236, 72, 153), (219, 39, 119), (190, 24, 93)
OUT = "/tmp/previews"
import os
os.makedirs(OUT, exist_ok=True)


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


def gradient(img, box, radius=12, colors=(GA, GB, GC)):
    x0, y0, x1, y1 = [v * S for v in box]
    w, h = int(x1 - x0), int(y1 - y0)
    grad = Image.new("RGB", (max(w, 1), max(h, 1)))
    gd = ImageDraw.Draw(grad)
    a, b, c = colors
    for i in range(w):
        t = i / max(w - 1, 1)
        if t < 0.5:
            u = t * 2
            col = tuple(int(a[k] + (b[k] - a[k]) * u) for k in range(3))
        else:
            u = (t - 0.5) * 2
            col = tuple(int(b[k] + (c[k] - b[k]) * u) for k in range(3))
        gd.line([(i, 0), (i, h)], fill=col)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w, h], radius=radius * S, fill=255)
    img.paste(grad, (int(x0), int(y0)), mask)
    return ImageDraw.Draw(img)


def page_bg(H):
    img = Image.new("RGB", (W * S, H * S), (18, 18, 18))
    wash = Image.new("RGB", img.size, (18, 18, 18))
    wd = ImageDraw.Draw(wash)
    wd.ellipse([180 * S, -180 * S, 580 * S, 220 * S], fill=(52, 20, 40))
    wd.ellipse([240 * S, 120 * S, 620 * S, 480 * S], fill=(14, 42, 44))
    wd.ellipse([-200 * S, (H - 320) * S, 200 * S, (H + 80) * S], fill=(34, 42, 56))
    return wash.filter(ImageFilter.GaussianBlur(50 * S))


def hsl(h, s_, l):
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, l, s_)
    return (int(r * 255), int(g * 255), int(b * 255))


def avatar(d, cx, cy, r, name, hue, photo=False):
    if photo:
        d.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill=hsl(hue, .45, .62))
        d.ellipse([(cx - r * .34) * S, (cy - r * .55) * S, (cx + r * .34) * S, (cy + r * .13) * S], fill=hsl(hue, .35, .38))
        d.pieslice([(cx - r * .62) * S, (cy + r * .05) * S, (cx + r * .62) * S, (cy + r * 1.1) * S], 180, 360, fill=hsl(hue, .35, .38))
        return
    d.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill=hsl(hue, .62, .45))
    d.pieslice([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], -90, 90, fill=hsl(hue + 45, .68, .55))
    parts = name.split()
    ini = parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")
    f = F("Bold", r * .8)
    text(d, cx - tw(d, ini, f) / 2, cy - r * .42, ini, f, (255, 255, 255))


def badge(d, x, y, r=7.5):
    d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=(29, 155, 240))
    d.line([(x - r * .45) * S, y * S, (x - r * .12) * S, (y + r * .4) * S], fill=(255, 255, 255), width=max(2, S))
    d.line([(x - r * .12) * S, (y + r * .4) * S, (x + r * .5) * S, (y - r * .38) * S], fill=(255, 255, 255), width=max(2, S))


def hero(img, points="25"):
    d = gradient(img, [-8, -8, 428, 98], radius=24, colors=((31, 41, 55), (51, 65, 85), (31, 41, 55)))
    d = ImageDraw.Draw(img)
    text(d, 16, 15, "☰", D(19), (255, 255, 255))
    text(d, 46, 14, "Nexora Social", F("Bold", 23), (255, 255, 255))
    d.ellipse([372 * S, 12 * S, 404 * S, 44 * S], fill=(51, 65, 85), outline=(100, 116, 139), width=S)
    d.ellipse([382 * S, 21 * S, 394 * S, 33 * S], outline=(255, 255, 255), width=2 * S)
    d.line([392 * S, 31 * S, 399 * S, 38 * S], fill=(255, 255, 255), width=2 * S)
    avatar(d, 38, 70, 20, "MD Shozib Rana", 150, photo=True)
    nm = "MD Shozib Rana"
    text(d, 66, 56, nm, F("SemiBold", 14.5), (255, 255, 255))
    badge(d, 66 + tw(d, nm, F("SemiBold", 14.5)) + 12, 65)
    text(d, 66, 77, "1 posts · 2 followers · 2 following", F("Regular", 11), (168, 182, 200))
    chip = "★ " + points
    cw = tw(d, chip, D(13)) + 20
    rr(d, [404 - cw, 56, 404, 84], 14, fill=(236, 72, 153))
    text(d, 404 - cw + 10, 64, chip, D(13), (18, 18, 18))
    return 112


def bottom_nav(img, H, active):
    sh = Image.new("L", img.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle([14 * S, (H - 58) * S, 414 * S, (H - 2) * S], radius=30 * S, fill=90)
    img.paste((0, 0, 0), (0, 0), sh.filter(ImageFilter.GaussianBlur(8 * S)))
    d = ImageDraw.Draw(img)
    y = H - 66
    rr(d, [10, y, 410, H - 8], 29, fill=(31, 41, 55))
    items = ["house", "videos", "games", "tasks", "ranks", "me"]
    names = ["Feed", "Videos", "Games", "Tasks", "Ranks", "Me"]
    bw = (420 - 20 - 12 - 30) / 6
    for i, kind in enumerate(items):
        x = 16 + i * (bw + 6)
        if i == active:
            rr(d, [x, y + 7, x + bw, y + 51], 22, fill=(51, 65, 85), outline=(100, 116, 139), width=S)
            tcol = TEXT
        else:
            tcol = GREY
        cx = x + bw / 2
        if kind == "house":
            text(d, cx - tw(d, "⌂", D(15)) / 2, y + 12, "⌂", D(15), tcol)
        elif kind == "me":
            text(d, cx - tw(d, "☺", D(15)) / 2, y + 12, "☺", D(15), tcol)
        elif kind == "tasks":
            text(d, cx - tw(d, "★", D(14)) / 2, y + 12, "★", D(14), tcol)
        elif kind == "videos":
            rr(d, [cx - 9, y + 14, cx + 9, y + 28], 4, outline=tcol, width=2 * S)
            d.polygon([(cx - 3) * S, (y + 17.5) * S, (cx - 3) * S, (y + 24.5) * S, (cx + 4) * S, (y + 21) * S], fill=tcol)
        elif kind == "games":
            rr(d, [cx - 11, y + 15, cx + 11, y + 29], 7, outline=tcol, width=2 * S)
            d.line([(cx - 6) * S, (y + 22) * S, (cx - 1) * S, (y + 22) * S], fill=tcol, width=2 * S)
            d.line([(cx - 3.5) * S, (y + 19.5) * S, (cx - 3.5) * S, (y + 24.5) * S], fill=tcol, width=2 * S)
            d.ellipse([(cx + 3) * S, (y + 19) * S, (cx + 6) * S, (y + 22) * S], fill=tcol)
            d.ellipse([(cx + 6) * S, (y + 23) * S, (cx + 9) * S, (y + 26) * S], fill=tcol)
        else:
            text(d, cx - tw(d, "♛", D(14)) / 2, y + 12, "♛", D(14), tcol)
        text(d, cx - tw(d, names[i], F("SemiBold" if i == active else "Regular", 10)) / 2,
             y + 33, names[i], F("SemiBold" if i == active else "Regular", 10), tcol)


def card(d, x, y, x2, y2):
    rr(d, [x, y, x2, y2], 16, fill=CARD, outline=(58, 72, 92), width=S)


def wrap(d, s, f, maxw):
    lines, cur = [], ""
    for w_ in s.split():
        if tw(d, (cur + " " + w_).strip(), f) <= maxw:
            cur = (cur + " " + w_).strip()
        else:
            lines.append(cur); cur = w_
    if cur:
        lines.append(cur)
    return lines


def post_card(img, y, author, hue, when, caption, photo_scene=None,
              likes="12", comments="3", liked=False, verified=False, photo_av=False):
    d = ImageDraw.Draw(img)
    lines = wrap(d, caption, F("Regular", 13), 360)[:2]
    h = 52 + (404 if photo_scene else 0) + 19 * len(lines) + 42
    card(d, 12, y, 408, y + h)
    avatar(d, 38, y + 26, 15, author, hue, photo=photo_av)
    text(d, 62, y + 12, author, F("SemiBold", 14))
    nx = 62 + tw(d, author, F("SemiBold", 14))
    if verified:
        badge(d, nx + 11, y + 20, 6.5)
    text(d, 62, y + 32, when, F("Regular", 11), FAINT)
    text(d, 392 - tw(d, "⋮", D(15)), y + 12, "⋮", D(15), GREY)
    cy = y + 52
    if photo_scene:
        sy = cy + 2
        d.rounded_rectangle([54 * S, sy * S, 366 * S, (sy + 390) * S], radius=12 * S, fill=photo_scene[0])
        d.ellipse([282 * S, (sy + 34) * S, 330 * S, (sy + 82) * S], fill=(255, 224, 130))
        d.polygon([54 * S, (sy + 390) * S, 160 * S, (sy + 240) * S, 250 * S, (sy + 390) * S], fill=photo_scene[1])
        d.polygon([170 * S, (sy + 390) * S, 300 * S, (sy + 200) * S, 366 * S, (sy + 300) * S, 366 * S, (sy + 390) * S], fill=photo_scene[2])
        cy = sy + 404
    for ln in lines:
        text(d, 24, cy, ln, F("Regular", 13))
        cy += 19
    ay = y + h - 30
    text(d, 24, ay, ("♥ " if liked else "♡ ") + likes, D(13.5), PINK if liked else GREY)
    text(d, 92, ay, "💬", D(12), GREY)
    text(d, 106, ay, comments, F("Regular", 12.5), GREY)
    text(d, 150, ay, "↗ Share", F("Regular", 12.5), GREY)
    return y + h + 12


def section_title(d, y, title, hint_lines):
    text(d, 14, y, title, F("Bold", 19))
    yy = y + 28
    for ln in hint_lines:
        text(d, 14, yy, ln, F("Regular", 12), GREY)
        yy += 17
    return yy + 8


# ------------------------------------------------------------- ENTRY SIGNUP --
def entry_signup():
    H = 780
    img = page_bg(H)
    d = ImageDraw.Draw(img)
    cx, cy, rx, ry = 210, 330, 178, 192
    sh = Image.new("L", img.size, 0)
    ImageDraw.Draw(sh).ellipse([(cx - rx + 16) * S, (cy - ry + 20) * S, (cx + rx + 16) * S, (cy + ry + 20) * S], fill=110)
    img.paste((163, 177, 198), (0, 0), sh.filter(ImageFilter.GaussianBlur(18 * S)))
    gl = Image.new("L", img.size, 0)
    ImageDraw.Draw(gl).ellipse([(cx - rx - 14) * S, (cy - ry - 16) * S, (cx + rx - 14) * S, (cy + ry - 16) * S], fill=140)
    img.paste((255, 255, 255), (0, 0), gl.filter(ImageFilter.GaussianBlur(18 * S)))
    d = ImageDraw.Draw(img)
    d.ellipse([(cx - rx) * S, (cy - ry) * S, (cx + rx) * S, (cy + ry) * S], fill=(31, 41, 55))
    d = gradient(img, [cx - 27, cy - 162, cx + 27, cy - 108], radius=27)
    d = ImageDraw.Draw(img)
    text(d, cx - tw(d, "N", F("Bold", 26)) / 2, cy - 152, "N", F("Bold", 26), (255, 255, 255))
    text(d, cx - tw(d, "Sign Up", F("Bold", 30)) / 2, cy - 100, "Sign Up", F("Bold", 30))
    text(d, cx - tw(d, "Create your account", F("Regular", 13)) / 2, cy - 62,
         "Create your account", F("Regular", 13), FAINT)

    def field(y, label, lock=False):
        x0, x1 = cx - 118, cx + 118
        rr(d, [x0, y, x1, y + 42], 12, fill=(18, 18, 18))
        d.line([(x0 + 10) * S, (y + 3) * S, (x1 - 10) * S, (y + 3) * S], fill=(0, 0, 0), width=2 * S)
        d.line([(x0 + 10) * S, (y + 39) * S, (x1 - 10) * S, (y + 39) * S], fill=(58, 72, 92), width=2 * S)
        if lock:
            rr(d, [x0 + 13, y + 16, x0 + 27, y + 30], 3, fill=GREY)
            d.arc([(x0 + 15) * S, (y + 7) * S, (x0 + 25) * S, (y + 20) * S], 180, 360, fill=GREY, width=2 * S)
        else:
            d.ellipse([(x0 + 14) * S, (y + 10) * S, (x0 + 24) * S, (y + 20) * S], fill=GREY)
            d.pieslice([(x0 + 10) * S, (y + 18) * S, (x0 + 28) * S, (y + 34) * S], 180, 360, fill=GREY)
        text(d, x0 + 38, y + 12, label, F("Regular", 13.5), (201, 212, 226))

    field(cy - 32, "MD Shozib Rana")
    field(cy + 22, "@shozib")
    field(cy + 76, "Telegram secure login", lock=True)
    by = cy + 136
    rr(d, [cx - 118, by, cx + 118, by + 44], 12, fill=(236, 72, 153))
    text(d, cx - tw(d, "C R E A T E   A C C O U N T", F("Bold", 12.5)) / 2, by + 14,
         "C R E A T E   A C C O U N T", F("Bold", 12.5), (18, 18, 18))
    sw, lk = "Already have an account?", "Login"
    total = tw(d, sw, F("Regular", 12.5)) + 6 + tw(d, lk, F("Bold", 12.5))
    text(d, cx - total / 2, by + 58, sw, F("Regular", 12.5), GREY)
    text(d, cx - total / 2 + tw(d, sw, F("Regular", 12.5)) + 6, by + 58, lk, F("Bold", 12.5), PINK)
    note = "No password needed — Telegram signs you in securely."
    text(d, cx - tw(d, note, F("Regular", 11)) / 2, 566, note, F("Regular", 11), FAINT)
    img.save(f"{OUT}/nexora_entry_signup.png")


# --------------------------------------------------------------------- FEED --
def feed():
    H = 1090
    img = page_bg(H)
    y = hero(img)
    d = ImageDraw.Draw(img)
    card(d, 12, y, 408, y + 92)
    text(d, 24, y + 12, "Share something… use #tags", F("Regular", 13), FAINT)
    d.ellipse([24, y + 54, 58, y + 88], fill=(51, 65, 85))
    d.rounded_rectangle([31, y + 65, 51, y + 79], 3, outline=(241, 245, 249), width=2)
    d.ellipse([38, y + 69, 44, y + 75], fill=(241, 245, 249))
    d = gradient(img, [322, y + 56, 396, y + 84], radius=10)
    d = ImageDraw.Draw(img)
    text(d, 359 - tw(d, "Post", F("SemiBold", 13)) / 2, y + 62, "Post", F("SemiBold", 13), (18, 18, 18))
    y += 104
    rr(d, [12, y, 408, y + 38], 19, fill=(31, 41, 55))
    d = gradient(img, [14, y + 2, 208, y + 36], radius=17)
    d = ImageDraw.Draw(img)
    text(d, 111 - tw(d, "Explore", F("SemiBold", 13)) / 2, y + 9, "Explore", F("SemiBold", 13), (18, 18, 18))
    text(d, 308 - tw(d, "Following", F("SemiBold", 13)) / 2, y + 9, "Following", F("SemiBold", 13), GREY)
    y += 50
    y = post_card(img, y, "Nexora Social", 265,
                  "Official · 2h",
                  "Welcome to Nexora Social! This is the official account — follow for updates, tips and announcements. #nexora",
                  likes="128", comments="24", verified=True)
    y = post_card(img, y, "Ayesha Rahman", 320, "3h",
                  "Sunset over the Padma river today 🌅 #nature #bangladesh",
                  photo_scene=((135, 180, 220), (90, 160, 110), (60, 130, 90)),
                  likes="46", comments="8", liked=True, photo_av=True)
    y = post_card(img, y, "Tanvir Ahmed", 20, "5h",
                  "Just finished my first week of daily check-ins. The streak is real! 🔥",
                  likes="19", comments="4", photo_av=True)
    bottom_nav(img, H, 0)
    img.save(f"{OUT}/nexora_feed.png")


# ------------------------------------------------------------------- SEARCH --
def search():
    H = 720
    img = page_bg(H)
    y = hero(img)
    d = ImageDraw.Draw(img)
    card(d, 12, y, 318, y + 44)
    text(d, 24, y + 12, "ayesha", F("Regular", 13.5))
    d = gradient(img, [326, y, 408, y + 44], radius=12)
    d = ImageDraw.Draw(img)
    text(d, 367 - tw(d, "Search", F("SemiBold", 13)) / 2, y + 12, "Search", F("SemiBold", 13), (255, 255, 255))
    y += 58
    text(d, 14, y, "People", F("Bold", 15)); y += 26
    for name, un, hue in [("Ayesha Rahman", "@ayesha", 320), ("Ayesha Khatun", "@ayesha.k", 45)]:
        card(d, 12, y, 408, y + 58)
        d = ImageDraw.Draw(img)
        avatar(d, 40, y + 29, 16, name, hue, photo=True)
        text(d, 66, y + 10, name, F("SemiBold", 13.5))
        text(d, 66, y + 31, un, F("Regular", 11.5), FAINT)
        rr(d, [318, y + 14, 396, y + 42], 14, fill=(51, 65, 85))
        text(d, 357 - tw(d, "View", F("SemiBold", 12)) / 2, y + 21, "View", F("SemiBold", 12), TEXT)
        y += 70
    text(d, 14, y, "Posts", F("Bold", 15)); y += 26
    y = post_card(img, y, "Ayesha Rahman", 320, "3h",
                  "Sunset over the Padma river today 🌅 #nature",
                  likes="46", comments="8", liked=True, photo_av=True)
    bottom_nav(img, H, 0)
    img.save(f"{OUT}/nexora_search.png")


# -------------------------------------------------------------------- TASKS --
def tasks():
    H = 720
    img = page_bg(H)
    y = hero(img)
    d = ImageDraw.Draw(img)
    y = section_title(d, y + 2, "⭐ Daily Tasks",
                      ["Complete tasks to earn points. Each task can be",
                       "claimed once per day — progress resets tomorrow."])
    rows = [
        ("✅", "Daily check-in", "Just open the app and claim", "3 day streak 🔥", 1, 1, "+20"),
        ("👥", "Follow 2 people", "Follow 2 new members today", "", 1, 2, "+5"),
        ("💬", "Write 5 comments", "Comment on any posts", "", 3, 5, "+5"),
    ]
    for ic, name, desc, extra, done, total, pts in rows:
        card(d, 12, y, 408, y + 96)
        d = ImageDraw.Draw(img)
        text(d, 24, y + 12, ic, D(17))
        text(d, 56, y + 10, name, F("SemiBold", 14.5))
        text(d, 56, y + 31, desc, F("Regular", 12), GREY)
        if extra:
            text(d, 56, y + 52, extra, F("SemiBold", 12), PINK)
        bx0, bx1, by = 248, 396, y + 52
        if done >= total:
            d = gradient(img, [bx0, by, bx1, by + 32], radius=10)
            d = ImageDraw.Draw(img)
            lb = "Claim " + pts
            text(d, (bx0 + bx1) / 2 - tw(d, lb, F("Bold", 12.5)) / 2, by + 7, lb, F("Bold", 12.5), (18, 18, 18))
        else:
            rr(d, [bx0, by, bx1, by + 32], 10, fill=(51, 65, 85))
            lb = f"{done}/{total} · Claim {pts}"
            text(d, (bx0 + bx1) / 2 - tw(d, lb, F("SemiBold", 12)) / 2, by + 7, lb, F("SemiBold", 12), FAINT)
            rr(d, [56, y + 74, 56 + 180 * done / total, y + 79], 2, fill=PINK)
        y += 108
    bottom_nav(img, H, 3)
    img.save(f"{OUT}/nexora_tasks.png")


# -------------------------------------------------------------------- RANKS --
def ranks():
    H = 760
    img = page_bg(H)
    y = hero(img)
    d = ImageDraw.Draw(img)
    y = section_title(d, y + 2, "🏆 Leaderboard",
                      ["Top members by points. Earn points from posts,",
                       "referrals and daily tasks."])
    rows = [(1, "Nexora Social", 265, "12,480", True), (2, "Ayesha Rahman", 320, "3,240", False),
            (3, "Tanvir Ahmed", 20, "2,915", False), (4, "Rahim Uddin", 200, "2,430", False),
            (5, "Sadia Islam", 280, "1,975", False)]
    medals = {1: (250, 176, 32), 2: (160, 165, 180), 3: (196, 120, 60)}
    for rank, name, hue, pts, ver in rows:
        card(d, 12, y, 408, y + 58)
        d = ImageDraw.Draw(img)
        if rank in medals:
            d.ellipse([22 * S, (y + 15) * S, 50 * S, (y + 43) * S], fill=medals[rank])
            text(d, 36 - tw(d, str(rank), F("Bold", 13)) / 2, y + 21, str(rank), F("Bold", 13), (255, 255, 255))
        else:
            text(d, 36 - tw(d, str(rank), F("Bold", 13)) / 2, y + 21, str(rank), F("Bold", 13), GREY)
        avatar(d, 78, y + 29, 15, name, hue, photo=True)
        text(d, 102, y + 19, name, F("SemiBold", 13.5))
        if ver:
            badge(d, 102 + tw(d, name, F("SemiBold", 13.5)) + 11, y + 27, 6.5)
        pt = "⭐ " + pts
        text(d, 396 - tw(d, pt, F("Bold", 13)), y + 19, pt, F("Bold", 13), PINK)
        y += 68
    d = gradient(img, [12, y + 2, 408, y + 60], radius=16)
    d = ImageDraw.Draw(img)
    text(d, 24, y + 21, "Your rank", F("SemiBold", 13.5), (255, 255, 255))
    avatar(d, 128, y + 31, 14, "MD Shozib Rana", 150, photo=True)
    text(d, 150, y + 21, "#128 · MD Shozib Rana", F("SemiBold", 13), (255, 255, 255))
    text(d, 396 - tw(d, "⭐ 25", F("Bold", 13)), y + 21, "⭐ 25", F("Bold", 13), (255, 255, 255))
    bottom_nav(img, H, 4)
    img.save(f"{OUT}/nexora_ranks.png")


# ------------------------------------------------------------------ ME PAGE --
def me_page():
    H = 900
    img = page_bg(H)
    y = hero(img)
    d = ImageDraw.Draw(img)
    card(d, 12, y, 408, y + 118)
    text(d, 24, y + 12, "Points history", F("Bold", 14.5))
    rows = [("Daily check-in", "+20", "Today"), ("New post", "+5", "Today"),
            ("Referral: Tanvir joined", "+20", "Yesterday")]
    yy = y + 42
    for label, pts, when in rows:
        text(d, 24, yy, label, F("Regular", 12.5))
        text(d, 300, yy, pts, F("Bold", 12.5), (22, 163, 74))
        text(d, 396 - tw(d, when, F("Regular", 11)), yy, when, F("Regular", 11), FAINT)
        yy += 24
    y += 130
    card(d, 12, y, 408, y + 64)
    text(d, 24, y + 10, "🔗 Your referral link", F("SemiBold", 13))
    text(d, 24, y + 33, "t.me/NexoraSocial_bot?start=ref_2", F("Regular", 12), GREY)
    rr(d, [322, y + 16, 396, y + 46], 10, fill=(51, 65, 85))
    text(d, 359 - tw(d, "Copy", F("SemiBold", 12)) / 2, y + 24, "Copy", F("SemiBold", 12), TEXT)
    y += 76
    for i, lb in enumerate(["🔖 Saved", "📥 Shared with me"]):
        bx = 12 + i * 202
        card(d, bx, y, bx + 194, y + 46)
        text(d, bx + 97 - tw(d, lb, F("SemiBold", 13)) / 2, y + 14, lb, F("SemiBold", 13))
    y += 58
    card(d, 12, y, 408, y + 218)
    text(d, 24, y + 12, "💰 Monetization", F("Bold", 14.5))
    rr(d, [316, y + 10, 396, y + 36], 13, fill=(51, 65, 85))
    text(d, 356 - tw(d, "🔒 Locked", F("Bold", 11.5)) / 2, y + 17, "🔒 Locked", F("Bold", 11.5), TEXT)
    checks = [("Followers", 2, 500), ("Posts", 1, 25), ("Account age (days)", 3, 14),
              ("Lifetime points", 25, 5000), ("Check-in streak (days)", 3, 30)]
    yy = y + 46
    for label, done, total in checks:
        text(d, 24, yy, ("✓ " if done >= total else "○ ") + label, F("Regular", 12.5))
        val = f"{done}/{total}"
        text(d, 396 - tw(d, val, F("SemiBold", 12)), yy, val, F("SemiBold", 12), GREY)
        rr(d, [24, yy + 19, 396, yy + 24], 2, fill=(51, 65, 85))
        rr(d, [24, yy + 19, 24 + max(6, 372 * min(done / total, 1)), yy + 24], 2, fill=PINK)
        yy += 34
    y += 230
    y = post_card(img, y, "MD Shozib Rana", 150, "Your post · 2h",
                  "Hello Nexora! Excited to be here 🎉", likes="7", comments="2", photo_av=True)
    bottom_nav(img, H, 5)
    img.save(f"{OUT}/nexora_me.png")


# ------------------------------------------------------------- OTHER PROFILE --
def profile_page():
    H = 1010
    img = page_bg(H)
    y = hero(img)
    d = ImageDraw.Draw(img)
    card(d, 12, y, 408, y + 168)
    avatar(d, 52, y + 44, 26, "Ayesha Rahman", 320, photo=True)
    text(d, 90, y + 22, "Ayesha Rahman", F("Bold", 17))
    text(d, 90, y + 47, "@ayesha", F("Regular", 12.5), FAINT)
    text(d, 24, y + 84, "Photographer 📷 | Padma river sunsets | Dhaka", F("Regular", 12.5), GREY)
    text(d, 24, y + 106, "48 posts · 1,204 followers · 312 following", F("SemiBold", 12.5))
    d = gradient(img, [24, y + 128, 396, y + 158], radius=10)
    d = ImageDraw.Draw(img)
    text(d, 210 - tw(d, "Following ✓", F("Bold", 13)) / 2, y + 136, "Following ✓", F("Bold", 13), (18, 18, 18))
    y += 180
    y = post_card(img, y, "Ayesha Rahman", 320, "3h",
                  "Sunset over the Padma river today 🌅 #nature #bangladesh",
                  photo_scene=((135, 180, 220), (90, 160, 110), (60, 130, 90)),
                  likes="46", comments="8", liked=True, photo_av=True)
    y = post_card(img, y, "Ayesha Rahman", 320, "1d",
                  "Morning fog on the river — winter is coming ❄️",
                  likes="31", comments="5", photo_av=True)
    bottom_nav(img, H, 5)
    img.save(f"{OUT}/nexora_profile.png")


# -------------------------------------------------------------------- REELS --
def reel_scene(img, menu=False, share=False):
    H = 840
    d = gradient(img, [0, 0, W, H], radius=0, colors=((30, 27, 75), (76, 29, 149), (157, 23, 77)))
    d = ImageDraw.Draw(img)
    d.ellipse([250 * S, 90 * S, 340 * S, 180 * S], fill=(255, 214, 120))
    d.polygon([0, 700 * S, 160 * S, 480 * S, 330 * S, 700 * S], fill=(24, 60, 44))
    d.polygon([180 * S, 700 * S, 380 * S, 430 * S, 420 * S, 560 * S, 420 * S, 700 * S], fill=(18, 48, 36))
    d.rectangle([0, 690 * S, W * S, H * S], fill=(16, 40, 30))
    text(d, 18, 24, "✕", D(16), (255, 255, 255))
    rr(d, [118, 18, 302, 52], 17, fill=(30, 30, 40))
    text(d, 168 - tw(d, "Explore", F("SemiBold", 12.5)) / 2, 27, "Explore", F("SemiBold", 12.5), (255, 255, 255))
    rr(d, [212, 21, 298, 49], 14, fill=(255, 255, 255))
    text(d, 255 - tw(d, "Following", F("SemiBold", 12.5)) / 2, 28, "Following", F("SemiBold", 12.5), TEXT)
    text(d, 386, 22, "🔊", D(14), (255, 255, 255))
    # right rail
    avatar(d, 378, 470, 19, "Ayesha Rahman", 320, photo=True)
    for yy, glyph, num in [(540, "♥", "46"), (606, "💬", "8")]:
        text(d, 378 - tw(d, glyph, D(19)) / 2, yy, glyph, D(19), PINK if glyph == "♥" else (255, 255, 255))
        text(d, 378 - tw(d, num, F("SemiBold", 11.5)) / 2, yy + 26, num, F("SemiBold", 11.5), (255, 255, 255))
    text(d, 378 - tw(d, "↗", D(19)) / 2, 668, "↗", D(19), (255, 255, 255))
    text(d, 378 - tw(d, "Share", F("SemiBold", 11)) / 2, 694, "Share", F("SemiBold", 11), (255, 255, 255))
    text(d, 378 - tw(d, "⋮", D(19)) / 2, 724, "⋮", D(19), (255, 255, 255))
    avatar(d, 30, 726, 13, "Ayesha Rahman", 320, photo=True)
    text(d, 52, 716, "@ayesha", F("SemiBold", 13.5), (255, 255, 255))
    text(d, 16, 744, "Sunset over the Padma river today 🌅", F("Regular", 13), (255, 255, 255))
    text(d, 16, 766, "#nature #bangladesh", F("Regular", 12.5), (210, 210, 225))
    return d


def reels():
    H = 840
    img = Image.new("RGB", (W * S, H * S), (10, 10, 14))
    reel_scene(img)
    img.save(f"{OUT}/nexora_videos.png")


def reel_menu():
    H = 840
    img = Image.new("RGB", (W * S, H * S), (10, 10, 14))
    reel_scene(img)
    dim = Image.new("RGBA", img.size, (8, 6, 20, 110))
    img = Image.alpha_composite(img.convert("RGBA"), dim).convert("RGB")
    d = ImageDraw.Draw(img)
    rr(d, [0, 470, W, H], 0, fill=(31, 41, 55))
    d.rounded_rectangle([-4 * S, 466 * S, (W + 4) * S, 520 * S], radius=22 * S, fill=(31, 41, 55))
    rr(d, [186, 480, 234, 484], 2, fill=(100, 116, 139))
    rows = [("🔖", "Save"), ("↗", "Share"), ("🔗", "Copy link"), ("⬇️", "Download"),
            ("👤", "View profile"), ("➕", "Follow"), ("🙈", "Not interested"),
            ("🚩", "Report"), ("🗑", "Delete")]
    yy = 496
    for ic, lb in rows:
        text(d, 22, yy, ic, D(14.5))
        text(d, 56, yy + 1, lb, F("SemiBold" if lb in ("Save", "Share") else "Regular", 14.5),
             (185, 28, 28) if lb == "Delete" else TEXT)
        yy += 34
    rr(d, [16, yy + 2, 404, yy + 40], 12, fill=(51, 65, 85))
    text(d, 210 - tw(d, "Cancel", F("SemiBold", 13.5)) / 2, yy + 11, "Cancel", F("SemiBold", 13.5), GREY)
    img.save(f"{OUT}/nexora_reel_menu.png")


def share_picker():
    H = 840
    img = Image.new("RGB", (W * S, H * S), (10, 10, 14))
    reel_scene(img)
    dim = Image.new("RGBA", img.size, (8, 6, 20, 110))
    img = Image.alpha_composite(img.convert("RGBA"), dim).convert("RGB")
    d = ImageDraw.Draw(img)
    rr(d, [0, 430, W, H], 0, fill=(31, 41, 55))
    d.rounded_rectangle([-4 * S, 426 * S, (W + 4) * S, 480 * S], radius=22 * S, fill=(31, 41, 55))
    rr(d, [186, 440, 234, 444], 2, fill=(100, 116, 139))
    text(d, 20, 456, "Share with…", F("Bold", 16))
    rr(d, [16, 490, 404, 530], 12, fill=(51, 65, 85))
    text(d, 28, 501, "🔍  Search people", F("Regular", 13), FAINT)
    people = [("Nexora Social", 265, True, False), ("Tanvir Ahmed", 20, False, False),
              ("Rahim Uddin", 200, False, True), ("Sadia Islam", 280, False, False)]
    yy = 546
    for name, hue, ver, sent in people:
        avatar(d, 42, yy + 18, 17, name, hue, photo=True)
        text(d, 70, yy + 9, name, F("SemiBold", 14))
        if ver:
            badge(d, 70 + tw(d, name, F("SemiBold", 14)) + 11, yy + 18, 6.5)
        if sent:
            rr(d, [322, yy + 4, 396, yy + 34], 15, fill=(51, 65, 85))
            text(d, 359 - tw(d, "Sent ✓", F("Bold", 12)) / 2, yy + 12, "Sent ✓", F("Bold", 12), (134, 239, 172))
        else:
            d = gradient(img, [322, yy + 4, 396, yy + 34], radius=15)
            d = ImageDraw.Draw(img)
            text(d, 359 - tw(d, "Send", F("Bold", 12.5)) / 2, yy + 12, "Send", F("Bold", 12.5), (18, 18, 18))
        yy += 52
    rr(d, [16, yy + 6, 404, yy + 46], 12, fill=(51, 65, 85))
    text(d, 210 - tw(d, "↗  Share via Telegram", F("SemiBold", 13)) / 2, yy + 16,
         "↗  Share via Telegram", F("SemiBold", 13), TEXT)
    img.save(f"{OUT}/nexora_share.png")


# ------------------------------------------------------------- SAVED/SHARED --
def saved():
    H = 930
    img = page_bg(H)
    y = hero(img)
    d = ImageDraw.Draw(img)
    y = section_title(d, y + 2, "🔖 Saved",
                      ["Posts and videos you saved from the options menu."])
    y = post_card(img, y, "Ayesha Rahman", 320, "3h",
                  "Sunset over the Padma river today 🌅 #nature",
                  photo_scene=((135, 180, 220), (90, 160, 110), (60, 130, 90)),
                  likes="46", comments="8", liked=True, photo_av=True)
    y = post_card(img, y, "Nexora Social", 265, "Official · 2h",
                  "Welcome to Nexora Social! Follow for updates and tips. #nexora",
                  likes="128", comments="24", verified=True)
    rr(d, [12, y + 2, 408, y + 44], 12, fill=(31, 41, 55))
    text(d, 210 - tw(d, "← Back to my profile", F("SemiBold", 13)) / 2, y + 13,
         "← Back to my profile", F("SemiBold", 13), GREY)
    bottom_nav(img, H, 5)
    img.save(f"{OUT}/nexora_saved.png")


def shared():
    H = 930
    img = page_bg(H)
    y = hero(img)
    d = ImageDraw.Draw(img)
    y = section_title(d, y + 2, "📥 Shared with me",
                      ["Posts and videos other members sent you inside the app."])
    for sender, hue in [("Tanvir Ahmed", 20), ("Sadia Islam", 280)]:
        text(d, 14, y, f"{sender} shared a post with you · 1h", F("SemiBold", 12.5), GREY)
        y += 22
        if sender.startswith("Tanvir"):
            y = post_card(img, y, "Ayesha Rahman", 320, "3h",
                          "Sunset over the Padma river today 🌅 #nature",
                          likes="46", comments="8", photo_av=True)
        else:
            y = post_card(img, y, "Rahim Uddin", 200, "6h",
                          "New video is up! Check the Videos tab 🎬",
                          likes="12", comments="3", photo_av=True)
    bottom_nav(img, H, 5)
    img.save(f"{OUT}/nexora_shared.png")


if __name__ == "__main__":
    entry_signup()
    feed()
    search()
    tasks()
    ranks()
    me_page()
    profile_page()
    reels()
    reel_menu()
    share_picker()
    saved()
    shared()
    print("ALL PREVIEWS DRAWN")
