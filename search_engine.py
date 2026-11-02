"""Typo-tolerant file search (RapidFuzz). Handles 'his replaced wife' -> 'His Replaced Bride' style mistakes."""
from rapidfuzz import fuzz, process

import database as db
import settings
from utils import norm, natural_key, series_key

_state = {"src": None, "names": None}


def _names(index):
    if _state["src"] is not index:
        _state["src"], _state["names"] = index, [norm(x["name"]) for x in index]
    return _state["names"]


def _score(qn: str, tn: str) -> float:
    base = fuzz.WRatio(qn, tn)
    if len(qn.split()) >= 2:  # "his replaced bride" fully inside "... ep 123 to 135"
        base = max(base, 0.97 * fuzz.token_set_ratio(qn, tn))
    return base


def matches(key_norm: str, file_name: str) -> bool:
    """Does a new file belong to a 'Subscribe Updates' key?"""
    return bool(key_norm) and fuzz.token_set_ratio(key_norm, norm(file_name)) >= 90


async def search(q: str) -> dict:
    """-> {'mode': 'direct' | 'suggest' | 'none', 'hits': [file docs], 'sugs': [series titles]}"""
    out = {"mode": "none", "hits": [], "sugs": []}
    index = await db.get_index()
    qn = norm(q)
    if not index or not qn:
        return out
    names = _names(index)
    exact, floor = int(settings.get("exact_score")), int(settings.get("min_score"))

    cand = set()
    for scorer in (fuzz.WRatio, fuzz.token_set_ratio):
        for _, _, i in process.extract(qn, names, scorer=scorer, limit=300, score_cutoff=max(30, floor - 15)):
            cand.add(i)
    scored = sorted(((i, _score(qn, names[i])) for i in cand), key=lambda x: x[1], reverse=True)
    scored = [(i, s) for i, s in scored if s >= floor]
    if not scored:
        return out

    direct = [(index[i], s) for i, s in scored if s >= exact][: int(settings.get("max_results"))]
    if direct:
        direct.sort(key=lambda x: natural_key(x[0]["name"]), reverse=True)  # newest episodes first
        direct.sort(key=lambda x: -(int(x[1]) // 5))                       # stable: best score bucket first
        out["mode"], out["hits"] = "direct", [d for d, _ in direct]
        return out

    seen = []
    for i, _ in scored:
        title = series_key(index[i]["name"])
        if norm(title) not in [norm(t) for t in seen]:
            seen.append(title)
        if len(seen) >= int(settings.get("suggest_count")):
            break
    out["mode"], out["sugs"] = "suggest", seen
    return out
