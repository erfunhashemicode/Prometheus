from dotenv import load_dotenv
load_dotenv()

import os
import html
import logging
import threading

from flask import Flask

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from scraper import get_nodes


# -----------------------
# Flask keep-alive server
# -----------------------

app_web = Flask(__name__)


@app_web.route("/")
def home():
    return "Prometheus bot is running"


def run_web():
    app_web.run(
        host="0.0.0.0",
        port=8080
    )


# -----------------------
# Logging
# -----------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# -----------------------
# Telegram Token
# -----------------------

TOKEN = os.environ.get("TOKEN")

if not TOKEN:
    raise RuntimeError(
        "TOKEN environment variable is not set. "
        "Add TOKEN in Render Environment Variables."
    )


# -----------------------
# Config
# -----------------------

# How many nodes to send per /nodes call. Set to None to send everything
# the scraper found (can be 50-100+ messages worth on a busy day).
MAX_NODES = 30

# Telegram hard-caps messages at 4096 chars. We stay well under that so
# formatting overhead never pushes a chunk over the limit.
CHUNK_CHAR_LIMIT = 3500


# -----------------------
# Helpers
# -----------------------

def build_header(result: dict, total_sent: int, total_found: int) -> str:
    lines = [
        "<b>Prometheus Nodes</b>",
        f"Fetched: {html.escape(result['fetched_at'])}",
    ]

    if result.get("page_timestamp"):
        lines.append(f"Site last updated: {html.escape(result['page_timestamp'])}")

    lines.append(f"Showing {total_sent} of {total_found} nodes found")
    lines.append(
        "Tap a config below to copy it. These are free/public nodes: "
        "test latency and protocol in your client before relying on one, "
        "and avoid using them for logins, payments, or sensitive traffic."
    )

    return "\n".join(lines)


def build_chunks(header: str, nodes: list[str], char_limit: int) -> list[str]:
    """
    Groups numbered, HTML-escaped, <code>-wrapped nodes into chunks that
    each stay under char_limit, so nothing gets silently truncated.
    The header is included only in the first chunk.
    """
    chunks = []
    current_lines = [header]
    current_len = len(header)
    is_first_chunk = True

    for i, node in enumerate(nodes, 1):
        escaped = html.escape(node)
        entry = f"\n#{i}\n<code>{escaped}</code>"

        would_overflow = current_len + len(entry) > char_limit
        has_content = len(current_lines) > (1 if is_first_chunk else 0)

        if would_overflow and has_content:
            chunks.append("\n".join(current_lines))
            current_lines = [entry]
            current_len = len(entry)
            is_first_chunk = False
        else:
            current_lines.append(entry)
            current_len += len(entry)

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks


# -----------------------
# Telegram Commands
# -----------------------

async def nodes(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Searching latest nodes..."
    )

    try:
        result = get_nodes()

    except Exception:
        logger.exception("get_nodes() failed")

        await update.message.reply_text(
            "Something went wrong while fetching nodes. Try again shortly."
        )
        return

    # Defensive: if an older scraper.py (returning a plain list instead of
    # a dict) ever ends up deployed, don't hard-crash — just degrade
    # gracefully to "no metadata" instead of raising AttributeError.
    if isinstance(result, dict):
        pass
    elif isinstance(result, list):
        logger.warning(
            "get_nodes() returned a list, not a dict — scraper.py looks "
            "out of date. Update it to the version that returns a dict."
        )
        result = {
            "nodes": result,
            "fetched_at": "unknown (outdated scraper.py)",
            "page_timestamp": None,
            "source_url": None,
        }
    else:
        logger.error("get_nodes() returned unexpected type: %r", type(result))
        result = {"nodes": [], "fetched_at": "unknown", "page_timestamp": None, "source_url": None}

    all_nodes = result.get("nodes", [])

    if not all_nodes:
        await update.message.reply_text(
            "No nodes found. The site's layout may have changed."
        )
        return

    nodes_to_send = all_nodes if MAX_NODES is None else all_nodes[:MAX_NODES]

    header = build_header(result, len(nodes_to_send), len(all_nodes))
    chunks = build_chunks(header, nodes_to_send, CHUNK_CHAR_LIMIT)

    for chunk in chunks:
        await update.message.reply_text(
            chunk,
            parse_mode=ParseMode.HTML,
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Prometheus Nodes online. Use /nodes to fetch the latest list."
    )


# -----------------------
# Main
# -----------------------

def main():

    # Start Flask server for Render
    threading.Thread(
        target=run_web,
        daemon=True
    ).start()


    # Start Telegram bot
    app = Application.builder().token(TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("nodes", nodes)
    )


    logger.info(
        "Bot starting (polling mode)..."
    )

    app.run_polling()


if __name__ == "__main__":
    main()
