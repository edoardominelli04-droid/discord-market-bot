import os
import discord
import sqlite3
import requests
import asyncio
import html
import re
import matplotlib.pyplot as plt
import io
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

plt.style.use("dark_background")
plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.titleweight"] = "bold"
plt.rcParams["axes.labelsize"] = 11

from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None
from discord.ext import commands

try:
    from scipy.interpolate import make_interp_spline
except Exception:
    make_interp_spline = None

import numpy as np


# =========================
# TOKEN
# =========================
token = os.environ.get("DISCORD_TOKEN")

# =========================
# DISCORD SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")

# =========================
# FOOTBALL-DATA.ORG
# =========================
FOOTBALL_DATA_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN")
BASE_URL = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": FOOTBALL_DATA_TOKEN}

# Se una quota cambia di almeno questa percentuale rispetto all'ultimo alert,
# il bot invia un messaggio nel canale del mercato.
ALERT_THRESHOLD = 15.0

# Referral automatizzato:
# premio solo se il nuovo utente resta almeno 24h nel server e fa almeno 1 trade.
REFERRAL_REWARD = 500
REFERRAL_MIN_AGE_HOURS = 24
INVITE_CACHE = {}

# Limite anti-spam/anti-exploit: massimo 3 acquisti per utente per mercato.
MAX_BUYS_PER_USER_MARKET = 3

# Canale Discord dedicato agli annunci dei nuovi mercati.
MARKET_CHANNEL_ID = 1522101664063029340
# Alias esplicito: canale #annunci-sport in cui pubblicare l'apertura dei mercati sportivi.
SPORT_ANNOUNCEMENTS_CHANNEL_ID = MARKET_CHANNEL_ID

# Ruolo Discord da pingare quando viene pubblicato un nuovo mercato.
MARKET_ROLE_ID = 1522125298345447546
# Alias esplicito: ruolo giocatori da pingare negli annunci sportivi.
PLAYERS_ROLE_ID = MARKET_ROLE_ID

# Canali dedicati al calendario automatico giornaliero.
PUBLIC_CALENDAR_CHANNEL_ID = 1522149843663982753
ADMIN_CALENDAR_CHANNEL_ID = 1522150991112310874
CALENDAR_POST_HOUR = 8
CALENDAR_POST_MINUTE = 0
LAST_CALENDAR_POST_DATE = None

# Canale dedicato ai risultati dei mercati risolti automaticamente.
RESULTS_CHANNEL_ID = 1522189230128762971

# Canale dedicato alle notizie automatiche / Gazzetta v2.0.1.
GAZZETTA_CHANNEL_ID = 1522564253725364295
MARKET_PULSE_CHANNEL_ID = SPORT_ANNOUNCEMENTS_CHANNEL_ID  # market update / pulse pubblici su annunci sport

# API News / Gazzetta v2.0.2
# GNEWS_API_KEY: fonte secondaria per notizie calcistiche via GNews.
# La vecchia integrazione Sportmonks/Sofascore è stata rimossa: #gazzetta usa RSS + GNews,
# mentre !live usa ESPN scoreboard pubblico con fallback football-data.org.
GNEWS_API_KEY = os.environ.get("GNEWS_API_KEY")
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
API_FOOTBALL_HOST = os.environ.get("API_FOOTBALL_HOST", "v3.football.api-sports.io")
API_FOOTBALL_NEWS_URL = os.environ.get("API_FOOTBALL_NEWS_URL")
NEWS_LOOP_MINUTES = 30

# Canale dedicato al registro delle attività admin.
ACTIVITY_LOG_CHANNEL_ID = 1522190483713953813

# Palette colori embed v1.9.2
COLOR_BLUE = 0x2563eb          # Profilo, Portafoglio, Balance, Leaderboard
COLOR_PURPLE = 0x8b5cf6        # Mercati, Nuovo Mercato, Nuovo Evento
COLOR_PINK = 0xec4899          # Buy, Sell
COLOR_ORANGE = 0xf59e0b        # AI Prediction, Chart
COLOR_CYAN = 0x38bdf8          # Calendario
COLOR_GREEN = 0x22c55e         # YES / risolto positivo
COLOR_RED = 0xef4444           # NO / Help / errori
COLOR_WHITE = 0xf8fafc         # Comandi Admin
COLOR_GOLD = 0xfacc15          # Daily, Referral
COLOR_DARK_PINK = 0xbe185d     # Follow
COLOR_RESOLVED = 0xe5e7eb      # Mercato risolto neutro
COLOR_BLACK = 0x000000         # Eventi speciali createevent

SPECIAL_EVENT_CATEGORIES = {
    "politica": "🗳️ Politica / Elezioni",
    "f1": "🏎️ Formula 1",
    "musica": "🎵 Musica",
    "cinema": "🎬 Cinema",
    "sport": "🏆 Sport extra calcio",
    "geopolitica": "🌍 Geopolitica",
    "economia": "💼 Economia / Mercati",
    "gaming": "🎮 Gaming / eSport",
    "tv": "📺 TV / Reality",
    "attualita": "📰 Attualità"
}

COMPETITIONS = {
    "PL": "Premier League",
    "SA": "Serie A",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "FL1": "Ligue 1",
    "CL": "Champions League",
    "WC": "World Cup",
    "EC": "European Championship"
}

COMPETITION_EMOJIS = {
    "PL": "🇬🇧",
    "SA": "🇮🇹",
    "PD": "🇪🇸",
    "BL1": "🇩🇪",
    "FL1": "🇫🇷",
    "CL": "🏆",
    "WC": "🌍",
    "EC": "🇪🇺"
}


# =========================
# UTILITY
# =========================
async def send_long(ctx, msg):
    if len(msg) <= 1900:
        await ctx.send(msg)
        return

    chunks = [msg[i:i + 1900] for i in range(0, len(msg), 1900)]

    for chunk in chunks:
        await ctx.send(chunk)



def is_admin_member(member):
    """Riconosce gli admin del bot tramite permessi Discord."""
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and (perms.administrator or perms.manage_guild))


def admin_only():
    """Decoratore per comandi riservati agli admin/moderatori del server."""
    async def predicate(ctx):
        if is_admin_member(ctx.author):
            return True

        await ctx.send("⛔ Comando riservato agli admin.")
        return False

    return commands.check(predicate)

async def delete_admin_command_message(ctx):
    """Elimina il messaggio comando degli admin quando il bot ha i permessi necessari.

    Nota: per cancellare i messaggi degli admin, il bot deve avere il permesso
    Discord "Gestire messaggi" nel canale in cui viene usato il comando.
    """
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        print(f"[ADMIN DELETE] Permesso Gestire messaggi mancante nel canale {getattr(ctx.channel, 'id', 'N/D')}")
    except discord.HTTPException as e:
        print(f"[ADMIN DELETE] Impossibile eliminare il comando admin: {e}")
    except Exception as e:
        print(f"[ADMIN DELETE] Errore inatteso: {e}")

async def log_admin_activity(ctx, action, market_id=None, details=None, color=COLOR_WHITE):
    """Invia un log operativo nel canale Registro Attività."""
    channel = bot.get_channel(ACTIVITY_LOG_CHANNEL_ID)
    if not channel:
        print(f"[ACTIVITY LOG] Canale {ACTIVITY_LOG_CHANNEL_ID} non trovato.")
        return

    now = get_rome_now().strftime("%d/%m/%Y %H:%M:%S") if "get_rome_now" in globals() else datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S UTC")

    embed = discord.Embed(
        title="📜 Registro Attività",
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="📄 Operazione", value=action, inline=False)
    embed.add_field(name="👤 Admin", value=f"{ctx.author.mention} (`{ctx.author.id}`)", inline=False)
    embed.add_field(name="🕒 Data e ora", value=now, inline=True)

    if market_id is not None:
        embed.add_field(name="🆔 Mercato", value=f"#{market_id}", inline=True)

    if details:
        embed.add_field(name="📄 Dettagli", value=str(details)[:1000], inline=False)

    embed.set_footer(text="Registro automatico v1.9.2")

    try:
        await channel.send(embed=embed)
    except Exception as e:
        print(f"[ACTIVITY LOG] Errore invio log: {e}")



async def get_discord_channel(channel_id):
    """Recupera un canale anche quando non è ancora presente nella cache del bot."""
    channel = bot.get_channel(int(channel_id))
    if channel:
        return channel
    try:
        return await bot.fetch_channel(int(channel_id))
    except Exception as e:
        print(f"[CHANNEL FETCH] Impossibile recuperare il canale {channel_id}: {e}")
        return None


async def announce_sport_market_opening(market_id, question, home, away, match_id, status):
    """Pubblica l'apertura del mercato nel canale annunci sport con ping ruolo giocatori."""
    market_channel = await get_discord_channel(SPORT_ANNOUNCEMENTS_CHANNEL_ID)

    if not market_channel:
        print(f"[MARKET ANNOUNCEMENT] Canale annunci sport {SPORT_ANNOUNCEMENTS_CHANNEL_ID} non trovato.")
        return False

    announcement = discord.Embed(
        title="📣 Nuovo mercato sportivo disponibile!",
        color=COLOR_GREEN
    )
    announcement.add_field(name="🏟️ Partita", value=f"{home} vs {away}", inline=False)
    announcement.add_field(name="❓ Domanda", value=question, inline=False)
    announcement.add_field(name="🆔 Mercato", value=f"#{market_id}", inline=True)
    announcement.add_field(name="🆔 Match API", value=str(match_id), inline=True)
    announcement.add_field(name="📡 Stato", value=str(status), inline=True)
    announcement.add_field(
        name="💸 Come partecipare",
        value=f"`!buy {market_id} YES importo` oppure `!buy {market_id} NO importo`",
        inline=False
    )
    announcement.set_footer(text="Mercato aperto • Ping riservato ai giocatori")

    try:
        await market_channel.send(
            content=f"<@&{PLAYERS_ROLE_ID}>",
            embed=announcement,
            allowed_mentions=discord.AllowedMentions(roles=True)
        )
        return True
    except discord.Forbidden:
        print(
            f"[MARKET ANNOUNCEMENT] Permessi insufficienti nel canale {SPORT_ANNOUNCEMENTS_CHANNEL_ID}. "
            "Controlla: Vedere canale, Inviare messaggi, Incorporare link, Menzionare @everyone/ruoli."
        )
        return False
    except Exception as e:
        print(f"[MARKET ANNOUNCEMENT] Errore invio annuncio/ping giocatori: {e}")
        return False


def api_get(path, params=None):
    url = f"{BASE_URL}{path}"

    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=10)

        try:
            data = r.json()
        except Exception:
            data = {}

        return r.status_code, data

    except Exception as e:
        return None, {"error": str(e)}


def get_match_result(match_id):
    status_code, data = api_get(f"/matches/{match_id}")

    if status_code != 200:
        return None

    if "id" not in data:
        return None

    status = data.get("status")
    home = data["homeTeam"]["name"]
    away = data["awayTeam"]["name"]

    score = data.get("score", {})
    full_time = score.get("fullTime", {})

    gh = full_time.get("home")
    ga = full_time.get("away")

    winner = score.get("winner")

    if status != "FINISHED":
        return {
            "finished": False,
            "status": status,
            "home": home,
            "away": away,
            "home_goals": gh,
            "away_goals": ga,
            "winner": None
        }

    if winner == "HOME_TEAM":
        final_winner = "HOME"
    elif winner == "AWAY_TEAM":
        final_winner = "AWAY"
    else:
        final_winner = "DRAW"

    return {
        "finished": True,
        "status": status,
        "home": home,
        "away": away,
        "home_goals": gh,
        "away_goals": ga,
        "winner": final_winner
    }


def market_probabilities(yes, no):
    total = yes + no

    if total <= 0:
        return 50.0, 50.0

    yes_p = round((yes / total) * 100, 1)
    no_p = round(100 - yes_p, 1)

    return yes_p, no_p


def parse_percent(value):
    raw = str(value).replace("%", "").strip().replace(",", ".")

    try:
        pct = float(raw)
    except Exception:
        return None

    if pct <= 0 or pct > 100:
        return None

    return pct


def safe_entry_price(entry_price, fallback_price):
    if entry_price is None or entry_price <= 0:
        return fallback_price if fallback_price > 0 else 50.0

    return entry_price


def signed_fmt(value):
    try:
        value = float(value)
    except Exception:
        value = 0.0
    return f"{value:+.1f}%"


def calculate_market_change(market_id):
    """Variazione YES dall'inizio della cronologia disponibile all'ultimo prezzo."""
    c.execute("""
        SELECT yes_price
        FROM price_history
        WHERE market_id=?
        ORDER BY id ASC
    """, (market_id,))
    prices = [float(r[0] or 50.0) for r in c.fetchall()]
    if len(prices) < 2:
        return 0.0
    return prices[-1] - prices[0]


def get_market_volume_stats(market_id):
    c.execute("""
        SELECT
            COALESCE(trade_count, 0),
            COALESCE(buy_volume, 0),
            COALESCE(sell_volume, 0),
            COALESCE(total_volume, 0),
            COALESCE(total_pool, 0)
        FROM markets
        WHERE id=?
    """, (market_id,))
    row = c.fetchone()
    if not row:
        return {"trades": 0, "buy_volume": 0, "sell_volume": 0, "total_volume": 0, "liquidity": 0}
    return {
        "trades": row[0] or 0,
        "buy_volume": row[1] or 0,
        "sell_volume": row[2] or 0,
        "total_volume": row[3] or 0,
        "liquidity": row[4] or 0,
    }


# =========================
# DATABASE
# =========================
DB_PATH = os.environ.get("BOT_DB_PATH", "/data/bot.db")
try:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
except Exception:
    DB_PATH = "bot.db"

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
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

c.execute("""
CREATE TABLE IF NOT EXISTS user_stats (
    user_id TEXT PRIMARY KEY,
    xp INTEGER DEFAULT 0,
    current_streak INTEGER DEFAULT 0,
    best_streak INTEGER DEFAULT 0,
    last_daily TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS wealth_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    timestamp TEXT,
    net_worth REAL
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS referrals (
    invited_user_id TEXT PRIMARY KEY,
    inviter_user_id TEXT,
    guild_id TEXT,
    invite_code TEXT,
    joined_at TEXT,
    rewarded INTEGER DEFAULT 0,
    rewarded_at TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS follows (
    follower_user_id TEXT,
    followed_user_id TEXT,
    created_at TEXT,
    PRIMARY KEY (follower_user_id, followed_user_id)
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS user_badges (
    user_id TEXT,
    badge_id TEXT,
    active INTEGER DEFAULT 1,
    permanent INTEGER DEFAULT 1,
    awarded_at TEXT,
    removed_at TEXT,
    PRIMARY KEY (user_id, badge_id)
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS personal_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    market_id INTEGER,
    alert_type TEXT,
    side TEXT,
    target_value REAL,
    active INTEGER DEFAULT 1,
    triggered INTEGER DEFAULT 0,
    created_at TEXT,
    triggered_at TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS news_seen (
    source TEXT,
    external_id TEXT,
    created_at TEXT,
    PRIMARY KEY (source, external_id)
)
""")

# =========================
# MARKETPLACE DATABASE
# =========================
c.execute("""
CREATE TABLE IF NOT EXISTS user_inventory (
    user_id TEXT,
    item_id TEXT,
    quantity INTEGER DEFAULT 1,
    purchased_at TEXT,
    PRIMARY KEY (user_id, item_id)
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS user_equipment (
    user_id TEXT,
    slot TEXT,
    item_id TEXT,
    equipped_at TEXT,
    PRIMARY KEY (user_id, slot)
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS marketplace_purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    item_id TEXT,
    price INTEGER,
    purchased_at TEXT
)
""")

# =========================
# SEASONS DATABASE
# =========================
c.execute("""
CREATE TABLE IF NOT EXISTS seasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_number INTEGER UNIQUE,
    name TEXT,
    started_at TEXT,
    ended_at TEXT,
    active INTEGER DEFAULT 1
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS season_archives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_number INTEGER,
    archived_at TEXT,
    champion_user_id TEXT,
    champion_net_worth REAL,
    top3_text TEXT,
    best_accuracy_user_id TEXT,
    best_accuracy REAL,
    most_trades_user_id TEXT,
    most_trades INTEGER,
    total_markets INTEGER,
    total_trades INTEGER
)
""")

# =========================
# DATABASE UPDATE
# =========================
for statement in [
    "ALTER TABLE trades ADD COLUMN price REAL",
    "ALTER TABLE trades ADD COLUMN closed INTEGER DEFAULT 0",
    "ALTER TABLE trades ADD COLUMN buy_count INTEGER DEFAULT 1",
    "ALTER TABLE markets ADD COLUMN channel_id TEXT",
    "ALTER TABLE markets ADD COLUMN alert_yes_price REAL",
    "ALTER TABLE markets ADD COLUMN event_category TEXT",
    "ALTER TABLE markets ADD COLUMN trade_count INTEGER DEFAULT 0",
    "ALTER TABLE markets ADD COLUMN buy_volume INTEGER DEFAULT 0",
    "ALTER TABLE markets ADD COLUMN sell_volume INTEGER DEFAULT 0",
    "ALTER TABLE markets ADD COLUMN total_volume INTEGER DEFAULT 0"
]:
    try:
        c.execute(statement)
    except Exception:
        pass

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
# PORTFOLIO HELPERS
# =========================
def get_open_positions(user_id):
    """Restituisce posizioni aperte aggregate per utente, mercato e lato.

    In questo modo più acquisti successivi sullo stesso mercato/lato vengono
    mostrati come una sola quota cumulativa, con prezzo medio ponderato.
    Esempio: 50 YES + 50 YES = una posizione YES da 100; 20 NO resta separata.
    """
    c.execute("""
        SELECT
            MIN(t.id) AS id,
            t.market_id,
            m.question,
            m.yes_pool,
            m.no_pool,
            m.total_pool,
            m.active,
            m.resolved,
            m.result,
            m.match_key,
            t.side,
            SUM(t.amount) AS amount,
            CASE
                WHEN SUM(t.amount) > 0 THEN SUM(t.amount * COALESCE(t.price, 50)) / SUM(t.amount)
                ELSE 50
            END AS price
        FROM trades t
        JOIN markets m ON t.market_id=m.id
        WHERE t.user_id=?
          AND t.amount > 0
          AND (t.closed IS NULL OR t.closed=0)
        GROUP BY t.market_id, t.side
        ORDER BY t.market_id DESC, MIN(t.id) ASC
    """, (user_id,))

    return c.fetchall()


def calculate_user_open_value(user_id):
    rows = get_open_positions(user_id)

    total_invested = 0.0
    total_value = 0.0
    total_possible_win = 0.0

    for _, _, _, yes, no, total, *_rest in rows:
        side = _rest[-3]
        amount = _rest[-2]
        entry_price = _rest[-1]

        yes_p, no_p = market_probabilities(yes, no)
        current_price = yes_p if side == "YES" else no_p
        entry_price = safe_entry_price(entry_price, current_price)

        invested = float(amount)
        current_value = invested * (current_price / entry_price)

        possible_win = invested
        if side == "YES" and yes > 0:
            possible_win += invested * (no / yes)
        elif side == "NO" and no > 0:
            possible_win += invested * (yes / no)

        total_invested += invested
        total_value += current_value
        total_possible_win += possible_win

    return total_invested, total_value, total_possible_win, len(rows)




def progress_bar(value, size=12):
    """Crea una barra testuale per percentuali 0-100."""
    try:
        value = float(value)
    except Exception:
        value = 0

    value = max(0, min(100, value))
    filled = round((value / 100) * size)
    empty = size - filled
    return "█" * filled + "░" * empty


def market_color(yes_p):
    if yes_p >= 60:
        return 0x22c55e
    if yes_p <= 40:
        return 0xef4444
    return 0xf59e0b


def ensure_user_stats(user_id):
    c.execute("SELECT user_id FROM user_stats WHERE user_id=?", (user_id,))
    if not c.fetchone():
        c.execute(
            "INSERT INTO user_stats (user_id, xp, current_streak, best_streak, last_daily) VALUES (?, 0, 0, 0, NULL)",
            (user_id,)
        )
        conn.commit()


def get_user_stats(user_id):
    ensure_user_stats(user_id)
    c.execute("SELECT xp, current_streak, best_streak, last_daily FROM user_stats WHERE user_id=?", (user_id,))
    return c.fetchone() or (0, 0, 0, None)


def trader_level_from_xp(xp):
    """Restituisce livello trader, XP nel livello corrente e XP richiesti per il prossimo livello."""
    xp = int(xp or 0)

    levels = [
        ("🪵 Wood", 0),
        ("🩶 Silver", 2500),
        ("⚜️ Gold", 7500),
        ("🔹 Platinum", 17500),
        ("💎 Diamond", 40000),
        ("👑 Master", 80000),
        ("🐉 Legend", 150000),
    ]

    current_name, current_threshold = levels[0]
    next_threshold = None

    for idx, (name, threshold) in enumerate(levels):
        if xp >= threshold:
            current_name = name
            current_threshold = threshold
            next_threshold = levels[idx + 1][1] if idx + 1 < len(levels) else None

    if next_threshold is None:
        return current_name, xp - current_threshold, "MAX"

    return current_name, xp - current_threshold, next_threshold - current_threshold

def award_xp(user_id, amount):
    if amount <= 0:
        return
    ensure_user_stats(user_id)
    c.execute("UPDATE user_stats SET xp = xp + ? WHERE user_id=?", (int(amount), user_id))
    conn.commit()


def get_server_level_from_roles(member):
    """
    Legge il livello server dai ruoli Discord assegnati da Maki.
    Funziona con nomi tipo: Level 10, Lv 10, Livello 10, Rank 10.
    """
    best_level = 0
    best_name = None

    for role in member.roles:
        name = role.name.strip()
        lower = name.lower()

        if not any(key in lower for key in ["level", "livello", "lv", "rank"]):
            continue

        digits = "".join(ch if ch.isdigit() else " " for ch in name).split()

        for d in digits:
            try:
                lvl = int(d)
            except Exception:
                continue

            if lvl > best_level:
                best_level = lvl
                best_name = name

    if best_level <= 0:
        return "N/D"

    return f"{best_name}"


def calculate_server_rank(user_id):
    c.execute("SELECT user_id, balance FROM users")
    users = c.fetchall()

    ranking = []
    for uid, bal in users:
        _, open_value, _, _ = calculate_user_open_value(uid)
        ranking.append((uid, bal + open_value))

    ranking.sort(key=lambda x: x[1], reverse=True)

    for idx, (uid, _) in enumerate(ranking, start=1):
        if uid == user_id:
            return idx

    return None


def record_wealth_snapshot(user_id):
    balance = get_user(user_id)
    _, open_value, _, _ = calculate_user_open_value(user_id)
    net_worth = balance + open_value
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    c.execute("""
        INSERT INTO wealth_history (user_id, timestamp, net_worth)
        VALUES (?, ?, ?)
    """, (user_id, now, net_worth))
    conn.commit()


def get_following_count(user_id):
    c.execute("SELECT COUNT(*) FROM follows WHERE follower_user_id=?", (str(user_id),))
    return c.fetchone()[0] or 0


def get_user_metrics(user_id):
    user_id = str(user_id)
    balance = get_user(user_id)
    total_invested, open_value, _, open_positions = calculate_user_open_value(user_id)
    net_worth = balance + open_value

    c.execute("SELECT COUNT(*) FROM trades WHERE user_id=?", (user_id,))
    total_trades = c.fetchone()[0] or 0

    c.execute("SELECT COUNT(DISTINCT market_id) FROM trades WHERE user_id=?", (user_id,))
    markets_played = c.fetchone()[0] or 0

    c.execute("SELECT COUNT(*) FROM trades WHERE user_id=? AND side='YES'", (user_id,))
    yes_trades = c.fetchone()[0] or 0

    c.execute("SELECT COUNT(*) FROM trades WHERE user_id=? AND side='NO'", (user_id,))
    no_trades = c.fetchone()[0] or 0

    c.execute("""
        SELECT COUNT(DISTINCT m.id)
        FROM trades t
        JOIN markets m ON t.market_id=m.id
        WHERE t.user_id=?
          AND m.resolved=1
    """, (user_id,))
    resolved_markets = c.fetchone()[0] or 0

    c.execute("""
        SELECT COUNT(DISTINCT m.id)
        FROM trades t
        JOIN markets m ON t.market_id=m.id
        WHERE t.user_id=?
          AND m.resolved=1
          AND t.side=m.result
    """, (user_id,))
    won_markets = c.fetchone()[0] or 0

    lost_markets = max(0, resolved_markets - won_markets)
    accuracy = 0 if resolved_markets == 0 else (won_markets / resolved_markets) * 100

    xp, current_streak, best_streak, _ = get_user_stats(user_id)
    rank = calculate_server_rank(user_id)

    return {
        "balance": balance,
        "net_worth": net_worth,
        "open_positions": open_positions,
        "total_trades": total_trades,
        "markets_played": markets_played,
        "yes_trades": yes_trades,
        "no_trades": no_trades,
        "resolved_markets": resolved_markets,
        "won_markets": won_markets,
        "lost_markets": lost_markets,
        "accuracy": accuracy,
        "xp": xp,
        "current_streak": current_streak,
        "best_streak": best_streak,
        "rank": rank,
        "following_count": get_following_count(user_id),
    }


