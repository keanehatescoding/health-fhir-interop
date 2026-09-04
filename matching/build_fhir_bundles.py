"""Turns patient_clusters.json + the 3 raw sources into valid FHIR R4 NDJSON,
ready for AWS HealthLake's StartFHIRImportJob.

Uses fhir.resources.R4B (this library's stand-in for FHIR R4 -- R4B is a
near-identical follow-on release; AWS HealthLake's DatastoreTypeVersion="R4"
accepts it) so every resource is pydantic-validated before it ever touches AWS.

One canonical Patient resource per matched person, with an identifier[] entry
per source ID (distinct `system` URI per source) -- this is what lets the
same real person be looked up by NHIF number, MRN, or national ID and get
back one record. All clinical resources reference that canonical Patient.id
via `subject`, regardless of which source they came from.

The "possible_links" band from matching (score 0.5-0.75, not auto-merged)
becomes a Patient.link entry of type "seealso" on both sides -- FHIR's own
mechanism for "probably the same person, needs human review".

Every clinical resource is tagged Resource.meta.source = "urn:source:<source>"
(the standard FHIR field for provenance), and one Consent resource is built
per (person, source) recording whether that source may be shared into the
unified record. Identity matching still links a "deny" source's records to
the right canonical Patient (the platform must still know it's the same
person) -- consent only gates what the query layer surfaces, applied in
query_api/healthlake_query.py, not what gets ingested. This mirrors how real
interoperability platforms work: the FHIR store holds everything; access
control is enforced at the application layer in front of it.

data/raw/family_history.json (relatives' conditions, captured at NHIF intake)
becomes one FamilyMemberHistory resource per relative/condition, plus one
derived RiskAssessment per person summarizing which conditions their family
history puts them at elevated risk for -- FHIR's own resources for exactly
this "does this patient's family history suggest a condition they should be
screened for" question. RISK_RULES is a small keyword-matched lookup table,
not a validated clinical risk model -- good enough for a hackathon demo, not
for real risk stratification.

Run: python matching/build_fhir_bundles.py
Reads:  data/patient_clusters.json, data/raw/*
Writes: data/fhir_ready/Patient.ndjson, Encounter.ndjson, Condition.ndjson,
        Observation.ndjson, Claim.ndjson, Consent.ndjson,
        FamilyMemberHistory.ndjson, RiskAssessment.ndjson
"""
import csv
import json
import pathlib
import uuid

from fhir.resources.R4B.claim import Claim
from fhir.resources.R4B.condition import Condition
from fhir.resources.R4B.consent import Consent
from fhir.resources.R4B.encounter import Encounter
from fhir.resources.R4B.familymemberhistory import FamilyMemberHistory
from fhir.resources.R4B.observation import Observation
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.riskassessment import RiskAssessment

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
OUT_DIR = DATA_DIR / "fhir_ready"

IDENTIFIER_SYSTEMS = {
    "nhif": "http://nhif.go.ke/member-id",
    "facility_b": "http://akuh.example.org/mrn",
    "facility_c": "http://clinic-x.example.org/patient-code",
    "national_id": "http://nationalregistration.go.ke/id",
}

SOURCE_ORG_DISPLAY = {
    "nhif": "NHIF (national insurer)",
    "facility_b": "Facility B - AKUH-style private hospital",
    "facility_c": "Facility C - independent clinic",
}

RESOURCE_NAMESPACE = uuid.UUID("6f9c3e2a-0000-4000-8000-000000000002")

# Keyword (matched case-insensitively against a family member's condition
# text) -> the condition a descendant may be at elevated risk for, plus a
# screening suggestion. Deliberately simple: a hackathon-scale stand-in for
# real hereditary risk scoring, not a clinical model.
RISK_RULES = [
    {"match": "diabetes", "outcome_code": "E11.9", "outcome_text": "Type 2 diabetes mellitus",
     "qualitative_risk": "high", "screening": "annual fasting glucose / HbA1c screening"},
    {"match": "hypertension", "outcome_code": "I10", "outcome_text": "Essential hypertension",
     "qualitative_risk": "moderate", "screening": "routine blood pressure monitoring"},
    {"match": "breast cancer", "outcome_code": "C50.9", "outcome_text": "Breast cancer",
     "qualitative_risk": "moderate", "screening": "earlier/more frequent mammogram screening"},
    {"match": "coronary artery disease", "outcome_code": "I25.1", "outcome_text": "Coronary artery disease",
     "qualitative_risk": "moderate", "screening": "lipid profile and cardiac risk screening"},
]


