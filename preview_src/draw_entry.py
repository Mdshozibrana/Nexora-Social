"""Preview: the neumorphic Login entry screen (owner's reference design)."""
from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 2
W, H = 420, 780
NOTO = "/usr/share/fonts/truetype/noto/NotoSans-{}.ttf"
DEJA = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
TEXT = (71, 42, 62)
GREY = (150, 97, 126)
FAINT = (188, 144, 166)
RED = (236, 72, 153)


def F(style, size):
    return ImageFont.truetype(NOTO.format(style), int(size * S))


def tw(d, s, f):
    return d.textlength(s, font=f) / S


def text(d, x, y, s, f, col=TEXT):
    d.text((x * S, y * S), s, font=f, fill=col)


def rr(d, box, r, **kw):
    d.rounded_rectangle([box[0] * S, box[1] * S, box[2] * S, box[3] * S],
                        radius=r * S, **kw)


img = Image.new("RGB", (W * S, H * S), (248, 234, 241))
# soft colour washes (glass background)
wash = Image.new("RGB", img.size, (248, 234, 241))
wd = ImageDraw.Draw(wash)
wd.ellipse([200 * S, -160 * S, 560 * S, 200 * S], fill=(255, 196, 222))
wd.ellipse([-180 * S, 480 * S, 220 * S, 880 * S], fill=(196, 242, 208))
img = wash.filter(ImageFilter.GaussianBlur(60 * S))
d = ImageDraw.Draw(img)

# disc with soft neumorphic shadow
cx, cy, rx, ry = 210, 330, 178, 190
shadow = Image.new("L", img.size, 0)
ImageDraw.Draw(shadow).ellipse([(cx - rx + 16) * S, (cy - ry + 20) * S,
                                (cx + rx + 16) * S, (cy + ry + 20) * S], fill=110)
img.paste((226, 168, 196), (0, 0), shadow.filter(ImageFilter.GaussianBlur(18 * S)))
glow = Image.new("L", img.size, 0)
ImageDraw.Draw(glow).ellipse([(cx - rx - 14) * S, (cy - ry - 16) * S,
                              (cx + rx - 14) * S, (cy + ry - 16) * S], fill=140)
img.paste((255, 255, 255), (0, 0), glow.filter(ImageFilter.GaussianBlur(18 * S)))
d = ImageDraw.Draw(img)
d.ellipse([(cx - rx) * S, (cy - ry) * S, (cx + rx) * S, (cy + ry) * S], fill=(255, 248, 250))

# logo
d.ellipse([(cx - 27) * S, (cy - 158) * S, (cx + 27) * S, (cy - 104) * S], fill=(236, 72, 153))
d.pieslice([(cx - 27) * S, (cy - 158) * S, (cx + 27) * S, (cy - 104) * S], -90, 90, fill=(190, 24, 93))
text(d, cx - tw(d, "N", F("Bold", 26)) / 2, cy - 148, "N", F("Bold", 26), (248, 234, 241))
text(d, cx - tw(d, "Login", F("Bold", 30)) / 2, cy - 96, "Login", F("Bold", 30))
text(d, cx - tw(d, "Sign in to your account", F("Regular", 13)) / 2, cy - 58,
     "Sign in to your account", F("Regular", 13), FAINT)


def field(y, glyph, label):
    x0, x1 = cx - 118, cx + 118
    rr(d, [x0, y, x1, y + 42], 12, fill=(250, 222, 235))
    d.line([(x0 + 10) * S, (y + 3) * S, (x1 - 10) * S, (y + 3) * S], fill=(255, 255, 255), width=2 * S)
    d.line([(x0 + 10) * S, (y + 39) * S, (x1 - 10) * S, (y + 39) * S], fill=(243, 205, 224), width=2 * S)
    if glyph == "user":
        d.ellipse([(x0 + 14) * S, (y + 10) * S, (x0 + 24) * S, (y + 20) * S], fill=GREY)
        d.pieslice([(x0 + 10) * S, (y + 18) * S, (x0 + 28) * S, (y + 34) * S], 180, 360, fill=GREY)
    else:
        rr(d, [x0 + 13, y + 16, x0 + 27, y + 30], 3, fill=GREY)
        d.arc([(x0 + 15) * S, (y + 7) * S, (x0 + 25) * S, (y + 20) * S], 180, 360, fill=GREY, width=2 * S)
    text(d, x0 + 38, y + 12, label, F("Regular", 13.5), (122, 74, 99))


field(cy - 28, "user", "@shozib")
field(cy + 26, "lock", "Telegram secure login")
# remember row
ry = cy + 82
rr(d, [cx - 118, ry, cx - 86, ry + 17], 9, fill=(236, 72, 153))
d.ellipse([(cx - 102) * S, (ry + 2) * S, (cx - 89) * S, (ry + 15) * S], fill=(255, 255, 255))
text(d, cx - 80, ry + 1, "Remember me", F("Regular", 12), GREY)
fp = "Forgot password?"
text(d, cx + 118 - tw(d, fp, F("Regular", 12)), ry + 1, fp, F("Regular", 12), GREY)
# button
by = cy + 112
rr(d, [cx - 118, by, cx + 118, by + 44], 12, fill=(236, 72, 153))
d.line([(cx - 108) * S, (by + 41) * S, (cx + 108) * S, (by + 41) * S], fill=(255, 180, 210), width=2 * S)
text(d, cx - tw(d, "S I G N   I N", F("Bold", 13.5)) / 2, by + 13, "S I G N   I N", F("Bold", 13.5), (255, 255, 255))
sw = "Don't have an account?"
text(d, cx - (tw(d, sw, F("Regular", 12.5)) + 6 + tw(d, "Sign up", F("Bold", 12.5))) / 2, by + 58, sw, F("Regular", 12.5), GREY)
text(d, cx - (tw(d, sw, F("Regular", 12.5)) + 6 + tw(d, "Sign up", F("Bold", 12.5))) / 2 + tw(d, sw, F("Regular", 12.5)) + 6, by + 58, "Sign up", F("Bold", 12.5), RED)
note = "No password needed — Telegram signs you in securely."
text(d, cx - tw(d, note, F("Regular", 11)) / 2, 560, note, F("Regular", 11), FAINT)
text(d, cx - tw(d, "Sign Up screen: same design, 3 fields + CREATE ACCOUNT", F("Regular", 11)) / 2, 582,
     "Sign Up screen: same design, 3 fields + CREATE ACCOUNT", F("Regular", 11), FAINT)
img.save("/tmp/nexora_entry.png")
print("entry ok")
