#!/usr/bin/env bash
# update the website: git pull, then stop the website and start it again
# usage: ./reloadweb.sh            (from anywhere)
# logs: web.log

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

PORT=3008
PID_FILE="web.pid"
LOG_FILE="web.log"

# update the code first: if the pull fails, the website keeps running with the old code
echo "📥 Mise à jour du code..."
git pull --ff-only
.venv/bin/pip install -q -r web/requirements.txt

# stop the website (SIGTERM: gunicorn finishes the current requests before stopping)
pids=""
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    pids="$(cat "$PID_FILE")"
fi
# also the ones started by hand (only real gunicorn processes, not a shell whose command contains "gunicorn")
pids="$pids $(ps -eo pid=,comm=,args= | awk '$2 !~ /^(bash|sh|zsh|fish|dash)$/ && /bin\/gunicorn .*web\.app:app/ {print $1}')"
pids="$(echo $pids | tr ' ' '\n' | sort -u | tr '\n' ' ')"
if [ -n "${pids// /}" ]; then
    echo "🛑 Arrêt du site..."
    kill -TERM $pids 2>/dev/null || true
    for _ in $(seq 1 30); do
        alive=""
        for pid in $pids; do kill -0 "$pid" 2>/dev/null && alive="yes"; done
        [ -z "$alive" ] && break
        sleep 1
    done
    if [ -n "$alive" ]; then
        echo "⚠️  Le site ne s'arrête pas, arrêt forcé"
        kill -KILL $pids 2>/dev/null || true
    fi
else
    echo "💤 Le site ne tournait pas"
fi
rm -f "$PID_FILE"

# start the website in the background
echo "🚀 Lancement du site..."
.venv/bin/gunicorn -w 2 -b "127.0.0.1:$PORT" --pid "$PID_FILE" --daemon \
    --access-logfile "$LOG_FILE" --error-logfile "$LOG_FILE" web.app:app

sleep 2
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "✅ Site relancé sur le port $PORT (logs : $LOG_FILE)"
else
    echo "❌ Le site n'a pas démarré, dernières lignes de $LOG_FILE :"
    tail -n 20 "$LOG_FILE"
    exit 1
fi
