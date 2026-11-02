"""/settings - every option of the bot, changed live with rich buttons (saved in MongoDB)."""
import logging
import re

from pyrogram import Client, filters

import richmsg
import settings
from config import Config
from richmsg import Btn
from utils import esc

log = logging.getLogger("settings")
ADMIN = filters.user(Config.ADMINS) & filters.private
_pending = {}  # admin id -> {"key": setting key or None (= add force-sub channel), "chat", "mid", "group"}


def _is_admin(cq) -> bool:
    return cq.from_user.id in Config.ADMINS


def main_view():
    items = list(settings.GROUPS.items())
    rows = [
        [Btn(title, cb=f"st:{g}", style="primary") for g, (title, _) in items[i:i + 2]]
        for i in range(0, len(items), 2)
    ]
    rows.append([Btn("✖ Close", cb="stx", style="danger")])
    return "⚙️ <b>BOT SETTINGS</b>\nEverything here changes live - no redeploy needed.\n👇 <i>Pick a section</i>", rows


def group_view(g: str, note: str = ""):
    title, keys = settings.GROUPS[g]
    lines, rows = [f"<b>{title}</b>", "━━━━━━━━━━━━━━━━━━"], []
    for k in keys:
        e = settings.ENTRY[k]
        v = settings.get(k)
        lines.append(f"◉ <b>{esc(e['label'])}:</b> <code>{esc(settings.display(e))}</code>")
        if e["type"] == "bool":
            rows.append([Btn(f"{e['label']}: {'ON ✅' if v else 'OFF ❌'}", cb=f"stt:{k}", style="success" if v else "danger")])
        elif e["type"] == "choice":
            rows.append([Btn(f"🔁 {e['label']}: {v}", cb=f"stc:{k}", style="primary")])
        else:
            rows.append([Btn(f"✏️ {e['label']}", cb=f"ste:{k}", style="primary")])
    if g == "fs":
        chans = settings.get("fsub_channels") or []
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append("<b>Channels</b> (tap the mode to switch normal ⇄ request-to-join)" if chans else "<b>Channels:</b> none yet")
        for i, ch in enumerate(chans):
            rows.append([
                Btn(f"{ch.get('title', ch['chat_id'])[:22]} • {ch.get('mode', 'normal')}", cb=f"fsm:{i}", style="primary"),
                Btn("🗑", cb=f"fsd:{i}", style="danger"),
            ])
        rows.append([Btn("➕ Add channel", cb="fsa", style="success")])
    rows.append([Btn("⬅️ Back", cb="st:main", style="primary")])
    if note:
        lines.insert(2, note)
    return "\n".join(lines), rows


async def _show(msg, g: str, note: str = ""):
    text, rows = main_view() if g == "main" else group_view(g, note)
    await richmsg.edit(msg, text, rows)


@Client.on_message(filters.command("settings") & ADMIN)
async def settings_cmd(client, message):
    text, rows = main_view()
    await richmsg.send(client, message.chat.id, text, rows)


@Client.on_callback_query(filters.regex(r"^st:"))
async def open_group(client, cq):
    if not _is_admin(cq):
        return await cq.answer("Admins only.", show_alert=True)
    _pending.pop(cq.from_user.id, None)
    await _show(cq.message, cq.data[3:])
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^stx$"))
async def close(client, cq):
    if _is_admin(cq):
        _pending.pop(cq.from_user.id, None)
        try:
            await cq.message.delete()
        except Exception:
            pass
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^stt:"))
async def toggle(client, cq):
    if not _is_admin(cq):
        return await cq.answer("Admins only.", show_alert=True)
    e = settings.ENTRY[cq.data[4:]]
    await settings.set(e["key"], not settings.get(e["key"]))
    await _show(cq.message, e["group"])
    await cq.answer("Saved")


@Client.on_callback_query(filters.regex(r"^stc:"))
async def cycle(client, cq):
    if not _is_admin(cq):
        return await cq.answer("Admins only.", show_alert=True)
    e = settings.ENTRY[cq.data[4:]]
    opts = e["options"]
    await settings.set(e["key"], opts[(opts.index(settings.get(e["key"])) + 1) % len(opts)] if settings.get(e["key"]) in opts else opts[0])
    await _show(cq.message, e["group"])
    await cq.answer("Saved")


