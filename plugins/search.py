import math

from bson import ObjectId  # noqa: F401  (kept for clarity of sub ids)
from pyrogram import Client, filters

import database as db
import guards
import richmsg
import search_engine as engine
import sessions
import settings
import texts
from config import Config
from richmsg import Btn
from utils import mention, norm, series_key

IGNORE = {
    "hello", "hii", "hiii", "hey", "heyy", "thanks", "thank you", "thankyou", "okay", "yes", "yeah", "good morning",
    "good night", "good evening", "welcome", "bye", "lol", "haha", "nice", "wow", "ok", "kaise ho", "kya hal hai",
}


def file_link(fid: str) -> str:
    return f"https://t.me/{Config.BOT_USERNAME}?start=f_{fid}"


def _request_row():
    link = settings.get("request_link")
    return [[Btn("📝 Request Story", url=link, style="primary")]] if link else []


def _results_view(sid: str, s: dict, page: int):
    size = int(settings.get("page_size"))
    pages = max(1, math.ceil(len(s["hits"]) / size))
    page = max(0, min(page, pages - 1))
    chunk = s["hits"][page * size:(page + 1) * size]
    text = texts.results(s["q"], len(s["hits"]), s["uhtml"], chunk, page * size, page, pages, file_link, int(settings.get("del_search")))
    rows = []
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(Btn("⬅️ Back", cb=f"pg:{sid}:{page - 1}", style="primary"))
        nav.append(Btn(f"📄 {page + 1}/{pages}", cb="noop", style="primary"))
        if page < pages - 1:
            nav.append(Btn("Next ➡️", cb=f"pg:{sid}:{page + 1}", style="primary"))
        rows.append(nav)
    rows.append([Btn("🔔 Subscribe Updates", cb=f"sub:{sid}", style="success")])
    rows += _request_row()
    return text, rows


async def _send_results(client, chat_id, q, hits, uid, uhtml, reply_to):
    sid = sessions.create({"q": q, "hits": [(h["_id"], h["name"]) for h in hits], "uid": uid, "uhtml": uhtml, "reply_to": reply_to})
    text, rows = _results_view(sid, sessions.get(sid), 0)
    mid = await richmsg.send(client, chat_id, text, rows, reply_to=reply_to)
    await db.schedule_delete(chat_id, mid, settings.get("del_search"))


async def respond(client, message, q: str, group: bool) -> bool:
    user = message.from_user
    uhtml = mention(user)
    reply_to = message.id if group else None
    res = await engine.search(q)
    await db.log_event("search", user.id)

    if res["mode"] == "direct":
        await _send_results(client, message.chat.id, q, res["hits"], user.id, uhtml, reply_to)
        return True

    if res["mode"] == "suggest":
        sid = sessions.create({"q": q, "sugs": res["sugs"], "uid": user.id, "uhtml": uhtml, "reply_to": reply_to})
        rows = [[Btn(f"📖 {t[:45]}", cb=f"sg:{sid}:{i}", style="primary")] for i, t in enumerate(res["sugs"])]
        rows += _request_row()
        secs = int(settings.get("del_suggest"))
        mid = await richmsg.send(client, message.chat.id, texts.nomatch(q, uhtml, True, secs), rows, reply_to=reply_to)
        await db.schedule_delete(message.chat.id, mid, secs)
        return True

    if group and not settings.get("reply_nomatch"):
        return False  # stay quiet in groups when nothing resembles a story
    secs = int(settings.get("del_suggest"))
    mid = await richmsg.send(client, message.chat.id, texts.nomatch(q, uhtml, False, secs), _request_row(), reply_to=reply_to)
    await db.schedule_delete(message.chat.id, mid, secs)
    return True


# ---- private chat ----
@Client.on_message(filters.private & filters.text & ~filters.regex(r"^/"), group=1)
async def on_pm_query(client, message):
    q = message.text.strip()
    if len(q) < 2:
        return
    c = guards.cooldown(message.from_user.id)
    if c != "ok":
        return
    await respond(client, message, q, group=False)


# ---- groups ----
@Client.on_message(filters.group & filters.text & ~filters.regex(r"^/") & ~filters.bot, group=1)
async def on_group_query(client, message):
    if not message.from_user or db.is_connected(message.chat.id):
        return
    q = message.text.strip()
    if not (int(settings.get("group_min_len")) <= len(q) <= 80) or q.lower() in IGNORE:
        return
    if guards.cooldown(message.from_user.id) != "ok":
        return
    if await respond(client, message, q, group=True) and settings.get("del_query"):
        await db.schedule_delete(message.chat.id, message.id, settings.get("del_search"))  # needs delete right


# ---- pagination ----
@Client.on_callback_query(filters.regex(r"^pg:"))
async def paginate(client, cq):
    try:
        _, sid, page = cq.data.split(":")
        page = int(page)
    except ValueError:
        return await cq.answer()
    s = sessions.get(sid)
    if not s:
        return await cq.answer("⌛ This search expired. Please search again.", show_alert=True)
    if cq.from_user.id != s["uid"]:
        return await cq.answer("This is someone else's search 🙂 Send your own!", show_alert=True)
    text, rows = _results_view(sid, s, page)
    await richmsg.edit(cq.message, text, rows)
    await cq.answer()


# ---- "Did you mean?" suggestion tapped ----
@Client.on_callback_query(filters.regex(r"^sg:"))
async def pick_suggestion(client, cq):
    try:
        _, sid, i = cq.data.split(":")
        s = sessions.get(sid)
        title = s["sugs"][int(i)]
    except (ValueError, IndexError, TypeError):
        return await cq.answer("⌛ Expired. Please search again.", show_alert=True)
    if cq.from_user.id != s["uid"]:
        return await cq.answer("This is someone else's search 🙂 Send your own!", show_alert=True)
    res = await engine.search(title)
    if res["mode"] != "direct":
        return await cq.answer("No files found for that right now.", show_alert=True)
    await cq.answer()
    try:
        await cq.message.delete()
    except Exception:
        pass
    await _send_results(client, cq.message.chat.id, title, res["hits"], s["uid"], s["uhtml"], s.get("reply_to"))


# ---- Subscribe Updates ----
@Client.on_callback_query(filters.regex(r"^sub:"))
async def subscribe(client, cq):
    s = sessions.get(cq.data[4:])
    if not s:
        return await cq.answer("⌛ Expired. Please search again.", show_alert=True)
    title = series_key(s["hits"][0][1]) if s.get("hits") else s["q"]
    new = await db.add_sub(cq.from_user.id, norm(title), title)
    if new:
        await cq.answer(f"🔔 Subscribed to “{title[:40]}”. Make sure you have started the bot in private chat.", show_alert=True)
    else:
        await cq.answer("You are already subscribed to this one ✅", show_alert=True)


@Client.on_callback_query(filters.regex(r"^unsub:"))
async def unsubscribe(client, cq):
    await db.remove_sub(cq.data[6:])
    await cq.answer("🔕 Unsubscribed", show_alert=True)
