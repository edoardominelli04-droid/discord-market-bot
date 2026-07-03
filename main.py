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



# =========================
# PROFILE CARD PNG TEMPLATE STANDARD
# =========================
PROFILE_CARD_STANDARD_TEMPLATE_B64 = """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IIAAAggggAACCCCAAAIIIIAAAggggEBUAmwBEJUk9XSsgKXft6+gLEx3bDtpGAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIINCMQPs3R2+m9bwXAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBAIBAgD4ICCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIILAJBAgA2AQXkS4ggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCBAAACfAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBDaBAAEAm+Ai0gUEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQIAOAzgAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAwCYQIABgE1xEuoAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAABAHwGEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQ2AQCBABsgotIFxBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEECAAgM8AAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACm0CAAIBNcBHpAgIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAgQA8BlAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEBgEwgQALAJLiJdQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAgAAAPgMIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAghsAgECADbBRaQLCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIEADAZwABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIFNIEAAwCa4iHQBAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABAgD4DCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIILAJBAgA2AQXkS4ggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCBAAACfAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBDaBAAEAm+Ai0gUEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQIAOAzgAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAwCYQIABgE1xEuoAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAABAHwGEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQ2AQCBABsgotIFxBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEECAAgM8AAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACm0CAAIBNcBHpAgIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAgQA8BlAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEBgEwgQALAJLiJdQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAgAAAPgMIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAghsAgECADbBRaQLCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIEADAZwABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIFNIEAAwCa4iHQBAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABAgD4DCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIILAJBAgA2AQXkS4ggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCBAAACfAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBDaBAAEAm+Ai0gUEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQIAOAzgAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAwCYQIABgE1xEuoAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggEBioxHE4nFJpzOSTKUlro8TyZTE4jHxvLh+bbTe0F4EEEAAAQQQQKDzBKp+VSqlslQqFSmXClIsFKRUKkpVf97KJRaLSSqd1nFoRuKJi+PQWFzseY+B6Fb+aNB3BBBAAAEEEIhIwPd9KZdLwTi0UixKsajjUP2ycelWLjbWTOo4NKX3RBPxxMX7oYxDt/Jngr4jgAACCCCAQLQCvlZXKdk4tKz3Q0vBGNTGopVyOdoTrVNtGyIAwAa5mWxOunr7JJvr0hus3GRdp88Hp0EAAQQQQACBrSqQebfjdiPWvgoL8zI9Na7fF4Kf3z1icz9KZ2wc2iu5rh4m+zf3paZ3CCCAAAIIINABAmnJXmqFjUFFdByaz8vM1IQszM+JX61een2zP7AJ/66e3uArpoGnizGnrIDa7Ned/iGAAAIIIIBAmwR07LVUFsehEgQCzExNyvzstFQ30DjU6xo8ZCPpziw6qk1nsjK4bWew2qozG0mrEEAAAQQQQACBrSWwsDAnU+OjUtQbsUuD4U0noPdV7YarjUNtPEpBAAEEEEAAAQQQaL9AobCg49AxyVsgQBAc0P42taIFlvm0f2i7BqB2t6J66kQAAQQQQAABBBBwFLCsVNOT4xoIMLMhAgE6OgAg29Ul23buDVZaLb8ONsC3KAv77muKWg0E1v93bhzD8rbzGAEEEEAAAQQQ6HQBT/R/wcIi/a7p7WuluLd0WOPDF2R+bqbTu9NQ+9LZrAzt2C1J3W5qeVkaf1ary8ehdgRj0eVOPEYAAQQQQAABBBoRsHHo4v8vjkN1UGrj0eWlWq3IxOiIzE5PLn960zy2yf/B7TuDbKjLO7U0DvV1HFq14Ae7LxocwDh0uROPEUAAAQQQQACBRgQuH4fqT5qN3u6JLi82Nz01MSbT+tXppaO3AOjtH7qEa4PcYB9a3QesWq5IRQf7Bh2kWwgCARjsdvqHjfYhgAACCCCAwMYQsO2Xlr5i8bjENd1oPKF7jeqXfbcS171He/oHNm0AQFdPn07+Jy9dMNvvq6xfFvhgY1JLPVvRr+DGq92ApSCAAAIIIIAAAgg0LbA0BrXvNg61m67Lx6F2Y9ZS4fcNbtu0AQC2/enyDFRL90Mrej/Ugh+qOha9NA41ccaiTX/uqAABBBBAAAEEELDxp0WixmI64rQx6MX7oUtj0WB8qs/39g8SANDsx8WiK5aK3XSdn5tdvOHKwHaJhe8IIIAAAggggEDkAourixYnte2GY0nPYINcm/TPaYamxMWJcbspu1lL7OKg3/pnAadzszoO1RuuW2nP2c16bekXAggggAACCHSuwMpxqLV0KRggm81d2iI0vonHodZf+1oqc5ZmVsfkwSKopSf5jgACCCCAAAIIIBCpgI1DLcOnDrvE/lO2O6JFvR+qk/4WnJnRbKFWNso4tKMzAASSF/9j8LbqioIAAggggAACCCCw/gKLYzHNxGSr3rdYWer7Fus23UUAAQQQQAABBDpCwMZitjDIAlO3YimXLByXggACCCCAAAIIILDuAjYOtWAAzU4vshgAsO5taPCE7y6xb7AC3oYAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD91x+/QpEAAEAASURBVIAWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC7RcgAKD914AWIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggg0LQAAQBNE1IBAggggAACCCCA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SIAESIAESIAESIAESIAESIAESIAESGAWEGAAwCx4CBwCCZAACZAACZAACZAACZAACZAACZAACZAACZAACZAACZAACZAACZAACZAACVRLgAEA1RLk/SRAAiRAAiRAAiRAAiRAAiRAAiRAAiRAAiRAAiRAAiRAAiRAAiRAAiRAAiQwCwgwAGAWPAQOgQRIgARIgARIgARIgARIgARIgARIgARIgARIgARIgARIgARIgARIgARIgASqJcAAgGoJ8n4SIAESIAESIAESIAESIAESIAESIAESIAESIAESIAESIAESIAESIAESIAESmAUEGAAwCx4Ch0ACJEACJEACJEACJEACJEACJEACJEACJEACJEACJEACJEACJEACJEACJEAC1RJgAEC1BHk/CZAACZAACZAACZAACZAACZAACZAACZAACZAACZAACZAACZAACZAACZAACcwCAgwAmAUPgUMgARIgARIgARIgARIgARIgARIgARIgARIgARIgARIgARIgARIgARIgARIggWoJMACgWoK8nwRIgARIgARIgARIgARIgARIgARIgARIgARIgARIgARIgARIgARIgARIgARmAQEGAMyCh8AhkAAJkAAJkAAJkAAJkAAJkAAJkAAJkAAJkAAJkAAJkAAJkAAJkAAJkAAJkEC1BBgAUC1B3k8CJEACJEACJEACJEACJEACJEACJEACJEACJEACJEACJEACJEACJEACJEACs4AAAwBmwUPgEEiABEiABEiABEiABEiABEiABEiABEiABEiABEiABEiABEiABEiABEiABEigWgIMAKiWIO8nARIgARIgARIgARIgARIgARIgARIgARIgARIgARIgARIgARIgARIgARIggVlAgAEAs+AhcAgkQAIkQAIkQAIkQAIkQAIkQAIkQAIkQAIkQAIkQAIkQAIkQAIkQAIkQAIkUC0BBgBUS5D3kwAJkAAJkAAJkAAJkAAJkAAJkAAJkAAJkAAJkAAJkAAJkAAJkAAJkAAJkMAsIMAAgFnwEDgEEiABEiABEiABEiABEiABEiABEiABEiABEiABEiABEiABEiABEiABEiABEqiWAAMAqiXI+0mABEiABEiABEiABEiABEiABEiABEiABEiABEiABEiABEiABEiABEiABEhgFhBgAMAseAgcAgmQAAmQAAmQAAmQAAmQAAmQAAmQ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EEAAAQQQQAABBBBAAAEEEEAAAQQQiFyABIDIibkAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC0QuQABC9MVdAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAgcgESACIn5gIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAghEL0ACQPTGXAEBBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIHIBUgAiJyYCyCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIBC9AAkA0RtzBQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBCIXIAEgcmIugAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAQPQCJABEb8wVEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQiFyABIDIibkAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC0QuQABC9MVdAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAgcgESACIn5gIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAghEL0ACQPTGXAEBBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIHIBUgAiJyYCyCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIBC9AAkA0RtzBQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBCIXIAEgcmIugAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAQPQCJABEb8wVEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQiFyABIDIibkAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC0QuQABC9MVdAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAgcgESACIn5gIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAghEL0ACQPTGXAEBBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIHIBUgAiJyYCyCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIBC9AAkA0RtzBQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBCIXIAEgcmIugAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAQPQCJABEb8wVEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQiFyABIDIibkAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC0QuQABC9MVdAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAgcgESACIn5gIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAghEL0ACQPTGXAEBBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIHIBUgAiJyYCyCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIBC9AAkA0RtzBQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBCIXIAEgcmIugAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAQPQCJABEb8wVEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQiFyABIDIibkAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAAC0QuQABC9MVdAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAgcgESACIn5gIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAghEL0ACQPTGXAEBBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIHIBUgAiJyYCyCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIBC9QF70lwj3Cv1yclxeXr79y3M5ublH//XLcdpOQwABBBBAAAEEEOi5wJEjR1xba6tra2tzra0trrW52bXY1yP2c19u/fr1c3n5ikPzg9gzNzcv+Jpj253+0RBAAAEEEEAAAQR6JmBxaOsLcWibxZ8tLc2utaUliEt7duLMPlpx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09rE9eE4TUkAeWk0qOfzvH5ditUib5qr0pNW9y/2RUNzfU40L11X0SKFrVbN6sHcdTWPRRMKhOavzTb596X2CHO9epbagzEQQCB+BEgAyObvggoA2QzK7hBAAAEEEEAAgSwKkACQRUA+jgACCCCAAAIIIJApARIAMsXGhxBAAAEEEEAAAQSyKJAXEwDyZfGa+TgCCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIxIEACQBx8CVwCggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCGRVgASArAryeQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBOJAgASAOPgSOAUEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQSyKkACQFYF+TwCCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAJxIEACQBx8CZwCAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACWRUgASCrgnweAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQACBOBAgASAOvgROAQEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAgawKkACQVUE+jwACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAQBwIkAAQB18Cp4AAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggEBWBUgAyKogn0cAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQCAOBEgAiIMvgVNAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAgqwIkAGRVkM8jgAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCAQBwIkAMTBl8ApIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAgggkFUBEgCyKsjnEUAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQiAMBEgDi4EvgFBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEMiqAAkAWRXk8wgggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCMSBAAkAcfAlcAoIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAghkVYAEgKwK8nkEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQTiQIAEgDj4EjgFBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEsipAAkBWBfk8AggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACcSBAAkAcfAmcAgIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAlkVIAEgq4J8HgEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAgTgQIAEgDr4ETgEBBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIGsCpAAkFVBPo8AAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggEAcCJAAEAdfAqeAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIBAVgVIAMiqIJ9HAAEEEEAAAQQQQAABBBBAYD8J5M+f32rWqGaNG9W3woUL5cpZHNGkodWvVydXjpWTBylWrKg1PqyetTiyaU4ehn0jgAACCCCAAAIIIIAAAgggkKsCBXL1aBwMAQQQyKJAgQIF7NDaNbK4l+Qf37lzly1fuco2bdqc/I089KxypQpWskTx8BmvXL3G1q5NDD/nAQIIIIAAAgggcKAKFCiQ3ypWKG/F/WZuNGPnrl22ffsO27x5iyWu32C7/HleHcWLF7OXnv6vnXFqp+AS+g4cYvc99LQtW74yRy6pod8sf//1Z61e3dq2detW6/Z5D3vtrW62LnF9jhwvJ3fauGF9e/qx+6zV0c1t9+7d1m/gULv/0eds2bIVOXlY9o0AAggggAACCMQkoGRPxXylS5WwalWrWMujjgh/ftu27bZ8xSr7e+r0IK5dvWataZ6TkbHAobVrmv6O0Ni+Y4ctWbI8+J3xJ9kCAQQQyBsCJADkje+Js0QAgb0C5cuVsYG/fWP5Djkk20yW+iTffx5+xvoOGJJt+8ztHT1072123tldw4d98rnX7K33Pg0/5wECCCCAAAIIIHCgCpQtW8aeeuQeO6Vz+wwvcc+ePbZhw0Zb7BN802bOtv5+03fM+L9s/oJFGX42Hjfo1L5N+Oa/zq9T+xOsXZvW9vV3P+XI6V592XnBzX/tvHDhwnb+2ae64TAbNmJMjhwvp3aaL18+u/C804OV/4f43xWaWG/WtLG1bnmk/fBTn5w6LPtFAAEEEEAAAQRiEihbprS1ObaltW1zjMd4x3gCQGVT7JJyrF2XaH/9Pd2+/f5n+3PUOFuydHmQ4JhyO57vE+jx+dtWtUql4IWZs+fZVdffZXPmLdi3AY8QQACBPC5AAkAe/wI5fQQQQAABBBBAAAEEEEAAgegENGFasmSJ4KdRw3rWucMJwSTpF1//YP0HDbMdvvonLw3dhE858u9dyZTy9ex4Xr5s2WS70Wq0QoUKJnstLzzRvwcF/KZ/5AR6QkIBK5KKZ164Hs4RAQQQQAABBA48gYoVytltN15tZ5/Rxcp5wmt6o0zpUtb2+FbWovnhQUz70Wff2Njxk1KtBqBtT/IkUsVCGstWrPRt/wqSZNM7Bu8hgAACCOQtARIA8tb3xdkigAACCCCAAAIIIIAAAghkk4B6wHf0CdC6dWpZKU8MyKmV89l0uv/YTf9BQ+2PISOs3Qmtg/dGjB5vI3zVV06NT7v3tFYtm1v5cmVNJWd//LmvTZsxO6cOl2P7VduH3r/2t6O9hG7TJg2DFXLjJvxto8ZOzLFjsmMEEEAAAQQQQCBagdKlS9pjD90ZVLgqXKhQso+tWrXGVOpfo3Spkla+fNmgmpGeK7bt2qVDsLL9wceet8lTppsqYEUOtRG9/66bgmpOen3on6NtztwFJABEIvEYAQQQOAAESAA4AL5ELgGBg0lAQe4Fl91k9s9qVwFDQoEED3Tb2+UXnxNm0UToi//3bvh5ygfqjTV7zvyUL/McAQQQQAABBBBAII8KvPz6+zZ85Nh/nL1u8tevd6id0bWjqQd8aNSuVd2uuux8mzpjlk36a2ro5bj/vWLlarvz/iesSaMGprL2U6fP8vYGy3LsvIeNGG2nnnu1HX1kU1u5eo1NnznHVvo55MUxetxEu+mOh4LS/+vXr7dJk6eHJ9Pz4vVwzggggAACCCBw4Ajcd+dNdtrJHU0VikJD1ao+/fI7T76cZTt37ApeVuWnhvXr2pmnd7ZzzzwleE197Y/ySgAXnX+6PfXsPNuydWtoF+H31VqgSJGkSlLFPWkgO1utJjsYTxBAAAEE9pvAvv8F2W+nwIERQACB6AV2+mqd9HqMFiyYYIc1ODTZDjdt2mzD/sxbfUmTXQBPEEAAAQQQQAABBGISmDVnQdrxX5+B9uEnX9ltN11t11x+QbBSSqXgD2/cwM7s2smm+U307dvzTiuApctWmH5yYyhxdsHCxcFPbhwvJ4+ha9FqN/0wEEAAAQQQQACBeBE4rP6h1qHtceGb/4pLv/j6e1/c9J6tWbvuH6e5cNES6ztwiC3y37fd/K/gZr4SQy869wz74OOvbS597f9hxgsIIIDAwSCQ72C4SK4RAQQQyKpAfu+LVbRIEVOfLPWNVTZtekOJCCq7FfpJSEhIb/N039OEtD5ftGiR8P4UyGfHyMl9Z8f5sQ8EEEAAAQQQQCAnBDZu3GQvv/ae/eRl4Hft2h0cokCBAtbiyCOCdgAZHVMxlMqxhmI9/c6fP2vxmY4fub9ChQom61Gf0TnF+/uKX7XSLHSNKcvZZuX8g30X3rfvrH4XWTkXPosAAggggAACCGRFoM1xLa1MmVLhXfw9dbp95m2YUrv5H97IH7zy5of2Y+/fwy9pHvGUzu3Dz3PqgY4TzJeWKB5uRZDWsTS/GhkPJnj8m5URmq8NxZfad3bNmWblvPgsAgggEA8CWfsvbDxcAeeAAAIIZJNAh3bHWbmyZYK9bfBJ4fETJ9vyFavs0Do1rWWLZlazWlWr5H2y1q/fYN2//dFmzpqb7MgKNqtXq2L1Dq1lNapXtbIRwfrKVWuDlVKz5swLyrJu3bot2WfTelK1SqWgPG3tmtWtbNnS4cSD2b5SacLEv23OvIW2Y0fmVqhVqVwx6Hlaw8+5XLky4X3PX7jEli9faTqGsoh37tyZ1unxOgIIIIAAAgggkGcF1MP+y29+sDNP62RF8ieVQK1RvYpVqlghKKWf2oVpUlGrsuodWjvorVq8eNHwZgsWLfW2UvNshseIq1cn9WUNv5nGAyWNVqtSOYg3a3m8V6lieb/pn7Tx+g2bbP6CxV5mf7bN8FL7qQ1NcKr9VRG/+a2R6HHqH0NH2rZtSbFmieLF7Mhmhwf7Te3zGb22afNmU7lZWWmoXOxJJx4f/tiiJUtt4qSptnnLlvBrKR+oz2yTxodZxfLlTPFn4cIFg002+PXNnD0vWJU236sKpBcfq12D2hyEhto7qNVBwYIFg8oNDbytg/ZdpEhSj1x9F/PmL7Kp02amWda/SuVKXh63SZDkq/2u9hV1I711mKqHMRBAAAEEEEAAgf0lUNVjlEIe42js3r3b5npMo5gpo7Fjx07r2es3q1a1cnjTUFJk6dIl7diWR1lxjw01d6kb56GhGEqJAqu8vZPGVo8j1U411Oap7fHHhGNJvTfR22WpIpRaaB15RBNvr1XHKlYob5s9buz2eQ+P7RaGdh381rFq1qjmMXQdq1ypos+9ljYlumqonZXass6YpfnSpcFr0fxD86V1atewOrVq+j4reEyYdJtrm1dLmO9eC3xuc/bc+UHSxJ49e6LZZYbbHN/66CD+D224ZctWGzB4uF932nFwaFt+I4AAAvtDgASA/aHOMRFAIC4F7rz1Wjv6qCOCfQTtRQAAQABJREFUc1N5rP8+8aJPKB4W9INV9m1olZISADTpGEoA0AowJQmcf/ap1uro5tbUP6OAOuVQpu5ff0+zQYNH+Gqzfhn2Zz2pfRu75PwzfdK2iQfS5ZIF59u2b7cRo8bZxx5Ya3+xDPX2OvXkk6xThxOCxAZN5EZWNNjtgfFqD/onT5lhvX1V3I+/9DWtkmMggAACCCCAAAIHmsCESVNszZp14YnS8uXKWulSJVO9zEYN69l5Z51qxx97tDU+rF5QoSlyQ00uzvEYcvTYSfZNz5+C3+klUqqq1BneckA38HVzu0L5sv9Y8a+b5JM8fvxjyJ/28Rff2oYNGyMPGVQdeOrhe4IkVb0x1dsXjJswOZwAoMnYW66/wtq2OSbZ56J9osnTUWMm+v6SJoRr+eTtay8+Hv54798G2KNPvZRqAoCSY7t26WCdPeZUjJwy5pSXEham+E36/gOHBfHxosVLLbVJ2pM7nWj33nFD+LjX3HyvrXeLqy493844taM1bFDX49l90xvaxwJPZB0ybFRQMnfS5GnBBHp4B/5ALR+e+O/d4Ylcud18539JAIhE4jECCCCAAAII5LqAEkTz5dubEepHVxKAWcY3sbXd0BGjbeHiJeFz3rg3sVGLfx6+//bgpnn4zb0PlGj5yAO3h1/WTfmb7ngonAAQGUsqSeDR/71iSjK967ZrraPPXSohMzT6DxqeLAFAC44Ux53S+URr0aypKREh5ViybLkvcpric5D97Ne+g9JNCtWxtIDrgnNOtUaH1fcFWMmTGbRvJZUquVRJDNrn0OGjUx4y5uddOrazRx+8wxMOagSfVZJst896BIm3Me+MDyCAAAK5JLDvL+RcOiCHQQABBPKKQNMmDa2Dr3A6+sim6ZaPauwTto96EN3iqKbhFUSpXaMmPdse39qOOLyR1atX215766MgIzW1bc8+vYvde+eN4cAy5TbKBG5zbKtgwnLnjl3JkgNSbhv5vHixYnbz9ZfbpReeFWTnRr4XepzPExoq+Aqt9m2PDSZGa9WsZs+9/PY/Jk1D2/MbAQQQQAABBBDIqwKqpBR5U10TrgkJyf9M1qqldn4D/Wa/kd7Kq0Kl1dpJSaF169QyVW5S/PjuR194IsDPtt0TN1OOIt5aSjefO7Q7Noi7Ur4fel6iRDE7vnULa9H88GDl1JPP/l9w4zv0frz+1s3/m669zC676JzwirGU5yovJVscd0wLa+ITz8cec5T95+FnbMnS5Sk3TfX5PbdfHyTLppZ4q30rWaHquacHyR0PPfa8r55Lvhot1Z3yIgIIIIAAAgggsJ8FVnklqe2+ml8xp6o9qfpUk0aH+cr7KRmemValT5sxO8PtsrKBboJ39YoBnU9qmywBM+U+lVir+FkLprTqX/FZakMVD6p4ZYCjPN49zJM6P/r066AyQMptlTx7923X2SmePKuEhrRG4cKFArM6XqGgjSfuPvLkSzbgj+FpbZ7h6x3bn2BPPnx3UO1VG+vm//vdugc/GzYmT87NcGdsgAACCOSiQPKZjVw8MIdCAAEE4lkgacVSey+/3yDdm/8KXl/3VVAKxiN7TE2dPtvGjJ9kW7wMVAVfva+qAHW8SkB+D9zVF+usUzt7SdJZQQ+vlJPC7dq0trv/ff0/bv6vXZdoY8dP9uA6XzBRrJViKj97x63X+KqrrRlyqifXDddcYv+6/AIrFbGyTZm9f/093VdJLQ4mSrVflZ/VUCLA9Vdf4m0AdtkLr76T4THYAAEEEEAAAQQQyGsCkTeQt3vZ0B0p2h81blTf7vHV5808iTMU72mFlVara4JVpUY1EaoV5RpKGKhXt7Y9+sAdtszbKvUbOPQfJNdceaGdc+bJFtn3dJrHj+N9YnfWrDlW0WOxFs2bBpUB1HZAE5lneYKoyt6/6v1dc2ssW77CtmzNOM6MPJ+intxw3VUX2zVXXpSsmoKSLRRzLvYb/CU8QUAVFdRuQUOxafu2x9lHb71g5152Y4ar8Dt1aBskT+i7U7lblaFdl7g+uNmf1EYhaYJZyRwnHNfKLr3oLHvx1feCkraR58pjBBBAAAEEEEAg3gRU0WnTpk1WzOfxNLTSXXN/jz/9qrc4ylxC4+bNW73S5/SgJL4SURs22DePudGPpapPSh7QUAXTdT4HmdpQxaWTO7Uzta6KrL6UcluV+P/3TVfb5RefE8Sxofe179FjJ3qLpnVB6f5jWh4ZXKfmV1XK/4Z/XWqrVq0J5ktV/TRy/PvGqzy59GzT/GZoqCLUn16lVeevUa9uLTvK218ptlS1ACXnPvP4f+y8S2/0ygjRtxgI7f+kE9vYEw/fFb75L6OPfeX/e92+tLVrUzcKfZbfCCCAwP4WIAFgf38DHB8BBOJSQOVS9aMJxR9/6efB3Tf2p5fc1yhZonh4Yvg/d93kgXi98DUo+Lv3of/Zz30GhF/TA2W9vvzcI9bRKwooqFWCwakndwh6qkYG76U9OeCKS861uofWCn9ewfGnX/a0Dz7uHu5hqiC7zbEtvUrADUGLgNBkdPhDKR7omEosuMwD79DNf5XE0rW9/Pr73l92UfgTRX2S+dYbr7ZrfWK6hF+rJpxV1mvwsBHeF3VCeDseIIAAAggggAACeV1APVLLeJWm0Ehcvz5Z66NSvtLosgvPDvqbhrZRDPXsy295fPZdeKJU76kl1BcfvRYkVCr20s3p55960Dqefqm3GVgb+ngwuXmbT2CGbv5v2bLF3nj3U3vPKwaEyrRqY8Vhd9xyjV156XnBxKjaOKmEar9Bw2yytwWIZqj36YVX3pLhpuoP28X3/fIzD5uuWUPJEFoxtWlv6dgMd+Ib6Lq1euucM08J3/xXGwQlQQST1hExp2LMW2+4ypMFLjKt6NI5NDuisT3plRHu8Xg6qdxt6ke96LzTg3j8936D7bGnX0m2uv8Uv47nnrzfk3CTElrV6urqyy6wdz/8ggSA1Dl5FQEEEEAAAQTiSGDI8FE2a/b8cOVOxTInewn6lt629D1fed7j+59tnc8/Kml1165dqbZPSnk5igmvv+3+4OWmTQ6zXl9/aEoy1dBc338ff8HmRcRpwRup/EPVm/Sj+G7Yn2OCiqF/ezunzb4qXkmYoVhWLVWvu/ri8B4UV37i7aye98VFkW1G1fJUiQJXXHJeUIVL8eGdPgc5dMQYm+aJEKHRrGlja3dC6/DNf137IF/V/9Tzb9gMT54NDd3079KxrWm+Vjf/NZRwevYZp9hrb38U2izD35pnVRJpZNn/pDnivvZ/b3dLVkEsw52xAQIIILCfBPLtp+NyWAQQQCDuBZQB+8a7H9s9Dz4Vvvmvk1Z2aSgrtkqVSkGvVa0AW7pshf3nkWfst35//OPa1CPrxn8/YIsXLwu/p1KulfeutNeLCi67ePmsY1sdFd5m3br19vYHn9srb7wfvvmvNxVoD/JesI899Yr9PXVGhsG+gvBzfSK28t5VVgq83/7gM7v93keT3fzXvlVN4I13unlg3C1Zidmbrr3c1HqAgQACCCCAAAIIHAgCSqi85IKzPL5JCF/OIo/VVB0pNI72idYzT+0UemprPTb7t8dPupkcigdDb86Zu8CuvvEeGz/x73BsVqVyRbv95qvDlQO0bYN6h1oBrxIQGpo8/dYnckMTpqHX1Zrg+Vfetp88YXOh97OfMWuuKaYsXSrpBn1ou+z4rZVl995+Q/jmv4793yeet4mTp8a0e1WPUjJrfa+AEBqDh42yu+5/8h+Tykqk0ETss95qKtFX74dGJ4+HW7c6MvQ01d+Khd95/3O78oa7kt3818bqHXvtLf/xfW4If1YrxVp4WwYGAggggAACCCAQ7wKKMe/3+cWZHvupglJolCtbxh64+2YbO6S3ffnx68GNc7XvbOhl81V9VFWocmNs9mqnH3z8lV11w902etzE4Oa/jrt8xaogcVQttZQEGxqK85567jV78rn/S3bzX+8r7v7vEy/a6z4PGarCpRaqF513RrKWAVWrVgo+q3hb8fCo0eODhNHIm//an6qs/vr7IOvV+/dwFSudzzEtm3nFguh85Nja52YfvPfWZDHtL77Y6+kX3uDmv6AZCCCQJwSoAJAnviZOEgEEcltg9+49NtAzST/v/n26gd3t9zzqZa+qWZ3aNa2IZ6mOHDMhyL5N7XwVIA8aOtLLVZ0VvK2sVK3G10qpPXv2BJUFmvuqpzJlSoU/PnzUWPv48x7BCqzwixEPxk/62wPbgUFWa2QJrIhNgv3XqF7VWh3dPPzy4KEjfJXZl+HnKR8oCeAXD5jber9bVRrQOTZr2sgaeKuDv6JccZZynzxHAAEEEEAAAQTiRUBl6o9r3cJO73pSuHypVlBN+OtvmztvQfg0u5zULlw9SS9q1b9uyKc1Zs2eG1Rteuyhu3zVVrlgs7NP6xL0CFXCqEaF8mXtkHz7eqAq7kqrzP62bds9IfUT69nrF58gXeMtAJb+I1Eg2GkW/qEqCA/ff3sweazdbNu2zbp/+6N9+XWvmPeqfqwq5Roain9ffPVdT5xIvUSqklJ/7z/Yy/8fax3btwlizlIli9tpJ58UrEbTd5LamD1nvp9j2uc34a+p9vPvA+yS888Mf7xpk0b2W99/JuqGN+ABAggggAACCCAQJwIzZ8+zm+54yK71tkqKk0KtOnV6mqNr7fGWfrQqfdHiJTZ+0hRvG/pX8DNtxiyP55KXz8/Oyxrmq/O7+VylFk6lNnTzvHHD+uG3fvX46/uffgvONfxiigeqDtCh3XHW/IgmwTtdu7S3Z158I3wdv/YZaCNHjQ8qbdWvX8cWLFicLGk3cndKFJ00eVrQZqC6x7nyKlO6tCmBQkkKGQ3NzaoS6hGHNwxvqmt+5KmX0jxmeEMeIIAAAnEkQAJAHH0ZnAoCCMSPgEqxjp0w2ZYsW57hSc33oFM/0Y3dyTZTT6xQAoAmg9VjNnL07PXrP7JjI99XUKsy/pem6IEVuY0qC6hUlvYfGp927xn0SQ09T+232gJMnTbLjjn6SO+blWCaKFfwSwJAalq8hgACCCCAAALxJKBy/Or/mXIoLqpevYod3qiBdfaV5ofW3td2afGS5Z4A+qdt2Jg0makSpOpxGhpaofTTL31DT1P9vXPnLpvoN5+neinUUAJA8RLFfPX5ET45m5QAoKpRkeXtG3o7Kd2cVoLmzlRueM+eM8/0kxOjhLcpUJuBtse3Cu9eSaAffvK17dqdPG4Nb5DGA9nqWkLXrc1U+l8Jq+mNxUuWmSZVNYmttgeqzKDvT0mx6gGb2hjjE9zqHZvW2LVrp40ZOylZAkDkxHlan+N1BBBAAAEEEEAgXgRU8fPpF163PzxG7NThBJ+fa26qLqWYKzQSEgoEi5K0MOms0zoH1Zv69h8StAkIxZ6hbbPjt5IzVe1qydJ9FU5T7ve8s7qGX1IS6J8jxwZVtMIvpvJA1Vb7eGunUAKAkkqVRKBjhYZapOono9hS22u1fz6/8R8aii/TWjgV2ka/K1eqYI8+cKe1bHFE+OW+A4bYk8++xs3/sAgPEEAgrwiQAJBXvinOEwEEclVAJVhX+iqrrAwF5GVKlwqCcwXoWoHfpeOJae6yePHivm2l8PtaMaUqBBmNufMW2tKlK6xalcqpbqoSs+q9FRoqt7psxcpkk7Oh91L+XudlurZ5+SwlAChZoXbN6ik34TkCCCCAAAIIIBB3Apd7cuSZXTv+47yUeKmbzOpzrxv8oaG46/OvegY3okOvNahbJyinGnquEqMqOZrRWLZ8pS3ce7Nf2yb4hOPRXn6+V+8+wUen+342rN9oxYoWDZ7X9ZvdTzx8l0+OjgvK18+YMdsW+U3xnB6qRnW73/w/+/Qu4UNN92PLQS0HYh1BAoCXoI0c/QcNjXya5uPxE/4OqgTou9F3VL5cWY9tK6WZALBs+YpkJXFT7ljVtdZv2NcCQO8XL1Ys5WY8RwABBBBAAAEE4lpgpSdD/vRz3+AmeuVKFf0GeeOgrdFRzZt6NdCayc5dsdiRvoK+vsewh9apZc+99JbHlEkJqMk2zMITVW9KXL/eW5OmXqVJu45su6QEWrXQKle2dLpH1bmnjN2OaNIwWQJAejsoUqSwVfGb95V9XrVBvTp2hrfwKh+xECq9z4beU5uB2264KtnN/z9HjbPnvF3VTK/yxUAAAQTymgAJAHntG+N8EUAgVwS0Kkur62MZKit1dItmvkq+kR3vJWVLe3n/4r6qSr2j9KOb6AUTEtLcZVEPVst7OarQWLhoqakkbEZD5zp1+ixTj9rURr78+ewwL90fGrqR/82nb9keb3OQ0dC2CqI1dA2alGUggAACCCCAAALxLqDV3rGs+H7mxTftM7/xHVkutZJPIkaOOZ50qUTKjMZmrySlVf7al2IpTWhGVmJa4yvXX3ztfXvx6YeCXSnGquuTtLVqVA9WbmlidbGvqhrtK9gHDx/plQFGmnrBZvdQmVWtFCtWLCkRQSVR3/rgcxvlLa10Az3WoRv3NWpUTfaxiV5+NZoxx9suKAE3NNQmq6ont6qaQmojqE4Q+ymmtiteQwABBBBAAAEE4lpAcY/iNP2oKkCP738OEllVyapThzZBGyXN+ymm1Cjusd1Zp3Xyeb/ddv+jz5oSXbNrKEZU29S0RrlyZayEL3AKjbqH1rI3Xn7CdqWTMBBs64v1U86Zli+f1E4rtK/Qb8WcSnQ49pijfA62sdWvVzuItbXKP7/Pgep3IU90VQwe7Ti0dg17/YXHraL/DREaG7wqwYeffOVzrjNDL/EbAQQQyFMCJADkqa+Lk0UAgXgTUGBZs0Y1u+f2G7xXaQe/yV8w1VNUgKySrtt37PhHQBv6gALU0M12vbY2MfVeqaHtI38nrk++winyPT0O/RGgxwqUlZyQmaHPMhBAAAEEEEAAgXgX2LVrd7Iy+5Hnq+RJlS9VXPbX39Pt/oefMd2ATjlKl0weL23y1gDabzRD5Um3bN0aTgCoVHFfMoHiwi++/t6qeoWoa666yCsBFAkmKlWqVMmjGmV9lVRTX/X0rysu8HKjq+xP73n68mvv2ey5C4Jzj+Yc0tpG8ZxKyN57xw1WzRNYNbZ7xac+/f4IqhSkt6IrrX3qdZVZreIr0yLHOl/xFc3QdxKZdKBzjGXSNppjsA0CCCCAAAIIIJDXBbRYST+6qa+k0jHjJpoSWdXa6j933eQLgOqGb4Kff86pNmDwMPvhp99z7bLzHZL8pruqkpbM5GKiyDlIPdac6emndLSbrrs82UKnlBeneF1zsAUUT/pPNEPzppU9No8cWgR15SXnBQmpOdFOIfJYPEYAAQRyQoAEgJxQZZ8IIHDQCJzY9jh77okHfPJ0X+l+TShv3Lg56B+71Sd+NwVB+dpgYlk9UU/v2ilVn6Qs2t3hyU4FydGOlFmy6X1OgfD8BYtinjxW8KxsYwYCCCCAAAIIIBDvAsO9p/yUabNSOc09phZHC7zE/bgJk23BwsVpJgqk/LBuSEc5hxjEc5GTltt3bE+5O3vp9fftN7/pfpm3K2jWtLGV9Z73JUuUsFKlSiTbtmKF8namlzHVyq5nXnzDBg0eESQvJNsoyic6p6peWl/HVF/V0FD7gad98jiyAkLovWh/ay2YqhdEDiU1MBBAAAEEEEAAAQRyVuD3/oM99p1pTz92n5104vHhucWLzzszVxMAUl7l1m3bvMXq6qiqaKX87Oo1a8MvKZlWCQ7nnNElvPhK86hKuN2wYZNXy9oSVFFd7wukFi9ZHryupAjNw8YyNnlFqk2bN/vnkioBnHB8K7vu6ovt6RcUJ2dcCSyWY7EtAgggkNMCJADktDD7RwCBA1ZAk6dPPnx3+Oa/bvzP9dKww0eONfVPVe/WNR6sLl2uMl0rgwzdh+67LU0PZfCqvGuoDGulvcFmmh+IeCNlidqIt8x8NlalaENj27at9tDjL5iC4ljGbg+so+l7G8s+2RYBBBBAAAEEEMgJge7f/mTf//hrlna9cdOmZJ8v533pVbEpmlHCV/Kr9KiGVrerf2vKodf/+nuax2XPm3q66gZ/La8sVd/7lmplfq2a1fyneng/ev/2m68J9jV+4t8pdxfVc7UkuPaqi61rlw7h7dVK6oVX37VET4zIytAk7MpVq5PtQq0PFntMnNEoXKhQsopVuzwuVlUCBgIIIIAAAggggEB0Alql/trbH1vLo5pZ6dJJlayOadk8ug9n01Y7PIYLJiL37m/x4mX21vuf2rTps2M+wtLlK4LPFC5cyM46vbOd3Kld+Oa/5jmH/znGxnlMPM8XOa30ilmrVq8N4s4NXrVLra7aHn9MTMdUddX3u3UP5ksfvPcWb7OQ1BJVVQA03/vF1z/YDq8gxkAAAQTyikB0sxd55Wo4TwQQQCAXBZRJWqdWjfARNYH7+juf2B9DR5gyRmMdCl5XecJAKAGgcuUKQXsBrUxLbxQvVsxq++RwWkO9wubNXxiUetU2alOwcPESmz1nflof4XUEEEAAAQQQQOCgF5jiN8Yjh3qDJk0Ept+mqaiX9K9apWJQ/l+f143+1T4hmdZQyX1N2IZKi6oEaRUvQVqjWhXr2OGEYLW+Sqdq9X7jRvWtbZtj7O8pMzJVBaBr5/Z26YVnhdtOqbfpo0+9bGMn/JXW6UX9uhIAUt7sP8LbGEyYNCXDfSjZQa0QQkMTt2p9wEAAAQQQQAABBA4mgUZeoalj+zZWoljR4LLXrEu0z7v3tI1RzjMqgXXd+vXhBIBCnmSZm2Ojx3Br1iZahfJJK++VPLtk2Qq/UT8506dRtXIla9emdbidqWLr7t/0svc//srj5yVRt+hK7wQ0j/vGu58ECQDFixcNEnIvPv+MIPlXCbRq/ao4t++AIenthvcQQACBuBJI3pQlrk6Nk0EAAQTiW6BJowbhE9y6dZv9+vsg6zdwSLo3/7WKK62x1nukzvG+rqGRkJBgx7VuEXqa5u8GvhqscqWk0lSpbbR7966gIkHoPQXfsWbBhj7LbwQQQAABBBBA4GAR0A35yNKjjRrWs/LlymR4+fXq1ramTRoFN+y18Y4dO2O6wa6qUjr2n6PG2WtvfWQq6RoaWimvxICixfbdLA+9l9HvLr5q6uH7bzdVJ9DQzf/nX33HjzM2o49G9b5izpSVCTp3bBfVZ49peaSVK7vPVm0aFi9dHtVn2QgBBBBAAAEEEDhQBKp7FagLzz3Nrr/m0uDnqkvPC25GR3t9aidarEjscWK0+89oO1U3HTt+X2KpqkHpmvLnz/xtKO1DVbJCQzHsy69/sLe96e7Qy8l+F/d4t2DBhGSvpfdkhVex+t1bc6nM/5o16+wzT7oYP2lfxa1yZUvbXbddZ00aH5bebngPAQQQiCuBzP+XN64ug5NBAAEEcl+goN+gD41tXqJU5fFT9j0Nva/fCj6bN20U+VKyx4meoZtytf/Vl53vK7TSD9zPPfNk7xlbOtm+Ip9oVdnosZOS9du6/l+XBOcTuV1qj6/0PzQee/BOO+fMrt6bNu1zT+2zvIYAAggggAACCORlAd2I7/3rgPAlFPEyoOedc2r4eWoPNNHY7PBGVrdOzfDbKoU6aszE4LlKmOpm9xWXnBPcjH/ykXus6eENw9umfKBSpJpE1er60FCFgPz5YvtTvrxPnP733ts8abRCaDf24y/9vE1CH29TtSv8WlYe7N69xyZPnZ4sofXEE461Fkc2TXe39evWthOOa2WqnKCxbdv2IJEgvaoJ6e6QNxFAAAEEEEAAgTwqsMQTIBMTNwQtoNROqlLFCnZyxxOjuhotJDrH5wgV94VGNCvvdZyEhOwrFN2j58+hwwfxnSoaVPJ2V+mNIkUK2+UXnxO0Wj3nzFPsiIj4WLFvZBuuNWvXeZWBdentzmPxWuGKAeluuPdNxcOhmFhx999TZ9gb3k5h3vxF4Y8f7jf/b7j6YivhlbkYCCCAQF4QiG3WIC9cEeeIAAII5JLA2sR95V9VsrRG9arh/lCRp6ByrSrrf9O1lwfbRL4X+XidVwAYOPjPZKVTG9Q71O689Zrg89pP5FAp/1M6n2jtva+Vgvz0xkJfRabVY6HJY7UM+M+dNwVBa75UJpAVWCtA/9cVF9oNnnX85stP2Gcf/F9Qciu94/AeAggggAACCCBwIAl88uW3ySYYr7/qYjvtlJM85vtnOVXFVE0aNrBrPH4qWbJEwKDY6+PPv7Vle3uY6j7+fXfcaM89+aDdfN3ldvH5Z1qn9ieE+5mmtFPSQasWzcPVBLQ/lSjdtj36/qNqJ/Dqc4/YoXuTErSPEaPH+3n1MK20DxIKlFSQxk/KGDTlOUY+X7FiVdAOS6VZNbTa65VnH7HqXrUgZcyp/Zb11VSa5G3erHF4N5rQjYxbw2/wAAEEEEAAAQQQOMAFZs6ea5OnTA8qSOlSFXOed3ZXu+i8M4L4UvFayqGb92VKl7KbPLbU3GModlM89uXXvVJuHpTM35daalbOK1xVqFD+H7HaPz4Y5QsjRo+zqdNmhrfu4hWhzjylo6mlVWpD19T8iCZ2/90327Uea7/58pPW6+sPrZpXDtDYtHmzx6z75mCr+/xrZFJr5D61rzaeWNq1S/tU4/XIbdN7LLtBQ0fadz/+Gm6/UKBAfuvS6cQgUSGpLVh6e+A9BBBAYP8LZF9q1/6/Fs4AAQQQyFWBEaPG2w3/ujQ4pm6Yd+3SwVfwL/EJ1XGmm/kKuBWoKzHg7NO7BMH6Vi8lpdKtaY3RYyfasBFj7JwzTg6yW/V5ZcAqSO792wBbumx50Ee2ZIkSvnqsuV1x8blBQKzytJFlU1Puf6WXsvqu168eUDe2mnvLZl156blWpkwp+/HnvsFKrc1btgQJAqVKlbQWzQ+3666+xBrUqxPe1fSZs5OVvwq/wQMEEEAAAQQQQOAAFVi0aIn1+P4Xu/qy88I36V997lF7+8MvbNDg4cENdE0Qqr9qvUNrBzf1D2tQN6wxxSc/3+v2Rfi5yor2HzTMjj6qabA/JZFefMGZQTl+xYArvaLULl+BpORRVXjqfNIJ1uHE48KfV8UpldlXf9VohlYoXXbR2UESQegGvEqzrvWb7E0aNwh+0tuPqluNGTfJFrpDNEMJBT/+0teOPaaFHeZtqhQPqyXCu689ba+/84nNW7AoKK2qfVWqWN7OOq2LnXdWVyu6t+KV2mp998OvXr0qqWJCNMdkGwQQQAABBBBA4EARUOz1/Y+/2XEeSymG0qhapZL979F7PSY8PkiSVPVQxXP5DsnnMWjBYDslqLY5tmWwfegfE/+aYv0GDQ09Df9WlQHFgkWLJN1gb3RYPbv1hiuDJIK16xKDfasClaphZXY89vSr9tarT4XnKu+76yarUbNaMAepOUrFfFrnpHi3YYN6dp8vUgpVN921a7d98fUPpvPUWLFyjc2dt9C0Al+xpdocPHTfv+3DT7r7POmKoBprfr85X8rnSo/w6qW3XH+F6ZqU9BpKhsjMdWz3aq/vecxf32P8M07tFOxC87MXnnu6zZw11xdxDQ9XDcjM/vkMAgggkNMCJADktDD7RwCBA1ZgwB/Dbdifo+34vQG2bpY/+cjdwSSpgvFDfBVYKV/91bRxQ7/pXtU2b94SvHdi22PTNNGKp6++/TEIVEOBbWm/Ia9S/J1PahsEvCojW8kzc+seWjNY+f9Ln4G2ectWnzw9Jc39amJ6+Mix9umXPe2WG64IgnpVDTjXV1x18AoCU6fPCnpc7fbgWH1lD/cJ4ciqArr5//wr79h6L0PLQAABBBBAAAEEDhaBjb7a/pvvfjKVqW97fKsgQVM35++85Rq70NsBLPAb4yoXqsnAxg3rBYkAIZsZM+fYMy++aSlL2ff0pEztq90JrYNN1Rf1/ntutpmz59mMmXN9EnOblS9XLmgjUMsnSkMx2ZatW70lQX8b6vFntKNJowZ22sknJStVqv2d0rl98JPRftauTbT7H3026gQA7W/iX1Ot22ff2L9vujqYsNbE61HNm9prLz7u1zjXkx2SkhfUJkGVAUJjx44d9uU3P3iiQLfQS/xGAAEEEEAAAQQOOoGxEybbB59+ZQ/efUu4qpRaJZ3uN/n1s2z5yiChMp/fCFcMWsJbjoYSPUNYc+YuCJIvV61aE3op/FsJm7rBft+dN4Zfa+9zlce3bmFbfH5RCannXXaTLffjZHZocVS3z3rYjddeZsU9dtYCJ7U5Pd0rAWiOMWl+8RCvUFXDFx8lJY3qWEo6UPLp51/1DFcxXbFypWkOtnWro6xihXLBTf2zT+/si5waBXHnZq8QULBgIV8gVclbrzYOkiKmexyuKliaU83KWL9ho738+gdWu1Z1b0uQ1BpV87+33XhVENdGtgjIynH4LAIIIJATAiQA5IQq+0QAgYNCQJmgDz72vGfh3uflpZKybIsVLZpqmfwNHjC+8saHnp17iKWXACA49Yh96vk3vET/jT5ZenjYUoGrfiLHpMlT7e0PPrOTvQRVRkMrxbr36GWaPFY2rDKINVQmTJnFaY0Bvkrt9Xc+ZiVWWkC8jgACCCCAAAIHrIBWDmkC8eXX3zetiOrqN87Vo1Sl7VXlST8phyYudRP89be7eTn8kSnftmUrVtpjT79ij9x/e9DKSRtoBXwzn1TUT2pDk7GaqH33oy9s+YpVqW2S6muaEM7tPqU61169fw+qIzx0763h6lM6l6Oa7YttI09Ytp9++Z29/3F300QrAwEEEEAAAQQQOFgFlBT5zbe9g6TJq3xBUMsWzZJRpFX+XhupMoBW77/70Zf2x5A/01zF/1n3nl4hqlmyOUq1GtWPWk3VrV0zSwkAqmTwqbfS2uLVRrWoKVSNtLy3Gyhf7uhk1xN6st2ve/CQEfbGu5/Y7LnzQy8HLQv6DRwa3IS/7uqLTXOvKvWv6lv6iRy6/sHDRnqlhCF2vVc2zWoCgPathIXHn1FFg/8FC7L02pEe0yqB4q77n/JqBlv1EgMBBBCIOwESAOLuK+GEEEAgLwnM8JJP/33iRc/8vDK4Ca8VYZFDgeeYsZOCzN2Bg//0lWKnR76d6mNNGg8dPsrmzV9gV19+oV107mlW2m/SRw61EtDK//e7fWl/T51p6qcVzVCFAa2sGjvhr2A12KUXnBW0AUj5WZ2DqgJ07/Gj9R0wJKZVXyn3xXMEEEAAAQQQQCAvCygumjBpij3uN+0n+m+VrFd50dSGWgZ0+/xb69Pvj73VAXamtplNmzHb7v3v03aSl3JVu6eG3jZALaVSDrUMGDxslH38xbc2zuM3tZnKCyPRq0YpVp3iceoF55xml150Vrisa+T5b/AE1UEeI3/tVRZGjpkQdWuDyH3wGAEEEEAAAQQQONAEtHhHCZXjvBpAR48Xz/fKU2qvpLZTaY1x4ycHPet/7z/YE0ZX2o4dqceh+rzaSt338DN29hld7KpLz0+24KioJ7s2blQ/qCSa1rGieX2lVx/o9nkPUwvViy84I1j9r7ajqQ3Nbfb+pZ993/s3W7R42T8SF9T69B0vx7/Gq1MpoUCVpFIOVeX66tufvDXAV151oNg/9pFy+1iejxw9wZ576W175vH7gu+ggLccOO3kjjZr9vwgUTiWfbEtAgggkFsChxQrW3tPbh0s1uNUrl7bChUuHHxsh6+03bA+MdZdsD0CCByEAip7pUzQ0NizZ3dUPZk06bqvN9SeIMNUpfOjGTpelUoV7DDvW9W0yWGeMZvgWa7bfCJzvE2eMj0ooaUVZCnPTRPK6R1D2ytbVT1aGx9W30qVKmGLPRAeN3GyKflAn9fQ8SPLfe3213dlcO7aXqXCDvfzrVOrhpfRKh+sZps7f5GN9wnmeQsWm/ajtgAMBBBAICRQvERJK7h30kFlqpcumBt664D6Xb5SFStWIin5Sv+tTVz7z9KJB9QFczEI5HEBTcId4n1QQyOjGCu0Xay/FT/pR/3rtZpdLZm0UkqlWCf+9bff8J4VxGDpxXeRx1TsmbSCqZbV8ZVWKtmvkZiYaPMXLgkmfbU6XvtTLJnaSEhQ4oA3UfWhbZSAGhr58iXtP/R+6PXofyePiXW+kYkKirPVpzWtc9Nx5FWiRDFvi+Uxp1+jSrcG5WV9UnjYiDFBRYP0rk/7UMWFfPn2xfe7d3us68dNb+i4yf4mcMOde2NnfS6lja5B/96kdy3pHY/3EEAg5wWKFC1mRXzlp4b+f3XB7Ok5f9D9cIRSZcpZ6XIVwkdesyrzZbjDO+EBAgjkWQFVE1W5f7UXVfn5UCl6XVBi4gabO3+hTfp7mqncf6zzeIqXVN2qbp1aXkK/sm3y9lfa35IlfhN+77xi8vnSpDL90ca6IfSkWC6ftfE2qnVq1bTy5cv4yvltfrN/qU2cPM3mL1gUxLsZ7TcU36k9l1bhq+y/xrJlK613nwFBDK0YMYhZNTfsdhqpxXmRMbRvEMSJ6cWBKeNg7VfnG5qb1XMGAggcuAKaC9WcaGjMnzUt9DBuf5MAELdfDSeGAAIIIIAAAgjEnwAJAPH3nXBGCCCAAAIIIIDAwSBAAsDB8C1zjQgggAACCCCAQPwJ5MUEgH1LJOLPkzNCAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAgSgFSACIEorNEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQiGcBEgDi+dvh3BBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEIhSgASAKKHYDAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAgXgWIAEgnr8dzg0BBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIEoBUgAiBKKzRBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEIhnARIA4vnb4dwQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBCIUoAEgCih2AwBBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIF4FiABIJ6/Hc4NAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQACBKAVIAIgSis0QQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBCIZwESAOL52+HcEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQiFKABIAoodgMAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQACBeBYgASCevx3ODQEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAgSgFSACIEorNEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQiGcBEgDi+dvh3BBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEIhSgASAKKHYDAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAgXgWIAEgnr8dzg0BBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIEoBUgAiBKKzRBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEIhnARIA4vnb4dwQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBCIUoAEgCih2AwBBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIF4FiABIJ6/Hc4NAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQACBKAVIAIgSis0QQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBCIZwESAOL52+HcEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQiFKABIAoodgMAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQACBeBYgASCevx3ODQEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAgSgFSACIEorNEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQiGcBEgDi+dvh3BBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEIhSgASAKKHYDAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAgXgWIAEgnr8dzg0BBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIEoBUgAiBKKzRBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEIhnARIA4vnb4dwQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBCIUoAEgCih2AwBBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIF4FiABIJ6/Hc4NAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQACBKAVIAIgSis0QQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBCIZwESAOL52+HcEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQiFIgzyQAHJLvECtQoIAdcsghUV4amyGAAAIIIIAAAghkl4BiMMVi+fLlmfAxuy49iD8LJCTYIQfhtWcbIjtCAAEEEEAAAQQyKaA4NL/i0PwHXxwqsoSCCQdlDJ7Jf134GAIIIIAAAgggkG0CQRyaP7/lz18g2/aZWzuK6zPevXtX2KFAgQQrVqKE7dyx03bt3Gl6b9euXbZnz57wT3hjHiCAAAIIIIAAAghkWkDBbfDjN7zz+0++fB7oFtBPgge8+cP73bN7d/jxgfZgt1+b4kw5KOmhePEStmPnjqQ41GPQXXp/7zbajoEAAggggAACCCCQdQHFXmZJ8Zdu+CsO04SrElGVBBAaitUO1BEZh+oaixUv6fOhSXHorr3zoR6o+txokgGx6IH6bwLXhQACCCCAAAK5KbAvDt0bi4bnQz0WjUgACMVguXlumTnWvsg5M5/O4c9sTFxnBQsWCgf4Cvj1E9z09yB39x4PdH2+NXiuBwwEEEAAAQQQQACBLAv47X+fd01KAsin3z7xmhQE79u14rDEtav3vXCAPdq8cYMVKlI0iEV1afk88aGQ/+wpqORTj0M14bo3DtX7/qp+MRBAAAEEEEAAAQSyILAvDvX465CkGDRlFSbNA65dtTwLR4nvj27busW2bd0cxKLyUBJEwUKFPA4tuDcODYLQYD5UV0IcGt/fJ2eHAAIIIIAAAnlDIIhD/VQ1B6r4MzQnGnn2ikMT16yKfCluHx9SrGztuJ2tFHLBwoWtVJnyVqRosbhF5MQQQAABBBBAAIGDSWDH9m22ZuVyn5jcEp54PNCuX3FogieilixbzooVK3GgXR7XgwACCCCAAAII5EmBnTu229rVK23Lpo0HbByqRNyEhIJWonQZK1GydJ78njhpBBBAAAEEEEDgQBNQdfrEtats04b14UpM8XyNcZ0AEILTBGyhwkU88C1rhYsU8ThYGcB6N/hHaDN+I4AAAggggAACCOSAQFBtyTNct27eZBvXJ9rWLZsO3AnXVPy04qpk6XJW2BNStQKLODQVJF5CAAEEEEAAAQRyRCCp9acSTzcmJtqWzRvzxIRrdlEUSEgI4tCixYt7HJqfODS7YNkPAggggAACCCCQoYDiULPtvhBqY+JaT0Dd5K3pd2b4qXjZIE8kAERiqfyqsmDVGkCrstQPTP1oNRnLQAABBBBAAAEEEMiagEpD7fHeort37fZeo9s9sN1lWvG/bdtWf21X1naexz+teLOA4lBPCChYsHAQf+b3SVni0Dz+xXL6CCCAAAIIIBA3AmqztFt97r3n/U5fZaV4VDf/FZMezCOoTuVxaEIoDt07H5rf50kZCCCAAAIIIIAAAlkXSIpDPRbducN2+M9Oj0eDONRj0rw48lwCQF5E5pwRQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBDIaQGWzee0MPtHAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAgFwRIAMgFZA6BAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIBATguQAJDTwuwfAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQACBXBAgASAXkDkEAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACOS1AAkBOC7N/BBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEckGABIBcQOYQCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAII5LQACQA5Lcz+EUAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQyAUBEgByAZlDIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAgggkNMCJADktDD7RwABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAIBcESADIBWQOgQACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAQE4LkACQ08LsHwEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAgVwQIAEgF5A5BAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAjktQAJATguzfwQQQACB/2fvLuCkqtc/jv9YOqVDGilBEZCQkFARTOzOa8e1vV7jb1295r12e+1uxVYEEZRQSlK6Q+nu//M9y9k958zszsyyu8zq56fLzJye95mZM695nt/zQwABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQKAQBEgAKARkdoEAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggEBBC5AAUNDCbB8BBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIFCECABoBCQ2QUCCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIFLUACQEELs30EEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQKQYAEgEJAZhcIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggUtAAJAAUtzPYRQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBAoBAESAAoBmV0ggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCBQ0AIkABS0MNtHAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEECgEARIACgEZHaBAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIBAQQuQAFDQwmwfAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQACBQhAgAaAQkNkFAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACBS1AAkBBC7N9BBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEECkGABIBCQGYXCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIFLQACQAFLcz2EUAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQKAQBEgAKAZldIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAgggUNACJAAUtDDbRwABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAoBAESAAoBGR2gQACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAQEELkABQ0MJsHwEEEEAA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AAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAJFQYAEgKJwljhGBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEgiQAJAAiNkIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggUBQESAIrCWeIYEUAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQSCBAAkACIGYjgAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCBQFARIACgKZ4ljRAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAIIEACQAJgJiNAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIBAURAgAaAonCWOEQEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAgQQCJAAkAGI2AggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACRUGABICicJY4RgQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBIIkACQAIjZCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIFAUBEgCKwlniGBFAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEggQAJAAiBmI4AAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAgggUBQESAAoCmeJY0QAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQCCBAAkACYCYjQACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAQFEQIAGgKJwljhEBBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIEEAiQAJABiNgIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAkVBgASAonCWOEYEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQSCJAAkACI2QgggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCBQFARIAisJZ4hgRQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBIIEACQAIgZiOAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIFAUBEgAKApniWNEAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAggQAJAAmAmI0AAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggEBRECABoCicJY4RAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQACBBAIkACQAYjYCCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAJFQYAEgKJwljhGBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEgiQAJAAiNkIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggUBYESReEgOUYEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEE/iwCDRvUdaVKlsp6OmvXrXNLf1/mtm3bljWNOwgggEBeBEgAyIsa6yCAQJESKFHCPuqKFXP6T/+rZRQLFEDRZJsfv9laOc2KvwJTEUAAAQQQQAABBBBAAAEEEEAAAQQQQCANBHbs0EF4/8QczQ7NDMzaYQ+8aVrD5unPC8RmbiRm/XSaUKZMaVe1SmVXpfIe3mGtW7/erV+/wQsm59dxlild2tWoXtVVqFDeZWRkuI2bNrl169a7P5atcFu3bs2v3RTKduSk51KyZEm3ZctWey4b3bz5i7LOf2EcRPny5dztN13tKlaskLW7bwb+4F5/+0O31lyLUqtgz6VO7VquVKmSnuH6DRvcMntdrFm7Ll+fRml7DdauVcNpf2p6jS9e+ofbYPvLz1a6dCl7fVRzlezcKG6g/SxbvsKtXrM2P3fDthAoUAESAAqUN/mN192zlrvswrNjVtiwYZN74JGn3caNm2Lm5TShdq2a7uLzT7fMsZKhRfQB9c4Hn9mFbKE3/ZLzz3T169UJLZPogbLP5i1Y5CZMnOJmz5nvNm3enGiVHOfXq1vHHX1EH1dvz9o5LrMrM8ZPmOw+/2rQn+pD+eTjj3L77bt3iGXUL+Pcl99+bxe5jaHpPMgWKFehYlaA34/lhwL+3kR/TvZ6uhdaLjyLRwgggAACCCCAAAIIIIAAAggggAACCCCQ5gJ+UD/uYQaC+14ugAL/OxfUemvXrHbb07Q3toLXHdq3cR3338+1a9PKC8z7gdGNmza7zfanWMCwEb+4YT+NynMyQNs2rV2/Pj1d44b1XPVq1ZySDTIyirnNFjjfZEkA8y1eMGz4L27goKFu5arVcZmjE5WscNZpx7uaNapFZ6X0+INPvnSjx05w27dvT7herZrVzWs/d1CPLq527ZpecLdEieJu67btbovFOZTIMPbXSfY8hrmp02Yk3N6uLtCqZTN3UM+uFjTPrgDwzXc/mOuWXd103PX1Wul7SE9XvlzZmPkjLcbwyadfu+2B90PMQpEJ+t28k732+tpro2H9et65lKc2objRihUr3aQp09zgH4a7MeMmWDJN4nMU2YX3sGTJEq59231dpw5tXbv9Wrsqe1TyXoOaucle43rNTf1tpsVIBrtp02ftUvKEYi+9DuziWu/dzFWrWtWVLVvG6xyo/SiZYcasOe77oSPs/fSz27wLsTEd+x72PK79+/nO67yoCTub3rtPPvuKvR6X+5MS3uqz4LyzT3YN6u0ZWlbH+M6Hn7tJk3/zph97dD/Xod2+KcU8li1f6ZavWOFG/TLee/7EoULEaf2ABIA0OT1//LHC1bVAeO8eXUNHpAvXvAUL3UuvvRuantMDZd6dcsJR7twzTgq9ibdv3+be++gLu8j/kbXqEf0Ocm32CQeTs2bmcGeLXXz0YacMwp9GjnFPPveKmzJ1eg5L5z65WtXK7rA+vSyg3Sr3BfM4d8AX39rFZcSfKgGge5eOrv+Rh4ZElFWniw4fvCGW0IPoRTQ0kwcIIIAAAggggAACCCCAAAIIIIAAAggg8KcVyLWDT6D0Z7zuQfGmpQOUSsdfduFZFkDu5ipbb/Z4QV0dpyoYHNa3t5sxc479lv+qGzh4mPV4Ty7A3LL5Xu7KS//mBV4VsFev6HiWW20f/Q7p5c45/QT3osUxPvj4i4RElStX8joHNm3SKOGyuS0wdvwkCy5PzG0RV7x4cde5Yzt3lT0XBd21b02L13r37OpOPfFo9+Ir77g33v04pY6Z8baX2zQlbmRkZB/HEuvJrgD25s3JnZ/cth2dV86C/upceOKxh4f26S+n8zrg82/sBeOnv/hz4t+qd/ytN17punfp4KrYa0OdUaOvDSXQKJh+2knHuI8sueDp519NOQlFnUj1Oj+kd3fbj17nmT3/o0fVs/sBFjfp44YMG+meffENN33G7OgiuT6uVq2Ku/n6y522U9kC85mB/9h3f49und2xR/Vzv1rn02tvutstWfp7rtvNbeY6G+5BSTTnWCwv2Lbv2O5VObj0qpuDk3O9f6TF+q79+wX2Hi0dWm7Kb9Pd/Q8/kzVtf0ukOO3kY1zxwOsua2YOd7ZYdQ9V+Fhj1Q/G2fN+5vnX3S9jf2WYihy80mkyCQBpcjaUEXXHPY+4bgd0cCr9EmxXXHKuG/T9j27OvAXByXHvN7IsvHPOOMErtRJcYO26zfZGf9oL3vvTS1pZdGVPpdK0vC4W+rA98dg63gXj1rv+455/6a2Uy+PogqDAbKrHkOzxatuB72/JrpbWyxUvnhHjpS8rf7bnmdYngYNDAAEEEEAAAQQQQAABBBBAAAEEEEAAAQR2k0B96+X7yAN3uM7WIzpR02/HCt5X3b+ye6p1C/fAw896AdJEJft7Wy/5u2673jVp1CDRLlwJ24fiBR2qtPEqEuxZp5Z74pmXc40XKJBbxhIKdjU2UMwqEeTW9PxVveDBu2/2EiVyW1bzVEFBSQl33/4P16xZE3fvg0+4VavXJFotT/PVe16/9/tt1px5buHipf7DfL096rBDLHDdNyZA7O8kp4QIf37w9sBundwDd93kGjaoF5wcc1/xHwXS9XfJ+Wd4yQIX/f1Gp+eZTKtjVRoefeB216Xz/gkXV1UKHc+Z9qfzd/3Nd3u91ROuaAuoSvZD997qulpsLprEEF1fnTFVteJgS0j49tPX3UVX3Oh+tOoXeWlbt25zjzz5gnde9J4JNp2r5156042x6haJmoaQuPkff/cqgASXVQLGzbff7w1f4E9X5Q7FBVM53/57VMMhqBPz4Yf2ds+//Ja79V//yfU97u+T290nkP3psvuOgT3vFFi4aLH73ytvxWR4qaf8heed7n1Q5oalxIHbbrrK1apZI7SYMnRusyD9UssgK4h2x83XuGssu8gvL1QQ+2CbCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAgj8lQXU8/qeO2+IG/xXwE/VezVeuWIC0VamTBn3f/+8wnoA97de4PFDQwoMqkrxnbdcGzf4rzLuGzZuzNyH9V6O16678kJ38QVnxHRSDC5bo3rVHIPRweV29f6hBx/o7rdgtaokRJu8VA0hp+EDVNHgmisutESFcK/q6Hby8rhxo/qerx9w1rHMmj3PLVmS9x7lOR1HC0tkOO2k/jEdT3NaPqfpes1oGAHFg3IK/ut1l5PnPq1auIfuu9U1adwwYaBdr49HH7wjx+C/KlsogC63aOvSub3t5zbXoH7d6KzQY9krmeauW6/39uOfi+BCSpTJqWJG9WpV3SP33+56dO+c4/spuK1499Wr/sbb7otb3fmOm692NRIMkaEhFy63ocUVmA822bzw6jtu1Ojxwcn5dv/8s09x/7WkiUqVKubbNtlQ/guk1v07//fPFgMCGzducm+996lrv9++rnvXjllzNAZM34N7uOEjRrvPvvouxw/QU0/s7w49qEfWev4drffGOx/7D3O91Tg3Ghco+iGtrCCNSVKzZjVX1r4oBJs+GM8/5xT3+x/L3GtvfRizbnDZ4P119kVEJUj0YZ1b08VQWYrBpvFP5szNvSLCTBuPpSDK5QSPg/sIIIAAAggggAACCCCAAAIIIIAAAggggAACCBS0gH6X/8fVF7mDrex/tGmM7ynTZrpFi5Z4Y6ArgKqA676tW8Z0LLz9xqvd6DET3IRJU6ObcfWt5Pq1V1zgmu7VKDRPQdDpNoyAhgOePXe+97t7dSub3nSvxraf5jZeepWs5UtbPOOsU45346w8f069o6t7CQClstbRnaW/L3MLFi5OOr6gdZbb+OQ5tWZ2bP/59/951Qmiy/w6car7bfpMb5x6xT0UCN7XvKLVmc869Tg3xcaxf/O9T6Kb2KXHOi977JEdPNXwvlN/m+FWrFy1S9uNrqxhG46x3uSdkqgWEV03+rh2rRru7NOOd3tZAD/YFEvS8AWTzWm2xWzKli3t6tSu5TSEhNbxm+JI7dvu4y6/6Gx3j1VWUDwpXlNv/n/ffoNVDMiOkfnL/W6vkfETp3ivEwX/97T97GOVLVQtINg67t/G3XLD3911N96V4xDRGgrignNP9cr+BxNitm/f4f6wY5s01Z7PnPleokE9qxLQ1J63Eh/8HvHan3ruX3L+md7xaJiNvLTho8a4T2z4hROOOSJUEUJ+xx99mHUafjvHJIR2++3jzjjl2Jjdjh0/0T334psx0+NNWLN2nfc8N1uV8mBTckG5smW95AJVBY82DScxb/4C9/gzr9jnQXjd6LI83j0CJADsHvcc96o3zNvvD3DNmja2nvzVs5bTB9iRhx3sja2x0C7i0bZ3i6ZOF6No0wfUw1ZGJNk26pexXtkRjT0SbKWs9L+yC3XR7HdoL0tS2MfK92ePT7OHZfocYeOMDBk2wvuwCK6b0/35lmjw6JMvujJWAia3dts/r3Q9DzwgtIgylx4IjF0SmrnzwepVawqsPE+8/TENAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIGCEND49f2PODRm0wMHD3OPPPE/N/bXyaFAYfOmTdxx/fs59dYNBra9kuwXnOmu+scdoeW14X59ern92+0b2oc6Wb/zwWf296mbbAkA6rWspuL7tS0Ae9JxR9iwxCeGgr116tT0OjWOHTfRrbfgdrRV3mMPC6SWDE0eNORHb6jhbRZQTrYttpL50c6MWlfPV9UONDRBtOl5vPzae+7XSVPs+W/1hiluaL3FFd+4/OKzXcUKFbJWUTD6akuI+NnGPJ82fVbW9F2907plc6eYit80lvyUaTP8h/l226FdG3d6nABxqjuQw2H22jjESt+rDL7f1LlzjJ3jl19/zw3+YbhbtnyFN0uxrV7dD3B/O/tk13rv5lk95HXOD+nVzX0/dLj79IuBcTuHqgKFzkW0/TLmV/e/l992w4b/bMkimdWulYRyQKf27m9nnhRTLUDDHvz8y3hvyIvothTwb9emtb2f+lgliuxEFCUVTJ8xy1vn20FDvaQUTVOZ/Y5W/eD8c071Ou+qw6yattPRhnLQ++Z/VhZfnXxTbXo/qWNt2zatXItme2WtXqF8eUveONR68Y9zeu7RVqdWTe+9XalS9utVy6hCx6tvfeAWLFgUXSXu41mz51pCxpNuyU5TfyE9Rz3v5pYM1Mc6KHfu2NZLCPDnq1qIkksG/zDCjbb3By39BEgASLNzotIc+qBUwPuYIw/1Lj46RH2QaFrfUT283vwq5eM3Zd8oy6dBg3BJE2XlvfHux5bNl/ybb8XK1XYRn5Fjxo6Obfio0Vby/3z7sD/QPwSvZEubffZ2XezDVkkHybQN9mGYzHgva9etj9ncmjXrvIyymBlMQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEDgTyZweN+DvIBc8GlNtJ7/6k2t22hTD/enn3/NStiXchedd0Zo9gEd21nP3loxv+XHC7z+8ONId/9DT3nB0OBGVHx90eIlXvCySaMG7vhjDs/qwawqAHu3aOb1zJ4xa25wNe9+Fet9XSqQAKBKvjNtuXhVCWJWTmKCSv93szHdo+3rgUO8YOfiJUuzZqnM+wyrJqwe0xs3bXI3XXd5KChcz8qrH9//cHfvf57IWmdX7qjacZPGDSyQnh14VmVmBWLzs1W1oaWvtjhODStVH2zfWcLIQRaET6XpmI86vE/MUArzLMj8r/setQDwBOspn92pdLENZfDBJ196ve/vuOUaV88qS/hNZe0PtYCyqkNEqwAo4Py3s06KGSJAlSH+/eDjMRUl5KZEAsWknn/ifuuhH46RnXPmie7Lbwe7ufMW+rv3bstbTO1oC/7XrJHdCVczVq9e45554Q33/kefu02BXu0K0n8/dIT3fGpZlexWlsDhN21LCQDf2GvrtzwkiSjBQO/fdz/43F1xyblWVj8zoK+KCXoPHWHve72XFRPzW2kbluJwS5LoZlUSSuxMRvDnyWPQ9z+5rQkqb/vLb9iwyap7zHbzc0gYGPbTKPeD/an6w9mnnxiqgKDz2veQHm78hMmh8+9vm9vdK5Cxe3fP3uMJKEtKmUzRN5wywk4+/iivJ35wvc52se7Vo4vTRTXYfho52n3x9SDvohWcviv39SE+zjIJX7IMuZmRC5KOr6VVIqhg2XXp0pTNqDIzKjnj/5Uvl318+hCtZ+V9TjruSC9bStmQ8bIC/eejqgeqzqAvQspq1PLn2V/XA/Z3dQLlbPzlU7nVmDTHWUkXbVN/ugjm9xgqOkf64nPmqcdnHvtZJ3sXuvpWwiaZpkQUjZfkW2be1nTBEjAaS+pg+wLhP4+DenaLyeZMZl8sgwACCCCAAAIIIIAAAggggAACCCCAAAIIIJAp0LnDfjEUHw74ynosz46Z7k9YuWq1G2ABwXnzw72B9Xtu08aN/MWybvfbt1XWff/Ow48/HxP89+fpdvmKlV6v7OUrMnt/+/OqWNBYf/Gaqg0He15ruOD8LH/fs/sBoe3rGFSm/olnX7Hb3+Mdktdz+qMBX3uB3uACiiH069PTNW5YPzg5z/ebNmnolDCh7aqpF/2s2fOsjHxs5ec878RW1O/zSvQItgGff+u+HvhDcFJS91X2X+X7g03H/dkX37mfrVpzMPjvL7PZOqiqF706lUaD0Qf17OoaNaznL5p1q6GwW1nQO9pefPXduL3g/eUmW7n+R5+KrYRdq2YNi4fEDiVQ0yoUKP4SbR/Y++mDj78IBf/9ZfxqBy+++l5WFQx/Xtt993Z7W4WO4hY/yUvTEBCffP61DW8wObS6qi0ce7QN4bB/26wqClpAr6GjDj/Ehs4OV7iYYsNIvP3eAKchtPOzaXiD980lmqCjYUlattjLhgCJ/z7Pz2NgW6kLUAEgdbMCX0MZPxqj4813P3HXX3VRKINHF+DzzznF3fHvh52W0xgjp53U37tgBA9MGUkff/p1rhf/4PKp3FdJHX2QLFq0NLRfXbDq1qltY9dU8sYZSmWbBbWsAt03XH1xKECtMVMetOEDlBl10z8ud6eecHRo97PmznMDBw3LmuYHvc+zcjUH24Up3pcgLbx+wwYb12iyZYi97oZYNphKrSRqOgaVzTnXstp6dO0Us7gy23S8z7/0Vkw5ppiFc5hQwkqx1LIhJK61bL9jj+rnVK4n2pRhOXrcBPeQfZkbMXJM3Auc1qlmJXWeevjuUPakXofnXnydV7ZHmW43XneZa2BJFX777vth9nqZ7uINXeEvwy0CCCCAAAIIIIAAAggggAACCCCAAAIIIIBAfIGyNhb3HtZrPhhotZ9l3aTJ03L8Ldff0mqLFfxuAcFgJzD95h2v89mDjz7rr5Z1q46GuTX9PrzUxmZXEL9GYEFVHlBP5WhT4F+/UfsBcM3fsmWzW2/r50fby3rXq+y8SpQH23ff/+gUyNTx5tQUOH3/489dj26dQr+j16he1XWwUu/JVDTOadv+9Nr2W7225zdVSh4/YUrccvj+MqneKuag8e2DBupt/+jTL1pJ9yYpbU7nSQH7kjZMdLCpSvWzL74RdwgGfzklAbz46juuv1W7rlihvD/ZVbYY0j6tmntBfX8IB+2nrZXlVxWAYBs/cYo39HSwKnZwvu5v27bd/WyVsDVMgzpw+q2sN3RBT/fWe5+EznvXzh1cFevoGGx6XWh4blWByKkpCUCBcG+oiMBxKs7Tx6pOaDiOtWuze+rntJ1405Wko47BGoY7ODx4bSv1f8qJR3sxw2XLV3qJLeoQ3LlD29BmdNzav4YMyO01HlopyQfanqoUjPh5jGu3X+vQWnta59v6dff0EmxCM3iw2wXC79jdfjgcQFDguZfe9Hqaq7R+sJ1lQe23LItHmX3drcRH7wO7BGd72VSffTXISwAIzcjHBwpMa0wQvfGDF2p9aSgT56Kej7vOl021aNbEPfjvW1zTvRrluj2NFdTbPkxvsqB2Y8vKy62Vsy9hXTq39/4+/uxrd/f9j1tmZbi0jL++zBQkv8TGWjrh2MNdsCqBv4xu61p5IQXU9Rq4856Hg7OSuq+Avca/ufi80y0JIrvyQXRlZZIpG/Dtl59wn335nbvHyhkp69C/+EaXjz7WF7lTLJHiH1dfYhfOStHZPEYAAQQQQAABBBBAAAEEEEAAAQQQQAABBBDIo8AO65T34CPPhqrvqlPXpCm/Jdxihv0WrU5iwabf9YMlzv15jz4Z24van5fbrX4TLhuJC6j6wCr7i7ZKFjitUCH8W/V66wGt4Ynzo+3TuqWrHil7v86GGR5qQxn4Y9TntB/9Hr5gwWLvd/1gIFnjse9jSQXvmeWuBFeV/NCi+V5OZfD9pt7f4yZM8h/u8m11Sy445/QTQuO1Kzj8wivveMMspJoAoAPqFYlBaZoSKpZGxo3X9GibNGWamzN3vgX8W4Rm9bRtvvbWR1kxCFVyVrwmmmgw2dZPpnPh4sVL3XdDfgwlACgOU8u2q+SX4DAAfQ7qHjoWPVC8bdz4xOdhg3UE/d6qGpxlJfGDre0+rWxYh5LBSSnfHzTkJyvf/6MX8A+u3McSOr7s0dUbmkCxogvPPS0423tNTpz0m83/wob33hKal18PtmzZ6mSsRB8Ne+A3xbYqBJI7/Onc7n4BEgB2/znI8Qj0wa/xU55++N9ez2t/QZW1v+Pmq91/Hn3O6zmuIHWwzbUP048+/cp7Iwan5/f9devWeZlVKotflFpp+xA+yy6ADeOUmAk+j3LmfMyRfd011nNelRZSaf2PONT7knHtP//l5sxbELNqTbvAa/ydYyzzLV4WZHCFksoeswvSXNtONPstuFz0vpIHLrvobHfaif1jyh1Flw0+1vAGSna45c4H3E8jfgnOyvF+40b13YmWyEDwP0ciZiCAAAIIIIAAAggggAACCCCAAAIIIIAAAnkSUABXFX9TbQqAKhi+p/U6DzYFCWfYuN/50dSTukvn/V3VqlWyNqce2bMtTrFocWxZe3WkK1u6TNayurPRxiHX+OuKNag3sX5v1rjzJazX+Xbb1uo1a7xhDDTW+7r160PrRh9o/ejv6OrQuMiCl8m0hXbMqoAcTABQYLdB/T2dYjF57eGtfetc7N28aegwFETX/vKjqSf6kf0Otl7a+2SVjFev9RGjxrovvxmcpyoLGjK5caPYcv2DLNiebNNQANEEgPbWk7x48Qyr/pC5FfV0j5a032IzZ86a65RMkqittSQPVXhQoDqYRFCxQgVXz14TwQSAfS1JJNrUuz3ZpmENogkASjLYo2JFt9x66ee1bbL3+X+tSnO3Lh0saWHPrM0ohqRq4aocrg6fii8Fm97Pz7zwhtNQCAXZ1tv7VOfEuewEgILcH9veNQESAHbNr8DXHvrjKPfqm++7qy4/P7SvHt06WwmaMq5tZEweZaipBMmIUcl/WIU2nOQDleipUrmy9wEdXEUliJLtNR5crzDvd+7Y3i60VZwC637TRVDNL4mjEkj7WibVuWeeGBP8VykilZ3JvJhsyTwPbVq5lpa5F2wHdGrvldm5w3ru66LjN12Ejz6ij1f2Jhr8l53GOppvWYbKeqxtY9Hoy46yqI7rf5hVVyjlbybXW305UpbfCcccHhP811hH436d7H35UukoHXczy6xTYonfWjZv4q667G/eeEi6wObW9CXyaBtvRuMABZsuVtHnF5zPfQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIGCEyhVsqTrcsD+Tr3Cg009quN1XAsuk8z9ChYQP+n4I73x1INBV5XS/27wj9bjPjYYuodVEY4G6BXUL1u2tAU3T3Y9D+xsv1k39crkl7Tj12/3qg4wa/Zc99v0me6Lb773Oq7FGzJAv+/XrlXdaWzyYFtq5e+THRd9pe1rgflEm6ofK66wKwkAKv3feu/wGPejfhm3S9sMHmebfVq6U61DYNXAmOy//7HcvffR525Ggt/5g9sJ3teQCvF+5x89bmJwsVzvx0twqFG9mqtsySPqVa6mCgCKawTbKksKUeKGH78JzoveV2xFy2qog2CHTiVt1AkkwGgIa+0r2n4cnlxnSK03bcas6OrW+7+Ua26Vp3d1mAhVlb7r/sfcYw/e4W3T31HD+nXd3bdd7zq238+flHWrZIyBg4dmPS6oO0rQUAJPsG3evDluNZHgMtzfPQLZEdDds3/2moTAmzY+SUcbz6PbAR1CS3eyMWeibeTPY93Lr7/vNtq4MQXZ6tap7WpacFrB32BbZhd2ZVqlc1Ow22/fWObZt9/94H0o65nowjBt+mzvC8IRfQ9yGiog2BYsWOQesFJLv9h4MstXrvSyDxXQ36tJQ3e59bbX2Dp+K25JBCqN896Hn7uxv2aXjlHp/0svOCtmqAR9UOpC/OEnX3lfRrZYMoW+QLVvu6+X1ZVouAJ/vzqerval7pij+obG1VESwnffD/PGkVH2pb6oaFkNE9B5/7buovNOs2SDzGEOlADR3rIED+vTyzLHXrexpTITJPx9RG9btcz80qJhAz7/epCXgLLeSuEocWHHDsvQtAs1DQEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQKDwBOpbr/XTTzomZofv2+/QqkCcbFMigXrAl9rZQU2B2qZNGrtDrXJtayvtHuyRrN7Ir7/9UY4BSQ1VGw3Qq5f52Wec6A15rCECgnEHBfUVeNdfBwt+dum0v23/Q/fSa+9ZJ7oNoadQvnxZpwBvRkY4brHGfgtPNm6hagsrrZOegs5+h0HtRGXPK1kP77w2/eaunujB4LS29W0+BW6rWQUGBf+DCQbqsKn4x9fffr+z53bqR1+3Tp24K822WECybfKU6XEXbWxVmv0EAJ33coHS8lpB50wdJpNtShhQtYCgsWIswQSARg1iqxlo+/MWxB/OOd6+cxr6WVWZ86N9bkN89z2khzvu6MNCm+vZ/YDQYz3QsBa33f3fPFV3iNlYLhNq1qjudSaNDnOg86O4IC39BEgASL9zEnNECxYusSoAHziVJdGHYG7tpjseSDiOTW7rJzNPvf/79ekZ0+Nd6860D/1E4+gks4+CXkbjtNx0+/1OH6Tqaa8LoZou6ApYV6pUyQuGq1SRxciz2v0PP+M++OTLrOX9GcvtQ/YVKyXT2sYBCl5MKtvYR82th30wAUDB+XgZZu988Jm7/d8PeR/UwXGENEaOqg3cc+cNrsnOAL2/33i3lSpVcAf36uaCFxttb+hPI931t/zb/WEZf8HtKyNO5Z42W+mWG6+7zMus1HY1bkvvnl2dkiR+mzYz3q5C00ZY8skt9vrTsepLkvahL2r6YpPuVSFCT4QHCCCAAAIIIIAAAggggAACCCCAAAIIIIBAERfQb9BPP/LvmN+i1QFO8YZUWi3rDPjQfbe5JtYbXE2/o6vHvwL5wWD9OgvYPmQlzF949Z0cEwwqVixvpfTDvYgb1q/nlTwPVu2Nd3zqj6hObJdeeJbX6/h1G0Nev0X7TUMLRJMLNG/NGksAsCSAZJp+11ZFAiUylC2bPfyxengrNpLXpsCpeuirU16wDRk6MvgwT/d1DtpaleKjrFJvMGlBAfTHn33FhlBYm6ftaiVVKI42neege3R+9PHipb9HJ3mPa9iQCH4ra7bR4PLmTZtTGup6ky2vv2DTMAOl7dz5TYkk8ZqqTCTbtA9VGwjGgrRuMPEg2W3FW07xqkeeeMHtt29rq7yc+Z6Lt5ymKSYTHN4gp+V2dfq+rVu4A7t2itnMHxYbU9VpWvoJZKTfIXFEUQFlmn0/dLj7aMBXocBtdLmnnn/VTbZgcUE0XUB0YVJpHmUdXXTeGTHJCOr9PXb8pLQP9uoCrvFQPjRPXfj84L/cZL19+w4vw+/M8690zdv2cgf07u9OPusy9697H3XvfPBpaHnferttc+acuVY9IFz6RReWGoELihwvOPc0f7Ws2zlzF7j/PPqc04UzGJzXAuq5/+OIX9wb73wcc/HK2kDgTu2aNVzfg3uGvnjpeV55/R3u99+XxWzf38eHA750EyZNCc3v2L6Nl9QQ2HzcuyoZ9R+rjDBh0lS3YePGrG3oucg0+pziboSJCCCAAAIIIIAAAggggAACCCCAAAIIIIAAArssUM0Cq08/ck/Mb7san/y8S69PKXirg8mwgL9K4Kvnv/5Uxl+lwP3gv37fftGC/r0PP8U9+dyrOQb/tS0F6MvYmObBpiCtKuqqsrGqyU6c/JubOm2GU49uVSoIdjBTEoB6u19/1cXuIOsIp/Wyms3T/GjT79Op/Eat41CHuWBT73Q977w2Demssd2D7QcbAjpzTPXg1NTvV7TOfIo7BI9PZg9ah8Y5Vg14V1owocDfzuo1qVX8zalCsDpi+k3JFaVKZgfqNX2H94/3r79YrrdeOfpAQkjmwsWyXqd6vEdgn8GNpRpEV9wj2kKvxejMFB/rPaXhwYOv/egmBg4e5gb/MDw6OV8e672t96XOS0erRn7jtZd61aSDG19jcaefR4/33qfB6dxPD4FwqlF6HBNHEUdAGWoKLq+z8edVsiRe++rbIfEmpzRNpXo623AD0YuOxodX73ONa9/HyvpEx3xREH34yNFuxM9jUtrf7lhYweovbZygaCZYvGPRBUMftPobMmxEvEW8afow1Bee0jtLIOW0YA3zbd60cczsL78Z7BYvyRzrJmamTZDvKOthP2PWHOeX24+3nI6jXdvWTiWTgu2773/0xr4JTove15eaz78abENNdMzKtFNWo8aW0Yd8bsNKjB0/0f3w465nKkaPiccIIIAAAggggAACCCCAAAIIIIAAAggggAACyQtUt+D/vXf+08rltwmtpFLdDz76rJs1e25oen48qGZjzu/fzoayPetk9/XAIV5HRZVij9e2bN3i5i1c5HUkUxVaJQQoxDty1Bj3yeffum+tIq2q1qopoN2je2d31qnHu86d2rlghQDNO+OUY72YxLJlK7zl8+sfxQ7UMS8/W2U73lYtMofS9bc74LNv/Lt5vtVv+JfZ8MQ9zSnYvh86wv3vlbeDk9L6fomSJa0TanbFhbwcrIYyjg5nrKoCiSpr52VfBb2OElBmzJhjw0WvCA2xEdzvL2PG5xq3CS6b0311+m23X2tXLzJ8QWmLCdWqXs11taSVow/vY9UwyoQ2oYSa3yxmOcReZ7T0FCABID3PS8xRaXydg3t3yzH4rxUuveBMN3HSbzYuSnKlbGJ2YhM0hn1wHPt4y8SbNnXaLPfqWx8W+Dgj8fad6rQZs+a6VTl8+Ui0LQXY9YVEAXZl1VUoX94yHys4lUDq1qWjlWRplesm9m7WNO78t977JO704EQdt8rK5JYAoLGN9m3VMriad1/Pt7sdX6JW2cZHira9mjS08Y3K5Xgh0Qf9pBzG8Ilui8cIIIAAAggggAACCCCAAAIIIIAAAggggAAC+S+g365VgvyCc091Pbp18nrv+ntZvmKl9dB/N3N42zg9l/3lcrpVh8HZc+Z7w71qGZX/Vy9+/S6upkB+m3329v6OO7qfe/v9Ae6VN9538xcs8uYH/xkybKR1dpztHaviHjUsyKjfmD+0oXfnzFsQXNTrWTzAkgKmzZjl/nnNpTYues/Q/G4HdHBtWu/tBg35MTR9Vx8oaFwyEoxWJz0NC5DX1mH/NqEhBJRgMGz4qLxuLms9neuzTjs+67HuqEPjTbffF5qWjg+CHVE3WmVh+SbqZJnb89C60fV13tbbkNCJms558HgSLV/Q85W0cMjBB+YY/Nf+jzzsEPflt99bws30PB9Oq5ZN3bOP3Zvy+krwefp/r7vJU/O+75R3ygopCZAAkBLX7llYmTXHHtXXde28f64H0LtHF3fe2Se7R558Idfl8numyvHc/9Azbsy4Cfm96QLZnj7wcyubEt1pScs8U6/9vVs09W5r2dhJVSpbAoB9AKsag0ofadwYVQBI1PSFJtqUnajAfqKmD9QlNlaOSsvEK7uj9fUlT5Uaoq1vn56ue5zxWaLLKblBX96CTUkB0WnB+br/+x/Lo5N4jAACCCCAAAIIIIAAAggggAACCCCAAAIIIFBIAg0b1HPXXnGB62Od/PTbtd9Upvvt9wa4l19/L88d4zR0wEOPP5/VQdFLALDfktu1ae31zNfY9n5Zf1UZPvfMk+z38jLe+POLI799axjc6TNne3/+MSa6nTJ1hrvrvkft9/kmLjgmvYK2h1jFYj8BQL+dR3uAa9vqWZ7Tb+rx9q1y/SVt28Gm4HRuVXKDy8a7f0iv7qHJs2xI4QVWrXhXWm2LVVx+8dku2LFPwe7X3vrAqRJyfrSVVjki2nIqox9dzn8cPD5/mm5Xrsrets5btKy+SupraOpkm85x9Dxvse2uX78xaxPBfWZNtDuK+ei1mWyrbMtH20obsiK/Wo9unV3/I/rkujl1Fr3Yhuu+8vrbc10uv2fOnb/QPf38a27g4KH5vWm2l48Cyb9z8nGnbCo1gWZ7NbYL5slWlj08/kl0KwpUX/i30+xNN8wbiz06P78fb7KxVAZ8PtA99sxLbsbMOfm9+bTYXksL+v/Nvqx0tHJJ1SzIrwubvlTktZWLM3zDUitntM3G40nUdPFbb0NAKHkhehHLXreYl5CQ/TjzXp1aNaOTkn6s3v857y/pzbAgAggggAACCCCAAAIIIIAAAggggAACCCCAQAEIVLUS/Hfecq2Vge8UiiOojPg7H3zqnnzuVSslnvdOXBstFqBhYKNN5b8bflbXXXL+mV6ZcP+3c3WcUyWAsb9Otp79X1hgN/Hv39FtRx9PtxjEgC++dVdccm5oVncrUe63TRakjzf0r46nvP2tSjJAW75c2ayEBn/bG21YgHVJ9CT3l4/eHtSrW2jSkKEjd9nl7NNOcG0jVYmHjxjtvvh6cL4NYbBk6R+h49aDcuajP8UrkmlKTonXgskF6gC51gLw2q7f9HrS8MTJtooVVbG5YmhxdQjdEDhvs+fOD833H1SpXCluxQp/fvC2rHUGjTdU97JdeI8Ft1+zRnV32YVnhRI7gvOD94+yKgA63xpmuqCbkmB+HP6ze9g6IY8dN9FtsiG0aekrkJG+h8aR+QK33nil18Pcf+zffhsnu6ZK5cru/264wj4Uw+Nx+Ovs6q2Cz3OtDM/zL73ljj/9EvfPW+9xv02bGZOZtav72d3rqyf9AZ3auyce+pc79aT+TokAKkXkf4GJHp9cdCHUeCyptmhWW6rrF/TyGZZlJw8aAggggAACCCCAAAIIIIAAAggggAACCCCAQHoJlLfy+y89/V93cK+uoeC/jvId6/l/132P7VLwP7dnu279eq/8+ONPv+SmWpwg2KpUqewO79vbhgmoEZy8S/e//m5IzPrBzm9r166zarXW4S4yzEGlihVtSN/sqggxGwlMUBC5du0aWcMd+LPW2dDLqwI91v3pydy2b7uPN6RwcNnho0bHHGdwfqL7qhh9RL+DrOR9doBcwzS8+Nq7btbsud6wCom2kcz8OfPDwzL46zSoF1vt2J8Xva1WtUp0kvd4YqB0vXrfRyss7GHBfFWUSLaVK1PWhjPOTiDQekoqWBioQpFTDKdVy+bJ7sa1sIrR8dqChYvjTU552tWXn+f2tSE1ou0pS+RZb++5YFMF8dsshqj4VUG1P6wCtIbiOO/S691FV97kRv48luB/QWHn43apAJCPmPm9KQVezzz1OKdxbIJN4+HoQ/y/jz3n7rvzRu8i6gdoFafdp3ULd3z/fk7jyqeaWacL6NPPvRY3O2zRkqVWkmV1SmVQgsddlO7ronLDNZe4Vi2ahQ5b2WK6YChbcupvM9z0WXPdPEuIGD9hijc+zc3/uNz1OejA0DrBB9sjXzw0T2V6dK4TNZ1jZSnm3ht/h1uzdm3Mpr4ZNNQu+vNipiczYfaceXG3mcy6LIMAAggggAACCCCAAAIIIIAAAggggAACCCCQ/wL6vVg9hZ986C7X0caXD7bN1jP37fcHuH/cck9wcoHcV7xCwf9Rv4xzLZvvFRpOtnHD+k5jmedfOfrVMc+hgiVA+E3HstSCles3bAwF3GvVrO5q2G/+U6fN8BfN8bZC+QquetWqofnargLHS5YuC01P9oHGag+2pb8vczN3IUivjoqH9z3INYsEohU/OOeME92Jxx4Z3F3ovuIR0XZgt07uqYfvyUoa+OzLge6Tz7/xFlNSwVaLa5Sw8vrB1rN7ZzfFYiTJtO5dO8YsNn3GbItDbcmarg6WK1audMFhlPV89qxTy+uYqd7nuTW9H+ruWcvVqR2uhqze/wpg+221VYGYM3eBa9igrj/Ju23fbl/vPROamMODfW3Ii2hT7GjSlGnRySk/Pvaofu7s00+I6ZQp67vuf8yLJV1w7qmhmFL9enW9eNY/b73XhsDYmtI+9d594OGn3ZIlsZUeVL16hQ0BoWFEaEVPgASAND5nGjfn7xefE3OEyt56xEpsrFixygvy72/ZY7UDH2pVLbNOvdbHjp/kJk7+LWb93Cb88ccK98vYCRbM/muX7jisTy93QMd2ISqVOfrok6/cm+9+7MaYbfDipAUb1g9fMEIr73wwM04Qvnq1qja+TCWnC09uTRc7jUOTW7KAfQ9xy+JUIfh64A/utTffz23zzEMAAQQQQAABBBBAAAEEEEAAAQQQQAABBBAoAgIKdjZp3MDdYtWAO3VoGzpiBetU9v/uBx4PTU/0QD31o+XWFTxVsDqZtnDxEq9He8mS2WEnBd7VQ9lvGsa4ug21GxzuWNV1ly9f6VRNIFHTb+nRtnx5uCqvKhavWLEylACgoHLzvRq54SN/sQDptugmQo/3rFPT7d2yaWjaBksomDZ9Vp7iJgrWd+8SDoBPmDTVqgnkHg8IHUDkQckSJeNWK65RvapVgugWWTrxw0ZWol9/fps+c7ZzOxMA9Hr61TpAttuvtT/bu+3ds6t7/uW3E1YxiPf8tQHtY/t2C2jsbEoS0WtNyRZ6fauVKFHCNbXzpgoCiwK9+HeuErqpUmUP6zUfG5hXAHvOvPmhZYePGhOTANCzW+ekhjVQB81op11tfNyEybvcK766nb9zzzwx6/n7B73MXuNX33CnNzz0S9Y5WK+n1q2yKxYUL55hw390dj3sOQz+4SdvOX/dRLcrV65242yojvkLFiValPlFTCBxt+Mi9oT+LIerLKyLbdycaLaSSqA89fxrbqllQ+nC+PPo8e7jz76JKY2inuvHHNXXxqwPj3fyZ/Ep6OfR88ADYnbxqZU4ue3u/7qRlskYDf5rYQXmc++d79yUadNjtqsJuVUN8Fdo0qh+zOvBn+ff6uI4eWrsPtq2aeUvwi0CCCCAAAIIIIAAAggggAACCCCAAAIIIIBAERUobr9Dt967ubvxustc7wO7WJA0u2e2OrF9OOArrwOhgtapNFUjvveOG0J/F513RtKbUFVdBSKDTcH2YJBXy1xs2wzu585brnW9e3YJrpbj/Q7tw5UOtOD0mXNCy6tHc2YgOXuyAskd9t/PqfNkbk3B6n1atXD19qwTWmyNDS3w68QpoWnJPmjapJFr3DA7uK711HlTgdei0ob+OCrmUNu1ae1ZxcyITOjcoZ2XrBKZ7IYMGxlKHlDV5UmTp7lNm8KdU9u03ts1btQgJige3J4SBhpYL/iOdo6DTa8/bXPxkt+Dk23fI0KP9UAVAaKJGjEL2YT6NvRBvHjL+F+tSvSmLfFWSWqaXntnnnKcJZ+Eq1Jvss667334uZuhpAxrSrR58bV33HJLcgk2dRI+9aSjvYoJwenc/+sKhD+N/7oOafXMdTE6ykrC9LKMnWhv78+/+s598fWgrONVSf53P/wsZnwdZdX1P/JQ186qA0S3kbUyd3IUiDdeyls2XtLqXEqd7LFHRRtnJTYDMbiTpVYiKF4p/pOPO8pV3qNScNHQfWVGdu3cwe1lXxZya0oKGW0VHKIJCt0O2N/Vq1s7t1W9eW3toq3XjUrytLILjdYpXapUwvVYAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQKDgBZo3a+Juvv5yd6gNRVu6dPZvtyqR/u13Q90zL7zhfg+UPE/2iFQiv1ePLqG/k48/yn6TbphwExoPft/WLb0e28GFFdTduDE7EUGB2obW0zy4nz4HdXdHWDn7YKWA4Db8+3vY7+dnnHyM/zDrdpR1kgy2JUt/dxOsMvK2bVuDk92B9pu3yrznFi/RkAUnHXdkTCWEefMXuhE27nle2v62zxKBqgiK6Wgogg0Bl7xst7DWUafDgYOHWsB5VWiXGnpBpeoVu8iplStX1p152nGubJnSoUUWLFzsxoybGNNT/YcfR3ol54MLK+Der09PV8EqJOfUlATT79BeNnxAuErzxk0b3Tff/RCzmsawX7Roacx0DZ8QHFIiuoBeo8f3P8wbTiI4b/36DW7oT6OcEnDy2lRV4MRjD495nhMmTnWfWCfgdbYPNe99PniY9fQfHvLTEA0HWmWAI/olfi/l9RhZr2gJZNdiKVrH/ac+2uY2bsvhfXu7SpHe+7NsLPZ3Pvgs5gNQY39oPJ/G1kNc4+n4rW6d2u6iv53uxlk2mcqc0HZNILcLjEojdem8v2vetEmuO1Fg/nNL4LjswrNCy6mk0FWXn+duv/uh0HQ90Jei9vvt4/RlK7dj8FecOWuu92UkmK1Wv24dd8Ulf3N33fdojkkMeu2ovEzP7gd4CQS6kGzZusU99+KbXoaZMs1oCCCAAAIIIIAAAggggAACCCCAAAIIIIAAArtHQOOh33vnP137thZUDvT8V8cw9ai++4HHvPHN83J0gyyoeJZVAQi2alUru3usKsAlV97sVIY8XqtovyufboH5NpYA4Jdu95ebOOm3UOBYCQGqYNv3kB7+Il5V3QM6tfc6RX7wyZdxxzBX57nbb77aNbIAfbCttLjHBx9/EZzk9SpXNd/j+/ezYQCy4yUaPuDqy85zk6dMN6NwSXh/A5fa7/YamjnYFAD3OgcmGMI3uE7w/v52rkpap0+/zZ23wCmhQNvNa9ti47wrISHqncz2VOEg2oN92ozZbpRtb/vOYxpv5eyDbabFpkb8PMZp6GS/KZFCww2ceNwR7l2LW0U7JSpYroD6gV07xSRdDPx+WNxz8MuYX72q10cdfoi/G6+qxMmWlKHXzZvvfJw1PXjnuKMPs9fu8TGdGecvWOyGDf85uKh3X8NGfPjpl+7SC8Jxms4d27rLLzrbPf70S27tuvCQFH7H3VNOONoSGrKHtdAGh48c7TSsg96HeWmqCH6CBf+VHBNsGu5ZHYAnTA5vWxXCP7JKH0ouCQ5NrSSZk48/2g0ZOtK8pgU3xf2/oED2p85f8Mmn41MuU7q0Bf8PsnF72oU+vJUl9+kXA50+AIMlc/Qctm3b5n0I9D+ij+scGLc+I6OY62FVBPoe0tMuUJ+k49NN22NaFCkJowM9/9xT3VcDh8Q95h7dOrmLLdkimHEZd0Gb+NpbH7hz7cKn7De/aeiAs0473h4Wcw89/ryN/7Pan+X227eVe/CeW9xeNqZTMk0Zjh8N+Np1snI3/lhK2v4JxxzuNGbTA48869ZayaJgU+mj66680PuSFcy0VGkjjUVE8D+oxX0EEEAAAQQQQAABBBBAAAEEEEAAAQQQQKBwBRQkfOeVJ71y6tHArwKFr7/9odMy+kumqQS9Ohf67WvrKa3OhPtFhpNVR7OBn73pnvnf6xaH+NT9Yfs+UiCyAAAnuklEQVRSUwC4t1UMOPmEo9xhh/Z26oEcbAqgqke3gv5+0xDHo34Z62bPmW/B/Oxgp475thuvcnX3rO2ee+nN0O/XrWy4g9v+eaXralVuo+37oSOcepNH208WkP3afss/vv/hoVmqUvDGC4+6u+5/LFRped/WLdwN11zqPZ9ohQCNjT7gi29D20n2Qe3aNVzLFk1DQwfPnbfQabz7XWmbrbPeRwO+dB9/+nXKm7nswrNjEgBGjBrjbrnzAYs1ZQawo4HsP6yixHsWiO5uvdSV8OE3Delw6w1XeB0XX3n9/awe8OpseN7Zp1gH1dOcgtLBNmfuAvf5l4PidlpVD/pnXnjdHXnYwaH4mDrL3nfnja56tSrWGfZTb4hsbVMxlgttH9dcfoFVIogNdz7xzMsWE8muQOEfx3qb9sXXg92R/Q6xqgF7+pNdubJl3Xlnnewljjz61ItOsRY1TT/tpP5OCSLRYbvXrV/vvvhmsJfUkbWhFO4okUfvsX6H9IpJlBhniRjq/a/OmsGWWZVhmOtiiTN/O/vkUOJDy+ZN3Gkn93d322tc7zfaX1cg9h3x17XY7c9cF21dxC6wQLOC98E2ybLSlMm2dl04cOsvo4DuzXc84D57/0ULQmeXU8mwbd5163Ve+RFdqGjJCQy1bEllswXHLNKH8KAv3nJPPveaGztuovdh3NTKHx1rmYQqUaSLo8aUCWZextubLu76EqMqAMoa85uyxnRBPPaoQy1b7DfvwqQvPsriUltlGYY6nypBE/2C529Dt1stIWTY8FHuu+9/dH2sDJSC/2oK7F9oSQoHWVaeysNMt6w+tRbN93KH9O7uVCUg2PRcvrOsT41HREMAAQQQQAABBBBAAAEEEEAAAQQQQAABBBDYfQL3/eumHMvxq3z/i08/mNLBDbTffs8478qsdRT0vfe/T7rnnrg/VIlWv0XXqlnd3Xrjle6f117idRjbauX11bs+p3Lp+m35SwuKDhryY0xPd/VcV0n5M2y882CHuqpWbeAfV1/sValVL32VPK+7Zy3X0n6/9ju6+QerAKh60T//0ltxK97qufzr3secet8HqwbouTSxjnbPPX6vt/7c+Yu84K4SAILH4u9HHeTu+PfDbnUee/+3bLaXq1JlD39zXiBX5f+XWA/uXW2ZwfrUe5xv374tZtfy3GpVBfwEgOgCmj985Bj3ofU6P9UC4cGKBgrw33HzNRbXOs0SO+Z5q+5tSQ/VqlaJbsYLSA/4/BtLAhkXM8+foE6wSmY59cT+WbENzVOA/6brLndXWRWH0WMnesewV5MG3n6i8RJ1mn397Y/dex997m825vbXiVPcy6+/6675+wWufGB4Ab2m/3bWSe7Yo/t6rxElyqiCc7xho7WfbwcNs2STH2Je5zE7zGGCKnlrKIVgh1EtumjxUvfCK2/HTZTQfL3G33jnIxseoZdXHVzT1GRx+knHeMOBfD90eOZE/v1LCmRHH/+STz+9nrTGj1dJlGAZfx2hMogGWMmaYDZevCOfaOPavPrmh94F0g/6ajl9eP2fZWFdf/PdcS+G8bb1V5/2rX0BOWHc4a5D+zYhipbNm7pHH7g9NE0PVJVhxszZ3gV8H/uykFtTttab737i2lrP/m6WVBBNGKhZo7o7qGf10CbUA1+ZXnptaHiI3MbV0YrKoHzWxnpSWaN2bfdxxS0b029NmzRy+sut6cI1YtRoL6tz/kISR3KzYh4CCCCAAAIIIIAAAggggAACCCCAAAIIIFDQAuUDFWULal8jLTD76JMveL2q9dtytCkQr2SD3NqmTZvdMBsPXcH5363neLSts8oA6iBXq2YNd+jBPSy4Hx5DXoHWGt1z3ocCnzNnz3X/sUq34yeGS9UH96Xe21dcd7t75MHbXePI0AGKnygxIJgcEFxX97X+40+/7D776rvorKQfq/NdlUAPeA2j8Nv0WUmvn04LLl+x0gLm77nadt569+oaSgLQcdaz6g36y6kpwWDQkJ+8oPx6q1ScW7vNhkpWnKTXgV1iXh/qjd+9S4ccV9+yZav7ccTP1pHzlRyX0Qy9Tj+xuJsqNBx9eJ+YBJAqlfdw+supZSZFjLY4zOtu6e95S+goY51CL7FhCKJxKO1TnTOVpJNbmz5zjvvvY8+5h+67NdzZ1DqD/ss6Bh936oWhChy5bYt5fz6B7Kjgn++5FblndORhh9gH2gExxz3sp58tsP9+zPR4Ex5+4n9u3K+xPbaVBXT0kYfGW4VpcQSW2BAA+qKjpAt9oUjU5s1f4J5/+S3366QpiRb15i+woPqjT79kvfSHufWWyZhbU7bkCMuue/3tj+wL07LcFg3NGzV6vLv/4afd99bbP5Wm8kHKWLv/oafdmPETU1mVZRFAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQSKqIB+q37trQ+934bVE1tjzafS1GtZvar/dd+jceMU/rZUBv5f9z3innvxDbc4znC8/nLRWwVdh1pygX67Vtn1aGn06PJjxk9wt1swWUMCRMeojy7rP/YSDGbNdY88+aJ74934Y877y+Z2q46ZLawCQLB3uYLo04poAoCe66Qp09x9Dz3lvvrme7PfnNvTD81TJQUNU33vf550U6fNDM2L90CvQyUBfPDJFykFsFevWWudab9xt1vVhrnzFsTbdGiaqmYryePt9weEhmUOLRTngV53g6wCs4aSGD12Qpwlkpt0WJ+e7jirNBBtk6dOd8+++GZ0ctzH6jz82VeDYuY126uRu+KScxJ2Jo1ZkQl/GgEqAKTJqVSGzyUXnBnzZtQF4annX/PK3SRzqFr+MfvA+o+NGa9x3f2m8ihnnHyMN4aPSpvQchdQGf2hlnjxf/960J147BHuiH4HufLlysWspDFUBg4a6t6yC4S+ELVq2SxmmXgTFNQfaaWOFtsXouP7H2ZjJPWyMjKx62p8Gl18FPyfPHWaO+GYw+JtLu40ZdT9YEMZLFq01Btrqf8Rhzp96Ae/cARX1BegEaPG2kX1S8uQ+8XNmTs/OJv7CCCAAAIIIIAAAggggAACCCCAAAIIIIAAAn9ygRUrV1mwdoAbY8Pg9u7RxarVdnUq6R4dy91nUDVZ9WofNvxnN9h6eI8aPc5K5q/1Z+d4O3feQuu9/Lz3m/ShBx/oDjmou6tdq2bc5RVs/nnMBCtD/4s37v0MC9Brv4maN8ytdcKbM2++N8b6Ccce7vZq3DDHIXYVX/lq4BD3qQVVR/48LmHnvdz2X8+G3G3csF7WuO5KLNBz9svk57ZuOs9TEsBd9z/qJVXIs9lejUNDRgSPXTEHOb79wadeHEW+yTYF8O/771PeEMXHHNXXtbdKx6VKloy7umxH/TLeSxhQr3kNw6xkkWTab9NnugceecbrDHlUv4Ndxw5tbXiL8nFXVXWB0WN/9YZCUOxFlSjy2mrVrOauvvx8V9GqPgfbpk2bvOet40qmqXq0EmLa79fa1a+3Z2iVEyy2NfiHEV5H1NAMHvwlBIqVr9oouXfBbuCoXa+RK20lMNS22It4zepVu+EoCmeXe1Sq6PaMUx5lq31AzrJy7grmJttKWxmeBvX3dCUiH4ba1iLLpltr2VZqjRvVdyoxEmwaz2TxkqVJfzgG1y2o+7pQRj8EV61a7X2IJ9qnxg2qaSWDigVK4K+z5y+HZDL+Mmy9ypUruQb16npjDbVo1tiVtRIzWlcX6wmTp7rpM2a7ZcszL1w1rfxRlUDihS48f1iZI5X2yalVKF/e6ThbNGvimttfLdvGxo2bnUrvaywcZU2utOerpvI63phBNo6L32ShMYNy+8Kj0kw6tjq1anj7UCmeyjvL16yxrDiNdTTJhpBYZOf+99+XOSVAxGsarqCurVsulAyxwxIZfs9xLJp42ynsaVWr1yjsXbI/BBBAAAEEEEAAAQQQQAABBBBAAAEEECjiAqtWLM/1d9fCfHoNG9SN/C67a3vX7+Rz5y/MdSNlLX6g36Or2p86v9Xds44NO1vFG5tdPff1u7gCld5v2JY4oJ7eyQZe/R1rzHLFRzRmfLOmjV3dOrW8Ww27u2bNGrfQfh+fMGmqxQOWulWrV+c5KF/WyqLXsrLynSzA28rGdK9lyQZ6fmrzFyz0erdPsN/I59lv5attP9u2Ja4M7D+HeLcH9+ru7r3zBqf4htpGC+w+8sSL7uEnno+3eKFN0/mrYQ7BttLOnc5hKk1DN6hMv55ftwM6eHEHxabUNmzc6CZbooB6x8+YNcerbKxkjLy0MmVKe51dmzRuYIkozbyqCnoOatrPTEsGGTTkRy9e9Mey5QmrQuR0DBp2Wa/zBvXruk7772fxswbefhUjUpBdz0fDcE+dNsOzUjLArjT5NbF9BGNX2p5fgSKZ+JW/fx1jwwb1LN5X2p/k3e6w+NQSG55gxYrM2Gptiw95wxoE4ksbrNrCAkuYSGV/oZ38RR6UKl3aVahYKevZzpme/h2tSQDIOl3cQSCxgL6MZLcd9mUm+1F+3AtuP9UvSqnsP7gfrVeQ+0rluApqWSVAFC9R0svs1HMvllHMZRQLj4Cii6QtEHMI3vJxpscsyAQEEEAAAQQQQAABBBBAAAEEEEAAAQQQSCsB/e6Z02+fCo4F5/kdrPx1duzY7jZZgDG4TFo9ud1wMIXxu7L3C23g99iC8I8+D1Hm536KFy/uLjjnVHfbTVdlnaVVq9e4i6+40XpkpzZkb9YG0vhOPE8dbn6aanuZL4vY3/Dzfz+x+yiI56Nt0oqGQFFMAGAIgKLx2uIo00Qgvy8k0adV0Nv391dY+/H3t7tvvfGILEuPhgACCCCAAAIIIIAAAggggAACCCCAAAIIIJA3gcL4Xdnrc5ffPe8iT7egn4d6We9tVQaCTZWZx09I/17DwWNO9n5Be/rHkfmyyOdemf7GA7eF9XwCu+QuAvkuEO4Cm++bZ4MIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAII/DUEVKK+zT57h56sxqhfviJzKOHQDB4ggAACBSBABYACQGWTCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACfz2BDRs3ueEjR7ux4ydmPfmPPv0m6z53EEAAgYIWIAGgoIXZPgIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAwF9CYMHCxe7BR54JPddVq9eGHvMAAQQQKEgBEgAKUpdtI4AAAggggAACCCCAAAIIIIAAAggggAACCCCAAAII/GUEtm7d6pYtp9z/X+aE80QRSEOBjDQ8Jg4JAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBFIUIAEgRTAWRwABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAIB0FSABIx7PCMSGAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIJCiAAkAKYKxOAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAukoQAJAOp4VjgkBBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIEUBUgASBGMxRFAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEhHARIA0vGscEwIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAgikKEACQIpgLI4AAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggEA6CpAAkI5nhWNCAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAgRQESAFIEY3EEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQTSUYAEgHQ8KxwTAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACKQqQAJAiGIsjgAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCQjgIkAKTjWeGYEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQSFGABIAUwVgcAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQACBdBQgASAdzwrHhAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAQIoCJACkCMbiCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIpKMACQDpeFY4JgQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBFIUIAEgRTAWRwABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAIB0FSABIx7PCMSGAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIJCiAAkAKYKxOAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAukoQAJAOp4VjgkBBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIEUBUgASBGMxRFAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEhHARIA0vGscEwIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAgikKEACQIpgLI4AAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggEA6CpAAkI5nhWNCAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAgRQESAFIEY3EEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQTSUYAEgHQ8KxwTAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACKQqQAJAiGIsjgAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCQjgIkAKTjWeGYEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQSFGABIAUwVgcAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQACBdBQgASAdzwrHhAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAQIoCJACkCMbiCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIpKMACQDpeFY4JgQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBFIUIAEgRTAWRwABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAIB0FSABIx7PCMSGAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIJCiAAkAKYKxOAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAukoQAJAOp4VjgkBBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIEUBUgASBGMxRFAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEhHARIA0vGscEwIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAgikKEACQIpgLI4AAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggEA6CpAAkI5nhWNCAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAgRQESAFIEY3EEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQTSUYAEgHQ8KxwTAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACKQqQAJAiGIsjgAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCQjgIkAKTjWeGYEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQSFGABIAUwVgcAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQACBdBQgASAdzwrHhAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAQIoCJACkCMbiCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIpKMACQDpeFY4JgQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBFIUIAEgRTAWRwABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAIB0FSABIx7PCMSGAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIJCiAAkAKYKxOAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAukoQAJAOp4VjgkBBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAIEUBUgASBGMxRFAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEhHgRLpeFDxjqlYRoYrWaqU27FjR9af3dH/1jKnxVuPaQgggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCMQTKFasmDfZu7X7uvX+yyjmSpQoMuH0rKdWZI5YuBUqVnI7tm/3EgC2e7e6b+F/LxEg876XDLBdWQGZyQH2rzffe8Zazn/q3jpZj7KX8edrC9o4DQEEEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEBgtwv4wfrwgShonz1FHcvVvEnB4L43zZa1wL7malZmoD9z+QybXqxYhjdftxm2nfj709bTt6V1AkA0AO9lWxQv7mlm/hsL663jB/p3BvC9sL/F8jPD+TuD+t7j4P3YbVkGQJyJTEIAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQQQKHSBzKh+aLfRSdlBe4X3M1v2NAv6ZyUA+HNDm8vxQTR2neOCu3lGWicArFy21JUrX9GVLVfelbDy/8ETk5Obt4xXliGnJZiOAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIBA7gIK+m/dstlt2rjBrVuzOveF02RusfJVGxWJbu4K7JcoWdLGWSjlSpUu7TKsEkDJkqVccbstXqKk9ziZBIE0cecwEEAAAQQQQAABBBBAAAEEEEAAAQQQQAABBBBAAAEEEEAAAQR2s4CGnt+2dYsF+u3Pbrdt3eq2bdtqQf+N3mMNUV+UWpFJAEgGVQkASgwoUdwKG+y8r7EZ9KcRHPz73nIZNojAzqoO/nrhfRTzkgvC03iEAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIFDYAurVvn37Nhv3Pdy/fcf2HZnTdx6QAvhq6r2v5bW4AvreNAX7t23zpm/3botWcN97Egn+SeshABIce8xsnUQvI2PnSY1ZgAkIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAgj8SQXUNZ6GAAIIIIAAAggggAACCCCAAAIIIIAAAggggAACCCCAAAIIIIAAAkVcgASAIn4COXwEEEAAAQQQQACB/2/XjmkAAGAYhvFnXZVGZAjzeoYAAQIECBAgQIAAAQIECBAgQIAAAQIECFxAAGAHBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEAgICAACDzRCQQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAQABgAwQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAICAgAAg80QkECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQEAAYAMECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQCAgIAAIPNEJBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEBAAGADBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEAgICAACDzRCQQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAQABgAwQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAICAgAAg80QkECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQEAAYAMECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQCAgIAAIPNEJBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEBAAGADBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEAgICAACDzRCQQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAQABgAwQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAICAgAAg80QkECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQEAAYAMECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQCAgIAAIPNEJBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEBAAGADBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEAgICAACDzRCQQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAQABgAwQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAICAgAAg80QkECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQEAAYAMECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQCAgIAAIPNEJBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEBAAGADBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEAgICAACDzRCQQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAQABgAwQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAICAgAAg80QkECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQEAAYAMECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQCAgIAAIPNEJBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEBAAGADBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEAgICAACDzRCQQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAQABgAwQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAICAgAAg80QkECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQEAAYAMECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQCAgIAAIPNEJBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEBAAGADBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEAgICAACDzRCQQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAQABgAwQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAICAgAAg80QkECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQEAAYAMECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQCAgIAAIPNEJBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEBAAGADBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEAgICAACDzRCQQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAQABgAwQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAICAgAAg80QkECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQEAAYAMECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQCAgIAAIPNEJBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEBAAGADBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEAgICAACDzRCQQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAQABgAwQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAICAgAAg80QkECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQEAAYAMECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQCAgIAAIPNEJBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEBAAGADBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEAgICAACDzRCQQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAQABgAwQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAICAgAAg80QkECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQEAAYAMECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQCAgIAAIPNEJBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEBAAGADBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEAgICAACDzRCQQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAQABgAwQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAICAgAAg80QkECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQEAAYAMECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQCAgIAAIPNEJBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEBAAGADBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEAgICAACDzRCQQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAQABgAwQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAICAgAAg80QkECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQEAAYAMECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQCAgIAAIPNEJBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEBAAGADBAgQIECAAAECBAgQIECAAAECBAgQIECAAAECBAgQIEAgICAACDzRCQQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAQABgAwQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAICAgAAg80QkECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQEAAYAMECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQCAgMBRcdvGfx2ENAAAAAElFTkSuQmCC"""


