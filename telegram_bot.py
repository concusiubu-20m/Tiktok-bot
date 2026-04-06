"""
Telegram Bot điều khiển TikTok View Bot v5.0
Deploy lên Railway – mọi lệnh được xử lý bất đồng bộ
"""

import asyncio
import io
import logging
import os
import sys
from typing import Dict, List, Optional, Tuple

import aiohttp
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode

from viewbot import TikTokViewBot, ProxyManager, BotStats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  IP public cache (lấy 1 lần, tái sử dụng)
# ─────────────────────────────────────────────

_PUBLIC_IP: Optional[str] = None

async def get_public_ip() -> str:
    """Lấy IP public của server, có cache."""
    global _PUBLIC_IP
    if _PUBLIC_IP:
        return _PUBLIC_IP
    services = [
        "https://api.ipify.org",
        "https://ipv4.icanhazip.com",
        "https://checkip.amazonaws.com",
        "https://api4.my-ip.io/ip",
    ]
    try:
        async with aiohttp.ClientSession() as sess:
            for url in services:
                try:
                    async with sess.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                        if r.status == 200:
                            ip = (await r.text()).strip()
                            if ip:
                                _PUBLIC_IP = ip
                                return ip
                except Exception:
                    continue
    except Exception:
        pass
    return "Không xác định"


# ─────────────────────────────────────────────
#  Parse proxy từ file txt (nhiều định dạng)
# ─────────────────────────────────────────────

