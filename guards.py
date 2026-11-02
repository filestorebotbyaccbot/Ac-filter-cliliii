"""Per-user cooldown so nobody can spam searches."""
import time

from config import Config

_last, _warned = {}, {}


def cooldown(uid: int, key: str = "search", seconds: float = 3) -> str:
    """'ok' = go ahead | 'warn' = blocked, tell the user | 'silent' = blocked, say nothing"""
    if uid in Config.ADMINS:
        return "ok"
    now, k = time.time(), (uid, key)
    if len(_last) > 20000:
        _last.clear()
        _warned.clear()
    if now - _last.get(k, 0) < seconds:
        if now - _warned.get(k, 0) > 8:
            _warned[k] = now
            return "warn"
        return "silent"
    _last[k] = now
    return "ok"
