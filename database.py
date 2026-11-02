import time
from datetime import datetime, timedelta

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from config import Config

files = users = tokens = deletions = subs = joinreq = events = channels = bans = settings_c = None
_cache = {"data": [], "dirty": True, "ts": 0.0}
_channel_ids = set()
_banned = set()


async def setup():
    global files, users, tokens, deletions, subs, joinreq, events, channels, bans, settings_c
    db = AsyncIOMotorClient(Config.MONGO_URI)[Config.DB_NAME]
    files, users, tokens, deletions = db.files, db.users, db.tokens, db.deletions
    subs, joinreq, events, channels, bans, settings_c = db.subs, db.joinreq, db.events, db.channels, db.bans, db.settings
    await files.create_index("file_unique_id")
    await files.create_index("chat_id")
    await tokens.create_index("created_dt", expireAfterSeconds=3 * 86400)
    await deletions.create_index("due")
    await events.create_index("ts", expireAfterSeconds=45 * 86400)
    await joinreq.create_index([("chat_id", 1), ("user_id", 1)], unique=True)
    await subs.create_index([("uid", 1), ("key", 1)], unique=True)
    await refresh_channels()
    await refresh_bans()


# ---------- settings ----------
async def settings_get() -> dict:
    return await settings_c.find_one({"_id": "settings"}) or {}


async def settings_set(key: str, value):
    await settings_c.update_one({"_id": "settings"}, {"$set": {key: value}}, upsert=True)


# ---------- connected channels ----------
async def refresh_channels():
    _channel_ids.clear()
    async for c in channels.find({}):
        _channel_ids.add(c["_id"])


def is_connected(chat_id: int) -> bool:
    return chat_id in _channel_ids


async def add_channel(chat_id: int, title: str):
    await channels.update_one({"_id": chat_id}, {"$set": {"title": title}}, upsert=True)
    _channel_ids.add(chat_id)


async def remove_channel(chat_id: int, purge: bool = False) -> int:
    await channels.delete_one({"_id": chat_id})
    _channel_ids.discard(chat_id)
    removed = 0
    if purge:
        removed = (await files.delete_many({"chat_id": chat_id})).deleted_count
        _cache["dirty"] = True
    return removed


async def list_channels():
    return [c async for c in channels.find({})]


# ---------- files ----------
async def upsert_file(doc: dict):
    """True = new file, False = updated, None = duplicate of a file we already have."""
    dup = await files.find_one({"file_unique_id": doc["file_unique_id"], "_id": {"$ne": doc["_id"]}}, {"_id": 1})
    if dup:
        return None
    res = await files.update_one(
        {"_id": doc["_id"]}, {"$set": doc, "$setOnInsert": {"added_at": time.time()}}, upsert=True
    )
    _cache["dirty"] = True
    return res.upserted_id is not None


async def delete_file(fid: str) -> bool:
    res = await files.delete_one({"_id": fid})
    _cache["dirty"] = True
    return res.deleted_count > 0


async def get_file(fid: str):
    return await files.find_one({"_id": fid})


async def count_files(chat_id=None) -> int:
    return await files.count_documents({"chat_id": chat_id} if chat_id else {})


async def get_index():
    """In-memory copy of all files for fast fuzzy search (refreshed when data changes)."""
    if _cache["dirty"] or time.time() - _cache["ts"] > 300:
        _cache["data"] = [d async for d in files.find({}, {"name": 1, "size": 1, "type": 1})]
        _cache["ts"], _cache["dirty"] = time.time(), False
    return _cache["data"]


# ---------- users ----------
async def add_user(uid: int):
    await users.update_one({"_id": uid}, {"$setOnInsert": {"t": time.time()}}, upsert=True)


async def get_user(uid: int):
    return await users.find_one({"_id": uid}) or {}


async def set_user(uid: int, fields: dict):
    await users.update_one({"_id": uid}, {"$set": fields, "$setOnInsert": {"t": time.time()}}, upsert=True)


async def count_users() -> int:
    return await users.count_documents({})


async def all_user_ids():
    return [d["_id"] async for d in users.find({}, {"_id": 1})]


async def remove_user(uid: int):
    await users.delete_one({"_id": uid})


# ---------- bans ----------
async def refresh_bans():
    _banned.clear()
    async for b in bans.find({}):
        _banned.add(b["_id"])


def is_banned(uid: int) -> bool:
    return uid in _banned


async def ban_user(uid: int):
    await bans.update_one({"_id": uid}, {"$set": {"t": time.time()}}, upsert=True)
    _banned.add(uid)


async def unban_user(uid: int) -> bool:
    res = await bans.delete_one({"_id": uid})
    _banned.discard(uid)
    return res.deleted_count > 0


# ---------- verification tokens ----------
async def tokens_insert(doc: dict):
    doc["created_dt"] = datetime.utcnow()
    await tokens.insert_one(doc)


async def tokens_get(token: str):
    return await tokens.find_one({"_id": token})


async def tokens_update(token: str, fields: dict):
    await tokens.update_one({"_id": token}, {"$set": fields})


async def tokens_mark_click(token: str, ts: float):
    await tokens.update_one({"_id": token, "clicked": None}, {"$set": {"clicked": ts}})


async def tokens_use(token: str, ts: float):
    """Atomic: True only for the first caller, so a link can never be used twice."""
    doc = await tokens.find_one_and_update({"_id": token, "used": False}, {"$set": {"used": True, "used_at": ts}})
    return doc is not None


# ---------- join requests (force-sub request mode) ----------
async def add_joinreq(chat_id: int, user_id: int):
    await joinreq.update_one({"chat_id": chat_id, "user_id": user_id}, {"$set": {"t": time.time()}}, upsert=True)


async def has_joinreq(chat_id: int, user_id: int) -> bool:
    return bool(await joinreq.find_one({"chat_id": chat_id, "user_id": user_id}, {"_id": 1}))


# ---------- subscriptions ("Subscribe Updates") ----------
async def add_sub(uid: int, key: str, title: str) -> bool:
    res = await subs.update_one(
        {"uid": uid, "key": key}, {"$setOnInsert": {"q": title, "ts": time.time()}}, upsert=True
    )
    return res.upserted_id is not None


async def remove_sub(sub_id: str):
    try:
        await subs.delete_one({"_id": ObjectId(sub_id)})
    except Exception:
        pass


def iter_subs():
    return subs.find({})


# ---------- scheduled auto-delete (survives restarts) ----------
async def schedule_delete(chat_id: int, message_id: int, seconds):
    if seconds and int(seconds) > 0:
        await deletions.insert_one({"chat_id": chat_id, "message_id": message_id, "due": time.time() + int(seconds)})


async def reschedule_delete(chat_id: int, message_id: int, seconds):
    """Replace the delete timer of a message (e.g. a suggestion turned into results)."""
    await deletions.delete_many({"chat_id": chat_id, "message_id": message_id})
    await schedule_delete(chat_id, message_id, seconds)


async def pop_due(limit: int = 200):
    docs = [d async for d in deletions.find({"due": {"$lte": time.time()}}).limit(limit)]
    if docs:
        await deletions.delete_many({"_id": {"$in": [d["_id"] for d in docs]}})
    return docs


# ---------- events / stats ----------
async def log_event(kind: str, uid: int = 0):
    try:
        await events.insert_one({"k": kind, "uid": uid, "ts": datetime.utcnow()})
    except Exception:
        pass


async def count_events(kind: str, days: int = 1) -> int:
    return await events.count_documents({"k": kind, "ts": {"$gte": datetime.utcnow() - timedelta(days=days)}})