def match_risk_rule(condition_text):
    lowered = (condition_text or "").lower()
    return next((rule for rule in RISK_RULES if rule["match"] in lowered), None)


def source_meta(source):
    return {"source": f"urn:source:{source}"}


def resource_id(*parts):
    return str(uuid.uuid5(RESOURCE_NAMESPACE, "|".join(parts)))


def load_raw():
    nhif_rows = list(csv.DictReader((RAW_DIR / "nhif_claims.csv").open()))
    facb = json.loads((RAW_DIR / "facility_b_akuh.json").read_text())
    facc_rows = list(csv.DictReader((RAW_DIR / "facility_c_clinic.txt").open(), delimiter="|"))
    return nhif_rows, facb, facc_rows


def load_family_history():
    path = RAW_DIR / "family_history.json"
    return json.loads(path.read_text()) if path.exists() else []


def build_patient(person_id, member_records, national_id, linked_person_ids=None):
    identifiers = []
    seen_ids = set()
    if national_id:
        identifiers.append({"system": IDENTIFIER_SYSTEMS["national_id"], "value": national_id})
    for m in member_records:
        ident = (IDENTIFIER_SYSTEMS[m["source"]], m["key"])
        if ident not in seen_ids:
            identifiers.append({"system": ident[0], "value": ident[1]})
            seen_ids.add(ident)

    best = member_records[0]
    name_str = best["name"]
    parts = name_str.replace(".", "").split()
    given, family = (parts[:-1], parts[-1]) if len(parts) > 1 else ([], name_str)

    # "possible match, needs review" pairs from matching (score 0.5-0.75) are
    # NOT merged into one Patient; instead each side points at the other via
    # FHIR's own mechanism for "probably the same person" -- Patient.link
    # type=seealso -- so a human reviewer can resolve it later.
    link = [
        {"other": {"reference": f"Patient/{other_id}"}, "type": "seealso"}
        for other_id in (linked_person_ids or [])
    ]

    return Patient(
        id=person_id,
        identifier=identifiers,
        name=[{"text": name_str, "given": given, "family": family}],
        birthDate=_iso_date(best["dob"]),
        link=link or None,
    )


def _iso_date(value):
    if not value:
        return None
    if "/" in value:
        d, m, y = value.split("/")
        return f"{y}-{m}-{d}"
    return value


def build_encounter(person_id, source, source_key, visit_date, res_id):
    return Encounter(
        id=res_id,
        meta=source_meta(source),
        status="finished",
        class_fhir={"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
        subject={"reference": f"Patient/{person_id}"},
        period={"start": _iso_date(visit_date)} if visit_date else None,
    )


def build_condition(person_id, source, encounter_id, code, text, res_id, visit_date):
    return Condition(
        id=res_id,
        meta=source_meta(source),
        subject={"reference": f"Patient/{person_id}"},
        encounter={"reference": f"Encounter/{encounter_id}"},
        code={"coding": [{"code": code}] if code else [], "text": text},
        recordedDate=_iso_date(visit_date),
    )


def build_claim(person_id, source, claim_id, service_date, amount, status, res_id):
    return Claim(
        id=res_id,
        meta=source_meta(source),
        status="active",
        type={"coding": [{"code": "institutional"}]},
        use="claim",
        patient={"reference": f"Patient/{person_id}"},
        created=_iso_date(service_date),
        provider={"display": "NHIF"},
        priority={"coding": [{"code": "normal"}]},
        total={"value": float(amount), "currency": "KES"},
        insurance=[{"sequence": 1, "focal": True, "coverage": {"display": "NHIF"}}],
    )


def build_consent(person_id, source, consent_value, date, res_id):
    return Consent(
        id=res_id,
        meta=source_meta(source),
        status="active" if consent_value == "permit" else "rejected",
        scope={"coding": [{"system": "http://terminology.hl7.org/CodeSystem/consentscope",
                            "code": "patient-privacy"}]},
        category=[{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/consentcategorycodes",
                                "code": "INFA", "display": "Information Access"}]}],
        patient={"reference": f"Patient/{person_id}"},
        dateTime=_iso_date(date),
        organization=[{"display": SOURCE_ORG_DISPLAY[source]}],
        provision={"type": consent_value},
    )


