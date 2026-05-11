import asyncio
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

import auth
import config
import jobs
import ops

app = FastAPI(title="aa-service", docs_url=None, redoc_url=None)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    question: str
    mode: str = "bfs"
    budget: int = 2000


class PathRequest(BaseModel):
    from_node: str = Field(alias="from")
    to: str
    model_config = {"populate_by_name": True}


class ExplainRequest(BaseModel):
    node: str


class SaveResultRequest(BaseModel):
    question: str
    answer: str
    type: str = "query"
    nodes: list[str] = []


class AddRequest(BaseModel):
    url: str
    author: str | None = None
    contributor: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_graph(graphify_out: str) -> bool:
    """True if either graph.json or graph.db exists in the KB."""
    out = Path(graphify_out)
    return (out / "graph.json").exists() or (out / "graph.db").exists()


def _get_kb_or_404(kb_id: str) -> dict:
    kb = config.get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail=f"KB '{kb_id}' not found. Call GET /kb to list available knowledge bases.")
    if not _has_graph(kb["graphify_out"]):
        raise HTTPException(status_code=503, detail=f"KB '{kb_id}' has no graph yet. Run /graphify {kb.get('raw', '')} in Claude Code first.")
    return kb


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

@app.get("/")
async def discovery(request: Request, _: None = Depends(auth.check_api_key)):
    host = _base(request)
    kbs = config.load_kbs()

    kb_summaries = {}
    for kb_id, kb_cfg in kbs.items():
        # Cheap metadata only — does not load the graph into memory.
        meta = ops.kb_meta(kb_cfg["graphify_out"]) if _has_graph(kb_cfg["graphify_out"]) else {}
        kb_summaries[kb_id] = {
            "name": kb_cfg["name"],
            **meta,
        }

    return {
        "service": "aa-service",
        "version": "0.1.0",
        "note": (
            "Call GET / to get this manifest. "
            "Use usage_patterns to construct any curl command: "
            "substitute {host} and {kb_id} from knowledge_bases keys."
        ),
        "usage_patterns": {
            "GET": f"curl {host}/{{path}}",
            "POST": f"curl -X POST {host}/{{path}} -H 'Content-Type: application/json' -d '{{...body as JSON...}}'",
        },
        "knowledge_bases": kb_summaries,
        "endpoints": [
            {
                "method": "GET",
                "path": "/kb",
                "description": "List all knowledge bases with node/edge/community counts.",
            },
            {
                "method": "GET",
                "path": "/kb/{kb_id}",
                "description": "Stats for a single knowledge base.",
            },
            {
                "method": "GET",
                "path": "/kb/{kb_id}/graph",
                "description": "Graph in node-link JSON format. All nodes and edges. Served from graph.json or materialised from graph.db transparently.",
            },
            {
                "method": "GET",
                "path": "/kb/{kb_id}/report",
                "description": "GRAPH_REPORT.md as plain text. Contains god nodes, surprising connections, and suggested questions.",
            },
            {
                "method": "POST",
                "path": "/kb/{kb_id}/query",
                "description": (
                    "BFS or DFS traversal of the graph to answer a question. "
                    "Returns the relevant subgraph as structured data and a traversal_text string "
                    "ready for an LLM to synthesize into an answer."
                ),
                "request_body": {
                    "question": "string — the question to answer",
                    "mode": '"bfs" (default, broad context) | "dfs" (trace a specific path)',
                    "budget": "integer — max tokens in traversal_text (default 2000)",
                },
                "response": {
                    "nodes": "list of matching nodes with label, source_file, community",
                    "edges": "list of edges between those nodes",
                    "traversal_text": "formatted text ready to paste into an LLM prompt",
                    "nodes_visited": "integer",
                },
            },
            {
                "method": "POST",
                "path": "/kb/{kb_id}/path",
                "description": "Find the shortest path between two named concepts in the graph.",
                "request_body": {
                    "from": "string — source concept name (partial match ok)",
                    "to": "string — target concept name (partial match ok)",
                },
                "response": {
                    "path": "list of node labels from source to target",
                    "hops": "list of {from, to, relation, confidence} dicts",
                    "length": "integer — number of hops",
                },
            },
            {
                "method": "POST",
                "path": "/kb/{kb_id}/explain",
                "description": "Return a node's metadata and all its direct connections.",
                "request_body": {
                    "node": "string — node name (partial match ok)",
                },
                "response": {
                    "label": "string",
                    "source_file": "string",
                    "degree": "integer — number of connections",
                    "connections": "list of {label, relation, confidence, source_file}",
                },
            },
            {
                "method": "POST",
                "path": "/kb/{kb_id}/save-result",
                "description": (
                    "Persist a Q&A result as a markdown file in graphify-out/memory/. "
                    "It becomes a graph node on the next /graphify --update run in Claude Code."
                ),
                "request_body": {
                    "question": "string",
                    "answer": "string",
                    "type": '"query" | "path_query" | "explain" (default: query)',
                    "nodes": "list of node label strings that were cited (optional)",
                },
                "response": {
                    "saved_to": "string — absolute path of the file written",
                },
            },
            {
                "method": "POST",
                "path": "/kb/{kb_id}/update",
                "description": (
                    "Trigger an AST-only incremental update for code files in raw/. "
                    "Returns a job_id immediately. Poll GET /jobs/{job_id} for completion. "
                    "Doc/image/memory ingestion requires /graphify --update in Claude Code."
                ),
                "request_body": {},
                "response": {
                    "job_id": "string — use with GET /jobs/{job_id}",
                },
            },
            {
                "method": "POST",
                "path": "/kb/{kb_id}/add",
                "description": (
                    "Fetch a URL and save it to the raw/ folder. "
                    "Semantic ingestion requires /graphify --update in Claude Code afterward."
                ),
                "request_body": {
                    "url": "string",
                    "author": "string (optional)",
                    "contributor": "string (optional)",
                },
                "response": {
                    "saved_to": "string — absolute path of the file written",
                    "note": "string — reminder about Claude Code ingestion",
                },
            },
            {
                "method": "GET",
                "path": "/jobs/{job_id}",
                "description": "Poll the status of an async job (e.g. from /update). Status: pending | running | done | error.",
                "response": {
                    "job_id": "string",
                    "status": "pending | running | done | error",
                    "result": "object or null",
                    "error": "string or null",
                },
            },
        ],
    }


