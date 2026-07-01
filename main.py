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

    params = {
        "search": f"{team1} {team2}"
    }

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

    return {
        "home": home,
        "away": away,
        "winner": winner
    }

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
    resolved INTEGER DEFAULT 0
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
        c.execute(
            "INSERT INTO users (user_id, balance) VALUES (?, ?)",
            (user_id, 1000)
        )
        conn.commit()
        return 1000

    return result[0]

# =========================
# COMMANDS BASE
# =========================

@bot.command()
async def ping(ctx):
    await ctx.send("pong 🟢")

@bot.command()
async def balance(ctx):
    bal = get_user(str(ctx.author.id))
    await ctx.send(f"💰 Il tuo saldo è: {bal} crediti")

@bot.command()
async def checkapi(ctx):
    key = os.environ.get("FOOTBALL_API_KEY")

    if key:
        await ctx.send("✅ FOOTBALL_API_KEY presente")
    else:
        await ctx.send("❌ FOOTBALL_API_KEY mancante")

# =========================
# CREATE MARKET
# =========================

@bot.command()
async def create(ctx, league: str, match_key: str, *, question):
    league = league.upper()

    allowed_leagues = ["SERIEA", "EPL", "LA_LIGA", "BUNDESLIGA", "LIGUE1", "UCL"]

    if league not in allowed_leagues:
        await ctx.send("❌ Lega non valida")
        return

    full_match_key = f"{league}_{match_key}"

    c.execute(
        "INSERT INTO markets (question, yes_price, no_price, total_pool, active, match_key, resolved) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (question, 50.0, 50.0, 0, 1, full_match_key, 0)
    )
    conn.commit()

    await ctx.send(f"📊 Mercato creato: {full_match_key}")

# =========================
# AUTO RESOLVE ENGINE
# =========================

async def resolve_markets():
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            c.execute("SELECT id, match_key FROM markets WHERE active=1 AND resolved=0")
            markets = c.fetchall()

            for market in markets:
                market_id, match_key = market

                try:
                    league, teams = match_key.split("_", 1)
                    team1, team2 = teams.split("_")
                except:
                    continue

                result = get_match_result(team1, team2)

                if result is None:
                    continue

                winner = result["winner"]

                # chiusura mercato
                c.execute("""
                    UPDATE markets
                    SET active=0, resolved=1
                    WHERE id=?
                """, (market_id,))

                conn.commit()

                print(f"Market {market_id} chiuso. Winner: {winner}")

        except Exception as e:
            print("Resolver error:", e)

        await asyncio.sleep(120)  # ogni 2 minuti

# =========================
# READY EVENT
# =========================

@bot.event
async def on_ready():
    print(f"Bot online come {bot.user}")

    # avvia loop automatico
    bot.loop.create_task(resolve_markets())

# =========================
# RUN
# =========================

bot.run(token)
