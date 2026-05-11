# aa-service: Design Plan

## What it is

A FastAPI HTTP service wrapping graphify's Python API. No LLM calls — all operations
are either in-process graph reads or file writes. Claude Code handles all semantic
extraction via `/graphify --update` as before.

## File layout

```
aa-service/
  main.py          # FastAPI app, all routes
  config.py        # KB registry (load/validate kbs.json)
  ops.py           # graphify operations (query, update, save-result, etc.)
  jobs.py          # async job queue + job store
  auth.py          # optional API key check
  kbs.json         # user-edited: maps KB IDs to paths
  requirements.txt
```

## KB config (kbs.json)

```json
{
  "cwe_kb": {
    "name": "CWE Pattern Kit",
    "graphify_out": "/home/xfz/kb/cwe_kb/graphify-out",
    "raw": "/home/xfz/kb/cwe_kb/raw"
  },
  "myproject": {
    "name": "My Project",
    "graphify_out": "/data/projects/myproject/graphify-out",
    "raw": "/data/projects/myproject/raw"
  }
}
```

Add a KB = add an entry to kbs.json, no restart needed (config loaded per-request).

## API endpoints

| Method | Path                    | Sync/Async   | What it does                                          |
|--------|-------------------------|--------------|-------------------------------------------------------|
| GET    | /                       | sync         | Discovery: full API manifest with live curl examples  |
| GET    | /kb                     | sync         | List all KB IDs, names, stats                         |
| GET    | /kb/{id}                | sync         | Node/edge/community count, last updated               |
| GET    | /kb/{id}/graph          | sync         | Raw graph.json                                        |
| GET    | /kb/{id}/report         | sync         | GRAPH_REPORT.md text                                  |
| POST   | /kb/{id}/query          | sync         | BFS/DFS traversal, returns answer text                |
| POST   | /kb/{id}/path           | sync         | Shortest path between two concepts                    |
| POST   | /kb/{id}/explain        | sync         | Plain-language explanation of a node                  |
| POST   | /kb/{id}/save-result    | sync         | Write Q&A to graphify-out/memory/                     |
| POST   | /kb/{id}/update         | async → job  | AST-only incremental update (code files only)         |
| POST   | /kb/{id}/add            | sync         | Fetch URL → save to raw/ (no LLM)                     |
| GET    | /jobs/{job_id}          | sync         | Poll job status (pending/running/done/error) + result |

## Responsibility split

| Operation                 | Service does                  | Claude Code does          |
|---------------------------|-------------------------------|---------------------------|
| query / path / explain    | In-process graph read         | —                         |
| save-result               | Writes .md to memory/         | —                         |
| add <url>                 | Fetches + saves to raw/       | /graphify --update        |
| update (code files)       | AST extract + rebuild         | —                         |
| update (docs/memory)      | —                             | /graphify --update        |
| Full pipeline / rebuild   | —                             | /graphify <path>          |

## Operations detail

### GET / — Discovery endpoint

The root endpoint returns a self-describing JSON manifest. An agent that calls `curl http://host:8000/` gets everything it needs to use the API: what KBs exist, what operations are available on each, and exact ready-to-run curl commands with real KB IDs substituted in.

