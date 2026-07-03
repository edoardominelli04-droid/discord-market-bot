import os
import discord
import sqlite3
import requests
import asyncio
import matplotlib.pyplot as plt
import io

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except Exception:
    Image = ImageDraw = ImageFont = ImageFilter = None

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

# API News + Live v2.0.1
# GNEWS_API_KEY: notizie calcistiche via GNews.
# SPORTMONKS_API_TOKEN: live calcio via Sportmonks.
# API_FOOTBALL_KEY: opzionale, per fonti API-Football/API-Sports se disponibili.
GNEWS_API_KEY = os.environ.get("GNEWS_API_KEY")
SPORTMONKS_API_TOKEN = os.environ.get("SPORTMONKS_API_TOKEN") or os.environ.get("SPORTMONKS_TOKEN")
SPORTMONKS_BASE_URL = os.environ.get("SPORTMONKS_BASE_URL", "https://api.sportmonks.com/v3/football")
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
API_FOOTBALL_HOST = os.environ.get("API_FOOTBALL_HOST", "v3.football.api-sports.io")
API_FOOTBALL_NEWS_URL = os.environ.get("API_FOOTBALL_NEWS_URL")
NEWS_LOOP_MINUTES = 30
GAZZETTA_LIVE_LOOP_SECONDS = 90

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
# PROFILE CARD PNG ENGINE v2.0.2
# =========================
PROFILE_CARD_WIDTH = 1200
PROFILE_CARD_HEIGHT = 675

PROFILE_CARD_THEMES = {
    "standard": {
        "name": "Standard",
        "bg": (14, 17, 23),
        "panel": (17, 24, 39),
        "panel_2": (31, 41, 55),
        "text": (248, 250, 252),
        "muted": (156, 163, 175),
        "accent": (56, 189, 248),
        "accent_2": (34, 197, 94),
        "danger": (239, 68, 68),
    },
    "theme_dark_exchange": {
        "name": "Dark Exchange",
        "bg": (3, 7, 18),
        "panel": (15, 23, 42),
        "panel_2": (30, 41, 59),
        "text": (248, 250, 252),
        "muted": (148, 163, 184),
        "accent": (139, 92, 246),
        "accent_2": (34, 197, 94),
        "danger": (248, 113, 113),
    },
    "theme_stadium": {
        "name": "Stadium Lights",
        "bg": (8, 47, 73),
        "panel": (12, 74, 110),
        "panel_2": (14, 116, 144),
        "text": (240, 249, 255),
        "muted": (186, 230, 253),
        "accent": (250, 204, 21),
        "accent_2": (34, 197, 94),
        "danger": (248, 113, 113),
    },
}


def _profile_card_theme_for_user(user_id):
    """Restituisce la palette grafica della card in base al tema equipaggiato."""
    theme_id = "standard"
    try:
        equipped = get_equipped_items(user_id)
        theme_id = equipped.get("theme") or "standard"
    except Exception:
        theme_id = "standard"
    return PROFILE_CARD_THEMES.get(theme_id, PROFILE_CARD_THEMES["standard"]), theme_id


def _load_card_font(size, bold=False):
    if ImageFont is None:
        return None
    candidates = []
    if bold:
        candidates += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        ]
    candidates += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_rounded(draw, box, radius, fill, outline=None, width=1):
    try:
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)
    except Exception:
        draw.rectangle(box, fill=fill, outline=outline, width=width)


def _draw_text(draw, xy, text, font, fill, max_width=None):
    text = str(text)
    if max_width and font is not None:
        while text:
            bbox = draw.textbbox((0, 0), text, font=font)
            if bbox[2] - bbox[0] <= max_width:
                break
            text = text[:-2] + "…"
    draw.text(xy, text, font=font, fill=fill)


def _make_circle_avatar(raw_bytes, size):
    avatar = Image.open(io.BytesIO(raw_bytes)).convert("RGBA").resize((size, size))
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, size - 1, size - 1), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(avatar, (0, 0), mask)
    return out


def _draw_stat_card(draw, box, label, value, theme, value_color=None):
    """Disegna un pannello statistico Standard v2.0.2.

    Redesign card Standard:
    - numero grande sopra;
    - etichetta piccola sotto;
    - pannello arrotondato e pulito;
    - nessuna texture o riga di sfondo.
    """
    _draw_rounded(draw, box, 28, theme["panel"], outline=theme["panel_2"], width=2)
    x1, y1, x2, y2 = box
    font_value = _load_card_font(46, True)
    font_label = _load_card_font(23, False)
    _draw_text(draw, (x1 + 26, y1 + 26), value, font_value, value_color or theme["text"], max_width=(x2 - x1 - 52))
    _draw_text(draw, (x1 + 28, y1 + 83), label.upper(), font_label, theme["muted"], max_width=(x2 - x1 - 56))


