import pytest
from pathlib import Path
from ops import _graph_artifact_path, kb_meta

def test_graph_artifact_path_json(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    json_path = out / "graph.json"
    json_path.write_text("{}")
    
    assert _graph_artifact_path(str(out)) == json_path

def test_graph_artifact_path_db(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    db_path = out / "graph.db"
    db_path.write_text("")
    
    assert _graph_artifact_path(str(out)) == db_path

def test_graph_artifact_path_none(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    
    assert _graph_artifact_path(str(out)) is None

def test_kb_meta_json(tmp_path):
    out = tmp_path / "graphify-out"
    out.mkdir()
    json_path = out / "graph.json"
    json_path.write_text("hello") # dummy content
    
    meta = kb_meta(str(out))
    assert meta["backend"] == "json"
    assert "last_updated" in meta
    assert meta["size_bytes"] == 5

def test_kb_meta_not_found(tmp_path):
    meta = kb_meta(str(tmp_path / "nonexistent"))
    assert "error" in meta
