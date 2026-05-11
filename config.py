import json
from pathlib import Path

_KBS_PATH = Path(__file__).parent / "kbs.json"


def load_kbs() -> dict:
    if not _KBS_PATH.exists():
        return {}
    return json.loads(_KBS_PATH.read_text())


def get_kb(kb_id: str) -> dict | None:
    return load_kbs().get(kb_id)
