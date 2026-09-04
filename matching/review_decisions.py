"""Persists human review decisions on flagged "possible match" pairs (the
0.5-0.75 fuzzy-score band from matching/match_patients.py), so an
approve/reject action survives a pipeline rebuild.

Decisions are keyed by the PRE-decision person_ids -- the ids match_patients
assigns each cluster purely from raw source data, before any decision is
applied, which stay stable across reruns as long as the raw data doesn't
change (see PERSON_ID_NAMESPACE in match_patients.py).

Run standalone for nothing -- this is a library used by match_patients.py
(to apply decisions) and demo_ui/server.py (to record a new one and trigger
a rebuild).
"""
import json
import pathlib

DECISIONS_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "review_decisions.json"


def load():
    if not DECISIONS_PATH.exists():
        return []
    return json.loads(DECISIONS_PATH.read_text()).get("decisions", [])


def save_decision(person_id_a: str, person_id_b: str, decision: str):
    if decision not in ("approve", "reject"):
        raise ValueError(f"decision must be 'approve' or 'reject', got {decision!r}")
    pair = frozenset((person_id_a, person_id_b))
    decisions = [d for d in load() if frozenset((d["person_id_a"], d["person_id_b"])) != pair]
    decisions.append({"person_id_a": person_id_a, "person_id_b": person_id_b, "decision": decision})
    DECISIONS_PATH.write_text(json.dumps({"decisions": decisions}, indent=2))


def as_map():
    """Returns {frozenset({person_id_a, person_id_b}): "approve"|"reject"}."""
    return {frozenset((d["person_id_a"], d["person_id_b"])): d["decision"] for d in load()}
