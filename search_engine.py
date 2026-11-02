"""Typo-tolerant file search (RapidFuzz).

direct   = every word of the query is really in the file name (typos allowed) and the score is high
suggest  = "Did you mean?": whole series (all episodes of that story), never a loose pile of random files
"""
from rapidfuzz import fuzz, process

import database as db
import settings
from utils import norm, natural_key, series_key

_STOP = {"the", "a", "an", "of", "and", "in", "to", "for", "my", "ki", "ka", "ke", "aur", "hai", "se", "ko", "me", "mein", "ek", "is"}
_state = {"src": None, "names": None, "skeys": None, "groups": None}


def _prep(index):
    if _state["src"] is not index:
        names = [norm(x["name"]) for x in index]
        skeys = [norm(series_key(x["name"])) for x in index]
        groups = {}
        for i, k in enumerate(skeys):
            groups.setdefault(k, []).append(i)
        _state.update(src=index, names=names, skeys=skeys, groups=groups)
    return _state["names"], _state["skeys"], _state["groups"]


def _score(qn: str, tn: str) -> float:
    base = fuzz.WRatio(qn, tn)
    if len(qn.split()) >= 2:  # "his replaced bride" fully inside "... ep 123 to 135"
        base = max(base, 0.97 * fuzz.token_set_ratio(qn, tn))
    return base


def _coverage(qwords: list, name: str) -> float:
    """Share of the typed words that appear in the file name (typos allowed)."""
    if not qwords:
        return 1.0
    words = name.split()
    hit = sum(1 for w in qwords if any(fuzz.ratio(w, t) >= 80 for t in words))
    return hit / len(qwords)


def matches(key_norm: str, file_name: str) -> bool:
    """Does a new file belong to a 'Subscribe Updates' key?"""
    return bool(key_norm) and fuzz.token_set_ratio(key_norm, norm(file_name)) >= 90


async def search(q: str) -> dict:
    """-> {'mode': 'direct'|'suggest'|'none', 'hits': [file docs], 'sugs': [{'title', 'files': [(id, name)]}]}"""
    out = {"mode": "none", "hits": [], "sugs": []}
    index = await db.get_index()
    qn = norm(q)
    if not index or not qn:
        return out
    names, skeys, groups = _prep(index)
    qwords = [w for w in qn.split() if w not in _STOP] or qn.split()
    exact, floor = int(settings.get("exact_score")), int(settings.get("min_score"))

    cand = set()
    for scorer in (fuzz.WRatio, fuzz.token_set_ratio):
        for _, _, i in process.extract(qn, names, scorer=scorer, limit=300, score_cutoff=max(30, floor - 15)):
            cand.add(i)
    scored = [(i, _score(qn, names[i]), _coverage(qwords, names[i])) for i in cand]
    scored = sorted(((i, s, c) for i, s, c in scored if s >= floor), key=lambda x: x[1], reverse=True)
    if not scored:
        return out

    direct = [(index[i], s) for i, s, c in scored if s >= exact and c >= 0.99][: int(settings.get("max_results"))]
    if direct:
        direct.sort(key=lambda x: natural_key(x[0]["name"]), reverse=True)  # newest episodes first
        direct.sort(key=lambda x: -(int(x[1]) // 5))                       # stable: best score bucket first
        out["mode"], out["hits"] = "direct", [d for d, _ in direct]
        return out

    seen = set()
    for i, _, c in scored:
        k = skeys[i]
        if c < 0.5 or k in seen:  # less than half of the words match = not a real suggestion
            continue
        seen.add(k)
        files = sorted((index[j] for j in groups[k]), key=lambda d: natural_key(d["name"]), reverse=True)
        out["sugs"].append({"title": series_key(index[i]["name"]), "files": [(d["_id"], d["name"]) for d in files]})
        if len(out["sugs"]) >= int(settings.get("suggest_count")):
            break
    if out["sugs"]:
        out["mode"] = "suggest"
    return out
