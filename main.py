import os
import discord
import sqlite3
from discord.ext import commands

# TOKEN
token = os.environ.get("DISCORD_TOKEN")

# DISCORD SETUP
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# DATABASE
# =========================
conn = sqlite3.connect("bot.db")
c = conn.cursor()

# USERS
c.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    balance INTEGER
)
""")

# MARKETS (AUTO READY)
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
# BASIC COMMANDS
# =========================

@bot.command()
async def ping(ctx):
    await ctx.send("pong 🟢")

@bot.command()
async def balance(ctx):
    bal = get_user(str(ctx.author.id))
    await ctx.send(f"💰 Il tuo saldo è: {bal} crediti")

# =========================
# CREATE MARKET (AUTO READY)
# =========================

@bot.command()
async def create(ctx, match_key: str, *, question):
    c.execute(
        "INSERT INTO markets (question, yes_price, no_price, total_pool, active, match_key, resolved) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (question, 50.0, 50.0, 0, 1, match_key, 0)
    )
    conn.commit()

    await ctx.send(
        f"📊 Mercato creato!\n"
        f"❓ {question}\n"
        f"🆔 Match ID: {match_key}\n"
        f"YES: 50% | NO: 50%"
    )

# =========================
# BUY SYSTEM
# =========================

@bot.command()
async def buy(ctx, market_id: int, side: str, amount: int):
    side = side.lower()

    if side not in ["yes", "no"]:
        await ctx.send("❌ Usa YES o NO")
        return

    c.execute("SELECT yes_price, no_price, total_pool FROM markets WHERE id=?", (market_id,))
    market = c.fetchone()

    if not market:
        await ctx.send("❌ Mercato non trovato")
        return

    yes_price, no_price, total_pool = market

    user_id = str(ctx.author.id)
    bal = get_user(user_id)

    if amount > bal:
        await ctx.send("❌ Non hai abbastanza crediti")
        return

    # saldo utente
    new_bal = bal - amount
    c.execute("UPDATE users SET balance=? WHERE user_id=?", (new_bal, user_id))

    # update mercato
    total_pool += amount

    if side == "yes":
        yes_price += amount * 0.05
        no_price -= amount * 0.03
    else:
        no_price += amount * 0.05
        yes_price -= amount * 0.03

    yes_price = max(1, min(99, yes_price))
    no_price = max(1, min(99, no_price))

    c.execute("""
        UPDATE markets
        SET yes_price=?, no_price=?, total_pool=?
        WHERE id=?
    """, (yes_price, no_price, total_pool, market_id))

    conn.commit()

    await ctx.send(
        f"📈 Acquisto OK!\n"
        f"Market {market_id} | {side.upper()} +{amount}\n"
        f"YES: {yes_price:.1f}% | NO: {no_price:.1f}%"
    )

# =========================
# MARKETS LIST
# =========================

@bot.command()
async def markets(ctx):
    c.execute("SELECT id, question, yes_price, no_price, total_pool FROM markets WHERE active=1")
    rows = c.fetchall()

    if not rows:
        await ctx.send("📭 Nessun mercato attivo")
        return

    msg = "📊 **MERCATI ATTIVI**\n\n"

    for m in rows:
        mid, q, yes, no, pool = m
        msg += (
            f"**ID {mid}**\n"
            f"{q}\n"
            f"YES: {yes:.1f}% | NO: {no:.1f}%\n"
            f"Pool: {pool}\n\n"
        )

    await ctx.send(msg)

# =========================
# SINGLE MARKET
# =========================

@bot.command()
async def market(ctx, market_id: int):
    c.execute("SELECT id, question, yes_price, no_price, total_pool FROM markets WHERE id=?", (market_id,))
    m = c.fetchone()

    if not m:
        await ctx.send("❌ Mercato non trovato")
        return

    mid, q, yes, no, pool = m

    msg = (
        f"📊 **MERCATO {mid}**\n\n"
        f"❓ {q}\n\n"
        f"🟢 YES: {yes:.1f}%\n"
        f"🔴 NO: {no:.1f}%\n\n"
        f"💰 Pool: {pool}\n"
    )

    await ctx.send(msg)

# =========================
# READY
# =========================

@bot.event
async def on_ready():
    print(f"Bot online come {bot.user}")

# =========================
# RUN
# =========================

bot.run(token)
