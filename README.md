# aa-service

A FastAPI HTTP service exposing one or more graphify knowledge bases over a small REST API. No LLM calls — all operations are in-process graph reads, AST-only updates, or file writes. Heavy semantic ingestion happens via `/graphify --update` in Claude Code.

Supports both backend formats — `graph.json` and `graph.db` — transparently per knowledge base.

---

## Architecture

```
~/kb/
├── aa-service/      ← this service
│   ├── main.py            FastAPI routes
│   ├── ops.py             graph load/cache/query
│   ├── config.py          kbs.json reader (auto-reloads per request)
│   ├── jobs.py            async job queue for /update
│   ├── auth.py            optional X-API-Key check
│   ├── kbs.json           ← edit this to add/remove KBs
│   └── .venv/             uv-managed venv
│
├── myproject_kb/          ← one KB per directory
│   ├── raw/               source files (code, docs, papers, images)
│   └── graphify-out/      built artifacts
│       ├── graph.json     OR graph.db   (one or the other, never both)
│       ├── GRAPH_REPORT.md
│       ├── graph.html
│       └── …
└── another_kb/
    └── …
```

**Key properties**:

- `kbs.json` is re-read on every request — adding, editing, or removing a KB takes effect immediately, no restart.
- Graphs are cached by mtime — when a KB is rebuilt or re-saved on disk, the next request loads the new version automatically.
- Listing endpoints (`GET /`, `GET /kb`) return cheap metadata only and never load the graph into memory. The first per-KB query lazy-loads.
- Choice of backend (`graph.json` vs `graph.db`) is per-KB. The service auto-detects and serves a uniform JSON API regardless.

---

## One-time setup

