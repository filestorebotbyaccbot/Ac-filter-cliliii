"""Live settings. Every value here is edited from the bot (/settings) and saved in MongoDB."""
import re

import database as db
from utils import fmt_duration, parse_duration

S = []


def _e(group, key, label, typ, default, **kw):
    S.append(dict(group=group, key=key, label=label, type=typ, default=default, **kw))


# ---- shortener 1 / 2 ----
for n, on in ((1, True), (2, False)):
    _e(f"s{n}", f"s{n}_enabled", "Enabled", "bool", on)
    _e(f"s{n}", f"s{n}_url", "Shortener site", "text", "", hint="Domain only, e.g. <code>shortener.com</code>")
    _e(f"s{n}", f"s{n}_api", "API key", "secret", "", hint="Your API key from the shortener's panel")
    _e(f"s{n}", f"s{n}_tutorial", "Tutorial video link", "text", "", hint="Shown on the 🎥 How to verify button. <code>-</code> removes it")

# ---- verification ----
_e("vf", "verify_enabled", "Verification", "bool", True)
_e("vf", "verify_format", "Format (server = hides shortener link)", "choice", "server", options=["server", "direct"])
_e("vf", "alias_min", "Alias length (min 15)", "int", 15, min=15, max=40, hint="Random alias length for every short link. Minimum 15")
_e("vf", "v2_gap", "Gap before 2nd verification", "dur", 3600, min=60, hint="After the 1st verification the user is free for this long, then the 2nd is asked (never past 12:00 AM). e.g. <code>1h</code>")
_e("vf", "v2_free", "Valid time after 2nd verification", "dur", 86400, min=60, hint="Free time after the 2nd verification. e.g. <code>1d</code>, <code>12h</code>, <code>1h</code>")
_e("vf", "verify_gap", "Fastest allowed (bypass guard)", "dur", 30, min=0, hint="Finishing a verification faster than this is rejected as bypass. e.g. <code>30s</code>")
_e("vf", "token_ttl", "Verify link valid for", "dur", 900, min=60, hint="e.g. <code>15m</code>")
_e("vf", "tz_offset", "Timezone offset (minutes)", "int", 330, min=-720, max=840, hint="India = <code>330</code>. One verification resets at 12:00 AM of this timezone")

# ---- delivery ----
_e("dl", "delivery_mode", "Deliver files to", "choice", "pm", options=["pm", "channel"])
_e("dl", "delivery_channel", "Delivery channel ID", "text", "", kind="chat", hint="e.g. <code>-1001234567890</code>. Bot must be admin there. <code>-</code> clears")
_e("dl", "caption", "File caption", "text", "{name}", hint="Use <code>{name}</code> and <code>{size}</code>. HTML allowed")
_e("dl", "deliver_note", "Send 'file will be deleted' note", "bool", True)

# ---- auto delete ----
_e("ad", "del_search", "Delete search results after", "dur", 300, min=0, hint="e.g. <code>5m</code>. <code>off</code> = never")
_e("ad", "del_suggest", "Delete suggestions after", "dur", 60, min=0, hint="e.g. <code>1m</code>")
_e("ad", "del_file", "Delete delivered file after", "dur", 600, min=0, hint="e.g. <code>10m</code>")
_e("ad", "del_prompt", "Delete prompts after", "dur", 300, min=0, hint="Verification / join / info messages")
_e("ad", "del_query", "Delete user's search message (groups)", "bool", True)

# ---- force subscribe ----
_e("fs", "fsub_enabled", "Force subscribe", "bool", False)
_e("fs", "fsub_autoapprove", "Auto-approve join requests", "bool", False)

# ---- protection ----
_e("pr", "protect_content", "File protection (no forward / save)", "bool", True)

# ---- search ----
_e("se", "exact_score", "Direct-match score", "int", 85, min=50, max=100, hint="Results at or above this are shown as a direct match")
_e("se", "min_score", "Suggestion score", "int", 55, min=30, max=95, hint="Below this = nothing found")
_e("se", "page_size", "Results per page", "int", 5, min=1, max=10)
_e("se", "suggest_count", "Max suggestions", "int", 5, min=1, max=8)
_e("se", "max_results", "Max results per search", "int", 30, min=5, max=100)
_e("se", "reply_nomatch", "Reply when nothing matches (groups)", "bool", False)
_e("se", "group_min_len", "Min query length (groups)", "int", 4, min=2, max=20)

# ---- links ----
_e("ln", "request_link", "Request Story link", "text", "", hint="Group / channel / bot link. <code>-</code> removes the button")
_e("ln", "updates_link", "Updates channel link", "text", "", hint="Shown on the welcome message")

GROUPS = {
    "s1": ("🔗 Shortener 1", [e["key"] for e in S if e["group"] == "s1"]),
    "s2": ("🔗 Shortener 2", [e["key"] for e in S if e["group"] == "s2"]),
    "vf": ("🛡 Verification", [e["key"] for e in S if e["group"] == "vf"]),
    "dl": ("📦 Delivery", [e["key"] for e in S if e["group"] == "dl"]),
    "ad": ("🗑 Auto-delete", [e["key"] for e in S if e["group"] == "ad"]),
    "fs": ("🔔 Force-sub", [e["key"] for e in S if e["group"] == "fs"]),
    "pr": ("🔒 Protection", [e["key"] for e in S if e["group"] == "pr"]),
    "se": ("🔎 Search", [e["key"] for e in S if e["group"] == "se"]),
    "ln": ("📢 Links", [e["key"] for e in S if e["group"] == "ln"]),
}
ENTRY = {e["key"]: e for e in S}
DEFAULTS = {e["key"]: e["default"] for e in S}
DEFAULTS["fsub_channels"] = []  # [{chat_id, title, mode: normal|request, link}] - managed in the Force-sub panel

_cache = dict(DEFAULTS)


async def load():
    doc = await db.settings_get()
    _cache.clear()
    _cache.update(DEFAULTS)
    for k, v in (doc or {}).items():
        if k in DEFAULTS:
            _cache[k] = v


def get(key):
    return _cache.get(key, DEFAULTS.get(key))


async def set(key, value):  # noqa: A001
    _cache[key] = value
    await db.settings_set(key, value)


def display(e) -> str:
    v = get(e["key"])
    t = e["type"]
    if t == "bool":
        return "ON ✅" if v else "OFF ❌"
    if t == "dur":
        return fmt_duration(v)
    if t == "secret":
        return f"••••{str(v)[-4:]}" if v else "—"
    return str(v) if v not in ("", None) else "—"


def parse_input(e, raw: str):
    """-> (True, value) or (False, error text)"""
    raw = (raw or "").strip()
    t = e["type"]
    if t == "int":
        try:
            v = int(raw)
        except ValueError:
            return False, "Send a whole number."
    elif t == "dur":
        v = parse_duration(raw)
        if v is None:
            return False, "Send a time like <code>30s</code>, <code>15m</code>, <code>1h</code>, <code>1d</code> (or <code>off</code>)."
    else:  # text / secret
        if raw.lower() in ("-", "none", "clear"):
            return True, ""
        if e.get("kind") == "chat" and not re.fullmatch(r"-?\d+|@\w+", raw):
            return False, "Send a chat ID like <code>-1001234567890</code>."
        if not raw:
            return False, "Send a value."
        return True, raw
    lo, hi = e.get("min"), e.get("max")
    if lo is not None and v < lo:
        return False, f"Minimum is {fmt_duration(lo) if t == 'dur' else lo}."
    if hi is not None and v > hi:
        return False, f"Maximum is {hi}."
    return True, v
