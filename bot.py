import asyncio
import logging
import os
from collections import defaultdict

from aiohttp import ClientSession, ClientTimeout, web
from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
from pyrogram.types import BotCommand

import database as db
import settings
import verify
from config import Config

logging.basicConfig(level=logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.WARNING)


async def _health(request):
    return web.Response(text="Bot is running ✅")


async def _keep_alive(url: str):
    """Ping our own Render URL so the free instance doesn't idle out."""
    async with ClientSession(timeout=ClientTimeout(total=15)) as session:
        while True:
            await asyncio.sleep(600)
            try:
                await session.get(url)
            except Exception:
                pass


async def _delete_ids(client, chat_id, ids):
    try:
        await client.delete_messages(chat_id, ids)
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
    except Exception:
        for i in ids:  # one bad id must not block the rest
            try:
                await client.delete_messages(chat_id, i)
            except Exception:
                pass


async def _deleter(client):
    """Deletes scheduled messages when due. Stored in MongoDB, so restarts don't lose them."""
    while True:
        await asyncio.sleep(10)
        try:
            by_chat = defaultdict(list)
            for d in await db.pop_due():
                by_chat[d["chat_id"]].append(d["message_id"])
            for chat_id, ids in by_chat.items():
                await _delete_ids(client, chat_id, ids)
        except Exception:
            logging.exception("auto-delete loop error")


class Bot(Client):
    def __init__(self):
        super().__init__(
            "autofilter",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.BOT_TOKEN,
            plugins=dict(root="plugins"),
            parse_mode=ParseMode.HTML,
            workers=50,
            in_memory=True,  # Render's disk is wiped on every deploy
        )
        self._runner = None
        self._tasks = []

    async def start(self, *args, **kwargs):
        # web server first, so Render sees the open port quickly
        app = web.Application()
        app.router.add_get("/", _health)
        app.router.add_get("/health", _health)
        verify.routes(app)  # /go/<token>  (verification page)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        await web.TCPSite(self._runner, "0.0.0.0", Config.PORT).start()
        logging.info("Web server on port %s", Config.PORT)

        await super().start(*args, **kwargs)
        await db.setup()
        await settings.load()
        me = await self.get_me()
        Config.BOT_USERNAME = me.username
        logging.info("Bot started as @%s", me.username)
        if not Config.BASE_URL:
            logging.warning("BASE_URL / RENDER_EXTERNAL_URL not set - 'server' verification format falls back to direct links")

        try:
            await self.set_bot_commands([BotCommand("start", "Start the bot"), BotCommand("help", "How to use")])
        except Exception:
            logging.warning("couldn't set bot commands")

        self._tasks.append(asyncio.create_task(_deleter(self)))
        if os.getenv("RENDER_EXTERNAL_URL"):
            self._tasks.append(asyncio.create_task(_keep_alive(os.environ["RENDER_EXTERNAL_URL"])))

    async def stop(self, *args, **kwargs):
        for t in self._tasks:
            t.cancel()
        if self._runner:
            await self._runner.cleanup()
        await super().stop(*args, **kwargs)
        logging.info("Bot stopped")


if __name__ == "__main__":
    Bot().run()
