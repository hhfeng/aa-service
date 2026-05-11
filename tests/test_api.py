import pytest

def test_discovery(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "aa-service"
    assert "test_kb" in data["knowledge_bases"]
    assert data["knowledge_bases"]["test_kb"]["name"] == "Test KB"

def test_list_kbs(client):
    response = client.get("/kb")
    assert response.status_code == 200
    data = response.json()
    assert "test_kb" in data
    assert data["test_kb"]["name"] == "Test KB"
    assert data["test_kb"]["nodes"] == 10

def test_get_kb_stats(client):
    response = client.get("/kb/test_kb")
    assert response.status_code == 200
    data = response.json()
    assert data["kb_id"] == "test_kb"
    assert data["nodes"] == 10
    assert data["communities"] == 2

def test_get_kb_not_found(client):
    response = client.get("/kb/unknown_kb")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

def test_query_kb(client):
    from unittest.mock import patch
    mock_result = {
        "nodes": [{"id": "n1", "label": "Node 1"}],
        "edges": [],
        "traversal_text": "Traversal text",
        "nodes_visited": 1
    }
    with patch("ops.query_graph", return_value=mock_result):
        response = client.post("/kb/test_kb/query", json={"question": "test question"})
        assert response.status_code == 200
        data = response.json()
        assert data["kb_id"] == "test_kb"
        assert data["question"] == "test question"
        assert data["nodes"][0]["label"] == "Node 1"

def test_path_query(client):
    from unittest.mock import patch
    mock_result = {
        "path": ["A", "B"],
        "hops": [{"from": "A", "to": "B", "relation": "connects", "confidence": "high"}],
        "length": 1
    }
    with patch("ops.path_between", return_value=mock_result):
        response = client.post("/kb/test_kb/path", json={"from": "A", "to": "B"})
        assert response.status_code == 200
        data = response.json()
        assert data["path"] == ["A", "B"]
        assert data["length"] == 1

def test_explain_node(client):
    from unittest.mock import patch
    mock_result = {
        "label": "Node A",
        "degree": 5,
        "connections": []
    }
    with patch("ops.explain_node", return_value=mock_result):
        response = client.post("/kb/test_kb/explain", json={"node": "Node A"})
        assert response.status_code == 200
        data = response.json()
        assert data["label"] == "Node A"
        assert data["degree"] == 5
