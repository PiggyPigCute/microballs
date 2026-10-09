# website of MicroBalls: discord login, personal collection and leaderboard
# run locally:       flask --app web.app run --port 3008         (from the microballs folder)
# run in production: gunicorn -w 2 -b 127.0.0.1:3008 web.app:app

import os
import sys
import json
import time
import secrets
import requests

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from flask import Flask, abort, flash, g, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import database as db
from texts import read_csv, transcription_ernestien

# config (web.lock is a JSON file next to token.lock, see web/README.md)
with open(os.path.join(BASE_DIR, "web.lock"), encoding="utf-8") as file:
    config = json.load(file)
BOT_TOKEN = config.get("bot_token")
if BOT_TOKEN is None and os.path.exists(os.path.join(BASE_DIR, "token.lock")):
    with open(os.path.join(BASE_DIR, "token.lock"), encoding="utf-8") as file:
        BOT_TOKEN = file.read().strip()

CLIENT_ID = config.get("client_id", "1462241870158630913")
CLIENT_SECRET = config["client_secret"]
REDIRECT_URI = config.get("redirect_uri", "https://microballs.chruk.fr/callback")
DISCORD_API = "https://discord.com/api/v10"
USER_CACHE_DURATION = timedelta(days=7)  # discord profiles older than that are fetched again
FETCH_TIME_BUDGET = 2                    # max seconds spent fetching profiles during a page load
LEADERBOARD_SIZE = 100
LOGS_CHANNEL_ID = config.get("logs_channel_id", 1463155147625467978)  # discord channel where the gifts are logged

discord_paused_until = 0.0  # time.time() until which discord must not be asked (rate limit)

app = Flask(__name__)
app.secret_key = config["secret_key"]
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=REDIRECT_URI.startswith("https"),
                  PERMANENT_SESSION_LIFETIME=timedelta(days=30))
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# balls
balls = read_csv(os.path.join(BASE_DIR, "balls.csv"))
for ball in balls.values():
    try:
        ball["nom_ens_transcrit"] = transcription_ernestien(ball["nom_ens"]) if ball.get("nom_ens") else None
    except KeyError:
        ball["nom_ens_transcrit"] = None

with db.connect() as connection:
    connection.executescript(db.SCHEMA)

# database
def get_db():
    if "db" not in g:
        g.db = db.connect()
        g.db.row_factory = db.sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()

# discord profiles
def avatar_url(user_id:int, avatar:str|None, size=64) -> str:
    if avatar:
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png?size={size}"
    return f"https://cdn.discordapp.com/embed/avatars/{(user_id >> 22) % 6}.png"

def fetch_user(user_id:int, wait=False) -> dict|None:
    # ask discord (with the bot token) for the profile of 𝑢𝑠𝑒𝑟_𝑖𝑑, None if it fails
    # → 𝑤𝑎𝑖𝑡: if True, wait when discord rate limits us (only for the "fetch-users" command)
    #          if False, give up and stop asking discord until the end of the rate limit
    global discord_paused_until
    while BOT_TOKEN is not None and (wait or time.time() >= discord_paused_until):
        try:
            response = requests.get(f"{DISCORD_API}/users/{user_id}", headers={"Authorization": "Bot "+BOT_TOKEN}, timeout=3)
        except requests.RequestException:
            return None
        if response.status_code == 429:
            retry_after = float(response.json().get("retry_after", 5))
            if wait:
                time.sleep(retry_after)
                continue
            discord_paused_until = time.time() + retry_after
            return None
        if response.status_code == 401:
            # wrong token: stop asking (too many 401 can get the server banned by discord)
            app.logger.error("Token du bot refusé par Discord, récupération des profils désactivée pendant 1h")
            discord_paused_until = time.time() + 3600
            return None
        if response.headers.get("X-RateLimit-Remaining") == "0":
            discord_paused_until = time.time() + float(response.headers.get("X-RateLimit-Reset-After", 1))
            if wait:
                time.sleep(discord_paused_until - time.time())
        return response.json() if response.ok else None
    return None

