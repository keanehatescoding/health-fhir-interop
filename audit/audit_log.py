"""Append-only audit trail of who accessed or modified a patient's unified
record, as FHIR AuditEvent resources -- the standard FHIR mechanism for
"who looked at this and when", which is table stakes for any real health
interoperability platform (NHIF/HIE access almost always requires this for
compliance).

Generated LIVE by demo_ui/server.py on every unified-record view and every
review-queue decision -- unlike data/fhir_ready/*.ndjson, which is a static
content bundle rebuilt by the batch pipeline. Kept deliberately separate
from that bundle: the audit log is operational data about *access*, not
clinical content. In a real deployment this would be HealthLake's own
AuditEvent resources (or a dedicated audit store), not something reimported
as patient content on every pipeline rebuild -- so it is NOT written under
data/fhir_ready/ and is not picked up by matching/validate_bundles.py.

There's no real auth in this demo, so "who" is whatever actor the UI's
"Viewing as" selector sends in the X-Demo-Actor header -- good enough to
demonstrate that access is attributable and auditable, not a real identity
provider integration.
"""
import json
import pathlib
import uuid
from datetime import datetime, timezone

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
AUDIT_LOG_PATH = DATA_DIR / "audit_log.ndjson"

RESTFUL_INTERACTION = "http://hl7.org/fhir/restful-interaction"


def _build_event(action, interaction, actor, patient_ids, description):
    return {
        "resourceType": "AuditEvent",
        "id": str(uuid.uuid4()),
        "type": {"system": "http://terminology.hl7.org/CodeSystem/audit-event-type",
                 "code": "rest", "display": "RESTful Operation"},
        "subtype": [{"system": RESTFUL_INTERACTION, "code": interaction}],
        "action": action,
        "recorded": datetime.now(timezone.utc).isoformat(),
        "outcome": "0",
        "agent": [{"who": {"display": actor}, "requestor": True}],
        "source": {"observer": {"display": "Portable Medical History Demo Server"}},
        "entity": [
            {
                "what": {"reference": f"Patient/{pid}"},
                "type": {"system": "http://terminology.hl7.org/CodeSystem/audit-entity-type",
                         "code": "1", "display": "Person"},
                "description": description,
            }
            for pid in patient_ids
        ],
    }


def record_view(patient_id, actor, withheld):
    description = "Viewed unified record"
    if withheld:
        gaps = "; ".join(f"{w['count']} from {w['organization']} withheld (no consent)" for w in withheld)
        description += f" — {gaps}"
    event = _build_event("R", "read", actor, [patient_id], description)
    _append(event)
    return event


def record_review_decision(patient_ids, actor, decision):
    label = "Approved merge" if decision == "approve" else "Rejected (kept separate)"
    event = _build_event("U", "update", actor, patient_ids, f"{label} — possible-match review decision")
    _append(event)
    return event


def _append(event):
    with AUDIT_LOG_PATH.open("a") as f:
        f.write(json.dumps(event) + "\n")


def get_trail(patient_id):
    if not AUDIT_LOG_PATH.exists():
        return []
    events = []
    for line in AUDIT_LOG_PATH.read_text().splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if any(e["what"]["reference"] == f"Patient/{patient_id}" for e in event.get("entity", [])):
            events.append(event)
    events.sort(key=lambda e: e["recorded"], reverse=True)
    return events
