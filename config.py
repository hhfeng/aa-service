import json
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    # Running in a PyInstaller bundle
    _KBS_PATH = Path(sys.executable).parent / "kbs.json"
else:
    # Running in normal Python
    _KBS_PATH = Path(__file__).parent / "kbs.json"


def load_kbs() -> dict:
    if not _KBS_PATH.exists():
        return {}
    return json.loads(_KBS_PATH.read_text())


def get_kb(kb_id: str) -> dict | None:
    return load_kbs().get(kb_id)
