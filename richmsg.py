"""Rich Messages (buttons inside the message bubble) with automatic fallback.

Describe buttons once as Btn objects. richmsg.send / richmsg.edit render them as
  1) a Telegram Rich Message (sendRichMessage / editMessageText + rich_message), and
  2) if Telegram refuses that for any reason, a normal message with normal inline buttons.
Set RICH_BUTTONS=0 in the environment to switch the rich look off completely.

Mini App (web_app) buttons are not available in the HTML form, so a message that has one
is sent in Telegram's native "blocks" form instead (paragraphs + a buttons block).
"""
import html
import logging
from collections import OrderedDict
from html.parser import HTMLParser

import aiohttp
from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from compat import NOPREVIEW, reply_kw
from config import Config

log = logging.getLogger("richmsg")
API = f"https://api.telegram.org/bot{Config.BOT_TOKEN}"
_session = None


class Btn:
    """style: None | 'primary' (blue) | 'success' (green) | 'danger' (red)
    Exactly one of cb / url / web_app is used."""

    def __init__(self, text: str, cb: str = None, url: str = None, style: str = None, web_app: str = None):
        self.text, self.cb, self.url, self.style, self.web_app = text, cb, url, style, web_app


# ---------- remember what we sent (admin messages get edited later: "Added by ...") ----------
_texts = OrderedDict()


def remember(chat_id: int, message_id: int, text: str):
    _texts[(chat_id, message_id)] = text
    while len(_texts) > 2000:
        _texts.popitem(last=False)


def cached(chat_id: int, message_id: int):
    return _texts.get((chat_id, message_id))


def text_of(msg) -> str:
    """HTML text of a bot message: what we sent, else what Telegram gives us, else ''."""
    c = _texts.get((msg.chat.id, msg.id))
    if c is not None:
        return c
    try:
        t = msg.text or msg.caption
        return t.html if t else ""
    except Exception:
        return ""


# ---------- HTML form ----------
def body_html(text: str) -> str:
    """texts.py messages are HTML with newlines; rich HTML needs one <p> per line.
    Lines that already are a <blockquote> block are passed through as they are."""
    out = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        out.append(line if line.lstrip().startswith("<blockquote") else f"<p>{line}</p>")
    return "".join(out)


def _btn_html(b: Btn) -> str:
    st = f' style="{b.style}"' if b.style else ""
    label = html.escape(b.text)
    if b.url:
        return f'<tg-button type="url"{st} url="{html.escape(b.url, quote=True)}">{label}</tg-button>'
    return f'<tg-button type="callback_data"{st} data="{html.escape(b.cb or "noop", quote=True)}">{label}</tg-button>'


def rows_html(rows: list) -> str:
    return "".join("<tg-button-row>" + "".join(_btn_html(b) for b in r) + "</tg-button-row>" for r in rows if r)


# ---------- native blocks form (needed for web_app buttons) ----------
_TAGS = {"b": "bold", "strong": "bold", "i": "italic", "em": "italic", "u": "underline", "ins": "underline",
         "s": "strikethrough", "del": "strikethrough", "code": "code", "tg-spoiler": "spoiler"}


class _RichText(HTMLParser):
    """Turns the few inline tags we use (b i u s code a) into Telegram RichText objects."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.meta = [[]], []

    def handle_starttag(self, tag, attrs):
        if tag in _TAGS or tag == "a":
            self.stack.append([])
            self.meta.append((tag, dict(attrs)))

    def _close(self):
        children = self.stack.pop()
        tag, attrs = self.meta.pop()
        if tag == "a" and attrs.get("href"):
            node = {"type": "url", "text": children or [""], "url": attrs["href"]}
        elif tag in _TAGS:
            node = {"type": _TAGS[tag], "text": children or [""]}
        else:
            self.stack[-1].extend(children)
            return
        self.stack[-1].append(node)

    def handle_endtag(self, tag):
        if self.meta and self.meta[-1][0] == tag:
            self._close()

    def handle_data(self, data):
        self.stack[-1].append(data)


def html_to_richtext(s: str) -> list:
    p = _RichText()
    p.feed(s)
    p.close()
    while p.meta:
        p._close()
    return p.stack[0] or [""]


def _btn_native(b: Btn) -> dict:
    d = {"text": b.text}
    if b.style:
        d["style"] = b.style
    if b.web_app:
        d["web_app"] = {"url": b.web_app}
    elif b.url:
        d["url"] = b.url
    else:
        d["callback_data"] = b.cb or "noop"
    return d


def blocks_payload(text: str, rows: list) -> dict:
    out = [{"type": "paragraph", "text": html_to_richtext(line)} for line in text.split("\n") if line.strip()]
    for r in rows:
        if r:
            out.append({"type": "buttons", "buttons": [_btn_native(b) for b in r][:8]})
    return {"blocks": out}


def rich_payload(text: str, rows: list) -> dict:
    if any(b.web_app for r in rows for b in r):
        return blocks_payload(text, rows)
    return {"html": body_html(text) + rows_html(rows)}


# ---------- normal inline keyboard (fallback) ----------
def markup(rows: list):
    out = []
    for r in rows or []:
        line = []
        for b in r:
            if b.web_app:
                line.append(InlineKeyboardButton(b.text, web_app=WebAppInfo(url=b.web_app)))
            elif b.url:
                line.append(InlineKeyboardButton(b.text, url=b.url))
            else:
                line.append(InlineKeyboardButton(b.text, callback_data=b.cb or "noop"))
        if line:
            out.append(line)
    return InlineKeyboardMarkup(out) if out else None


# ---------- raw Bot API ----------
async def _api(method: str, payload: dict) -> dict:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
    try:
        async with _session.post(f"{API}/{method}", json=payload) as r:
            return await r.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}


async def send(client, chat_id: int, text: str, rows: list, reply_to: int = None) -> int:
    """Send text + buttons. Returns the new message id."""
    rows = [r for r in (rows or []) if r]
    if Config.RICH_BUTTONS and rows:
        payload = {"chat_id": chat_id, "rich_message": rich_payload(text, rows)}
        if reply_to:
            payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        res = await _api("sendRichMessage", payload)
        if res.get("ok"):
            mid = res["result"]["message_id"]
            remember(chat_id, mid, text)
            return mid
        log.warning("sendRichMessage failed, using normal buttons: %s", res.get("description"))
    sent = await client.send_message(
        chat_id, text, reply_markup=markup(rows), **NOPREVIEW, **reply_kw(reply_to)
    )
    remember(chat_id, sent.id, text)
    return sent.id


async def edit_id(client, chat_id: int, message_id: int, text: str, rows: list):
    """Edit a bot message by id (Next / Back, 'Added by ...'). rows=[] removes the buttons."""
    rows = [r for r in (rows or []) if r]
    if Config.RICH_BUTTONS:
        res = await _api("editMessageText", {
            "chat_id": chat_id,
            "message_id": message_id,
            "rich_message": rich_payload(text, rows),
        })
        if res.get("ok"):
            remember(chat_id, message_id, text)
            return
        desc = str(res.get("description", ""))
        if "not modified" in desc.lower():
            return
        log.warning("rich edit failed, using normal edit: %s", desc)
    try:
        await client.edit_message_text(chat_id, message_id, text, reply_markup=markup(rows), **NOPREVIEW)
        remember(chat_id, message_id, text)
    except MessageNotModified:
        pass
    except Exception:
        log.exception("edit failed")


async def edit(msg, text: str, rows: list):
    """Edit the message a callback button was pressed on (msg = callback_query.message)."""
    await edit_id(msg._client, msg.chat.id, msg.id, text, rows)
