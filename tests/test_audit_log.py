"""Unit tests for audit/audit_log.py -- the FHIR AuditEvent trail logged on
every unified-record view and review decision. The property that matters for
a health-data audit trail is that every event is attributable and that a
patient's trail can be reliably retrieved later; these tests pin both."""
import pytest

from audit import audit_log


@pytest.fixture(autouse=True)
def isolated_audit_log(tmp_path, monkeypatch):
    path = tmp_path / "audit_log.ndjson"
    monkeypatch.setattr(audit_log, "AUDIT_LOG_PATH", path)
    return path


def test_record_view_logs_read_action_with_actor():
    event = audit_log.record_view("p1", "Data Steward (MPI review)", withheld=[])
    assert event["action"] == "R"
    assert event["subtype"][0]["code"] == "read"
    assert event["agent"][0]["who"]["display"] == "Data Steward (MPI review)"
    assert event["entity"][0]["what"]["reference"] == "Patient/p1"


def test_record_view_description_mentions_withheld_sources():
    withheld = [{"source": "urn:source:facility_b", "organization": "Facility B", "count": 3}]
    event = audit_log.record_view("p1", "NHIF Claims Officer", withheld)
    assert "3 from Facility B withheld" in event["entity"][0]["description"]


def test_record_view_description_omits_withheld_note_when_nothing_withheld():
    event = audit_log.record_view("p1", "NHIF Claims Officer", [])
    assert "withheld" not in event["entity"][0]["description"]


def test_record_review_decision_logs_update_action_for_both_patients():
    event = audit_log.record_review_decision(["p1", "p2"], "Data Steward (MPI review)", "approve")
    assert event["action"] == "U"
    assert event["subtype"][0]["code"] == "update"
    refs = {e["what"]["reference"] for e in event["entity"]}
    assert refs == {"Patient/p1", "Patient/p2"}
    assert "Approved merge" in event["entity"][0]["description"]


def test_record_review_decision_reject_wording():
    event = audit_log.record_review_decision(["p1", "p2"], "Data Steward (MPI review)", "reject")
    assert "Rejected" in event["entity"][0]["description"]


def test_get_trail_returns_empty_list_when_no_log_file_exists():
    assert audit_log.get_trail("p1") == []


def test_get_trail_filters_to_requested_patient_only():
    audit_log.record_view("p1", "Data Steward (MPI review)", [])
    audit_log.record_view("p2", "Data Steward (MPI review)", [])
    trail = audit_log.get_trail("p1")
    assert len(trail) == 1
    assert trail[0]["entity"][0]["what"]["reference"] == "Patient/p1"


def test_get_trail_sorted_most_recent_first():
    audit_log.record_view("p1", "Data Steward (MPI review)", [])
    audit_log.record_review_decision(["p1"], "Data Steward (MPI review)", "approve")
    trail = audit_log.get_trail("p1")
    assert len(trail) == 2
    assert trail[0]["recorded"] >= trail[1]["recorded"]
