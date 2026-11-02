"""Verification: tokens, shortener steps, access time, bypass protection and the /go/<token> server page."""
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


def access(user: dict, ts: float = None):
    """-> (has access, valid until, tier). tier 2 = long free time, 1 = until midnight, 0 = none."""
    ts = ts or time.time()
    v1, v2 = (user or {}).get("v1_until", 0), (user or {}).get("v2_until", 0)
    return max(v1, v2) > ts, max(v1, v2), (2 if v2 > ts else 1 if v1 > ts else 0)


def grant_fields(stage: int, ts: float, tz_min: int, free_secs: int) -> dict:
    """Stage 1 = one verification: valid until 11:59 PM, resets at 12:00 AM. Stage 2 = long free time."""
    if stage == 1:
        return {"v1_until": next_midnight(ts, tz_min)}
    return {"v2_until": ts + int(free_secs)}


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
    """-> (status, token doc). status: ok | missing | notyours | used | expired | fast"""
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
    await db.set_user(uid, grant_fields(doc["stage"], ts, settings.get("tz_offset"), settings.get("v2_free")))
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
