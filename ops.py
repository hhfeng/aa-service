import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import networkx as nx
from networkx.readwrite import json_graph

import jobs

_graph_cache: dict[str, dict] = {}
_update_locks: dict[str, asyncio.Lock] = {}


# ---------------------------------------------------------------------------
# Graph loading (cached per KB, invalidated on graph artifact mtime change).
# Backend-aware: handles graph.json or graph.db transparently.
# ---------------------------------------------------------------------------

def _graph_artifact_path(graphify_out: str) -> Path | None:
    """Return whichever graph artifact exists in graphify_out, or None."""
    out = Path(graphify_out)
    db_path = out / "graph.db"
    if db_path.exists():
        return db_path
    json_path = out / "graph.json"
    if json_path.exists():
        return json_path
    return None


def _load_graph(graphify_out: str) -> nx.Graph:
    from graphify import store
    artifact = _graph_artifact_path(graphify_out)
    if artifact is None:
        raise FileNotFoundError(f"No graph found in {graphify_out} (neither graph.json nor graph.db).")
    mtime = artifact.stat().st_mtime
    cached = _graph_cache.get(graphify_out)
    if cached and cached["mtime"] == mtime and cached.get("artifact") == str(artifact):
        return cached["G"]
    G = store.load(Path(graphify_out))
    _graph_cache[graphify_out] = {"G": G, "mtime": mtime, "artifact": str(artifact)}
    return G


def _score_nodes(G: nx.Graph, text: str) -> list[str]:
    terms = [t.lower() for t in re.split(r"\W+", text) if len(t) > 3]
    scored = []
    for nid, ndata in G.nodes(data=True):
        label = ndata.get("label", "").lower()
        score = sum(1 for t in terms if t in label)
        if score > 0:
            scored.append((score, nid))
    scored.sort(reverse=True)
    return [nid for _, nid in scored[:3]]


def _find_node(G: nx.Graph, term: str) -> str | None:
    term_lower = term.lower()
    scored = sorted(
        [
            (sum(1 for w in term_lower.split() if w in G.nodes[n].get("label", "").lower()), n)
            for n in G.nodes()
        ],
        reverse=True,
    )
    return scored[0][1] if scored and scored[0][0] > 0 else None


# ---------------------------------------------------------------------------
# KB stats
# ---------------------------------------------------------------------------

def kb_meta(graphify_out: str) -> dict:
    """Cheap metadata for listing endpoints — does NOT load the graph.

    For graph.db, counts come from SQL aggregates (fast, indexed). For
    graph.json, counts are omitted (parsing the file would defeat lazy loading).
    Use kb_stats() when full NetworkX-derived stats are needed.
    """
    artifact = _graph_artifact_path(graphify_out)
    if artifact is None:
        return {"error": "no graph found (neither graph.json nor graph.db)"}
    backend = artifact.suffix.lstrip(".")  # "json" or "db"
    meta = {
        "backend": backend,
        "last_updated": datetime.fromtimestamp(artifact.stat().st_mtime, tz=timezone.utc).isoformat(),
    }
    if backend == "db":
        # Cheap counts via SQL — no NetworkX construction.
        import sqlite3
        try:
            conn = sqlite3.connect(artifact)
            try:
                meta["nodes"] = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
                meta["edges"] = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
                row = conn.execute(
                    "SELECT COUNT(DISTINCT community) FROM nodes WHERE community IS NOT NULL"
                ).fetchone()
                meta["communities"] = row[0] if row else 0
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            pass  # corrupt db — caller will surface a real error if they query
    else:
        # JSON: no cheap counts without parsing. Listing endpoints get a
        # placeholder; full kb_stats() can be called for accurate numbers.
        meta["size_bytes"] = artifact.stat().st_size
    return meta


