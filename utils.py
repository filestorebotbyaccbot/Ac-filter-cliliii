import html
import re
import time

_MULT = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(raw):
    """'90', '90s', '15m', '1h', '1d', '1d 12h' -> seconds (int) or None if not understood. 'off' -> 0."""
    raw = (raw or "").strip().lower()
    if raw in ("off", "none", "no"):
        return 0
    if not re.fullmatch(r"(?:\s*\d+\s*[smhd]?)+\s*", raw):
        return None
    return sum(int(n) * _MULT[u] for n, u in re.findall(r"(\d+)\s*([smhd]?)", raw))


def fmt_duration(sec) -> str:
    sec = int(sec or 0)
    if sec <= 0:
        return "off"
    out = []
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if sec >= size:
            out.append(f"{sec // size}{unit}")
            sec %= size
    return " ".join(out[:2])


def fmt_clock(ts: float, tz_min: int) -> str:
    return time.strftime("%I:%M %p", time.gmtime(ts + int(tz_min) * 60))


def human_size(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024


def esc(s) -> str:
    return html.escape(str(s or ""))


def mention(user) -> str:
    name = esc((user.first_name or "User")[:30])
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def mention_id(uid: int, name: str) -> str:
    return f'<a href="tg://user?id={uid}">{esc((name or "User")[:30])}</a>'


# ---------- file names ----------
_EXT = re.compile(r"\.(mp3|m4a|aac|ogg|oga|opus|wav|flac|mp4|mkv|avi|mov|webm|pdf|epub|zip|rar|7z|docx?|txt)$", re.I)
_EP = re.compile(r"(?i)\b(?:ep(?:isodes?)?|part|parts|chapter|ch|season|vol(?:ume)?)\b\.?\s*\d+(?:\s*(?:to|-|–|&|and)\s*\d+)?")
_RANGE = re.compile(r"(?i)\b\d+\s*(?:to|-|–)\s*\d+\b")


def clean_name(raw: str) -> str:
    s = _EXT.sub("", (raw or "").strip())
    s = re.sub(r"@\w+", " ", s)
    s = s.replace("_", " ")
    return " ".join(s.split()).strip(" -–|:.,") or "Untitled"


def norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"@\w+", " ", s)
    s = re.sub(r"[\._\-\[\]\(\)\{\}\|]+", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)  # \w is unicode aware, so Hindi names survive
    return " ".join(s.split())


def series_key(name: str) -> str:
    """'His Replaced Bride Ep 123 To 135' -> 'His Replaced Bride'"""
    s = clean_name(name)
    s = _EP.sub(" ", s)
    s = _RANGE.sub(" ", s)
    s = " ".join(s.split())
    s = re.sub(r"[\s\-–:|,.]+$", "", s)
    return s or clean_name(name)


def natural_key(s: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", (s or "").lower())]