BADGES = {
    "prime_quote": {"emoji": "🎟️", "name": "Prime Quote", "desc": "Hai effettuato il tuo primo trade.", "permanent": True},
    "mercato_aperto": {"emoji": "📊", "name": "Mercato Aperto", "desc": "Hai giocato almeno 5 mercati.", "permanent": True},
    "trader_attivo": {"emoji": "💼", "name": "Trader Attivo", "desc": "Hai completato almeno 50 trade.", "permanent": True},
    "trader_esperto": {"emoji": "📈", "name": "Trader Esperto", "desc": "Hai completato almeno 150 trade.", "permanent": True},
    "veterano": {"emoji": "🏛️", "name": "Veterano", "desc": "Hai completato almeno 300 trade.", "permanent": True},
    "cecchino": {"emoji": "🎯", "name": "Cecchino", "desc": "Accuracy almeno 70% con almeno 40 mercati risolti.", "permanent": True},
    "inarrestabile": {"emoji": "🔥", "name": "Inarrestabile", "desc": "Hai raggiunto 15 vittorie consecutive.", "permanent": True},
    "serie_leggendaria": {"emoji": "🐉", "name": "Serie Leggendaria", "desc": "Hai raggiunto 35 vittorie consecutive.", "permanent": True},
    "bilanciato": {"emoji": "⚖️", "name": "Bilanciato", "desc": "Hai almeno 10 trade YES e 10 trade NO.", "permanent": True},
    "social_trader": {"emoji": "🤝", "name": "Social Trader", "desc": "Segui almeno 75 trader.", "permanent": True},
    "top_1": {"emoji": "🥇", "name": "Top 1", "desc": "Sei attualmente primo in classifica.", "permanent": False},
    "podio": {"emoji": "🥈", "name": "Podio", "desc": "Sei attualmente nella Top 3.", "permanent": False},
    "capitale_30k": {"emoji": "💰", "name": "Capitale 30K", "desc": "Il tuo saldo disponibile è almeno 30.000 crediti.", "permanent": False},
    "capitale_50k": {"emoji": "🏦", "name": "Capitale 50K", "desc": "Il tuo saldo disponibile è almeno 50.000 crediti.", "permanent": False},
    "capitale_80k": {"emoji": "💎", "name": "Capitale 80K", "desc": "Il tuo saldo disponibile è almeno 80.000 crediti.", "permanent": False},
}


def badge_conditions(metrics):
    return {
        "prime_quote": metrics["total_trades"] >= 1,
        "mercato_aperto": metrics["markets_played"] >= 5,
        "trader_attivo": metrics["total_trades"] >= 50,
        "trader_esperto": metrics["total_trades"] >= 150,
        "veterano": metrics["total_trades"] >= 300,
        "cecchino": metrics["resolved_markets"] >= 40 and metrics["accuracy"] >= 70,
        "inarrestabile": metrics["best_streak"] >= 15,
        "serie_leggendaria": metrics["best_streak"] >= 35,
        "bilanciato": metrics["yes_trades"] >= 10 and metrics["no_trades"] >= 10,
        "social_trader": metrics["following_count"] >= 75,
        "top_1": metrics["rank"] == 1,
        "podio": metrics["rank"] is not None and metrics["rank"] <= 3,
        "capitale_30k": metrics["balance"] >= 30000,
        "capitale_50k": metrics["balance"] >= 50000,
        "capitale_80k": metrics["balance"] >= 80000,
    }


def format_badge(badge_id):
    b = BADGES.get(badge_id, {})
    return f"{b.get('emoji', '🏅')} {b.get('name', badge_id)}"


async def send_badge_dm(user_id, badge_id, obtained=True):
    badge = BADGES.get(badge_id)
    if not badge:
        return

    try:
        user = bot.get_user(int(user_id)) or await bot.fetch_user(int(user_id))
    except Exception:
        user = None

    if not user:
        return

    if obtained:
        title = "🎉 Nuovo badge sbloccato!"
        desc = (
            f"Hai ottenuto il badge:\n\n"
            f"**{format_badge(badge_id)}**\n\n"
            f"_{badge['desc']}_"
        )
    else:
        title = "⚠️ Badge dinamico rimosso"
        desc = (
            f"Hai perso temporaneamente il badge:\n\n"
            f"**{format_badge(badge_id)}**\n\n"
            "Potrai riottenerlo quando soddisferai di nuovo il requisito."
        )

    embed = discord.Embed(title=title, description=desc, color=COLOR_GREEN if obtained else COLOR_RED)
    embed.set_footer(text="Apri !profile per vedere i tuoi badge.")

    try:
        await user.send(embed=embed)
    except Exception:
        pass


async def evaluate_user_badges(user_id, notify=True):
    user_id = str(user_id)
    metrics = get_user_metrics(user_id)
    conditions = badge_conditions(metrics)
    now = datetime.now(timezone.utc).isoformat()

    for badge_id, condition in conditions.items():
        badge = BADGES[badge_id]
        permanent = 1 if badge["permanent"] else 0

        c.execute("SELECT active, permanent FROM user_badges WHERE user_id=? AND badge_id=?", (user_id, badge_id))
        row = c.fetchone()
        currently_active = bool(row and row[0] == 1)

        if badge["permanent"]:
            if condition and not currently_active:
                c.execute("""
                    INSERT OR REPLACE INTO user_badges (user_id, badge_id, active, permanent, awarded_at, removed_at)
                    VALUES (?, ?, 1, ?, ?, NULL)
                """, (user_id, badge_id, permanent, now))
                conn.commit()
                if notify:
                    await send_badge_dm(user_id, badge_id, obtained=True)
        else:
            if condition and not currently_active:
                c.execute("""
                    INSERT OR REPLACE INTO user_badges (user_id, badge_id, active, permanent, awarded_at, removed_at)
                    VALUES (?, ?, 1, ?, ?, NULL)
                """, (user_id, badge_id, permanent, now))
                conn.commit()
                if notify:
                    await send_badge_dm(user_id, badge_id, obtained=True)
            elif not condition and currently_active:
                c.execute("""
                    UPDATE user_badges
                    SET active=0, removed_at=?
                    WHERE user_id=? AND badge_id=?
                """, (now, user_id, badge_id))
                conn.commit()
                if notify:
                    await send_badge_dm(user_id, badge_id, obtained=False)


def get_active_badges(user_id):
    c.execute("""
        SELECT badge_id
        FROM user_badges
        WHERE user_id=?
          AND active=1
        ORDER BY awarded_at ASC
    """, (str(user_id),))
    return [r[0] for r in c.fetchall()]


async def badge_checker_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            c.execute("SELECT user_id FROM users")
            for (user_id,) in c.fetchall():
                await evaluate_user_badges(user_id, notify=True)
        except Exception as e:
            print("BADGE CHECK ERR:", e)

        await asyncio.sleep(900)


def get_rome_now():
    if ZoneInfo:
        return datetime.now(ZoneInfo("Europe/Rome"))
    return datetime.utcnow().replace(tzinfo=timezone.utc) + timedelta(hours=2)


def format_match_time_rome(utc_date):
    if not utc_date:
        return "N/D"
    try:
        dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
        if ZoneInfo:
            dt = dt.astimezone(ZoneInfo("Europe/Rome"))
        else:
            dt = dt + timedelta(hours=2)
        return dt.strftime("%H:%M")
    except Exception:
        return str(utc_date).replace("T", " ").replace("Z", "")


def get_today_matches_for_competition(competition_code, target_date):
    status_code, data = api_get(
        f"/competitions/{competition_code}/matches",
        {"dateFrom": target_date.isoformat(), "dateTo": target_date.isoformat()}
    )
    if status_code != 200:
        return []
    return data.get("matches", []) or []


def get_today_matches_by_competition(target_date=None):
    """Recupera una sola volta le partite del giorno per pubblico e admin.

    Così il calendario pubblico e quello admin usano esattamente gli stessi dati:
    il pubblico li mostra senza ID, l'admin li mostra con Match ID e comando pronto.
    """
    if target_date is None:
        target_date = get_rome_now().date()

    result = {}
    for code in COMPETITIONS.keys():
        result[code] = get_today_matches_for_competition(code, target_date)

    return result


def build_calendar_embed_from_matches(matches_by_competition, public=True):
    title = "📅 Partite di oggi" if public else "👑 Calendario admin"
    description = "Calendario pubblico senza ID partita." if public else "Calendario operativo con Match ID per creare mercati."
    embed = discord.Embed(title=title, description=description, color=COLOR_CYAN if public else COLOR_WHITE)

    found = False
    field_count = 0

    for code, name in COMPETITIONS.items():
        matches = matches_by_competition.get(code, [])
        if not matches:
            continue

        found = True
        emoji = COMPETITION_EMOJIS.get(code, "⚽")
        lines = []

        for m in matches[:6]:
            mid = m.get("id")
            home = m.get("homeTeam", {}).get("name", "Home")
            away = m.get("awayTeam", {}).get("name", "Away")
            status = m.get("status", "N/D")
            time_str = format_match_time_rome(m.get("utcDate"))

            if public:
                lines.append(
                    f"**{home}** vs **{away}**\n"
                    f"🕒 {time_str} | 📡 {status}"
                )
            else:
                lines.append(
                    f"**{home}** vs **{away}**\n"
                    f"🕒 {time_str} | 📡 {status}\n"
                    f"🆔 Match ID: `{mid}`\n"
                    f"Comando: `!creatematch {mid} Domanda del mercato`"
                )

        value = "\n\n".join(lines)
        if len(value) > 1024:
            value = value[:1000] + "..."

        embed.add_field(name=f"{emoji} {name}", value=value, inline=False)
        field_count += 1
        if field_count >= 20:
            break

    if not found:
        embed.add_field(name="📭 Nessuna partita", value="Nessuna partita disponibile oggi nelle competizioni monitorate.", inline=False)

    embed.set_footer(text="Aggiornamento automatico giornaliero • Orario Roma")
    return embed


def build_calendar_embeds(public=True):
    matches_by_competition = get_today_matches_by_competition()
    return build_calendar_embed_from_matches(matches_by_competition, public=public)


async def post_daily_calendars():
    public_channel = bot.get_channel(PUBLIC_CALENDAR_CHANNEL_ID)
    admin_channel = bot.get_channel(ADMIN_CALENDAR_CHANNEL_ID)
    matches_by_competition = get_today_matches_by_competition()

    if public_channel:
        try:
            await public_channel.send(embed=build_calendar_embed_from_matches(matches_by_competition, public=True))
        except Exception as e:
            print(f"[CALENDAR PUBLIC] Errore invio: {e}")

    if admin_channel:
        try:
            await admin_channel.send(embed=build_calendar_embed_from_matches(matches_by_competition, public=False))
        except Exception as e:
            print(f"[CALENDAR ADMIN] Errore invio: {e}")


async def calendar_poster_loop():
    global LAST_CALENDAR_POST_DATE
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            now = get_rome_now()
            today_key = now.date().isoformat()

            if (
                now.hour == CALENDAR_POST_HOUR
                and now.minute >= CALENDAR_POST_MINUTE
                and LAST_CALENDAR_POST_DATE != today_key
            ):
                await post_daily_calendars()
                LAST_CALENDAR_POST_DATE = today_key

        except Exception as e:
            print("CALENDAR LOOP ERR:", e)

        await asyncio.sleep(60)



# =========================
# REFERRAL HELPERS
# =========================
async def cache_guild_invites(guild):
    """Salva lo stato degli inviti di un server per capire chi ha invitato un nuovo membro."""
    try:
        invites = await guild.invites()
    except Exception as e:
        print(f"[REFERRAL] Impossibile leggere gli inviti per {guild.name}: {e}")
        INVITE_CACHE[guild.id] = {}
        return

    INVITE_CACHE[guild.id] = {invite.code: invite.uses for invite in invites}


async def cache_all_invites():
    for guild in bot.guilds:
        await cache_guild_invites(guild)


def user_has_trade(user_id):
    c.execute("""
        SELECT COUNT(*)
        FROM trades
        WHERE user_id=?
          AND amount > 0
    """, (str(user_id),))

    return (c.fetchone()[0] or 0) > 0


async def referral_checker():
    """Premia automaticamente i referral validi: 24h nel server + almeno 1 trade."""
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            c.execute("""
                SELECT invited_user_id, inviter_user_id, guild_id, joined_at
                FROM referrals
                WHERE rewarded=0
            """)
            rows = c.fetchall()
            now = datetime.now(timezone.utc)

            for invited_id, inviter_id, guild_id, joined_at in rows:
                try:
                    joined = datetime.fromisoformat(joined_at)
                    if joined.tzinfo is None:
                        joined = joined.replace(tzinfo=timezone.utc)
                except Exception:
                    continue

                if now - joined < timedelta(hours=REFERRAL_MIN_AGE_HOURS):
                    continue

                guild = bot.get_guild(int(guild_id))
                if not guild:
                    continue

                member = guild.get_member(int(invited_id))
                if member is None:
                    # Il nuovo utente non è più nel server: niente premio.
                    continue

                if not user_has_trade(invited_id):
                    # Anti-abuso: il nuovo utente deve aver fatto almeno un trade reale.
                    continue

                get_user(inviter_id)
                c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (REFERRAL_REWARD, inviter_id))
                c.execute("""
                    UPDATE referrals
                    SET rewarded=1,
                        rewarded_at=?
                    WHERE invited_user_id=?
                """, (now.isoformat(), invited_id))
                conn.commit()

                award_xp(inviter_id, 100)
                record_wealth_snapshot(inviter_id)

                inviter = guild.get_member(int(inviter_id))
                if inviter:
                    try:
                        await inviter.send(
                            f"🎁 Referral valido! Hai ricevuto +{REFERRAL_REWARD} crediti perché {member.display_name} è rimasto nel server e ha fatto almeno un trade."
                        )
                    except Exception:
                        pass

                print(f"[REFERRAL PAID] {inviter_id} +{REFERRAL_REWARD} for {invited_id}")

        except Exception as e:
            print("REFERRAL ERR:", e)

        await asyncio.sleep(600)


def update_streaks_for_market(market_id, result):
    c.execute("""
        SELECT user_id,
               SUM(CASE WHEN side=? THEN amount ELSE 0 END) AS win_amount,
               SUM(CASE WHEN side!=? THEN amount ELSE 0 END) AS lose_amount
        FROM trades
        WHERE market_id=?
          AND amount > 0
          AND (closed IS NULL OR closed=0)
        GROUP BY user_id
    """, (result, result, market_id))

    rows = c.fetchall()

    for user_id, win_amount, lose_amount in rows:
        win_amount = win_amount or 0
        lose_amount = lose_amount or 0
        ensure_user_stats(user_id)

        if win_amount > 0:
            c.execute("""
                UPDATE user_stats
                SET current_streak = current_streak + 1,
                    best_streak = MAX(best_streak, current_streak + 1)
                WHERE user_id=?
            """, (user_id,))
            award_xp(user_id, 75)
        elif lose_amount > 0:
            c.execute("UPDATE user_stats SET current_streak=0 WHERE user_id=?", (user_id,))

    conn.commit()


def make_profile_dashboard_image(member, balance, net_worth, xp, trader_level, xp_current, xp_required, accuracy, streak, rank):
    c.execute("""
        SELECT timestamp, net_worth
        FROM wealth_history
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 12
    """, (str(member.id),))
    rows = list(reversed(c.fetchall()))

    if not rows:
        rows = [(datetime.utcnow().strftime("%H:%M"), net_worth)]

    labels = []
    values = []
    for ts, value in rows:
        labels.append(str(ts)[11:16] if len(str(ts)) >= 16 else str(ts))
        values.append(float(value or 0))

    fig = plt.figure(figsize=(10, 5), dpi=140)
    fig.patch.set_facecolor("#0e1117")

    ax_bg = fig.add_axes([0, 0, 1, 1])
    ax_bg.axis("off")
    ax_bg.set_facecolor("#0e1117")

    # Header
    ax_bg.text(0.05, 0.88, f"{member.display_name}", fontsize=24, fontweight="bold", color="white")
    ax_bg.text(0.05, 0.80, "Prediction Market Dashboard", fontsize=11, color="#9ca3af")

    rank_text = f"#{rank}" if rank else "N/D"
    ax_bg.text(0.73, 0.88, f"Rank {rank_text}", fontsize=18, fontweight="bold", color="#facc15")

    # Stat cards
    stats = [
        ("Saldo", f"{balance:.0f}"),
        ("Patrimonio", f"{net_worth:.0f}"),
        ("Livello trader", f"Lv {trader_level}"),
        ("XP", f"{xp_current}/{xp_required}"),
        ("Accuracy", f"{accuracy:.1f}%"),
        ("Streak", f"{streak}"),
    ]

    x0 = 0.05
    y0 = 0.62
    w = 0.27
    h = 0.12
    gap = 0.035

    for i, (label, value) in enumerate(stats):
        col = i % 3
        row = i // 3
        x = x0 + col * (w + gap)
        y = y0 - row * (h + 0.04)
        rect = plt.Rectangle((x, y), w, h, transform=fig.transFigure, facecolor="#111827", edgecolor="#1f2937", linewidth=1.2)
        fig.patches.append(rect)
        ax_bg.text(x + 0.02, y + 0.073, label, fontsize=10, color="#9ca3af")
        ax_bg.text(x + 0.02, y + 0.025, value, fontsize=17, fontweight="bold", color="white")

    # Chart
    ax = fig.add_axes([0.08, 0.10, 0.84, 0.28])
    ax.set_facecolor("#0e1117")
    ax.plot(range(len(values)), values, linewidth=2.5, color="#22c55e")
    ax.fill_between(range(len(values)), values, min(values) if values else 0, alpha=0.12, color="#22c55e")
    ax.grid(True, alpha=0.15)
    ax.tick_params(colors="#9ca3af", labelsize=8)
    ax.set_title("Andamento patrimonio", color="white", fontsize=12, fontweight="bold")

    if len(labels) > 1:
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=25)
    else:
        ax.set_xticks([])

    for spine in ax.spines.values():
        spine.set_color("#1f2937")

    buffer = io.BytesIO()
    plt.savefig(buffer, format="png", facecolor="#0e1117", bbox_inches="tight", pad_inches=0.1)
    buffer.seek(0)
    plt.close(fig)
    return buffer




# =========================
# AI PREDICTION HELPERS
# =========================
def get_match_details(match_id):
    """Recupera i dettagli completi di una partita da football-data.org."""
    status_code, data = api_get(f"/matches/{match_id}")

    if status_code != 200 or "id" not in data:
        return None, status_code, data

    return data, status_code, data


def get_recent_team_matches(team_id, limit=5):
    """Recupera le ultime partite concluse di una squadra.

    Se il piano API non consente l'endpoint o non restituisce dati,
    torna una lista vuota. Il comando !predict resta comunque funzionante.
    """
    params = {
        "status": "FINISHED",
        "limit": limit
    }

    status_code, data = api_get(f"/teams/{team_id}/matches", params)

    if status_code != 200:
        return []

    matches = data.get("matches", [])

    finished = [m for m in matches if m.get("status") == "FINISHED"]
    finished.sort(key=lambda m: m.get("utcDate", ""), reverse=True)

    return finished[:limit]


def analyze_team_form(matches, team_id):
    """Calcola forma, gol fatti/subiti e indicatori base."""
    wins = draws = losses = 0
    goals_for = 0
    goals_against = 0
    clean_sheets = 0
    form = []

    for m in matches:
        home_id = m.get("homeTeam", {}).get("id")
        away_id = m.get("awayTeam", {}).get("id")
        score = m.get("score", {}).get("fullTime", {})
        hg = score.get("home")
        ag = score.get("away")

        if hg is None or ag is None:
            continue

        if team_id == home_id:
            gf, ga = hg, ag
        elif team_id == away_id:
            gf, ga = ag, hg
        else:
            continue

        goals_for += gf
        goals_against += ga

        if ga == 0:
            clean_sheets += 1

        if gf > ga:
            wins += 1
            form.append("✅")
        elif gf == ga:
            draws += 1
            form.append("⚪️")
        else:
            losses += 1
            form.append("❌")

    played = wins + draws + losses

    if played == 0:
        return {
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "goals_for": 0,
            "goals_against": 0,
            "avg_for": 0,
            "avg_against": 0,
            "clean_sheets": 0,
            "form": "N/D",
            "points": 0,
            "power": 50.0
        }

    points = wins * 3 + draws
    avg_for = goals_for / played
    avg_against = goals_against / played

    # Power rating semplice e spiegabile, 0-100.
    power = 50
    power += (wins - losses) * 7
    power += (avg_for - avg_against) * 8
    power += clean_sheets * 2
    power = max(20, min(80, power))

    return {
        "played": played,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "avg_for": avg_for,
        "avg_against": avg_against,
        "clean_sheets": clean_sheets,
        "form": " ".join(form[:5]) if form else "N/D",
        "points": points,
        "power": power
    }


def calculate_ai_prediction(home_stats, away_stats):
    """Genera probabilità Home/Draw/Away e indicatori di rischio.

    L'algoritmo è volutamente trasparente: non pretende di essere infallibile,
    ma costruisce una stima coerente sulla base dei dati disponibili.
    """
    home_power = home_stats["power"]
    away_power = away_stats["power"]

    data_quality = min(home_stats["played"], away_stats["played"])
    power_diff = home_power - away_power

    # Vantaggio casa leggero.
    home_advantage = 5
    adjusted_diff = power_diff + home_advantage

    home_prob = 45 + adjusted_diff * 0.45
    away_prob = 35 - adjusted_diff * 0.35

    balance = abs(adjusted_diff)
    draw_prob = 20
    if balance < 6:
        draw_prob += 6
    elif balance > 18:
        draw_prob -= 5

    home_prob = max(18, min(78, home_prob))
    away_prob = max(10, min(65, away_prob))
    draw_prob = max(12, min(32, draw_prob))

    total = home_prob + draw_prob + away_prob
    home_prob = round(home_prob / total * 100, 1)
    draw_prob = round(draw_prob / total * 100, 1)
    away_prob = round(100 - home_prob - draw_prob, 1)

    favorite_prob = max(home_prob, draw_prob, away_prob)

    # Prediction score: qualità dei dati + chiarezza del vantaggio.
    data_score = min(30, data_quality * 6)
    clarity_score = min(45, abs(adjusted_diff) * 1.8)
    confidence_score = int(max(35, min(95, 25 + data_score + clarity_score)))

    if confidence_score >= 80:
        stars = "★★★★★"
    elif confidence_score >= 65:
        stars = "★★★★☆"
    elif confidence_score >= 50:
        stars = "★★★☆☆"
    elif confidence_score >= 40:
        stars = "★★☆☆☆"
    else:
        stars = "★☆☆☆☆"

    if favorite_prob >= 62 and confidence_score >= 70:
        risk = "🟢 BASSO"
        color = 0x22c55e
    elif favorite_prob >= 52:
        risk = "🟡 MEDIO"
        color = 0xf59e0b
    else:
        risk = "🔴 ALTO"
        color = 0xef4444

    return {
        "home_prob": home_prob,
        "draw_prob": draw_prob,
        "away_prob": away_prob,
        "confidence_score": confidence_score,
        "stars": stars,
        "risk": risk,
        "color": color,
        "home_power": round(home_power, 1),
        "away_power": round(away_power, 1),
        "adjusted_diff": round(adjusted_diff, 1)
    }


def find_market_for_match(match_id):
    match_key = f"MATCH_{match_id}"
    c.execute("""
        SELECT id, question, yes_pool, no_pool, total_pool, active
        FROM markets
        WHERE match_key=?
        ORDER BY id DESC
        LIMIT 1
    """, (match_key,))

    return c.fetchone()


def build_prediction_comment(home_name, away_name, home_stats, away_stats, prediction, community=None):
    home_prob = prediction["home_prob"]
    away_prob = prediction["away_prob"]
    draw_prob = prediction["draw_prob"]

    if home_prob >= max(away_prob, draw_prob):
        fav = home_name
        fav_prob = home_prob
    elif away_prob >= max(home_prob, draw_prob):
        fav = away_name
        fav_prob = away_prob
    else:
        fav = "il pareggio"
        fav_prob = draw_prob

    parts = []

    if fav == home_name:
        parts.append(f"L'algoritmo vede **{home_name}** leggermente o nettamente favorito, soprattutto per il vantaggio casa e il confronto di forma recente.")
    elif fav == away_name:
        parts.append(f"L'algoritmo vede **{away_name}** come possibile favorita, nonostante giochi fuori casa, per il rendimento recente superiore.")
    else:
        parts.append("La partita appare molto equilibrata: l'algoritmo assegna un peso rilevante allo scenario pareggio.")

    if home_stats["played"] and away_stats["played"]:
        if home_stats["avg_for"] > away_stats["avg_for"] + 0.4:
            parts.append(f"{home_name} mostra una produzione offensiva migliore nelle ultime gare.")
        elif away_stats["avg_for"] > home_stats["avg_for"] + 0.4:
            parts.append(f"{away_name} arriva con una produzione offensiva più alta nelle ultime gare.")

        if home_stats["avg_against"] < away_stats["avg_against"] - 0.3:
            parts.append(f"La fase difensiva di {home_name} risulta più solida dai dati recenti.")
        elif away_stats["avg_against"] < home_stats["avg_against"] - 0.3:
            parts.append(f"La fase difensiva di {away_name} sembra più solida dai dati recenti.")
    else:
        parts.append("I dati storici disponibili tramite API sono limitati: la previsione va letta con prudenza.")

    if community:
        diff = home_prob - community["yes_p"]
        if abs(diff) >= 8:
            if diff > 0:
                parts.append("La community è più prudente dell'AI sul lato YES: potrebbe esserci valore se si crede nella squadra di casa.")
            else:
                parts.append("La community è più ottimista dell'AI sul lato YES: attenzione a un possibile eccesso di entusiasmo.")

    parts.append(f"Prediction score: **{prediction['confidence_score']}/100**. Probabilità principale stimata: **{fav_prob:.1f}%**.")

    return " ".join(parts)


def fmt_avg(value):
    return f"{value:.2f}" if isinstance(value, (int, float)) else "N/D"


# =========================
# BASE COMMANDS
# =========================
@bot.command()
async def ping(ctx):
    await ctx.send("pong 🟢")


