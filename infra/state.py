"""Tiny local state file so infra/*.py scripts chain together without the
user having to copy-paste ARNs/IDs between commands by hand."""
import json
import pathlib

STATE_PATH = pathlib.Path(__file__).resolve().parent / ".state.json"


def load():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save(**updates):
    state = load()
    state.update(updates)
    STATE_PATH.write_text(json.dumps(state, indent=2))
    return state
