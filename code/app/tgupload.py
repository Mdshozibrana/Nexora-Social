"""Upload a member's file to Telegram (as the bot) to obtain a file_id.

Telegram has no standalone file-hosting endpoint for bots: the only way to
get a file_id for new bytes is to SEND the file in a message. We send it to
the member's own chat with the bot (notifications silenced), read the
file_id from the result, then delete that message so the chat stays clean.
Only the file_id is kept in our database — the file itself lives on
Telegram's servers, exactly like media posted through the bot (PRD §7).

If the member has never opened the bot (or has blocked it), Telegram
refuses the send; the caller turns that into a friendly "open the bot
once and press Start" message.
"""
import httpx

from .config import settings

# getFile (used by the /media proxy) serves files up to 20 MB, so the
# FINAL file handed to Telegram is capped there. Photos are capped at
# the same size directly. Videos may arrive larger (phone clips are
# routinely 30-80 MB): they are accepted up to RAW_VIDEO_MAX_BYTES and
# transcoded down to size by app.videoutil before they reach Telegram.
MAX_MEDIA_BYTES = 20 * 1024 * 1024
RAW_VIDEO_MAX_BYTES = 60 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm",
               "video/x-matroska", "video/3gpp", "video/x-msvideo"}


class TelegramUploadError(Exception):
    """kind: 'not_started' (member must open the bot once) or 'failed'."""

    def __init__(self, kind):
        super().__init__(kind)
        self.kind = kind


def classify(content_type: str):
    """'photo', 'video', or None when the type is not supported."""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in IMAGE_TYPES:
        return "photo"
    if ct in VIDEO_TYPES:
        return "video"
    return None


async def upload_media(chat_id: int, filename: str, data: bytes,
                       content_type: str):
    """Send `data` to the member's bot chat; return (kind, file_id)."""
    kind = classify(content_type)
    if kind is None:
        raise TelegramUploadError("failed")
    if not settings.BOT_TOKEN:
        raise TelegramUploadError("failed")
    api = f"https://api.telegram.org/bot{settings.BOT_TOKEN}"
    method, field = ("sendPhoto", "photo") if kind == "photo" \
        else ("sendVideo", "video")
    extra = {"supports_streaming": "true"} if kind == "video" else {}
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{api}/{method}",
            data={"chat_id": str(chat_id), "disable_notification": "true",
                  **extra},
            files={field: (filename or "upload", data, content_type)})
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if resp.status_code != 200 or not payload.get("ok"):
            desc = (payload.get("description") or "").lower()
            if resp.status_code == 403 or "blocked" in desc \
                    or "chat not found" in desc:
                raise TelegramUploadError("not_started")
            raise TelegramUploadError("failed")
        msg = payload["result"]
        if kind == "photo":
            file_id = msg["photo"][-1]["file_id"]
        else:
            file_id = msg["video"]["file_id"]
        # Best-effort cleanup: remove the copy from the member's bot chat.
        try:
            await client.post(f"{api}/deleteMessage", data={
                "chat_id": str(chat_id),
                "message_id": str(msg["message_id"])})
        except Exception:
            pass
    return kind, file_id
