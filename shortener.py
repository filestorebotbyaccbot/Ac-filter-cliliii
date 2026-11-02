"""Short-link maker for AdLinkFly-style shorteners:  GET https://site/api?api=KEY&url=URL&alias=ALIAS"""
import json
import logging
import random
import string

import aiohttp

import settings

log = logging.getLogger("shortener")
_ALNUM = string.ascii_letters + string.digits


def make_alias() -> str:
    n = max(15, int(settings.get("alias_min") or 15))  # never shorter than 15
    return "".join(random.choices(_ALNUM, k=random.randint(n, n + 4)))


def configured(n: int) -> bool:
    return bool(settings.get(f"s{n}_enabled") and settings.get(f"s{n}_url") and settings.get(f"s{n}_api"))


def _base(url: str) -> str:
    u = url.strip().rstrip("/")
    return u if u.startswith("http") else "https://" + u


async def _call(base: str, api: str, dest: str, alias):
    params = {"api": api, "url": dest, "format": "json"}
    if alias:
        params["alias"] = alias
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
        async with s.get(f"{base}/api", params=params) as r:
            text = await r.text()
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        short = data.get("shortenedUrl") or data.get("short_url") or data.get("shortlink") or data.get("result_url")
        if short and str(data.get("status", "success")).lower() != "error":
            return short, None
        return None, str(data.get("message") or data.get("error") or data)[:200]
    t = text.strip()
    if t.startswith("http"):
        return t.split()[0], None
    return None, t[:200]


async def make_short(n: int, dest: str):
    """Short link for `dest` using shortener n, with a random 15+ character alias. None if it failed."""
    base, api = _base(settings.get(f"s{n}_url")), settings.get(f"s{n}_api")
    for alias in (make_alias(), make_alias(), None):  # last try without alias if the site refuses custom aliases
        try:
            short, err = await _call(base, api, dest, alias)
        except Exception as e:  # network / timeout
            short, err = None, str(e)
        if short:
            if alias is None:
                log.warning("shortener %s gave a link without our alias (site may not support aliases)", n)
            return short
        log.warning("shortener %s failed (alias=%s): %s", n, bool(alias), err)
    return None
