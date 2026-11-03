# Auto Filter Bot (Kurigram + MongoDB + RapidFuzz) - rich buttons everywhere

## How it works
1. Admin posts audio / files in a **connected channel** (or sends a file to the bot in PM). The bot saves the file name.
2. Someone types a story name in a group -> the bot replies with a rich message: results as deep links, Back/Next, Subscribe Updates, Request Story.
3. Typos are fine (RapidFuzz). Nothing close? -> "Did you mean?" buttons.
4. User taps a result -> opens the bot PM -> force-sub check -> verification (if on) -> file is delivered.

## Setup
1. Create the bot in @BotFather. Add it to your search group (group privacy: Disable, or make it admin).
2. Add it as **admin** in your file channel, then in the bot: `/connect -100xxxxxxxxxx` (old files: `/index -100id`).
3. Render: New > Web Service > this repo. Build `pip install -r requirements.txt`, Start `python bot.py`.
   Env: `API_ID`, `API_HASH`, `BOT_TOKEN`, `MONGO_URI`, `ADMINS` (your user id), `PYTHON_VERSION=3.11.9`.
   Port: the web server (health page + `/go/<token>` verification page) listens on `0.0.0.0:$PORT`. Render sets `PORT` itself (10000), so you don't need to add it. Add `PORT` only to use a different one.
4. Send `/settings` to the bot: set Shortener 1 (and 2), tutorial video, times, force-sub... all live.

## /settings (everything is dynamic, saved in MongoDB)
- **Shortener 1 / 2**: on/off, site, API key, tutorial video link (🎥 button).
- **Verification**: on/off, format (server / direct), alias length (min 15), gap, link validity, free time after 2nd verification, timezone.
- **Delivery**: PM or delivery channel, caption, "file will be deleted" note.
- **Auto-delete**: search results, suggestions, delivered file, prompts, user's query.
- **Force-sub**: channels list, each normal or request-to-join, auto-approve.
- **Protection**: no forward / save on delivered files.
- **Search**: scores, page size, suggestions, group behaviour.   **Links**: Request Story, updates channel.

## Verification rules (1/2 and 2/2)
- **1/2 is asked straight away.** After it the user is free for the **gap time** (`Gap before 2nd verification`, e.g. 1h) - never past 12:00 AM.
- When the gap is over (same day) **2/2 is asked**. After it the user is free for the **valid time** (`Valid time after 2nd verification`, e.g. 1d or 1h).
- If only 1/2 was done today it is forgotten at **12:00 AM**: the user starts again from 1/2, even if they come back 2 days later.
- When the valid time ends, the cycle restarts from 1/2.
- Only one shortener turned on: one verification = free until 11:59 PM.
- Every short link gets a random alias of 15+ characters.
- **server** format: the Verify button opens `your-app/go/<token>` which redirects to the shortener, so users never see the real shortener link.
- Bypass protection: a link works once, only for the user it was made for, expires, finishing faster than **Fastest allowed** is rejected, and an old link can't extend free time that is already running.

## Joining rules
- **Force-sub, normal**: user must be a member. **Request mode**: the user sends a join request on the bot's link, the bot notices it (needs the bot to be **admin with "Invite users"** in that channel), and the file arrives automatically. "Auto-approve" can accept the request at once.
- **Delivery channel (private)**: before any "Open file" button the bot checks the user is a member; if not, it asks them to join first. A public delivery channel (with @username) needs no join.
- **Did you mean?**: tapping a suggestion turns that same message into the result list with exactly that story's files.

## Assumptions to check
- Shortener API must be AdLinkFly-style: `https://site/api?api=KEY&url=URL&alias=ALIAS`. Other formats: send me the API doc.
- "Delivery channel": the file is copied into that channel (auto-deleted) and the user gets an Open file button.
- Force-sub request mode: users who sent a join request count as joined.