def get_users(user_ids) -> dict[int,dict]:
    # return {user_id: {"name", "avatar_url"}}, fetching from discord the unknown or outdated profiles
    # (at most 𝐹𝐸𝑇𝐶𝐻_𝑇𝐼𝑀𝐸_𝐵𝑈𝐷𝐺𝐸𝑇 seconds, the remaining profiles will be fetched during the next page loads)
    user_ids = {user_id for user_id in user_ids if user_id is not None}
    if not user_ids:
        return {}
    connection = get_db()
    placeholders = ",".join("?"*len(user_ids))
    rows = {row["id"]: row for row in connection.execute(f"SELECT * FROM users WHERE id IN ({placeholders})", list(user_ids))}
    limit = datetime.now(timezone.utc) - USER_CACHE_DURATION
    deadline = time.monotonic() + FETCH_TIME_BUDGET
    for user_id in user_ids:
        if time.monotonic() > deadline or time.time() < discord_paused_until:
            break
        row = rows.get(user_id)
        if row is None or datetime.fromisoformat(row["updated_at"]) < limit:
            user = fetch_user(user_id)
            if user is not None:
                db.save_user(user_id, user["username"], user.get("global_name"), user.get("avatar"), connection)
                rows[user_id] = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    users = {}
    for user_id in user_ids:
        row = rows.get(user_id)
        users[user_id] = {
            "name": (row["global_name"] or row["username"]) if row else f"Joueur·euse #{str(user_id)[-4:]}",
            "username": row["username"] if row else None,
            "avatar_url": avatar_url(user_id, row["avatar"] if row else None),
        }
    return users

@app.cli.command("fetch-users")
def fetch_users_command():
    # flask --app web.app fetch-users
    # fetch the discord profile of every player (owners and catchers), waiting when discord rate limits us
    connection = db.connect()
    user_ids = [row[0] for row in connection.execute(
        "SELECT owner_id FROM microballs UNION SELECT catcher_id FROM microballs WHERE catcher_id IS NOT NULL")]
    for i, user_id in enumerate(user_ids):
        user = fetch_user(user_id, wait=True)
        if user is not None:
            db.save_user(user_id, user["username"], user.get("global_name"), user.get("avatar"), connection)
        print(f"{i+1}/{len(user_ids)} {user_id} → {user['username'] if user else 'échec'}")
    connection.close()

# session
def current_user() -> dict|None:
    if "user_id" not in session:
        return None
    user_id = int(session["user_id"])
    return {"id": user_id, **get_users([user_id])[user_id]}

def csrf_token() -> str:
    # token put in every form, checked by 𝑐ℎ𝑒𝑐𝑘_𝑐𝑠𝑟𝑓() (prevents other websites from submitting forms in the name of the user)
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]

def check_csrf():
    if not secrets.compare_digest(request.form.get("csrf", ""), session.get("csrf", "-")):
        abort(400)

@app.context_processor
def inject_globals():
    return {"me": current_user(), "n_balls": len(balls), "csrf_token": csrf_token}

# pages
@app.route("/")
def leaderboard():
    # 𝑚𝑖𝑛_𝑎𝑚𝑜𝑢𝑛𝑡: amount of the rarest type of the player, i.e. number of complete collections if all the types are found
    rows = get_db().execute(
        "SELECT owner_id, SUM(amount) AS total, COUNT(*) AS types, SUM(ernestien) AS ernestien, MIN(amount) AS min_amount "
        "FROM (SELECT owner_id, ball_type, COUNT(*) AS amount, SUM(language = 'ens') AS ernestien FROM microballs GROUP BY owner_id, ball_type) "
        "GROUP BY owner_id ORDER BY total DESC, types DESC").fetchall()
    ranking = [dict(row, rank=i+1, complete_sets=row["min_amount"] if row["types"] >= len(balls) else 0) for i, row in enumerate(rows)]
    shown = ranking[:LEADERBOARD_SIZE]
    my_row = None
    if "user_id" in session:
        my_row = next((row for row in ranking if row["owner_id"] == int(session["user_id"])), None)
        if my_row is not None and my_row["rank"] <= LEADERBOARD_SIZE:
            my_row = None  # already visible
    users = get_users([row["owner_id"] for row in shown] + ([my_row["owner_id"]] if my_row else []))
    return render_template("leaderboard.html", ranking=shown, my_row=my_row, users=users,
                           n_players=len(ranking), n_total=sum(row["total"] for row in ranking))

@app.route("/collection")
def collection():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return redirect(url_for("player", user_id=session["user_id"]))

