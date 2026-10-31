# Nexora — ডেপ্লয় গাইড (GitHub → Render)

কোড পুরো তৈরি ও পরীক্ষিত। লাইভ করতে মালিকের অ্যাকাউন্ট থেকে কয়েকটা ধাপ লাগবে — মোটামুটি ১৫–২০ মিনিটের কাজ।

## ধাপ ১ — GitHub-এ কোড তোলা

1. github.com-এ লগইন করে **New repository** — নাম দাও `nexora` (Public বা Private, যেকোনোটা) — **Create repository**
2. এই প্রজেক্ট ফোল্ডারটা ইতিমধ্যে git repo হিসাবে তৈরি ও প্রথম কমিট করা আছে। নিজের কম্পিউটারে ফোল্ডারটা নিয়ে টার্মিনালে চালাও:

```bash
cd friendline_tg_project
git remote add origin https://github.com/<তোমার-username>/nexora.git
git push -u origin main
```

(GitHub Desktop ব্যবহার করলেও হবে: Add local repository → এই ফোল্ডার → Publish.)

## ধাপ ২ — Render-এ Blueprint ডেপ্লয়

1. dashboard.render.com → **New** → **Blueprint**
2. GitHub অ্যাকাউন্ট সংযুক্ত করে `nexora` রেপোটা বেছে নাও — Render নিজে থেকেই `code/render.yaml` পড়ে Web Service (nexora) ও PostgreSQL (nexora-db) সাজিয়ে দেবে
3. **Apply / Create** চাপার আগে environment variable গুলো বসাও (ধাপ ৩)

## ধাপ ৩ — Environment variables (Render ড্যাশবোর্ডে)

| নাম | মান |
|---|---|
| BOT_TOKEN | @NexoraSocial_bot-এর টোকেন — BotFather → /mybots → Nexora → API Token (পুরোটা, কোলনসহ) |
| BOT_USERNAME | NexoraSocial_bot |
| ADMIN_IDS | তোমার নিজের Telegram numeric ID — জানতে টেলিগ্রামে **@userinfobot**-কে /start পাঠালেই ও তোমার ID দেখিয়ে দেবে। শুধু সংখ্যাটা বসাও |
| WEBAPP_URL | প্রথম ডেপ্লয়ের **পরে** (ধাপ ৪) |

## ধাপ ৪ — WEBAPP_URL বসানো

1. প্রথম ডেপ্লয় শেষ হলে সার্ভিসের ঠিকানা পাবে, যেমন `https://nexora-xxxx.onrender.com`
2. WEBAPP_URL = সেই ঠিকানা + `/webapp/` — যেমন `https://nexora-xxxx.onrender.com/webapp/`
3. সেভ করলেই Render আবার ডেপ্লয় নেবে — এরপর বটের /start-এর "Open App" বোতাম কাজ করবে

## ধাপ ৫ — লাইভ টেস্ট চেকলিস্ট

- [ ] টেলিগ্রামে @NexoraSocial_bot-কে /start — ওয়েলকাম মেসেজ + Open App বোতাম আসে কি না
- [ ] Open App চাপলে Mini App খোলে, নিজের নাম দেখায়
- [ ] বটকে একটা ছবি ক্যাপশনসহ পাঠাও → "Posted" উত্তর আসে + ফিডে দেখা যায় (প্রথম পোস্টে +৫ পয়েন্ট)
- [ ] অন্য অ্যাকাউন্ট (বন্ধুর) দিয়ে রেফারেল লিংকে জয়েন + প্রথম পোস্ট → তোমার কাছে নোটিফিকেশন ও +২০ পয়েন্ট
- [ ] লাইক/কমেন্ট/ফলো করলে পোস্টদাতার কাছে বটের নোটিফিকেশন যায় কি না
- [ ] Render Logs-এ লাল এরর আছে কি না

## সমস্যা হলে

- বট উত্তর না দিলে: BOT_TOKEN ঠিক বসেছে কি না (কোলনসহ পুরোটা) Render → Environment-এ যাচাই করো
- অ্যাপ খুললে "Please open from inside Telegram" দেখালে স্বাভাবিক — ব্রাউজারে সরাসরি খুললে লগইন হয় না, টেলিগ্রামের ভেতর থেকেই খুলতে হয়
- লগ দেখা: Render → সার্ভিস → Logs

## জানা সীমাবদ্ধতা (MVP)

- ছবি/ভিডিও পোস্ট শুধু বটে পাঠিয়ে করা যায়; Mini App-এর ভেতর থেকে আপলোড v2-তে আসবে
- ব্রডকাস্ট একে একে পাঠায় — ইউজার হাজার ছাড়ালে ধীর হবে, তখন queue লাগবে
- পয়েন্ট উত্তোলন v1-এ নেই (শুধু হিসাব ও লিডারবোর্ডের প্রস্তুতি)
