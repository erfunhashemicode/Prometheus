from dotenv import load_dotenv
load_dotenv()

import os
import logging
import threading

from flask import Flask

from telegram import Update
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
# Telegram Commands
# -----------------------

async def nodes(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Searching latest nodes..."
    )

    try:
        data = get_nodes()

    except Exception:
        logger.exception("get_nodes() failed")

        await update.message.reply_text(
            "Something went wrong while fetching nodes. Try again shortly."
        )
        return

    if not data:
        await update.message.reply_text(
            "No nodes found."
        )
        return

    msg = ""

    for i, node in enumerate(data[:10], 1):
        msg += f"\n#{i}\n{node}\n"

    await update.message.reply_text(
        msg[:4000]
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
