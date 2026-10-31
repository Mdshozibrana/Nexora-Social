# -*- coding: utf-8 -*-
"""Nexora deploy guide video — same proven pipeline as the Telegram Bot
Course (course_lib slides + Rumi@95 Bengali TTS + ffmpeg assembly,
720x1280 yuv420p, AAC 48kHz stereo), with a Nexora footer instead of the
course footer. Output: ../Nexora_Deploy_Guide_Video.mp4"""
import sys, os, subprocess
sys.path.insert(0, os.path.expanduser("~/workspace/telegram_bot_course"))
import course_lib as cl
from PIL import ImageDraw

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
data = [
 {"kind": "title", "badge": B, "title": "Nexora ডেপ্লয় গাইড",
  "subtitle": "GitHub থেকে Render — ধাপে ধাপে লাইভ",
  "say": "আসসালামু আলাইকুম! Nexora-র কোড পুরোপুরি তৈরি, সব টেস্ট পাস করেছে। এখন পালা সেটাকে সত্যিকারের লাইভ করার — যাতে আপনার বট চব্বিশ ঘণ্টা নিজে নিজে চলতে পারে। এই ভিডিও গাইডে আমরা ধাপে ধাপে দেখব: প্রথমে কোড GitHub-এ তোলা, তারপর Render-এ ডেপ্লয়, তারপর দরকারি মানগুলো বসানো, আর শেষে লাইভ টেস্ট। পুরো কাজটা মোটামুটি পনেরো থেকে বিশ মিনিটের। চলুন শুরু করি।"},
 {"kind": "slide", "badge": B, "heading": "শুরু করার আগে যা লাগবে",
  "bullets": ["একটা GitHub অ্যাকাউন্ট — ফ্রি", "Render অ্যাকাউন্ট — আপনার সাবস্ক্রিপশন আছেই", "বটের টোকেন — BotFather-এ তৈরি আছে", "নিজের Telegram ID — অ্যাডমিনের জন্য", "সময়: মোটামুটি ১৫–২০ মিনিট"],
  "say": "শুরু করার আগে জিনিসগুলো গুছিয়ে নিন। লাগবে একটা GitHub অ্যাকাউন্ট, না থাকলে ফ্রি খুলে নিন। Render অ্যাকাউন্ট আপনার সাবস্ক্রিপশনসহ আগেই আছে। বটের টোকেন BotFather-এ তৈরিই আছে, শুধু কপি করে বসাতে হবে। আর লাগবে নিজের Telegram আইডি, অ্যাডমিন নিয়ন্ত্রণের জন্য — সেটা পাওয়ার উপায় ধাপ পাঁচে দেখাব। এই চারটে জিনিস হাতের কাছে থাকলেই পুরো কাজটা একটানা করে ফেলা যাবে।"},
 {"kind": "step", "badge": B, "heading": "ধাপ ১ — GitHub-এ রেপো বানানো",
  "steps": ["ব্রাউজারে github.com-এ লগইন করুন", "New repository বোতামে চাপ দিন", "রেপোর নাম দিন nexora", "Create repository চাপুন", "ব্যস — খালি রেপো তৈরি"],
  "say": "ধাপ এক, GitHub-এ একটা রেপো বানানো। রেপো মানে হলো আপনার কোডের অনলাইন গুদাম। ব্রাউজারে GitHub-এ লগইন করে New repository-তে চাপ দিন, নাম দিন nexora, তারপর Create repository। কোনো অতিরিক্ত সেটিং বদলানোর দরকার নেই — খালি রেপোটাই আমাদের দরকার, কোড আমি আগেই তৈরি করে রেখেছি।"},
 {"kind": "code", "badge": B, "heading": "ধাপ ২ — কোড পুশ করা",
  "code": ["cd friendline_tg_project",
           "",
           "git remote add origin \\",
           "  https://github.com/YOU/nexora.git",
           "",
           "git push -u origin main"],
  "note": "YOU-এর জায়গায় নিজের GitHub username বসান। প্রজেক্টটা আগেই git রেপো হিসাবে তৈরি, শুধু push করলেই কোড উঠে যাবে।",
  "say": "ধাপ দুই, কোডটা ওই রেপোতে তুলে দেওয়া। প্রজেক্ট ফোল্ডারটা আমি আগেই git রেপো হিসাবে তৈরি করে প্রথম কমিট দিয়ে রেখেছি, তাই আপনার কাজ শুধু এই তিনটা কমান্ড। প্রথমে ফোল্ডারে ঢুকুন, তারপর remote add দিয়ে আপনার রেপোর ঠিকানাটা জুড়ে দিন — ঠিকানায় YOU লেখা জায়গায় নিজের GitHub username বসাবেন। শেষে push চাপলেই পুরো কোড GitHub-এ উঠে যাবে। GitHub Desktop ব্যবহার করলেও একই কাজ হবে।"},
 {"kind": "step", "badge": B, "heading": "ধাপ ৩ — Render-এ Blueprint ডেপ্লয়",
  "steps": ["dashboard.render.com-এ যান", "New থেকে Blueprint চাপুন", "GitHub সংযুক্ত করে nexora রেপো বাছুন", "render.yaml নিজেই সার্ভিস ও ডাটাবেস সাজাবে", "Apply চাপার আগে ধাপ ৪-এর মান বসান"],
  "say": "ধাপ তিন, আসল ডেপ্লয়। Render-এর ড্যাশবোর্ডে গিয়ে New থেকে Blueprint বাছুন, GitHub অ্যাকাউন্টটা সংযুক্ত করে nexora রেপোটা দেখিয়ে দিন। প্রজেক্টে render.yaml নামে একটা ফাইল আমি দিয়ে রেখেছি — Render ওটা পড়ে নিজে নিজেই ওয়েব সার্ভিস আর PostgreSQL ডাটাবেস সাজিয়ে দেবে, আপনাকে হাতে কিছু বানাতে হবে না। তবে Apply চাপার আগে পরের ধাপের মানগুলো বসিয়ে নিন।"},
 {"kind": "slide", "badge": B, "heading": "ধাপ ৪ — Environment-এর ৪টা মান",
  "bullets": ["BOT_TOKEN — BotFather থেকে পুরো টোকেন", "BOT_USERNAME — NexoraSocial_bot", "ADMIN_IDS — নিজের Telegram numeric ID", "WEBAPP_URL — প্রথম ডেপ্লয়ের পরে (ধাপ ৬)", "টোকেন কাউকে পাঠাবেন না, গোপন রাখুন"],
  "say": "ধাপ চার সবচেয়ে গুরুত্বপূর্ণ — চারটা environment মান। BOT_TOKEN-এ বসবে BotFather থেকে নেওয়া পুরো টোকেনটা, মাঝখানের কোলনসহ। BOT_USERNAME-এ বসবে NexoraSocial_bot। ADMIN_IDS-এ বসবে আপনার নিজের Telegram আইডি, যাতে ব্যান আর ব্রডকাস্টের নিয়ন্ত্রণ শুধু আপনার হাতে থাকে। আর WEBAPP_URL এখন খালি রাখুন, ওটা প্রথম ডেপ্লয়ের পরে বসাব ধাপ ছয়ে। মনে রাখবেন, টোকেনটা পাসওয়ার্ডের মতো গোপন — কারো সাথে শেয়ার করবেন না।"},
 {"kind": "step", "badge": B, "heading": "ধাপ ৫ — নিজের Telegram ID বের করা",
  "steps": ["টেলিগ্রামে userinfobot বট খুঁজুন", "ওকে /start পাঠান", "ও আপনার numeric ID দেখিয়ে দেবে", "সেই সংখ্যাটাই ADMIN_IDS-এ বসান", "শুধু সংখ্যাটাই বসাবেন, আর কিছু নয়"],
  "say": "নিজের Telegram আইডি বের করা একদম সহজ। টেলিগ্রামে userinfobot নামের বটটা খুঁজে ওকে start পাঠালেই ও আপনার আইডিটা দেখিয়ে দেবে — লম্বা একটা সংখ্যা। সেই সংখ্যাটা কপি করে ADMIN_IDS-এ বসিয়ে দিন। খেয়াল রাখবেন, এটা আপনার username নয়, সংখ্যাটাই লাগবে।"},
 {"kind": "step", "badge": B, "heading": "ধাপ ৬ — WEBAPP_URL বসানো",
  "steps": ["প্রথম ডেপ্লয় শেষ হওয়া পর্যন্ত অপেক্ষা করুন", "সার্ভিসের onrender.com ঠিকানাটা দেখুন", "ঠিকানার শেষে /webapp/ যোগ করুন", "WEBAPP_URL হিসাবে বসিয়ে সেভ করুন", "সেভ হলেই Render আবার ডেপ্লয় নেবে"],
  "say": "প্রথম ডেপ্লয় শেষ হলে Render আপনার সার্ভিসের একটা ঠিকানা দেবে, দেখতে অনেকটা nexora ড্যাশ কিছু একটা ডট onrender ডট কম-এর মতো। সেই ঠিকানার শেষে webapp যোগ করে পুরোটা WEBAPP_URL-এ বসিয়ে সেভ করুন। সেভ হলেই Render নিজে থেকে আবার ডেপ্লয় নেবে। এই ঠিকানাটাই বটের Open App বোতামের প্রাণ — এটা না বসালে বোতাম কাজ করবে না।"},
 {"kind": "step", "badge": B, "heading": "ধাপ ৭ — লাইভ টেস্ট",
  "steps": ["@NexoraSocial_bot-কে /start পাঠান", "Open App চেপে Mini App খুলুন", "বটে ছবি পাঠিয়ে পোস্ট করে দেখুন", "বন্ধুকে নিজের রেফারেল লিংক পাঠান", "লাইক-কমেন্টে নোটিফিকেশন যাচাই করুন"],
  "say": "সবশেষে লাইভ টেস্ট। টেলিগ্রামে নিজের বটকে start পাঠান — ওয়েলকাম মেসেজ আর Open App বোতাম এলে অর্ধেক যাচাই হয়েই গেল। অ্যাপ খুলে নিজের নাম দেখতে পেলে লগইন ঠিক আছে। বটে একটা ছবি ক্যাপশনসহ পাঠান, পোস্ট হয়ে ফিডে দেখা গেলে মিডিয়া পথও ঠিক। তারপর বন্ধুকে আপনার রেফারেল লিংকটা পাঠিয়ে জয়েন আর প্রথম পোস্ট করান — আপনার কাছে নোটিফিকেশন আর বিশ পয়েন্ট এলে পুরো সিস্টেমই লাইভ।"},
 {"kind": "slide", "badge": B, "heading": "সমস্যা হলে",
  "bullets": ["বট চুপ থাকলে BOT_TOKEN যাচাই — কোলনসহ পুরোটা তো?", "অ্যাপ না খুললে WEBAPP_URL যাচাই করুন", "এরর দেখতে Render-এর Logs", "ব্রাউজারে সরাসরি খুললে লগইন হবে না — স্বাভাবিক", "যে ধাপে আটকাবেন, স্ক্রিনশট পাঠাবেন"],
  "say": "কোথাও আটকে গেলে ঘাবড়াবেন না। বট উত্তর না দিলে প্রথমে টোকেনটা যাচাই করুন — কোলনসহ পুরোটা বসেছে তো। অ্যাপ না খুললে WEBAPP_URL-টা মিলিয়ে দেখুন। আর যেকোনো এররের কারণ জানতে Render-এর Logs-ই সেরা জায়গা। একটা কথা মনে রাখবেন, অ্যাপটা ব্রাউজারে সরাসরি খুললে লগইন হবে না, এটা টেলিগ্রামের ভেতর থেকেই খুলতে হয় — এটা কোনো সমস্যা নয়। আর যেকোনো ধাপে আটকালে স্ক্রিনশট পাঠিয়ে দেবেন, আমি দেখে বলে দেব কোথায় কী করতে হবে। Nexora লাইভ করার জন্য শুভকামনা! আল্লাহ হাফেজ।"},
]