def kb_stats(graphify_out: str) -> dict:
    """Full stats — loads (and caches) the NetworkX graph. Use for endpoints
    that already need the graph anyway, or when accurate counts matter."""
    artifact = _graph_artifact_path(graphify_out)
    if artifact is None:
        return {"error": "no graph found (neither graph.json nor graph.db)"}
    G = _load_graph(graphify_out)
    communities = {d.get("community") for _, d in G.nodes(data=True) if d.get("community") is not None}
    return {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "communities": len(communities),
        "backend": artifact.suffix.lstrip("."),  # "json" or "db"
        "last_updated": datetime.fromtimestamp(artifact.stat().st_mtime, tz=timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Query (BFS / DFS)
# ---------------------------------------------------------------------------

def query_graph(graphify_out: str, question: str, mode: str = "bfs", budget: int = 2000) -> dict:
    G = _load_graph(graphify_out)
    start_nodes = _score_nodes(G, question)

    if not start_nodes:
        return {
            "nodes": [],
            "edges": [],
            "traversal_text": "No matching nodes found.",
            "nodes_visited": 0,
        }

    subgraph_nodes: set[str] = set()
    subgraph_edges: list[tuple[str, str]] = []

    if mode == "dfs":
        visited: set[str] = set()
        stack = [(n, 0) for n in reversed(start_nodes)]
        while stack:
            node, depth = stack.pop()
            if node in visited or depth > 6:
                continue
            visited.add(node)
            subgraph_nodes.add(node)
            for neighbor in G.neighbors(node):
                if neighbor not in visited:
                    stack.append((neighbor, depth + 1))
                    subgraph_edges.append((node, neighbor))
    else:
        frontier = set(start_nodes)
        subgraph_nodes = set(start_nodes)
        for _ in range(3):
            next_frontier: set[str] = set()
            for n in frontier:
                for neighbor in G.neighbors(n):
                    if neighbor not in subgraph_nodes:
                        next_frontier.add(neighbor)
                        subgraph_edges.append((n, neighbor))
            subgraph_nodes.update(next_frontier)
            frontier = next_frontier

    terms = [t.lower() for t in re.split(r"\W+", question) if len(t) > 3]

    def relevance(nid: str) -> int:
        return sum(1 for t in terms if t in G.nodes[nid].get("label", "").lower())

    ranked = sorted(subgraph_nodes, key=relevance, reverse=True)
    char_budget = budget * 4

    lines = [
        f"Traversal: {mode.upper()} | Start: {[G.nodes[n].get('label', n) for n in start_nodes]} | {len(subgraph_nodes)} nodes"
    ]
    node_objects = []
    edge_objects = []

    for nid in ranked:
        d = G.nodes[nid]
        node_objects.append(
            {
                "id": nid,
                "label": d.get("label", nid),
                "source_file": d.get("source_file", ""),
                "source_location": d.get("source_location", ""),
                "community": d.get("community"),
            }
        )
        lines.append(
            f"NODE {d.get('label', nid)} [src={d.get('source_file', '')} "
            f"loc={d.get('source_location', '')} community={d.get('community', '')}]"
        )

    seen_edges: set[tuple[str, str]] = set()
    for u, v in subgraph_edges:
        if u not in subgraph_nodes or v not in subgraph_nodes:
            continue
        key = (u, v)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        try:
            ed = G[u][v]
        except KeyError:
            ed = {}
        edge_objects.append(
            {
                "source": G.nodes[u].get("label", u),
                "target": G.nodes[v].get("label", v),
                "relation": ed.get("relation", ""),
                "confidence": ed.get("confidence", ""),
            }
        )
        lines.append(
            f"EDGE {G.nodes[u].get('label', u)} --{ed.get('relation', '')} "
            f"[{ed.get('confidence', '')}]--> {G.nodes[v].get('label', v)}"
        )

    text = "\n".join(lines)
    if len(text) > char_budget:
        text = text[:char_budget] + f"\n... (truncated at ~{budget} token budget)"

    return {
        "nodes": node_objects,
        "edges": edge_objects,
        "traversal_text": text,
        "nodes_visited": len(subgraph_nodes),
    }


# ---------------------------------------------------------------------------
# Shortest path
# ---------------------------------------------------------------------------

def path_between(graphify_out: str, from_node: str, to_node: str) -> dict:
    G = _load_graph(graphify_out)
    src = _find_node(G, from_node)
    tgt = _find_node(G, to_node)

    if not src:
        return {"error": f"No node matching '{from_node}'", "path": [], "hops": []}
    if not tgt:
        return {"error": f"No node matching '{to_node}'", "path": [], "hops": []}

    try:
        path = nx.shortest_path(G, src, tgt)
    except nx.NetworkXNoPath:
        return {"error": f"No path between '{from_node}' and '{to_node}'", "path": [], "hops": []}
    except nx.NodeNotFound as e:
        return {"error": str(e), "path": [], "hops": []}

    hops = []
    for i in range(len(path) - 1):
        try:
            ed = G[path[i]][path[i + 1]]
        except KeyError:
            ed = {}
        hops.append(
            {
                "from": G.nodes[path[i]].get("label", path[i]),
                "to": G.nodes[path[i + 1]].get("label", path[i + 1]),
                "relation": ed.get("relation", ""),
                "confidence": ed.get("confidence", ""),
            }
        )

    return {
        "path": [G.nodes[n].get("label", n) for n in path],
        "hops": hops,
        "length": len(path) - 1,
    }


# ---------------------------------------------------------------------------
# Explain node
# ---------------------------------------------------------------------------

def explain_node(graphify_out: str, node_name: str) -> dict:
    G = _load_graph(graphify_out)
    nid = _find_node(G, node_name)
    if not nid:
        return {"error": f"No node matching '{node_name}'"}

    ndata = G.nodes[nid]
    connections = []
    for neighbor in G.neighbors(nid):
        try:
            ed = G[nid][neighbor]
        except KeyError:
            ed = {}
        connections.append(
            {
                "label": G.nodes[neighbor].get("label", neighbor),
                "relation": ed.get("relation", ""),
                "confidence": ed.get("confidence", ""),
                "source_file": G.nodes[neighbor].get("source_file", ""),
            }
        )

    return {
        "label": ndata.get("label", nid),
        "source_file": ndata.get("source_file", ""),
        "source_location": ndata.get("source_location", ""),
        "file_type": ndata.get("file_type", ""),
        "degree": G.degree(nid),
        "connections": connections,
    }


# ---------------------------------------------------------------------------
# Save result
# ---------------------------------------------------------------------------

def save_result(
    graphify_out: str,
    question: str,
    answer: str,
    query_type: str = "query",
    nodes: list[str] | None = None,
) -> dict:
    from graphify.ingest import save_query_result

    memory_dir = Path(graphify_out) / "memory"
    memory_dir.mkdir(exist_ok=True)
    path = save_query_result(question, answer, memory_dir, query_type, nodes or [])
    return {"saved_to": str(path)}


# ---------------------------------------------------------------------------
# Add URL
# ---------------------------------------------------------------------------

def add_url(
    raw: str,
    url: str,
    author: str | None = None,
    contributor: str | None = None,
) -> dict:
    from graphify.ingest import ingest

    path = ingest(url, Path(raw), author=author, contributor=contributor)
    return {
        "saved_to": str(path),
        "note": "File saved. Run /graphify --update in Claude Code to ingest semantically into the graph.",
    }


# ---------------------------------------------------------------------------
# Async update (AST-only, code files only)
# ---------------------------------------------------------------------------

async def run_update(kb_id: str, graphify_out: str, raw: str, job_id: str) -> None:
    if kb_id not in _update_locks:
        _update_locks[kb_id] = asyncio.Lock()

    async with _update_locks[kb_id]:
        jobs.set_running(job_id)
        try:
            await asyncio.get_event_loop().run_in_executor(None, _do_update, kb_id, graphify_out, raw, job_id)
        except Exception as e:
            jobs.set_error(job_id, str(e))


def _do_update(kb_id: str, graphify_out: str, raw: str, job_id: str) -> None:
    from graphify import store
    from graphify.analyze import god_nodes, surprising_connections, suggest_questions
    from graphify.build import build_from_json
    from graphify.cluster import cluster, score_all
    from graphify.detect import detect_incremental, save_manifest
    from graphify.export import to_html
    from graphify.extract import collect_files, extract
    from graphify.report import generate

    result = detect_incremental(Path(raw))
    code_files = [Path(f) for f in result.get("new_files", {}).get("code", [])]

    if not code_files:
        jobs.set_done(job_id, {"message": "No code changes detected.", "nodes_added": 0})
        return

    # Expand any directories to individual files
    expanded: list[Path] = []
    for f in code_files:
        expanded.extend(collect_files(f) if f.is_dir() else [f])

    # AST extraction on changed code files
    new_extraction = extract(expanded, cache_root=Path(graphify_out).parent)

    # Load existing graph (backend-aware: graph.json or graph.db)
    G_existing = store.load(Path(graphify_out))
    old_count = G_existing.number_of_nodes()

    # Prune nodes from deleted files
    deleted = set(result.get("deleted_files", []))
    if deleted:
        to_remove = [n for n, d in G_existing.nodes(data=True) if d.get("source_file") in deleted]
        G_existing.remove_nodes_from(to_remove)

    # Merge new AST nodes into existing graph
    G_new = build_from_json(new_extraction)
    G_existing.update(G_new)

    # Re-serialize merged graph for build_from_json
    merged = {
        "nodes": [{"id": n, **{k: v for k, v in d.items() if k != "id"}} for n, d in G_existing.nodes(data=True)],
        "edges": [{"source": u, "target": v, **d} for u, v, d in G_existing.edges(data=True)],
        "hyperedges": [],
        "input_tokens": 0,
        "output_tokens": 0,
    }

    G_final = build_from_json(merged)
    communities = cluster(G_final)
    cohesion = score_all(G_final, communities)
    gods = god_nodes(G_final)
    surprises = surprising_connections(G_final, communities)
    labels: dict[int, str] = {}
    questions = suggest_questions(G_final, communities, labels)

    detection = {
        "total_files": result.get("new_total", 0),
        "total_words": 0,
        "needs_graph": True,
        "warning": None,
        "files": result.get("files", {}),
    }
    tokens = {"input": 0, "output": 0}
    report = generate(G_final, communities, cohesion, labels, gods, surprises, detection, tokens, raw, suggested_questions=questions)
    Path(graphify_out, "GRAPH_REPORT.md").write_text(report)

    # Backend-aware save: respects whichever artifact exists in graphify_out.
    store.save(Path(graphify_out), G_final, communities, force=True)
    to_html(G_final, communities, str(Path(graphify_out) / "graph.html"))

    save_manifest(result.get("files", {}))

    # Invalidate graph cache so next query reloads from disk
    _graph_cache.pop(graphify_out, None)

    nodes_added = G_final.number_of_nodes() - old_count
    jobs.set_done(
        job_id,
        {
            "message": f"Updated: {G_final.number_of_nodes()} nodes, {G_final.number_of_edges()} edges",
            "nodes_added": max(0, nodes_added),
            "code_files_processed": len(expanded),
        },
    )
