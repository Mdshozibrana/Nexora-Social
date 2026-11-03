"""The bot: front door + notifications (PRD section 2).
/start handles referrals via the deep-link payload ref_<telegram_id> and
hands the user a button that opens the Mini App."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Update, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters,
)

import asyncio
import os
import tempfile

from . import moderation
from .config import settings
from .db import SessionLocal
from .services import register_post
from .users import get_or_create_user


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    referrer_id = None
    if context.args and context.args[0].startswith("ref_"):
        try:
            referrer_id = int(context.args[0][4:])
        except ValueError:
            referrer_id = None
    db = SessionLocal()
    try:
        user, is_new = get_or_create_user(
            db,
            {"id": tg_user.id, "username": tg_user.username,
             "first_name": tg_user.first_name},
            referrer_id=referrer_id,
        )
        banned = user.is_banned
        if not banned and not user.photo_file_id:
            from . import photosync
            fid = await photosync.fetch_telegram_photo_file_id(tg_user.id)
            if fid:
                user.photo_file_id = fid
                db.commit()
    finally:
        db.close()
    if banned:
        await update.message.reply_text("This account is suspended.")
        return
    text = (
        f"Welcome to {settings.APP_NAME}! \U0001F44B\n"
        "Post photos and videos, follow people, earn points.\n"
        "Tip: send me a photo or video with a caption and I will post it "
        "for you. Send a photo with the caption #profile to set it as "
        "your profile picture. Or tap below to open the app."
    )
    buttons = []
    if settings.WEBAPP_URL:
        buttons.append([InlineKeyboardButton(
            "\U0001F680 Open App", web_app=WebAppInfo(url=settings.WEBAPP_URL))])
    if settings.BOT_USERNAME:
        link = f"https://t.me/{settings.BOT_USERNAME}?start=ref_{tg_user.id}"
        buttons.append([InlineKeyboardButton("\U0001F517 My referral link", url=
            f"https://t.me/share/url?url={link}&text=Join%20me!")])
    await update.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)


async def _screen_via_bot(context, ptype, file_id):
    """Phase 81: download the media from Telegram and classify it
    (a video by three frames). Any failure to fetch or classify
    fails closed — unscreened media never becomes a post."""
    try:
        tg_file = await context.bot.get_file(file_id)
        data = bytes(await tg_file.download_as_bytearray())
    except Exception:
        return "error"
    if ptype == "photo":
        return await asyncio.to_thread(
            moderation.classify_image, data, "image/jpeg")
    with tempfile.NamedTemporaryFile(delete=False,
                                     suffix=".src") as f:
        f.write(data)
        path = f.name
    try:
        return await asyncio.to_thread(moderation.screen_video, path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


async def _save_media_post(update: Update, ptype: str, file_id: str,
                           thumb_file_id: str = None, context=None):
    """A photo/video sent to the bot becomes a post (PRD section 7: the
    media already lives on Telegram's servers, we keep only the file_id).
    Same shared service as the Mini App, so first-post points and referral
    qualification work identically."""
    tg_user = update.effective_user
    db = SessionLocal()
    try:
        user, _ = get_or_create_user(
            db,
            {"id": tg_user.id, "username": tg_user.username,
             "first_name": tg_user.first_name})
        if user.is_banned:
            await update.message.reply_text("This account is suspended.")
            return
        # Phase 81 (owner's rule): adult or graphic media is
        # screened BEFORE the post exists — it is never posted,
        # and the member is told exactly why.
        if context is not None and moderation.active():
            verdict = await _screen_via_bot(context, ptype, file_id)
            if verdict != "clean":
                await update.message.reply_text(
                    moderation.block_message(ptype, verdict))
                return
        post, is_first, _ = register_post(
            db, user, ptype, file_id, update.message.caption or "",
            thumb_file_id=thumb_file_id)
    finally:
        db.close()
    note = " \U0001F389 First post bonus earned!" if is_first else ""
    await update.message.reply_text(
        f"\u2705 Posted to {settings.APP_NAME}!{note}")


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = (update.message.caption or "").lower()
    if "#profile" in caption:
        tg_user = update.effective_user
        db = SessionLocal()
        try:
            user, _ = get_or_create_user(
                db,
                {"id": tg_user.id, "username": tg_user.username,
                 "first_name": tg_user.first_name})
            user.photo_file_id = update.message.photo[-1].file_id
            db.commit()
        finally:
            db.close()
        await update.message.reply_text(
            "\u2705 Profile picture updated!")
        return
    await _save_media_post(update, "photo",
                           update.message.photo[-1].file_id,
                           context=context)


async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    video = update.message.video
    # Phase 51: keep Telegram's own thumbnail so the app can show
    # a preview frame before the video plays.
    thumb = video.thumbnail.file_id if video.thumbnail else None
    await _save_media_post(update, "video", video.file_id,
                           thumb_file_id=thumb, context=context)


def build_bot_app() -> Application:
    app = Application.builder().token(settings.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.VIDEO, video_handler))
    return app


async def start_bot(app: Application):
    """Start polling without blocking the API server (PTB async API)."""
    await app.initialize()
    # Phase 64 (owner): a persistent "Open App" button beside the
    # message input in every chat with the bot — Telegram's chat
    # menu button. Set once at startup; Telegram stores it
    # server-side. It takes over the menu slot next to the input
    # (typed commands like /start keep working). A failure here
    # must never stop the bot, so it is fully guarded.
    if settings.WEBAPP_URL:
        try:
            await app.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="Open App",
                    web_app=WebAppInfo(url=settings.WEBAPP_URL)))
        except Exception:
            pass
    await app.updater.start_polling(drop_pending_updates=True)
    await app.start()
