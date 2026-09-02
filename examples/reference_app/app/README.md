# Reference application

A small but complete Protean app you can run from a clean clone. It takes the
golden-path blog domain from [`../blog.py`](../blog.py) and wires it to HTTP
(FastAPI), a database (SQLite), and a broker (the in-process inline broker). Two
endpoints cover the write-then-read arc:

- `POST /posts` creates and publishes a post.
- `GET /posts` returns the published-posts feed.

The domain itself is untouched: this app imports it and adds the plumbing.

## Run it

From this directory:

```bash
pip install -r requirements.txt
cd ..
uvicorn app.api:app --reload
```

That is the whole clean-clone path: SQLite on disk (`reference_app.db`) and the
inline broker, no other services. Commands and events run synchronously, so a
`POST` fills the feed before the request returns.

Walk the arc with `curl`:

```bash
# Publish a post.
curl -sS -X POST http://127.0.0.1:8000/posts \
  -H 'Content-Type: application/json' \
  -d '{"title": "Hello, Protean!", "body": "My first published post."}'
# -> {"id": "<post-id>"}

# Read the feed.
curl -sS http://127.0.0.1:8000/posts
# -> {"posts": [{"post_id": "<post-id>", "title": "Hello, Protean!"}]}
```

A post with a missing or empty title comes back as `400` with an `{"error": ...}`
body, straight from Protean's validation:

```bash
curl -sS -X POST http://127.0.0.1:8000/posts \
  -H 'Content-Type: application/json' \
  -d '{"title": "", "body": "no title"}'
# -> 400 {"error": {"title": [...]}, "correlation_id": "..."}
```

## When you are ready: PostgreSQL + Redis

The same [`domain.toml`](./domain.toml) switches to PostgreSQL and Redis through
environment variables, so you do not edit the config to change targets. Start the
optional services and point the app at them:

```bash
docker compose up -d   # older Docker installs: docker-compose up -d
cp .env.example .env
set -a && . ./.env && set +a   # export DATABASE_* and BROKER_*
cd ..
uvicorn app.api:app
```

With `DATABASE_PROVIDER=postgresql` and `BROKER_PROVIDER=redis` set, the app runs
against the containers instead of SQLite and the inline broker. Unset them (or
skip the `.env` step) and it falls back to the clean-clone path. This path also
needs the PostgreSQL and Redis adapters:

```bash
pip install 'protean[postgresql,redis,server]'
```
