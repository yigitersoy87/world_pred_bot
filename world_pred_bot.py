"""
Kicktipp WorldPrediction2026 — Telegram Bot
============================================
Commands:
  /start              - Welcome message
  /leaderboard        - Overall leaderboard
  /matchday <N>       - Leaderboard for matchday N (1-15)
  /scores             - Scores + everyone's predictions for Matchday 1
  /scores <N>         - Scores + everyone's predictions for Matchday N
  /today              - Today's matches + predictions
  /help               - Show available commands

Setup:
  1. pip install python-telegram-bot requests beautifulsoup4
  2. Get a bot token from @BotFather on Telegram
  3. Set TELEGRAM_BOT_TOKEN env var or paste token below
  4. Run: python kicktipp_bot.py
"""

import os
import re
import logging
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
BASE        = "https://www.kicktipp.com/worldprediction2026"
SEASON_ID   = "4343234"

MATCHDAY_LABELS = {
    1:"Matchday 1",  2:"Matchday 2",  3:"Matchday 3",
    4:"Matchday 4",  5:"Matchday 5",  6:"Matchday 6",
    7:"Matchday 7",  8:"Matchday 8",  9:"Matchday 9",
    10:"Matchday 10",11:"Round of 32",12:"Round of 16",
    13:"Quarter-final",14:"Semi-finals",15:"Final",
}

FLAG = {
    "Mexico":"🇲🇽","South Africa":"🇿🇦","South Korea":"🇰🇷","Czech Republic":"🇨🇿",
    "Canada":"🇨🇦","Bosnien-Herzegowina":"🇧🇦","USA":"🇺🇸","Paraguay":"🇵🇾",
    "Qatar":"🇶🇦","Switzerland":"🇨🇭","Brazil":"🇧🇷","Morocco":"🇲🇦",
    "Haiti":"🇭🇹","Scotland":"🏴󠁧󠁢󠁳󠁣󠁴󠁿","Australia":"🇦🇺","Türkiye":"🇹🇷",
    "Argentina":"🇦🇷","France":"🇫🇷","Germany":"🇩🇪","Spain":"🇪🇸",
    "England":"🏴󠁧󠁢󠁥󠁮󠁧󠁿","Portugal":"🇵🇹","Netherlands":"🇳🇱","Belgium":"🇧🇪",
    "Uruguay":"🇺🇾","Colombia":"🇨🇴","Japan":"🇯🇵","Senegal":"🇸🇳",
    "Serbia":"🇷🇸","Croatia":"🇭🇷","Denmark":"🇩🇰","Poland":"🇵🇱",
    "Ecuador":"🇪🇨","Peru":"🇵🇪","Chile":"🇨🇱","Iran":"🇮🇷",
    "Saudi Arabia":"🇸🇦","New Zealand":"🇳🇿","Wales":"🏴󠁧󠁢󠁷󠁬󠁳󠁿","Ukraine":"🇺🇦",
    "Austria":"🇦🇹","Tunisia":"🇹🇳","Egypt":"🇪🇬","Nigeria":"🇳🇬",
    "Ghana":"🇬🇭","Cameroon":"🇨🇲","Venezuela":"🇻🇪","Bolivia":"🇧🇴",
    "Panama":"🇵🇦","Costa Rica":"🇨🇷","Honduras":"🇭🇳","Jamaica":"🇯🇲",
    "Indonesia":"🇮🇩","China":"🇨🇳","India":"🇮🇳",
}

