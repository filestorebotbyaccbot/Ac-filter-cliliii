"""Small in-memory store for paginated results (buttons carry only a short id)."""
import secrets
import time

_TTL = 1800
_S = {}


def create(data: dict) -> str:
    now = time.time()
    if len(_S) > 1500:
        for k in [k for k, v in _S.items() if v["_exp"] < now]:
            _S.pop(k, None)
    sid = secrets.token_urlsafe(5)
    _S[sid] = dict(data, _exp=now + _TTL)
    return sid


def get(sid: str):
    s = _S.get(sid)
    if not s or s["_exp"] < time.time():
        _S.pop(sid, None)
        return None
    return s
