"""Unit tests for matching/review_decisions.py -- the persistence layer behind
the demo UI's approve/reject action. A bug here (e.g. failing to replace an
existing decision for the same pair) would let a data steward's correction
silently not take effect on the next pipeline rebuild."""
import json

import pytest

from matching import review_decisions


@pytest.fixture(autouse=True)
def isolated_decisions_path(tmp_path, monkeypatch):
    path = tmp_path / "review_decisions.json"
    monkeypatch.setattr(review_decisions, "DECISIONS_PATH", path)
    return path


def test_load_missing_file_returns_empty_list():
    assert review_decisions.load() == []


def test_save_decision_persists_and_reloads():
    review_decisions.save_decision("p1", "p2", "approve")
    assert review_decisions.load() == [{"person_id_a": "p1", "person_id_b": "p2", "decision": "approve"}]


def test_save_decision_rejects_invalid_decision():
    with pytest.raises(ValueError):
        review_decisions.save_decision("p1", "p2", "maybe")


def test_save_decision_overwrites_previous_decision_for_same_pair_either_order():
    review_decisions.save_decision("p1", "p2", "approve")
    review_decisions.save_decision("p2", "p1", "reject")
    decisions = review_decisions.load()
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "reject"


def test_as_map_keys_by_unordered_pair():
    review_decisions.save_decision("p1", "p2", "approve")
    m = review_decisions.as_map()
    assert m[frozenset(("p1", "p2"))] == "approve"
    assert m[frozenset(("p2", "p1"))] == "approve"


def test_save_decision_writes_valid_json(isolated_decisions_path):
    review_decisions.save_decision("p1", "p2", "reject")
    on_disk = json.loads(isolated_decisions_path.read_text())
    assert on_disk == {"decisions": [{"person_id_a": "p1", "person_id_b": "p2", "decision": "reject"}]}
