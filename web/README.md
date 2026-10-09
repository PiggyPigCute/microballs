# Site MicroBalls

Site Flask qui lit la même base `microballs.db` que le bot : il doit donc tourner **sur la même machine, dans le même dossier `microballs/`**.

## 1. Discord Developer Portal

Dans l'application du bot → **OAuth2** :
- ajouter la redirection `https://microballs.chruk.fr/callback` ;
- récupérer le **Client Secret** (bouton « Reset Secret » si besoin).

## 2. Configuration

Créer `microballs/web.lock` (ignoré par git) :

```json
{
  "client_secret": "le client secret de Discord",
  "secret_key": "une longue chaîne aléatoire"
}
```

- `secret_key` signe les cookies de session : `python -c "import secrets; print(secrets.token_hex(32))"`.
- Le token du bot est lu dans `token.lock` ; il sert à récupérer les pseudos et avatars des joueurs pour le classement. On peut aussi le mettre dans `web.lock` (`"bot_token"`).
- Pour tester en local : ajouter `"redirect_uri": "http://localhost:3008/callback"` (et cette redirection sur le portail Discord).

## 3. Installation

```sh
cd microballs
python -m venv .venv
.venv/bin/pip install -r web/requirements.txt
```

## 4. Lancement

```sh
cd microballs
.venv/bin/gunicorn -w 2 -b 127.0.0.1:3008 web.app:app
```

En local : `.venv/bin/flask --app web.app run --port 3008`.

Derrière un reverse proxy HTTPS (nginx, Caddy…) qui transmet `X-Forwarded-Proto` et `X-Forwarded-Host`. Exemple Caddy :

```
microballs.chruk.fr {
    reverse_proxy 127.0.0.1:3008
}
```