@Client.on_callback_query(filters.regex(r"^ste:"))
async def ask_value(client, cq):
    if not _is_admin(cq):
        return await cq.answer("Admins only.", show_alert=True)
    e = settings.ENTRY[cq.data[4:]]
    _pending[cq.from_user.id] = {"key": e["key"], "chat": cq.message.chat.id, "mid": cq.message.id, "group": e["group"]}
    text = (
        f"✏️ <b>{esc(e['label'])}</b>\n"
        f"Current: <code>{esc(settings.display(e))}</code>\n"
        f"{e.get('hint', '')}\n"
        f"{'Time examples: <code>30s</code> <code>15m</code> <code>1h</code> <code>1d</code> (a plain number = seconds)' if e['type'] == 'dur' else ''}\n\n"
        "👇 <i>Send the new value now</i> (<code>-</code> clears it)"
    )
    await richmsg.edit(cq.message, text, [[Btn("❌ Cancel", cb=f"st:{e['group']}", style="danger")]])
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^fsa$"))
async def ask_channel(client, cq):
    if not _is_admin(cq):
        return await cq.answer("Admins only.", show_alert=True)
    _pending[cq.from_user.id] = {"key": None, "chat": cq.message.chat.id, "mid": cq.message.id, "group": "fs"}
    text = "➕ <b>Add force-sub channel</b>\nSend the channel ID like <code>-1001234567890</code>.\nThe bot must be <b>admin</b> there."
    await richmsg.edit(cq.message, text, [[Btn("❌ Cancel", cb="st:fs", style="danger")]])
    await cq.answer()


@Client.on_callback_query(filters.regex(r"^fs[md]:"))
async def channel_edit(client, cq):
    if not _is_admin(cq):
        return await cq.answer("Admins only.", show_alert=True)
    action, idx = cq.data[:3], int(cq.data[4:])
    chans = list(settings.get("fsub_channels") or [])
    if idx >= len(chans):
        return await cq.answer("Not found", show_alert=True)
    if action == "fsd":
        chans.pop(idx)
    else:
        chans[idx] = dict(chans[idx], mode="request" if chans[idx].get("mode") != "request" else "normal")
    await settings.set("fsub_channels", chans)
    await _show(cq.message, "fs")
    await cq.answer("Saved")


async def _apply(client, message, p):
    """Save what the admin typed. (Runs before stop_propagation, which raises and ends the handler.)"""
    raw = message.text.strip()
    try:
        await message.delete()  # the value may be an API key
    except Exception:
        pass

    async def back(note):
        await richmsg.edit_id(client, p["chat"], p["mid"], *group_view(p["group"], note))

    if raw.lower() == "cancel":
        _pending.pop(message.from_user.id, None)
        return await back("")

    if p["key"] is None:  # add a force-sub channel
        if not re.fullmatch(r"-?\d+", raw):
            return await back("❌ Send a channel ID like <code>-1001234567890</code>.")
        try:
            chat = await client.get_chat(int(raw))
        except Exception as e:
            return await back(f"❌ Can't open that channel: <code>{esc(str(e)[:80])}</code>")
        chans = list(settings.get("fsub_channels") or [])
        if any(c["chat_id"] == chat.id for c in chans):
            return await back("ℹ️ Already added.")
        chans.append({"chat_id": chat.id, "title": chat.title or str(chat.id), "mode": "normal", "link": ""})
        await settings.set("fsub_channels", chans)
        _pending.pop(message.from_user.id, None)
        return await back(f"✅ <b>Saved!</b> Added <b>{esc(chat.title)}</b>")

    e = settings.ENTRY[p["key"]]
    ok, val = settings.parse_input(e, raw)
    if not ok:
        return await back(f"❌ {val}")
    await settings.set(e["key"], val)
    _pending.pop(message.from_user.id, None)
    await back(f"✅ <b>Saved!</b> {esc(e['label'])} = <code>{esc(settings.display(e))}</code>")


# group=-3: runs before the normal handlers; only reacts while this admin has an edit pending
@Client.on_message(ADMIN & filters.text & ~filters.regex(r"^/"), group=-3)
async def receive_value(client, message):
    p = _pending.get(message.from_user.id)
    if not p:
        return
    try:
        await _apply(client, message, p)
    except Exception:
        log.exception("saving a setting failed")
    message.stop_propagation()  # raises StopPropagation: keeps the value away from the normal search handler
