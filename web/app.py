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
from flask import Flask, abort, g, redirect, render_template, request, send_from_directory, session, url_for
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
MAX_FETCHES_PER_REQUEST = 50             # avoid slow pages when many profiles are missing
LEADERBOARD_SIZE = 100

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

def fetch_user(user_id:int) -> dict|None:
    # ask discord (with the bot token) for the profile of 𝑢𝑠𝑒𝑟_𝑖𝑑
    if BOT_TOKEN is None:
        return None
    for _ in range(3):
        response = requests.get(f"{DISCORD_API}/users/{user_id}", headers={"Authorization": "Bot "+BOT_TOKEN}, timeout=5)
        if response.status_code == 429:
            time.sleep(response.json().get("retry_after", 1))
            continue
        return response.json() if response.ok else None
    return None

def get_users(user_ids) -> dict[int,dict]:
    # return {user_id: {"name", "avatar_url"}}, fetching from discord the unknown or outdated profiles
    user_ids = {user_id for user_id in user_ids if user_id is not None}
    if not user_ids:
        return {}
    connection = get_db()
    placeholders = ",".join("?"*len(user_ids))
    rows = {row["id"]: row for row in connection.execute(f"SELECT * FROM users WHERE id IN ({placeholders})", list(user_ids))}
    limit = datetime.now(timezone.utc) - USER_CACHE_DURATION
    fetches = 0
    for user_id in user_ids:
        row = rows.get(user_id)
        if (row is None or datetime.fromisoformat(row["updated_at"]) < limit) and fetches < MAX_FETCHES_PER_REQUEST:
            fetches += 1
            user = fetch_user(user_id)
            if user is not None:
                db.save_user(user_id, user["username"], user.get("global_name"), user.get("avatar"), connection)
                rows[user_id] = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    users = {}
    for user_id in user_ids:
        row = rows.get(user_id)
        users[user_id] = {
            "name": (row["global_name"] or row["username"]) if row else f"Joueur #{str(user_id)[-4:]}",
            "username": row["username"] if row else None,
            "avatar_url": avatar_url(user_id, row["avatar"] if row else None),
        }
    return users

# session
def current_user() -> dict|None:
    if "user_id" not in session:
        return None
    user_id = int(session["user_id"])
    return {"id": user_id, **get_users([user_id])[user_id]}

@app.context_processor
def inject_globals():
    return {"me": current_user(), "n_balls": len(balls)}

# pages
@app.route("/")
def leaderboard():
    rows = get_db().execute(
        "SELECT owner_id, COUNT(*) AS total, COUNT(DISTINCT ball_type) AS types, SUM(language = 'ens') AS ernestien "
        "FROM microballs GROUP BY owner_id ORDER BY total DESC, types DESC").fetchall()
    ranking = [dict(row, rank=i+1) for i, row in enumerate(rows)]
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
    user_id = int(session["user_id"])
    rows = get_db().execute(
        "SELECT id, ball_type, catcher_id, caught_at, language FROM microballs WHERE owner_id = ? ORDER BY id DESC",
        (user_id,)).fetchall()
    counts = {}
    for row in rows:
        counts[row["ball_type"]] = counts.get(row["ball_type"], 0)+1
    users = get_users([row["catcher_id"] for row in rows])
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
            "catcher": users.get(row["catcher_id"]), "catcher_is_me": row["catcher_id"] == user_id,
            "caught_at": datetime.fromisoformat(row["caught_at"]) if row["caught_at"] else None,
        }
        if row["caught_at"] is None and row["catcher_id"] is None:
            old_groups[(row["ball_type"], row["language"])] = microball
        microballs.append(microball)
    return render_template("collection.html", balls=balls, counts=counts, microballs=microballs, n_microballs=len(rows),
                           n_ernestien=sum(row["language"] == "ens" for row in rows))

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
