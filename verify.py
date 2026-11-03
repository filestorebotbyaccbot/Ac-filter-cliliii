"""Verification: tokens, 1/2 + 2/2 steps, free-time rules, bypass protection and the /go/<token> server page.

Rules
- Verification 1 is asked straight away. After it the user is free for the GAP time (setting `v2_gap`), never past 12:00 AM.
- When the gap is over (same day) Verification 2 is asked. After it the user is free for the VALID time (`v2_free`).
- If only Verification 1 was done today, it is forgotten at 12:00 AM: the user starts again from 1/2, even days later.
- With a single shortener: one verification = free until 11:59 PM.
"""
import html
import logging
import secrets
import time

from aiohttp import web

import database as db
import settings
import shortener
from config import Config

log = logging.getLogger("verify")
_BOTS = ("TelegramBot", "WhatsApp", "facebookexternalhit", "Twitterbot", "Slackbot", "Discordbot")


def chain() -> list:
    """Shortener numbers in use, in order. [] = verification is off (or no shortener is set up)."""
    if not settings.get("verify_enabled"):
        return []
    return [n for n in (1, 2) if shortener.configured(n)]


def next_midnight(ts: float, tz_min: int) -> float:
    off = int(tz_min) * 60
    return (int(ts + off) // 86400 + 1) * 86400 - off


def state(user: dict, ts: float, tz_min: int, gap: int, two_steps: bool):
    """-> (name, free until). name: 'ok' (free until that time) | 'need1' | 'need2'"""
    user = user or {}
    v2 = user.get("v2_until", 0)
    if v2 > ts:  # long free time after Verification 2
        return "ok", v2
    v1 = user.get("v1_at", 0)
    midnight = next_midnight(v1, tz_min) if v1 else 0
    if v1 and ts < midnight:  # Verification 1 was done today
        if not two_steps:
            return "ok", midnight
        free_until = min(v1 + int(gap), midnight)
        if ts < free_until:
            return "ok", free_until
        return "need2", 0
    return "need1", 0  # nothing valid today (or it was reset at 12 AM): start again from 1/2


def current(user: dict, ts: float = None):
    return state(user, ts or time.time(), settings.get("tz_offset"), int(settings.get("v2_gap")), len(chain()) > 1)


def grant_fields(stage: int, ts: float, free_secs: int) -> dict:
    if stage == 1:
        return {"v1_at": ts}
    return {"v2_until": ts + int(free_secs), "v1_at": 0}  # after 2/2 the cycle restarts from 1/2 when the valid time ends


def dest_url(token: str) -> str:
    return f"https://t.me/{Config.BOT_USERNAME}?start=v_{token}"


async def new_token(uid: int, stage: int, file_id) -> dict:
    ch = chain()
    doc = {
        "_id": secrets.token_urlsafe(18),
        "uid": uid,
        "stage": stage,
        "sh": ch[min(stage, len(ch)) - 1],
        "file_id": file_id,
        "created": time.time(),
        "clicked": None,
        "used": False,
        "short": None,
    }
    await db.tokens_insert(doc)
    return doc


async def link_for(doc: dict):
    """The URL on the Verify button. 'server' format: our own page, so the shortener link is never shown."""
    if settings.get("verify_format") == "server" and Config.BASE_URL:
        return f"{Config.BASE_URL}/go/{doc['_id']}"
    short = await shortener.make_short(doc["sh"], dest_url(doc["_id"]))
    if short:
        await db.tokens_update(doc["_id"], {"short": short})
    return short


async def complete(uid: int, token: str):
    """-> (status, token doc). status: ok | stale | missing | notyours | used | expired | fast"""
    doc = await db.tokens_get(token)
    if not doc:
        return "missing", None
    if doc["uid"] != uid:
        return "notyours", doc
    if doc["used"]:
        return "used", doc
    ts = time.time()
    if ts - doc["created"] > int(settings.get("token_ttl")):
        await db.tokens_use(token, ts)
        return "expired", doc
    started = doc.get("clicked") or doc["created"]
    if ts - started < int(settings.get("verify_gap")):  # finished faster than a human can = bypass
        await db.tokens_use(token, ts)
        await db.log_event("bypass", uid)
        return "fast", doc
    if not await db.tokens_use(token, ts):
        return "used", doc
    name, _ = current(await db.get_user(uid), ts)
    if name != f"need{doc['stage']}":  # already verified at this step (older link): don't extend the free time
        return "stale", doc
    await db.set_user(uid, grant_fields(doc["stage"], ts, settings.get("v2_free")))
    await db.log_event(f"verify{doc['stage']}", uid)
    return "ok", doc


# ---------- web page: /go/<token> ----------
def _page(title: str, msg: str, status: int):
    body = (
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title>"
        "<body style='font-family:sans-serif;text-align:center;padding:48px 20px'>"
        f"<h2>{html.escape(title)}</h2><p>{html.escape(msg)}</p></body>"
    )
    return web.Response(text=body, content_type="text/html", status=status)


async def go(request):
    token = request.match_info["token"]
    if request.method == "HEAD" or any(b in request.headers.get("User-Agent", "") for b in _BOTS):
        return web.Response(text="ok")  # link-preview crawlers must not start the verification clock
    doc = await db.tokens_get(token)
    ts = time.time()
    if not doc or doc.get("used") or ts - doc["created"] > int(settings.get("token_ttl")):
        return _page("Link expired", "This link has expired or was already used. Go back to the bot and tap Verify again.", 410)
    short = doc.get("short")
    if not short:
        short = await shortener.make_short(doc["sh"], dest_url(token))
        if not short:
            return _page("Try again", "Verification is temporarily unavailable. Please try again in a minute.", 503)
        await db.tokens_update(token, {"short": short})
    await db.tokens_mark_click(token, ts)
    raise web.HTTPFound(location=short)


def routes(app: web.Application):
    app.router.add_get("/go/{token}", go)
