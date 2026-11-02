"""Small helpers so the same code works with Kurigram's newer argument names."""
try:  # Kurigram: link_preview_options replaced disable_web_page_preview
    from pyrogram.types import LinkPreviewOptions

    NOPREVIEW = {"link_preview_options": LinkPreviewOptions(is_disabled=True)}
except (ImportError, TypeError):
    NOPREVIEW = {"disable_web_page_preview": True}

try:  # Kurigram: reply_parameters replaced reply_to_message_id
    from pyrogram.types import ReplyParameters

    def reply_kw(message_id):
        return {"reply_parameters": ReplyParameters(message_id=message_id)} if message_id else {}
except ImportError:
    def reply_kw(message_id):
        return {"reply_to_message_id": message_id} if message_id else {}