def build_family_member_history(person_id, source, relationship, relationship_code,
                                 condition_code, condition_text, onset_age, deceased, res_id):
    return FamilyMemberHistory(
        id=res_id,
        meta=source_meta(source),
        status="completed",
        patient={"reference": f"Patient/{person_id}"},
        relationship={
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
                        "code": relationship_code, "display": relationship}],
            "text": relationship.capitalize(),
        },
        deceasedBoolean=deceased,
        condition=[{
            "code": {"coding": [{"code": condition_code}] if condition_code else [], "text": condition_text},
            "onsetAge": {"value": onset_age, "unit": "years",
                         "system": "http://unitsofmeasure.org", "code": "a"},
        }],
    )


def build_risk_assessment(person_id, source, entries, fmh_ids, res_id):
    predictions, seen_outcomes = [], set()
    for entry in entries:
        rule = match_risk_rule(entry["condition_text"])
        if not rule or rule["outcome_text"] in seen_outcomes:
            continue
        seen_outcomes.add(rule["outcome_text"])
        predictions.append({
            "outcome": {"coding": [{"code": rule["outcome_code"]}], "text": rule["outcome_text"]},
            "qualitativeRisk": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/risk-probability",
                "code": rule["qualitative_risk"],
            }]},
            "rationale": (
                f"{entry['relationship'].capitalize()} diagnosed with {entry['condition_text']} "
                f"at age {entry['onset_age']} — first-degree relative history increases risk. "
                f"Suggested: {rule['screening']}."
            ),
        })
    if not predictions:
        return None
    return RiskAssessment(
        id=res_id,
        meta=source_meta(source),
        status="final",
        subject={"reference": f"Patient/{person_id}"},
        basis=[{"reference": f"FamilyMemberHistory/{fid}"} for fid in fmh_ids],
        prediction=predictions,
        note=[{"text": "Derived from family history; not a clinical diagnosis. For screening guidance only."}],
    )


