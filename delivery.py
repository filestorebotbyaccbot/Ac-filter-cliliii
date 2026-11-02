"""Getting a file to a user: force-sub check -> verification -> send the file (PM or delivery channel)."""
import logging
import re
import time

from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import UserNotParticipant

import database as db
import settings
import texts
import verify
from config import Config
import richmsg
from richmsg import Btn
from utils import fmt_clock, fmt_duration

log = logging.getLogger("delivery")
_invites = {}


async def temp_send(client, chat_id, text, rows=None, secs=None):
    """Send a message (rich when it has buttons) that deletes itself after the 'prompts' time."""
    mid = await richmsg.send(client, chat_id, text, rows or [])
    await db.schedule_delete(chat_id, mid, settings.get("del_prompt") if secs is None else secs)
    return mid


# ---------- force subscribe (normal or request-to-join) ----------
async def fsub_missing(client, uid: int) -> list:
    if not settings.get("fsub_enabled") or uid in Config.ADMINS:
        return []
    missing = []
    for ch in settings.get("fsub_channels") or []:
        cid = ch["chat_id"]
        try:
            m = await client.get_chat_member(cid, uid)
            joined = m.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)
        except UserNotParticipant:
            joined = False
        except Exception as e:  # broken setup must never lock everybody out
            log.warning("force-sub check failed for %s: %s", cid, e)
            joined = True
        if not joined and ch.get("mode") == "request" and await db.has_joinreq(cid, uid):
            joined = True
        if not joined:
            missing.append(ch)
    return missing


async def invite_url(client, ch: dict):
    if ch.get("link"):
        return ch["link"]
    key = (ch["chat_id"], ch.get("mode"))
    if key not in _invites:
        try:
            link = await client.create_chat_invite_link(
                ch["chat_id"], name="fsub", creates_join_request=(ch.get("mode") == "request")
            )
            _invites[key] = link.invite_link
        except Exception as e:
            log.warning("no invite link for %s: %s", ch["chat_id"], e)
            return None
    return _invites[key]


async def send_fsub_prompt(client, uid: int, fid, missing: list):
    rows = []
    for ch in missing:
        url = await invite_url(client, ch)
        if url:
            label = "📩 Request to join" if ch.get("mode") == "request" else "➕ Join"
            rows.append([Btn(f"{label} {ch.get('title', '')[:24]}".strip(), url=url, style="primary")])
    rows.append([Btn("✅ I've joined", cb=f"fs:{fid or '-'}", style="success")])
    await temp_send(client, uid, texts.fsub_prompt(), rows)


# ---------- verification prompt ----------
async def send_verify_prompt(client, uid: int, stage: int, fid):
    doc = await verify.new_token(uid, stage, fid)
    url = await verify.link_for(doc)
    if not url:
        return await temp_send(client, uid, texts.verify_unavailable())
    f = await db.get_file(fid) if fid else None
    tz = settings.get("tz_offset")
    valid_text = fmt_clock(verify.next_midnight(time.time(), tz) - 60, tz)
    rows = [[Btn("✅ Verify", url=url, style="success")]]
    tut = settings.get(f"s{doc['sh']}_tutorial")
    if tut:
        rows.append([Btn("🎥 How to verify", url=tut, style="primary")])
    await temp_send(
        client, uid,
        texts.verify_prompt(stage, f and f["name"], fmt_duration(settings.get("v2_free")), valid_text),
        rows,
    )


# ---------- main entry: a user wants a file ----------
async def request_file(client, uid: int, fid: str):
    f = await db.get_file(fid)
    if not f:
        return await temp_send(client, uid, texts.file_missing())
    miss = await fsub_missing(client, uid)
    if miss:
        return await send_fsub_prompt(client, uid, fid, miss)
    if uid not in Config.ADMINS and verify.chain():
        ok, _, _ = verify.access(await db.get_user(uid))
        if not ok:
            return await send_verify_prompt(client, uid, 1, fid)
    await deliver(client, uid, f)


def _msg_link(sent) -> str:
    link = getattr(sent, "link", None)
    if link:
        return link
    chat = sent.chat
    if getattr(chat, "username", None):
        return f"https://t.me/{chat.username}/{sent.id}"
    return f"https://t.me/c/{str(chat.id).replace('-100', '', 1)}/{sent.id}"


async def deliver(client, uid: int, f: dict):
    protect = bool(settings.get("protect_content"))
    cap = texts.file_caption(settings.get("caption"), f["name"], f.get("size"))
    secs = int(settings.get("del_file") or 0)
    ch = str(settings.get("delivery_channel") or "").strip()
    try:
        if settings.get("delivery_mode") == "channel" and ch:
            cid = int(ch) if re.fullmatch(r"-?\d+", ch) else ch
            sent = await client.send_cached_media(cid, f["file_id"], caption=cap, protect_content=protect)
            await db.schedule_delete(cid, sent.id, secs)
            await temp_send(
                client, uid, texts.file_ready(f["name"], secs),
                [[Btn("📂 Open file", url=_msg_link(sent), style="primary")]],
            )
        else:
            sent = await client.send_cached_media(uid, f["file_id"], caption=cap, protect_content=protect)
            await db.schedule_delete(uid, sent.id, secs)
            if secs and settings.get("deliver_note"):
                await temp_send(client, uid, texts.file_note(secs), secs=secs)
        await db.log_event("delivery", uid)
    except Exception as e:
        log.exception("delivery failed")
        await temp_send(client, uid, f"⚠️ <b>Couldn't send the file.</b>\n<code>{type(e).__name__}</code> - please try again or tell the admin.")
