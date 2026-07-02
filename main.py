import os
import discord
import sqlite3
import requests
import asyncio
import matplotlib.pyplot as plt
import io

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

# Ruolo Discord da pingare quando viene pubblicato un nuovo mercato.
MARKET_ROLE_ID = 1522125298345447546

# Canali dedicati al calendario automatico giornaliero.
PUBLIC_CALENDAR_CHANNEL_ID = 1522149843663982753
ADMIN_CALENDAR_CHANNEL_ID = 1522150991112310874
CALENDAR_POST_HOUR = 11
CALENDAR_POST_MINUTE = 0
LAST_CALENDAR_POST_DATE = None

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


# =========================
# DATABASE
# =========================
conn = sqlite3.connect("bot.db", check_same_thread=False)
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

# =========================
# DATABASE UPDATE
# =========================
for statement in [
    "ALTER TABLE trades ADD COLUMN price REAL",
    "ALTER TABLE trades ADD COLUMN closed INTEGER DEFAULT 0",
    "ALTER TABLE markets ADD COLUMN channel_id TEXT",
    "ALTER TABLE markets ADD COLUMN alert_yes_price REAL",
    "ALTER TABLE markets ADD COLUMN event_category TEXT"
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
    c.execute("""
        SELECT
            t.id,
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
            t.amount,
            t.price
        FROM trades t
        JOIN markets m ON t.market_id=m.id
        WHERE t.user_id=?
          AND t.amount > 0
          AND (t.closed IS NULL OR t.closed=0)
        ORDER BY t.market_id DESC, t.id ASC
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

    embed = discord.Embed(title=title, description=desc, color=0x22c55e if obtained else 0xef4444)
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


def build_calendar_embeds(public=True):
    today = get_rome_now().date()
    title = "📅 Partite di oggi" if public else "👑 Calendario admin"
    description = "Calendario pubblico senza ID partita." if public else "Calendario operativo con Match ID per creare mercati."
    embed = discord.Embed(title=title, description=description, color=0x2563eb if public else 0xf59e0b)

    found = False
    field_count = 0

    for code, name in COMPETITIONS.items():
        matches = get_today_matches_for_competition(code, today)
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
                lines.append(f"**{home}** vs **{away}\n🕒 {time_str} | 📡 {status}")
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


async def post_daily_calendars():
    public_channel = bot.get_channel(PUBLIC_CALENDAR_CHANNEL_ID)
    admin_channel = bot.get_channel(ADMIN_CALENDAR_CHANNEL_ID)

    if public_channel:
        try:
            await public_channel.send(embed=build_calendar_embeds(public=True))
        except Exception as e:
            print(f"[CALENDAR PUBLIC] Errore invio: {e}")

    if admin_channel:
        try:
            await admin_channel.send(embed=build_calendar_embeds(public=False))
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
    bal = get_user(str(ctx.author.id))

    embed = discord.Embed(
        title="💰 Saldo",
        color=0x22c55e
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
        color=0x22c55e
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
        color=0x22c55e
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
            color=0xef4444
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
        color=prediction["color"]
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
    """, (question, f"MATCH_{match_id}", str(ctx.channel.id)))

    market_id = c.lastrowid
    conn.commit()

    # Risposta privata/operativa nel canale in cui l'admin ha creato il mercato.
    embed = discord.Embed(
        title="📊 Mercato creato",
        description=question,
        color=0x22c55e
    )
    embed.add_field(name="🆔 Mercato", value=f"#{market_id}", inline=True)
    embed.add_field(name="🆔 Match API", value=str(match_id), inline=True)
    embed.add_field(name="📡 Stato API", value=status, inline=True)
    embed.add_field(name="🏟️ Partita", value=f"{home} vs {away}", inline=False)
    embed.set_footer(text="Mercato aperto correttamente.")

    await ctx.send(embed=embed)

    # Annuncio pubblico nel canale dedicato ai mercati.
    market_channel = bot.get_channel(MARKET_CHANNEL_ID)

    if market_channel:
        announcement = discord.Embed(
            title="📣 Nuovo mercato disponibile!",
            color=0x22c55e
        )
        announcement.add_field(
            name="🏟️ Partita",
            value=f"{home} vs {away}",
            inline=False
        )
        announcement.add_field(
            name="❓ Domanda",
            value=question,
            inline=False
        )
        announcement.add_field(
            name="🆔 Mercato",
            value=f"#{market_id}",
            inline=False
        )
        announcement.set_footer(text="💡 Acquista le tue quote")

        await market_channel.send(embed=announcement)
        try:
            await market_channel.send(
                content=f"<@&{MARKET_ROLE_ID}>",
                allowed_mentions=discord.AllowedMentions(roles=True)
            )
        except Exception as e:
            print(f"[MARKET ROLE PING] Impossibile pingare il ruolo {MARKET_ROLE_ID}: {e}")
    else:
        print(f"[MARKET ANNOUNCEMENT] Canale {MARKET_CHANNEL_ID} non trovato.")


# =========================
# CREATE SPECIAL EVENT MARKET
# =========================
@bot.command(aliases=["creaevento"])
@admin_only()
async def createevent(ctx, category: str, *, question):
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
        color=0x8b5cf6
    )
    embed.add_field(name="🏷️ Categoria", value=category_label, inline=False)
    embed.add_field(name="🆔 Mercato", value=f"#{market_id}", inline=True)
    embed.set_footer(text="Il mercato dovrà essere risolto manualmente con !resolve ID YES/NO")
    await ctx.send(embed=embed)

    market_channel = bot.get_channel(MARKET_CHANNEL_ID)
    if market_channel:
        announcement = discord.Embed(
            title="📣 Nuovo mercato disponibile!",
            color=0x8b5cf6
        )
        announcement.add_field(name="🎲 Evento Speciale", value=category_label, inline=False)
        announcement.add_field(name="❓ Domanda", value=question, inline=False)
        announcement.add_field(name="🆔 Mercato", value=f"#{market_id}", inline=False)
        announcement.set_footer(text="💡 Acquista le tue quote")
        await market_channel.send(embed=announcement)
        try:
            await market_channel.send(
                content=f"<@&{MARKET_ROLE_ID}>",
                allowed_mentions=discord.AllowedMentions(roles=True)
            )
        except Exception as e:
            print(f"[EVENT ROLE PING] Impossibile pingare il ruolo {MARKET_ROLE_ID}: {e}")


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
        color=0x2563eb
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
        color=market_color(yes_p)
    )
    embed.add_field(name="🏟️ Partita", value=match_line, inline=False)
    embed.add_field(name="📡 Stato API", value=api_status, inline=True)
    if score:
        embed.add_field(name="⚽ Risultato", value=score, inline=True)
    embed.add_field(name="📉 Stato mercato", value=status, inline=True)
    embed.add_field(name="🟢 YES", value=f"**{yes_p}%**\n`{progress_bar(yes_p)}`", inline=True)
    embed.add_field(name="🔴 NO", value=f"**{no_p}%**\n`{progress_bar(no_p)}`", inline=True)
    embed.add_field(name="💰 Pool totale", value=str(total), inline=True)
    embed.set_footer(text="Usa !buy, !sell, !chart oppure gli alias italiani !compra, !vendi, !grafico")

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
            color=0x64748b
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        embed.add_field(name="💰 Saldo", value=f"{balance} crediti", inline=False)
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
            f"💸 Investito: **{invested:.0f}** | 📈 Valore: **{current_value:.0f}** | 💰 Vincita: **{possible_win:.0f}**\n"
            f"📊 P/L: **{profit:+.0f}** ({profit_pct:+.1f}%)"
        )

    total_profit = total_value - total_invested
    total_profit_pct = 0 if total_invested == 0 else (total_profit / total_invested) * 100
    color = 0x22c55e if total_profit >= 0 else 0xef4444

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
    embed.set_footer(text="Comando disponibile anche come !portafoglio")

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
        color=0x2563eb
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
        color=0x22c55e
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

    color = 0x22c55e if open_profit >= 0 else 0xef4444
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

    badge_ids = get_active_badges(user_id)
    badge_text = " • ".join(format_badge(b) for b in badge_ids[:12]) if badge_ids else "Nessun badge sbloccato."
    if len(badge_text) > 1024:
        badge_text = badge_text[:1000] + "..."
    embed.add_field(name="🏅 Badge", value=badge_text, inline=False)

    embed.set_footer(text="Comando disponibile anche come !profilo")

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
        color=0xfacc15
    )

    medals = ["🥇", "🥈", "🥉"]

    for i, (user_id, balance, open_value, net_worth) in enumerate(ranking[:10], start=1):
        medal = medals[i - 1] if i <= 3 else f"#{i}"
        embed.add_field(
            name=f"{medal} Posizione {i}",
            value=(
                f"👤 <@{user_id}>\n"
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
        color=0xef4444
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

        if res["status"] not in ["IN_PLAY", "PAUSED"]:
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
        SELECT COUNT(*)
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
                total_pool = total_pool + ?
            WHERE id=?
        """, (amount, amount, market_id))
    else:
        c.execute("""
            UPDATE markets
            SET no_pool = no_pool + ?,
                total_pool = total_pool + ?
            WHERE id=?
        """, (amount, amount, market_id))

    c.execute("SELECT yes_pool, no_pool FROM markets WHERE id=?", (market_id,))
    yes, no = c.fetchone()

    yes_p, no_p = market_probabilities(yes, no)
    trade_price = yes_p if side == "YES" else no_p

    c.execute("""
        INSERT INTO trades (user_id, market_id, side, amount, price, closed)
        VALUES (?, ?, ?, ?, ?, 0)
    """, (user_id, market_id, side, amount, trade_price))

    save_price(market_id, yes_p)
    award_xp(user_id, max(5, amount // 20))
    record_wealth_snapshot(user_id)
    conn.commit()

    embed = discord.Embed(
        title="📈 Acquisto effettuato",
        color=0x22c55e if side == "YES" else 0xef4444
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    embed.add_field(name="🆔 Mercato", value=str(market_id), inline=True)
    embed.add_field(name="📊 Posizione", value=side, inline=True)
    embed.add_field(name="💸 Puntata", value=f"+{amount}", inline=True)
    embed.add_field(name="🟢 YES", value=f"{yes_p}%", inline=True)
    embed.add_field(name="🔴 NO", value=f"{no_p}%", inline=True)
    embed.add_field(name="📉 Barra", value=f"`{progress_bar(yes_p)}`", inline=False)

    await ctx.send(embed=embed)
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
                total_pool = MAX(total_pool - ?, 0)
            WHERE id=?
        """, (pool_reduction, pool_reduction, market_id))
    else:
        pool_reduction = min(pool_reduction, no_pool)
        c.execute("""
            UPDATE markets
            SET no_pool = no_pool - ?,
                total_pool = MAX(total_pool - ?, 0)
            WHERE id=?
        """, (pool_reduction, pool_reduction, market_id))

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
        color=0x22c55e if profit >= 0 else 0xef4444
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    embed.add_field(name="🆔 Mercato", value=str(market_id), inline=True)
    embed.add_field(name="📊 Side", value=side, inline=True)
    embed.add_field(name="📉 Venduto", value=f"{pct:.1f}%", inline=True)
    embed.add_field(name="💰 Incassato", value=str(proceeds), inline=True)
    embed.add_field(name="📊 Profitto/Perdita", value=f"{profit:+.0f}", inline=True)
    embed.add_field(name="💼 Saldo aggiornato", value=str(bal), inline=True)
    embed.add_field(name="🟢 YES", value=f"{new_yes_p}%", inline=True)
    embed.add_field(name="🔴 NO", value=f"{new_no_p}%", inline=True)
    embed.add_field(name="📉 Barra", value=f"`{progress_bar(new_yes_p)}`", inline=False)

    await ctx.send(embed=embed)
    await evaluate_user_badges(user_id, notify=True)

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

    def smooth(arr, window=4):
        if len(arr) < window:
            return arr

        smoothed = []
        for i in range(len(arr)):
            start = max(0, i - window + 1)
            chunk = arr[start:i + 1]
            smoothed.append(sum(chunk) / len(chunk))
        return smoothed

    yes_smooth = smooth(yes_prices)
    no_smooth = smooth(no_prices)

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

    # Chart area
    ax = fig.add_axes([0.07, 0.18, 0.86, 0.42])
    ax.set_facecolor("#0b0f19")

    ax.plot(x, yes_smooth, linewidth=3.2, color="#22c55e", label="YES")
    ax.plot(x, no_smooth, linewidth=3.2, color="#ef4444", label="NO")

    ax.fill_between(x, yes_smooth, 0, alpha=0.10, color="#22c55e")
    ax.fill_between(x, no_smooth, 0, alpha=0.06, color="#ef4444")
    ax.axhline(50, linestyle="--", linewidth=1, alpha=0.25, color="#9ca3af")

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

    ax_bg.text(0.05, 0.08, f"Grafico aggiornato alle {updated_at}", fontsize=9, color="#6b7280")
    ax_bg.text(0.74, 0.08, "Prediction Market Bot", fontsize=9, color="#6b7280", ha="right")

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
    c.execute("SELECT id, question, active, resolved FROM markets WHERE id=?", (market_id,))
    row = c.fetchone()

    if not row:
        await ctx.send("❌ Mercato non trovato")
        return

    _, question, active, resolved = row

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

    embed = discord.Embed(
        title="🔒 Mercato chiuso manualmente",
        description=question,
        color=0xf59e0b
    )
    embed.add_field(name="🆔 Mercato", value=str(market_id), inline=True)
    embed.set_footer(text="Nessun payout distribuito. Usa !cancelmarket per rimborsare oppure !resolve per risolvere.")
    await ctx.send(embed=embed)


@bot.command(aliases=["annullamercato"])
@admin_only()
async def cancelmarket(ctx, market_id: int):
    await delete_admin_command_message(ctx)
    """Annulla un mercato e rimborsa le posizioni aperte."""
    c.execute("SELECT id, question, active, resolved FROM markets WHERE id=?", (market_id,))
    row = c.fetchone()

    if not row:
        await ctx.send("❌ Mercato non trovato")
        return

    _, question, active, resolved = row

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
        color=0xef4444
    )
    embed.add_field(name="🆔 Mercato", value=str(market_id), inline=True)
    embed.add_field(name="💸 Rimborsi totali", value=f"{total_refund} crediti", inline=True)
    embed.set_footer(text="Le posizioni aperte sono state chiuse e rimborsate.")
    await ctx.send(embed=embed)


