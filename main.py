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
# FOOTBALL-DATA.ORG
# =========================
FOOTBALL_DATA_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN")
BASE_URL = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": FOOTBALL_DATA_TOKEN}


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


async def send_long(ctx, msg):
    if len(msg) <= 1900:
        await ctx.send(msg)
        return

    chunks = [msg[i:i+1900] for i in range(0, len(msg), 1900)]

    for chunk in chunks:
        await ctx.send(chunk)


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

# =========================
# DATABASE UPDATE
# =========================

try:
    c.execute("ALTER TABLE trades ADD COLUMN price REAL")
except:
    pass

try:
    c.execute("ALTER TABLE markets ADD COLUMN channel_id TEXT")
except:
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
# BASE COMMANDS
# =========================
@bot.command()
async def ping(ctx):
    await ctx.send("pong 🟢")


@bot.command()
async def balance(ctx):
    bal = get_user(str(ctx.author.id))
    await ctx.send(f"💰 {bal}")


# =========================
# API TEST COMMANDS
# =========================
@bot.command()
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


@bot.command()
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
# FIND MATCHES
# =========================
@bot.command()
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


@bot.command()
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
@bot.command()
async def creatematch(ctx, match_id: int, *, question):

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
        channel_id
    )
    VALUES (?, 0, 0, 0, 1, ?, 0, NULL, ?)
""", (question, f"MATCH_{match_id}", str(ctx.channel.id)))

    market_id = c.lastrowid
    conn.commit()

    await ctx.send(
f"""📊 Mercato creato!

🆔 ID Mercato: {market_id}
🆔 Match API: {match_id}

🏟️ Partita:
{home} vs {away}

📡 Stato API: {status}

❓ Domanda:
{question}

⚖️ Quote iniziali:
🟢 YES: 50%
🔴 NO: 50%
"""
    )


# =========================
# MARKETS VIEW
# =========================
@bot.command()
async def markets(ctx):

    c.execute("SELECT id, question, yes_pool, no_pool FROM markets WHERE active=1")
    rows = c.fetchall()

    if not rows:
        await ctx.send("📭 Nessun mercato attivo")
        return

    msg = "📊 MERCATI ATTIVI\n\n"

    for mid, q, yes, no in rows:
        total = yes + no
        yp = 50 if total == 0 else round((yes / total) * 100, 1)
        np = round(100 - yp, 1)

        msg += f"""🆔 {mid}
❓ {q}

🟢 YES: {yp}%
🔴 NO: {np}%
💰 Pool: {total}

────────────────
"""

    await ctx.send(msg)


# =========================
# SINGLE MARKET VIEW
# =========================
@bot.command()
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

    yes_p = 50 if total == 0 else round((yes / total) * 100, 1)
    no_p = round(100 - yes_p, 1)

    match_text = ""

    if match_key and match_key.startswith("MATCH_"):
        match_id = match_key.replace("MATCH_", "")
        res = get_match_result(match_id)

        if res:
            match_text = f"""
🏟️ Partita:
{res["home"]} vs {res["away"]}

📡 Stato API: {res["status"]}
"""
            if res["home_goals"] is not None and res["away_goals"] is not None:
                match_text += f"⚽ Risultato live/finale: {res['home_goals']}-{res['away_goals']}\n"

    if active == 1:
        status = "ATTIVO"
    elif resolved == 1:
        status = f"CHIUSO | Risultato mercato: {result}"
    else:
        status = "CHIUSO"

    await ctx.send(
f"""📊 MERCATO #{market_id}

❓ {q}
{match_text}
🟢 YES: {yes_p}%
🔴 NO: {no_p}%

💰 Pool totale: {total}
📉 Stato: {status}
"""
    )


# =========================
# PORTFOLIO
# =========================
@bot.command()
async def portfolio(ctx):

    user_id = str(ctx.author.id)

    balance = get_user(user_id)

    c.execute("""
    SELECT
        t.market_id,
        m.question,
        m.yes_pool,
        m.no_pool,
        m.total_pool,
        m.active,
        t.side,
        t.amount,
        t.price
    FROM trades t
    JOIN markets m
        ON t.market_id=m.id
    WHERE t.user_id=?
    ORDER BY t.market_id DESC
    """,(user_id,))

    rows = c.fetchall()

    if not rows:

        await ctx.send(
f"""💼 PORTFOLIO DI {ctx.author.display_name}

💰 Saldo: {balance}

Non hai ancora aperto nessuna posizione.
"""
        )
        return

    msg = f"""💼 PORTFOLIO DI {ctx.author.display_name}

💰 Saldo: {balance}

────────────────────

"""

    for market_id, question, yes, no, total, active, side, amount, entry_price in rows:

        if total == 0:
            current_yes = 50
        else:
            current_yes = (yes/total)*100

        current_no = 100-current_yes

        current_price = current_yes if side=="YES" else current_no

        invested = amount

        current_value = invested*(current_price/entry_price)

        if side=="YES":
            possible_win = invested

            if yes>0:
                possible_win += invested*(no/yes)

        else:

            possible_win = invested

            if no>0:
                possible_win += invested*(yes/no)

        profit = current_value-invested

        status="🟢 LIVE" if active else "⚪ CHIUSO"

        emoji="🟢" if side=="YES" else "🔴"

        msg += f"""
📊 Mercato {market_id}

❓ {question}

{emoji} Posizione: {side}

💸 Investito: {invested:.0f}

📈 Valore attuale: {current_value:.0f}

💰 Possibile vincita: {possible_win:.0f}

📊 Profitto:
{profit:+.0f}

{status}