sdir = os.path.join(HERE, "slides")
adir = os.path.join(HERE, "audio")
os.makedirs(sdir, exist_ok=True)
os.makedirs(adir, exist_ok=True)
total = len(data)
segs = []
for i, s in enumerate(data, 1):
    png = os.path.join(sdir, f"s{i}.png")
    mp3 = os.path.join(adir, f"s{i}.mp3")
    if s["kind"] == "title":
        cl.render_title_slide(s["badge"], s["title"], s["subtitle"], png, i, total)
    elif s["kind"] == "step":
        cl.render_step_slide(s["badge"], s["heading"], s["steps"], png, i, total)
    elif s["kind"] == "code":
        cl.render_code_slide(s["badge"], s["heading"], s["code"], s.get("note", ""), png, i, total)
    else:
        cl.render_slide(s["badge"], s["heading"], s["bullets"], png, i, total)
    cl.tts(s["say"], mp3)
    dur = cl.duration(mp3) + 0.35
    seg = os.path.join(HERE, f"seg{i}.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", png,
                    "-i", mp3, "-filter_complex",
                    "[1:a]pan=stereo|c0=c0|c1=c0,aresample=48000,apad=whole_dur=%.3f[a]" % dur,
                    "-map", "0:v", "-map", "[a]", "-t", "%.3f" % dur,
                    "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
                    "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                    seg], check=True)
    segs.append(seg)

lst = os.path.join(HERE, "concat.txt")
with open(lst, "w") as f:
    for s in segs:
        f.write(f"file '{s}'\n")
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                "-i", lst, "-c", "copy", "-movflags", "+faststart", OUT], check=True)
print("BUILT", OUT, "duration", cl.duration(OUT))
