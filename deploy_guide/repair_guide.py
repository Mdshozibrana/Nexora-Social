# -*- coding: utf-8 -*-
"""Repair pass: slides 5, 7, 10 had tofu boxes (the '->' arrow glyph in
s5/s10, and '@' attached to a Bengali run in s7). Re-renders those three
slides with corrected text, rebuilds their segments from the EXISTING
audio, and re-concats the final video. Narration is unchanged."""
import sys, os, subprocess
sys.path.insert(0, os.path.expanduser("~/workspace/telegram_bot_course"))
import course_lib as cl

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.expanduser("~/workspace/friendline_tg_project/Nexora_Deploy_Guide_Video.mp4")


def nexora_footer(d, idx, total):
    t = "Nexora — ডেপ্লয় গাইড"
    w = cl.tw(d, t, "Medium", 24)
    cl.draw_mixed(d, (cl.W - w) / 2, 1212, t, "Medium", 24, cl.FOOT)
    n = f"{idx}/{total}"
    w2 = cl.tw(d, n, "Medium", 24)
    cl.draw_mixed(d, (cl.W - w2) / 2, 1172, n, "Medium", 24, cl.FOOT)


cl._footer = nexora_footer
B = "Nexora গাইড"
TOTAL = 10

FIXED = {
    5: ("step", "ধাপ ৩ — Render-এ Blueprint ডেপ্লয়",
        ["dashboard.render.com-এ যান", "New থেকে Blueprint চাপুন",
         "GitHub সংযুক্ত করে nexora রেপো বাছুন",
         "render.yaml নিজেই সার্ভিস ও ডাটাবেস সাজাবে",
         "Apply চাপার আগে ধাপ ৪-এর মান বসান"]),
    7: ("step", "ধাপ ৫ — নিজের Telegram ID বের করা",
        ["টেলিগ্রামে userinfobot বট খুঁজুন", "ওকে /start পাঠান",
         "ও আপনার numeric ID দেখিয়ে দেবে",
         "সেই সংখ্যাটাই ADMIN_IDS-এ বসান",
         "শুধু সংখ্যাটাই বসাবেন, আর কিছু নয়"]),
    10: ("slide", "সমস্যা হলে",
         ["বট চুপ থাকলে BOT_TOKEN যাচাই — কোলনসহ পুরোটা তো?",
          "অ্যাপ না খুললে WEBAPP_URL যাচাই করুন",
          "এরর দেখতে Render-এর Logs",
          "ব্রাউজারে সরাসরি খুললে লগইন হবে না — স্বাভাবিক",
          "যে ধাপে আটকাবেন, স্ক্রিনশট পাঠাবেন"]),
}

for i, (kind, heading, items) in FIXED.items():
    png = os.path.join(HERE, "slides", f"s{i}.png")
    if kind == "step":
        cl.render_step_slide(B, heading, items, png, i, TOTAL)
    else:
        cl.render_slide(B, heading, items, png, i, TOTAL)
    mp3 = os.path.join(HERE, "audio", f"s{i}.mp3")
    dur = cl.duration(mp3) + 0.35
    seg = os.path.join(HERE, f"seg{i}.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", png,
                    "-i", mp3, "-filter_complex",
                    "[1:a]pan=stereo|c0=c0|c1=c0,aresample=48000,apad=whole_dur=%.3f[a]" % dur,
                    "-map", "0:v", "-map", "[a]", "-t", "%.3f" % dur,
                    "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
                    "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                    seg], check=True)
    print("rebuilt segment", i)

lst = os.path.join(HERE, "concat.txt")
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                "-i", lst, "-c", "copy", "-movflags", "+faststart", OUT], check=True)
print("REBUILT", OUT, "duration", cl.duration(OUT))
