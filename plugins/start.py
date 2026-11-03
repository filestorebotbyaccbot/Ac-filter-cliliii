import logging
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

log = logging.getLogger("start")


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
    if status == "stale":  # an older link of a step that is already done: nothing to grant, just continue
        if doc and doc.get("file_id"):
            await delivery.request_file(client, uid, doc["file_id"])
        return
    if status == "ok":
        tz = settings.get("tz_offset")
        two = len(verify.chain()) > 1
        valid_text = fmt_clock(verify.next_midnight(time.time(), tz) - 60, tz)
        await delivery.temp_send(
            client, uid,
            texts.verify_ok(doc["stage"], two, fmt_duration(settings.get("v2_gap")), fmt_duration(settings.get("v2_free")), valid_text),
        )
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
async def old_second_button(client, cq):  # buttons from older messages
    await cq.answer("The 2nd verification is asked automatically after your free time ends.", show_alert=True)


@Client.on_callback_query(filters.regex(r"^noop$"))
async def noop(client, cq):
    await cq.answer()


# ---- force-sub "request to join" channels: remember the request, then carry on with the user's file ----
@Client.on_chat_join_request()
async def on_join_request(client, req):
    chat_id, uid = req.chat.id, req.from_user.id
    if chat_id not in [c["chat_id"] for c in settings.get("fsub_channels") or []]:
        return
    await db.add_joinreq(chat_id, uid)
    if settings.get("fsub_autoapprove"):
        try:
            await client.approve_chat_join_request(chat_id, uid)
        except Exception as e:
            log.warning("couldn't approve join request: %s", e)
    await delivery.auto_continue(client, uid)
