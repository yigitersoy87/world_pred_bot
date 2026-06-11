"""
Kicktipp WorldPrediction2026 — Telegram Bot
============================================
Commands:
  /start          - Welcome message
  /leaderboard    - Overall leaderboard
  /matchday <N>   - Leaderboard for matchday N (1-15)
  /scores         - Scores + all predictions for Matchday 1
  /scores <N>     - Scores + all predictions for Matchday N
  /today          - Today's matches + predictions
  /help           - Show available commands

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
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
BASE      = "https://www.kicktipp.com/worldprediction2026"
SEASON_ID = "4343234"

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
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_soup(url, params=None):
    r = requests.get(url, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def flag(team):
    return FLAG.get(team, "🏳️")

def split_pred_pts(raw):
    """
    Kicktipp concatenates prediction + points into one string.
    e.g. "1-09" → pred="1-0", pts="9"
         "2-13" → pred="2-1", pts="3"
         "2-02" → pred="2-0", pts="2"
         "---"  → pred="---", pts=""
         ""     → pred="",    pts=""
    """
    if not raw or raw.strip() in ("", "---"):
        return raw.strip(), ""
    # Match score pattern: digit-digit then optional trailing digits (pts)
    m = re.match(r'^(\d+-\d+)(\d*)$', raw.strip())
    if m:
        return m.group(1), m.group(2)
    return raw.strip(), ""

def pred_emoji(result, pred):
    """✅ exact · 🎯 tendency · ❌ wrong · '' if not applicable"""
    if not result or result == "---" or not pred or pred == "---":
        return "🔮"
    try:
        rh, ra = map(int, result.split("-"))
        ph, pa = map(int, pred.split("-"))
        if rh == ph and ra == pa:
            return "✅"
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
    soup = get_soup(f"{BASE}/leaderboard", params)
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
            "total":  cells[-1].get_text(strip=True) or "0",
        })
    return players


def fetch_predictions(matchday=1):
    """
    Returns:
      matches: [{"label": "MEX RSA", "result": "1-0"}, ...]
      players: [{"name": "Yiko", "preds": ["2-1", "---", ...], "pts": ["3","",...]}, ...]

    Key fix: Kicktipp puts pred+pts concatenated in each cell e.g. "1-09".
    We split them with split_pred_pts().

    The match headers are in the leaderboard table header row as link text like:
      "MEX RSA 1-0"  or  "KOR CZE ---"
    """
    params = {"tippsaisonId": SEASON_ID, "spieltagIndex": matchday}
    soup = get_soup(f"{BASE}/leaderboard", params)

    table = soup.find("table")
    if not table:
        return [], []

    all_rows = table.find_all("tr")
    if len(all_rows) < 2:
        return [], []

    # ── Step 1: find match columns from header links ──
    # Header cells contain links whose text is like "MEX RSA 1-0"
    matches = []
    header_row = all_rows[0]
    for cell in header_row.find_all(["th", "td"]):
        txt = cell.get_text(strip=True)
        # pattern: 3-letter 3-letter space score/---
        m = re.match(r'^([A-Z]{2,4})\s+([A-Z]{2,4})\s+([\d]+-[\d]+|---)$', txt)
        if m:
            matches.append({
                "label":  f"{m.group(1)} {m.group(2)}",
                "result": m.group(3),
            })

    if not matches:
        # fallback: also check second row
        for cell in all_rows[1].find_all(["th","td"]):
            txt = cell.get_text(strip=True)
            m = re.match(r'^([A-Z]{2,4})\s+([A-Z]{2,4})\s+([\d]+-[\d]+|---)$', txt)
            if m:
                matches.append({"label": f"{m.group(1)} {m.group(2)}", "result": m.group(3)})

    num_matches = len(matches)

    # ── Step 2: find which column index the first match prediction starts ──
    # Player rows: col0=pos, col1=+/-, col2=name, col3..col3+N-1=match preds,
    #              col[-4]=md_pts, col[-3]=bonus, col[-2]=wins, col[-1]=total
    # So pred columns are [3 .. 3+num_matches-1]
    PRED_START = 3

    # ── Step 3: parse player rows ──
    players = []
    for row in all_rows[1:]:
        cells = row.find_all("td")
        if len(cells) < PRED_START + num_matches:
            continue
        pos_text = cells[0].get_text(strip=True).replace(".", "")
        if not pos_text.isdigit():
            continue
        name = cells[2].get_text(strip=True)
        if not name:
            continue

        preds = []
        pts_list = []
        for i in range(num_matches):
            raw = cells[PRED_START + i].get_text(strip=True)
            pred, pts = split_pred_pts(raw)
            preds.append(pred)
            pts_list.append(pts)

        total = cells[-1].get_text(strip=True) or "0"

        players.append({
            "pos":    int(pos_text),
            "name":   name,
            "preds":  preds,
            "pts":    pts_list,
            "total":  total,
        })

    return matches, players


def fetch_schedule(matchday=None):
    params = {"tippsaisonId": SEASON_ID}
    if matchday:
        params["spieltagIndex"] = matchday
    soup = get_soup(f"{BASE}/schedule", params)
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
    medal = {1:"🥇", 2:"🥈", 3:"🥉"}
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
    if not matches:
        return "⚠️ No match data found for this matchday."
    if not players:
        return "⚠️ No prediction data found — predictions may not be visible yet."

    lines = [f"🔮 *Predictions — {label}*\n"]

    for i, match in enumerate(matches):
        result = match["result"]
        if result and result != "---":
            result_str = f"*{result}* (final)"
        else:
            result_str = "_not played yet_"

        lines.append(f"⚽ *{match['label']}* → {result_str}")

        for p in players:
            pred = p["preds"][i] if i < len(p["preds"]) else ""
            pts  = p["pts"][i]   if i < len(p["pts"])   else ""

            if pred and pred != "---":
                em = pred_emoji(result, pred)
                pts_str = f"  (+{pts}pts)" if pts else ""
                lines.append(f"  {em} *{p['name']}*: `{pred}`{pts_str}")
            else:
                lines.append(f"  ➖ *{p['name']}*: no tip")

        lines.append("")  # spacer between matches

    lines.append("_✅ exact · 🎯 correct tendency · ❌ wrong · 🔮 not played_")
    return "\n".join(lines)


def format_today(schedule_matches, matches, players):
    now = datetime.now()
    date_prefixes = [
        f"{now.month}/{now.day}/{str(now.year)[2:]}",
        f"{now.month}/{now.day}/{now.year}",
    ]
    today = [m for m in schedule_matches
             if any(m["date"].startswith(p) for p in date_prefixes)]

    if not today:
        return "📅 No matches today."

    lines = [f"📅 *Today — {now.strftime('%b %d')}*\n"]

    for m in today:
        hf = flag(m["home"])
        af = flag(m["away"])
        result = m["result"]

        if result and result != "---":
            lines.append(f"{hf} *{m['home']}* {result} *{m['away']}* {af}  _{m['group']}_")
        else:
            time_part = " ".join(m["date"].split()[-2:])
            lines.append(f"{hf} {m['home']} vs {m['away']} {af}  _{time_part} · {m['group']}_")

        # Match this game to prediction columns by label
        home_abbr = m["home"][:3].upper()
        away_abbr = m["away"][:3].upper()
        # Special cases
        abbr_map = {"BOS": "BIH", "TUR": "TUR", "SCO": "SCO"}
        home_abbr = abbr_map.get(home_abbr, home_abbr)
        away_abbr = abbr_map.get(away_abbr, away_abbr)

        col_idx = None
        for idx, pm in enumerate(matches):
            parts = pm["label"].split()
            if len(parts) == 2:
                if (parts[0] == home_abbr or home_abbr in parts[0]) and \
                   (parts[1] == away_abbr or away_abbr in parts[1]):
                    col_idx = idx
                    break

        if col_idx is not None:
            for p in players:
                pred = p["preds"][col_idx] if col_idx < len(p["preds"]) else ""
                pts  = p["pts"][col_idx]   if col_idx < len(p["pts"])   else ""
                if pred and pred != "---":
                    em = pred_emoji(result, pred)
                    pts_str = f" (+{pts})" if pts else ""
                    lines.append(f"  {em} {p['name']}: `{pred}`{pts_str}")
                else:
                    lines.append(f"  ➖ {p['name']}: no tip")
        lines.append("")

    lines.append("_✅ exact · 🎯 tendency · ❌ wrong · 🔮 not played_")
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
    # Split if over Telegram's 4096 char limit
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        await update.message.reply_text(chunk, parse_mode="Markdown")

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching today's matches…")
    try:
        schedule = fetch_schedule(matchday=1)
        matches, players = fetch_predictions(matchday=1)
        text = format_today(schedule, matches, players)
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