# ---------------------------------------------------------------------------
# KB list and stats
# ---------------------------------------------------------------------------

@app.get("/kb")
async def list_kbs(request: Request, _: None = Depends(auth.check_api_key)):
    kbs = config.load_kbs()
    result = {}
    for kb_id, kb_cfg in kbs.items():
        # Cheap metadata only — does not load the graph into memory.
        meta = (
            ops.kb_meta(kb_cfg["graphify_out"])
            if _has_graph(kb_cfg["graphify_out"])
            else {"error": "no graph yet"}
        )
        result[kb_id] = {"name": kb_cfg["name"], **meta}
    return result


@app.get("/kb/{kb_id}")
async def get_kb(kb_id: str, _: None = Depends(auth.check_api_key)):
    kb = config.get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail=f"KB '{kb_id}' not found.")
    stats = (
        ops.kb_stats(kb["graphify_out"])
        if _has_graph(kb["graphify_out"])
        else {"error": "no graph yet"}
    )
    return {"kb_id": kb_id, "name": kb["name"], **stats}


@app.get("/kb/{kb_id}/graph")
async def get_graph(kb_id: str, _: None = Depends(auth.check_api_key)):
    kb = _get_kb_or_404(kb_id)
    out = Path(kb["graphify_out"])
    json_path = out / "graph.json"
    # JSON backend: zero-copy passthrough.
    if json_path.exists():
        return json_path.read_text()
    # DB backend: materialise the same node-link shape on the fly so consumers
    # parsing graph.json continue to work unchanged.
    import json as _json
    from networkx.readwrite import json_graph as _jg
    G = ops._load_graph(kb["graphify_out"])
    try:
        data = _jg.node_link_data(G, edges="links")
    except TypeError:
        data = _jg.node_link_data(G)
    data["hyperedges"] = G.graph.get("hyperedges", [])
    if G.graph.get("built_at_commit"):
        data["built_at_commit"] = G.graph["built_at_commit"]
    return _json.dumps(data)


@app.get("/kb/{kb_id}/report", response_class=PlainTextResponse)
async def get_report(kb_id: str, _: None = Depends(auth.check_api_key)):
    kb = _get_kb_or_404(kb_id)
    report_path = Path(kb["graphify_out"], "GRAPH_REPORT.md")
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="GRAPH_REPORT.md not found.")
    return report_path.read_text()


