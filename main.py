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
# DATABASE SQLITE
# =========================
conn = sqlite3.connect("bot.db")
c = conn.cursor()

# USERS TABLE
c.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    balance INTEGER
)
""")

# MARKETS TABLE
c.execute("""
CREATE TABLE IF NOT EXISTS markets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT,
    yes_price REAL,
    no_price REAL,
    total_pool INTEGER,
    active INTEGER
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
# COMMANDS
# =========================

@bot.command()
async def ping(ctx):
    await ctx.send("pong 🟢")

@bot.command()
async def balance(ctx):
    bal = get_user(str(ctx.author.id))
    await ctx.send(f"💰 Il tuo saldo è: {bal} crediti")

@bot.command()
async def create(ctx, *, question):
    c.execute(
        "INSERT INTO markets (question, yes_price, no_price, total_pool, active) VALUES (?, ?, ?, ?, ?)",
        (question, 50.0, 50.0, 0, 1)
    )
    conn.commit()

    await ctx.send(
        f"📊 Mercato creato:\n"
        f"**{question}**\n"
        f"YES: 50% | NO: 50%"
    )

# =========================
# BOT READY
# =========================

@bot.event
async def on_ready():
    print(f"Bot online come {bot.user}")

# =========================
# RUN
# =========================
bot.run(token)
