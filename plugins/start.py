import time

from pyrogram import Client, filters

import database as db
import delivery
import richmsg
import settings
import texts
import verify
from config import Config
from richmsg import Btn
from utils import fmt_clock, fmt_duration


@Client.on_message(filters.command(["start", "help"]) & filters.private)
async def start(client, message):
    user = message.from_user
    await db.add_user(user.id)
    payload = message.command[1] if len(message.command) > 1 and message.command[0] == "start" else ""
    if payload:
        await db.schedule_delete(message.chat.id, message.id, settings.get("del_prompt"))
    if payload.startswith("f_"):
        return await delivery.request_file(client, user.id, payload[2:])
    if payload.startswith("v_"):
        return await on_verify_return(client, user.id, payload[2:])

    if message.command[0] == "help":
        return await message.reply_text(texts.help_text(user.id in Config.ADMINS))
    rows = [[Btn("➕ Add me to your group", url=f"https://t.me/{Config.BOT_USERNAME}?startgroup=true", style="success")]]
    if settings.get("updates_link"):
        rows.append([Btn("📢 Updates channel", url=settings.get("updates_link"), style="primary")])
    if settings.get("request_link"):
        rows.append([Btn("📝 Request Story", url=settings.get("request_link"), style="primary")])
    await richmsg.send(client, message.chat.id, texts.welcome(user.first_name or "there"), rows)


async def on_verify_return(client, uid: int, token: str):
    status, doc = await verify.complete(uid, token)
    if status == "ok":
        tz = settings.get("tz_offset")
        stage = doc["stage"]
        valid_text = fmt_clock(verify.next_midnight(time.time(), tz) - 60, tz)
        free_text = fmt_duration(settings.get("v2_free"))
        rows = []
        if stage == 1 and len(verify.chain()) > 1:  # optional second verification for longer free time
            rows = [[Btn(f"⚡ Get {free_text} free", cb="vf2", style="success")]]
        await delivery.temp_send(client, uid, texts.verify_ok(stage, free_text, valid_text), rows)
        if doc.get("file_id"):
            f = await db.get_file(doc["file_id"])
            if f:
                await delivery.deliver(client, uid, f)
        return
    await delivery.temp_send(client, uid, texts.verify_fail(status))
    if status in ("fast", "expired"):
        await delivery.send_verify_prompt(client, uid, doc["stage"], doc.get("file_id"))


@Client.on_callback_query(filters.regex(r"^fs:"))
async def fsub_retry(client, cq):
    fid = cq.data[3:]
    await cq.answer()
    try:
        await cq.message.delete()
    except Exception:
        pass
    if fid == "-":
        return
    await delivery.request_file(client, cq.from_user.id, fid)


@Client.on_callback_query(filters.regex(r"^vf2$"))
async def second_verification(client, cq):
    uid = cq.from_user.id
    ok, _, tier = verify.access(await db.get_user(uid))
    if tier == 2:
        return await cq.answer("You already have the long free time ✅", show_alert=True)
    await cq.answer()
    await delivery.send_verify_prompt(client, uid, 2, None)


@Client.on_callback_query(filters.regex(r"^noop$"))
async def noop(client, cq):
    await cq.answer()