# ---------------------------------------------------------------------------
# Query / path / explain
# ---------------------------------------------------------------------------

@app.post("/kb/{kb_id}/query")
async def query(kb_id: str, req: QueryRequest, _: None = Depends(auth.check_api_key)):
    kb = _get_kb_or_404(kb_id)
    result = ops.query_graph(kb["graphify_out"], req.question, req.mode, req.budget)
    return {"kb_id": kb_id, "question": req.question, **result}


@app.post("/kb/{kb_id}/path")
async def path_query(kb_id: str, req: PathRequest, _: None = Depends(auth.check_api_key)):
    kb = _get_kb_or_404(kb_id)
    result = ops.path_between(kb["graphify_out"], req.from_node, req.to)
    return {"kb_id": kb_id, **result}


@app.post("/kb/{kb_id}/explain")
async def explain(kb_id: str, req: ExplainRequest, _: None = Depends(auth.check_api_key)):
    kb = _get_kb_or_404(kb_id)
    result = ops.explain_node(kb["graphify_out"], req.node)
    return {"kb_id": kb_id, **result}


# ---------------------------------------------------------------------------
# Save result
# ---------------------------------------------------------------------------

@app.post("/kb/{kb_id}/save-result")
async def save_result(kb_id: str, req: SaveResultRequest, _: None = Depends(auth.check_api_key)):
    kb = config.get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail=f"KB '{kb_id}' not found.")
    result = ops.save_result(kb["graphify_out"], req.question, req.answer, req.type, req.nodes)
    return {"kb_id": kb_id, **result}


# ---------------------------------------------------------------------------
# Update (async, AST-only)
# ---------------------------------------------------------------------------

@app.post("/kb/{kb_id}/update")
async def update(kb_id: str, background_tasks: BackgroundTasks, _: None = Depends(auth.check_api_key)):
    kb = config.get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail=f"KB '{kb_id}' not found.")
    if not kb.get("raw"):
        raise HTTPException(status_code=400, detail=f"KB '{kb_id}' has no 'raw' path configured.")
    job_id = jobs.create_job()
    background_tasks.add_task(ops.run_update, kb_id, kb["graphify_out"], kb["raw"], job_id)
    return {"job_id": job_id, "poll": f"/jobs/{job_id}"}


# ---------------------------------------------------------------------------
# Add URL
# ---------------------------------------------------------------------------

@app.post("/kb/{kb_id}/add")
async def add(kb_id: str, req: AddRequest, _: None = Depends(auth.check_api_key)):
    kb = config.get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail=f"KB '{kb_id}' not found.")
    if not kb.get("raw"):
        raise HTTPException(status_code=400, detail=f"KB '{kb_id}' has no 'raw' path configured.")
    try:
        result = ops.add_url(kb["raw"], req.url, req.author, req.contributor)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"kb_id": kb_id, **result}


# ---------------------------------------------------------------------------
# Job polling
# ---------------------------------------------------------------------------

@app.get("/jobs/{job_id}")
async def get_job(job_id: str, _: None = Depends(auth.check_api_key)):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return {"job_id": job_id, **job}


if __name__ == "__main__":
    import argparse
    import os
    import sys
    import uvicorn

    parser = argparse.ArgumentParser(
        prog="aa-service",
        description="HTTP API over one or more graphify knowledge bases.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address. 127.0.0.1 (default) = loopback only. "
             "0.0.0.0 = all interfaces (reachable on the network).",
    )
    parser.add_argument("--port", type=int, default=8000, help="TCP port (default 8000).")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Auto-restart workers on .py edits. Dev only — drop in production.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of uvicorn worker processes (incompatible with --reload).",
    )
    args = parser.parse_args()

    # Loud warning when exposing externally without auth — easy to miss otherwise.
    if args.host not in ("127.0.0.1", "localhost", "::1") and not os.environ.get(
        "GRAPHIFY_SERVICE_API_KEY"
    ):
        print(
            f"WARNING: binding to {args.host} (externally reachable) without "
            "GRAPHIFY_SERVICE_API_KEY set. Anyone on the network can hit this "
            "service. Set GRAPHIFY_SERVICE_API_KEY=<value> to require an "
            "X-API-Key header on every request.",
            file=sys.stderr,
        )

    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers if not args.reload else None,
    )