────────────────────
"""

    await send_long(ctx,msg)


# =========================
# LIVE MARKETS
# =========================
@bot.command()
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

    msg = "🔴 LIVE MARKETS\n\n"
    found_live = False

    for market_id, question, yes, no, total, match_key in rows:

        if not match_key or not match_key.startswith("MATCH_"):
            continue

        try:
            match_id = int(match_key.replace("MATCH_", ""))
        except:
            continue

        res = get_match_result(match_id)

        if not res:
            continue

        if res["status"] not in ["IN_PLAY", "PAUSED"]:
            continue

        found_live = True

        yes_p = 50 if total == 0 else round((yes / total) * 100, 1)
        no_p = round(100 - yes_p, 1)

        score = "N/D"
        if res["home_goals"] is not None and res["away_goals"] is not None:
            score = f'{res["home_goals"]}-{res["away_goals"]}'

        msg += f"""🆔 Mercato {market_id}

🏟️ {res["home"]} vs {res["away"]}
⚽ Risultato: {score}
📡 Stato: {res["status"]}

❓ {question}

🟢 YES: {yes_p}%
🔴 NO: {no_p}%
💰 Pool: {total}

────────────────
"""

    if not found_live:
        await ctx.send("📭 Nessun mercato live in questo momento")
        return

    await send_long(ctx, msg)

    
# =========================
# BUY + PRICE UPDATE
# =========================
@bot.command()
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

    total = yes + no

    yes_p = 50 if total == 0 else round((yes / total) * 100, 1)
    no_p = round(100 - yes_p, 1)

    trade_price = yes_p if side == "YES" else no_p

    c.execute("""
        INSERT INTO trades (user_id, market_id, side, amount, price)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, market_id, side, amount, trade_price))

    save_price(market_id, yes_p)

    conn.commit()

    await ctx.send(
f"""📈 Acquisto effettuato!

🆔 Mercato {market_id}
📊 Scommessa: {side}
💸 Puntata: +{amount}

⚖️ Nuove quote:
🟢 YES: {yes_p}%
🔴 NO: {no_p}%
"""
    )


# =========================
# CHART
# =========================
@bot.command()
async def chart(ctx, market_id: int):

    c.execute("""
        SELECT timestamp, yes_price
        FROM price_history
        WHERE market_id=?
        ORDER BY id ASC
        LIMIT 60
    """, (market_id,))

    data = c.fetchall()

    if len(data) < 2:
        await ctx.send("❌ Dati insufficienti")
        return

    times = [d[0] for d in data]
    yes_prices = [d[1] for d in data]
    no_prices = [100 - y for y in yes_prices]

    x = list(range(len(yes_prices)))

    def smooth(arr, window=3):
        if len(arr) < window:
            return arr

        return [
            sum(arr[max(0, i-window):i+1]) / min(i+1, window)
            for i in range(len(arr))
        ]

    yes_smooth = smooth(yes_prices)
    no_smooth = smooth(no_prices)

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor("#0e1117")
    ax.set_facecolor("#0e1117")

    ax.plot(x, yes_smooth, label="YES", linewidth=2.5, color="#22c55e")
    ax.plot(x, no_smooth, label="NO", linewidth=2.5, color="#ef4444")

    ax.axhline(50, linestyle="--", linewidth=1, alpha=0.3, color="white")

    ax.fill_between(x, yes_smooth, alpha=0.10, color="#00ff88")
    ax.fill_between(x, no_smooth, alpha=0.05, color="#ff4444")

    ax.set_title("Market Probability", fontsize=15, fontweight="bold", color="white")
    ax.set_ylabel("Probability (%)", color="white")
    ax.set_ylim(0, 100)

    ax.grid(True, alpha=0.15)

    step = max(1, len(x)//6)
    ax.set_xticks(range(0, len(x), step))
    ax.set_xticklabels(
        [times[i] for i in range(0, len(times), step)],
        rotation=25,
        color="white"
    )

    ax.tick_params(colors="white")
    ax.legend()

    plt.tight_layout()

    buffer = io.BytesIO()
    plt.savefig(buffer, format="png", facecolor="#0e1117")
    buffer.seek(0)

    await ctx.send(file=discord.File(buffer, "market_chart.png"))

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

    conn.commit()

    return total_paid


# =========================
# RESOLVER LOOP
# =========================
async def resolve():

    await bot.wait_until_ready()

    while not bot.is_closed():

        try:
            c.execute("""
                SELECT id, question, match_key, channel_id
                FROM markets
                WHERE active=1 AND resolved=0
            """)

            markets = c.fetchall()

            for mid, question, mk, channel_id in markets:

                if not mk or not mk.startswith("MATCH_"):
                    continue

                try:
                    match_id = int(mk.replace("MATCH_", ""))
                except:
                    continue

                res = get_match_result(match_id)

                if not res:
                    continue

                if not res["finished"]:
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

                total_paid = payout_market(mid, final)

                score = "N/D"
                if res["home_goals"] is not None and res["away_goals"] is not None:
                    score = f'{res["home_goals"]}-{res["away_goals"]}'

                print(f"[CLOSED] {mid} -> {final}")

                if channel_id:
                    try:
                        channel = bot.get_channel(int(channel_id))
                    except:
                        channel = None

                    if channel:
                        await channel.send(
f"""🏁 MERCATO CHIUSO

🆔 Mercato {mid}

🏟️ {res["home"]} vs {res["away"]}
⚽ Risultato finale: {score}

❓ {question}

✅ Esito mercato: {final}

💰 Premi distribuiti: {total_paid} crediti
🎉 Congratulazioni ai vincitori!
"""
                        )

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