async def make_profile_card_png(member, metrics, trader_level, xp_current, xp_required, badge_ids=None):
    """
    Profile Card PNG Standard redesign.

    Principi:
    - niente emoji nella PNG;
    - sfondo tinta unita;
    - avatar e nome grandi;
    - trader level e rank sotto il nome;
    - riquadri uniformi;
    - numeri sopra, etichette sotto;
    - colori solo sui numeri principali;
    - badge/collezionabili NON nella PNG.
    """
    if Image is None or ImageDraw is None or ImageFont is None:
        raise RuntimeError("Pillow non installato: impossibile generare la card PNG.")

    user_id = str(member.id)
    theme, theme_id = _profile_card_theme_for_user(user_id)

    W, H = 1200, 675

    # Palette Standard pulita
    bg = (10, 14, 22)
    panel = (18, 25, 38)
    panel_soft = (24, 32, 48)
    border = (42, 54, 76)
    text = (245, 247, 250)
    muted = (155, 164, 178)

    green = (34, 197, 94)
    blue = (56, 189, 248)
    red = (239, 68, 68)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    # Font
    font_name = _load_card_font(76, True)
    font_meta = _load_card_font(30, False)
    font_number_big = _load_card_font(58, True)
    font_number_med = _load_card_font(50, True)
    font_label = _load_card_font(24, False)
    font_xp = _load_card_font(26, True)
    font_xp_small = _load_card_font(24, False)

    # Helpers locali
    def rounded(box, radius=28, fill=panel, outline=border, width=2):
        _draw_rounded(draw, box, radius, fill, outline=outline, width=width)

    def text_fit(xy, value, font, fill, max_width=None):
        _draw_text(draw, xy, str(value), font, fill, max_width=max_width)

    def draw_stat(box, value, label, value_color=text):
        rounded(box, 30, panel, border, 2)
        x1, y1, x2, y2 = box

        value = str(value)
        label = str(label).upper()

        # Numero grande sopra
        text_fit(
            (x1 + 28, y1 + 25),
            value,
            font_number_big if len(value) <= 7 else font_number_med,
            value_color,
            max_width=(x2 - x1 - 56)
        )

        # Etichetta sotto
        text_fit(
            (x1 + 30, y2 - 44),
            label,
            font_label,
            muted,
            max_width=(x2 - x1 - 60)
        )

    # =========================
    # HEADER
    # =========================
    header = (48, 42, 1152, 220)
    rounded(header, 38, panel, border, 2)

    # Avatar grande
    avatar_size = 142
    avatar_x = 78
    avatar_y = 60

    try:
        avatar_bytes = await member.display_avatar.with_size(256).read()
        avatar = _make_circle_avatar(avatar_bytes, avatar_size)
        img.paste(avatar, (avatar_x, avatar_y), avatar)

        draw.ellipse(
            (
                avatar_x - 5,
                avatar_y - 5,
                avatar_x + avatar_size + 5,
                avatar_y + avatar_size + 5,
            ),
            outline=blue,
            width=5,
        )
    except Exception:
        draw.ellipse(
            (
                avatar_x,
                avatar_y,
                avatar_x + avatar_size,
                avatar_y + avatar_size,
            ),
            fill=panel_soft,
            outline=blue,
            width=5,
        )

    # Nome grande
    display_name = getattr(member, "display_name", "Trader")
    rank = metrics.get("rank")
    rank_text = f"Rank #{rank}" if rank else "Rank N/D"

    name_x = 250
    text_fit(
        (name_x, 70),
        display_name,
        font_name,
        text,
        max_width=720
    )

    # Trader level + rank sotto
    text_fit(
        (name_x + 4, 150),
        f"{trader_level}   |   {rank_text}",
        font_meta,
        muted,
        max_width=700
    )

    # Piccola label standard, pulita
    rounded((970, 88, 1118, 136), 22, bg, border, 1)
    text_fit(
        (998, 101),
        "STANDARD",
        _load_card_font(23, True),
        blue,
        max_width=100
    )

    # =========================
    # DATI
    # =========================
    balance = float(metrics.get("balance", 0) or 0)
    net_worth = float(metrics.get("net_worth", 0) or 0)
    accuracy = float(metrics.get("accuracy", 0) or 0)
    total_trades = int(metrics.get("total_trades", 0) or 0)
    open_positions = int(metrics.get("open_positions", 0) or 0)
    current_streak = int(metrics.get("current_streak", 0) or 0)

    def fmt_int(v):
        try:
            return f"{float(v):,.0f}".replace(",", ".")
        except Exception:
            return str(v)

    # =========================
    # RIQUADRI STATISTICHE
    # =========================
    card_w = 338
    card_h = 132
    gap_x = 31
    gap_y = 28

    start_x = 48
    start_y = 255

    boxes = [
        (start_x, start_y, start_x + card_w, start_y + card_h),
        (start_x + card_w + gap_x, start_y, start_x + 2 * card_w + gap_x, start_y + card_h),
        (start_x + 2 * (card_w + gap_x), start_y, start_x + 3 * card_w + 2 * gap_x, start_y + card_h),

        (start_x, start_y + card_h + gap_y, start_x + card_w, start_y + 2 * card_h + gap_y),
        (start_x + card_w + gap_x, start_y + card_h + gap_y, start_x + 2 * card_w + gap_x, start_y + 2 * card_h + gap_y),
        (start_x + 2 * (card_w + gap_x), start_y + card_h + gap_y, start_x + 3 * card_w + 2 * gap_x, start_y + 2 * card_h + gap_y),
    ]

    draw_stat(boxes[0], fmt_int(balance), "Saldo", green)
    draw_stat(boxes[1], fmt_int(net_worth), "Patrimonio", blue)

    accuracy_color = green if accuracy >= 50 else red
    draw_stat(boxes[2], f"{accuracy:.1f}%", "Accuracy", accuracy_color)

    draw_stat(boxes[3], total_trades, "Trade", text)
    draw_stat(boxes[4], open_positions, "Posizioni", text)
    draw_stat(boxes[5], current_streak, "Streak", text)

    # =========================
    # XP BAR
    # =========================
    xp_box = (48, 590, 1152, 642)
    rounded(xp_box, 24, panel, border, 2)

    # Testo XP sinistra/destra
    text_fit(
        (76, 604),
        "XP Trader",
        font_xp,
        text,
        max_width=220
    )

    if str(xp_required) == "MAX":
        xp_text = f"{xp_current} XP"
        pct = 1.0
    else:
        xp_text = f"{xp_current}/{xp_required} XP"
        try:
            pct = float(xp_current) / float(xp_required)
        except Exception:
            pct = 0.0

    pct = max(0.0, min(1.0, pct))

    # XP totale a destra
    xp_text_font = font_xp_small
    bbox = draw.textbbox((0, 0), xp_text, font=xp_text_font)
    xp_text_w = bbox[2] - bbox[0]

    text_fit(
        (1124 - xp_text_w, 605),
        xp_text,
        xp_text_font,
        muted,
        max_width=260
    )

    # Barra centrale
    bar_x = 285
    bar_y = 611
    bar_w = 610
    bar_h = 15

    _draw_rounded(
        draw,
        (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
        9,
        panel_soft,
        outline=None,
        width=0
    )

    if pct > 0:
        fill_w = max(10, int(bar_w * pct))
        _draw_rounded(
            draw,
            (bar_x, bar_y, bar_x + fill_w, bar_y + bar_h),
            9,
            blue,
            outline=None,
            width=0
        )

    # Nessun footer, nessuna vetrina, nessun badge nella PNG

    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)

    return buffer, theme_id




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
    bal = get_user(str(ctx.author.id))

    embed = discord.Embed(
        title="💰 Saldo",
        color=COLOR_BLUE
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    embed.add_field(name="Crediti disponibili", value=f"{bal}", inline=False)

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
    color = COLOR_BLUE

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

    badge_ids = get_active_badges(user_id)
    metrics = {
        "balance": balance,
        "net_worth": net_worth,
        "open_positions": open_positions,
        "total_trades": total_trades,
        "accuracy": accuracy,
        "current_streak": current_streak,
        "best_streak": best_streak,
        "won_markets": won_markets,
        "lost_markets": lost_markets,
        "resolved_markets": resolved_markets,
        "rank": rank,
    }

    # v2.0.2: Profile Card PNG. Se l'ambiente non ha Pillow o Discord non riesce
    # a scaricare l'avatar, il comando torna automaticamente al vecchio embed.
    try:
        card_buffer, theme_id = await make_profile_card_png(
            ctx.author,
            metrics,
            trader_level,
            xp_current,
            xp_required,
            badge_ids=badge_ids,
        )
        file = discord.File(card_buffer, filename=f"profile_card_{ctx.author.id}.png")
        embed = discord.Embed(
            title=f"👤 Profilo di {ctx.author.display_name}",
            description="Profile Card grafica v2.0.2",
            color=COLOR_BLUE,
        )
        embed.set_image(url=f"attachment://profile_card_{ctx.author.id}.png")
        embed.add_field(name="🎨 Tema card", value=theme_id.replace("theme_", "").replace("_", " ").title(), inline=True)
        embed.add_field(name="⭐ Livello server", value=server_level, inline=True)
        embed.add_field(name="💹 Livello trader", value=trader_level, inline=True)
        apply_cosmetics_to_embed(embed, user_id, ctx.author, "Comando disponibile anche come !profilo • Card PNG v2.0.2")
        await ctx.send(embed=embed, file=file)
        return
    except Exception as e:
        print(f"[PROFILE CARD] Fallback embed per {user_id}: {e}")

    color = COLOR_BLUE
    profit_emoji = "🟢" if open_profit >= 0 else "🔴"

    embed = discord.Embed(
        title=f"👤 Profilo di {ctx.author.display_name} • {trader_level}",
        description="Scheda personale del trader",
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

    badge_text = " • ".join(format_badge(b) for b in badge_ids[:12]) if badge_ids else "Nessun badge sbloccato."
    if len(badge_text) > 1024:
        badge_text = badge_text[:1000] + "..."
    embed.add_field(name="🏅 Badge", value=badge_text, inline=False)
    embed.add_field(name="🎨 Marketplace", value=get_equipped_items_text(user_id), inline=False)

    apply_cosmetics_to_embed(embed, user_id, ctx.author, "Comando disponibile anche come !profilo • Fallback embed")

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
# LIVE MARKETS
# =========================
@bot.command(aliases=["diretta"])
async def live(ctx):
    """Live v2.0.1: usa Sportmonks per eventi completi, con fallback su football-data.org."""
    if SPORTMONKS_API_TOKEN:
        await live_sportmonks(ctx)
    else:
        await live_football_data_fallback(ctx)


async def live_sportmonks(ctx):
    status, data = sportmonks_live_payload()

    if status != 200:
        await ctx.send("⚠️ Sportmonks non disponibile ora. Uso il fallback football-data.org.")
        await live_football_data_fallback(ctx)
        return

    fixtures = data.get("data") or []
    if not fixtures:
        await ctx.send("📭 Nessuna partita live in questo momento")
        return

    embed = discord.Embed(
        title="🔴 Live calcio",
        description="Dati live da Sportmonks • eventi minuto per minuto",
        color=COLOR_RED,
        timestamp=datetime.now(timezone.utc)
    )

    for fixture in fixtures[:8]:
        home, away = sportmonks_fixture_teams(fixture)
        score = sportmonks_fixture_score(fixture)
        minute = sportmonks_fixture_minute(fixture)
        state = sportmonks_fixture_state(fixture)
        league = sportmonks_fixture_league(fixture)
        events = sportmonks_fixture_events_summary(fixture)

        embed.add_field(
            name=f"⚽ {home} vs {away}",
            value=(
                f"🏆 {league}\n"
                f"📊 Risultato: **{score}** | ⏱️ {minute} | 📡 {state}\n"
                f"{events}"
            )[:1024],
            inline=False
        )

    embed.set_footer(text="Comando disponibile anche come !diretta • v2.0.1")
    await ctx.send(embed=embed)


async def live_football_data_fallback(ctx):
    c.execute("""
        SELECT id, question, yes_pool, no_pool, total_pool, match_key
        FROM markets
        WHERE active=1
    """)

    rows = c.fetchall()

    if not rows:
        await ctx.send("📭 Nessun mercato attivo")
        return

    embed = discord.Embed(
        title="🔴 Mercati live",
        description="Fallback football-data.org",
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
        await ctx.send("📭 Nessun mercato live in questo momento")
        return

    embed.set_footer(text="Comando disponibile anche come !diretta")
    await ctx.send(embed=embed)


def sportmonks_fixture_teams(fixture):
    participants = fixture.get("participants") or []
    home = "Casa"
    away = "Trasferta"
    for p in participants:
        meta = p.get("meta") or {}
        location = str(meta.get("location", "")).lower()
        name = p.get("name") or p.get("short_code") or "Squadra"
        if location == "home":
            home = name
        elif location == "away":
            away = name
    if home == "Casa" and len(participants) >= 1:
        home = participants[0].get("name") or home
    if away == "Trasferta" and len(participants) >= 2:
        away = participants[1].get("name") or away
    return home, away


def sportmonks_fixture_score(fixture):
    scores = fixture.get("scores") or []
    home_score = away_score = None
    for s in scores:
        score_data = s.get("score") or {}
        goals = score_data.get("goals")
        participant = str(s.get("description") or s.get("participant") or "").lower()
        if "home" in participant:
            home_score = goals
        elif "away" in participant:
            away_score = goals
    if home_score is None or away_score is None:
        return "N/D"
    return f"{home_score}-{away_score}"


def sportmonks_fixture_minute(fixture):
    minute = fixture.get("minute") or fixture.get("current_minute") or fixture.get("time")
    extra = fixture.get("extra_minute") or fixture.get("added_time")
    if minute and extra:
        return f"{minute}+{extra}'"
    if minute:
        return f"{minute}'"
    return "N/D"


def sportmonks_fixture_state(fixture):
    state = fixture.get("state") or {}
    if isinstance(state, dict):
        return state.get("name") or state.get("short_name") or fixture.get("status") or "LIVE"
    return str(state or fixture.get("status") or "LIVE")


def sportmonks_fixture_league(fixture):
    league = fixture.get("league") or {}
    if isinstance(league, dict):
        return league.get("name") or "Competizione"
    return "Competizione"


def sportmonks_event_label(event):
    type_data = event.get("type") or {}
    type_name = ""
    if isinstance(type_data, dict):
        type_name = (type_data.get("name") or type_data.get("code") or "").lower()
    type_name = type_name or str(event.get("type_id") or "").lower()

    if "goal" in type_name:
        return "⚽ Goal"
    if "red" in type_name:
        return "🟥 Espulsione"
    if "yellow" in type_name:
        return "🟨 Ammonizione"
    if "substitution" in type_name or "subst" in type_name:
        return "🔄 Sostituzione"
    if "lineup" in type_name:
        return "📋 Formazione"
    return "🟢 INFO"


def sportmonks_fixture_events_summary(fixture):
    events = fixture.get("events") or []
    if not events:
        return "📭 Nessun evento dettagliato disponibile."

    lines = []
    for ev in events[-5:]:
        minute = ev.get("minute") or ev.get("time") or ""
        player = ev.get("player_name") or ev.get("player", {}).get("name") if isinstance(ev.get("player"), dict) else ev.get("player_name")
        team = ev.get("participant_name") or ev.get("team_name") or ""
        label = sportmonks_event_label(ev)
        prefix = f"{minute}' " if minute else ""
        body = player or team or "Evento live"
        lines.append(f"{label} {prefix}{body}")

    return "\n".join(lines)

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
    "cosmetics": {"emoji": "🎨", "name": "Cosmetici", "desc": "Cornici, temi e personalizzazioni del profilo."},
    "cases": {"emoji": "📦", "name": "Casse", "desc": "Oggetti collezionabili e pacchetti cosmetici."},
    "bundles": {"emoji": "💎", "name": "Bundle", "desc": "Set estetici coordinati."},
    "limited": {"emoji": "⭐", "name": "Edizioni limitate", "desc": "Oggetti rari o stagionali."},
    "new": {"emoji": "🆕", "name": "Novità", "desc": "Ultimi arrivi nel Marketplace."},
}

SHOP_ITEMS = {
    "frame_green": {
        "emoji": "🟩", "name": "Cornice Green Trader", "category": "cosmetics", "slot": "frame",
        "price": 750, "rarity": "Comune", "new": True, "limited": False,
        "desc": "Cornice profilo verde in stile profitto positivo."
    },
    "frame_gold": {
        "emoji": "🟨", "name": "Cornice Gold Market", "category": "cosmetics", "slot": "frame",
        "price": 2500, "rarity": "Rara", "new": False, "limited": False,
        "desc": "Cornice dorata per profilo e schede trader."
    },
    "theme_dark_exchange": {
        "emoji": "🌑", "name": "Tema Dark Exchange", "category": "cosmetics", "slot": "theme",
        "price": 1500, "rarity": "Non comune", "new": True, "limited": False,
        "desc": "Tema estetico scuro ispirato a una piattaforma di trading."
    },
    "theme_stadium": {
        "emoji": "🏟️", "name": "Tema Stadium Lights", "category": "cosmetics", "slot": "theme",
        "price": 1800, "rarity": "Non comune", "new": False, "limited": False,
        "desc": "Tema profilo ispirato alle luci dello stadio."
    },
    "title_sharp_trader": {
        "emoji": "🎯", "name": "Titolo: Sharp Trader", "category": "cosmetics", "slot": "title",
        "price": 1200, "rarity": "Comune", "new": False, "limited": False,
        "desc": "Titolo cosmetico da mostrare nel profilo."
    },
    "title_market_maker": {
        "emoji": "📈", "name": "Titolo: Market Maker", "category": "cosmetics", "slot": "title",
        "price": 3000, "rarity": "Rara", "new": False, "limited": False,
        "desc": "Titolo premium per chi domina i mercati."
    },
    "badge_founder": {
        "emoji": "🏛️", "name": "Badge Founder", "category": "limited", "slot": "showcase",
        "price": 5000, "rarity": "Limitata", "new": False, "limited": True,
        "desc": "Badge cosmetico limitato per i primi sostenitori del bot."
    },
    "case_basic": {
        "emoji": "📦", "name": "Cassa Base", "category": "cases", "slot": None,
        "price": 1000, "rarity": "Comune", "new": True, "limited": False,
        "desc": "Cassa cosmetica collezionabile. In questa versione è un oggetto da inventario, non altera il gameplay."
    },
    "bundle_night_trader": {
        "emoji": "💎", "name": "Bundle Night Trader", "category": "bundles", "slot": "bundle",
        "price": 6500, "rarity": "Epica", "new": True, "limited": False,
        "desc": "Bundle estetico collezionabile per il profilo trader."
    },
}

EQUIPMENT_SLOTS = {
    "frame": "Cornice",
    "theme": "Tema",
    "title": "Titolo",
    "showcase": "Badge vetrina",
    "bundle": "Bundle",
}


def get_shop_item(item_id):
    return SHOP_ITEMS.get(str(item_id).lower().strip())


def user_owns_item(user_id, item_id):
    c.execute("SELECT quantity FROM user_inventory WHERE user_id=? AND item_id=?", (str(user_id), str(item_id)))
    row = c.fetchone()
    return bool(row and (row[0] or 0) > 0)


def get_equipped_items(user_id):
    c.execute("SELECT slot, item_id FROM user_equipment WHERE user_id=?", (str(user_id),))
    return {slot: item_id for slot, item_id in c.fetchall()}


def get_equipped_items_text(user_id):
    equipped = get_equipped_items(user_id)
    if not equipped:
        return "Nessun cosmetico equipaggiato."

    lines = []
    for slot, label in EQUIPMENT_SLOTS.items():
        item_id = equipped.get(slot)
        if not item_id:
            continue
        item = SHOP_ITEMS.get(item_id)
        if not item:
            continue
        lines.append(f"**{label}:** {item['emoji']} {item['name']}")

    return "\n".join(lines) if lines else "Nessun cosmetico equipaggiato."


def get_cosmetic_style(user_id):
    """Trasforma gli oggetti equipaggiati in effetti grafici reali sugli embed."""
    equipped = get_equipped_items(user_id)
    style = {
        "color": None,
        "title_prefix": "",
        "description_prefix": "",
        "footer_suffix": "",
        "author_suffix": "",
        "showcase": "",
    }

    frame_id = equipped.get("frame")
    theme_id = equipped.get("theme")
    title_id = equipped.get("title")
    showcase_id = equipped.get("showcase")
    bundle_id = equipped.get("bundle")

    if frame_id == "frame_green":
        style["color"] = COLOR_GREEN
        style["title_prefix"] += "🟩 "
        style["footer_suffix"] += " • Cornice Green Trader"
    elif frame_id == "frame_gold":
        style["color"] = COLOR_GOLD
        style["title_prefix"] += "🟨 "
        style["footer_suffix"] += " • Cornice Gold Market"

    if theme_id == "theme_dark_exchange":
        style["color"] = style["color"] or COLOR_PURPLE
        style["description_prefix"] += "🌑 **Tema Dark Exchange attivo**\n"
        style["footer_suffix"] += " • Tema Dark Exchange"
    elif theme_id == "theme_stadium":
        style["color"] = style["color"] or COLOR_CYAN
        style["description_prefix"] += "🏟️ **Tema Stadium Lights attivo**\n"
        style["footer_suffix"] += " • Tema Stadium Lights"

    if title_id and title_id in SHOP_ITEMS:
        item = SHOP_ITEMS[title_id]
        style["author_suffix"] = f" • {item['emoji']} {item['name'].replace('Titolo: ', '')}"
        style["showcase"] += f"{item['emoji']} **{item['name']}**\n"

    if showcase_id and showcase_id in SHOP_ITEMS:
        item = SHOP_ITEMS[showcase_id]
        style["showcase"] += f"{item['emoji']} **{item['name']}**\n"

    if bundle_id == "bundle_night_trader":
        style["color"] = 0x111827
        style["description_prefix"] += "💎 **Bundle Night Trader equipaggiato**\n"
        style["footer_suffix"] += " • Bundle Night Trader"

    return style


def apply_cosmetics_to_embed(embed, user_id, member=None, base_footer=None):
    """Applica colore, prefissi, vetrina e footer cosmetici a un embed esistente."""
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

    if style["showcase"]:
        value = style["showcase"].strip()
        if value:
            embed.add_field(name="🎨 Vetrina cosmetica", value=value[:1024], inline=False)

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
            description="Spendi i crediti in oggetti cosmetici e collezionabili. Nessun oggetto dà vantaggi nel trading.",
            color=COLOR_PURPLE
        )
        for key, data in SHOP_CATEGORIES.items():
            count = sum(1 for item in SHOP_ITEMS.values() if item["category"] == key or (key == "new" and item.get("new")) or (key == "limited" and item.get("limited")))
            embed.add_field(
                name=f"{data['emoji']} {data['name']}",
                value=f"{data['desc']}\n`!shop {key}` • {count} oggetti",
                inline=False
            )
        embed.set_footer(text="Comandi: !buyitem item_id • !inventory • !equip item_id")
        await ctx.send(embed=embed)
        return

    category = category.lower().strip()
    if category not in SHOP_CATEGORIES:
        await ctx.send("❌ Categoria non valida. Usa `!shop` per vedere le categorie disponibili.")
        return

    if category == "new":
        items = [(item_id, item) for item_id, item in SHOP_ITEMS.items() if item.get("new")]
    elif category == "limited":
        items = [(item_id, item) for item_id, item in SHOP_ITEMS.items() if item.get("limited")]
    else:
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
        await ctx.send("❌ Devi indicare l'ID oggetto. Esempio: `!buyitem frame_green`")
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
    embed.add_field(name="💰 Prezzo", value=f"{price} crediti", inline=True)
    embed.add_field(name="💳 Saldo residuo", value=str(get_user(user_id)), inline=True)
    if item.get("slot"):
        embed.add_field(name="🎛️ Equipaggia", value=f"`!equip {item_id}`", inline=False)
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
        lines = []
        for item_id, quantity, _ in rows[:20]:
            item = SHOP_ITEMS.get(item_id)
            if not item:
                continue
            qty_text = f" x{quantity}" if quantity and quantity > 1 else ""
            slot = EQUIPMENT_SLOTS.get(item.get("slot"), "Inventario") if item.get("slot") else "Inventario"
            lines.append(f"`{item_id}` — {item['emoji']} **{item['name']}**{qty_text} • {slot}")
        embed.add_field(name="📦 Oggetti", value="\n".join(lines) if lines else "Nessun oggetto valido.", inline=False)

    embed.set_footer(text="Equipaggia con !equip item_id • Rimuovi con !unequip slot")
    await ctx.send(embed=embed)


@bot.command(name="equip", aliases=["equipaggia"])
async def equip(ctx, item_id: str = None):
    user_id = str(ctx.author.id)
    if not item_id:
        await ctx.send("❌ Devi indicare l'ID oggetto. Esempio: `!equip frame_green`")
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
        await ctx.send("❌ Devi indicare lo slot. Slot disponibili: `frame`, `theme`, `title`, `showcase`, `bundle`.")
        return

    slot = slot.lower().strip()
    if slot not in EQUIPMENT_SLOTS:
        await ctx.send("❌ Slot non valido. Slot disponibili: `frame`, `theme`, `title`, `showcase`, `bundle`.")
        return

    c.execute("DELETE FROM user_equipment WHERE user_id=? AND slot=?", (user_id, slot))
    removed = c.rowcount
    conn.commit()

    if removed <= 0:
        await ctx.send("📭 Non avevi nulla equipaggiato in questo slot.")
        return

    await ctx.send(f"✅ Slot **{EQUIPMENT_SLOTS[slot]}** svuotato.")


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
            "`!shop cosmetics|cases|bundles|limited|new`\n"
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


def sportmonks_get(path, params=None):
    """Wrapper Sportmonks v2.0.1: non blocca il bot se il token manca o l'API risponde male."""
    if not SPORTMONKS_API_TOKEN:
        return None, {"error": "SPORTMONKS_API_TOKEN mancante"}

    clean_path = str(path).lstrip("/")
    url = f"{SPORTMONKS_BASE_URL.rstrip('/')}/{clean_path}"
    final_params = dict(params or {})
    final_params.setdefault("api_token", SPORTMONKS_API_TOKEN)

    return request_json(url, params=final_params, timeout=12)


def safe_int(value):
    try:
        return int(value)
    except Exception:
        return None


def sportmonks_live_payload():
    """Recupera le partite live evitando l'errore 422 fixtureId non intero."""
    include = "participants;scores;events.type;state;league"
    status, data = sportmonks_get("fixtures/live", params={"include": include})

    # Alcuni piani/endpoints Sportmonks rispondono 422 chiedendo fixtureId.
    # In quel caso usiamo l'endpoint live score corretto e non facciamo crashare il loop.
    if status == 422 and "fixture" in str(data).lower():
        status, data = sportmonks_get("livescores/inplay", params={"include": include})

    return status, data


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
            "title": a.get("title", "Notizia calcistica"),
            "description": a.get("description") or "",
            "url": a.get("url") or "",
            "published_at": a.get("publishedAt") or ""
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
        title = item.get("title") or item.get("headline") or "Aggiornamento calcio"
        url = item.get("url") or item.get("link") or ""
        external_id = item.get("id") or url or title
        articles.append({
            "source": "API-Football",
            "external_id": external_id,
            "title": title,
            "description": item.get("description") or item.get("summary") or "",
            "url": url,
            "published_at": item.get("published_at") or item.get("date") or ""
        })

    return articles


async def post_news_article(channel, article):
    embed = discord.Embed(
        title=f"📰 {article['title'][:250]}",
        description=(article.get("description") or "Nuovo aggiornamento disponibile.")[:1000],
        color=COLOR_CYAN,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="Fonte", value=article.get("source", "News"), inline=True)
    if article.get("published_at"):
        embed.add_field(name="Pubblicata", value=str(article["published_at"])[:80], inline=True)
    if article.get("url"):
        embed.add_field(name="Link", value=article["url"][:1024], inline=False)
    if article.get("relevance_score") is not None:
        embed.add_field(name="Rilevanza calcio", value=f"{article.get('relevance_score')} punti", inline=True)
    embed.set_footer(text="Gazzetta • filtro calcio mondiale v2.0.1")

    await channel.send(embed=embed)


async def market_pulse_news_loop():
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            channel = await get_discord_channel_safe(GAZZETTA_CHANNEL_ID)
            if not channel:
                print(f"[GAZZETTA] Canale {GAZZETTA_CHANNEL_ID} non trovato.")
            else:
                articles = fetch_api_football_news() + fetch_gnews_sports()

                for article in articles:
                    source = article.get("source", "news")
                    external_id = article.get("external_id")
                    if not external_id or is_news_already_seen(source, external_id):
                        continue

                    await post_news_article(channel, article)
                    mark_news_seen(source, external_id)
                    await asyncio.sleep(2)

        except Exception as e:
            print("[GAZZETTA NEWS] Errore loop news:", e)

        await asyncio.sleep(NEWS_LOOP_MINUTES * 60)


async def gazzetta_live_loop():
    """Pubblica su #gazzetta gli eventi live Sportmonks: goal, cartellini, formazioni e sostituzioni."""
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            if not SPORTMONKS_API_TOKEN:
                await asyncio.sleep(GAZZETTA_LIVE_LOOP_SECONDS)
                continue

            channel = await get_discord_channel_safe(GAZZETTA_CHANNEL_ID)
            if not channel:
                await asyncio.sleep(GAZZETTA_LIVE_LOOP_SECONDS)
                continue

            status, data = sportmonks_live_payload()

            if status != 200:
                print(f"[GAZZETTA LIVE] Sportmonks status {status}: {data}")
                await asyncio.sleep(GAZZETTA_LIVE_LOOP_SECONDS)
                continue

            for fixture in data.get("data", []) or []:
                home, away = sportmonks_fixture_teams(fixture)
                score = sportmonks_fixture_score(fixture)
                league = sportmonks_fixture_league(fixture)
                fixture_id = safe_int(fixture.get("id"))
                if fixture_id is None:
                    # Fix Gazzetta Live/Sportmonks: niente richieste/eventi con fixtureId vuoto o non numerico.
                    continue

                for ev in fixture.get("events", []) or []:
                    label = sportmonks_event_label(ev)
                    # Pubblica solo eventi davvero utili per il canale Gazzetta.
                    if label not in ["⚽ Goal", "🟥 Espulsione", "🟨 Ammonizione", "🔄 Sostituzione", "📋 Formazione"]:
                        continue

                    event_id = ev.get("id") or f"{fixture_id}-{ev.get('minute')}-{label}-{ev.get('player_name') or ev.get('participant_name')}"
                    if is_news_already_seen("SportmonksLive", event_id):
                        continue

                    minute = ev.get("minute") or ev.get("time") or ""
                    player = ev.get("player_name") or ""
                    team = ev.get("participant_name") or ev.get("team_name") or ""

                    embed = discord.Embed(
                        title=f"{label} | {home} vs {away}",
                        description=f"🏆 {league}\n📊 Risultato: **{score}**",
                        color=COLOR_RED if "Espulsione" in label else COLOR_GREEN if "Goal" in label else COLOR_CYAN,
                        timestamp=datetime.now(timezone.utc)
                    )
                    if minute:
                        embed.add_field(name="⏱️ Minuto", value=f"{minute}'", inline=True)
                    if player:
                        embed.add_field(name="👤 Giocatore", value=player, inline=True)
                    if team:
                        embed.add_field(name="🏟️ Squadra", value=team, inline=True)
                    embed.set_footer(text="Gazzetta Live • Sportmonks v2.0.1")

                    await channel.send(embed=embed)
                    mark_news_seen("SportmonksLive", event_id)
                    await asyncio.sleep(1)

        except Exception as e:
            print("[GAZZETTA LIVE] Errore loop:", e)

        await asyncio.sleep(GAZZETTA_LIVE_LOOP_SECONDS)


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
    bot.loop.create_task(gazzetta_live_loop())
    bot.loop.create_task(personal_alert_checker_loop())


# =========================
# RUN
# =========================
bot.run(token)
