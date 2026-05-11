import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def mock_kbs():
    return {
        "test_kb": {
            "name": "Test KB",
            "graphify_out": "/tmp/test_kb/graphify-out",
            "raw": "/tmp/test_kb/raw"
        }
    }

@pytest.fixture(autouse=True)
def patch_config(mock_kbs):
    with patch("config.load_kbs", return_value=mock_kbs):
        with patch("config.get_kb", side_effect=lambda kb_id: mock_kbs.get(kb_id)):
            yield

@pytest.fixture(autouse=True)
def patch_ops():
    with patch("ops.kb_meta", return_value={"backend": "json", "nodes": 10, "edges": 20}):
        with patch("ops.kb_stats", return_value={"nodes": 10, "edges": 20, "communities": 2, "backend": "json"}):
            with patch("main._has_graph", return_value=True):
                yield