HEADERS = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def get(url, params=None):
    r = requests.get(url, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def flag(team):
    return FLAG.get(team, "🏳️")

def result_emoji(result, home_pred, away_pred):
    """Return ✅ if prediction exactly matches result, 🎯 if tendency correct, ❌ if wrong."""
    if not result or result == "---" or not home_pred or not away_pred:
        return ""
    try:
        rh, ra = map(int, result.split("-"))
        ph, pa = map(int, home_pred.split("-"))
        if rh == ph and ra == pa:
            return "✅"  # exact score
        # correct tendency
        if (rh > ra and ph > pa) or (rh < ra and ph < pa) or (rh == ra and ph == pa):
            return "🎯"
        return "❌"
    except Exception:
        return ""

# ── Scrapers ──────────────────────────────────────────────────────────────────

def fetch_leaderboard(matchday=None):
    params = {"tippsaisonId": SEASON_ID}
    if matchday:
        params["spieltagIndex"] = matchday
    soup = get(f"{BASE}/leaderboard", params)
    players = []
    for row in soup.select("table tr"):
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        pos_text = cells[0].get_text(strip=True).replace(".", "")
        name = cells[2].get_text(strip=True)
        if not name or not pos_text.isdigit():
            continue
        players.append({
            "pos":    int(pos_text),
            "name":   name,
            "md_pts": cells[-4].get_text(strip=True) or "0",
            "bonus":  cells[-3].get_text(strip=True) or "0",
            "wins":   cells[-2].get_text(strip=True) or "0",
            "total":  cells[-1].get_text(strip=True) or "0",
        })
    return players


def fetch_predictions(matchday=1):
    """
    Scrape the leaderboard page which shows each player's prediction per match.
    Returns:
      matches: list of {label, result}  (e.g. "MEX RSA", "1-0")
      players: list of {name, preds: [pred_per_match], md_pts, total}
    """
    params = {"tippsaisonId": SEASON_ID, "spieltagIndex": matchday}
    soup = get(f"{BASE}/leaderboard", params)

    table = soup.find("table")
    if not table:
        return [], []

    rows = table.find_all("tr")
    if not rows:
        return [], []

    # ── Parse header row for match labels & results ──
    header_cells = rows[0].find_all("th") if rows[0].find("th") else []
    # The match columns are in the header as links like "MEX RSA 1-0"
    # Extract from the leaderboard page heading table
    matches = []
    # Find all th/td in first two rows to locate match columns
    for row in rows[:3]:
        for cell in row.find_all(["th","td"]):
            txt = cell.get_text(strip=True)
            # Match pattern: "ABC DEF 1-0" or "ABC DEF ---"
            m = re.match(r'^([A-Z]{2,4})\s+([A-Z]{2,4})\s+([\d\-]+|---)$', txt)
            if m:
                matches.append({"label": f"{m.group(1)} {m.group(2)}", "result": m.group(3)})

    # ── Parse player rows ──
    players = []
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        pos_text = cells[0].get_text(strip=True).replace(".", "")
        if not pos_text.isdigit():
            continue
        name = cells[2].get_text(strip=True)
        if not name:
            continue

        # Prediction columns: cells[3] to cells[3+len(matches)-1]
        preds = []
        for i in range(len(matches)):
            col = 3 + i
            if col < len(cells):
                raw = cells[col].get_text(strip=True)
                # Sometimes score and points are concatenated e.g. "1-09" → split on digit after score
                m2 = re.match(r'^(\d+-\d+)', raw)
                preds.append(m2.group(1) if m2 else raw[:3] if raw else "—")
            else:
                preds.append("—")

        md_pts = cells[-4].get_text(strip=True) or "0"
        total  = cells[-1].get_text(strip=True) or "0"

        players.append({
            "pos":    int(pos_text),
            "name":   name,
            "preds":  preds,
            "md_pts": md_pts,
            "total":  total,
        })

    return matches, players


def fetch_schedule(matchday=None):
    params = {"tippsaisonId": SEASON_ID}
    if matchday:
        params["spieltagIndex"] = matchday
    soup = get(f"{BASE}/schedule", params)
    matches = []
    for row in soup.select("table tr"):
        cells = row.find_all("td")
        if len(cells) < 6:
            continue
        date   = cells[0].get_text(strip=True)
        home   = cells[2].get_text(strip=True)
        away   = cells[3].get_text(strip=True)
        group  = cells[4].get_text(strip=True)
        result = cells[5].get_text(strip=True)
        if not home or not away:
            continue
        matches.append({"date":date,"home":home,"away":away,"group":group,"result":result})
    return matches

# ── Formatters ────────────────────────────────────────────────────────────────

def format_leaderboard(players, title):
    if not players:
        return "⚠️ Could not load leaderboard."
    medal = {1:"🥇",2:"🥈",3:"🥉"}
    lines = [f"🏆 *{title}*\n",
             "`Pos  Name              Pts  Tot`",
             "`───  ────────────────  ───  ───`"]
    for p in players:
        icon = medal.get(p["pos"], f"{p['pos']:>3}.")
        name = p["name"][:16].ljust(16)
        lines.append(f"`{icon}  {name}  {p['md_pts']:>3}  {p['total']:>3}`")
    lines.append("\n_P = Matchday pts · T = Total pts_")
    return "\n".join(lines)


def format_predictions(matches, players, label):
    """
    For each match, show the actual score and each player's prediction with emoji.
    """
    if not matches:
        return "⚠️ No prediction data found."

    lines = [f"🔮 *Predictions — {label}*\n"]

    for i, match in enumerate(matches):
        result = match["result"]
        result_str = f"*{result}*" if result != "---" else "_not played yet_"
        lines.append(f"⚽ *{match['label']}* → {result_str}")

        for p in players:
            pred = p["preds"][i] if i < len(p["preds"]) else "—"
            if pred and pred not in ("—", "---", ""):
                emoji = result_emoji(result, pred, pred) if "-" in pred else ""
                # Actually compare prediction vs result properly
                if result and result != "---" and "-" in pred:
                    try:
                        rh, ra = map(int, result.split("-"))
                        ph, pa = map(int, pred.split("-"))
                        if rh == ph and ra == pa:
                            em = "✅"
                        elif (rh>ra and ph>pa) or (rh<ra and ph<pa) or (rh==ra and ph==pa):
                            em = "🎯"
                        else:
                            em = "❌"
                    except Exception:
                        em = ""
                else:
                    em = ""
                lines.append(f"  {em} *{p['name']}*: {pred}")
            else:
                lines.append(f"  ➖ *{p['name']}*: no tip")

        lines.append("")  # blank line between matches

    lines.append("_✅ exact · 🎯 correct tendency · ❌ wrong_")
    return "\n".join(lines)


def format_today(all_matches, all_preds_by_md):
    now = datetime.now()
    date_prefixes = [f"{now.month}/{now.day}/{str(now.year)[2:]}",
                     f"{now.month}/{now.day}/{now.year}"]

    today = [m for m in all_matches if any(m["date"].startswith(p) for p in date_prefixes)]
    if not today:
        return "📅 No matches today."

    lines = [f"📅 *Today's Matches — {now.strftime('%b %d')}*\n"]
    for m in today:
        hf = flag(m["home"])
        af = flag(m["away"])
        if m["result"] and m["result"] != "---":
            lines.append(f"{hf} {m['home']} *{m['result']}* {m['away']} {af}")
        else:
            time_part = " ".join(m["date"].split()[-2:])
            lines.append(f"{hf} {m['home']} vs {m['away']} {af}  _{time_part}_")

        # Show predictions for this match from the predictions data
        match_key = f"{m['home'][:3].upper()} {m['away'][:3].upper()}"
        for md_matches, players in all_preds_by_md:
            for i, pm in enumerate(md_matches):
                if pm["label"] == match_key or match_key in pm["label"]:
                    for p in players:
                        pred = p["preds"][i] if i < len(p["preds"]) else "—"
                        if pred and pred not in ("—","---",""):
                            if m["result"] and m["result"] != "---" and "-" in pred:
                                try:
                                    rh,ra = map(int, m["result"].split("-"))
                                    ph,pa = map(int, pred.split("-"))
                                    if rh==ph and ra==pa: em="✅"
                                    elif (rh>ra and ph>pa) or (rh<ra and ph<pa) or (rh==ra and ph==pa): em="🎯"
                                    else: em="❌"
                                except: em=""
                            else:
                                em="🔮"
                            lines.append(f"  {em} {p['name']}: {pred}")
                        else:
                            lines.append(f"  ➖ {p['name']}: no tip")
        lines.append("")
    return "\n".join(lines)

# ── Handlers ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome to the WorldPrediction2026 Bot!*\n\n"
        "Commands:\n"
        "• /leaderboard — Current standings\n"
        "• /matchday 1 — Standings for matchday N\n"
        "• /scores — Scores + everyone's predictions\n"
        "• /scores 2 — Predictions for matchday 2\n"
        "• /today — Today's matches + predictions\n"
        "• /help — All commands",
        parse_mode="Markdown"
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Commands*\n\n"
        "/leaderboard — Overall standings\n"
        "/matchday `<N>` — Standings for matchday N (1–15)\n"
        "/scores — Scores & predictions for Matchday 1\n"
        "/scores `<N>` — Scores & predictions for matchday N\n"
        "/today — Today's matches & all predictions",
        parse_mode="Markdown"
    )

