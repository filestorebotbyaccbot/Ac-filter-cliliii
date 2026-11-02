import asyncio
import html

from pyrogram import Client, filters
from pyrogram.errors import FloodWait, InputUserDeactivated, PeerIdInvalid, UserIsBlocked

import database as db
import richmsg
import search_engine as engine
import texts
from config import Config
from richmsg import Btn

ADMIN = filters.user(Config.ADMINS) & filters.private
ADMIN_ANY = filters.user(Config.ADMINS)


# ---------------- banned users are stopped before any other handler ----------------
async def _is_banned(_, __, update):
    u = getattr(update, "from_user", None)
    return bool(u) and u.id not in Config.ADMINS and db.is_banned(u.id)


banned = filters.create(_is_banned)


@Client.on_message(banned, group=-10)
async def block_message(client, message):
    message.stop_propagation()


@Client.on_callback_query(banned, group=-10)
async def block_callback(client, cq):
    await cq.answer("🚫 You are banned from using this bot.", show_alert=True)
    cq.stop_propagation()


def _target(message):
    if len(message.command) > 1 and message.command[1].lstrip("-").isdigit():
        return int(message.command[1])
    r = message.reply_to_message
    return r.from_user.id if r and r.from_user else None


@Client.on_message(filters.command("ban") & ADMIN_ANY)
async def ban(client, message):
    uid = _target(message)
    if not uid:
        return await message.reply_text("Usage: /ban <code>user_id</code> (or reply to their message)")
    if uid in Config.ADMINS:
        return await message.reply_text("❌ You can't ban an admin.")
    await db.ban_user(uid)
    await message.reply_text(f"🚫 Banned <code>{uid}</code>.")


@Client.on_message(filters.command("unban") & ADMIN_ANY)
async def unban(client, message):
    uid = _target(message)
    if not uid:
        return await message.reply_text("Usage: /unban <code>user_id</code>")
    ok = await db.unban_user(uid)
    await message.reply_text(f"✅ Unbanned <code>{uid}</code>." if ok else "ℹ️ That user wasn't banned.")


# ---------------- stats ----------------
@Client.on_message(filters.command("stats") & ADMIN)
async def stats(client, message):
    d = {
        "files": await db.count_files(),
        "channels": len(await db.list_channels()),
        "users": await db.count_users(),
        "search1": await db.count_events("search", 1), "search7": await db.count_events("search", 7),
        "dl1": await db.count_events("delivery", 1), "dl7": await db.count_events("delivery", 7),
        "v1": await db.count_events("verify1", 1) + await db.count_events("verify2", 1),
        "v7": await db.count_events("verify1", 7) + await db.count_events("verify2", 7),
        "bp1": await db.count_events("bypass", 1), "bp7": await db.count_events("bypass", 7),
    }
    await message.reply_text(texts.stats_box(d))


# ---------------- delete a file from the database ----------------
@Client.on_message(filters.command("delfile") & ADMIN)
async def delfile(client, message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /delfile <code>name</code>")
    res = await engine.search(message.text.split(None, 1)[1])
    hits = res["hits"][:8]
    if not hits:
        return await message.reply_text("❌ No matching file.")
    rows = [[Btn(f"🗑 {h['name'][:45]}", cb=f"df:{h['_id']}", style="danger")] for h in hits]
    await richmsg.send(client, message.chat.id, "Which one to delete?", rows)


@Client.on_callback_query(filters.regex(r"^df:"))
async def delfile_cb(client, cq):
    if cq.from_user.id not in Config.ADMINS:
        return await cq.answer("Admins only.", show_alert=True)
    ok = await db.delete_file(cq.data[3:])
    await richmsg.edit(cq.message, "🗑 File deleted." if ok else "Already deleted.", [])
    await cq.answer()


# ---------------- broadcast ----------------
@Client.on_message(filters.command("broadcast") & ADMIN)
async def broadcast(client, message):
    src = message.reply_to_message
    text = message.text.split(None, 1)[1] if len(message.command) > 1 else None
    if not src and not text:
        return await message.reply_text("Usage: reply to any message with /broadcast, or send <code>/broadcast your text</code>.")
    users = [u for u in await db.all_user_ids() if not db.is_banned(u)]
    status = await message.reply_text(f"📣 Sending to {len(users)} users…")
    asyncio.create_task(_run_broadcast(client, src, text, users, status))


async def _run_broadcast(client, src, text, users, status):
    sent = blocked = failed = 0
    for i, uid in enumerate(users, 1):
        for attempt in (1, 2):
            try:
                if src:
                    await src.copy(uid)
                else:
                    await client.send_message(uid, text)
                sent += 1
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                if attempt == 1:
                    continue
                failed += 1
            except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid):
                blocked += 1
                await db.remove_user(uid)
            except Exception:
                failed += 1
            break
        if i % 50 == 0:
            try:
                await status.edit_text(f"📣 {i}/{len(users)}  ✅ {sent}  🚫 {blocked}  ⚠️ {failed}")
            except Exception:
                pass
        await asyncio.sleep(0.06)
    try:
        await status.edit_text(f"✅ <b>Broadcast done</b>\n✅ Sent: {sent}\n🚫 Blocked/inactive (removed): {blocked}\n⚠️ Failed: {failed}")
    except Exception:
        pass