@bot.command(name="resolve", aliases=["risolvi"])
@admin_only()
async def resolve_market_command(ctx, market_id: int, result: str):
    await delete_admin_command_message(ctx)
    """Risolve manualmente un mercato con YES o NO e distribuisce il payout."""
    result = result.upper()

    if result not in ["YES", "NO"]:
        await ctx.send("❌ Risultato non valido. Usa YES o NO.")
        return

    c.execute("SELECT id, question, active, resolved FROM markets WHERE id=?", (market_id,))
    row = c.fetchone()

    if not row:
        await ctx.send("❌ Mercato non trovato")
        return

    _, question, active, resolved = row

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

    embed = discord.Embed(
        title="🏁 Mercato risolto manualmente",
        description=question,
        color=0x22c55e if result == "YES" else 0xef4444
    )
    embed.add_field(name="🆔 Mercato", value=str(market_id), inline=True)
    embed.add_field(name="✅ Esito", value=result, inline=True)
    embed.add_field(name="💰 Premi distribuiti", value=f"{total_paid} crediti", inline=True)
    await ctx.send(embed=embed)


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
            color=0xf59e0b
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
                "`!resetuser @utente`"
            ),
            inline=False
        )
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title="📘 Help",
        description="Comandi disponibili per usare il prediction market.",
        color=0x2563eb
    )
    embed.add_field(
        name="💰 Account",
        value=(
            "`!balance` / `!saldo`\n"
            "`!daily` / `!giornaliero`\n"
            "`!profile` / `!profilo`\n"
            "`!portfolio` / `!portafoglio`\n"
            "`!leaderboard` / `!classifica`"
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
        name="👥 Social trading",
        value=(
            "`!follow @utente`\n"
            "`!unfollow @utente`\n"
            "`!following`\n"
            "`!trader @utente`"
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
# MARKET ALERTS
# =========================
async def maybe_send_market_alert(market_id, question, yes, no, channel_id, last_alert_yes_price):
    if not channel_id:
        return

    yes_p, no_p = market_probabilities(yes, no)

    if last_alert_yes_price is None:
        c.execute("UPDATE markets SET alert_yes_price=? WHERE id=?", (yes_p, market_id))
        conn.commit()
        return

    diff = yes_p - last_alert_yes_price

    if abs(diff) < ALERT_THRESHOLD:
        return

    try:
        channel = bot.get_channel(int(channel_id))
    except Exception:
        channel = None

    if not channel:
        return

    direction = "📈" if diff > 0 else "📉"

    embed = discord.Embed(
        title="🚨 Alert quota",
        description=question,
        color=0x22c55e if diff > 0 else 0xef4444
    )
    embed.add_field(name="🆔 Mercato", value=str(market_id), inline=True)
    embed.add_field(name="Variazione YES", value=f"{direction} {last_alert_yes_price:.1f}% → {yes_p:.1f}%", inline=False)
    embed.add_field(name="🔴 NO", value=f"{no_p:.1f}%", inline=True)
    embed.add_field(name="📊 Scostamento", value=f"{diff:+.1f}%", inline=True)
    embed.add_field(name="📉 Barra", value=f"`{progress_bar(yes_p)}`", inline=False)

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

                if channel_id:
                    try:
                        channel = bot.get_channel(int(channel_id))
                    except Exception:
                        channel = None

                    if channel:
                        embed = discord.Embed(
                            title="🏁 Mercato chiuso",
                            description=question,
                            color=0x22c55e if final == "YES" else 0xef4444
                        )
                        embed.add_field(name="🆔 Mercato", value=str(mid), inline=True)
                        embed.add_field(name="✅ Esito mercato", value=final, inline=True)
                        embed.add_field(name="💰 Premi distribuiti", value=f"{total_paid} crediti", inline=True)
                        embed.add_field(name="🏟️ Partita", value=f'{res["home"]} vs {res["away"]}', inline=False)
                        embed.add_field(name="⚽ Risultato finale", value=score, inline=True)
                        embed.set_footer(text="🎉 Congratulazioni ai vincitori!")

                        await channel.send(embed=embed)

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


# =========================
# RUN
# =========================
bot.run(token)