async def cmd_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching leaderboard…")
    try:
        players = fetch_leaderboard()
        text = format_leaderboard(players, "WorldPrediction2026 — Overall")
    except Exception as e:
        logger.error(e)
        text = f"❌ Error: {e}"
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_matchday(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /matchday `<N>` e.g. `/matchday 2`", parse_mode="Markdown")
        return
    md = int(args[0])
    if not 1 <= md <= 15:
        await update.message.reply_text("❌ Matchday must be 1–15.")
        return
    label = MATCHDAY_LABELS.get(md, f"Matchday {md}")
    await update.message.reply_text(f"⏳ Fetching {label}…")
    try:
        players = fetch_leaderboard(matchday=md)
        text = format_leaderboard(players, f"WorldPrediction2026 — {label}")
    except Exception as e:
        logger.error(e)
        text = f"❌ Error: {e}"
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_scores(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    md = int(args[0]) if args and args[0].isdigit() else 1
    if not 1 <= md <= 15:
        await update.message.reply_text("❌ Matchday must be 1–15.")
        return
    label = MATCHDAY_LABELS.get(md, f"Matchday {md}")
    await update.message.reply_text(f"⏳ Fetching scores & predictions for {label}…")
    try:
        matches, players = fetch_predictions(matchday=md)
        text = format_predictions(matches, players, label)
    except Exception as e:
        logger.error(e)
        text = f"❌ Error: {e}"
    # Telegram has 4096 char limit — split if needed
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts:
            await update.message.reply_text(part, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching today's matches…")
    try:
        all_matches = []
        all_preds_by_md = []
        for md in range(1, 4):
            all_matches.extend(fetch_schedule(matchday=md))
            mp = fetch_predictions(matchday=md)
            all_preds_by_md.append(mp)
        text = format_today(all_matches, all_preds_by_md)
    except Exception as e:
        logger.error(e)
        text = f"❌ Error: {e}"
    await update.message.reply_text(text, parse_mode="Markdown")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("⚠️  Set TELEGRAM_BOT_TOKEN env var or paste your token into BOT_TOKEN.")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("matchday",    cmd_matchday))
    app.add_handler(CommandHandler("scores",      cmd_scores))
    app.add_handler(CommandHandler("today",       cmd_today))
    logger.info("Bot is running…")
    app.run_polling()

if __name__ == "__main__":
    main()
