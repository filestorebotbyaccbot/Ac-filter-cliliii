"""All user-facing messages. HTML, one line per paragraph (rich messages turn each line into a paragraph)."""
from utils import esc, fmt_duration, human_size

LINE = "━━━━━━━━━━━━━━━━━━"


def _note(secs, what="This message") -> str:
    return f"⏱ <i>{what} will be deleted in {fmt_duration(secs)}.</i>" if secs and secs > 0 else ""


def _join(*lines) -> str:
    return "\n".join(x for x in lines if x)


def welcome(name: str) -> str:
    return _join(
        f"👋 <b>Hello {esc(name)}!</b>",
        "📚 I'm a story search bot.",
        "◉ Add me to your group and type a story name",
        "◉ Spelling mistakes are fine",
        "◉ Tap a result to get the file here",
    )


def help_text(is_admin: bool) -> str:
    base = _join(
        "ℹ️ <b>HELP</b>",
        "◉ Type a story name in the group (or here) to search",
        "◉ Tap a result - I'll send the file in this chat",
        "◉ Use 🔔 Subscribe Updates to hear about new files",
    )
    if not is_admin:
        return base
    return base + "\n\n" + _join(
        "🛠 <b>Admin</b>",
        "/settings - change everything live",
        "/connect <code>-100id</code> · /disconnect <code>-100id</code> [purge] · /channels",
        "/index <code>-100id [last_msg_id] [first_msg_id]</code> - index old files",
        "/delfile <code>name</code> - delete a file from the database",
        "/stats · /broadcast · /ban <code>id</code> · /unban <code>id</code>",
        "Send or forward a file here in PM to save it too.",
    )


def results(q: str, total: int, user_html: str, chunk: list, start: int, page: int, pages: int, link, secs) -> str:
    lines = [
        f"📖 <b>STORY:</b> <code>{esc(q[:60])}</code>",
        f"🔗 <b>RESULTS FOUND:</b> {total}" + (f"  |  📄 {page + 1}/{pages}" if pages > 1 else ""),
        f"👤 <b>REQUESTED BY:</b> {user_html}",
    ]
    for i, (fid, name) in enumerate(chunk, start=start + 1):
        lines.append(f'<blockquote>{i}. 📁 <a href="{esc(link(fid))}">{esc(name)}</a></blockquote>')
    lines.append(_note(secs))
    return _join(*lines)


def nomatch(q: str, user_html: str, has_sugs: bool, secs) -> str:
    return _join(
        f"❌ <b>NO DIRECT MATCH FOUND FOR</b> <code>{esc(q[:60])}</code>",
        f"👤 <b>REQUESTED BY:</b> {user_html}",
        "🤖 <b>DID YOU MEAN?</b>" if has_sugs else "Check the spelling, or request this story below.",
        _note(secs, "This suggestion message"),
    )


def sub_alert(title: str, name: str) -> str:
    return _join("🔔 <b>NEW FILE</b>", f"◉ <b>For:</b> {esc(title)}", f"◉ <b>File:</b> {esc(name)}")


def file_missing() -> str:
    return _join("⚠️ <b>FILE NOT AVAILABLE</b>", "This file was removed. Please search again.")


def file_ready(name: str, secs) -> str:
    return _join("✅ <b>YOUR FILE IS READY</b>", f"◉ <b>Name:</b> {esc(name)}", _note(secs, "The file"), "👇 <i>Tap below to open it</i>")


def file_note(secs) -> str:
    return _join(f"⏳ <i>The file above will be deleted in {fmt_duration(secs)}. Forward or save it now.</i>")


def file_caption(template: str, name: str, size) -> str:
    try:
        return (template or "{name}").format(name=esc(name), size=human_size(size))
    except Exception:
        return esc(name)


def fsub_prompt() -> str:
    return _join(
        "🔔 <b>JOIN REQUIRED</b>",
        "To get this file, first join the channel(s) below.",
        "Then tap <b>✅ I've joined</b>.",
    )


def verify_prompt(stage: int, name, free_text: str, valid_text: str) -> str:
    head = "🛡 <b>VERIFICATION REQUIRED</b>" if stage == 1 else "⚡ <b>EXTEND YOUR FREE TIME</b>"
    reward = (
        f"✅ After verifying, all files are free until <b>{valid_text}</b> today."
        if stage == 1
        else f"✅ After this verification you get <b>{free_text}</b> of free access."
    )
    return _join(
        head,
        f"◉ <b>File:</b> {esc(name)}" if name else "",
        reward,
        "1️⃣ Tap <b>Verify</b> and complete the page properly",
        "2️⃣ Come back here - your file arrives automatically",
        "<i>Skipping steps is detected and the link is rejected.</i>",
    )


def verify_unavailable() -> str:
    return _join("⚠️ <b>VERIFICATION UNAVAILABLE</b>", "Couldn't create the verification link. Please try again in a minute.")


def verify_ok(stage: int, free_text: str, valid_text: str) -> str:
    when = f"until <b>{valid_text}</b> today" if stage == 1 else f"for <b>{free_text}</b>"
    return _join("✅ <b>VERIFIED</b>", f"All files are free {when}.")


def verify_fail(kind: str) -> str:
    msg = {
        "fast": "You finished too fast - the shortener page was skipped. Please do it properly.",
        "expired": "That link expired. A new one is below.",
        "used": "That link was already used.",
        "notyours": "That verification link belongs to someone else.",
        "missing": "That verification link is not valid.",
    }[kind]
    return _join("⚠️ <b>VERIFICATION FAILED</b>", msg)


def stats_box(d: dict) -> str:
    return _join(
        "📊 <b>BOT STATS</b>",
        f"📚 <b>Files:</b> {d['files']}   📡 <b>Channels:</b> {d['channels']}",
        f"👥 <b>Users:</b> {d['users']}",
        LINE,
        f"🔍 <b>Searches:</b> {d['search1']} today  •  {d['search7']} (7 days)",
        f"📦 <b>Files delivered:</b> {d['dl1']} today  •  {d['dl7']} (7 days)",
        f"✅ <b>Verifications:</b> {d['v1']} today  •  {d['v7']} (7 days)",
        f"🚫 <b>Bypass blocked:</b> {d['bp1']} today  •  {d['bp7']} (7 days)",
    )
