import asyncio
import html
import logging

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import FloodWait

import database as db
import richmsg
import search_engine as engine
import texts
from config import Config
from richmsg import Btn
from utils import clean_name, norm, series_key

log = logging.getLogger("indexer")
ADMIN = filters.user(Config.ADMINS) & filters.private
MEDIA = filters.audio | filters.document | filters.video
KINDS = ("audio", "document", "video")


def media_doc(m, doc_id: str):
    """A message with a file -> the dict we store (name comes from the file name, else title, else caption)."""
    for kind in KINDS:
        media = getattr(m, kind, None)
        if media:
            break
    else:
        return None
    raw = getattr(media, "file_name", None) or getattr(media, "title", None) or (m.caption or "").split("\n")[0]
    return {
        "_id": doc_id,
        "name": clean_name(raw),
        "file_id": media.file_id,
        "file_unique_id": media.file_unique_id,
        "size": getattr(media, "file_size", 0) or 0,
        "type": kind,
        "chat_id": m.chat.id,
        "msg_id": m.id,
    }


async def notify_subs(client, f: dict):
    """Tell 'Subscribe Updates' users that a matching new file arrived."""
    name_norm, link = norm(f["name"]), f"https://t.me/{Config.BOT_USERNAME}?start=f_{f['_id']}"
    async for s in db.iter_subs():
        if not engine.matches(s["key"], f["name"]):
            continue
        try:
            await richmsg.send(
                client, s["uid"], texts.sub_alert(s["q"], f["name"]),
                [[Btn("📂 Get file", url=link, style="success")], [Btn("🔕 Unsubscribe", cb=f"unsub:{s['_id']}", style="danger")]],
            )
        except Exception:
            pass
        await asyncio.sleep(0.05)


# ---------- auto indexing: files posted in a connected channel ----------
@Client.on_message(filters.channel & MEDIA, group=2)
async def auto_index(client, message):
    if not db.is_connected(message.chat.id):
        log.info("File seen in NOT connected channel %s - run /connect %s", message.chat.id, message.chat.id)
        return
    doc = media_doc(message, f"{message.chat.id}_{message.id}")
    if not doc:
        return
    new = await db.upsert_file(doc)
    log.info("Indexed %s (%s)", doc["name"], {True: "new", False: "updated", None: "duplicate"}[new])
    if new:
        asyncio.create_task(notify_subs(client, doc))


@Client.on_deleted_messages(filters.channel, group=2)
async def auto_delete(client, messages):
    for m in messages:
        if m.chat and db.is_connected(m.chat.id):
            await db.delete_file(f"{m.chat.id}_{m.id}")


# ---------- admin sends / forwards a file in the bot's PM ----------
@Client.on_message(ADMIN & MEDIA, group=2)
async def pm_index(client, message):
    doc = media_doc(message, f"pm_{message.chat.id}_{message.id}")
    if not doc:
        return
    new = await db.upsert_file(doc)
    if new is None:
        return await message.reply_text("ℹ️ This file is already saved.")
    await message.reply_text(f"✅ Saved: <b>{html.escape(doc['name'])}</b>\n<i>Search name:</i> <code>{html.escape(series_key(doc['name']))}</code>")
    if new:
        asyncio.create_task(notify_subs(client, doc))


# ---------- channel management ----------
@Client.on_message(filters.command("connect") & ADMIN)
async def connect(client, message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /connect <code>-100xxxxxxxxxx</code>")
    try:
        chat_id = int(message.command[1])
        chat = await client.get_chat(chat_id)
        me = await client.get_chat_member(chat_id, "me")
    except Exception as e:
        return await message.reply_text(f"❌ {html.escape(str(e))}")
    if me.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        return await message.reply_text("❌ Make the bot an admin of that channel first.")
    await db.add_channel(chat.id, chat.title)
    await message.reply_text(
        f"✅ Connected <b>{html.escape(chat.title)}</b>\nNew files are saved automatically. For old files use /index."
    )


@Client.on_message(filters.command("disconnect") & ADMIN)
async def disconnect(client, message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /disconnect <code>-100id</code> [purge]")
    chat_id = int(message.command[1])
    purge = len(message.command) > 2 and message.command[2].lower() == "purge"
    removed = await db.remove_channel(chat_id, purge)
    await message.reply_text("✅ Disconnected." + (f" {removed} files deleted." if purge else ""))


@Client.on_message(filters.command("channels") & ADMIN)
async def channels(client, message):
    chs = await db.list_channels()
    if not chs:
        return await message.reply_text("No channels connected.")
    lines = [f"• <b>{html.escape(c['title'])}</b> <code>{c['_id']}</code> – {await db.count_files(c['_id'])} files" for c in chs]
    await message.reply_text("\n".join(lines))


@Client.on_message(filters.command("index") & ADMIN)
async def index_old(client, message):
    args = message.command[1:]
    if not args:
        return await message.reply_text(
            "Usage: /index <code>-100id [last_msg_id] [first_msg_id]</code>\n"
            "Without last_msg_id the bot finds the newest message itself (it must be allowed to post in the channel)."
        )
    try:
        chat_id = int(args[0])
    except ValueError:
        return await message.reply_text("❌ First argument must be the channel ID like -1001234567890")
    if not db.is_connected(chat_id):
        return await message.reply_text("❌ Connect the channel first with /connect.")
    first = int(args[2]) if len(args) > 2 and args[2].isdigit() else 1
    if len(args) > 1 and args[1].isdigit():
        last = int(args[1])
    else:
        try:
            tmp = await client.send_message(chat_id, ".")
            last = tmp.id - 1
            await tmp.delete()
        except Exception as e:
            return await message.reply_text(f"❌ Couldn't detect the last message: {html.escape(str(e))}\nRun /index <code>-100id last_msg_id</code>")

    status = await message.reply_text("⏳ Indexing started...")
    new = upd = skipped = 0
    for start in range(first, last + 1, 200):
        ids = list(range(start, min(start + 200, last + 1)))
        while True:
            try:
                msgs = await client.get_messages(chat_id, ids)
                break
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
        for m in msgs:
            doc = None if m.empty else media_doc(m, f"{chat_id}_{m.id}")
            if not doc:
                skipped += 1
                continue
            r = await db.upsert_file(doc)
            if r is True:
                new += 1
            elif r is False:
                upd += 1
            else:
                skipped += 1
        try:
            await status.edit_text(f"⏳ {min(start + 199, last)}/{last}\n➕ {new} new  ♻️ {upd} updated  ⏭ {skipped} skipped")
        except Exception:
            pass
        await asyncio.sleep(1)
    await status.edit_text(f"✅ Done (IDs {first}–{last}).\n➕ {new} new  ♻️ {upd} updated  ⏭ {skipped} skipped")
