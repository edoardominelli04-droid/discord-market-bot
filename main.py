import os
import discord
import sqlite3
from discord.ext import commands

token = os.environ.get("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# DATABASE
conn = sqlite3.connect("bot.db")
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    balance INTEGER
)
""")
conn.commit()

def get_user(user_id):
    c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    result = c.fetchone()

    if result is None:
        c.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, 1000))
        conn.commit()
        return 1000

    return result[0]

@bot.command()
async def ping(ctx):
    await ctx.send("pong 🟢")

@bot.command()
async def balance(ctx):
    bal = get_user(str(ctx.author.id))
    await ctx.send(f"💰 Il tuo saldo è: {bal} crediti")

@bot.event
async def on_ready():
    print(f"Bot online come {bot.user}")

bot.run(token)
