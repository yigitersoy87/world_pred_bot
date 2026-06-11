"""
Kicktipp WorldPrediction2026 Leaderboard Telegram Bot
======================================================
Commands:
  /start    - Welcome message
  /leaderboard  - Show current overall leaderboard
  /matchday <N> - Show leaderboard for a specific matchday (1-15)
  /help     - Show available commands

Setup:
  1. pip install python-telegram-bot requests beautifulsoup4
  2. Create a bot via @BotFather on Telegram → get your BOT_TOKEN
  3. Set BOT_TOKEN below (or via environment variable TELEGRAM_BOT_TOKEN)
  4. Run: python kicktipp_bot.py
"""

import os
import logging
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

BASE_URL = "https://www.kicktipp.com/worldprediction2026/leaderboard"
SEASON_ID = "4343234"

MATCHDAY_LABELS = {
    1: "Matchday 1",  2: "Matchday 2",  3: "Matchday 3",
    4: "Matchday 4",  5: "Matchday 5",  6: "Matchday 6",
    7: "Matchday 7",  8: "Matchday 8",  9: "Matchday 9",
    10: "Matchday 10", 11: "Round of 32", 12: "Round of 16",
    13: "Quarter-final", 14: "Semi-finals", 15: "Final",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Scraper ───────────────────────────────────────────────────────────────────

def fetch_leaderboard(matchday: int = None) -> list[dict]:
    """
    Fetch and parse the leaderboard table from Kicktipp.
    Returns a list of dicts: {pos, name, points, bonus, wins, total}
    """
    params = {"tippsaisonId": SEASON_ID}
    if matchday:
        params["spieltagIndex"] = matchday

    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # The leaderboard is in a <table> — find all rows
    rows = soup.select("table tr")

    players = []
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 5:
            continue

        # Kicktipp table columns (after stripping links/arrows):
        # 0: position, 1: +/-, 2: name, ..., -4: P (matchday pts),
        # -3: B (bonus), -2: W (wins), -1: T (total)
        pos_text = cells[0].get_text(strip=True).replace(".", "")
        name = cells[2].get_text(strip=True)

        if not name or not pos_text.isdigit():
            continue

        total  = cells[-1].get_text(strip=True)
        wins   = cells[-2].get_text(strip=True)
        bonus  = cells[-3].get_text(strip=True)
        md_pts = cells[-4].get_text(strip=True)

        players.append({
            "pos":    int(pos_text),
            "name":   name,
            "md_pts": md_pts or "0",
            "bonus":  bonus  or "0",
            "wins":   wins   or "0",
            "total":  total  or "0",
        })

    return players


def format_leaderboard(players: list[dict], title: str) -> str:
    """Format the player list into a nicely readable Telegram message."""
    if not players:
        return "⚠️ Could not load leaderboard data. Try again later."

    medal = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [f"🏆 *{title}*\n"]
    lines.append("`Pos  Name              Pts  Tot`")
    lines.append("`───  ────────────────  ───  ───`")

    for p in players:
        icon = medal.get(p["pos"], f"{p['pos']:>3}.")
        name = p["name"][:16].ljust(16)
        line = f"`{icon}  {name}  {p['md_pts']:>3}  {p['total']:>3}`"
        lines.append(line)

    lines.append("\n_P = Matchday pts · T = Total pts_")
    return "\n".join(lines)

# ── Handlers ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Welcome to the WorldPrediction2026 Bot!*\n\n"
        "Track your Kicktipp leaderboard right here in Telegram.\n\n"
        "Commands:\n"
        "• /leaderboard — Current overall standings\n"
        "• /matchday 1 — Standings after Matchday 1\n"
        "• /help — Full command list"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "*Available commands*\n\n"
        "/leaderboard — Overall leaderboard (Matchday 1 default)\n"
        "/matchday `<N>` — Leaderboard for matchday N\n"
        "  • 1–10 → Group stage matchdays\n"
        "  • 11 → Round of 32\n"
        "  • 12 → Round of 16\n"
        "  • 13 → Quarter-finals\n"
        "  • 14 → Semi-finals\n"
        "  • 15 → Final\n"
        "/start — Welcome message\n"
        "/help — This message"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching leaderboard…")
    try:
        players = fetch_leaderboard()
        text = format_leaderboard(players, "WorldPrediction2026 — Overall")
    except Exception as e:
        logger.error("Error fetching leaderboard: %s", e)
        text = f"❌ Failed to fetch leaderboard: {e}"
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_matchday(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "Usage: /matchday `<number>` (e.g. `/matchday 3`)",
            parse_mode="Markdown",
        )
        return

    md = int(args[0])
    if md < 1 or md > 15:
        await update.message.reply_text("❌ Matchday must be between 1 and 15.")
        return

    label = MATCHDAY_LABELS.get(md, f"Matchday {md}")
    await update.message.reply_text(f"⏳ Fetching {label} leaderboard…")

    try:
        players = fetch_leaderboard(matchday=md)
        text = format_leaderboard(players, f"WorldPrediction2026 — {label}")
    except Exception as e:
        logger.error("Error fetching matchday %d: %s", md, e)
        text = f"❌ Failed to fetch leaderboard: {e}"

    await update.message.reply_text(text, parse_mode="Markdown")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print(
            "⚠️  No bot token set!\n"
            "Either set the TELEGRAM_BOT_TOKEN environment variable or\n"
            "replace YOUR_BOT_TOKEN_HERE in the script with your token."
        )
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("matchday",    cmd_matchday))

    logger.info("Bot is running…")
    app.run_polling()


if __name__ == "__main__":
    main()