@bot.command(aliases=["saldo"])
async def balance(ctx):
    user_id = str(ctx.author.id)
    bal = get_user(user_id)

    embed = discord.Embed(
        title="💰 Saldo",
        color=COLOR_BLUE
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    embed.add_field(name="Crediti disponibili", value=f"{bal}", inline=False)
    apply_cosmetics_to_embed(embed, user_id, ctx.author, "Comando disponibile anche come !saldo")

    await ctx.send(embed=embed)

# =========================
# DAILY REWARD
# =========================
@bot.command(aliases=["giornaliero"])
async def daily(ctx):
    user_id = str(ctx.author.id)
    get_user(user_id)
    ensure_user_stats(user_id)

    xp, current_streak, best_streak, last_daily = get_user_stats(user_id)
    now = datetime.now(timezone.utc)

    if last_daily:
        try:
            last = datetime.fromisoformat(last_daily)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
        except Exception:
            last = None

        if last and now - last < timedelta(hours=24):
            remaining = timedelta(hours=24) - (now - last)
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            await ctx.send(f"⏳ Hai già riscattato il daily. Riprova tra {hours}h {minutes}m.")
            return

    reward = 100
    xp_reward = 25
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (reward, user_id))
    c.execute("UPDATE user_stats SET xp = xp + ?, last_daily=? WHERE user_id=?", (xp_reward, now.isoformat(), user_id))
    conn.commit()
    record_wealth_snapshot(user_id)

    balance = get_user(user_id)
    xp, current_streak, best_streak, _ = get_user_stats(user_id)
    trader_level, xp_current, xp_required = trader_level_from_xp(xp)

    embed = discord.Embed(
        title="🎁 Daily riscattato",
        description=f"Hai ricevuto **+{reward} crediti** e **+{xp_reward} XP trader**.",
        color=COLOR_GOLD
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    embed.add_field(name="💰 Saldo aggiornato", value=str(balance), inline=True)
    embed.add_field(name="💹 Livello trader", value=trader_level, inline=True)
    embed.add_field(name="📈 XP", value=f"{xp_current}/{xp_required}", inline=True)
    embed.set_footer(text="Comando disponibile anche come !giornaliero")

    await ctx.send(embed=embed)


# =========================
# REFERRAL STATUS
# =========================
@bot.command(aliases=["inviti", "referral"])
async def referrals(ctx):
    user_id = str(ctx.author.id)

    c.execute("""
        SELECT COUNT(*)
        FROM referrals
        WHERE inviter_user_id=?
    """, (user_id,))
    total = c.fetchone()[0] or 0

    c.execute("""
        SELECT COUNT(*)
        FROM referrals
        WHERE inviter_user_id=?
          AND rewarded=1
    """, (user_id,))
    rewarded = c.fetchone()[0] or 0

    pending = max(0, total - rewarded)

    embed = discord.Embed(
        title="🤝 Referral",
        description=(
            f"Invita un amico nel server: ricevi **+{REFERRAL_REWARD} crediti** quando resta almeno "
            f"**{REFERRAL_MIN_AGE_HOURS}h** e fa almeno **1 trade**."
        ),
        color=COLOR_GOLD
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    embed.add_field(name="✅ Premi riscossi", value=str(rewarded), inline=True)
    embed.add_field(name="⏳ In attesa", value=str(pending), inline=True)
    embed.add_field(name="👥 Inviti tracciati", value=str(total), inline=True)
    embed.set_footer(text="Anti-abuso: niente premio per auto-inviti, bot o utenti che lasciano subito il server.")

    await ctx.send(embed=embed)


# =========================
# API TEST COMMANDS
# =========================
@bot.command()
@admin_only()
async def checkapi(ctx):
    if not FOOTBALL_DATA_TOKEN:
        await ctx.send("❌ FOOTBALL_DATA_TOKEN non trovata nelle variabili ambiente")
        return

    status_code, data = api_get("/competitions")

    await ctx.send(
f"""🧪 TEST API FOOTBALL-DATA

📡 Status HTTP: {status_code}
🔑 Token caricato: Sì

📦 Messaggio:
{data.get("message", "API raggiunta correttamente")}
"""
    )


@bot.command(aliases=["competizioni"])
@admin_only()
async def competitions(ctx):
    msg = "🏆 COMPETIZIONI RAPIDE\n\n"

    for code, name in COMPETITIONS.items():
        msg += f"🆔 {code} | {name}\n"

    msg += """
Esempi:
!fixtures SA 7
!fixtures PL 7
!fixtures CL 14
!fixtures WC 7
"""

    await ctx.send(msg)


@bot.command()
@admin_only()
async def testmatch(ctx, match_id: int):
    status_code, data = api_get(f"/matches/{match_id}")

    msg = f"""🧪 TEST MATCH

🆔 Match ID: {match_id}
📡 Status HTTP: {status_code}
"""

    if status_code != 200:
        msg += f"""
❌ Errore API:
{data}
"""
        await ctx.send(msg)
        return

    home = data["homeTeam"]["name"]
    away = data["awayTeam"]["name"]
    status = data["status"]

    score = data.get("score", {})
    full_time = score.get("fullTime", {})

    gh = full_time.get("home")
    ga = full_time.get("away")
    winner = score.get("winner")

    msg += f"""
🏟️ Partita:
{home} vs {away}

📡 Stato: {status}
⚽ Risultato: {gh}-{ga}
🏆 Winner API: {winner}
"""

    await ctx.send(msg)




# =========================
# AI MATCH PREDICTION
# =========================
@bot.command(aliases=["previsione", "pronostico"])
@admin_only()
async def predict(ctx, match_id: int):
    await delete_admin_command_message(ctx)
    match, status_code, raw_data = get_match_details(match_id)

    if not match:
        embed = discord.Embed(
            title="❌ Match non trovato",
            description=f"Non riesco a recuperare il match `{match_id}` da football-data.org.",
            color=COLOR_RED
        )
        embed.add_field(name="Status API", value=str(status_code), inline=True)
        embed.add_field(name="Suggerimento", value="Prova prima `!testmatch ID` oppure recupera l'ID con `!fixtures`.", inline=False)
        await ctx.send(embed=embed)
        return

    home_team = match.get("homeTeam", {})
    away_team = match.get("awayTeam", {})
    competition = match.get("competition", {})
    score = match.get("score", {})

    home_id = home_team.get("id")
    away_id = away_team.get("id")
    home_name = home_team.get("name", "Home")
    away_name = away_team.get("name", "Away")
    competition_name = competition.get("name", "Competizione")
    utc_date = match.get("utcDate", "N/D")
    status = match.get("status", "N/D")

    if not home_id or not away_id:
        await ctx.send("❌ Dati squadre insufficienti per generare la previsione.")
        return

    home_recent = get_recent_team_matches(home_id, 5)
    away_recent = get_recent_team_matches(away_id, 5)

    home_stats = analyze_team_form(home_recent, home_id)
    away_stats = analyze_team_form(away_recent, away_id)
    prediction = calculate_ai_prediction(home_stats, away_stats)

    market = find_market_for_match(match_id)
    community = None

    if market:
        market_id, question, yes_pool, no_pool, total_pool, active = market
        yes_p, no_p = market_probabilities(yes_pool, no_pool)
        community = {
            "market_id": market_id,
            "question": question,
            "yes_p": yes_p,
            "no_p": no_p,
            "total_pool": total_pool,
            "active": active
        }

    comment = build_prediction_comment(home_name, away_name, home_stats, away_stats, prediction, community)

    embed = discord.Embed(
        title="🤖 AI Match Analysis",
        description=f"**{home_name}** vs **{away_name}**",
        color=COLOR_ORANGE
    )

    embed.add_field(name="🏆 Competizione", value=competition_name, inline=True)
    embed.add_field(name="📡 Stato", value=status, inline=True)
    embed.add_field(name="🆔 Match ID", value=str(match_id), inline=True)
    embed.add_field(name="📅 Data UTC", value=str(utc_date).replace("T", " ").replace("Z", ""), inline=False)

    embed.add_field(
        name="📊 Probabilità AI",
        value=(
            f"🏠 **{home_name}**: **{prediction['home_prob']}%** `{progress_bar(prediction['home_prob'], 10)}`\n"
            f"🤝 **Pareggio**: **{prediction['draw_prob']}%** `{progress_bar(prediction['draw_prob'], 10)}`\n"
            f"✈️ **{away_name}**: **{prediction['away_prob']}%** `{progress_bar(prediction['away_prob'], 10)}`"
        ),
        inline=False
    )

    embed.add_field(name="⭐ Confidenza", value=f"{prediction['stars']}\n{prediction['confidence_score']}/100", inline=True)
    embed.add_field(name="📉 Rischio", value=prediction["risk"], inline=True)
    embed.add_field(name="🧮 Power rating", value=f"{home_name}: {prediction['home_power']}\n{away_name}: {prediction['away_power']}", inline=True)

    embed.add_field(
        name=f"📈 Forma {home_name}",
        value=(
            f"{home_stats['form']}\n"
            f"V/P/S: **{home_stats['wins']}/{home_stats['draws']}/{home_stats['losses']}**\n"
            f"⚽ GF: **{fmt_avg(home_stats['avg_for'])}** | 🛡 GA: **{fmt_avg(home_stats['avg_against'])}**"
        ),
        inline=True
    )

    embed.add_field(
        name=f"📈 Forma {away_name}",
        value=(
            f"{away_stats['form']}\n"
            f"V/P/S: **{away_stats['wins']}/{away_stats['draws']}/{away_stats['losses']}**\n"
            f"⚽ GF: **{fmt_avg(away_stats['avg_for'])}** | 🛡 GA: **{fmt_avg(away_stats['avg_against'])}**"
        ),
        inline=True
    )

    if community:
        diff = prediction["home_prob"] - community["yes_p"]
        if diff > 0:
            verdict = f"AI più favorevole al YES di **+{diff:.1f}%**"
        elif diff < 0:
            verdict = f"Community più favorevole al YES di **+{abs(diff):.1f}%**"
        else:
            verdict = "AI e community sono allineate."

        embed.add_field(
            name="📊 AI vs Community",
            value=(
                f"Mercato: **#{community['market_id']}**\n"
                f"Community YES: **{community['yes_p']}%**\n"
                f"Community NO: **{community['no_p']}%**\n"
                f"Volume: **{community['total_pool']} crediti**\n"
                f"{verdict}"
            ),
            inline=False
        )
    else:
        embed.add_field(
            name="📊 AI vs Community",
            value="Nessun mercato collegato a questo Match ID. Crea un mercato con `!creatematch` per confrontare AI e community.",
            inline=False
        )

    embed.add_field(name="🧠 Analisi", value=comment[:1000], inline=False)
    embed.set_footer(text="Stima probabilistica: non garantisce il risultato finale. Usa !predict come supporto, non come certezza.")

    await ctx.send(embed=embed)


# =========================
# FIND MATCHES
# =========================
@bot.command(aliases=["oggi"])
@admin_only()
async def today(ctx, competition: str = "WC"):
    competition = competition.upper()

    if competition not in COMPETITIONS:
        await ctx.send(
f"""❌ Competizione non riconosciuta.

Usa:
!competitions

Esempio:
!today WC
!today SA
!today PL
"""
        )
        return

    today_date = datetime.now(timezone.utc).date().isoformat()

    status_code, data = api_get(
        f"/competitions/{competition}/matches",
        {
            "dateFrom": today_date,
            "dateTo": today_date
        }
    )

    if status_code != 200:
        await ctx.send(f"❌ Errore API:\n{data}")
        return

    matches = data.get("matches", [])

    if not matches:
        await ctx.send(f"📭 Nessuna partita trovata oggi per {COMPETITIONS[competition]}")
        return

    msg = f"📅 PARTITE DI OGGI | {COMPETITIONS[competition]}\n\n"

    for m in matches[:15]:
        mid = m["id"]
        home = m["homeTeam"]["name"]
        away = m["awayTeam"]["name"]
        status = m["status"]
        utc_date = m.get("utcDate", "N/D")

        msg += f"""🆔 Match ID: {mid}
🏟️ {home} vs {away}
📡 Stato: {status}
🕒 UTC: {utc_date}

────────────────
"""

    await send_long(ctx, msg)


@bot.command(aliases=["partite", "calendario"])
@admin_only()
async def fixtures(ctx, competition: str = "SA", days: int = 7):
    competition = competition.upper()

    if competition not in COMPETITIONS:
        await ctx.send(
f"""❌ Competizione non riconosciuta.

Usa:
!competitions

Esempio:
!fixtures SA 7
"""
        )
        return

    if days < 1:
        days = 1

    if days > 30:
        days = 30

    date_from = datetime.now(timezone.utc).date()
    date_to = date_from + timedelta(days=days)

    status_code, data = api_get(
        f"/competitions/{competition}/matches",
        {
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat()
        }
    )

    if status_code != 200:
        await ctx.send(f"❌ Errore API:\n{data}")
        return

    matches = data.get("matches", [])

    if not matches:
        await ctx.send(f"📭 Nessuna partita trovata per {competition} nei prossimi {days} giorni")
        return

    msg = f"📅 PARTITE {COMPETITIONS[competition]} | prossimi {days} giorni\n\n"

    for m in matches[:20]:
        mid = m["id"]
        home = m["homeTeam"]["name"]
        away = m["awayTeam"]["name"]
        status = m["status"]
        utc_date = m.get("utcDate", "N/D")

        msg += f"""🆔 Match ID: {mid}
🏟️ {home} vs {away}
📡 Stato: {status}
🕒 UTC: {utc_date}

────────────────
"""

    await send_long(ctx, msg)


# =========================
# CREATE MARKET FROM FOOTBALL-DATA MATCH
# =========================
@bot.command(aliases=["creamercato"])
@admin_only()
async def creatematch(ctx, match_id: int, *, question):
    await delete_admin_command_message(ctx)
    res = get_match_result(match_id)

    if not res:
        await ctx.send(
f"""❌ Match non trovato nell'API

Prova prima:
!checkapi
!testmatch {match_id}
"""
        )
        return

    if res["finished"]:
        await ctx.send("❌ Questa partita è già finita")
        return

    home = res["home"]
    away = res["away"]
    status = res["status"]

    c.execute("""
        INSERT INTO markets (
            question,
            yes_pool,
            no_pool,
            total_pool,
            active,
            match_key,
            resolved,
            result,
            channel_id,
            alert_yes_price
        )
        VALUES (?, 0, 0, 0, 1, ?, 0, NULL, ?, 50)
    """, (question, f"MATCH_{match_id}", str(SPORT_ANNOUNCEMENTS_CHANNEL_ID)))

    market_id = c.lastrowid
    conn.commit()

    # Risposta privata/operativa nel canale in cui l'admin ha creato il mercato.
    embed = discord.Embed(
        title="📊 Mercato creato",
        description=question,
        color=COLOR_GREEN
    )
    embed.add_field(name="🆔 Mercato", value=f"#{market_id}", inline=True)
    embed.add_field(name="🆔 Match API", value=str(match_id), inline=True)
    embed.add_field(name="📡 Stato API", value=status, inline=True)
    embed.add_field(name="🏟️ Partita", value=f"{home} vs {away}", inline=False)
    embed.set_footer(text="Mercato aperto correttamente.")

    await ctx.send(embed=embed)
    await log_admin_activity(
        ctx,
        "🟣 !creatematch",
        market_id=market_id,
        details=f"Match API {match_id} • {home} vs {away} • {question}",
        color=COLOR_PURPLE
    )

    # Annuncio pubblico nel canale #annunci-sport con ping del ruolo giocatori.
    announced = await announce_sport_market_opening(
        market_id=market_id,
        question=question,
        home=home,
        away=away,
        match_id=match_id,
        status=status
    )

    if not announced:
        await ctx.send(
            "⚠️ Mercato creato, ma non sono riuscito a pubblicarlo nel canale annunci sport "
            "o a pingare il ruolo giocatori. Controlla ID canale/ruolo e permessi del bot."
        )


# =========================
# CREATE SPECIAL EVENT MARKET
# =========================
@bot.command(aliases=["creaevento"])
@admin_only()
async def createevent(ctx, category: str, *, question):
    await delete_admin_command_message(ctx)
    category_key = category.lower().strip()

    if category_key not in SPECIAL_EVENT_CATEGORIES:
        categories = "\n".join([f"`{k}` → {v}" for k, v in SPECIAL_EVENT_CATEGORIES.items()])
        await ctx.send(f"❌ Categoria non valida. Categorie disponibili:\n{categories}")
        return

    category_label = SPECIAL_EVENT_CATEGORIES[category_key]

    c.execute("""
        INSERT INTO markets (
            question,
            yes_pool,
            no_pool,
            total_pool,
            active,
            match_key,
            resolved,
            result,
            channel_id,
            alert_yes_price,
            event_category
        )
        VALUES (?, 0, 0, 0, 1, ?, 0, NULL, ?, 50, ?)
    """, (question, f"EVENT_{category_key.upper()}", str(ctx.channel.id), category_key))

    market_id = c.lastrowid
    conn.commit()

    embed = discord.Embed(
        title="🎲 Evento Speciale creato",
        description=question,
        color=COLOR_BLACK
    )
    embed.add_field(name="🏷️ Categoria", value=category_label, inline=False)
    embed.add_field(name="🆔 Mercato", value=f"#{market_id}", inline=True)
    embed.set_footer(text="Il mercato dovrà essere risolto manualmente con !resolve ID YES/NO")
    await ctx.send(embed=embed)
    await log_admin_activity(
        ctx,
        "🎲 !createevent",
        market_id=market_id,
        details=f"Categoria {category_label} • {question}",
        color=COLOR_BLACK
    )


# =========================
# MARKETS VIEW
# =========================
@bot.command(aliases=["mercati"])
async def markets(ctx):
    c.execute("SELECT id, question, yes_pool, no_pool FROM markets WHERE active=1")
    rows = c.fetchall()

    if not rows:
        await ctx.send("📭 Nessun mercato attivo")
        return

    embed = discord.Embed(
        title="📊 Mercati attivi",
        description=f"Mercati disponibili: {len(rows)}",
        color=COLOR_PURPLE
    )

    for mid, q, yes, no in rows[:10]:
        total = yes + no
        yp, np = market_probabilities(yes, no)
        embed.add_field(
            name=f"🆔 Mercato {mid}",
            value=(
                f"❓ {q}\n"
                f"🟢 YES: **{yp}%** `{progress_bar(yp, 10)}`\n"
                f"🔴 NO: **{np}%**\n"
                f"💰 Pool: **{total}**"
            ),
            inline=False
        )

    if len(rows) > 10:
        embed.set_footer(text="Mostro i primi 10 mercati attivi")
    else:
        embed.set_footer(text="Usa !market ID o !mercato ID per il dettaglio")

    await ctx.send(embed=embed)

# =========================
# SINGLE MARKET VIEW
# =========================
@bot.command(aliases=["mercato"])
async def market(ctx, market_id: int):
    c.execute("""
        SELECT question, yes_pool, no_pool, active, resolved, result, match_key
        FROM markets
        WHERE id=?
    """, (market_id,))

    row = c.fetchone()

    if not row:
        await ctx.send("❌ Mercato non trovato")
        return

    q, yes, no, active, resolved, result, match_key = row
    total = yes + no
    yes_p, no_p = market_probabilities(yes, no)

    match_line = "N/D"
    api_status = "N/D"
    score = None

    if match_key and match_key.startswith("MATCH_"):
        match_id = match_key.replace("MATCH_", "")
        res = get_match_result(match_id)

        if res:
            match_line = f'{res["home"]} vs {res["away"]}'
            api_status = res["status"]
            if res["home_goals"] is not None and res["away_goals"] is not None:
                score = f'{res["home_goals"]}-{res["away_goals"]}'

    if active == 1:
        status = "🟢 ATTIVO"
    elif resolved == 1:
        status = f"⚪ CHIUSO | Risultato mercato: {result}"
    else:
        status = "⚪ CHIUSO"

    embed = discord.Embed(
        title=f"📊 Mercato #{market_id}",
        description=q,
        color=COLOR_PURPLE
    )
    embed.add_field(name="🏟️ Partita", value=match_line, inline=False)
    embed.add_field(name="📡 Stato API", value=api_status, inline=True)
    if score:
        embed.add_field(name="⚽ Risultato", value=score, inline=True)
    embed.add_field(name="📉 Stato mercato", value=status, inline=True)
    embed.add_field(name="🟢 YES", value=f"**{yes_p}%**\n`{progress_bar(yes_p)}`", inline=True)
    embed.add_field(name="🔴 NO", value=f"**{no_p}%**\n`{progress_bar(no_p)}`", inline=True)
    volume_stats = get_market_volume_stats(market_id)
    embed.add_field(name="💰 Pool totale", value=str(total), inline=True)
    embed.add_field(name="📦 Volume", value=f"{volume_stats['total_volume']} crediti", inline=True)
    embed.add_field(name="🔁 Trade", value=str(volume_stats['trades']), inline=True)
    embed.set_footer(text="Usa !buy, !sell, !chart, !volume oppure gli alias italiani !compra, !vendi, !grafico")

    await ctx.send(embed=embed)

# =========================
# PORTFOLIO
# =========================
@bot.command(aliases=["portafoglio"])
async def portfolio(ctx):
    user_id = str(ctx.author.id)
    balance = get_user(user_id)
    rows = get_open_positions(user_id)

    if not rows:
        embed = discord.Embed(
            title=f"💼 Portafoglio di {ctx.author.display_name}",
            description="Non hai ancora aperto nessuna posizione.",
            color=COLOR_BLUE
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        embed.add_field(name="💰 Saldo", value=f"{balance} crediti", inline=False)
        apply_cosmetics_to_embed(embed, user_id, ctx.author, "Comando disponibile anche come !portafoglio")
        await ctx.send(embed=embed)
        return

    total_invested = 0.0
    total_value = 0.0
    total_possible_win = 0.0
    position_lines = []

    for _, market_id, question, yes, no, total, active, resolved, result, match_key, side, amount, entry_price in rows:
        yes_p, no_p = market_probabilities(yes, no)
        current_price = yes_p if side == "YES" else no_p
        entry_price = safe_entry_price(entry_price, current_price)

        invested = float(amount)
        current_value = invested * (current_price / entry_price)

        possible_win = invested
        if side == "YES" and yes > 0:
            possible_win += invested * (no / yes)
        elif side == "NO" and no > 0:
            possible_win += invested * (yes / no)

        profit = current_value - invested
        profit_pct = 0 if invested == 0 else (profit / invested) * 100

        total_invested += invested
        total_value += current_value
        total_possible_win += possible_win

        status = "🟢 Attivo" if active else f"⚪ Chiuso ({result})"
        emoji = "🟢" if side == "YES" else "🔴"
        short_question = question if len(question) <= 80 else question[:77] + "..."

        position_lines.append(
            f"**Mercato {market_id}** | {emoji} **{side}** | {status}\n"
            f"❓ {short_question}\n"
            f"📦 Quota cumulativa: **{amount}** crediti\n"
            f"💸 Investito: **{invested:.0f}** | 📈 Valore: **{current_value:.0f}** | 💰 Vincita: **{possible_win:.0f}**\n"
            f"🎯 Prezzo medio: **{entry_price:.1f}%** | 📍 Prezzo attuale: **{current_price:.1f}%**\n"
            f"📊 P/L non realizzato: **{profit:+.0f}** ({profit_pct:+.1f}%)"
        )

    total_profit = total_value - total_invested
    total_profit_pct = 0 if total_invested == 0 else (total_profit / total_invested) * 100
    color = COLOR_GREY

    embed = discord.Embed(
        title=f"💼 Portafoglio di {ctx.author.display_name}",
        color=color
    )
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    embed.add_field(name="💰 Saldo", value=f"{balance}", inline=True)
    embed.add_field(name="💸 Investito", value=f"{total_invested:.0f}", inline=True)
    embed.add_field(name="📈 Valore attuale", value=f"{total_value:.0f}", inline=True)
    embed.add_field(name="💰 Possibile vincita", value=f"{total_possible_win:.0f}", inline=True)
    embed.add_field(name="📊 Profitto totale", value=f"{total_profit:+.0f} ({total_profit_pct:+.1f}%)", inline=True)
    embed.add_field(name="📌 Posizioni", value=str(len(rows)), inline=True)

    description = "\n\n".join(position_lines[:6])
    if len(rows) > 6:
        description += f"\n\n_Altre {len(rows) - 6} posizioni non mostrate._"

    embed.description = description
    apply_cosmetics_to_embed(embed, user_id, ctx.author, "Comando disponibile anche come !portafoglio")

    await ctx.send(embed=embed)

# =========================
# FOLLOW SYSTEM
# =========================
@bot.command()
async def follow(ctx, member: discord.Member):
    follower_id = str(ctx.author.id)
    followed_id = str(member.id)

    if member.bot:
        await ctx.send("❌ Non puoi seguire un bot.")
        return

    if follower_id == followed_id:
        await ctx.send("❌ Non puoi seguire te stesso.")
        return

    now = datetime.now(timezone.utc).isoformat()
    c.execute("""
        INSERT OR IGNORE INTO follows (follower_user_id, followed_user_id, created_at)
        VALUES (?, ?, ?)
    """, (follower_id, followed_id, now))
    conn.commit()

    await evaluate_user_badges(follower_id, notify=True)

    await ctx.send(f"✅ Ora segui {member.mention}.")


@bot.command()
async def unfollow(ctx, member: discord.Member):
    follower_id = str(ctx.author.id)
    followed_id = str(member.id)

    c.execute("DELETE FROM follows WHERE follower_user_id=? AND followed_user_id=?", (follower_id, followed_id))
    conn.commit()

    await ctx.send(f"✅ Hai smesso di seguire {member.mention}.")


@bot.command()
async def following(ctx):
    user_id = str(ctx.author.id)
    c.execute("""
        SELECT followed_user_id
        FROM follows
        WHERE follower_user_id=?
        ORDER BY created_at DESC
        LIMIT 25
    """, (user_id,))
    rows = c.fetchall()

    if not rows:
        await ctx.send("📭 Non segui ancora nessun trader.")
        return

    lines = []
    for (followed_id,) in rows:
        xp, *_ = get_user_stats(followed_id)
        level, _, _ = trader_level_from_xp(xp)
        lines.append(f"👤 <@{followed_id}> — {level}")

    embed = discord.Embed(
        title="👥 Trader seguiti",
        description="\n".join(lines),
        color=COLOR_BLUE
    )
    embed.set_footer(text="Usa !trader @utente per vedere una scheda sintetica.")
    await ctx.send(embed=embed)


@bot.command()
async def trader(ctx, member: discord.Member):
    user_id = str(member.id)
    get_user(user_id)
    await evaluate_user_badges(user_id, notify=False)

    metrics = get_user_metrics(user_id)
    level, xp_current, xp_required = trader_level_from_xp(metrics["xp"])
    rank_text = f"#{metrics['rank']}" if metrics["rank"] else "N/D"

    badge_ids = get_active_badges(user_id)
    badge_text = " • ".join(format_badge(b) for b in badge_ids[:8]) if badge_ids else "Nessun badge."

    embed = discord.Embed(
        title=f"👤 Trader: {member.display_name} • {level}",
        color=COLOR_GREEN
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="🏆 Rank", value=rank_text, inline=True)
    embed.add_field(name="💰 Saldo", value=str(metrics["balance"]), inline=True)
    embed.add_field(name="💼 Patrimonio stimato", value=f"{metrics['net_worth']:.0f}", inline=True)
    embed.add_field(name="🎯 Accuracy", value=f"{metrics['accuracy']:.1f}%", inline=True)
    embed.add_field(name="🔥 Streak", value=str(metrics["current_streak"]), inline=True)
    embed.add_field(name="📜 Trade", value=str(metrics["total_trades"]), inline=True)
    embed.add_field(name="🏆 Vinti/Persi", value=f"{metrics['won_markets']} / {metrics['lost_markets']}", inline=True)
    embed.add_field(name="📈 XP", value=f"{xp_current}/{xp_required}", inline=True)
    embed.add_field(name="🏅 Badge", value=badge_text, inline=False)
    await ctx.send(embed=embed)


# =========================
# PROFILE
# =========================
@bot.command(aliases=["profilo"])
async def profile(ctx):
    user_id = str(ctx.author.id)
    balance = get_user(user_id)
    await evaluate_user_badges(user_id, notify=True)

    total_invested, total_value, _, open_positions = calculate_user_open_value(user_id)
    net_worth = balance + total_value
    open_profit = total_value - total_invested
    roi = 0 if total_invested == 0 else (open_profit / total_invested) * 100

    c.execute("""
        SELECT COUNT(DISTINCT m.id)
        FROM trades t
        JOIN markets m ON t.market_id=m.id
        WHERE t.user_id=?
          AND m.resolved=1
    """, (user_id,))
    resolved_markets = c.fetchone()[0] or 0

    c.execute("""
        SELECT COUNT(DISTINCT m.id)
        FROM trades t
        JOIN markets m ON t.market_id=m.id
        WHERE t.user_id=?
          AND m.resolved=1
          AND t.side=m.result
    """, (user_id,))
    won_markets = c.fetchone()[0] or 0

    lost_markets = max(0, resolved_markets - won_markets)
    accuracy = 0 if resolved_markets == 0 else (won_markets / resolved_markets) * 100

    c.execute("SELECT COUNT(*) FROM trades WHERE user_id=?", (user_id,))
    total_trades = c.fetchone()[0] or 0

    xp, current_streak, best_streak, _ = get_user_stats(user_id)
    trader_level, xp_current, xp_required = trader_level_from_xp(xp)
    server_level = get_server_level_from_roles(ctx.author)
    rank = calculate_server_rank(user_id)
    rank_text = f"#{rank}" if rank else "N/D"

    color = COLOR_GREY
    profit_emoji = "🟢" if open_profit >= 0 else "🔴"

    status_emoji = get_status_emoji_from_level(trader_level)
    identity_lines = get_profile_identity_lines(user_id)
    profile_description = identity_lines + ("\n\n" if identity_lines else "") + "Scheda personale del trader"

    embed = discord.Embed(
        title=f"👤 Profilo di {ctx.author.display_name} {status_emoji}",
        description=profile_description,
        color=color
    )
    embed.set_thumbnail(url=ctx.author.display_avatar.url)

    embed.add_field(name="⭐ Livello server", value=server_level, inline=True)
    embed.add_field(name="💹 Livello trader", value=trader_level, inline=True)
    embed.add_field(name="🏆 Rank", value=rank_text, inline=True)

    embed.add_field(name="💰 Saldo", value=f"{balance}", inline=True)
    embed.add_field(name="💼 Patrimonio stimato", value=f"{net_worth:.0f}", inline=True)
    embed.add_field(name="📈 XP trader", value=f"{xp_current}/{xp_required}", inline=True)

    embed.add_field(name=f"{profit_emoji} Profitto aperto", value=f"{open_profit:+.0f} ({roi:+.1f}%)", inline=True)
    embed.add_field(name="🟢 Posizioni aperte", value=str(open_positions), inline=True)
    embed.add_field(name="📜 Trade totali", value=str(total_trades), inline=True)

    embed.add_field(name="🎯 Accuracy", value=f"{accuracy:.1f}%", inline=True)
    embed.add_field(name="🔥 Streak attuale", value=str(current_streak), inline=True)
    embed.add_field(name="🥇 Miglior streak", value=str(best_streak), inline=True)

    embed.add_field(name="🏆 Mercati vinti", value=str(won_markets), inline=True)
    embed.add_field(name="❌ Mercati persi", value=str(lost_markets), inline=True)
    embed.add_field(name="📊 Mercati risolti", value=str(resolved_markets), inline=True)

    badge_ids = get_active_badges(user_id)
    badge_text = " • ".join(format_badge(b) for b in badge_ids[:12]) if badge_ids else "Nessun badge sbloccato."
    if len(badge_text) > 1024:
        badge_text = badge_text[:1000] + "..."
    embed.add_field(name="🏅 Badge vinti", value=badge_text, inline=False)
    embed.add_field(name="🏺 Collezionabili acquistati", value=get_purchased_collectibles_text(user_id), inline=False)
    embed.add_field(name="🎨 Marketplace equipaggiato", value=get_equipped_items_text(user_id), inline=False)

    apply_cosmetics_to_embed(embed, user_id, ctx.author, "Comando disponibile anche come !profilo", show_collectible=False)

    await ctx.send(embed=embed)


# =========================
# LEADERBOARD
# =========================
@bot.command(aliases=["classifica"])
async def leaderboard(ctx):
    c.execute("SELECT user_id, balance FROM users")
    users = c.fetchall()

    if not users:
        await ctx.send("📭 Nessun utente in classifica")
        return

    ranking = []

    for user_id, balance in users:
        _, open_value, _, _ = calculate_user_open_value(user_id)
        net_worth = balance + open_value
        ranking.append((user_id, balance, open_value, net_worth))

    ranking.sort(key=lambda x: x[3], reverse=True)

    embed = discord.Embed(
        title="🏆 Classifica trader",
        description="Classifica per patrimonio stimato: saldo + valore posizioni aperte",
        color=COLOR_GOLD
    )

    medals = ["🥇", "🥈", "🥉"]

    for i, (user_id, balance, open_value, net_worth) in enumerate(ranking[:10], start=1):
        medal = medals[i - 1] if i <= 3 else f"#{i}"
        equipped = get_equipped_items(user_id)
        title_item = SHOP_ITEMS.get(equipped.get("title")) if equipped.get("title") else None
        showcase_item = SHOP_ITEMS.get(equipped.get("showcase")) if equipped.get("showcase") else None
        cosmetic_line = ""
        if title_item:
            cosmetic_line += f"\n🎖️ {title_item['emoji']} {title_item['name']}"
        if showcase_item:
            cosmetic_line += f"\n🎨 {showcase_item['emoji']} {showcase_item['name']}"
        embed.add_field(
            name=f"{medal} Posizione {i}",
            value=(
                f"👤 <@{user_id}>{cosmetic_line}\n"
                f"💼 Patrimonio: **{net_worth:.0f}**\n"
                f"💰 Saldo: {balance}\n"
                f"📈 Posizioni aperte: {open_value:.0f}"
            ),
            inline=False
        )

    embed.set_footer(text="Comando disponibile anche come !classifica")
    await ctx.send(embed=embed)

# =========================
# LIVE / ESPN SCOREBOARD
# =========================
ESPN_SOCCER_LEAGUES = {
    # Stessi tornei principali previsti da football-data.org, dove ESPN espone lo scoreboard pubblico.
    "fifa.world": "FIFA World Cup",              # WC
    "uefa.champions": "Champions League",       # CL
    "ger.1": "Bundesliga",                      # BL1
    "ned.1": "Eredivisie",                      # DED
    "bra.1": "Brasileirão Série A",             # BSA
    "esp.1": "La Liga",                         # PD
    "fra.1": "Ligue 1",                         # FL1
    "eng.2": "Championship",                    # ELC
    "por.1": "Primeira Liga",                   # PPL
    "uefa.euro": "European Championship",       # EC
    "ita.1": "Serie A",                         # SA
    "eng.1": "Premier League",                  # PL
    "uefa.europa": "Europa League",
    "uefa.europa.conf": "Conference League",
}

ESPN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CalcyscordBot/2.0; +https://discord.com)",
    "Accept": "application/json,text/plain,*/*",
}


def espn_scoreboard_url(league_code):
    return f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_code}/scoreboard"


def fetch_espn_scoreboard(league_code):
    return request_json(espn_scoreboard_url(league_code), headers=ESPN_HEADERS, timeout=12)


def espn_competitors(event):
    comps = event.get("competitions") or []
    comp = comps[0] if comps else {}
    competitors = comp.get("competitors") or []
    home = {"id": None, "name": "Casa", "score": "-"}
    away = {"id": None, "name": "Trasferta", "score": "-"}

    for team_data in competitors:
        team = team_data.get("team") or {}
        item = {
            "id": str(team.get("id") or team_data.get("id") or ""),
            "name": team.get("displayName") or team.get("shortDisplayName") or team.get("name") or "Squadra",
            "score": team_data.get("score", "-"),
        }
        if team_data.get("homeAway") == "home":
            home = item
        elif team_data.get("homeAway") == "away":
            away = item

    return home, away


def espn_event_venue(event):
    comps = event.get("competitions") or []
    comp = comps[0] if comps else {}
    venue = comp.get("venue") or event.get("venue") or {}
    if not isinstance(venue, dict):
        return ""

    name = venue.get("fullName") or venue.get("name") or ""
    address = venue.get("address") or {}
    city = address.get("city") if isinstance(address, dict) else ""

    if name and city:
        return f"{name}, {city}"
    return name or city or ""


def _espn_detail_text(detail):
    """Testo grezzo di un evento ESPN, usato come fallback."""
    parts = []
    if isinstance(detail, dict):
        for key in ["text", "displayText", "description", "headline", "shortText"]:
            value = detail.get(key)
            if value:
                parts.append(str(value))
        type_data = detail.get("type") or {}
        if isinstance(type_data, dict):
            for key in ["text", "name", "abbreviation", "description", "shortDetail"]:
                value = type_data.get(key)
                if value:
                    parts.append(str(value))
    return " ".join(p for p in parts if p).strip()


def _espn_detail_search_text(detail):
    return _espn_detail_text(detail).lower()


def _espn_detail_team_side(detail, home_id, away_id):
    team = detail.get("team") or {}
    team_id = ""
    if isinstance(team, dict):
        team_id = str(team.get("id") or "")
    team_id = team_id or str(detail.get("teamId") or detail.get("team_id") or "")

    if team_id and home_id and team_id == str(home_id):
        return "home"
    if team_id and away_id and team_id == str(away_id):
        return "away"
    return None


def _espn_event_minute(detail):
    clock = detail.get("clock") or {}
    minute = ""
    if isinstance(clock, dict):
        minute = clock.get("displayValue") or clock.get("displayClock") or clock.get("value") or ""
    minute = minute or detail.get("displayClock") or detail.get("time") or detail.get("minute") or ""
    minute = str(minute).strip()
    if minute and minute.isdigit():
        minute = f"{minute}'"
    return minute


def _espn_person_name(obj):
    if not isinstance(obj, dict):
        return ""
    for key in ["displayName", "shortName", "fullName", "name", "athleteName"]:
        value = obj.get(key)
        if value:
            return str(value).strip()
    athlete = obj.get("athlete") or obj.get("player")
    if isinstance(athlete, dict):
        return _espn_person_name(athlete)
    return ""


def _espn_detail_people(detail):
    """Estrae nomi calciatori da varie strutture ESPN possibili.

    ESPN, per il calcio, spesso usa `athletesInvolved` negli eventi live
    (gol, cartellini, sostituzioni). Se non lo leggiamo, il bot vede solo
    etichette generiche tipo `Goal` o `Yellow Card`.
    """
    people = []

    for key in [
        "athletesInvolved",
        "athleteInvolved",
        "participantsInvolved",
        "playersInvolved",
        "athletes",
        "participants",
        "players",
        "competitors",
    ]:
        value = detail.get(key)
        if isinstance(value, list):
            for item in value:
                name = _espn_person_name(item)
                if name and name not in people:
                    people.append(name)
        elif isinstance(value, dict):
            name = _espn_person_name(value)
            if name and name not in people:
                people.append(name)

    for key in ["athlete", "participant", "player"]:
        value = detail.get(key)
        if isinstance(value, dict):
            name = _espn_person_name(value)
            if name and name not in people:
                people.append(name)

    return people


def _espn_clean_event_fallback(text):
    text = str(text or "").strip()
    if not text:
        return "Evento"
    # Evita fallback troppo generici quando ESPN non espone il nome.
    low = text.lower()
    if low in {"goal", "gol", "yellow card", "red card"}:
        return text.title()
    return text[:90]


def _espn_format_event_line(minute, label):
    label = _espn_clean_event_fallback(label)
    return f"{minute} {label}".strip()[:140]



def _espn_penalty_result(text):
    low = (text or "").lower()
    if any(k in low for k in ["saved", "parato", "save"]):
        return "❌ Parato"
    if any(k in low for k in ["missed", "fuori", "off target"]):
        return "❌ Fuori"
    if any(k in low for k in ["scored", "made", "goal", "gol"]):
        return "✅ Goal"
    return "🎯 Rigore"


def espn_event_details_summary(event):
    comps = event.get("competitions") or []
    comp = comps[0] if comps else {}
    details = comp.get("details") or event.get("details") or []
    home, away = espn_competitors(event)
    home_id, away_id = home.get("id"), away.get("id")

    cards_y = {"home": 0, "away": 0}
    cards_r = {"home": 0, "away": 0}

    scorers = []
    yellows = []
    reds = []
    penalties = []

    if not isinstance(details, list):
        details = []

    for detail in details:
        if not isinstance(detail, dict):
            continue

        raw_text = _espn_detail_text(detail)
        text = raw_text.lower()
        type_data = detail.get("type") or {}
        type_id = str(type_data.get("id") or "") if isinstance(type_data, dict) else ""
        side = _espn_detail_team_side(detail, home_id, away_id)
        minute = _espn_event_minute(detail)
        people = _espn_detail_people(detail)

        # Usiamo sia il testo sia i flag/ID ESPN: alcuni eventi live hanno
        # campi strutturati ma poco testo descrittivo.
        is_yellow = bool(detail.get("yellowCard")) or "yellow" in text or "ammon" in text or type_id in {"74"}
        is_red = bool(detail.get("redCard")) or "red" in text or "espuls" in text or type_id in {"75"}
        is_penalty = bool(detail.get("penaltyKick")) or "penalty" in text or "rigor" in text
        is_goal = (
            bool(detail.get("scoringPlay"))
            or detail.get("scoreValue") not in (None, 0, "0")
            or any(k in text for k in ["goal", "gol", "own goal", "penalty - scored"])
        ) and not is_yellow and not is_red

        if side and is_yellow:
            cards_y[side] += 1
        if side and is_red:
            cards_r[side] += 1

        if is_goal:
            name = people[0] if people else ""
            label = name or raw_text or "Goal"
            if is_penalty and name:
                label = f"{name} (rig.)"
            scorers.append(_espn_format_event_line(minute, label))

        if is_yellow:
            label = (people[0] if people else raw_text or "Ammonizione")
            yellows.append(_espn_format_event_line(minute, label))

        if is_red:
            label = (people[0] if people else raw_text or "Espulsione")
            reds.append(_espn_format_event_line(minute, label))


        # Se ESPN invia una sequenza rigori, la mostriamo in sezione dedicata.
        if is_penalty and not is_yellow and not is_red:
            name = people[0] if people else raw_text or "Rigore"
            result = _espn_penalty_result(raw_text)
            if name and result not in name:
                penalties.append(_espn_format_event_line(minute, f"{result} {name}"))
            else:
                penalties.append(_espn_format_event_line(minute, result))

    return {
        "yellow": cards_y,
        "red": cards_r,
        "scorers": scorers[:8],
        "yellows": yellows[:8],
        "reds": reds[:8],
        "penalties": penalties[:10],
    }

def espn_event_is_live(event):
    status = event.get("status") or {}
    type_data = status.get("type") or {}
    state = str(type_data.get("state") or "").lower()
    name = str(type_data.get("name") or type_data.get("description") or "").lower()
    return state == "in" or "in progress" in name or "halftime" in name


def espn_event_status_text(event):
    """Formato pulito: minuto una sola volta + fase partita."""
    status = event.get("status") or {}
    type_data = status.get("type") or {}

    display_clock = str(status.get("displayClock") or "").strip()
    short_detail = str(
        event.get("shortDetail")
        or type_data.get("shortDetail")
        or type_data.get("description")
        or type_data.get("name")
        or "LIVE"
    ).strip()

    state_text = " ".join([
        str(type_data.get("name") or ""),
        str(type_data.get("description") or ""),
        str(type_data.get("detail") or ""),
        str(short_detail or ""),
    ]).lower()

    period = status.get("period") or event.get("period")
    phase = ""

    if any(k in state_text for k in ["halftime", "half time", "intervallo"]):
        return "Intervallo"
    if any(k in state_text for k in ["full time", "final", "finished", "fine partita"]):
        return "Fine partita"
    if any(k in state_text for k in ["penalty", "shootout", "rigori"]):
        phase = "Rigori"
    elif any(k in state_text for k in ["extra time", "supplementari"]):
        phase = "Tempi supplementari"
    else:
        try:
            pnum = int(period)
        except Exception:
            pnum = None
        if pnum == 1:
            phase = "1° Tempo"
        elif pnum == 2:
            phase = "2° Tempo"
        elif pnum in (3, 4):
            phase = "Tempi supplementari"

    # Evita casi tipo "45'+4' • 45'+4'".
    if display_clock and short_detail and display_clock.strip().lower() == short_detail.strip().lower():
        short_detail = ""

    if display_clock and phase:
        return f"{display_clock} • {phase}"
    if display_clock:
        return display_clock
    if phase:
        return phase
    return short_detail or "LIVE"

def fetch_espn_live_matches():
    matches = []
    diagnostics = []

    for league_code, league_name in ESPN_SOCCER_LEAGUES.items():
        status, data = fetch_espn_scoreboard(league_code)
        events = data.get("events") or [] if isinstance(data, dict) else []
        live_events = []

        if status == 200:
            for event in events:
                if espn_event_is_live(event):
                    home, away = espn_competitors(event)
                    live_events.append({
                        "league_code": league_code,
                        "league": league_name,
                        "event_id": event.get("id"),
                        "home": home["name"],
                        "away": away["name"],
                        "home_score": home["score"],
                        "away_score": away["score"],
                        "status": espn_event_status_text(event),
                        "venue": espn_event_venue(event),
                        "details": espn_event_details_summary(event),
                    })
        else:
            print(f"[ESPN LIVE] {league_code} status {status}: {data}")

        diagnostics.append({
            "league": league_name,
            "code": league_code,
            "status": status,
            "events": len(events),
            "live": len(live_events),
        })
        matches.extend(live_events)

    return matches, diagnostics


@bot.command(aliases=["diretta"])
async def live(ctx):
    """Mostra le partite live tramite ESPN scoreboard, con fallback sui mercati football-data.org."""
    matches, diagnostics = fetch_espn_live_matches()

    if matches:
        embed = discord.Embed(
            title="🔴 Live calcio",
            description="Partite in corso da ESPN scoreboard pubblico.",
            color=COLOR_RED,
            timestamp=datetime.now(timezone.utc)
        )

        for m in matches[:10]:
            details = m.get("details") or {}
            yellow = details.get("yellow") or {}
            red = details.get("red") or {}
            scorers = details.get("scorers") or []
            yellows = details.get("yellows") or []
            reds = details.get("reds") or []
            penalties = details.get("penalties") or []

            lines = [
                f"🏆 {m['league']}",
                f"🕒 {m['status']}",
            ]
            if m.get("venue"):
                # Manteniamo lo stadio completo, come richiesto.
                lines.append(f"🏟️ Stadio: {m['venue']}")
            if scorers:
                lines.append("⚽ Marcatori\n" + "\n".join(scorers[:5]))
            if yellows:
                lines.append("🟨 Ammoniti\n" + "\n".join(yellows[:5]))
            elif (yellow.get("home") or yellow.get("away")):
                lines.append(f"🟨 Cartellini: {yellow.get('home', 0)}-{yellow.get('away', 0)}")
            if reds:
                lines.append("🟥 Espulsi\n" + "\n".join(reds[:5]))
            elif (red.get("home") or red.get("away")):
                lines.append(f"🟥 Espulsioni: {red.get('home', 0)}-{red.get('away', 0)}")
            if penalties:
                lines.append("🎯 Rigori\n" + "\n".join(penalties[:6]))

            embed.add_field(
                name=f"⚽ {m['home']} {m['home_score']}-{m['away_score']} {m['away']}",
                value="\n\n".join(lines)[:1024],
                inline=False
            )

        embed.set_footer(text="Comando disponibile anche come !diretta • ESPN fallback gratuito")
        await ctx.send(embed=embed)
        return

    # Se ESPN non trova live, mostriamo eventuali mercati live football-data.org.
    await live_football_data_fallback(ctx)


@bot.command()
@admin_only()
async def testespn(ctx):
    """Diagnostica admin per controllare se ESPN restituisce partite live."""
    matches, diagnostics = fetch_espn_live_matches()
    embed = discord.Embed(
        title="🧪 Test ESPN Live",
        description=f"Partite live trovate: **{len(matches)}**",
        color=COLOR_CYAN,
        timestamp=datetime.now(timezone.utc)
    )

    lines = []
    for d in diagnostics:
        lines.append(f"`{d['code']}` {d['league']}: HTTP {d['status']} • eventi {d['events']} • live {d['live']}")

    embed.add_field(name="Endpoint controllati", value="\n".join(lines)[:1024] or "N/D", inline=False)

    if matches:
        live_lines = []
        for m in matches[:8]:
            venue = f" • {m['venue']}" if m.get("venue") else ""
            live_lines.append(f"{m['league']}: {m['home']} {m['home_score']}-{m['away_score']} {m['away']} ({m['status']}){venue}")
        embed.add_field(name="Live", value="\n".join(live_lines)[:1024], inline=False)

    embed.set_footer(text="ESPN è un endpoint pubblico non ufficiale: usare sempre con fallback.")
    await ctx.send(embed=embed)


async def live_football_data_fallback(ctx):
    c.execute("""
        SELECT id, question, yes_pool, no_pool, total_pool, match_key
        FROM markets
        WHERE active=1
    """)

    rows = c.fetchall()

    if not rows:
        await ctx.send("📭 Nessuna partita live trovata e nessun mercato attivo")
        return

    embed = discord.Embed(
        title="🔴 Mercati live",
        description="Fallback football-data.org sui mercati attivi",
        color=COLOR_RED
    )
    found_live = False

    for market_id, question, yes, no, total, match_key in rows:
        if not match_key or not match_key.startswith("MATCH_"):
            continue

        try:
            match_id = int(match_key.replace("MATCH_", ""))
        except Exception:
            continue

        res = get_match_result(match_id)

        if not res:
            continue

        if res["status"] not in ["IN_PLAY", "PAUSED", "LIVE"]:
            continue

        found_live = True
        yes_p, no_p = market_probabilities(yes, no)

        score = "N/D"
        if res["home_goals"] is not None and res["away_goals"] is not None:
            score = f'{res["home_goals"]}-{res["away_goals"]}'

        embed.add_field(
            name=f"🆔 Mercato {market_id} | {res['home']} vs {res['away']}",
            value=(
                f"⚽ Risultato: **{score}** | 📡 {res['status']}\n"
                f"❓ {question}\n"
                f"🟢 YES: **{yes_p}%** `{progress_bar(yes_p, 10)}`\n"
                f"🔴 NO: **{no_p}%**\n"
                f"💰 Pool: **{total}**"
            ),
            inline=False
        )

    if not found_live:
        await ctx.send("📭 Nessuna partita live in questo momento")
        return

    embed.set_footer(text="Comando disponibile anche come !diretta")
    await ctx.send(embed=embed)


# =========================
# BUY + PRICE UPDATE
# =========================
@bot.command(aliases=["compra"])
async def buy(ctx, market_id: int, side: str, amount: int):
    user_id = str(ctx.author.id)
    side = side.upper()

    if amount <= 0:
        await ctx.send("❌ Importo non valido")
        return

    if side not in ["YES", "NO"]:
        await ctx.send("❌ Side non valido (YES/NO)")
        return

    c.execute("SELECT active FROM markets WHERE id=?", (market_id,))
    m = c.fetchone()

    if not m or m[0] == 0:
        await ctx.send("❌ Mercato chiuso")
        return

    c.execute("""
        SELECT COALESCE(SUM(COALESCE(buy_count, 1)), 0)
        FROM trades
        WHERE user_id=?
          AND market_id=?
    """, (user_id, market_id))
    buy_count = c.fetchone()[0] or 0

    if buy_count >= MAX_BUYS_PER_USER_MARKET:
        await ctx.send(f"❌ Hai già raggiunto il limite di {MAX_BUYS_PER_USER_MARKET} acquisti su questo mercato.")
        return

    bal = get_user(user_id)

    if bal < amount:
        await ctx.send("❌ Fondi insufficienti")
        return

    c.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, user_id))

    if side == "YES":
        c.execute("""
            UPDATE markets
            SET yes_pool = yes_pool + ?,
                total_pool = total_pool + ?,
                trade_count = COALESCE(trade_count, 0) + 1,
                buy_volume = COALESCE(buy_volume, 0) + ?,
                total_volume = COALESCE(total_volume, 0) + ?
            WHERE id=?
        """, (amount, amount, amount, amount, market_id))
    else:
        c.execute("""
            UPDATE markets
            SET no_pool = no_pool + ?,
                total_pool = total_pool + ?,
                trade_count = COALESCE(trade_count, 0) + 1,
                buy_volume = COALESCE(buy_volume, 0) + ?,
                total_volume = COALESCE(total_volume, 0) + ?
            WHERE id=?
        """, (amount, amount, amount, amount, market_id))

    c.execute("SELECT yes_pool, no_pool FROM markets WHERE id=?", (market_id,))
    yes, no = c.fetchone()

    yes_p, no_p = market_probabilities(yes, no)
    trade_price = yes_p if side == "YES" else no_p

    # Posizioni cumulative: se l'utente ha già una posizione aperta sullo
    # stesso mercato/lato, aggiorniamo quella riga invece di crearne una nuova.
    # Il prezzo viene ricalcolato come media ponderata.
    c.execute("""
        SELECT id, amount, price, COALESCE(buy_count, 1)
        FROM trades
        WHERE user_id=?
          AND market_id=?
          AND side=?
          AND amount > 0
          AND (closed IS NULL OR closed=0)
        ORDER BY id ASC
        LIMIT 1
    """, (user_id, market_id, side))
    existing_position = c.fetchone()

    if existing_position:
        trade_id, old_amount, old_price, old_buy_count = existing_position
        old_amount = old_amount or 0
        old_price = safe_entry_price(old_price, trade_price)
        new_amount = old_amount + amount
        new_avg_price = ((old_amount * old_price) + (amount * trade_price)) / new_amount

        c.execute("""
            UPDATE trades
            SET amount=?,
                price=?,
                buy_count=?
            WHERE id=?
        """, (new_amount, new_avg_price, (old_buy_count or 1) + 1, trade_id))
    else:
        c.execute("""
            INSERT INTO trades (user_id, market_id, side, amount, price, closed, buy_count)
            VALUES (?, ?, ?, ?, ?, 0, 1)
        """, (user_id, market_id, side, amount, trade_price))

    save_price(market_id, yes_p)
    award_xp(user_id, max(5, amount // 20))
    record_wealth_snapshot(user_id)
    conn.commit()

    embed = discord.Embed(
        title="📈 Acquisto effettuato",
        color=COLOR_PINK
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    embed.add_field(name="🆔 Mercato", value=str(market_id), inline=True)
    embed.add_field(name="📊 Posizione", value=side, inline=True)
    embed.add_field(name="💸 Puntata", value=f"+{amount}", inline=True)
    embed.add_field(name="🟢 YES", value=f"{yes_p}%", inline=True)
    embed.add_field(name="🔴 NO", value=f"{no_p}%", inline=True)
    volume_stats = get_market_volume_stats(market_id)
    embed.add_field(name="📦 Volume mercato", value=f"{volume_stats['total_volume']} crediti", inline=True)
    c.execute("""
        SELECT SUM(amount),
               CASE
                   WHEN SUM(amount) > 0 THEN SUM(amount * COALESCE(price, 50)) / SUM(amount)
                   ELSE ?
               END
        FROM trades
        WHERE user_id=?
          AND market_id=?
          AND side=?
          AND amount > 0
          AND (closed IS NULL OR closed=0)
    """, (trade_price, user_id, market_id, side))
    cumulative_amount, avg_price = c.fetchone()
    embed.add_field(name="📦 Quota cumulativa", value=f"{int(cumulative_amount or amount)} crediti", inline=True)
    embed.add_field(name="🎯 Prezzo medio", value=f"{float(avg_price or trade_price):.1f}%", inline=True)
    embed.add_field(name="📉 Barra", value=f"`{progress_bar(yes_p)}`", inline=False)

    await ctx.send(embed=embed)
    await check_personal_alerts_for_market(market_id, fallback_channel=ctx.channel)
    await evaluate_user_badges(user_id, notify=True)

# =========================
# SELL POSITION
# =========================
@bot.command(aliases=["vendi"])
async def sell(ctx, market_id: int, percent: str, side: str = None):
    user_id = str(ctx.author.id)
    pct = parse_percent(percent)

    if pct is None:
        await ctx.send("❌ Percentuale non valida. Esempio: `!sell 3 50%`")
        return

    if side is not None:
        side = side.upper()
        if side not in ["YES", "NO"]:
            await ctx.send("❌ Side non valido. Usa YES o NO.")
            return

    c.execute("SELECT yes_pool, no_pool, active FROM markets WHERE id=?", (market_id,))
    market = c.fetchone()

    if not market:
        await ctx.send("❌ Mercato non trovato")
        return

    yes_pool, no_pool, active = market

    if active == 0:
        await ctx.send("❌ Non puoi vendere su un mercato chiuso")
        return

    c.execute("""
        SELECT id, side, amount, price
        FROM trades
        WHERE user_id=?
          AND market_id=?
          AND amount > 0
          AND (closed IS NULL OR closed=0)
        ORDER BY id ASC
    """, (user_id, market_id))
    rows = c.fetchall()

    if not rows:
        await ctx.send("❌ Non hai posizioni aperte su questo mercato")
        return

    sides_open = sorted(set(r[1] for r in rows))

    if side is None:
        if len(sides_open) > 1:
            await ctx.send("❌ Hai posizioni sia YES che NO. Specifica cosa vendere: `!sell 3 50% YES`")
            return
        side = sides_open[0]

    rows = [r for r in rows if r[1] == side]

    if not rows:
        await ctx.send(f"❌ Non hai posizioni aperte {side} su questo mercato")
        return

    yes_p, no_p = market_probabilities(yes_pool, no_pool)
    current_price = yes_p if side == "YES" else no_p

    total_position = sum(r[2] for r in rows)
    sell_amount = int(round(total_position * (pct / 100)))

    if sell_amount <= 0:
        await ctx.send("❌ Importo venduto troppo basso")
        return

    weighted_entry_sum = 0.0
    for _, _, amount, price in rows:
        entry_price = safe_entry_price(price, current_price)
        weighted_entry_sum += amount * entry_price

    avg_entry_price = weighted_entry_sum / total_position
    proceeds = int(round(sell_amount * (current_price / avg_entry_price)))
    profit = proceeds - sell_amount

    remaining_to_sell = sell_amount

    for trade_id, _, amount, _ in rows:
        if remaining_to_sell <= 0:
            break

        reduce_amount = min(amount, remaining_to_sell)
        new_amount = amount - reduce_amount

        if new_amount <= 0:
            c.execute("UPDATE trades SET amount=0, closed=1 WHERE id=?", (trade_id,))
        else:
            c.execute("UPDATE trades SET amount=? WHERE id=?", (new_amount, trade_id))

        remaining_to_sell -= reduce_amount

    pool_reduction = sell_amount

    if side == "YES":
        pool_reduction = min(pool_reduction, yes_pool)
        c.execute("""
            UPDATE markets
            SET yes_pool = yes_pool - ?,
                total_pool = MAX(total_pool - ?, 0),
                trade_count = COALESCE(trade_count, 0) + 1,
                sell_volume = COALESCE(sell_volume, 0) + ?,
                total_volume = COALESCE(total_volume, 0) + ?
            WHERE id=?
        """, (pool_reduction, pool_reduction, sell_amount, sell_amount, market_id))
    else:
        pool_reduction = min(pool_reduction, no_pool)
        c.execute("""
            UPDATE markets
            SET no_pool = no_pool - ?,
                total_pool = MAX(total_pool - ?, 0),
                trade_count = COALESCE(trade_count, 0) + 1,
                sell_volume = COALESCE(sell_volume, 0) + ?,
                total_volume = COALESCE(total_volume, 0) + ?
            WHERE id=?
        """, (pool_reduction, pool_reduction, sell_amount, sell_amount, market_id))

    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (proceeds, user_id))

    c.execute("SELECT yes_pool, no_pool FROM markets WHERE id=?", (market_id,))
    new_yes, new_no = c.fetchone()
    new_yes_p, new_no_p = market_probabilities(new_yes, new_no)
    save_price(market_id, new_yes_p)
    award_xp(user_id, max(3, proceeds // 25))
    record_wealth_snapshot(user_id)

    conn.commit()
    bal = get_user(user_id)

    embed = discord.Embed(
        title="💸 Posizione venduta",
        color=COLOR_PINK
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    embed.add_field(name="🆔 Mercato", value=str(market_id), inline=True)
    embed.add_field(name="📊 Side", value=side, inline=True)
    embed.add_field(name="📉 Venduto", value=f"{pct:.1f}%", inline=True)
    embed.add_field(name="💰 Incassato", value=str(proceeds), inline=True)
    embed.add_field(name="📊 Profitto/Perdita", value=f"{profit:+.0f}", inline=True)
    embed.add_field(name="💼 Saldo aggiornato", value=str(bal), inline=True)
    embed.add_field(name="🎯 Prezzo medio", value=f"{avg_entry_price:.1f}%", inline=True)
    embed.add_field(name="📍 Prezzo vendita", value=f"{current_price:.1f}%", inline=True)
    embed.add_field(name="🟢 YES", value=f"{new_yes_p}%", inline=True)
    embed.add_field(name="🔴 NO", value=f"{new_no_p}%", inline=True)
    volume_stats = get_market_volume_stats(market_id)
    embed.add_field(name="📦 Volume mercato", value=f"{volume_stats['total_volume']} crediti", inline=True)
    embed.add_field(name="📉 Barra", value=f"`{progress_bar(new_yes_p)}`", inline=False)

    await ctx.send(embed=embed)
    await evaluate_user_badges(user_id, notify=True)


# =========================
# V2.0.2 MARKET VOLUME + TOP MOVERS
# =========================
@bot.command(aliases=["volumi", "liquidita"])
async def volume(ctx, market_id: int = None):
    """Mostra volume e liquidità di un mercato o la top per volume."""
    if market_id is not None:
        c.execute("""
            SELECT question, yes_pool, no_pool, active, resolved, result
            FROM markets
            WHERE id=?
        """, (market_id,))
        row = c.fetchone()
        if not row:
            await ctx.send("❌ Mercato non trovato")
            return

        question, yes_pool, no_pool, active, resolved, result = row
        yes_p, no_p = market_probabilities(yes_pool, no_pool)
        stats = get_market_volume_stats(market_id)
        change = calculate_market_change(market_id)
        status = "🟢 Attivo" if active else (f"⚪ Risolto: {result}" if resolved else "⚪ Chiuso")

        embed = discord.Embed(
            title=f"📦 Volume mercato #{market_id}",
            description=question,
            color=COLOR_CYAN
        )
        embed.add_field(name="📉 Stato", value=status, inline=True)
        embed.add_field(name="💧 Liquidità", value=f"{stats['liquidity']} crediti", inline=True)
        embed.add_field(name="📦 Volume totale", value=f"{stats['total_volume']} crediti", inline=True)
        embed.add_field(name="🛒 Volume buy", value=f"{stats['buy_volume']} crediti", inline=True)
        embed.add_field(name="💸 Volume sell", value=f"{stats['sell_volume']} crediti", inline=True)
        embed.add_field(name="🔁 Operazioni", value=str(stats['trades']), inline=True)
        embed.add_field(name="🟢 YES", value=f"{yes_p}%", inline=True)
        embed.add_field(name="🔴 NO", value=f"{no_p}%", inline=True)
        embed.add_field(name="🚀 Movimento YES", value=signed_fmt(change), inline=True)
        embed.set_footer(text="v2.0.2 • Volume, liquidità e movimento del mercato")
        await ctx.send(embed=embed)
        return

    c.execute("""
        SELECT id, question, yes_pool, no_pool,
               COALESCE(total_volume, 0), COALESCE(trade_count, 0), COALESCE(total_pool, 0)
        FROM markets
        ORDER BY COALESCE(total_volume, 0) DESC, id DESC
        LIMIT 10
    """)
    rows = c.fetchall()
    if not rows:
        await ctx.send("📭 Nessun mercato disponibile.")
        return

    lines = []
    for mid, question, yes_pool, no_pool, total_volume, trade_count, liquidity in rows:
        yes_p, no_p = market_probabilities(yes_pool, no_pool)
        short_q = question if len(question) <= 70 else question[:67] + "..."
        lines.append(
            f"**#{mid}** • 📦 **{total_volume}** crediti • 💧 {liquidity} • 🔁 {trade_count}\n"
            f"{short_q}\n🟢 YES {yes_p}% | 🔴 NO {no_p}%"
        )

    embed = discord.Embed(
        title="📦 Mercati per volume",
        description="\n\n".join(lines),
        color=COLOR_CYAN
    )
    embed.set_footer(text="Usa !volume ID per il dettaglio di un mercato")
    await ctx.send(embed=embed)


@bot.command(aliases=["topmover", "movers", "movimenti"])
async def topmovers(ctx):
    """Mostra i mercati con i movimenti più forti del prezzo YES."""
    c.execute("""
        SELECT id, question, yes_pool, no_pool,
               COALESCE(total_volume, 0), COALESCE(trade_count, 0), active, resolved
        FROM markets
        ORDER BY id DESC
        LIMIT 80
    """)
    rows = c.fetchall()

    movers = []
    for mid, question, yes_pool, no_pool, total_volume, trade_count, active, resolved in rows:
        change = calculate_market_change(mid)
        if abs(change) < 0.1 and total_volume <= 0:
            continue
        yes_p, no_p = market_probabilities(yes_pool, no_pool)
        movers.append((abs(change), change, mid, question, yes_p, no_p, total_volume, trade_count, active, resolved))

    movers.sort(reverse=True, key=lambda x: x[0])
    movers = movers[:10]

    if not movers:
        await ctx.send("📭 Non ci sono ancora movimenti sufficienti da mostrare.")
        return

    lines = []
    for _, change, mid, question, yes_p, no_p, total_volume, trade_count, active, resolved in movers:
        arrow = "🚀" if change > 0 else "📉" if change < 0 else "➖"
        status = "🟢" if active else "⚪"
        short_q = question if len(question) <= 72 else question[:69] + "..."
        lines.append(
            f"{status} **#{mid}** {arrow} **{signed_fmt(change)}** • YES **{yes_p}%** / NO **{no_p}%**\n"
            f"{short_q}\n📦 Volume: **{total_volume}** • 🔁 Trade: **{trade_count}**"
        )

    embed = discord.Embed(
        title="🚀 Top Movers",
        description="\n\n".join(lines),
        color=COLOR_ORANGE
    )
    embed.set_footer(text="v2.0.2 • Mercati con maggiore variazione del prezzo YES")
    await ctx.send(embed=embed)


# =========================
# CHART
# =========================
@bot.command(aliases=["grafico"])
async def chart(ctx, market_id: int):
    c.execute("""
        SELECT m.question, m.yes_pool, m.no_pool, m.total_pool, m.active, m.resolved, m.result
        FROM markets m
        WHERE m.id=?
    """, (market_id,))
    market_row = c.fetchone()

    if not market_row:
        await ctx.send("❌ Mercato non trovato")
        return

    question, yes_pool, no_pool, total_pool, active, resolved, result = market_row
    current_yes, current_no = market_probabilities(yes_pool, no_pool)

    c.execute("""
        SELECT timestamp, yes_price
        FROM price_history
        WHERE market_id=?
        ORDER BY id ASC
        LIMIT 80
    """, (market_id,))

    data = c.fetchall()

    if len(data) < 2:
        await ctx.send("❌ Dati insufficienti")
        return

    times = [d[0] for d in data]
    yes_prices = [float(d[1]) for d in data]
    no_prices = [100 - y for y in yes_prices]
    x = list(range(len(yes_prices)))

    opening_yes = yes_prices[0]
    price_change = current_yes - opening_yes
    direction_icon = "📈" if price_change > 0 else "📉" if price_change < 0 else "➖"
    change_color = "#22c55e" if price_change > 0 else "#ef4444" if price_change < 0 else "#e5e7eb"

    def moving_average(arr, window=4):
        if len(arr) < window:
            return arr

        smoothed = []
        for i in range(len(arr)):
            start = max(0, i - window + 1)
            chunk = arr[start:i + 1]
            smoothed.append(sum(chunk) / len(chunk))
        return smoothed

    yes_smooth = moving_average(yes_prices)
    no_smooth = moving_average(no_prices)

    # Curve ondulate: moving average + spline, con fallback lineare se scipy non è disponibile.
    x_plot = np.array(x, dtype=float)
    yes_plot = np.array(yes_smooth, dtype=float)
    no_plot = np.array(no_smooth, dtype=float)

    if make_interp_spline and len(x_plot) >= 4:
        x_curve = np.linspace(x_plot.min(), x_plot.max(), 240)
        spline_k = min(3, len(x_plot) - 1)
        try:
            yes_curve = make_interp_spline(x_plot, yes_plot, k=spline_k)(x_curve)
            no_curve = make_interp_spline(x_plot, no_plot, k=spline_k)(x_curve)
            yes_curve = np.clip(yes_curve, 0, 100)
            no_curve = np.clip(no_curve, 0, 100)
        except Exception:
            x_curve = x_plot
            yes_curve = yes_plot
            no_curve = no_plot
    else:
        x_curve = x_plot
        yes_curve = yes_plot
        no_curve = no_plot

    short_question = question if len(question) <= 90 else question[:87] + "..."
    status_text = "ATTIVO" if active == 1 else f"CHIUSO ({result or 'N/D'})"
    updated_at = datetime.utcnow().strftime("%H:%M UTC")

    fig = plt.figure(figsize=(11, 6), dpi=140)
    fig.patch.set_facecolor("#0b0f19")

    # Background card
    ax_bg = fig.add_axes([0, 0, 1, 1])
    ax_bg.axis("off")
    ax_bg.set_facecolor("#0b0f19")

    ax_bg.text(0.05, 0.91, f"Andamento mercato #{market_id}", fontsize=24, fontweight="bold", fontfamily="Liberation Sans", color="white")
    ax_bg.text(0.05, 0.855, short_question, fontsize=10.5, color="#9ca3af")
    ax_bg.text(0.82, 0.91, status_text, fontsize=11, fontweight="bold", color="#facc15", ha="right")

    # Stat cards
    ax_bg.text(0.055, 0.755, "YES", fontsize=10, color="#9ca3af", fontweight="bold")
    ax_bg.text(0.055, 0.695, f"{current_yes:.1f}%", fontsize=25, color="#22c55e", fontweight="bold")

    ax_bg.text(0.245, 0.755, "NO", fontsize=10, color="#9ca3af", fontweight="bold")
    ax_bg.text(0.245, 0.695, f"{current_no:.1f}%", fontsize=25, color="#ef4444", fontweight="bold")

    ax_bg.text(0.435, 0.755, "POOL", fontsize=10, color="#9ca3af", fontweight="bold")
    ax_bg.text(0.435, 0.695, f"{total_pool}", fontsize=25, color="white", fontweight="bold")

    ax_bg.text(0.625, 0.755, "VAR. APERTURA", fontsize=10, color="#9ca3af", fontweight="bold")
    ax_bg.text(0.625, 0.695, f"{direction_icon} {price_change:+.1f}%", fontsize=25, color=change_color, fontweight="bold")

    # Chart area
    ax = fig.add_axes([0.07, 0.18, 0.86, 0.42])
    ax.set_facecolor("#0b0f19")

    ax.plot(x_curve, yes_curve, linewidth=3.2, color="#22c55e", label="YES")
    ax.plot(x_curve, no_curve, linewidth=3.2, color="#ef4444", label="NO")

    ax.fill_between(x_curve, yes_curve, 0, alpha=0.10, color="#22c55e")
    ax.fill_between(x_curve, no_curve, 0, alpha=0.06, color="#ef4444")
    ax.axhline(50, linestyle="--", linewidth=1, alpha=0.25, color="#9ca3af")

    ax.scatter([x[-1]], [current_yes], color="#22c55e", s=38, zorder=5)
    ax.scatter([x[-1]], [current_no], color="#ef4444", s=38, zorder=5)

    ax.set_ylim(0, 100)
    ax.set_ylabel("Probabilità (%)", color="#9ca3af", fontsize=9)
    ax.grid(True, alpha=0.12)

    step = max(1, len(x) // 6)
    tick_positions = list(range(0, len(x), step))
    ax.set_xticks(tick_positions)
    ax.set_xticklabels([times[i] for i in tick_positions], rotation=25, color="#9ca3af", fontsize=8)

    ax.tick_params(colors="#9ca3af", labelsize=8)

    for spine in ax.spines.values():
        spine.set_color("#1f2937")

    legend = ax.legend(loc="upper left", frameon=True, fontsize=9)
    legend.get_frame().set_facecolor("#111827")
    legend.get_frame().set_edgecolor("#1f2937")

    ax_bg.text(0.05, 0.08, f"Apertura YES: {opening_yes:.1f}% • Grafico aggiornato alle {updated_at}", fontsize=9, color="#6b7280")
    ax_bg.text(0.74, 0.08, "Prediction Market Bot • v1.9.2", fontsize=9, color="#6b7280", ha="right")

    buffer = io.BytesIO()
    plt.savefig(buffer, format="png", facecolor="#0b0f19", bbox_inches="tight", pad_inches=0.15)
    buffer.seek(0)

    await ctx.send(file=discord.File(buffer, "market_dashboard.png"))

    plt.close(fig)



# =========================
# ADMIN MARKET MANAGEMENT
# =========================
@bot.command(aliases=["chiudimercato"])
@admin_only()
async def closemarket(ctx, market_id: int):
    await delete_admin_command_message(ctx)
    """Chiude un mercato senza payout."""
    c.execute("SELECT id, question, active, resolved, match_key FROM markets WHERE id=?", (market_id,))
    row = c.fetchone()

    if not row:
        await ctx.send("❌ Mercato non trovato")
        return

    _, question, active, resolved, match_key = row

    if active == 0:
        await ctx.send("⚠️ Mercato già chiuso")
        return

    c.execute("""
        UPDATE markets
        SET active=0,
            resolved=0,
            result='CLOSED'
        WHERE id=?
    """, (market_id,))
    conn.commit()

    result_channel = await get_discord_channel_safe(RESULTS_CHANNEL_ID)
    embed = discord.Embed(
        title="🔒 Mercato chiuso manualmente",
        description=question,
        color=COLOR_RESOLVED
    )
    embed.add_field(name="🏟️ Partita / Evento", value="Mercato chiuso manualmente", inline=False)
    embed.add_field(name="⚽ Risultato finale", value="N/D", inline=True)
    embed.add_field(name="🏆 Vincitore", value="Nessun vincitore", inline=True)
    embed.add_field(name="🎯 Esito mercato", value="⚪ CHIUSO", inline=True)
    embed.add_field(name="💰 Payout", value=f"Mercato #{market_id} chiuso • Nessun payout distribuito", inline=False)
    embed.set_footer(text="Mercato chiuso manualmente. Grazie per aver giocato!")

    if result_channel:
        await result_channel.send(embed=embed)
        await ctx.send(f"✅ Mercato #{market_id} chiuso e pubblicato nel canale risultati.")
    else:
        await ctx.send("⚠️ Canale risultati non trovato. Pubblico qui il riepilogo.", embed=embed)
        print(f"[RESULTS CHANNEL] Canale {RESULTS_CHANNEL_ID} non trovato.")

    await log_admin_activity(
        ctx,
        "🔒 !closemarket",
        market_id=market_id,
        details=f"Mercato chiuso senza payout • {question}",
        color=COLOR_WHITE
    )


@bot.command(aliases=["annullamercato"])
@admin_only()
async def cancelmarket(ctx, market_id: int):
    await delete_admin_command_message(ctx)
    """Annulla un mercato e rimborsa le posizioni aperte."""
    c.execute("SELECT id, question, active, resolved, match_key FROM markets WHERE id=?", (market_id,))
    row = c.fetchone()

    if not row:
        await ctx.send("❌ Mercato non trovato")
        return

    _, question, active, resolved, match_key = row

    c.execute("""
        SELECT user_id, SUM(amount)
        FROM trades
        WHERE market_id=?
          AND amount > 0
          AND (closed IS NULL OR closed=0)
        GROUP BY user_id
    """, (market_id,))
    refunds = c.fetchall()

    total_refund = 0
    for user_id, amount in refunds:
        amount = int(amount or 0)
        if amount <= 0:
            continue
        total_refund += amount
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
        record_wealth_snapshot(user_id)

    c.execute("""
        UPDATE trades
        SET closed=1
        WHERE market_id=?
          AND amount > 0
          AND (closed IS NULL OR closed=0)
    """, (market_id,))

    c.execute("""
        UPDATE markets
        SET active=0,
            resolved=1,
            result='CANCELLED'
        WHERE id=?
    """, (market_id,))
    conn.commit()

    embed = discord.Embed(
        title="🚫 Mercato annullato",
        description=question,
        color=COLOR_RED
    )
    embed.add_field(name="🆔 Mercato", value=str(market_id), inline=True)
    embed.add_field(name="💸 Rimborsi totali", value=f"{total_refund} crediti", inline=True)
    embed.set_footer(text="Le posizioni aperte sono state chiuse e rimborsate.")
    await ctx.send(embed=embed)
    await log_admin_activity(
        ctx,
        "❌ !cancelmarket",
        market_id=market_id,
        details=f"Mercato annullato e rimborsato • Rimborsi totali: {total_refund} crediti • {question}",
        color=COLOR_WHITE
    )


@bot.command(name="resolve", aliases=["risolvi"])
@admin_only()
async def resolve_market_command(ctx, market_id: int, result: str):
    await delete_admin_command_message(ctx)
    """Risolve manualmente un mercato con YES o NO e distribuisce il payout."""
    result = result.upper()

    if result not in ["YES", "NO"]:
        await ctx.send("❌ Risultato non valido. Usa YES o NO.")
        return

    c.execute("SELECT id, question, active, resolved, match_key FROM markets WHERE id=?", (market_id,))
    row = c.fetchone()

    if not row:
        await ctx.send("❌ Mercato non trovato")
        return

    _, question, active, resolved, match_key = row

    if resolved == 1:
        await ctx.send("⚠️ Mercato già risolto")
        return

    c.execute("""
        UPDATE markets
        SET active=0,
            resolved=1,
            result=?
        WHERE id=?
    """, (result, market_id))
    conn.commit()

    update_streaks_for_market(market_id, result)
    total_paid = payout_market(market_id, result)

    c.execute("SELECT DISTINCT user_id FROM trades WHERE market_id=?", (market_id,))
    for (affected_user_id,) in c.fetchall():
        await evaluate_user_badges(affected_user_id, notify=True)

    outcome_icon = "🟢 YES" if result == "YES" else "🔴 NO"
    partita_text = "Evento speciale / mercato manuale"
    score_text = "Risoluzione manuale"
    winner_text = "N/D"

    if match_key and str(match_key).startswith("MATCH_"):
        try:
            match_api_id = str(match_key).replace("MATCH_", "")
            res = get_match_result(match_api_id)
            if res:
                partita_text = f'{res["home"]} vs {res["away"]}'
                if res["home_goals"] is not None and res["away_goals"] is not None:
                    score_text = f'{res["home_goals"]}-{res["away_goals"]}'
                winner_api = res.get("winner")
                if winner_api == "HOME":
                    winner_text = res["home"]
                elif winner_api == "AWAY":
                    winner_text = res["away"]
                elif winner_api == "DRAW":
                    winner_text = "Pareggio"
        except Exception as e:
            print(f"[RESULTS CHANNEL MANUAL] Errore recupero match: {e}")

    result_embed = discord.Embed(
        title="🏁 Mercato risolto",
        description=question,
        color=COLOR_RESOLVED
    )
    result_embed.add_field(name="🏟️ Partita", value=partita_text, inline=False)
    result_embed.add_field(name="⚽ Risultato finale", value=score_text, inline=True)
    result_embed.add_field(name="🏆 Vincitore", value=winner_text, inline=True)
    result_embed.add_field(name="🎯 Esito mercato", value=outcome_icon, inline=True)
    result_embed.add_field(name="💰 Payout", value=f"Mercato #{market_id} risolto • {total_paid} crediti distribuiti", inline=False)
    result_embed.set_footer(text="Grazie per aver giocato!")

    result_channel = await get_discord_channel_safe(RESULTS_CHANNEL_ID)
    if result_channel:
        await result_channel.send(embed=result_embed)
        await ctx.send(f"✅ Mercato #{market_id} risolto e pubblicato nel canale risultati.")
    else:
        await ctx.send("⚠️ Canale risultati non trovato. Pubblico qui il riepilogo.", embed=result_embed)
        print(f"[RESULTS CHANNEL] Canale {RESULTS_CHANNEL_ID} non trovato.")

    await check_personal_alerts_for_market(market_id, fallback_channel=ctx.channel, only_resolved=True)

    await log_admin_activity(
        ctx,
        "✅ !resolve",
        market_id=market_id,
        details=f"Risoluzione manuale: {result} • Payout: {total_paid} crediti • {question}",
        color=COLOR_WHITE
    )


@bot.command(aliases=["aggiungisaldo"])
@admin_only()
async def addbalance(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        await ctx.send("❌ Importo non valido")
        return

    user_id = str(member.id)
    get_user(user_id)
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    record_wealth_snapshot(user_id)

    await ctx.send(f"✅ Aggiunti **{amount}** crediti a {member.mention}.")
    await log_admin_activity(
        ctx,
        "💰 !addbalance",
        details=f"Aggiunti {amount} crediti a {member.mention} (`{member.id}`)",
        color=COLOR_WHITE
    )


@bot.command(aliases=["rimuovisaldo"])
@admin_only()
async def removebalance(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        await ctx.send("❌ Importo non valido")
        return

    user_id = str(member.id)
    get_user(user_id)
    c.execute("UPDATE users SET balance = MAX(balance - ?, 0) WHERE user_id=?", (amount, user_id))
    conn.commit()
    record_wealth_snapshot(user_id)

    await ctx.send(f"✅ Rimossi fino a **{amount}** crediti da {member.mention}.")
    await log_admin_activity(
        ctx,
        "💸 !removebalance",
        details=f"Rimossi fino a {amount} crediti da {member.mention} (`{member.id}`)",
        color=COLOR_WHITE
    )


@bot.command(aliases=["resetutente"])
@admin_only()
async def resetuser(ctx, member: discord.Member):
    user_id = str(member.id)
    c.execute("INSERT OR REPLACE INTO users (user_id, balance) VALUES (?, ?)", (user_id, 1000))
    c.execute("""
        INSERT OR REPLACE INTO user_stats (user_id, xp, current_streak, best_streak, last_daily)
        VALUES (?, 0, 0, 0, NULL)
    """, (user_id,))
    c.execute("UPDATE trades SET amount=0, closed=1 WHERE user_id=?", (user_id,))
    conn.commit()
    record_wealth_snapshot(user_id)

    await ctx.send(f"🔄 Utente {member.mention} resettato a **1000 crediti**.")
    await log_admin_activity(
        ctx,
        "♻️ !resetuser",
        details=f"Utente resettato a 1000 crediti: {member.mention} (`{member.id}`)",
        color=COLOR_WHITE
    )


# =========================
# PERSONAL ALERT COMMANDS
# =========================
@bot.group(name="alert", invoke_without_command=True)
async def alert_group(ctx, alert_type: str = None, market_id: int = None, side_or_value: str = None, value: str = None):
    user_id = str(ctx.author.id)

    if not alert_type:
        embed = discord.Embed(
            title="🔔 Alert personali",
            description="Crea notifiche personali sui mercati. Le notifiche arrivano in DM; se i DM sono chiusi, il bot prova con mention nel server.",
            color=COLOR_GOLD
        )
        embed.add_field(
            name="Comandi",
            value=(
                "`!alert price ID YES/NO percentuale`\n"
                "`!alert profit ID percentuale`\n"
                "`!alert loss ID percentuale`\n"
                "`!alert closing ID`\n"
                "`!alert resolved ID`\n"
                "`!alerts`\n"
                "`!alert remove ALERT_ID`\n"
                "`!alert clear`"
            ),
            inline=False
        )
        await ctx.send(embed=embed)
        return

    alert_type = alert_type.lower().strip()

    if alert_type not in ["price", "profit", "loss", "closing", "resolved"]:
        await ctx.send("❌ Tipo alert non valido. Usa `price`, `profit`, `loss`, `closing` o `resolved`.")
        return

    if market_id is None:
        await ctx.send("❌ Devi indicare l'ID del mercato.")
        return

    market = get_market_row(market_id)
    if not market:
        await ctx.send("❌ Mercato non trovato.")
        return

    _, question, *_ = market
    side = None
    target_value = None

    if alert_type == "price":
        if not side_or_value:
            await ctx.send("❌ Esempio corretto: `!alert price 3 YES 65`")
            return
        side = side_or_value.upper()
        if side not in ["YES", "NO"]:
            await ctx.send("❌ Side non valido. Usa YES o NO.")
            return
        target_value = parse_percent(value)
        if target_value is None:
            await ctx.send("❌ Percentuale non valida. Esempio: `!alert price 3 YES 65`")
            return

    elif alert_type in ["profit", "loss"]:
        target_value = parse_percent(side_or_value)
        if target_value is None:
            await ctx.send(f"❌ Percentuale non valida. Esempio: `!alert {alert_type} 3 20`")
            return

    elif alert_type in ["closing", "resolved"]:
        target_value = 0

    c.execute("""
        INSERT INTO personal_alerts (user_id, market_id, alert_type, side, target_value, active, triggered, created_at)
        VALUES (?, ?, ?, ?, ?, 1, 0, ?)
    """, (user_id, market_id, alert_type, side, target_value, datetime.now(timezone.utc).isoformat()))
    conn.commit()

    alert_id = c.lastrowid

    embed = discord.Embed(
        title="✅ Alert creato",
        description=question,
        color=COLOR_GREEN
    )
    embed.add_field(name="🆔 Alert", value=f"#{alert_id}", inline=True)
    embed.add_field(name="🆔 Mercato", value=f"#{market_id}", inline=True)
    embed.add_field(name="Tipo", value=alert_type, inline=True)

    if alert_type == "price":
        embed.add_field(name="Soglia", value=f"{side} ≥ {target_value:.1f}%", inline=False)
    elif alert_type == "profit":
        embed.add_field(name="Soglia", value=f"Profitto ≥ {target_value:.1f}%", inline=False)
    elif alert_type == "loss":
        embed.add_field(name="Soglia", value=f"Perdita ≤ -{target_value:.1f}%", inline=False)
    elif alert_type == "closing":
        embed.add_field(name="Soglia", value="10 minuti prima dell'inizio della partita collegata.", inline=False)
    else:
        embed.add_field(name="Soglia", value="Quando il mercato viene risolto.", inline=False)

    await ctx.send(embed=embed)


@alert_group.command(name="remove", aliases=["delete", "rimuovi"])
async def alert_remove(ctx, alert_id: int):
    user_id = str(ctx.author.id)
    c.execute("""
        UPDATE personal_alerts
        SET active=0,
            triggered=1,
            triggered_at=?
        WHERE id=?
          AND user_id=?
          AND active=1
    """, (datetime.now(timezone.utc).isoformat(), alert_id, user_id))
    conn.commit()

    if c.rowcount <= 0:
        await ctx.send("❌ Alert non trovato o già disattivato.")
        return

    await ctx.send(f"🗑️ Alert #{alert_id} rimosso.")


@alert_group.command(name="clear", aliases=["pulisci"])
async def alert_clear(ctx):
    user_id = str(ctx.author.id)
    c.execute("""
        UPDATE personal_alerts
        SET active=0,
            triggered=1,
            triggered_at=?
        WHERE user_id=?
          AND active=1
    """, (datetime.now(timezone.utc).isoformat(), user_id))
    removed = c.rowcount
    conn.commit()

    await ctx.send(f"🧹 Alert attivi rimossi: **{removed}**.")


@bot.command(name="alerts", aliases=["mieialert"])
async def alerts_list(ctx):
    user_id = str(ctx.author.id)
    c.execute("""
        SELECT a.id, a.market_id, a.alert_type, a.side, a.target_value, m.question
        FROM personal_alerts a
        JOIN markets m ON a.market_id=m.id
        WHERE a.user_id=?
          AND a.active=1
          AND a.triggered=0
        ORDER BY a.id DESC
        LIMIT 15
    """, (user_id,))
    rows = c.fetchall()

    if not rows:
        await ctx.send("📭 Non hai alert personali attivi.")
        return

    embed = discord.Embed(
        title="🔔 I tuoi alert attivi",
        color=COLOR_GOLD
    )

    for alert_id, market_id, alert_type, side, target_value, question in rows:
        if alert_type == "price":
            rule = f"{side} ≥ {target_value:.1f}%"
        elif alert_type == "profit":
            rule = f"Profitto ≥ {target_value:.1f}%"
        elif alert_type == "loss":
            rule = f"Perdita ≤ -{target_value:.1f}%"
        elif alert_type == "closing":
            rule = "10 minuti prima dell'inizio"
        else:
            rule = "mercato risolto"

        embed.add_field(
            name=f"#{alert_id} • Mercato #{market_id} • {alert_type}",
            value=f"{question[:120]}\n**Regola:** {rule}",
            inline=False
        )

    embed.set_footer(text="Rimuovi con !alert remove ALERT_ID")
    await ctx.send(embed=embed)



# =========================
# MARKETPLACE SYSTEM
# =========================
SHOP_CATEGORIES = {
    "themes": {
        "emoji": "🎨",
        "name": "Embed Themes",
        "desc": "Temi che cambiano colore e stile degli embed personali: !profile, !portfolio, !balance e leaderboard."
    },
    "titles": {
        "emoji": "🎖️",
        "name": "Titles",
        "desc": "Etichette cosmetiche acquistabili, separate dallo Status di gioco. Appaiono sotto il nome nel profilo."
    },
    "flairs": {
        "emoji": "💬",
        "name": "Flairs",
        "desc": "Motti e frasi personali acquistabili. Appaiono sotto il Title nel profilo."
    },
    "collectibles": {
        "emoji": "🏺",
        "name": "Collectibles",
        "desc": "Pezzi da collezione acquistabili, separati dai badge vinti e visibili negli embed."
    },
    "decorative": {
        "emoji": "🖼️",
        "name": "Decorative Images",
        "desc": "Elementi decorativi cosmetici per arricchire gli embed personali, senza vantaggi gameplay."
    },
    "crates": {
        "emoji": "📦",
        "name": "Crates",
        "desc": "Casse cosmetiche da inventario. Nessun effetto gameplay."
    },
}

SHOP_CATEGORY_ALIASES = {
    "theme": "themes", "themes": "themes", "temi": "themes", "tema": "themes", "embedthemes": "themes",
    "title": "titles", "titles": "titles", "titoli": "titles", "titolo": "titles",
    "flair": "flairs", "flairs": "flairs", "motti": "flairs", "motto": "flairs",
    "collectible": "collectibles", "collectibles": "collectibles", "collezionabili": "collectibles", "collezione": "collectibles",
    "decorative": "decorative", "decorative_images": "decorative", "images": "decorative", "immagini": "decorative", "decorazioni": "decorative",
    "crate": "crates", "crates": "crates", "casse": "crates", "cassa": "crates",
}

SHOP_ITEMS = {
    # EMBED THEMES
    "theme_dark_exchange": {
        "emoji": "🌑", "name": "Dark Exchange", "category": "themes", "slot": "theme",
        "price": 1500, "rarity": "Non comune", "new": True, "limited": False,
        "desc": "Tema scuro da piattaforma trading. Cambia il colore degli embed personali.",
        "color": COLOR_PURPLE,
    },
    "theme_stadium": {
        "emoji": "🏟️", "name": "Stadium Lights", "category": "themes", "slot": "theme",
        "price": 1800, "rarity": "Non comune", "new": False, "limited": False,
        "desc": "Tema ispirato alle luci dello stadio. Visibile su profilo, portafoglio, saldo e classifica.",
        "color": COLOR_CYAN,
    },
    "theme_profit_green": {
        "emoji": "🟢", "name": "Profit Green", "category": "themes", "slot": "theme",
        "price": 750, "rarity": "Comune", "new": True, "limited": False,
        "desc": "Tema verde essenziale per embed personali in stile profitto positivo.",
        "color": COLOR_GREEN,
    },
    "theme_gold_market": {
        "emoji": "🟡", "name": "Gold Market", "category": "themes", "slot": "theme",
        "price": 2500, "rarity": "Rara", "new": False, "limited": False,
        "desc": "Tema dorato premium per trader in evidenza.",
        "color": COLOR_GOLD,
    },

    # TITLES
    "title_sharp_trader": {
        "emoji": "🎯", "name": "Sharp Trader", "category": "titles", "slot": "title",
        "price": 1200, "rarity": "Comune", "new": False, "limited": False,
        "desc": "Title cosmetico mostrato sotto il nome nel profilo. Non modifica lo Status di gioco."
    },
    "title_market_maker": {
        "emoji": "📈", "name": "Market Maker", "category": "titles", "slot": "title",
        "price": 3000, "rarity": "Rara", "new": False, "limited": False,
        "desc": "Title premium per chi domina i mercati. Solo estetico."
    },
    "title_value_hunter": {
        "emoji": "🧭", "name": "Value Hunter", "category": "titles", "slot": "title",
        "price": 2200, "rarity": "Non comune", "new": True, "limited": False,
        "desc": "Title per chi cerca valore prima della massa."
    },

    # FLAIRS
    "flair_buy_the_dip": {
        "emoji": "💬", "name": "Buy the Dip", "category": "flairs", "slot": "flair",
        "price": 900, "rarity": "Comune", "new": True, "limited": False,
        "desc": "Flair personale mostrato sotto il Title nel profilo."
    },
    "flair_risk_manager": {
        "emoji": "💬", "name": "Gestisco il rischio, non la fortuna", "category": "flairs", "slot": "flair",
        "price": 1400, "rarity": "Non comune", "new": False, "limited": False,
        "desc": "Motto cosmetico per profilo e identità trader."
    },
    "flair_mercato_parla": {
        "emoji": "💬", "name": "Il mercato parla", "category": "flairs", "slot": "flair",
        "price": 1100, "rarity": "Comune", "new": False, "limited": False,
        "desc": "Frase breve da mostrare nel profilo."
    },

    # COLLECTIBLES
    "collectible_founder": {
        "emoji": "🏛️", "name": "Founder Relic", "category": "collectibles", "slot": "collectible",
        "price": 5000, "rarity": "Limitata", "new": False, "limited": True,
        "desc": "Collezionabile limitato per i primi sostenitori. Separato dai badge vinti."
    },
    "collectible_bull": {
        "emoji": "🐂", "name": "Bull Token", "category": "collectibles", "slot": "collectible",
        "price": 2600, "rarity": "Rara", "new": True, "limited": False,
        "desc": "Pezzo da collezione visibile negli embed personali."
    },
    "collectible_bear": {
        "emoji": "🐻", "name": "Bear Token", "category": "collectibles", "slot": "collectible",
        "price": 2600, "rarity": "Rara", "new": True, "limited": False,
        "desc": "Collezionabile per trader prudenti e contrarian."
    },

    # DECORATIVE IMAGES / DECORATIONS
    "decor_night_trader": {
        "emoji": "🌌", "name": "Night Trader Decoration", "category": "decorative", "slot": "decorative",
        "price": 3500, "rarity": "Epica", "new": True, "limited": False,
        "desc": "Elemento decorativo testuale per gli embed personali."
    },
    "decor_stadium_banner": {
        "emoji": "🏟️", "name": "Stadium Banner", "category": "decorative", "slot": "decorative",
        "price": 2100, "rarity": "Non comune", "new": False, "limited": False,
        "desc": "Banner decorativo per dare agli embed un taglio più sportivo."
    },

    # CRATES
    "crate_basic": {
        "emoji": "📦", "name": "Cassa Base", "category": "crates", "slot": None,
        "price": 1000, "rarity": "Comune", "new": True, "limited": False,
        "desc": "Cassa cosmetica da inventario. Apertura premi da sviluppare in una fase successiva."
    },
    "crate_premium": {
        "emoji": "🎁", "name": "Cassa Premium", "category": "crates", "slot": None,
        "price": 3000, "rarity": "Rara", "new": True, "limited": False,
        "desc": "Cassa cosmetica premium da inventario. Nessun vantaggio competitivo."
    },

    # Legacy IDs mantenuti per non rompere inventari già esistenti.
    "frame_green": {
        "emoji": "🟢", "name": "Profit Green Legacy", "category": "themes", "slot": "theme",
        "price": 750, "rarity": "Comune", "new": False, "limited": False,
        "desc": "Versione legacy convertita in Embed Theme.",
        "color": COLOR_GREEN,
    },
    "frame_gold": {
        "emoji": "🟡", "name": "Gold Market Legacy", "category": "themes", "slot": "theme",
        "price": 2500, "rarity": "Rara", "new": False, "limited": False,
        "desc": "Versione legacy convertita in Embed Theme.",
        "color": COLOR_GOLD,
    },
    "badge_founder": {
        "emoji": "🏛️", "name": "Founder Relic Legacy", "category": "collectibles", "slot": "collectible",
        "price": 5000, "rarity": "Limitata", "new": False, "limited": True,
        "desc": "Vecchio badge vetrina convertito in Collectible acquistato."
    },
    "case_basic": {
        "emoji": "📦", "name": "Cassa Base Legacy", "category": "crates", "slot": None,
        "price": 1000, "rarity": "Comune", "new": False, "limited": False,
        "desc": "Vecchia cassa base mantenuta per compatibilità inventario."
    },
    "bundle_night_trader": {
        "emoji": "🌌", "name": "Night Trader Legacy", "category": "decorative", "slot": "decorative",
        "price": 6500, "rarity": "Epica", "new": False, "limited": False,
        "desc": "Vecchio bundle convertito in Decorative Image/Decoration."
    },
}

EQUIPMENT_SLOTS = {
    "theme": "Embed Theme",
    "title": "Title",
    "flair": "Flair",
    "collectible": "Collectible",
    "decorative": "Decorative Image",
    # Slot legacy accettati solo per sicurezza, ma non più proposti nello shop.
    "frame": "Embed Theme legacy",
    "showcase": "Collectible legacy",
    "bundle": "Decorative legacy",
}


def normalize_shop_category(category):
    if not category:
        return None
    return SHOP_CATEGORY_ALIASES.get(str(category).lower().strip(), str(category).lower().strip())


def get_shop_item(item_id):
    return SHOP_ITEMS.get(str(item_id).lower().strip())


def user_owns_item(user_id, item_id):
    c.execute("SELECT quantity FROM user_inventory WHERE user_id=? AND item_id=?", (str(user_id), str(item_id)))
    row = c.fetchone()
    return bool(row and (row[0] or 0) > 0)


def get_equipped_items(user_id):
    c.execute("SELECT slot, item_id FROM user_equipment WHERE user_id=?", (str(user_id),))
    equipped = {slot: item_id for slot, item_id in c.fetchall()}

    # Normalizzazione legacy: se qualcuno ha ancora vecchi slot equipaggiati, li leggiamo come nuovi slot.
    if "theme" not in equipped and "frame" in equipped:
        equipped["theme"] = equipped["frame"]
    if "collectible" not in equipped and "showcase" in equipped:
        equipped["collectible"] = equipped["showcase"]
    if "decorative" not in equipped and "bundle" in equipped:
        equipped["decorative"] = equipped["bundle"]

    return equipped


def get_equipped_item(user_id, slot):
    item_id = get_equipped_items(user_id).get(slot)
    if not item_id:
        return None
    return SHOP_ITEMS.get(item_id)


def get_equipped_items_text(user_id):
    equipped = get_equipped_items(user_id)
    lines = []
    for slot in ["theme", "title", "flair", "collectible", "decorative"]:
        item_id = equipped.get(slot)
        item = SHOP_ITEMS.get(item_id) if item_id else None
        if item:
            lines.append(f"**{EQUIPMENT_SLOTS.get(slot, slot)}:** {item['emoji']} {item['name']}")
    return "\n".join(lines) if lines else "Nessun cosmetico equipaggiato."


def get_purchased_collectibles_text(user_id, equipped_only=False):
    if equipped_only:
        item = get_equipped_item(user_id, "collectible")
        return f"{item['emoji']} **{item['name']}**" if item else "Nessun collezionabile equipaggiato."

    c.execute("""
        SELECT item_id, quantity
        FROM user_inventory
        WHERE user_id=?
        ORDER BY purchased_at DESC
    """, (str(user_id),))
    rows = c.fetchall()
    lines = []
    for item_id, quantity in rows:
        item = SHOP_ITEMS.get(item_id)
        if item and item.get("category") == "collectibles":
            qty = f" x{quantity}" if quantity and quantity > 1 else ""
            lines.append(f"{item['emoji']} **{item['name']}**{qty}")
    return " • ".join(lines[:8]) if lines else "Nessun collezionabile acquistato."


def get_profile_identity_lines(user_id):
    title = get_equipped_item(user_id, "title")
    flair = get_equipped_item(user_id, "flair")
    lines = []
    if title:
        lines.append(f"🎖️ **{title['name']}**")
    if flair:
        lines.append(f"💬 _{flair['name']}_")
    return "\n".join(lines)


def get_status_emoji_from_level(trader_level):
    text = str(trader_level or "").strip()
    return text.split()[0] if text else "👤"


def get_cosmetic_style(user_id):
    """Trasforma gli oggetti equipaggiati in effetti grafici reali sugli embed."""
    equipped = get_equipped_items(user_id)
    style = {
        "color": None,
        "title_prefix": "",
        "description_prefix": "",
        "footer_suffix": "",
        "author_suffix": "",
        "collectible": "",
        "decorative": "",
    }

    theme_id = equipped.get("theme")
    title_id = equipped.get("title")
    flair_id = equipped.get("flair")
    collectible_id = equipped.get("collectible")
    decorative_id = equipped.get("decorative")

    theme_item = SHOP_ITEMS.get(theme_id) if theme_id else None
    if theme_item:
        style["color"] = theme_item.get("color") or COLOR_PURPLE
        style["footer_suffix"] += f" • Theme: {theme_item['name']}"

    # Compatibilità per vecchi temi hardcoded.
    if theme_id == "theme_dark_exchange":
        style["description_prefix"] += "🌑 **Tema Dark Exchange attivo**\n"
    elif theme_id == "theme_stadium":
        style["description_prefix"] += "🏟️ **Tema Stadium Lights attivo**\n"

    title_item = SHOP_ITEMS.get(title_id) if title_id else None
    if title_item:
        style["author_suffix"] = f" • {title_item['name']}"

    flair_item = SHOP_ITEMS.get(flair_id) if flair_id else None
    if flair_item:
        style["footer_suffix"] += f" • Flair: {flair_item['name']}"

    collectible_item = SHOP_ITEMS.get(collectible_id) if collectible_id else None
    if collectible_item:
        style["collectible"] = f"{collectible_item['emoji']} **{collectible_item['name']}**"

    decorative_item = SHOP_ITEMS.get(decorative_id) if decorative_id else None
    if decorative_item:
        style["decorative"] = f"{decorative_item['emoji']} **{decorative_item['name']}**"
        style["footer_suffix"] += f" • Decorazione: {decorative_item['name']}"

    return style


def apply_cosmetics_to_embed(embed, user_id, member=None, base_footer=None, show_collectible=True, show_decorative=True):
    """Applica tema, title/flair e collezionabili agli embed personali."""
    style = get_cosmetic_style(user_id)

    if style["color"] is not None:
        embed.color = discord.Color(style["color"])

    if style["title_prefix"] and embed.title:
        embed.title = f"{style['title_prefix']}{embed.title}"

    if style["description_prefix"]:
        embed.description = f"{style['description_prefix']}{embed.description or ''}"

    if member is not None and style["author_suffix"]:
        try:
            embed.set_author(name=f"{member.display_name}{style['author_suffix']}", icon_url=member.display_avatar.url)
        except Exception:
            pass

    if show_collectible and style["collectible"]:
        embed.add_field(name="🏺 Collectible equipaggiato", value=style["collectible"][:1024], inline=False)

    if show_decorative and style["decorative"]:
        embed.add_field(name="🖼️ Decorazione equipaggiata", value=style["decorative"][:1024], inline=False)

    footer = base_footer or ""
    if style["footer_suffix"]:
        footer = f"{footer}{style['footer_suffix']}" if footer else style["footer_suffix"].lstrip(" •")
    if footer:
        embed.set_footer(text=footer[:2048])

    return embed


def build_shop_item_line(item_id, item):
    slot = EQUIPMENT_SLOTS.get(item.get("slot"), "Inventario") if item.get("slot") else "Inventario"
    tags = []
    if item.get("new"):
        tags.append("🆕 Novità")
    if item.get("limited"):
        tags.append("⭐ Limitato")
    tag_text = f" • {' • '.join(tags)}" if tags else ""
    return (
        f"`{item_id}` — {item['emoji']} **{item['name']}**\n"
        f"💰 {item['price']} crediti • 🏷️ {item['rarity']} • 🎛️ {slot}{tag_text}\n"
        f"_{item['desc']}_"
    )


@bot.command(name="shop", aliases=["marketplace", "negozio"])
async def shop(ctx, category: str = None):
    if not category:
        embed = discord.Embed(
            title="🛒 Marketplace",
            description="Spendi i crediti solo in oggetti cosmetici. Nessun oggetto dà vantaggi nel trading.",
            color=COLOR_PURPLE
        )
        for key, data in SHOP_CATEGORIES.items():
            count = sum(1 for item in SHOP_ITEMS.values() if item.get("category") == key)
            embed.add_field(
                name=f"{data['emoji']} {data['name']}",
                value=f"{data['desc']}\n`!shop {key}` • {count} oggetti",
                inline=False
            )
        embed.set_footer(text="Comandi: !buyitem item_id • !inventory • !equip item_id • !unequip slot")
        await ctx.send(embed=embed)
        return

    category = normalize_shop_category(category)
    if category not in SHOP_CATEGORIES:
        await ctx.send("❌ Categoria non valida. Usa `!shop` per vedere le 6 categorie disponibili.")
        return

    items = [(item_id, item) for item_id, item in SHOP_ITEMS.items() if item.get("category") == category]
    data = SHOP_CATEGORIES[category]
    embed = discord.Embed(
        title=f"{data['emoji']} {data['name']}",
        description=data["desc"],
        color=COLOR_PURPLE
    )

    if not items:
        embed.add_field(name="📭 Nessun oggetto", value="Questa categoria è vuota.", inline=False)
    else:
        for item_id, item in items[:12]:
            embed.add_field(name=f"{item['emoji']} {item['name']}", value=build_shop_item_line(item_id, item), inline=False)

    embed.set_footer(text="Acquista con !buyitem item_id")
    await ctx.send(embed=embed)


@bot.command(name="buyitem", aliases=["compraitem", "buycosmetic"])
async def buyitem(ctx, item_id: str = None):
    user_id = str(ctx.author.id)
    if not item_id:
        await ctx.send("❌ Devi indicare l'ID oggetto. Esempio: `!buyitem theme_dark_exchange`")
        return

    item_id = item_id.lower().strip()
    item = get_shop_item(item_id)
    if not item:
        await ctx.send("❌ Oggetto non trovato. Usa `!shop` per vedere il Marketplace.")
        return

    if user_owns_item(user_id, item_id):
        await ctx.send("❌ Possiedi già questo oggetto.")
        return

    balance = get_user(user_id)
    price = int(item["price"])
    if balance < price:
        await ctx.send(f"❌ Crediti insufficienti. Prezzo: **{price}**, saldo: **{balance}**.")
        return

    now = datetime.now(timezone.utc).isoformat()
    c.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (price, user_id))
    c.execute("""
        INSERT INTO user_inventory (user_id, item_id, quantity, purchased_at)
        VALUES (?, ?, 1, ?)
    """, (user_id, item_id, now))
    c.execute("""
        INSERT INTO marketplace_purchases (user_id, item_id, price, purchased_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, item_id, price, now))
    conn.commit()
    record_wealth_snapshot(user_id)

    embed = discord.Embed(
        title="✅ Acquisto completato",
        description=f"Hai acquistato {item['emoji']} **{item['name']}**.",
        color=COLOR_GREEN
    )
    embed.add_field(name="Categoria", value=SHOP_CATEGORIES[item['category']]["name"], inline=True)
    embed.add_field(name="💰 Prezzo", value=f"{price} crediti", inline=True)
    embed.add_field(name="💳 Saldo residuo", value=str(get_user(user_id)), inline=True)
    if item.get("slot"):
        embed.add_field(name="🎛️ Equipaggia", value=f"`!equip {item_id}`", inline=False)
    else:
        embed.add_field(name="📦 Inventario", value="Questo oggetto resta in inventario e non si equipaggia direttamente.", inline=False)
    embed.set_footer(text="Gli oggetti Marketplace sono solo cosmetici: nessun vantaggio competitivo.")
    await ctx.send(embed=embed)


@bot.command(name="inventory", aliases=["inventario", "items"])
async def inventory(ctx, member: discord.Member = None):
    member = member or ctx.author
    user_id = str(member.id)
    c.execute("""
        SELECT item_id, quantity, purchased_at
        FROM user_inventory
        WHERE user_id=?
        ORDER BY purchased_at DESC
    """, (user_id,))
    rows = c.fetchall()

    embed = discord.Embed(
        title=f"🎒 Inventario di {member.display_name}",
        color=COLOR_BLUE
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="🎛️ Equipaggiati", value=get_equipped_items_text(user_id), inline=False)

    if not rows:
        embed.add_field(name="📭 Vuoto", value="Nessun oggetto acquistato. Usa `!shop` per aprire il Marketplace.", inline=False)
    else:
        grouped = {key: [] for key in SHOP_CATEGORIES.keys()}
        for item_id, quantity, _ in rows:
            item = SHOP_ITEMS.get(item_id)
            if not item:
                continue
            qty_text = f" x{quantity}" if quantity and quantity > 1 else ""
            slot = EQUIPMENT_SLOTS.get(item.get("slot"), "Inventario") if item.get("slot") else "Inventario"
            grouped.setdefault(item.get("category", "collectibles"), []).append(f"`{item_id}` — {item['emoji']} **{item['name']}**{qty_text} • {slot}")

        for category, lines in grouped.items():
            if not lines:
                continue
            data = SHOP_CATEGORIES.get(category, {"emoji": "📦", "name": category})
            embed.add_field(name=f"{data['emoji']} {data['name']}", value="\n".join(lines[:8])[:1024], inline=False)

    embed.set_footer(text="Equipaggia con !equip item_id • Rimuovi con !unequip slot")
    await ctx.send(embed=embed)


@bot.command(name="equip", aliases=["equipaggia"])
async def equip(ctx, item_id: str = None):
    user_id = str(ctx.author.id)
    if not item_id:
        await ctx.send("❌ Devi indicare l'ID oggetto. Esempio: `!equip theme_dark_exchange`")
        return

    item_id = item_id.lower().strip()
    item = get_shop_item(item_id)
    if not item:
        await ctx.send("❌ Oggetto non trovato.")
        return

    if not user_owns_item(user_id, item_id):
        await ctx.send("❌ Non possiedi questo oggetto. Acquistalo prima con `!buyitem item_id`.")
        return

    slot = item.get("slot")
    if not slot:
        await ctx.send("❌ Questo oggetto è solo da inventario e non può essere equipaggiato.")
        return

    now = datetime.now(timezone.utc).isoformat()
    c.execute("""
        INSERT OR REPLACE INTO user_equipment (user_id, slot, item_id, equipped_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, slot, item_id, now))
    conn.commit()

    await ctx.send(f"✅ Hai equipaggiato {item['emoji']} **{item['name']}** nello slot **{EQUIPMENT_SLOTS.get(slot, slot)}**.")


@bot.command(name="unequip", aliases=["rimuoviitem"])
async def unequip(ctx, slot: str = None):
    user_id = str(ctx.author.id)
    if not slot:
        await ctx.send("❌ Devi indicare lo slot. Slot disponibili: `theme`, `title`, `flair`, `collectible`, `decorative`.")
        return

    slot = slot.lower().strip()
    legacy_slot_map = {"frame": "theme", "showcase": "collectible", "bundle": "decorative"}
    slot = legacy_slot_map.get(slot, slot)
    if slot not in EQUIPMENT_SLOTS:
        await ctx.send("❌ Slot non valido. Slot disponibili: `theme`, `title`, `flair`, `collectible`, `decorative`.")
        return

    c.execute("DELETE FROM user_equipment WHERE user_id=? AND slot=?", (user_id, slot))
    removed = c.rowcount
    # Pulizia eventuale vecchio slot collegato.
    for legacy, normalized in {"frame": "theme", "showcase": "collectible", "bundle": "decorative"}.items():
        if normalized == slot:
            c.execute("DELETE FROM user_equipment WHERE user_id=? AND slot=?", (user_id, legacy))
            removed += c.rowcount
    conn.commit()

    if removed <= 0:
        await ctx.send("📭 Non avevi nulla equipaggiato in questo slot.")
        return

    await ctx.send(f"✅ Slot **{EQUIPMENT_SLOTS[slot]}** svuotato.")


@bot.command(name="adminshop", aliases=["shopadmin"])
@admin_only()
async def adminshop(ctx, action: str = "overview", target: str = None):
    """Comando admin unico e centralizzato per controllare il Marketplace."""
    action = (action or "overview").lower().strip()

    if action in ["overview", "status", "categorie", "categories"]:
        embed = discord.Embed(
            title="👑 Admin Shop",
            description="Pannello unico Marketplace. Gli oggetti sono hardcoded nel file; questo comando centralizza verifica e diagnostica.",
            color=COLOR_WHITE
        )
        for key, data in SHOP_CATEGORIES.items():
            count = sum(1 for item in SHOP_ITEMS.values() if item.get("category") == key)
            embed.add_field(name=f"{data['emoji']} {data['name']}", value=f"{count} oggetti • `!shop {key}`", inline=False)
        embed.set_footer(text="Azioni: !adminshop overview • !adminshop item item_id • !adminshop user @utente")
        await ctx.send(embed=embed)
        return

    if action == "item":
        if not target:
            await ctx.send("❌ Usa `!adminshop item item_id`.")
            return
        item = get_shop_item(target)
        if not item:
            await ctx.send("❌ Oggetto non trovato.")
            return
        embed = discord.Embed(title=f"👑 Item admin: {item['name']}", color=COLOR_WHITE)
        embed.add_field(name="ID", value=f"`{target}`", inline=True)
        embed.add_field(name="Categoria", value=SHOP_CATEGORIES[item['category']]["name"], inline=True)
        embed.add_field(name="Slot", value=EQUIPMENT_SLOTS.get(item.get("slot"), "Inventario") if item.get("slot") else "Inventario", inline=True)
        embed.add_field(name="Prezzo", value=str(item["price"]), inline=True)
        embed.add_field(name="Rarità", value=item["rarity"], inline=True)
        embed.add_field(name="Descrizione", value=item["desc"], inline=False)
        await ctx.send(embed=embed)
        return

    if action == "user":
        if not ctx.message.mentions:
            await ctx.send("❌ Usa `!adminshop user @utente`.")
            return
        member = ctx.message.mentions[0]
        embed = discord.Embed(title=f"👑 Shop user: {member.display_name}", color=COLOR_WHITE)
        embed.add_field(name="Equipaggiati", value=get_equipped_items_text(str(member.id)), inline=False)
        embed.add_field(name="Collezionabili acquistati", value=get_purchased_collectibles_text(str(member.id)), inline=False)
        await ctx.send(embed=embed)
        return

    await ctx.send("❌ Azione non valida. Usa `!adminshop overview`, `!adminshop item item_id`, `!adminshop user @utente`.")

# =========================
# SEASON SYSTEM
# =========================
def ensure_active_season():
    now = datetime.now(timezone.utc).isoformat()
    c.execute("SELECT season_number FROM seasons WHERE active=1 ORDER BY season_number DESC LIMIT 1")
    row = c.fetchone()
    if row:
        return int(row[0])

    c.execute("SELECT MAX(season_number) FROM seasons")
    last = c.fetchone()[0] or 0
    season_number = int(last) + 1
    c.execute(
        "INSERT INTO seasons (season_number, name, started_at, ended_at, active) VALUES (?, ?, ?, NULL, 1)",
        (season_number, f"Stagione {season_number}", now)
    )
    conn.commit()
    return season_number


def build_current_ranking(limit=3):
    c.execute("SELECT user_id, balance FROM users")
    users = c.fetchall()
    ranking = []
    for user_id, balance in users:
        _, open_value, _, _ = calculate_user_open_value(user_id)
        ranking.append((user_id, float(balance or 0), float(open_value or 0), float((balance or 0) + (open_value or 0))))
    ranking.sort(key=lambda x: x[3], reverse=True)
    return ranking[:limit]


def get_best_accuracy_user():
    c.execute("SELECT DISTINCT user_id FROM trades")
    candidates = [r[0] for r in c.fetchall()]
    best_user = None
    best_acc = 0.0
    for user_id in candidates:
        metrics = get_user_metrics(user_id)
        if metrics["resolved_markets"] >= 1 and metrics["accuracy"] >= best_acc:
            best_user = user_id
            best_acc = float(metrics["accuracy"] or 0)
    return best_user, best_acc


def archive_current_season():
    season_number = ensure_active_season()
    now = datetime.now(timezone.utc).isoformat()
    top3 = build_current_ranking(3)
    champion_user_id = top3[0][0] if top3 else None
    champion_net_worth = top3[0][3] if top3 else 0
    top3_text = "\n".join(
        f"#{idx} <@{uid}> — {net:.0f} crediti"
        for idx, (uid, _bal, _open, net) in enumerate(top3, start=1)
    ) or "Nessun partecipante"

    best_accuracy_user_id, best_accuracy = get_best_accuracy_user()

    c.execute("SELECT user_id, COUNT(*) FROM trades GROUP BY user_id ORDER BY COUNT(*) DESC LIMIT 1")
    row = c.fetchone()
    most_trades_user_id = row[0] if row else None
    most_trades = int(row[1]) if row else 0

    c.execute("SELECT COUNT(*) FROM markets")
    total_markets = int(c.fetchone()[0] or 0)
    c.execute("SELECT COUNT(*) FROM trades")
    total_trades = int(c.fetchone()[0] or 0)

    c.execute("UPDATE seasons SET ended_at=?, active=0 WHERE season_number=?", (now, season_number))
    c.execute("""
        INSERT INTO season_archives (
            season_number, archived_at, champion_user_id, champion_net_worth, top3_text,
            best_accuracy_user_id, best_accuracy, most_trades_user_id, most_trades, total_markets, total_trades
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        season_number, now, champion_user_id, champion_net_worth, top3_text,
        best_accuracy_user_id, best_accuracy, most_trades_user_id, most_trades, total_markets, total_trades
    ))
    new_season = season_number + 1
    c.execute(
        "INSERT INTO seasons (season_number, name, started_at, ended_at, active) VALUES (?, ?, ?, NULL, 1)",
        (new_season, f"Stagione {new_season}", now)
    )
    conn.commit()
    return season_number, new_season, top3_text, champion_user_id


def reset_seasonal_data(starting_balance=1000):
    """Resetta solo la progressione stagionale. Marketplace e cosmetici restano intatti."""
    c.execute("UPDATE users SET balance=?", (int(starting_balance),))
    c.execute("DELETE FROM trades")
    c.execute("DELETE FROM markets")
    c.execute("DELETE FROM price_history")
    c.execute("DELETE FROM wealth_history")
    c.execute("DELETE FROM personal_alerts")
    c.execute("DELETE FROM user_badges")
    c.execute("UPDATE user_stats SET xp=0, current_streak=0, best_streak=0, last_daily=NULL")
    conn.commit()


@bot.command(name="seasonreset")
@admin_only()
async def seasonreset(ctx, starting_balance: int = 1000):
    await delete_admin_command_message(ctx)
    if starting_balance < 0:
        await ctx.send("❌ Il saldo iniziale non può essere negativo.")
        return

    closed_season, new_season, top3_text, champion_user_id = archive_current_season()
    reset_seasonal_data(starting_balance)

    embed = discord.Embed(
        title="🔄 Reset stagione completato",
        description=(
            f"La **Stagione {closed_season}** è stata archiviata.\n"
            f"È iniziata la **Stagione {new_season}**.\n\n"
            "Gli acquisti Marketplace, inventario e cosmetici equipaggiati sono stati conservati."
        ),
        color=COLOR_GOLD
    )
    embed.add_field(name="🏆 Top 3 archiviata", value=top3_text[:1024], inline=False)
    embed.add_field(name="💰 Saldo iniziale", value=f"{starting_balance} crediti", inline=True)
    embed.add_field(name="🛡️ Conservato", value="Shop, inventario, cosmetici, equipaggiamenti", inline=False)
    embed.add_field(name="♻️ Reset", value="Crediti, XP, livelli, badge stagionali, streak, statistiche, mercati, portafogli e storico prezzi", inline=False)
    await ctx.send(embed=embed)
    await log_admin_activity(ctx, "🔄 !seasonreset", details=f"Archiviata stagione {closed_season}; avviata stagione {new_season}; saldo iniziale {starting_balance}", color=COLOR_GOLD)


@bot.command(name="stagione", aliases=["season"])
async def stagione(ctx):
    current = ensure_active_season()
    c.execute("SELECT started_at FROM seasons WHERE season_number=?", (current,))
    row = c.fetchone()
    started_at = row[0] if row else "N/D"

    embed = discord.Embed(
        title=f"📖 Stagione {current}",
        description="Stagione corrente e archivio delle stagioni concluse.",
        color=COLOR_CYAN
    )
    embed.add_field(name="🟢 Stato", value="Attiva", inline=True)
    embed.add_field(name="📅 Inizio", value=str(started_at).replace("T", " ")[:19], inline=True)

    top3 = build_current_ranking(3)
    if top3:
        value = "\n".join(f"#{idx} <@{uid}> — **{net:.0f}** crediti" for idx, (uid, _bal, _open, net) in enumerate(top3, start=1))
    else:
        value = "Nessun partecipante."
    embed.add_field(name="🏆 Top 3 corrente", value=value, inline=False)

    c.execute("""
        SELECT season_number, champion_user_id, champion_net_worth, top3_text, total_markets, total_trades
        FROM season_archives
        ORDER BY season_number DESC
        LIMIT 3
    """)
    archives = c.fetchall()
    if archives:
        for season_number, champion_id, champion_net, top3_text, total_markets, total_trades in archives:
            champion = f"<@{champion_id}>" if champion_id else "N/D"
            embed.add_field(
                name=f"📜 Stagione {season_number} archiviata",
                value=(
                    f"🏆 Campione: {champion} — **{float(champion_net or 0):.0f}** crediti\n"
                    f"📊 Mercati: {total_markets or 0} • Trade: {total_trades or 0}\n"
                    f"{str(top3_text or '')[:500]}"
                ),
                inline=False
            )
    else:
        embed.add_field(name="📜 Archivio", value="Nessuna stagione archiviata.", inline=False)

    embed.set_footer(text="Il reset stagionale è disponibile solo agli admin con !seasonreset")
    await ctx.send(embed=embed)


# =========================
# HELP COMMANDS
# =========================
@bot.command(name="help", aliases=["aiuto"])
async def help_command(ctx, section: str = None):
    if section and section.lower() == "admin":
        if not is_admin_member(ctx.author):
            await ctx.send("⛔ La guida admin è riservata agli admin.")
            return

        embed = discord.Embed(
            title="🛠️ Help Admin",
            description="Comandi riservati alla gestione del bot e dei mercati.",
            color=COLOR_WHITE
        )
        embed.add_field(
            name="📊 Mercati",
            value=(
                "`!creatematch ID domanda` / `!creamercato`\n"
                "`!closemarket ID` / `!chiudimercato`\n"
                "`!cancelmarket ID` / `!annullamercato`\n"
                "`!resolve ID YES/NO` / `!risolvi`\n"
                "`!createevent categoria domanda` / `!creaevento`"
            ),
            inline=False
        )
        embed.add_field(
            name="🎲 Eventi speciali",
            value=(
                "Categorie: `politica`, `f1`, `musica`, `cinema`, `sport`, `geopolitica`, `economia`, `gaming`, `tv`, `attualita`\n"
                "Gli eventi non vengono pubblicati nel canale annunci e vanno risolti manualmente."
            ),
            inline=False
        )
        embed.add_field(
            name="⚽ API e analisi",
            value=(
                "`!fixtures COMPETIZIONE giorni` / `!partite`\n"
                "`!predict MATCH_ID` / `!previsione`\n"
                "`!checkapi`\n"
                "`!testmatch MATCH_ID`"
            ),
            inline=False
        )
        embed.add_field(
            name="💰 Utenti",
            value=(
                "`!addbalance @utente importo`\n"
                "`!removebalance @utente importo`\n"
                "`!resetuser @utente`\n"
                "`!seasonreset [saldo_iniziale]`"
            ),
            inline=False
        )
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title="📘 Help",
        description="Comandi disponibili per usare il prediction market.",
        color=COLOR_RED
    )
    embed.add_field(
        name="💰 Account",
        value=(
            "`!balance` / `!saldo`\n"
            "`!daily` / `!giornaliero`\n"
            "`!profile` / `!profilo`\n"
            "`!portfolio` / `!portafoglio`\n"
            "`!leaderboard` / `!classifica`\n"
            "`!stagione`"
        ),
        inline=False
    )
    embed.add_field(
        name="📊 Mercati",
        value=(
            "`!markets` / `!mercati`\n"
            "`!market ID` / `!mercato ID`\n"
            "`!buy ID YES/NO importo` / `!compra`\n"
            "`!sell ID percentuale [YES/NO]` / `!vendi`\n"
            "`!chart ID` / `!grafico`"
        ),
        inline=False
    )
    embed.add_field(
        name="⚽ Info",
        value=(
            "`!live` / `!diretta`\n"
            "`!referrals` / `!inviti`"
        ),
        inline=False
    )
    embed.add_field(
        name="🔔 Alert personali",
        value=(
            "`!alert price ID YES/NO percentuale`\n"
            "`!alert profit ID percentuale`\n"
            "`!alert loss ID percentuale`\n"
            "`!alert closing ID`\n"
            "`!alert resolved ID`\n"
            "`!alerts`\n"
            "`!alert remove ALERT_ID` / `!alert clear`"
        ),
        inline=False
    )
    embed.add_field(
        name="👥 Social trading",
        value=(
            "`!follow @utente`\n"
            "`!unfollow @utente`\n"
            "`!following`\n"
            "`!trader @utente`"
        ),
        inline=False
    )
    embed.add_field(
        name="🛒 Marketplace",
        value=(
            "`!shop` / `!marketplace` / `!negozio`\n"
            "`!shop themes|titles|flairs|collectibles|decorative|crates`\n"
            "`!buyitem item_id` / `!compraitem`\n"
            "`!inventory` / `!inventario`\n"
            "`!equip item_id` / `!equipaggia`\n"
            "`!unequip slot`"
        ),
        inline=False
    )
    await ctx.send(embed=embed)


# =========================
# PAYOUT
# =========================
def payout_market(market_id, result):
    c.execute("""
        SELECT user_id, side, amount
        FROM trades
        WHERE market_id=?
          AND amount > 0
          AND (closed IS NULL OR closed=0)
    """, (market_id,))
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
        c.execute("""
            UPDATE trades
            SET closed=1
            WHERE market_id=?
              AND amount > 0
              AND (closed IS NULL OR closed=0)
        """, (market_id,))
        conn.commit()
        return 0

    total_paid = 0

    for u, a in winners:
        share = a / total_win
        payout = int(a + share * losers_pool)

        total_paid += payout

        c.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id=?",
            (payout, u)
        )
        award_xp(u, max(10, payout // 20))
        record_wealth_snapshot(u)

    c.execute("""
        UPDATE trades
        SET closed=1
        WHERE market_id=?
          AND amount > 0
          AND (closed IS NULL OR closed=0)
    """, (market_id,))

    conn.commit()

    return total_paid


# =========================
# V2.0.0 NEWS + PERSONAL ALERT HELPERS
# =========================
def request_json(url, headers=None, params=None, timeout=10):
    try:
        r = requests.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
        try:
            data = r.json()
        except Exception:
            data = {}
        return r.status_code, data
    except Exception as e:
        return None, {"error": str(e)}


async def get_discord_channel_safe(channel_id):
    """Recupera un canale anche quando non è ancora in cache."""
    try:
        channel = bot.get_channel(int(channel_id))
        if channel:
            return channel
        return await bot.fetch_channel(int(channel_id))
    except Exception as e:
        print(f"[CHANNEL FETCH] Impossibile recuperare {channel_id}: {e}")
        return None


# Fonti RSS gratuite per #gazzetta. Ogni feed è opzionale: se non risponde, viene saltato.
GAZZETTA_RSS_FEEDS = [
    ("BBC Football", "https://feeds.bbci.co.uk/sport/football/rss.xml"),
    ("Sky Sports Football", "https://www.skysports.com/rss/12040"),
    ("ESPN Soccer", "https://www.espn.com/espn/rss/soccer/news"),
    ("Gazzetta Calcio", "https://www.gazzetta.it/rss/Calcio.xml"),
    ("Corriere dello Sport Calcio", "https://www.corrieredellosport.it/rss/calcio"),
    ("Tuttosport Calcio", "https://www.tuttosport.com/rss/calcio"),
]

# Filtro intelligente GNews/Gazzetta: calcio mondiale, non cronaca/politica.
FOOTBALL_COMPETITION_KEYWORDS = [
    "fifa", "world cup", "coppa del mondo", "mondiale", "mondiali", "uefa",
    "champions league", "europa league", "conference league", "nations league",
    "club world cup", "serie a", "serie b", "premier league", "la liga", "liga",
    "bundesliga", "ligue 1", "eredivisie", "primeira liga", "mls", "brasileirao",
    "copa libertadores", "libertadores", "copa sudamericana", "copa america", "afcon",
    "asian cup", "euro", "european championship", "qualificazioni", "qualifiers"
]

FOOTBALL_TERMS = [
    "calcio", "football", "soccer", "gol", "goal", "assist", "rigore", "penalty",
    "var", "fuorigioco", "offside", "cartellino", "red card", "yellow card",
    "espulsione", "ammonizione", "formazione", "formazioni", "lineup", "starting xi",
    "sostituzione", "substitution", "infortunio", "injury", "squalifica", "suspension",
    "allenatore", "coach", "manager", "ct", "stadio", "match", "partita", "derby",
    "mercato", "calciomercato", "transfer", "signing", "prestito", "loan", "contratto",
    "rinnovo", "club", "nazionale", "convocati", "rosa", "campionato", "coppa"
]

FOOTBALL_TEAM_KEYWORDS = [
    "italia", "italy", "argentina", "brazil", "brasile", "francia", "france", "spagna", "spain",
    "germany", "germania", "england", "inghilterra", "portugal", "portogallo", "netherlands",
    "olanda", "belgium", "belgio", "croatia", "croazia", "morocco", "marocco", "japan", "giappone",
    "usa", "united states", "mexico", "messico", "colombia", "uruguay", "ghana", "senegal",
    "milan", "inter", "juventus", "roma", "lazio", "napoli", "atalanta", "fiorentina",
    "torino", "bologna", "arsenal", "chelsea", "liverpool", "manchester united", "manchester city",
    "tottenham", "real madrid", "barcelona", "atletico", "psg", "paris saint-germain", "bayern",
    "borussia", "dortmund", "leverkusen", "benfica", "porto", "sporting", "ajax", "psv",
    "feyenoord", "flamengo", "palmeiras", "boca", "river plate", "al hilal", "al nassr"
]

NEWS_BLACKLIST = [
    "politica", "elezioni", "election", "parlamento", "parliament", "governo", "government",
    "ministro", "minister", "presidente del consiglio", "partito", "war", "guerra", "terrorismo",
    "omicidio", "murder", "polizia", "police", "tribunale", "court", "arresto", "arrested",
    "cronaca", "economia", "finance", "borsa", "stock", "crypto", "bitcoin", "meteo", "weather",
    "terremoto", "earthquake", "cinema", "movie", "tv", "reality", "celebrity", "gossip"
]


def clean_news_text(value):
    """Pulisce titoli e descrizioni provenienti da RSS/GNews.

    Risolve entità HTML, apostrofi/virgolette strane, spazi invisibili
    e piccoli residui di markup che rendono brutti gli embed di #gazzetta.
    """
    if value is None:
        return ""
    text = str(value)
    for _ in range(2):
        text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    replacements = {
        "‘": "'", "’": "'", "‚": "'", "ʼ": "'",
        "“": '"', "”": '"', "„": '"',
        "–": "-", "—": "-", "−": "-",
        " ": " ", "​": "", "﻿": "",
    }
    for old, new_value in replacements.items():
        text = text.replace(old, new_value)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _contains_keyword(text, keywords):
    text = text.lower()
    return [kw for kw in keywords if kw.lower() in text]


def football_news_relevance(article):
    """Restituisce (score, motivi). Pubblica solo notizie con score >= 3."""
    title = article.get("title", "") or ""
    desc = article.get("description", "") or ""
    text = f"{title} {desc}".lower()

    blacklist_hits = _contains_keyword(text, NEWS_BLACKLIST)
    competition_hits = _contains_keyword(text, FOOTBALL_COMPETITION_KEYWORDS)
    team_hits = _contains_keyword(text, FOOTBALL_TEAM_KEYWORDS)
    term_hits = _contains_keyword(text, FOOTBALL_TERMS)

    score = 0
    score += min(6, len(competition_hits) * 3)
    score += min(6, len(team_hits) * 2)
    score += min(6, len(term_hits) * 1)
    score -= len(blacklist_hits) * 5

    reasons = []
    if competition_hits:
        reasons.append("competizioni: " + ", ".join(competition_hits[:3]))
    if team_hits:
        reasons.append("squadre/nazionali: " + ", ".join(team_hits[:3]))
    if term_hits:
        reasons.append("termini calcio: " + ", ".join(term_hits[:4]))
    if blacklist_hits:
        reasons.append("blacklist: " + ", ".join(blacklist_hits[:3]))

    return score, "; ".join(reasons) if reasons else "nessun segnale forte"


def is_relevant_football_news(article):
    score, reason = football_news_relevance(article)
    article["relevance_score"] = score
    article["relevance_reason"] = reason
    return score >= 3


def is_news_already_seen(source, external_id):
    c.execute("SELECT 1 FROM news_seen WHERE source=? AND external_id=?", (source, str(external_id)))
    return c.fetchone() is not None


def mark_news_seen(source, external_id):
    try:
        c.execute("""
            INSERT OR IGNORE INTO news_seen (source, external_id, created_at)
            VALUES (?, ?, ?)
        """, (source, str(external_id), datetime.now(timezone.utc).isoformat()))
        conn.commit()
    except Exception as e:
        print(f"[NEWS SEEN] Errore salvataggio: {e}")


def _strip_xml_namespace(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _child_text(node, child_name):
    if node is None:
        return ""
    for child in list(node):
        if _strip_xml_namespace(child.tag).lower() == child_name.lower():
            return (child.text or "").strip()
    return ""


def _first_link(node):
    # RSS: <link>url</link>; Atom: <link href="url" />
    direct = _child_text(node, "link")
    if direct:
        return direct
    for child in list(node):
        if _strip_xml_namespace(child.tag).lower() == "link":
            href = child.attrib.get("href")
            if href:
                return href.strip()
    return ""


def _parse_rss_date(raw):
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(raw).isoformat()
    except Exception:
        return str(raw)[:80]


def parse_rss_items(source_name, xml_text, limit=6):
    """Parser RSS/Atom leggero senza dipendenze esterne."""
    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        print(f"[RSS] XML non valido per {source_name}: {e}")
        return []

    items = []
    for node in root.iter():
        tag = _strip_xml_namespace(node.tag).lower()
        if tag not in ("item", "entry"):
            continue

        title = clean_news_text(_child_text(node, "title") or "Notizia calcistica")
        description = clean_news_text(_child_text(node, "description") or _child_text(node, "summary") or _child_text(node, "content") or "")
        url = clean_news_text(_first_link(node))
        guid = clean_news_text(_child_text(node, "guid") or _child_text(node, "id") or url or title)
        published = clean_news_text(_child_text(node, "pubDate") or _child_text(node, "published") or _child_text(node, "updated"))

        article = {
            "source": source_name,
            "external_id": guid,
            "title": title,
            "description": description,
            "url": url,
            "published_at": _parse_rss_date(published),
        }
        if is_relevant_football_news(article):
            items.append(article)
        else:
            print(f"[RSS FILTER] Scartata da {source_name}: {article['title']} | score={article.get('relevance_score')} | {article.get('relevance_reason')}")

        if len(items) >= limit:
            break

    return items


def fetch_rss_football_news():
    articles = []
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; CalcyscordBot/2.0; +https://discord.com)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }

    for source_name, url in GAZZETTA_RSS_FEEDS:
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code != 200:
                print(f"[RSS] {source_name} status {r.status_code}: {url}")
                continue
            articles.extend(parse_rss_items(source_name, r.text, limit=4))
        except Exception as e:
            print(f"[RSS] Errore {source_name}: {e}")

    articles.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    return articles[:12]


@bot.command()
@admin_only()
async def testrss(ctx):
    """Diagnostica admin per controllare i feed RSS della Gazzetta."""
    embed = discord.Embed(
        title="🧪 Test RSS Gazzetta",
        description="Controllo feed RSS calcistici.",
        color=COLOR_CYAN,
        timestamp=datetime.now(timezone.utc)
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; CalcyscordBot/2.0; +https://discord.com)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    lines = []
    total_relevant = 0
    for source_name, url in GAZZETTA_RSS_FEEDS:
        try:
            r = requests.get(url, headers=headers, timeout=12)
            parsed = parse_rss_items(source_name, r.text, limit=5) if r.status_code == 200 else []
            total_relevant += len(parsed)
            lines.append(f"{source_name}: HTTP {r.status_code} • rilevanti {len(parsed)}")
        except Exception as e:
            lines.append(f"{source_name}: errore {str(e)[:60]}")

    embed.add_field(name="Feed", value="\n".join(lines)[:1024] or "N/D", inline=False)
    embed.add_field(name="Totale notizie rilevanti", value=str(total_relevant), inline=True)
    await ctx.send(embed=embed)


def fetch_gnews_sports():
    """GNews v2.0.1: ricerca larga ma filtro severo sul calcio mondiale."""
    if not GNEWS_API_KEY:
        return []

    query = (
        '("calcio" OR "football" OR "soccer" OR "Serie A" OR "Premier League" OR '
        '"Champions League" OR "World Cup" OR "calciomercato" OR "transfer")'
    )

    status, data = request_json(
        "https://gnews.io/api/v4/search",
        params={
            "q": query,
            "lang": "it",
            "country": "it",
            "max": 10,
            "apikey": GNEWS_API_KEY
        }
    )

    if status != 200:
        print(f"[GNEWS] Status {status}: {data}")
        return []

    articles = []
    for a in data.get("articles", []) or []:
        external_id = a.get("url") or a.get("title")
        if not external_id:
            continue
        article = {
            "source": "GNews",
            "external_id": external_id,
            "title": clean_news_text(a.get("title", "Notizia calcistica")),
            "description": clean_news_text(a.get("description") or ""),
            "url": clean_news_text(a.get("url") or ""),
            "published_at": clean_news_text(a.get("publishedAt") or "")
        }
        if is_relevant_football_news(article):
            articles.append(article)
        else:
            print(f"[GNEWS FILTER] Scartata: {article['title']} | score={article.get('relevance_score')} | {article.get('relevance_reason')}")

    # pubblica prima le notizie più pertinenti
    articles.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    return articles[:5]


def fetch_api_football_news():
    """Fonte opzionale separata per API-Football/API-Sports.

    API-Football non sempre espone endpoint news nei piani standard: per questo
    la URL può essere configurata via API_FOOTBALL_NEWS_URL. Se non è presente,
    il bot non si blocca e GNews continua a funzionare.
    """
    if not API_FOOTBALL_KEY or not API_FOOTBALL_NEWS_URL:
        return []

    headers = {
        "x-apisports-key": API_FOOTBALL_KEY,
        "x-rapidapi-key": API_FOOTBALL_KEY,
        "x-rapidapi-host": API_FOOTBALL_HOST
    }

    status, data = request_json(API_FOOTBALL_NEWS_URL, headers=headers)

    if status != 200:
        print(f"[API-FOOTBALL NEWS] Status {status}: {data}")
        return []

    raw_items = data.get("response") or data.get("articles") or data.get("news") or []
    articles = []

    for item in raw_items[:5]:
        title = clean_news_text(item.get("title") or item.get("headline") or "Aggiornamento calcio")
        url = clean_news_text(item.get("url") or item.get("link") or "")
        external_id = clean_news_text(item.get("id") or url or title)
        articles.append({
            "source": "API-Football",
            "external_id": external_id,
            "title": title,
            "description": clean_news_text(item.get("description") or item.get("summary") or ""),
            "url": url,
            "published_at": clean_news_text(item.get("published_at") or item.get("date") or "")
        })

    return articles


async def post_news_article(channel, article):
    title = clean_news_text(article.get("title") or "Notizia calcistica")
    description = clean_news_text(article.get("description") or "Nuovo aggiornamento disponibile.")
    embed = discord.Embed(
        title=f"📰 {title[:250]}",
        description=description[:1000],
        color=COLOR_CYAN,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="Fonte", value=clean_news_text(article.get("source", "News")), inline=True)
    if article.get("published_at"):
        embed.add_field(name="Pubblicata", value=clean_news_text(article["published_at"])[:80], inline=True)
    if article.get("url"):
        embed.add_field(name="Link", value=clean_news_text(article["url"])[:1024], inline=False)
    if article.get("relevance_score") is not None:
        embed.add_field(name="Rilevanza calcio", value=f"{article.get('relevance_score')} punti", inline=True)
    embed.set_footer(text="Gazzetta • RSS + GNews • filtro calcio mondiale v2.0.2")

    await channel.send(embed=embed)


async def market_pulse_news_loop():
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            channel = await get_discord_channel_safe(GAZZETTA_CHANNEL_ID)
            if not channel:
                print(f"[GAZZETTA] Canale {GAZZETTA_CHANNEL_ID} non trovato.")
            else:
                articles = fetch_rss_football_news() + fetch_api_football_news() + fetch_gnews_sports()

                for article in articles:
                    source = clean_news_text(article.get("source", "news"))
                    external_id = clean_news_text(article.get("external_id") or article.get("url") or article.get("title"))
                    if not external_id or is_news_already_seen(source, external_id):
                        continue

                    await post_news_article(channel, article)
                    mark_news_seen(source, external_id)
                    await asyncio.sleep(2)

        except Exception as e:
            print("[GAZZETTA NEWS] Errore loop news:", e)

        await asyncio.sleep(NEWS_LOOP_MINUTES * 60)


# Gazzetta live Sportmonks/Sofascore rimossa: #gazzetta usa RSS + GNews.


async def notify_personal_alert(user_id, embed, fallback_channel=None):
    try:
        user = bot.get_user(int(user_id)) or await bot.fetch_user(int(user_id))
    except Exception:
        user = None

    if user:
        try:
            await user.send(embed=embed)
            return True
        except Exception:
            pass

    if fallback_channel:
        try:
            await fallback_channel.send(content=f"<@{user_id}>", embed=embed)
            return True
        except Exception:
            pass

    return False


def get_market_row(market_id):
    c.execute("""
        SELECT id, question, yes_pool, no_pool, total_pool, active, resolved, result, match_key, channel_id
        FROM markets
        WHERE id=?
    """, (market_id,))
    return c.fetchone()


def calculate_user_market_pnl(user_id, market_id):
    c.execute("""
        SELECT side, amount, price
        FROM trades
        WHERE user_id=?
          AND market_id=?
          AND amount > 0
          AND (closed IS NULL OR closed=0)
    """, (str(user_id), market_id))
    rows = c.fetchall()

    if not rows:
        return None

    market = get_market_row(market_id)
    if not market:
        return None

    _, _, yes, no, *_ = market
    yes_p, no_p = market_probabilities(yes, no)

    invested = 0.0
    current_value = 0.0

    for side, amount, entry_price in rows:
        current_price = yes_p if side == "YES" else no_p
        entry_price = safe_entry_price(entry_price, current_price)
        invested += float(amount)
        current_value += float(amount) * (current_price / entry_price)

    if invested <= 0:
        return None

    pnl_percent = ((current_value - invested) / invested) * 100
    return invested, current_value, pnl_percent


def build_personal_alert_embed(alert_id, alert_type, market_id, question, details):
    embed = discord.Embed(
        title="🔔 Alert personale",
        description=question,
        color=COLOR_GOLD,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="🆔 Alert", value=f"#{alert_id}", inline=True)
    embed.add_field(name="🆔 Mercato", value=f"#{market_id}", inline=True)
    embed.add_field(name="Tipo", value=alert_type, inline=True)
    embed.add_field(name="Dettagli", value=details[:1000], inline=False)
    embed.set_footer(text="Alert personale v2.0.0")
    return embed


async def check_personal_alerts_for_market(market_id, fallback_channel=None, only_resolved=False):
    market = get_market_row(market_id)
    if not market:
        return

    mid, question, yes, no, total, active, resolved, result, match_key, channel_id = market
    yes_p, no_p = market_probabilities(yes, no)

    c.execute("""
        SELECT id, user_id, alert_type, side, target_value
        FROM personal_alerts
        WHERE market_id=?
          AND active=1
          AND triggered=0
    """, (market_id,))
    alerts = c.fetchall()

    for alert_id, user_id, alert_type, side, target_value in alerts:
        should_trigger = False
        details = ""

        if alert_type == "price" and not only_resolved:
            current = yes_p if side == "YES" else no_p
            if current >= float(target_value):
                should_trigger = True
                details = f"La quota **{side}** ha raggiunto **{current:.1f}%** contro soglia **{target_value:.1f}%**."

        elif alert_type in ["profit", "loss"] and not only_resolved:
            pnl = calculate_user_market_pnl(user_id, market_id)
            if pnl:
                invested, current_value, pnl_percent = pnl
                if alert_type == "profit" and pnl_percent >= float(target_value):
                    should_trigger = True
                    details = f"Profit target raggiunto: **{pnl_percent:+.1f}%**. Valore stimato: **{current_value:.0f}** su **{invested:.0f}** investiti."
                elif alert_type == "loss" and pnl_percent <= -abs(float(target_value)):
                    should_trigger = True
                    details = f"Soglia perdita raggiunta: **{pnl_percent:+.1f}%**. Valore stimato: **{current_value:.0f}** su **{invested:.0f}** investiti."

        elif alert_type == "resolved" and resolved == 1:
            should_trigger = True
            details = f"Il mercato è stato risolto con esito **{result or 'N/D'}**."

        if should_trigger:
            embed = build_personal_alert_embed(alert_id, alert_type, market_id, question, details)
            sent = await notify_personal_alert(user_id, embed, fallback_channel=fallback_channel)
            if sent:
                c.execute("""
                    UPDATE personal_alerts
                    SET triggered=1,
                        active=0,
                        triggered_at=?
                    WHERE id=?
                """, (datetime.now(timezone.utc).isoformat(), alert_id))
                conn.commit()


async def personal_alert_checker_loop():
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            c.execute("SELECT id, channel_id FROM markets WHERE active=1 OR resolved=1")
            rows = c.fetchall()
            for market_id, channel_id in rows:
                fallback = None
                try:
                    fallback = bot.get_channel(int(channel_id)) if channel_id else None
                except Exception:
                    fallback = None
                await check_personal_alerts_for_market(market_id, fallback_channel=fallback)

            await check_closing_alerts()

        except Exception as e:
            print("[PERSONAL ALERTS] Errore:", e)

        await asyncio.sleep(60)


async def check_closing_alerts():
    now = datetime.now(timezone.utc)

    c.execute("""
        SELECT a.id, a.user_id, a.market_id, m.question, m.match_key, m.channel_id
        FROM personal_alerts a
        JOIN markets m ON a.market_id=m.id
        WHERE a.alert_type='closing'
          AND a.active=1
          AND a.triggered=0
          AND m.active=1
          AND m.resolved=0
          AND m.match_key LIKE 'MATCH_%'
    """)
    rows = c.fetchall()

    for alert_id, user_id, market_id, question, match_key, channel_id in rows:
        try:
            match_id = int(str(match_key).replace("MATCH_", ""))
        except Exception:
            continue

        match, _, _ = get_match_details(match_id)
        if not match:
            continue

        utc_date = match.get("utcDate")
        if not utc_date:
            continue

        try:
            start_dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
        except Exception:
            continue

        if start_dt - timedelta(minutes=10) <= now <= start_dt + timedelta(minutes=5):
            embed = build_personal_alert_embed(
                alert_id,
                "closing",
                market_id,
                question,
                "La partita collegata al mercato inizierà tra circa **10 minuti**. Ultima occasione per controllare la posizione."
            )
            fallback = None
            try:
                fallback = bot.get_channel(int(channel_id)) if channel_id else None
            except Exception:
                fallback = None

            sent = await notify_personal_alert(user_id, embed, fallback_channel=fallback)
            if sent:
                c.execute("""
                    UPDATE personal_alerts
                    SET triggered=1,
                        active=0,
                        triggered_at=?
                    WHERE id=?
                """, (datetime.now(timezone.utc).isoformat(), alert_id))
                conn.commit()

# =========================
# MARKET ALERTS
# =========================
async def maybe_send_market_alert(market_id, question, yes, no, channel_id, last_alert_yes_price):
    yes_p, no_p = market_probabilities(yes, no)

    if last_alert_yes_price is None:
        c.execute("UPDATE markets SET alert_yes_price=? WHERE id=?", (yes_p, market_id))
        conn.commit()
        return

    diff = yes_p - last_alert_yes_price

    if abs(diff) < ALERT_THRESHOLD:
        return

    # v2.0.2: gli alert pubblici sulle quote vanno nel canale annunci sport.
    channel = await get_discord_channel_safe(SPORT_ANNOUNCEMENTS_CHANNEL_ID)
    if not channel and MARKET_CHANNEL_ID:
        channel = await get_discord_channel_safe(MARKET_CHANNEL_ID)
    if not channel and channel_id:
        try:
            channel = await get_discord_channel_safe(int(channel_id))
        except Exception:
            channel = None

    if not channel:
        print(f"[MARKET UPDATE] Canale annunci sport {SPORT_ANNOUNCEMENTS_CHANNEL_ID} non trovato.")
        return

    direction = "📈" if diff > 0 else "📉"

    embed = discord.Embed(
        title="🔔 MARKET UPDATE | Alert quota",
        description=question,
        color=COLOR_ORANGE,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="🆔 Mercato", value=str(market_id), inline=True)
    embed.add_field(name="Variazione YES", value=f"{direction} {last_alert_yes_price:.1f}% → {yes_p:.1f}%", inline=False)
    embed.add_field(name="🔴 NO", value=f"{no_p:.1f}%", inline=True)
    embed.add_field(name="📊 Scostamento", value=f"{diff:+.1f}%", inline=True)
    embed.add_field(name="📉 Barra", value=f"`{progress_bar(yes_p)}`", inline=False)
    embed.set_footer(text="Annunci Sport • Market Update v2.0.2")

    await channel.send(embed=embed)

    c.execute("UPDATE markets SET alert_yes_price=? WHERE id=?", (yes_p, market_id))
    conn.commit()


# =========================
# RESOLVER LOOP
# =========================
async def resolver_loop():
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            c.execute("""
                SELECT id, question, match_key, channel_id, yes_pool, no_pool, alert_yes_price
                FROM markets
                WHERE active=1 AND resolved=0
            """)

            markets = c.fetchall()

            for mid, question, mk, channel_id, yes, no, alert_yes_price in markets:
                if not mk or not mk.startswith("MATCH_"):
                    continue

                try:
                    match_id = int(mk.replace("MATCH_", ""))
                except Exception:
                    continue

                res = get_match_result(match_id)

                if not res:
                    continue

                if not res["finished"]:
                    await maybe_send_market_alert(mid, question, yes, no, channel_id, alert_yes_price)
                    continue

                winner = res["winner"]

                if winner == "HOME":
                    final = "YES"
                else:
                    final = "NO"

                c.execute("""
                    UPDATE markets
                    SET active=0,
                        resolved=1,
                        result=?
                    WHERE id=?
                """, (final, mid))

                conn.commit()

                update_streaks_for_market(mid, final)
                total_paid = payout_market(mid, final)

                c.execute("SELECT DISTINCT user_id FROM trades WHERE market_id=?", (mid,))
                for (affected_user_id,) in c.fetchall():
                    await evaluate_user_badges(affected_user_id, notify=True)

                score = "N/D"
                if res["home_goals"] is not None and res["away_goals"] is not None:
                    score = f'{res["home_goals"]}-{res["away_goals"]}'

                print(f"[CLOSED] {mid} -> {final}")

                result_channel = await get_discord_channel_safe(RESULTS_CHANNEL_ID)
                if result_channel:
                    outcome_icon = "🟢 YES" if final == "YES" else "🔴 NO"
                    winner_text = res["home"] if winner == "HOME" else res["away"] if winner == "AWAY" else "Pareggio"

                    embed = discord.Embed(
                        title="🏁 Mercato risolto",
                        description=question,
                        color=COLOR_RESOLVED
                    )
                    embed.add_field(name="🏟️ Partita", value=f'{res["home"]} vs {res["away"]}', inline=False)
                    embed.add_field(name="⚽ Risultato finale", value=score, inline=True)
                    embed.add_field(name="🏆 Vincitore", value=winner_text, inline=True)
                    embed.add_field(name="🎯 Esito mercato", value=outcome_icon, inline=True)
                    embed.add_field(name="💰 Payout", value=f"Mercato #{mid} risolto • {total_paid} crediti distribuiti", inline=False)
                    embed.set_footer(text="Grazie per aver giocato!")

                    await result_channel.send(embed=embed)
                else:
                    print(f"[RESULTS CHANNEL] Canale {RESULTS_CHANNEL_ID} non trovato.")

                await check_personal_alerts_for_market(mid, fallback_channel=result_channel, only_resolved=True)

        except Exception as e:
            print("ERR:", e)

        await asyncio.sleep(120)



# =========================
# REFERRAL EVENTS
# =========================
@bot.event
async def on_member_join(member):
    # Ignora i bot e gli auto-inviti.
    if member.bot:
        return

    guild = member.guild
    before = INVITE_CACHE.get(guild.id, {})

    try:
        current_invites = await guild.invites()
    except Exception as e:
        print(f"[REFERRAL] Impossibile leggere inviti su join: {e}")
        await cache_guild_invites(guild)
        return

    used_invite = None
    for invite in current_invites:
        old_uses = before.get(invite.code, 0)
        if invite.uses > old_uses:
            used_invite = invite
            break

    INVITE_CACHE[guild.id] = {invite.code: invite.uses for invite in current_invites}

    if not used_invite or not used_invite.inviter:
        return

    inviter = used_invite.inviter

    if inviter.bot:
        return

    if inviter.id == member.id:
        return

    now = datetime.now(timezone.utc).isoformat()

    c.execute("""
        INSERT OR IGNORE INTO referrals (
            invited_user_id,
            inviter_user_id,
            guild_id,
            invite_code,
            joined_at,
            rewarded,
            rewarded_at
        )
        VALUES (?, ?, ?, ?, ?, 0, NULL)
    """, (str(member.id), str(inviter.id), str(guild.id), used_invite.code, now))
    conn.commit()

    print(f"[REFERRAL TRACKED] {inviter.id} invited {member.id} via {used_invite.code}")


# =========================
# READY
# =========================
@bot.event
async def on_ready():
    print(f"Bot online {bot.user}")
    await cache_all_invites()
    bot.loop.create_task(resolver_loop())
    bot.loop.create_task(referral_checker())
    bot.loop.create_task(badge_checker_loop())
    bot.loop.create_task(calendar_poster_loop())
    bot.loop.create_task(market_pulse_news_loop())
    bot.loop.create_task(personal_alert_checker_loop())


# =========================
# RUN
# =========================
bot.run(token)


# === Marketplace Theme Update v2.0.2 ===
# Temi Embed:
# Standard, After Hours, Iceberg, Dark Pool,
# Toro di Smeraldo, Blue Chip,
# Prime Broker, Aurora Quantica
# Colore predefinito embed: COLOR_GREY
# I temi modificano !profile, !portfolio e !balance.


# === TEMI EMBED v2.0.2 ===
SHOP_ITEMS.update({
    "theme_standard":{
        "emoji":"⚪","name":"Standard","category":"embed_themes","slot":"theme",
        "price":0,"rarity":"Comune","new":False,"limited":False,
        "desc":"Tema classico dai toni grigi."
    },
    "theme_after_hours":{
        "emoji":"🌌","name":"After Hours","category":"embed_themes","slot":"theme",
        "price":2500,"rarity":"Comune","new":True,"limited":False,
        "desc":"Tema viola ispirato ai mercati notturni."
    },
    "theme_iceberg":{
        "emoji":"🧊","name":"Iceberg","category":"embed_themes","slot":"theme",
        "price":4500,"rarity":"Non comune","new":True,"limited":False,
        "desc":"Tema glaciale dai toni ghiaccio."
    },
    "theme_dark_pool":{
        "emoji":"🌑","name":"Dark Pool","category":"embed_themes","slot":"theme",
        "price":7500,"rarity":"Rara","new":True,"limited":False,
        "desc":"Tema viola scuro dal look esclusivo."
    },
    "theme_emerald_bull":{
        "emoji":"🌿","name":"Toro di Smeraldo","category":"embed_themes","slot":"theme",
        "price":9000,"rarity":"Rara","new":True,"limited":False,
        "desc":"Tema verde smeraldo raffinato."
    },
    "theme_blue_chip":{
        "emoji":"💎","name":"Blue Chip","category":"embed_themes","slot":"theme",
        "price":15000,"rarity":"Epica","new":True,"limited":False,
        "desc":"Tema blu profondo ed elegante."
    },
    "theme_prime_broker":{
        "emoji":"👑","name":"Prime Broker","category":"embed_themes","slot":"theme",
        "price":25000,"rarity":"Epica","new":True,"limited":False,
        "desc":"Tema dorato dallo stile premium."
    },
    "theme_quantum_aurora":{
        "emoji":"🌠","name":"Aurora Quantica","category":"embed_themes","slot":"theme",
        "price":35000,"rarity":"Leggendaria","new":True,"limited":False,
        "desc":"Tema cangiante viola e ciano."
    },
})