@app.route("/joueur-euse/<int:user_id>")
def player(user_id:int):
    viewer_id = int(session["user_id"]) if "user_id" in session else None
    rows = get_db().execute(
        "SELECT id, ball_type, catcher_id, caught_at, language FROM microballs WHERE owner_id = ? ORDER BY id DESC",
        (user_id,)).fetchall()
    if not rows and user_id != viewer_id:
        abort(404)  # unknown player (avoid asking discord for random ids)
    counts = {}
    for row in rows:
        counts[row["ball_type"]] = counts.get(row["ball_type"], 0)+1
    # types sorted from the most to the least owned, the missing ones at the end (sorted() keeps the balls.csv order for ties)
    sorted_balls = sorted(balls.items(), key=lambda item: -counts.get(item[0], 0))
    complete_sets = min(counts.get(ball_id, 0) for ball_id in balls)
    # last gift received for each MicroBall currently owned
    received = {row["microball_id"]: row for row in get_db().execute(
        "SELECT t.microball_id, t.from_id, t.transferred_at FROM transfers t JOIN microballs m ON m.id = t.microball_id "
        "WHERE m.owner_id = ? AND t.to_id = ? ORDER BY t.id", (user_id, user_id))}
    users = get_users([row["catcher_id"] for row in rows] + [row["from_id"] for row in received.values()] + [user_id])
    microballs = []
    old_groups = {}  # the old MicroBalls (no catcher, no date) are grouped by type and language
    for row in rows:
        if row["caught_at"] is None and row["catcher_id"] is None:
            key = (row["ball_type"], row["language"])
            if key in old_groups:
                old_groups[key]["amount"] += 1
                continue
        ball = balls.get(row["ball_type"], {"img": None, "nom_fr": row["ball_type"], "nom_ens_transcrit": None})
        microball = {
            "id": row["id"], "amount": 1, "type": row["ball_type"], "ball": ball, "language": row["language"],
            "language_name": db.LANGUAGES.get(row["language"], row["language"]),
            "name": ball["nom_ens_transcrit"] if row["language"] == "ens" and ball["nom_ens_transcrit"] else ball["nom_fr"],
            "catcher": users.get(row["catcher_id"]), "catcher_is_me": row["catcher_id"] == viewer_id,
            "caught_at": datetime.fromisoformat(row["caught_at"]) if row["caught_at"] else None,
            "received_from": None, "received_at": None,
        }
        if row["id"] in received and not (row["caught_at"] is None and row["catcher_id"] is None):
            microball["received_from"] = users.get(received[row["id"]]["from_id"])
            microball["received_at"] = datetime.fromisoformat(received[row["id"]]["transferred_at"])
        if row["caught_at"] is None and row["catcher_id"] is None:
            old_groups[(row["ball_type"], row["language"])] = microball
        microballs.append(microball)
    return render_template("collection.html", balls=balls, sorted_balls=sorted_balls, counts=counts, microballs=microballs,
                           n_microballs=len(rows), n_ernestien=sum(row["language"] == "ens" for row in rows),
                           complete_sets=complete_sets, player={"id": user_id, **users[user_id]}, is_mine=user_id == viewer_id,
                           recipients=get_recipients(viewer_id) if user_id == viewer_id else [])

# gifts
def get_recipients(viewer_id:int) -> list[dict]:
    # every known player except 𝑣𝑖𝑒𝑤𝑒𝑟_𝑖𝑑, for the autocompletion of the gift form
    return [dict(row) for row in get_db().execute(
        "SELECT id, username, global_name FROM users WHERE id != ? ORDER BY COALESCE(global_name, username) COLLATE NOCASE", (viewer_id,))]

def find_recipient(text:str) -> int|None:
    # find a player from what was typed in the gift form: "@username", "username", display name or discord id
    text = text.strip().removeprefix("@").strip()
    if not text:
        return None
    connection = get_db()
    if text.isdigit() and 17 <= len(text) <= 20:
        user_id = int(text)
        if connection.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
            return user_id
        user = fetch_user(user_id)
        if user is None:
            return None
        db.save_user(user_id, user["username"], user.get("global_name"), user.get("avatar"), connection)
        return user_id
    row = connection.execute("SELECT id FROM users WHERE username = ? COLLATE NOCASE", (text,)).fetchone()
    if row:
        return row[0]
    rows = connection.execute("SELECT id FROM users WHERE global_name = ? COLLATE NOCASE", (text,)).fetchall()
    return rows[0][0] if len(rows) == 1 else None  # several players with this display name: ambiguous

def log_discord(text:str):
    # send a log in the discord logs channel (best effort, a failure doesn't prevent the gift)
    if BOT_TOKEN is None:
        return
    try:
        requests.post(f"{DISCORD_API}/channels/{LOGS_CHANNEL_ID}/messages", json={"content": text, "allowed_mentions": {"parse": []}},
                      headers={"Authorization": "Bot "+BOT_TOKEN}, timeout=3)
    except requests.RequestException:
        pass