Requires [`uv`](https://docs.astral.sh/uv/). The project is managed via `pyproject.toml`.

```bash
cd ~/kb/aa-service

uv sync                                              # creates .venv/ and installs all deps
```

Sanity check the venv:

```bash
uv run python -c "from graphify import store, db; print('store + db OK')"
```

## Running tests

The project uses `pytest` for testing. Development dependencies (including `pytest` and `httpx`) are managed via `uv`.

```bash
uv run pytest
```

---

## Build a new KB

A "KB" is just a directory with two subfolders:

```
~/kb/myproject_kb/
├── raw/              ← put source files here (any folder of code, docs, papers, images, audio, video)
└── graphify-out/     ← created by graphify on first build
```

Steps:

```bash
# 1. Make the KB directory and drop your corpus into raw/.
mkdir -p ~/kb/myproject_kb/raw
cp -r /path/to/your/source/* ~/kb/myproject_kb/raw/

# 2a. Build interactively in Claude Code (semantic + AST extraction):
#     in Claude Code, run:
#     /graphify ~/kb/myproject_kb/raw

# 2b. OR build headlessly with an API key (Gemini shown; OpenAI/Anthropic/Kimi work too):
export GEMINI_API_KEY=...
graphify extract ~/kb/myproject_kb/raw --out ~/kb/myproject_kb/graphify-out
```

After either path you'll have `~/kb/myproject_kb/graphify-out/graph.json` plus `GRAPH_REPORT.md` and `graph.html`.

### Choosing the backend

By default builds produce `graph.json`. To opt into the SQLite backend (faster incremental updates, indexed queries, single-file but binary):

```bash
# Build directly to graph.db
graphify extract ~/kb/myproject_kb/raw --out ~/kb/myproject_kb/graphify-out --db

# Or convert an existing graph.json after the fact
cd ~/kb/myproject_kb
graphify migrate-store --to db          # graph.json → graph.db
graphify migrate-store --to json        # graph.db → graph.json
```

**Only one backend per KB is allowed.** If both files end up in `graphify-out/` (e.g. interrupted migration), the service errors with a clear message; delete the unwanted one.

---

## Register the KB with the service

Edit `~/kb/aa-service/kbs.json` and add an entry. The change is picked up on the next request — **no restart needed**.

```json
{
  "myproject_kb": {
    "name": "My Project",
    "graphify_out": "/home/xfz/kb/myproject_kb/graphify-out",
    "raw": "/home/xfz/kb/myproject_kb/raw"
  }
}
```

Field reference:

| Field | Required | Purpose |
|---|---|---|
| `name` | yes | Human-readable display name |
| `graphify_out` | yes | Absolute path to the `graphify-out/` directory |
| `raw` | recommended | Absolute path to the `raw/` directory; needed for `/update` and `/add` endpoints |

The `kb_id` (the JSON object key) is what you'll use in API paths: `/kb/myproject_kb/query`.

---

## Start the service

```bash
cd ~/kb/aa-service
uv run python main.py                              # 127.0.0.1:8000 (default)
uv run python main.py --host 0.0.0.0 --port 9000   # exposed on network
uv run python main.py --reload                     # dev mode, auto-restart on .py edits
uv run python main.py --help                       # full flag list
```

Flags:

- `--host 127.0.0.1` (default) — loopback only, safest. Use `0.0.0.0` to expose on the network. The service prints a loud warning if `--host` is anything other than loopback and `GRAPHIFY_SERVICE_API_KEY` is unset.
- `--port 8000` (default) — TCP port.
- `--reload` — auto-restart on `*.py` edits. Dev only.
- `--workers N` — number of uvicorn worker processes (incompatible with `--reload`). Default 1.

Equivalent direct uvicorn invocation if you prefer (skips the security warning):

```bash
uv run uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

### Authentication (optional)

If you set `GRAPHIFY_SERVICE_API_KEY` in the environment, every request must include `X-API-Key: <value>`:

```bash
GRAPHIFY_SERVICE_API_KEY=secret123 ./.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

When the env var is unset (default), all endpoints are open. **Always set it when binding to `0.0.0.0`.**

### Run as a background daemon

For long-lived deployment, use systemd / supervisord / nohup:

```bash
nohup ./.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 \
  > /tmp/aa-service.log 2>&1 &
```

To stop:

```bash
pkill -f 'uvicorn main:app'
```

---

## Test it

### Discovery (no graph loaded)

```bash
curl -s http://127.0.0.1:8000/ | python3 -m json.tool
```

Returns the manifest: every endpoint, request/response schemas, and a one-line summary per KB (`backend`, `last_updated`, plus cheap counts for DB-backed KBs).

### List KBs

```bash
curl -s http://127.0.0.1:8000/kb | python3 -m json.tool
```

### Single-KB stats (lazy-loads the graph the first time)

```bash
curl -s http://127.0.0.1:8000/kb/myproject_kb | python3 -m json.tool
```

Response includes `nodes`, `edges`, `communities`, `backend`, `last_updated`.

### Query the graph (BFS or DFS traversal)

```bash
curl -s -X POST http://127.0.0.1:8000/kb/myproject_kb/query \
  -H 'Content-Type: application/json' \
  -d '{"question": "how is authentication handled", "mode": "bfs", "budget": 2000}' \
  | python3 -m json.tool
```

Returns:
- `nodes` — list of relevant nodes with label / source / community
- `edges` — relations between them
- `traversal_text` — formatted text ready to paste into an LLM prompt
- `nodes_visited` — count

`mode`: `bfs` (default, broad context) or `dfs` (trace one path).
`budget`: cap on tokens in `traversal_text` (default 2000).

### Shortest path between two concepts

```bash
curl -s -X POST http://127.0.0.1:8000/kb/myproject_kb/path \
  -H 'Content-Type: application/json' \
  -d '{"from": "AuthModule", "to": "Database"}' \
  | python3 -m json.tool
```

### Explain a single node

```bash
curl -s -X POST http://127.0.0.1:8000/kb/myproject_kb/explain \
  -H 'Content-Type: application/json' \
  -d '{"node": "SessionManager"}' \
  | python3 -m json.tool
```

### Raw graph (always returned in node-link JSON shape)

```bash
curl -s http://127.0.0.1:8000/kb/myproject_kb/graph > graph.json
```

For JSON-backed KBs this is a passthrough. For DB-backed KBs the same shape is materialised on the fly so consumers don't need to know which backend a KB uses.

### GRAPH_REPORT.md

```bash
curl -s http://127.0.0.1:8000/kb/myproject_kb/report
```

### Trigger an AST-only incremental update (async)

Picks up changes to **code files only** — doc/paper/image changes still require a `/graphify --update` run in Claude Code.

```bash
JOB=$(curl -s -X POST http://127.0.0.1:8000/kb/myproject_kb/update | python3 -c "import json,sys; print(json.load(sys.stdin)['job_id'])")
echo "job: $JOB"

# Poll status
while true; do
    STATUS=$(curl -s http://127.0.0.1:8000/jobs/$JOB)
    echo "$STATUS"
    case "$STATUS" in *'"status":"done"'*|*'"status":"error"'*) break ;; esac
    sleep 2
done
```

### Add a URL to the corpus (saves to `raw/`, re-extract via Claude Code afterwards)

```bash
curl -s -X POST http://127.0.0.1:8000/kb/myproject_kb/add \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://arxiv.org/abs/2106.09685", "author": "Hu et al"}' \
  | python3 -m json.tool
```

---

## Auto-reload behaviour

These changes are picked up **without restarting the service**:

| Change | Picked up by |
|---|---|
| Add / edit / remove an entry in `kbs.json` | next request to any endpoint |
| Rebuild a KB (`graph.json` mtime changes) | next request that touches that KB |
| Migrate a KB between backends (`graph.json` ↔ `graph.db`) | next request that touches that KB |
| Edit a `*.py` file in `~/kb/aa-service/` | uvicorn `--reload` restarts the worker |

What **does** require a restart:

- Adding / removing a Python dependency in `.venv/`
- Changing `--host`, `--port`, or auth env vars

---

## Common gotchas

- **`Address already in use`**: another uvicorn is on the port. `pkill -f 'uvicorn main:app'` then restart.
- **`ImportError: cannot import name 'store' from graphify'`**: the venv has an old graphify wheel. Re-run `uv pip install -e /path/to/your/graphify`.
- **`uv run` picks up the wrong venv**: uv walks up the directory tree looking for a project. Always invoke uvicorn directly via `./.venv/bin/uvicorn …` to be unambiguous.
- **`KB has no graph yet`**: confirm `graphify_out` path is correct and contains either `graph.json` or `graph.db`. Run `ls $graphify_out`.
- **`Both graph.json and graph.db exist`**: a migration was interrupted or you built twice with different `--db` settings. Delete the one you don't want and the next request resolves correctly.

---

## API reference (quick map)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Discovery manifest with per-KB summaries |
| `GET` | `/kb` | List all KBs (cheap metadata) |
| `GET` | `/kb/{kb_id}` | Single-KB full stats (loads graph on demand) |
| `GET` | `/kb/{kb_id}/graph` | Full graph in node-link JSON shape |
| `GET` | `/kb/{kb_id}/report` | `GRAPH_REPORT.md` as text |
| `POST` | `/kb/{kb_id}/query` | BFS/DFS traversal for a question |
| `POST` | `/kb/{kb_id}/path` | Shortest path between two named concepts |
| `POST` | `/kb/{kb_id}/explain` | Node + neighbors |
| `POST` | `/kb/{kb_id}/save-result` | Write a Q&A result to `graphify-out/memory/` |
| `POST` | `/kb/{kb_id}/update` | Trigger AST-only update job |
| `POST` | `/kb/{kb_id}/add` | Fetch a URL into `raw/` |
| `GET` | `/jobs/{job_id}` | Poll an async job |

For full request/response schemas, hit `GET /` — the manifest documents every endpoint inline.
