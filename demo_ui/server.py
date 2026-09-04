"""Minimal Flask backend for the demo UI.

Serves:
  GET  /api/patients             -> list of resolved people (for the picker)
  GET  /api/patients/<id>/before -> raw siloed records for that person, as they
                                     exist in each original source (mismatched
                                     ID schemes, on purpose), plus any pending
                                     or already-reviewed "possible match" links
  GET  /api/patients/<id>/after  -> the unified timeline from the query layer
                                     (query_api.healthlake_query), mock or real
                                     depending on HEALTHLAKE_MODE
  POST /api/review-decisions     -> approve (merge) or reject (keep separate)
                                     a flagged pair; rebuilds the whole
                                     matching+FHIR pipeline in-process so the
                                     decision is reflected immediately
  GET  /                         -> the static demo page

Run: python -m demo_ui.server
"""
import csv
import json
import pathlib

from flask import Flask, jsonify, request, send_from_directory

from matching.rebuild import rebuild
from matching.review_decisions import save_decision
from query_api.healthlake_query import apply_consent_filter, get_patient_everything

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"

app = Flask(__name__, static_folder=None)


def load_clusters():
    return json.loads((DATA_DIR / "patient_clusters.json").read_text())


def load_raw_by_key():
    raw = {}
    with (RAW_DIR / "nhif_claims.csv").open() as f:
        for row in csv.DictReader(f):
            key = ("nhif", row["nhif_member_no"])
            entry = raw.setdefault(key, {
                "source": "NHIF (national insurer)",
                "identity": {k: row[k] for k in ("nhif_member_no", "national_id", "full_name", "dob", "phone")},
                "consent": row["consent_to_share"],
                "events": [],
            })
            entry["events"].append({
                "date": row["service_date"], "label": row["procedure_desc"],
                "detail": f"Claim {row['claim_id']} · KES {row['amount_kes']} · {row['claim_status']}",
            })

    facb = json.loads((RAW_DIR / "facility_b_akuh.json").read_text())
    for p in facb:
        d = p["demographics"]
        raw[("facility_b", p["mrn"])] = {
            "source": "Facility B - AKUH-style private hospital",
            "identity": {"mrn": p["mrn"], "national_id": d.get("nationalIdNumber"),
                         "name": d["name"], "dob": d["dateOfBirth"], "phone": d["contactPhone"]},
            "consent": d["consentToShare"],
            "events": [
                {"date": v["visitDate"], "label": v["diagnosis"]["text"], "detail": v["notes"]}
                for v in p["visits"]
            ],
        }

    with (RAW_DIR / "facility_c_clinic.txt").open() as f:
        for row in csv.DictReader(f, delimiter="|"):
            raw[("facility_c", row["patient_code"])] = {
                "source": "Facility C - independent clinic (no national ID captured)",
                "identity": {"patient_code": row["patient_code"], "name": row["full_name"],
                             "dob": row["dob"], "phone": row["phone"]},
                "consent": row["consent"],
                "events": [{"date": row["visit_date"], "label": row["diagnosis_text"], "detail": ""}],
            }
    return raw


@app.get("/api/patients")
def list_patients():
    clusters = load_clusters()
    review_ids = set()
    for link in clusters.get("possible_links", []):
        review_ids.add(link["person_id_a"])
        review_ids.add(link["person_id_b"])

    people = []
    for c in clusters["clusters"]:
        people.append({
            "person_id": c["person_id"],
            "display_name": c["members"][0]["name"],
            "sources": sorted({m["source"] for m in c["members"]}),
            "flagged_for_review": c["person_id"] in review_ids,
        })
    people.sort(key=lambda p: (-len(p["sources"]), p["display_name"]))
    return jsonify(people)


@app.get("/api/patients/<person_id>/before")
def patient_before(person_id):
    clusters = load_clusters()
    raw_by_key = load_raw_by_key()
    cluster = next((c for c in clusters["clusters"] if c["person_id"] == person_id), None)
    if not cluster:
        return jsonify({"error": "not found"}), 404

    records = [raw_by_key[(m["source"], m["key"])] for m in cluster["members"]]

    def links_for(pool):
        return [
            {"person_id_a": l["person_id_a"], "person_id_b": l["person_id_b"],
             "other_person_id": (l["person_id_b"] if l["person_id_a"] == person_id else l["person_id_a"]),
             "score": l["score"]}
            for l in clusters.get(pool, [])
            if person_id in (l["person_id_a"], l["person_id_b"])
        ]

    return jsonify({
        "records": records,
        "possible_links": links_for("possible_links"),
        "reviewed_links": links_for("reviewed_links"),
    })


@app.post("/api/review-decisions")
def review_decision():
    data = request.get_json(force=True)
    person_id_a, person_id_b, decision = data["person_id_a"], data["person_id_b"], data["decision"]

    # figure out where person_id_a's records end up after the merge, so the
    # frontend can reselect the right (possibly new, merged) person_id
    clusters_before = load_clusters()
    cluster_a = next((c for c in clusters_before["clusters"] if c["person_id"] == person_id_a), None)
    member_keys = {(m["source"], m["key"]) for m in (cluster_a["members"] if cluster_a else [])}

    save_decision(person_id_a, person_id_b, decision)
    rebuild()

    new_person_id = person_id_a
    if decision == "approve":
        clusters_after = load_clusters()
        for c in clusters_after["clusters"]:
            if any((m["source"], m["key"]) in member_keys for m in c["members"]):
                new_person_id = c["person_id"]
                break

    return jsonify({"decision": decision, "person_id": new_person_id})


@app.get("/api/patients/<person_id>/after")
def patient_after(person_id):
    bundle = get_patient_everything(person_id)
    filtered_bundle, withheld = apply_consent_filter(bundle)
    return jsonify({"bundle": filtered_bundle, "withheld": withheld})


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
