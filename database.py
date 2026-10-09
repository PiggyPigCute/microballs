import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "microballs.db")

# languages in which a MicroBall can be caught
# → key: code stored in the database (also the suffix of the columns in balls.csv: regex_fr, nom_ens...)
# → value: display name
LANGUAGES = {"fr": "français", "ens": "ernestien"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS languages (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

-- one row per MicroBall
CREATE TABLE IF NOT EXISTS microballs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ball_type  TEXT    NOT NULL,                          -- id of the ball in balls.csv
    owner_id   INTEGER NOT NULL,                          -- discord id of the current owner
    catcher_id INTEGER,                                   -- discord id of the catcher (NULL if unknown)
    caught_at  TEXT,                                      -- ISO 8601 UTC date (NULL if unknown)
    language   TEXT    NOT NULL REFERENCES languages(code)
);
CREATE INDEX IF NOT EXISTS microballs_owner ON microballs(owner_id, ball_type);

CREATE TABLE IF NOT EXISTS spawn_channels (
    guild_id   INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    special    TEXT
);

-- history of the MicroBalls given from a player to another
CREATE TABLE IF NOT EXISTS transfers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    microball_id   INTEGER NOT NULL REFERENCES microballs(id),
    from_id        INTEGER NOT NULL,
    to_id          INTEGER NOT NULL,
    transferred_at TEXT    NOT NULL                       -- ISO 8601 UTC date
);
CREATE INDEX IF NOT EXISTS transfers_microball ON transfers(microball_id);

-- discord profiles, used by the website to display names and avatars
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT NOT NULL,
    global_name TEXT,                                     -- display name (NULL if the same as username)
    avatar      TEXT,                                     -- avatar hash (NULL for the default avatar)
    updated_at  TEXT NOT NULL                             -- ISO 8601 UTC date
);
"""

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def connect() -> sqlite3.Connection:
    # open a new connection (the bot uses 𝑐𝑜𝑛, the website opens one per request)
    # WAL mode allows the website to read while the bot writes
    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection

con = connect()

def init_db():
    # create the tables if they don't exist and register the 𝐿𝐴𝑁𝐺𝑈𝐴𝐺𝐸𝑆
    with con:
        con.executescript(SCHEMA)
        con.executemany("INSERT OR REPLACE INTO languages (code, name) VALUES (?, ?)", LANGUAGES.items())

# microballs
def add_ball(ball_type:str, owner_id:int, language:str, catcher_id:int|None=None, caught_at:str|None=None) -> int:
    # insert a new MicroBall and return its id
    # → 𝑐𝑎𝑢𝑔ℎ𝑡_𝑎𝑡: if None and 𝑐𝑎𝑡𝑐ℎ𝑒𝑟_𝑖𝑑 is given, the current date is used
    if caught_at is None and catcher_id is not None:
        caught_at = now()
    with con:
        cursor = con.execute(
            "INSERT INTO microballs (ball_type, owner_id, catcher_id, caught_at, language) VALUES (?, ?, ?, ?, ?)",
            (ball_type, owner_id, catcher_id, caught_at, language))
    return cursor.lastrowid

def catch_ball(ball_type:str, catcher_id:int, language:str) -> int:
    # register a MicroBall caught by 𝑐𝑎𝑡𝑐ℎ𝑒𝑟_𝑖𝑑 (who becomes its owner)
    return add_ball(ball_type, catcher_id, language, catcher_id=catcher_id)

def count_balls(owner_id:int, language:str|None=None) -> dict[str,int]:
    # return {ball_type: amount} of the MicroBalls owned by 𝑜𝑤𝑛𝑒𝑟_𝑖𝑑
    # → 𝑙𝑎𝑛𝑔𝑢𝑎𝑔𝑒: if given, only count the MicroBalls caught in this language
    query = "SELECT ball_type, COUNT(*) FROM microballs WHERE owner_id = ?"
    params = [owner_id]
    if language is not None:
        query += " AND language = ?"
        params.append(language)
    return dict(con.execute(query+" GROUP BY ball_type", params).fetchall())

def give_balls(from_id:int, to_id:int, microball_ids:list[int], old_groups:dict[tuple[str,str],int],
               connection:sqlite3.Connection|None=None) -> list[int]|None:
    # give MicroBalls from 𝑓𝑟𝑜𝑚_𝑖𝑑 to 𝑡𝑜_𝑖𝑑 and record it in the 𝑡𝑟𝑎𝑛𝑠𝑓𝑒𝑟𝑠 table, all or nothing
    # → 𝑚𝑖𝑐𝑟𝑜𝑏𝑎𝑙𝑙_𝑖𝑑𝑠: ids of the MicroBalls to give
    # → 𝑜𝑙𝑑_𝑔𝑟𝑜𝑢𝑝𝑠: {(ball_type, language): amount} of old MicroBalls (no catcher, no date) to give
    # return the ids of the given MicroBalls, or None if 𝑓𝑟𝑜𝑚_𝑖𝑑 doesn't own all of them (nothing is given)
    connection = connection or con
    if connection.in_transaction:
        connection.commit()
    connection.execute("BEGIN IMMEDIATE")  # lock the database: the balls can't change owner between the check and the update
    try:
        ids = list(dict.fromkeys(microball_ids))
        if ids:
            placeholders = ",".join("?"*len(ids))
            owned = connection.execute(f"SELECT COUNT(*) FROM microballs WHERE owner_id = ? AND id IN ({placeholders})",
                                       [from_id]+ids).fetchone()[0]
            if owned != len(ids):
                connection.rollback()
                return None
        for (ball_type, language), amount in old_groups.items():
            rows = connection.execute(
                "SELECT id FROM microballs WHERE owner_id = ? AND ball_type = ? AND language = ? AND catcher_id IS NULL AND caught_at IS NULL "
                "ORDER BY id LIMIT ?", (from_id, ball_type, language, amount)).fetchall()
            if len(rows) < amount:
                connection.rollback()
                return None
            ids += [row[0] for row in rows]
        date = now()
        connection.executemany("UPDATE microballs SET owner_id = ? WHERE id = ?", [(to_id, i) for i in ids])
        connection.executemany("INSERT INTO transfers (microball_id, from_id, to_id, transferred_at) VALUES (?, ?, ?, ?)",
                               [(i, from_id, to_id, date) for i in ids])
        connection.commit()
        return ids
    except BaseException:
        connection.rollback()
        raise

# spawn channels
def get_spawn_channels() -> dict[int,int]:
    # return {guild_id: channel_id}
    return dict(con.execute("SELECT guild_id, channel_id FROM spawn_channels").fetchall())

def set_spawn_channel(guild_id:int, channel_id:int):
    with con:
        con.execute(
            "INSERT INTO spawn_channels (guild_id, channel_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id",
            (guild_id, channel_id))

# users
def save_user(user_id:int, username:str, global_name:str|None, avatar:str|None, connection:sqlite3.Connection|None=None):
    # insert or update the discord profile of a user
    connection = connection or con
    with connection:
        connection.execute(
            "INSERT INTO users (id, username, global_name, avatar, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET username = excluded.username, global_name = excluded.global_name, avatar = excluded.avatar, updated_at = excluded.updated_at",
            (user_id, username, global_name, avatar, now()))