async def make_profile_card_png(member, metrics, trader_level, xp_current, xp_required, badge_ids=None):
    """
    Genera la Profile Card PNG usando il template Standard creato in Figma.

    Il template contiene solo la struttura grafica; il bot sovrascrive in tempo reale:
    avatar, username, trader level, rank, saldo, patrimonio, accuracy, trade,
    posizioni, streak e barra XP. Badge e collezionabili restano fuori dalla PNG.
    """
    if Image is None or ImageDraw is None or ImageFont is None:
        raise RuntimeError("Pillow non installato: impossibile generare la card PNG.")

    import base64

    theme, theme_id = _profile_card_theme_for_user(str(member.id))

    # Template Figma 2048x1152.
    template_bytes = base64.b64decode(PROFILE_CARD_STANDARD_TEMPLATE_B64)
    img = Image.open(io.BytesIO(template_bytes)).convert("RGBA")
    draw = ImageDraw.Draw(img)

    # Palette coerente con il template Standard.
    bg = (11, 18, 32, 255)          # #0B1220
    panel = (24, 34, 51, 255)       # #182233
    text = (255, 255, 255, 255)
    muted = (226, 232, 240, 255)
    blue = (96, 165, 250, 255)
    cyan = (56, 189, 248, 255)
    green = (34, 197, 94, 255)
    red = (239, 68, 68, 255)

    # Font proporzionati al template 2048x1152.
    font_name = _load_card_font(128, True)
    font_meta = _load_card_font(58, True)
    font_num_big = _load_card_font(86, True)
    font_label = _load_card_font(38, False)
    font_xp_label = _load_card_font(42, True)
    font_xp_value = _load_card_font(42, True)

    def clear_rect(box, fill):
        draw.rectangle(box, fill=fill)

    def write_fit(xy, value, font, fill, max_width=None):
        _draw_text(draw, xy, str(value), font, fill, max_width=max_width)

    def text_size(value, font):
        bbox = draw.textbbox((0, 0), str(value), font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def write_center(box, value, font, fill):
        x1, y1, x2, y2 = box
        tw, th = text_size(value, font)
        draw.text((x1 + (x2 - x1 - tw) / 2, y1 + (y2 - y1 - th) / 2), str(value), font=font, fill=fill)

    def fmt_int(value):
        try:
            return f"{float(value):,.0f}".replace(",", ".")
        except Exception:
            return str(value)

    # =========================
    # AVATAR
    # =========================
    # Nel template il placeholder avatar è il cerchio bianco in alto a sinistra.
    avatar_size = 300
    avatar_x, avatar_y = 48, 38
    try:
        avatar_bytes = await member.display_avatar.with_size(512).read()
        avatar = _make_circle_avatar(avatar_bytes, avatar_size)
        img.paste(avatar, (avatar_x, avatar_y), avatar)
        draw.ellipse(
            (avatar_x - 5, avatar_y - 5, avatar_x + avatar_size + 5, avatar_y + avatar_size + 5),
            outline=blue,
            width=10,
        )
    except Exception:
        draw.ellipse(
            (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
            fill=panel,
            outline=blue,
            width=10,
        )

    # =========================
    # HEADER TEXT
    # =========================
    display_name = getattr(member, "display_name", "Trader")
    rank = metrics.get("rank")
    rank_text = f"Rank #{rank}" if rank else "Rank N/D"

    # Copre i placeholder USERNAME / Trader Wood | Rank #1.
    clear_rect((410, 70, 1500, 330), bg)
    write_fit((410, 80), display_name, font_name, blue, max_width=1080)
    write_fit((410, 258), f"{trader_level} | {rank_text}", font_meta, text, max_width=980)

    # =========================
    # STAT BOXES
    # =========================
    balance = metrics.get("balance", 0) or 0
    net_worth = metrics.get("net_worth", 0) or 0
    accuracy = float(metrics.get("accuracy", 0) or 0)
    total_trades = int(metrics.get("total_trades", 0) or 0)
    open_positions = int(metrics.get("open_positions", 0) or 0)
    current_streak = int(metrics.get("current_streak", 0) or 0)

    stat_boxes = [
        ((42, 395, 656, 616), fmt_int(balance), "Saldo", green),
        ((714, 395, 1330, 616), fmt_int(net_worth), "Patrimonio", cyan),
        ((1390, 395, 2004, 616), f"{accuracy:.1f}%", "Accuracy", green if accuracy >= 50 else red),
        ((42, 662, 656, 884), str(total_trades), "Trade", text),
        ((714, 662, 1330, 884), str(open_positions), "Posizioni", text),
        ((1390, 662, 2004, 884), str(current_streak), "Streak", text),
    ]

    for box, value, label, color in stat_boxes:
        x1, y1, x2, y2 = box
        # Copre solo l'interno, lasciando bordo e angoli del template.
        clear_rect((x1 + 18, y1 + 18, x2 - 18, y2 - 18), panel)
        write_center((x1 + 20, y1 + 45, x2 - 20, y1 + 120), value, font_num_big, color)
        write_center((x1 + 20, y1 + 135, x2 - 20, y2 - 30), label, font_label, color if color in (green, cyan, red) else text)

    # =========================
    # XP BAR
    # =========================
    # Copre e riscrive la parte dinamica della fascia XP.
    clear_rect((92, 960, 1958, 1026), panel)
    write_fit((98, 972), "XP Trader", font_xp_label, text, max_width=250)

    if str(xp_required) == "MAX":
        xp_text = f"{xp_current} XP"
        pct = 1.0
    else:
        xp_text = f"{xp_current} / {xp_required} XP"
        try:
            pct = float(xp_current) / float(xp_required)
        except Exception:
            pct = 0.0
    pct = max(0.0, min(1.0, pct))

    bar_x, bar_y, bar_w, bar_h = 315, 978, 1300, 30
    _draw_rounded(draw, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), 14, (42, 54, 72, 255), outline=None, width=0)
    if pct > 0:
        _draw_rounded(draw, (bar_x, bar_y, bar_x + max(18, int(bar_w * pct)), bar_y + bar_h), 14, blue, outline=None, width=0)

    xp_tw, _ = text_size(xp_text, font_xp_value)
    draw.text((1945 - xp_tw, 970), xp_text, font=font_xp_value, fill=text)

    # Rimuove ogni residuo testuale basso: badge/vetrina e footer non devono stare nella PNG.
    clear_rect((0, 1080, 2048, 1152), bg)

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
