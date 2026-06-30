import os

print("ENV KEYS:", list(os.environ.keys()))
print("DISCORD_TOKEN RAW:", os.environ.get("DISCORD_TOKEN"))

token = os.environ.get("DISCORD_TOKEN")

if not token:
    raise Exception("DISCORD_TOKEN NON VISTA DA RAILWAY")

import discord
from discord.ext import commands

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print("BOT ONLINE:", bot.user)

bot.run(token)