def main():
    clusters = json.loads((DATA_DIR / "patient_clusters.json").read_text())
    nhif_rows, facb, facc_rows = load_raw()
    family_history_rows = load_family_history()

    key_to_person = {}
    key_to_national_id = {}
    for c in clusters["clusters"]:
        for m in c["members"]:
            key_to_person[(m["source"], m["key"])] = c["person_id"]
            if m["national_id"]:
                key_to_national_id[c["person_id"]] = m["national_id"]

    review_links = {}
    for link in clusters.get("possible_links", []):
        review_links.setdefault(link["person_id_a"], set()).add(link["person_id_b"])
        review_links.setdefault(link["person_id_b"], set()).add(link["person_id_a"])

    patients, encounters, conditions, observations, claims, consents = [], [], [], [], [], []
    # dedupe consent to one Consent resource per (person, source), keyed by
    # the first record seen for that relationship
    consent_seen = {}

    def note_consent(source, key, person_id, consent_value, date):
        dedup_key = (person_id, source)
        if dedup_key not in consent_seen:
            consent_seen[dedup_key] = True
            consents.append(build_consent(
                person_id, source, consent_value, date, resource_id("consent", source, key),
            ))

    for c in clusters["clusters"]:
        national_id = key_to_national_id.get(c["person_id"])
        linked = review_links.get(c["person_id"])
        patients.append(build_patient(c["person_id"], c["members"], national_id, linked))

    for row in nhif_rows:
        person_id = key_to_person[("nhif", row["nhif_member_no"])]
        enc_id = resource_id("encounter", "nhif", row["claim_id"])
        encounters.append(build_encounter(person_id, "nhif", row["nhif_member_no"], row["service_date"], enc_id))
        conditions.append(build_condition(
            person_id, "nhif", enc_id, row["diagnosis_code"], row["procedure_desc"],
            resource_id("condition", "nhif", row["claim_id"]), row["service_date"],
        ))
        claims.append(build_claim(
            person_id, "nhif", row["claim_id"], row["service_date"], row["amount_kes"], row["claim_status"],
            resource_id("claim", "nhif", row["claim_id"]),
        ))
        note_consent("nhif", row["nhif_member_no"], person_id, row["consent_to_share"], row["service_date"])

    for p in facb:
        person_id = key_to_person[("facility_b", p["mrn"])]
        note_consent("facility_b", p["mrn"], person_id, p["demographics"]["consentToShare"],
                      p["visits"][0]["visitDate"] if p["visits"] else None)
        for i, visit in enumerate(p["visits"]):
            enc_id = resource_id("encounter", "facility_b", p["mrn"], str(i))
            encounters.append(build_encounter(person_id, "facility_b", p["mrn"], visit["visitDate"], enc_id))
            conditions.append(build_condition(
                person_id, "facility_b", enc_id, visit["diagnosis"]["code"], visit["diagnosis"]["text"],
                resource_id("condition", "facility_b", p["mrn"], str(i)), visit["visitDate"],
            ))
            observations.append(Observation(
                id=resource_id("observation", "facility_b", p["mrn"], str(i)),
                meta=source_meta("facility_b"),
                status="final",
                code={"text": "Clinical note"},
                subject={"reference": f"Patient/{person_id}"},
                encounter={"reference": f"Encounter/{enc_id}"},
                effectiveDateTime=_iso_date(visit["visitDate"]),
                valueString=visit["notes"],
            ))

    for row in facc_rows:
        person_id = key_to_person[("facility_c", row["patient_code"])]
        enc_id = resource_id("encounter", "facility_c", row["patient_code"])
        encounters.append(build_encounter(person_id, "facility_c", row["patient_code"], row["visit_date"], enc_id))
        conditions.append(build_condition(
            person_id, "facility_c", enc_id, None, row["diagnosis_text"],
            resource_id("condition", "facility_c", row["patient_code"]), row["visit_date"],
        ))
        note_consent("facility_c", row["patient_code"], person_id, row["consent"], row["visit_date"])

    family_histories, risk_assessments = [], []
    fh_entries_by_person = {}
    for i, row in enumerate(family_history_rows):
        person_id = key_to_person.get((row["source"], row["key"]))
        if not person_id:
            continue
        fmh_id = resource_id("familymemberhistory", row["source"], row["key"], str(i))
        family_histories.append(build_family_member_history(
            person_id, row["source"], row["relationship"], row["relationship_code"],
            row["condition_code"], row["condition_text"], row["onset_age"], row["deceased"], fmh_id,
        ))
        fh_entries_by_person.setdefault(person_id, []).append({**row, "_fmh_id": fmh_id})

    for person_id, entries in fh_entries_by_person.items():
        risk = build_risk_assessment(
            person_id, entries[0]["source"], entries, [e["_fmh_id"] for e in entries],
            resource_id("riskassessment", person_id),
        )
        if risk:
            risk_assessments.append(risk)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_ndjson("Patient", patients)
    _write_ndjson("Encounter", encounters)
    _write_ndjson("Condition", conditions)
    _write_ndjson("Observation", observations)
    _write_ndjson("Claim", claims)
    _write_ndjson("Consent", consents)
    _write_ndjson("FamilyMemberHistory", family_histories)
    _write_ndjson("RiskAssessment", risk_assessments)

    print(f"Patients: {len(patients)}, Encounters: {len(encounters)}, "
          f"Conditions: {len(conditions)}, Observations: {len(observations)}, Claims: {len(claims)}, "
          f"Consents: {len(consents)}, FamilyMemberHistory: {len(family_histories)}, "
          f"RiskAssessments: {len(risk_assessments)}")
    print(f"Wrote NDJSON bundles to {OUT_DIR}")


def _write_ndjson(resource_type, resources):
    path = OUT_DIR / f"{resource_type}.ndjson"
    with path.open("w") as f:
        for r in resources:
            f.write(r.model_dump_json(exclude_none=True) + "\n")


if __name__ == "__main__":
    main()
