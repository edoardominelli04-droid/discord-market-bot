import os
import discord
import sqlite3
import requests
import asyncio
from discord.ext import commands

# =========================
# TOKEN
# =========================
token = os.environ.get("DISCORD_TOKEN")

# =========================
# DISCORD SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# API FOOTBALL
# =========================
API_KEY = os.environ.get("FOOTBALL_API_KEY")

HEADERS = {
    "x-apisports-key": API_KEY
}

def get_match_result(team1, team2):
    url = "https://v3.football.api-sports.io/fixtures"

    params = {"search": f"{team1} {team2}"}

    try:
        r = requests.get(url, headers=HEADERS, params=params)
        data = r.json()
    except:
        return None

    if "response" not in data or not data["response"]:
        return None

    match = data["response"][0]

    status = match["fixture"]["status"]["short"]
    home = match["teams"]["home"]["name"]
    away = match["teams"]["away"]["name"]
    goals_home = match["goals"]["home"]
    goals_away = match["goals"]["away"]

    if status != "FT":
        return None

    if goals_home > goals_away:
        winner = home
    elif goals_away > goals_home:
        winner = away
    else:
        winner = "DRAW"

    return {"winner": winner}

# =========================
# DATABASE
# =========================
conn = sqlite3.connect("bot.db")
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    balance INTEGER
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS markets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT,
    yes_price REAL,
    no_price REAL,
    total_pool INTEGER,
    active INTEGER,
    match_key TEXT,
    resolved INTEGER DEFAULT 0,
    result TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    market_id INTEGER,
    side TEXT,
    amount INTEGER
)
""")

conn.commit()

# =========================
# USERS
# =========================
def get_user(user_id):
    c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    result = c.fetchone()

    if result is None:
        c.execute("INSERT INTO users VALUES (?, ?)", (user_id, 1000))
        conn.commit()
        return 1000

    return result[0]

# =========================
# COMMANDS
# =========================

@bot.command()
async def ping(ctx):
    await ctx.send("pong 🟢")

@bot.command()
async def balance(ctx):
    bal = get_user(str(ctx.author.id))
    await ctx.send(f"💰 {bal}")

@bot.command()
async def checkapi(ctx):
    if os.environ.get("FOOTBALL_API_KEY"):
        await ctx.send("✅ API OK")
    else:
        await ctx.send("❌ API MANCANTE")

# =========================
# CREATE MARKET
# =========================

@bot.command()
async def create(ctx, league: str, match_key: str, *, question):
    league = league.upper()

    allowed = ["SERIEA", "EPL", "LA_LIGA", "BUNDESLIGA", "LIGUE1", "UCL"]

    if league not in allowed:
        await ctx.send("❌ Lega non valida")
        return

    full_match_key = f"{league}_{match_key}"

    c.execute("""
        INSERT INTO markets VALUES (NULL, ?, 50, 50, 0, 1, ?, 0, NULL)
    """, (question, full_match_key))

    conn.commit()

    await ctx.send(f"📊 Mercato creato {full_match_key}")

# =========================
# BUY (FIX ANTI-BUG)
# =========================

@bot.command()
async def buy(ctx, market_id: int, side: str, amount: int):
    user_id = str(ctx.author.id)
    side = side.upper()

    # check mercato attivo
    c.execute("SELECT active FROM markets WHERE id=?", (market_id,))
    market = c.fetchone()

    if not market or market[0] == 0:
        await ctx.send("❌ Mercato chiuso")
        return

    bal = get_user(user_id)

    if bal < amount:
        await ctx.send("❌ Fondi insufficienti")
        return

    # update balance sicuro
    c.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, user_id))

    c.execute("""
        INSERT INTO trades (user_id, market_id, side, amount)
        VALUES (?, ?, ?, ?)
    """, (user_id, market_id, side, amount))

    conn.commit()

    await ctx.send("📈 Trade registrato")

# =========================
# PAYOUT SAFE
# =========================

def payout_market(market_id, result):
    c.execute("SELECT user_id, side, amount FROM trades WHERE market_id=?", (market_id,))
    trades = c.fetchall()

    winners = []
    losers_pool = 0

    for user_id, side, amount in trades:
        if side == result:
            winners.append((user_id, amount))
        else:
            losers_pool += amount

    total_win = sum([a for _, a in winners])

    if total_win == 0 or losers_pool == 0:
        return

    for user_id, amount in winners:
        share = amount / total_win
        payout = int(share * losers_pool + amount)

        c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (payout, user_id))

    conn.commit()

# =========================
# RESOLVER (FIXED)
# =========================

async def resolve_markets():
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            c.execute("SELECT id, match_key FROM markets WHERE active=1 AND resolved=0")
            markets = c.fetchall()

            for market_id, match_key in markets:

                # prevent double resolve
                c.execute("SELECT resolved FROM markets WHERE id=?", (market_id,))
                if c.fetchone()[0] == 1:
                    continue

                try:
                    league, teams = match_key.split("_", 1)
                    team1, team2 = teams.split("_")
                except:
                    continue

                result = get_match_result(team1, team2)

                if not result:
                    continue

                winner = result["winner"]

                if winner not in [team1, team2]:
                    continue

                final_result = "YES" if winner == team1 else "NO"

                c.execute("""
                    UPDATE markets
                    SET active=0,
                        resolved=1,
                        result=?
                    WHERE id=?
                """, (final_result, market_id))

                conn.commit()

                print(f"[RESOLVE] {market_id} -> {final_result}")

                payout_market(market_id, final_result)

        except Exception as e:
            print("ERROR:", e)

        await asyncio.sleep(120)

# =========================
# READY
# =========================

@bot.event
async def on_ready():
    print(f"Bot online {bot.user}")
    bot.loop.create_task(resolve_markets())

# =========================
# RUN
# =========================

bot.run(token)
