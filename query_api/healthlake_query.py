"""Query layer for the "after" view: given a canonical Patient.id, return
that person's unified timeline.

HEALTHLAKE_MODE=mock (default): serves the exact same FHIR resources built by
matching/build_fhir_bundles.py, read straight from data/fhir_ready/*.ndjson,
with no AWS calls at all. This is the safe fallback for a demo and lets the
UI be built/tested before a real data store exists.

HEALTHLAKE_MODE=real: issues SigV4-signed HTTPS calls to the real HealthLake
data store's FHIR REST endpoint (from infra/.state.json, written by
infra/create_healthlake_store.py). REQUIRES REAL AWS -- never available on floci.
"""
import json
import os
import pathlib

import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from dotenv import load_dotenv

from infra.state import load as load_state

load_dotenv(".env")
load_dotenv(".env.real", override=True)

FHIR_READY_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "fhir_ready"
_RESOURCE_TYPES = ["Patient", "Encounter", "Condition", "Observation", "MedicationRequest", "Claim", "Consent",
                   "FamilyMemberHistory", "RiskAssessment"]


def _mode():
    return os.environ.get("HEALTHLAKE_MODE", "mock")


def _bundle(resources):
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(resources),
        "entry": [{"resource": r} for r in resources],
    }


def _load_ndjson(resource_type):
    path = FHIR_READY_DIR / f"{resource_type}.ndjson"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _references_patient(resource, patient_id):
    ref = (resource.get("subject") or resource.get("patient") or {}).get("reference")
    return ref == f"Patient/{patient_id}"


def _mock_everything(patient_id):
    resources = [p for p in _load_ndjson("Patient") if p["id"] == patient_id]
    for rt in _RESOURCE_TYPES[1:]:
        resources += [r for r in _load_ndjson(rt) if _references_patient(r, patient_id)]
    return _bundle(resources)


def _mock_find_by_identifier(system, value):
    matches = [
        p for p in _load_ndjson("Patient")
        if any(i.get("system") == system and i.get("value") == value for i in p.get("identifier", []))
    ]
    return _bundle(matches)


def _signed_get(url, params=None):
    session = boto3.Session()
    credentials = session.get_credentials()
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    request = AWSRequest(method="GET", url=url, params=params or {})
    SigV4Auth(credentials, "healthlake", region).add_auth(request)
    resp = requests.get(url, headers=dict(request.headers), params=params or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _real_endpoint():
    state = load_state()
    if "datastore_endpoint" not in state:
        raise RuntimeError(
            "No datastore_endpoint in infra/.state.json -- run "
            "infra/create_healthlake_store.py first, or set HEALTHLAKE_MODE=mock."
        )
    return state["datastore_endpoint"].rstrip("/")


def get_patient_everything(patient_id: str) -> dict:
    """Returns a FHIR Bundle: the Patient plus every resource referencing it."""
    if _mode() == "mock":
        return _mock_everything(patient_id)
    return _signed_get(f"{_real_endpoint()}/Patient/{patient_id}/$everything")


def find_patient_by_identifier(system: str, value: str) -> dict:
    """Look up the canonical Patient by ANY source identifier (NHIF number,
    MRN, national ID, ...) -- demonstrates that all of them resolve to the
    same record."""
    if _mode() == "mock":
        return _mock_find_by_identifier(system, value)
    return _signed_get(f"{_real_endpoint()}/Patient", params={"identifier": f"{system}|{value}"})


def apply_consent_filter(bundle: dict) -> dict:
    """Enforces per-source consent on a $everything bundle: any non-Patient,
    non-Consent resource whose meta.source matches a source with a "deny"
    Consent is removed. Returns (filtered_bundle, withheld_summary) where
    withheld_summary is a list of {"source", "organization", "count"} for
    what got excluded -- so the UI can say WHY data is missing instead of
    silently showing less.

    This is deliberately NOT done inside get_patient_everything(): the FHIR
    store (real or mocked) holds everything HealthLake actually has; consent
    enforcement is an application-layer concern in front of it, same as a
    real interoperability platform's API gateway would do.
    """
    entries = bundle.get("entry", [])
    resources = [e["resource"] for e in entries]

    denied_sources = {}
    for r in resources:
        if r["resourceType"] == "Consent" and r.get("provision", {}).get("type") == "deny":
            source = (r.get("meta") or {}).get("source", "")
            org = (r.get("organization") or [{}])[0].get("display", source)
            denied_sources[source] = org

    kept, withheld_counts = [], {}
    for r in resources:
        source = (r.get("meta") or {}).get("source", "")
        if r["resourceType"] not in ("Patient", "Consent") and source in denied_sources:
            withheld_counts[source] = withheld_counts.get(source, 0) + 1
            continue
        kept.append(r)

    withheld = [
        {"source": source, "organization": denied_sources[source], "count": count}
        for source, count in withheld_counts.items()
    ]
    return _bundle(kept), withheld


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python -m query_api.healthlake_query <patient_id>")
        raise SystemExit(1)
    print(json.dumps(get_patient_everything(sys.argv[1]), indent=2))
