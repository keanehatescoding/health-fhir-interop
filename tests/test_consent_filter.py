"""Unit tests for query_api.healthlake_query.apply_consent_filter -- the
application-layer gate that withholds a source's clinical resources when a
patient denied sharing from it. This is the one piece of logic in the demo
that has real privacy consequences if it regresses (e.g. a refactor that
starts matching on organization display name instead of meta.source and
silently stops filtering)."""
from query_api.healthlake_query import apply_consent_filter


def consent(source, consent_type, org):
    return {
        "resourceType": "Consent",
        "meta": {"source": source},
        "organization": [{"display": org}],
        "provision": {"type": consent_type},
    }


def observation(source):
    return {"resourceType": "Observation", "meta": {"source": source}, "subject": {"reference": "Patient/p1"}}


def patient():
    return {"resourceType": "Patient", "id": "p1"}


def bundle(*resources):
    return {"resourceType": "Bundle", "type": "searchset", "total": len(resources),
            "entry": [{"resource": r} for r in resources]}


def test_withholds_resources_from_denied_source_only():
    permitted_obs = observation("urn:source:nhif")
    denied_obs = observation("urn:source:facility_b")
    b = bundle(
        patient(),
        consent("urn:source:nhif", "permit", "NHIF"),
        consent("urn:source:facility_b", "deny", "Facility B"),
        permitted_obs,
        denied_obs,
    )

    filtered, withheld = apply_consent_filter(b)

    kept_resource_types_and_sources = {
        (e["resource"]["resourceType"], e["resource"].get("meta", {}).get("source"))
        for e in filtered["entry"]
    }
    assert ("Observation", "urn:source:facility_b") not in kept_resource_types_and_sources
    assert ("Observation", "urn:source:nhif") in kept_resource_types_and_sources


def test_consent_resources_themselves_are_never_withheld():
    b = bundle(patient(), consent("urn:source:facility_b", "deny", "Facility B"))
    filtered, _ = apply_consent_filter(b)
    kept_types = {e["resource"]["resourceType"] for e in filtered["entry"]}
    assert "Consent" in kept_types


def test_patient_resource_is_never_withheld():
    b = bundle(patient(), consent("urn:source:nhif", "deny", "NHIF"))
    filtered, _ = apply_consent_filter(b)
    kept_types = {e["resource"]["resourceType"] for e in filtered["entry"]}
    assert "Patient" in kept_types


def test_withheld_summary_reports_organization_and_count():
    b = bundle(
        patient(),
        consent("urn:source:facility_b", "deny", "Facility B - AKUH-style private hospital"),
        observation("urn:source:facility_b"),
        observation("urn:source:facility_b"),
    )
    _, withheld = apply_consent_filter(b)
    assert withheld == [{
        "source": "urn:source:facility_b",
        "organization": "Facility B - AKUH-style private hospital",
        "count": 2,
    }]


def test_no_denials_withholds_nothing():
    b = bundle(patient(), consent("urn:source:nhif", "permit", "NHIF"), observation("urn:source:nhif"))
    filtered, withheld = apply_consent_filter(b)
    assert withheld == []
    assert len(filtered["entry"]) == len(b["entry"])