@app.post("/donner")
def give():
    if "user_id" not in session:
        return redirect(url_for("login"))
    check_csrf()
    sender_id = int(session["user_id"])
    back = redirect(url_for("player", user_id=sender_id))

    recipient_id = find_recipient(request.form.get("recipient", ""))
    if recipient_id is None:
        flash("Joueur·euse introuvable : choisis un nom dans la liste ou colle son identifiant Discord.", "error")
        return back
    if recipient_id == sender_id:
        flash("Tu ne peux pas te donner des MicroBalls à toi-même.", "error")
        return back

    # selection: "mb" = ids of recent MicroBalls, "old:<type>:<language>" = amount of old MicroBalls of this group
    try:
        microball_ids = [int(value) for value in request.form.getlist("mb")]
        old_groups = {}
        for key, value in request.form.items():
            if key.startswith("old:") and value.strip() not in ("", "0"):
                _, ball_type, language = key.split(":", 2)
                if int(value) < 0: raise ValueError
                old_groups[(ball_type, language)] = int(value)
    except ValueError:
        abort(400)
    if not microball_ids and not old_groups:
        flash("Sélectionne au moins une MicroBall à donner.", "error")
        return back

    given = db.give_balls(sender_id, recipient_id, microball_ids, old_groups, get_db())
    if given is None:
        flash("Le don a échoué : certaines MicroBalls ne sont plus dans ta collection. Rien n'a été donné.", "error")
        return back

    users = get_users([sender_id, recipient_id])
    n = len(given)
    flash(f"🎁 Tu as donné {n} MicroBall{'s' if n > 1 else ''} à {users[recipient_id]['name']} !", "success")
    types = {}
    for row in get_db().execute(f"SELECT ball_type, language FROM microballs WHERE id IN ({','.join('?'*n)})", given):
        types[(row["ball_type"], row["language"])] = types.get((row["ball_type"], row["language"]), 0)+1
    log_discord(" 🪵 🎁 cadeau (site) │ sender: "+str(users[sender_id]["username"])+" │ to: "+str(users[recipient_id]["username"])+" │ "
                +", ".join(f"{ball_type}{' 🐠' if language == 'ens' else ''}×{amount}" for (ball_type, language), amount in types.items())
                +" │ microball_ids: "+(",".join(map(str, given)) if n <= 100 else f"{n} balles"))
    return back

# "secret" pages (not linked anywhere, not indexed): statistics by type
@app.route("/bytype")
def by_type():
    stats = {row["ball_type"]: row for row in get_db().execute(
        "SELECT ball_type, COUNT(*) AS total, SUM(language = 'ens') AS ernestien, COUNT(DISTINCT owner_id) AS owners "
        "FROM microballs GROUP BY ball_type")}
    types = [{"id": ball_id, "ball": ball, "total": stats[ball_id]["total"] if ball_id in stats else 0,
              "ernestien": stats[ball_id]["ernestien"] if ball_id in stats else 0,
              "owners": stats[ball_id]["owners"] if ball_id in stats else 0} for ball_id, ball in balls.items()]
    return render_template("bytype.html", types=types, max_total=max([t["total"] for t in types] + [1]),
                           n_total=sum(t["total"] for t in types))

@app.route("/bytype/<ball_id>")
def by_type_detail(ball_id:str):
    if ball_id not in balls:
        abort(404)
    rows = get_db().execute(
        "SELECT owner_id, COUNT(*) AS total, SUM(language = 'ens') AS ernestien FROM microballs WHERE ball_type = ? "
        "GROUP BY owner_id ORDER BY total DESC, ernestien DESC", (ball_id,)).fetchall()
    ranking = [dict(row, rank=i+1) for i, row in enumerate(rows)]
    users = get_users([row["owner_id"] for row in ranking])
    return render_template("bytype_detail.html", ball_id=ball_id, ball=balls[ball_id], ranking=ranking, users=users,
                           n_total=sum(row["total"] for row in ranking))

@app.route("/img/<path:filename>")
def ball_image(filename):
    return send_from_directory(os.path.join(BASE_DIR, "img"), filename, max_age=86400)

# discord login (OAuth2, scope "identify")
@app.route("/login")
def login():
    session["oauth_state"] = secrets.token_urlsafe(24)
    return redirect("https://discord.com/oauth2/authorize?"+urlencode({
        "client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI, "response_type": "code",
        "scope": "identify", "state": session["oauth_state"], "prompt": "none"}))

@app.route("/callback")
def callback():
    state = session.pop("oauth_state", None)
    if state is None or request.args.get("state") != state:
        abort(400)
    if "code" not in request.args:
        return redirect(url_for("leaderboard"))  # the user refused
    token = requests.post(f"{DISCORD_API}/oauth2/token", timeout=10, auth=(CLIENT_ID, CLIENT_SECRET), data={
        "grant_type": "authorization_code", "code": request.args["code"], "redirect_uri": REDIRECT_URI})
    if not token.ok:
        abort(502)
    user = requests.get(f"{DISCORD_API}/users/@me", timeout=10,
                        headers={"Authorization": "Bearer "+token.json()["access_token"]})
    if not user.ok:
        abort(502)
    user = user.json()
    db.save_user(int(user["id"]), user["username"], user.get("global_name"), user.get("avatar"), get_db())
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    return redirect(url_for("collection"))

@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("leaderboard"))

# template filters
@app.template_filter("date_fr")
def date_fr(date:datetime) -> str:
    months = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
    date = date.astimezone(ZoneInfo("Europe/Paris"))
    return f"{date.day} {months[date.month-1]} {date.year} à {date.hour:02d}h{date.minute:02d}"