Response shape:
```json
{
  "service": "aa-service",
  "version": "0.1.0",
  "note": "Call any endpoint below directly. No prior knowledge needed.",
  "knowledge_bases": {
    "cwe_kb": {
      "name": "CWE Pattern Kit",
      "nodes": 46,
      "edges": 73,
      "communities": 7,
      "last_updated": "2026-04-19T16:03:00Z"
    }
  },
  "endpoints": [
    {
      "method": "POST",
      "path": "/kb/{kb_id}/query",
      "description": "BFS or DFS traversal of the graph to answer a question. Returns a text answer derived only from graph contents.",
      "request": {
        "question": "string — the question to answer",
        "mode": "\"bfs\" (default, broad context) | \"dfs\" (trace a specific path)",
        "budget": "integer — max tokens in answer (default 2000)"
      },
      "response": {
        "answer": "string",
        "nodes_visited": "integer",
        "kb_id": "string"
      },
      "example": "curl -X POST http://HOST/kb/cwe_kb/query -H 'Content-Type: application/json' -d '{\"question\": \"how does scan_file_with_card work\", \"mode\": \"bfs\"}'"
    },
    {
      "method": "POST",
      "path": "/kb/{kb_id}/path",
      "description": "Find the shortest path between two named concepts in the graph.",
      "request": {
        "from": "string — source concept name",
        "to": "string — target concept name"
      },
      "response": {
        "path": ["node label", "..."],
        "hops": "integer",
        "explanation": "string"
      },
      "example": "curl -X POST http://HOST/kb/cwe_kb/path -H 'Content-Type: application/json' -d '{\"from\": \"compile_query\", \"to\": \"Evidence Model\"}'"
    },
    {
      "method": "POST",
      "path": "/kb/{kb_id}/explain",
      "description": "Plain-language explanation of a single node — what it is, what it connects to, why those connections matter.",
      "request": {
        "node": "string — node name or partial match"
      },
      "response": {
        "label": "string",
        "explanation": "string",
        "connections": "integer"
      },
      "example": "curl -X POST http://HOST/kb/cwe_kb/explain -H 'Content-Type: application/json' -d '{\"node\": \"get_cached_language\"}'"
    },
    {
      "method": "POST",
      "path": "/kb/{kb_id}/save-result",
      "description": "Persist a Q&A result into the KB memory folder. It becomes a graph node on the next /update run in Claude Code.",
      "request": {
        "question": "string",
        "answer": "string",
        "type": "\"query\" | \"path_query\" | \"explain\" (default: query)",
        "nodes": "list of node label strings that were cited (optional)"
      },
      "response": {
        "saved_to": "string — file path written"
      },
      "example": "curl -X POST http://HOST/kb/cwe_kb/save-result -H 'Content-Type: application/json' -d '{\"question\": \"what is the evidence model\", \"answer\": \"...\", \"nodes\": [\"Evidence Model\"]}'"
    },
    {
      "method": "POST",
      "path": "/kb/{kb_id}/update",
      "description": "Trigger an AST-only incremental update for code files. Returns a job_id to poll. Doc/memory ingestion requires Claude Code /graphify --update.",
      "request": {},
      "response": {
        "job_id": "string"
      },
      "example": "curl -X POST http://HOST/kb/cwe_kb/update"
    },
    {
      "method": "POST",
      "path": "/kb/{kb_id}/add",
      "description": "Fetch a URL and save it to the raw/ folder. Semantic ingestion into the graph requires Claude Code /graphify --update afterward.",
      "request": {
        "url": "string",
        "author": "string (optional)",
        "contributor": "string (optional)"
      },
      "response": {
        "saved_to": "string — file path written",
        "note": "string — reminder to run /graphify --update in Claude Code"
      },
      "example": "curl -X POST http://HOST/kb/cwe_kb/add -H 'Content-Type: application/json' -d '{\"url\": \"https://example.com/paper.pdf\"}'"
    },
    {
      "method": "GET",
      "path": "/jobs/{job_id}",
      "description": "Poll status of an async job (e.g. update). Status: pending | running | done | error.",
      "response": {
        "job_id": "string",
        "status": "string",
        "result": "object or null",
        "error": "string or null"
      },
      "example": "curl http://HOST/jobs/abc123"
    }
  ]
}
```

`HOST` in every example is substituted at runtime with the actual `host:port` from the incoming request, so the examples are always correct regardless of how the service is deployed.

### query / path / explain
Synchronous, in-process. Calls graphify.serve._load_graph(), _bfs/_dfs(),
_subgraph_to_text() directly — same logic as the MCP server. Graph is cached in memory
per KB; reloaded when graph.json mtime changes.

Request shape (query):
  { "question": "...", "mode": "bfs|dfs", "budget": 2000 }

Request shape (path):
  { "from": "NodeA", "to": "NodeB" }

Request shape (explain):
  { "node": "NodeName" }

### save-result
Synchronous. Calls ingest.save_query_result() directly — writes a markdown file to
graphify-out/memory/. Returns the file path. No graph modification; graph update
requires a subsequent /graphify --update in Claude Code.

Request shape:
  { "question": "...", "answer": "...", "type": "query", "nodes": ["node1", "node2"] }

### update (AST-only)
Calls graphify's AST extractor + build_from_json() + cluster() + to_html() via Python
API. Skips doc/image/memory files silently. Runs as a background asyncio task —
POST /kb/{id}/update returns job_id immediately; caller polls GET /jobs/{job_id}.

### add
Synchronous. Calls ingest.ingest(url, raw_path). Returns saved file path and a note
that semantic ingestion requires /graphify --update in Claude Code.

Request shape:
  { "url": "https://...", "author": "optional", "contributor": "optional" }

## Auth
Optional X-API-Key header. Set via GRAPHIFY_SERVICE_API_KEY env var. If unset, service
is open (suitable for local/trusted-network use). Applied uniformly to all endpoints.

## Deployment

```bash
cd /home/xfz/kb/aa-service
uvicorn main:app --host 0.0.0.0 --port 8000
```

Other users on the same network point to http://<your-ip>:8000.
