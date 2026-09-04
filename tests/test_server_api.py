"""Integration tests for demo_ui/server.py's read-only API routes, run
against the actual committed data/ pipeline output -- the same output the
CI drift-check (.github/workflows/validate-bundles.yml) proves is
reproducible from data_gen/generate_synthetic_data.py onward. These tests
pin the aggregate numbers DEMO.md tells presenters to say out loud, so a
pipeline or aggregation regression fails loudly instead of surfacing as a
wrong number mid-pitch.

Deliberately does NOT exercise POST /api/review-decisions here: that route
rebuilds and overwrites data/patient_clusters.json and data/fhir_ready/*
in place, which would mutate committed repository files as a side effect of
running the test suite. matching/test coverage for the underlying decision
logic lives in test_match_patients.py and test_review_decisions.py instead.
"""
import pytest

from audit import audit_log
from demo_ui import server


@pytest.fixture(autouse=True)
def isolated_audit_log(tmp_path, monkeypatch):
    """/after and /audit write real AuditEvents; keep them out of the
    gitignored-but-shared data/audit_log.ndjson so test runs don't pollute it."""
    monkeypatch.setattr(audit_log, "AUDIT_LOG_PATH", tmp_path / "audit_log.ndjson")


@pytest.fixture
def client():
    server.app.testing = True
    return server.app.test_client()


def test_list_patients_returns_nine_synthetic_people(client):
    people = client.get("/api/patients").get_json()
    assert len(people) == 9
    assert all({"person_id", "display_name", "sources", "flagged_for_review"} <= p.keys() for p in people)


def test_list_patients_sorted_multi_source_first(client):
    people = client.get("/api/patients").get_json()
    source_counts = [len(p["sources"]) for p in people]
    assert source_counts == sorted(source_counts, reverse=True)


def test_before_view_returns_records_and_links_for_hero_patient(client):
    people = client.get("/api/patients").get_json()
    hero = next(p for p in people if p["display_name"] == "Grace Wanjiru Njeri")
    before = client.get(f"/api/patients/{hero['person_id']}/before").get_json()
    assert len(before["records"]) == 3
    assert {r["source"] for r in before["records"]} == {
        "NHIF (national insurer)",
        "Facility B - AKUH-style private hospital",
        "Facility C - independent clinic (no national ID captured)",
    }


def test_before_view_unknown_person_is_404(client):
    resp = client.get("/api/patients/does-not-exist/before")
    assert resp.status_code == 404


def test_after_view_unifies_identifiers_and_logs_audit_event(client):
    people = client.get("/api/patients").get_json()
    hero = next(p for p in people if p["display_name"] == "Grace Wanjiru Njeri")
    resp = client.get(
        f"/api/patients/{hero['person_id']}/after",
        headers={"X-Demo-Actor": "Data Steward (MPI review)"},
    )
    body = resp.get_json()
    patient_resource = next(e["resource"] for e in body["bundle"]["entry"] if e["resource"]["resourceType"] == "Patient")
    assert len(patient_resource["identifier"]) >= 3

    trail = client.get(f"/api/patients/{hero['person_id']}/audit").get_json()
    assert any(e["action"] == "R" and e["agent"][0]["who"]["display"] == "Data Steward (MPI review)" for e in trail)


def test_after_view_withholds_denied_source_for_susan(client):
    people = client.get("/api/patients").get_json()
    susan = next(p for p in people if p["display_name"] == "Susan Nyambura Kariuki")
    body = client.get(
        f"/api/patients/{susan['person_id']}/after",
        headers={"X-Demo-Actor": "Facility B Physician"},
    ).get_json()
    assert body["withheld"]
    assert body["withheld"][0]["organization"] == "Facility B - AKUH-style private hospital"


def test_dashboard_matches_known_synthetic_dataset_shape(client):
    d = client.get("/api/dashboard").get_json()
    assert d["total_people"] == 9
    assert d["multi_source_people"] == 5
    assert d["single_source_people"] == 4
    assert d["pending_review"] == 1
    assert d["risk_flagged_people"] == 3
    assert len(d["consent_denials"]) == 1
    assert d["consent_denials"][0]["display_name"] == "Susan Nyambura Kariuki"


def test_dashboard_risk_breakdown_covers_all_four_risk_rules(client):
    d = client.get("/api/dashboard").get_json()
    outcomes = {r["outcome"] for r in d["risk_breakdown"]}
    assert outcomes == {
        "Type 2 diabetes mellitus",
        "Essential hypertension",
        "Breast cancer",
        "Coronary artery disease",
    }
    assert sum(r["count"] for r in d["risk_breakdown"]) >= d["risk_flagged_people"]