def parse_proxy_line(line: str) -> Optional[str]:
    """
    Hỗ trợ các định dạng:
      ip:port                        → http://ip:port
      ip:port:user:pass              → http://user:pass@ip:port   (Webshare)
      user:pass@ip:port              → http://user:pass@ip:port
      http://...  /  https://...     → giữ nguyên
    Bỏ qua dòng comment (#) và dòng trống.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    # Đã có scheme
    if line.startswith(("http://", "https://", "socks5://")):
        return line

    # user:pass@ip:port
    if "@" in line:
        return f"http://{line}"

    parts = line.split(":")
    if len(parts) == 2:
        # ip:port
        try:
            int(parts[1])
            return f"http://{line}"
        except ValueError:
            return None

    if len(parts) == 4:
        # ip:port:user:pass  (Webshare format)
        ip, port, user, pwd = parts
        try:
            int(port)
            return f"http://{user}:{pwd}@{ip}:{port}"
        except ValueError:
            return None

    return None


def parse_proxy_text(text: str) -> Tuple[List[str], int]:
    """Trả về (danh sách proxy hợp lệ, số dòng bị lỗi)."""
    proxies: List[str] = []
    errors = 0
    for line in text.splitlines():
        p = parse_proxy_line(line)
        if p:
            proxies.append(p)
        elif line.strip() and not line.strip().startswith("#"):
            errors += 1
    return proxies, errors


# ─────────────────────────────────────────────
#  Trạng thái toàn cục (mỗi chat_id riêng biệt)
# ─────────────────────────────────────────────

class SessionState:
    def __init__(self):
        self.bot: Optional[TikTokViewBot] = None
        self.video_url: str = ""
        self.workers: int = 0
        self.rps: int = 200
        self.target_views: int = 0
        self._extra_proxies: List[str] = []

    def is_running(self) -> bool:
        return self.bot is not None and self.bot.is_running

    def proxy_count(self) -> int:
        return len(self._extra_proxies)


SESSIONS: Dict[int, SessionState] = {}

def get_session(chat_id: int) -> SessionState:
    if chat_id not in SESSIONS:
        SESSIONS[chat_id] = SessionState()
    return SESSIONS[chat_id]


# ─────────────────────────────────────────────
#  UI helpers
# ─────────────────────────────────────────────

def _keyboard_running(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📊 Thống kê", callback_data=f"stats:{chat_id}"),
        InlineKeyboardButton("🛑 Dừng",    callback_data=f"stop:{chat_id}"),
    ]])

def _keyboard_stopped() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("▶️ Bắt đầu lại", callback_data="restart"),
    ]])


async def _progress_cb(
    stats: BotStats,
    app: Application,
    chat_id: int,
    message_id: Optional[int] = None,
    session: Optional[SessionState] = None,
):
    """Callback định kỳ cập nhật message Telegram."""
    text = "📡 *Đang chạy...*\n\n" + stats.summary()
    try:
        if message_id:
            await app.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_keyboard_running(chat_id),
            )
        else:
            await app.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_keyboard_running(chat_id),
            )
    except Exception:
        pass

    # Tự dừng nếu đạt giới hạn
    if session and session.target_views > 0:
        if stats.total_views >= session.target_views and session.bot:
            await session.bot.stop()
            session.bot = None
            await app.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"✅ *Đã đạt {session.target_views:,} view!*\n\n"
                    + stats.summary()
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_keyboard_stopped(),
            )


# ─────────────────────────────────────────────
#  Command Handlers
# ─────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Hiển thị menu và IP public của server."""
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    # Thông báo đang lấy IP
    loading_msg = await update.message.reply_text(
        "⏳ Đang lấy thông tin server...",
    )

    public_ip = await get_public_ip()

    banner = (
        "🤖 *TikTok View Bot v5.0*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🌐 *IP Server:* `{public_ip}`\n"
        f"🌐 *Proxy đã load:* `{session.proxy_count()} proxy`\n\n"
        "📋 *Lệnh có sẵn:*\n"
        "/view \\<url\\>   – Bắt đầu gửi view\n"
        "/stop           – Dừng bot\n"
        "/stats          – Xem thống kê\n"
        "/config         – Cấu hình hiện tại\n"
        "/setworkers     – Đặt số workers\n"
        "/setrps         – Đặt giới hạn req/s\n"
        "/setlimit       – Giới hạn view tự dừng\n"
        "/addproxy       – Thêm 1 proxy\n"
        "/clearproxy     – Xoá tất cả proxy\n"
        "/help           – Hướng dẫn\n\n"
        "📁 *Gửi file `.txt`* để import proxy hàng loạt\\!"
    )

    await loading_msg.edit_text(banner, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 *Hướng dẫn sử dụng*\n\n"
        "*1\\. Bắt đầu gửi view:*\n"
        "`/view https://www.tiktok.com/@user/video/ID`\n\n"
        "*2\\. Dừng:*\n"
        "`/stop`\n\n"
        "*3\\. Thống kê:*\n"
        "`/stats`\n\n"
        "*4\\. Tuỳ chỉnh:*\n"
        "`/setworkers 2000` – số luồng \\(10–10000\\)\n"
        "`/setrps 300`      – request/giây tối đa\n"
        "`/setlimit 5000`   – tự dừng khi đủ view \\(0\\=vô hạn\\)\n\n"
        "*5\\. Proxy:*\n"
        "`/addproxy ip:port`         – thêm 1 proxy\n"
        "`/clearproxy`               – xoá tất cả\n"
        "📁 Gửi file `.txt` để import hàng loạt\n\n"
        "*Định dạng proxy hỗ trợ:*\n"
        "`ip:port`\n"
        "`ip:port:user:pass` \\(Webshare\\)\n"
        "`user:pass@ip:port`\n\n"
        "⚠️ Chỉ dùng cho mục đích học tập\\!"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_view(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if session.is_running():
        await update.message.reply_text(
            "⚠️ Bot đang chạy rồi\\! Gõ /stop trước khi bắt đầu phiên mới\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    if not ctx.args:
        await update.message.reply_text(
            "❌ Thiếu URL\\!\nCú pháp: `/view <url>`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    url = ctx.args[0].strip()
    if "tiktok.com" not in url:
        await update.message.reply_text("❌ URL không hợp lệ\\. Phải là link TikTok\\!", parse_mode=ParseMode.MARKDOWN_V2)
        return

    session.video_url = url
    msg = await update.message.reply_text("🔍 Đang lấy Video ID và khởi động bot\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)

    # Xây dựng ProxyManager
    pm = ProxyManager(proxy_list=list(session._extra_proxies))
    env_proxies = os.getenv("PROXIES", "")
    if env_proxies:
        extras, _ = parse_proxy_text(env_proxies.replace(",", "\n"))
        pm.proxies.extend(extras)

    session.bot = TikTokViewBot(
        proxy_manager=pm,
        max_workers=session.workers,
        max_rps=session.rps,
    )

    live_msg_id = msg.message_id

    async def _prog_cb(stats: BotStats):
        await _progress_cb(stats, ctx.application, chat_id, live_msg_id, session)

    session.bot.on_progress = _prog_cb

    try:
        await session.bot.start(url)
        proxy_info = f"{pm.has_proxies() and len(pm.proxies) or 0} proxy"
        await ctx.application.bot.edit_message_text(
            chat_id=chat_id,
            message_id=live_msg_id,
            text=(
                f"✅ *Bot đã khởi động\\!*\n\n"
                f"🎯 URL: `{url}`\n"
                f"🧵 Workers: `{session.bot.max_workers:,}`\n"
                f"⚡ Max RPS: `{session.rps}`\n"
                f"🌐 Proxy: `{proxy_info}`\n"
                f"🎯 Giới hạn: `{'Không giới hạn' if session.target_views == 0 else f'{session.target_views:,} view'}`\n\n"
                "Nhấn 📊 để xem thống kê hoặc 🛑 để dừng\\."
            ),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=_keyboard_running(chat_id),
        )
    except Exception as e:
        session.bot = None
        err = str(e).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
        await ctx.application.bot.edit_message_text(
            chat_id=chat_id,
            message_id=live_msg_id,
            text=f"❌ Lỗi: `{err}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        logger.exception("Lỗi khởi động bot")


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if not session.is_running():
        await update.message.reply_text("ℹ️ Bot chưa chạy\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    stats = session.bot.stats
    await session.bot.stop()
    session.bot = None

    await update.message.reply_text(
        "🛑 *Bot đã dừng\\.*\n\n" + _escape_md(stats.summary()),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_keyboard_stopped(),
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if not session.is_running():
        await update.message.reply_text("ℹ️ Bot chưa chạy\\. Dùng /view để bắt đầu\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    await update.message.reply_text(
        "📊 *Thống kê hiện tại:*\n\n" + _escape_md(session.bot.stats.summary()),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_keyboard_running(chat_id),
    )


async def cmd_config(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    public_ip = await get_public_ip()

    text = (
        "⚙️ *Cấu hình hiện tại:*\n\n"
        f"🌐 IP Server: `{public_ip}`\n"
        f"🧵 Workers: `{session.workers or 'Auto'}`\n"
        f"⚡ Max RPS: `{session.rps}`\n"
        f"🎯 Giới hạn view: `{'Không giới hạn' if session.target_views == 0 else f'{session.target_views:,}'}`\n"
        f"🌐 Proxy: `{session.proxy_count()} proxy`\n"
        f"📹 URL: `{_escape_md(session.video_url) or 'Chưa đặt'}`\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_set_workers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_chat.id)
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text(
            "❌ Cú pháp: `/setworkers <số>`\nVí dụ: `/setworkers 2000`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return
    session.workers = max(10, min(int(ctx.args[0]), 10000))
    await update.message.reply_text(f"✅ Workers đã đặt: `{session.workers:,}`", parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_set_rps(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_chat.id)
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text(
            "❌ Cú pháp: `/setrps <số>`\nVí dụ: `/setrps 300`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return
    session.rps = max(10, min(int(ctx.args[0]), 2000))
    await update.message.reply_text(f"✅ Max RPS đã đặt: `{session.rps}`", parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_set_limit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_chat.id)
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text(
            "❌ Cú pháp: `/setlimit <số>` \\(0 \\= không giới hạn\\)\nVí dụ: `/setlimit 5000`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return
    n = int(ctx.args[0])
    session.target_views = max(0, n)
    label = "Không giới hạn" if n == 0 else f"{n:,} view"
    await update.message.reply_text(f"✅ Giới hạn view: `{label}`", parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_add_proxy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_chat.id)
    if not ctx.args:
        await update.message.reply_text(
            "❌ Cú pháp: `/addproxy ip:port` hoặc `/addproxy user:pass@ip:port`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return
    raw = ctx.args[0].strip()
    proxy = parse_proxy_line(raw)
    if not proxy:
        await update.message.reply_text("❌ Định dạng proxy không hợp lệ\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return
    session._extra_proxies.append(proxy)
    await update.message.reply_text(
        f"✅ Đã thêm: `{_escape_md(proxy)}`\nTổng: `{session.proxy_count()} proxy`",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_clear_proxy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    session = get_session(update.effective_chat.id)
    old = session.proxy_count()
    session._extra_proxies.clear()
    await update.message.reply_text(f"✅ Đã xoá `{old}` proxy\\.", parse_mode=ParseMode.MARKDOWN_V2)


# ─────────────────────────────────────────────
#  Document Handler – import proxy từ file .txt
# ─────────────────────────────────────────────

async def doc_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Nhận file .txt và tự động import proxy."""
    doc = update.message.document
    if not doc:
        return

    fname = doc.file_name or ""
    if not fname.lower().endswith(".txt"):
        await update.message.reply_text(
            "ℹ️ Chỉ hỗ trợ file `.txt` để import proxy\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    loading = await update.message.reply_text(
        f"⏳ Đang xử lý `{_escape_md(fname)}`\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    try:
        tg_file = await ctx.bot.get_file(doc.file_id)
        buf = io.BytesIO()
        await tg_file.download_to_memory(buf)
        content = buf.getvalue().decode("utf-8", errors="ignore")
    except Exception as e:
        await loading.edit_text(f"❌ Không tải được file: `{_escape_md(str(e))}`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    proxies, errors = parse_proxy_text(content)

    if not proxies:
        await loading.edit_text(
            f"❌ Không tìm thấy proxy hợp lệ trong file `{_escape_md(fname)}`\\.\n"
            f"Dòng lỗi định dạng: `{errors}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # Thêm vào session (tránh trùng)
    existing = set(session._extra_proxies)
    added = 0
    for p in proxies:
        if p not in existing:
            session._extra_proxies.append(p)
            existing.add(p)
            added += 1

    # Hiển thị vài proxy đầu làm preview
    preview_lines = []
    for p in proxies[:5]:
        preview_lines.append(f"  • `{_escape_md(p)}`")
    preview = "\n".join(preview_lines)
    if len(proxies) > 5:
        preview += f"\n  _\\.\\.\\. và {len(proxies) - 5} proxy khác_"

    await loading.edit_text(
        f"✅ *Import proxy thành công\\!*\n\n"
        f"📄 File: `{_escape_md(fname)}`\n"
        f"✅ Hợp lệ: `{len(proxies)}`\n"
        f"➕ Thêm mới: `{added}`\n"
        f"⏭️ Đã có: `{len(proxies) - added}`\n"
        f"❌ Lỗi định dạng: `{errors}`\n"
        f"📦 Tổng proxy hiện tại: `{session.proxy_count()}`\n\n"
        f"*Proxy mẫu:*\n{preview}",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


# ─────────────────────────────────────────────
#  Callback Query (nút bấm inline)
# ─────────────────────────────────────────────

async def cb_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if data.startswith("stats:"):
        if not session.is_running():
            await query.edit_message_text("ℹ️ Bot đã dừng\\.", parse_mode=ParseMode.MARKDOWN_V2)
            return
        await query.edit_message_text(
            "📊 *Thống kê:*\n\n" + _escape_md(session.bot.stats.summary()),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=_keyboard_running(chat_id),
        )

    elif data.startswith("stop:"):
        if not session.is_running():
            await query.edit_message_text("ℹ️ Bot đã dừng rồi\\.", parse_mode=ParseMode.MARKDOWN_V2)
            return
        stats = session.bot.stats
        await session.bot.stop()
        session.bot = None
        await query.edit_message_text(
            "🛑 *Đã dừng bot\\.*\n\n" + _escape_md(stats.summary()),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=_keyboard_stopped(),
        )

    elif data == "restart":
        await query.edit_message_text(
            "ℹ️ Dùng lệnh `/view <url>` để bắt đầu phiên mới\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


# ─────────────────────────────────────────────
#  Text message handler (gửi link TikTok trực tiếp)
# ─────────────────────────────────────────────

async def msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if "tiktok.com" in text:
        ctx.args = [text.strip()]
        await cmd_view(update, ctx)
    else:
        await update.message.reply_text(
            "ℹ️ Gửi link TikTok hoặc file `.txt` proxy, hoặc dùng /help\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


# ─────────────────────────────────────────────
#  Utility
# ─────────────────────────────────────────────

_MD_SPECIAL = r"\_*[]()~`>#+-=|{}.!"

def _escape_md(text: str) -> str:
    """Escape ký tự đặc biệt MarkdownV2."""
    for ch in _MD_SPECIAL:
        text = text.replace(ch, f"\\{ch}")
    return text


# ─────────────────────────────────────────────
#  Khởi động
# ─────────────────────────────────────────────

async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start",      "Giới thiệu + IP server"),
        BotCommand("view",       "Bắt đầu gửi view"),
        BotCommand("stop",       "Dừng bot"),
        BotCommand("stats",      "Xem thống kê"),
        BotCommand("config",     "Cấu hình hiện tại"),
        BotCommand("setworkers", "Đặt số workers"),
        BotCommand("setrps",     "Đặt giới hạn req/s"),
        BotCommand("setlimit",   "Đặt giới hạn view"),
        BotCommand("addproxy",   "Thêm 1 proxy"),
        BotCommand("clearproxy", "Xoá tất cả proxy"),
        BotCommand("help",       "Hướng dẫn"),
    ])
    logger.info("Bot đã sẵn sàng!")


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("Thiếu TELEGRAM_BOT_TOKEN trong biến môi trường!")
        sys.exit(1)

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("view",       cmd_view))
    app.add_handler(CommandHandler("stop",       cmd_stop))
    app.add_handler(CommandHandler("stats",      cmd_stats))
    app.add_handler(CommandHandler("config",     cmd_config))
    app.add_handler(CommandHandler("setworkers", cmd_set_workers))
    app.add_handler(CommandHandler("setrps",     cmd_set_rps))
    app.add_handler(CommandHandler("setlimit",   cmd_set_limit))
    app.add_handler(CommandHandler("addproxy",   cmd_add_proxy))
    app.add_handler(CommandHandler("clearproxy", cmd_clear_proxy))
    app.add_handler(CallbackQueryHandler(cb_handler))
    # File .txt → import proxy
    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), doc_handler))
    # Text thường → detect link TikTok
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))

    logger.info("Đang khởi động polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
