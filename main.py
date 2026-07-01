import os
import discord
import sqlite3
import requests
import asyncio
import matplotlib.pyplot as plt
import io
from datetime import datetime
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
HEADERS = {"x-apisports-key": API_KEY}

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

    if match["fixture"]["status"]["short"] != "FT":
        return None

    home = match["teams"]["home"]["name"]
    away = match["teams"]["away"]["name"]
    gh = match["goals"]["home"]
    ga = match["goals"]["away"]

    if gh > ga:
        return {"winner": home}
    elif ga > gh:
        return {"winner": away}
    else:
        return {"winner": "DRAW"}

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
    yes_pool INTEGER,
    no_pool INTEGER,
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

c.execute("""
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id INTEGER,
    timestamp TEXT,
    yes_price REAL
)
""")

conn.commit()

# =========================
# USERS
# =========================
def get_user(user_id):
    c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    r = c.fetchone()

    if not r:
        c.execute("INSERT INTO users VALUES (?, ?)", (user_id, 1000))
        conn.commit()
        return 1000

    return r[0]

# =========================
# PRICE SAVE
# =========================
def save_price(market_id, yes_price):
    now = datetime.utcnow().strftime("%H:%M:%S")

    c.execute("""
        INSERT INTO price_history (market_id, timestamp, yes_price)
        VALUES (?, ?, ?)
    """, (market_id, now, yes_price))

    conn.commit()

# =========================
# COMMANDS BASE
# =========================

@bot.command()
async def ping(ctx):
    await ctx.send("pong 🟢")

@bot.command()
async def balance(ctx):
    bal = get_user(str(ctx.author.id))
    await ctx.send(f"💰 {bal}")

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

    full = f"{league}_{match_key}"

    c.execute("""
        INSERT INTO markets VALUES (NULL, ?, 0, 0, 0, 1, ?, 0, NULL)
    """, (question, full))

    conn.commit()

    await ctx.send(f"📊 Mercato creato {full}")

# =========================
# MARKETS VIEW
# =========================

@bot.command()
async def markets(ctx):

    c.execute("SELECT id, question, yes_pool, no_pool FROM markets WHERE active=1")
    rows = c.fetchall()

    if not rows:
        await ctx.send("📭 Nessun mercato")
        return

    msg = "📊 MERCATI\n\n"

    for mid, q, yes, no in rows:
        total = yes + no

        if total == 0:
            yp, np = 50, 50
        else:
            yp = round((yes / total) * 100, 2)
            np = round((no / total) * 100, 2)

        msg += f"ID {mid} | {q}\nYES {yp}% | NO {np}%\n\n"

    await ctx.send(msg)

# =========================
# BUY + PRICE UPDATE
# =========================

@bot.command()
async def buy(ctx, market_id: int, side: str, amount: int):

    user_id = str(ctx.author.id)
    side = side.upper()

    c.execute("SELECT active FROM markets WHERE id=?", (market_id,))
    m = c.fetchone()

    if not m or m[0] == 0:
        await ctx.send("❌ Mercato chiuso")
        return

    bal = get_user(user_id)

    if bal < amount:
        await ctx.send("❌ Fondi insufficienti")
        return

    c.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, user_id))

    if side == "YES":
        c.execute("UPDATE markets SET yes_pool = yes_pool + ?, total_pool = total_pool + ? WHERE id=?",
                  (amount, amount, market_id))
    else:
        c.execute("UPDATE markets SET no_pool = no_pool + ?, total_pool = total_pool + ? WHERE id=?",
                  (amount, amount, market_id))

    c.execute("""
        INSERT INTO trades (user_id, market_id, side, amount)
        VALUES (?, ?, ?, ?)
    """, (user_id, market_id, side, amount))

    # 📊 PRICE UPDATE
    c.execute("SELECT yes_pool, no_pool FROM markets WHERE id=?", (market_id,))
    yes, no = c.fetchone()

    total = yes + no
    yes_price = 50 if total == 0 else (yes / total) * 100

    save_price(market_id, yes_price)

    conn.commit()

    await ctx.send("📈 Trade OK")

# =========================
# CHART (REAL IMAGE)
# =========================

@bot.command()
async def chart(ctx, market_id: int):

    c.execute("""
        SELECT timestamp, yes_price
        FROM price_history
        WHERE market_id=?
        ORDER BY id DESC
        LIMIT 30
    """, (market_id,))

    data = list(reversed(c.fetchall()))

    if not data:
        await ctx.send("❌ Nessun dato storico")
        return

    times = [d[0] for d in data]
    prices = [d[1] for d in data]

    plt.figure(figsize=(8,4))

    plt.plot(prices, linewidth=2)

    plt.title("📊 YES Price Trend", fontsize=14)
    plt.xlabel("Time")
    plt.ylabel("YES %")

    plt.grid(True, alpha=0.3)

    plt.xticks(range(0, len(times), max(1, len(times)//5)),
               [times[i] for i in range(0, len(times), max(1, len(times)//5))],
               rotation=45)

    buffer = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buffer, format="png")
    buffer.seek(0)

    await ctx.send(file=discord.File(buffer, "chart.png"))

    plt.close()

# =========================
# PAYOUT
# =========================

def payout_market(market_id, result):

    c.execute("SELECT user_id, side, amount FROM trades WHERE market_id=?", (market_id,))
    trades = c.fetchall()

    winners = []
    losers_pool = 0

    for u, s, a in trades:
        if s == result:
            winners.append((u, a))
        else:
            losers_pool += a

    total_win = sum(a for _, a in winners)

    if total_win == 0:
        return

    for u, a in winners:
        share = a / total_win
        payout = int(a + share * losers_pool)

        c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (payout, u))

    conn.commit()

# =========================
# RESOLVER LOOP
# =========================

async def resolve():

    await bot.wait_until_ready()

    while not bot.is_closed():

        try:
            c.execute("SELECT id, match_key FROM markets WHERE active=1 AND resolved=0")
            markets = c.fetchall()

            for mid, mk in markets:

                c.execute("SELECT resolved FROM markets WHERE id=?", (mid,))
                if c.fetchone()[0] == 1:
                    continue

                try:
                    league, teams = mk.split("_", 1)
                    t1, t2 = teams.split("_")
                except:
                    continue

                res = get_match_result(t1, t2)

                if not res:
                    continue

                winner = res["winner"]

                if winner not in [t1, t2]:
                    continue

                final = "YES" if winner == t1 else "NO"

                c.execute("""
                    UPDATE markets
                    SET active=0,
                        resolved=1,
                        result=?
                    WHERE id=?
                """, (final, mid))

                conn.commit()

                payout_market(mid, final)

                print(f"[CLOSED] {mid} -> {final}")

        except Exception as e:
            print("ERR:", e)

        await asyncio.sleep(120)

# =========================
# READY
# =========================

@bot.event
async def on_ready():
    print(f"Bot online {bot.user}")
    bot.loop.create_task(resolve())

# =========================
# RUN
# =========================

bot.run(token)
