"""Identity resolution: links records across NHIF / Facility B / Facility C
into canonical person clusters.

Stage 1 (deterministic): matching normalized national_id -> same person, confidence 1.0.
Stage 2 (probabilistic, for sources lacking a national id): weighted score on
    phone (0.4) + dob (0.3) + fuzzy name (0.3).
        score >= 0.75         -> auto-link (fuzzy match)
        0.5 <= score < 0.75   -> NOT merged; recorded as a "possible_link" for
                                  human review (mirrors FHIR Patient.link type=seealso)
        score < 0.5           -> distinct people

Stage 3 (human review): any recorded decision in data/review_decisions.json
(written by demo_ui/server.py's approve/reject action) is applied on top of
the above -- "approve" merges the two clusters into one (same as an
auto-link), "reject" removes the pair from possible_links into
reviewed_links (informational only, no longer flagged, no Patient.link).

Run: python matching/match_patients.py
Reads:  data/raw/nhif_claims.csv, data/raw/facility_b_akuh.json, data/raw/facility_c_clinic.txt,
        data/review_decisions.json
Writes: data/patient_clusters.json
"""
import csv
import json
import pathlib
import uuid
from itertools import combinations

from rapidfuzz import fuzz

from matching.normalize import normalize_dob, normalize_name, normalize_national_id, normalize_phone
from matching.review_decisions import as_map as load_decisions_map

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"

FUZZY_AUTO_LINK_THRESHOLD = 0.75
FUZZY_REVIEW_THRESHOLD = 0.5
PERSON_ID_NAMESPACE = uuid.UUID("6f9c3e2a-0000-4000-8000-000000000001")


class IdentityRecord:
    def __init__(self, source, key, name, dob, phone, national_id):
        self.source = source
        self.key = key  # the source's own identifier (member no / mrn / patient code)
        self.name = name
        self.dob = dob
        self.phone = phone
        self.national_id = national_id
        self.norm_name = normalize_name(name)
        self.norm_dob = normalize_dob(dob)
        self.norm_phone = normalize_phone(phone)
        self.norm_national_id = normalize_national_id(national_id)

    def __repr__(self):
        return f"<{self.source}:{self.key} {self.name!r}>"


def load_nhif():
    records = {}
    with (RAW_DIR / "nhif_claims.csv").open() as f:
        for row in csv.DictReader(f):
            records.setdefault(row["nhif_member_no"], row)
    return [
        IdentityRecord("nhif", key, row["full_name"], row["dob"], row["phone"], row["national_id"])
        for key, row in records.items()
    ]


def load_facility_b():
    patients = json.loads((RAW_DIR / "facility_b_akuh.json").read_text())
    return [
        IdentityRecord(
            "facility_b", p["mrn"], p["demographics"]["name"], p["demographics"]["dateOfBirth"],
            p["demographics"]["contactPhone"], p["demographics"].get("nationalIdNumber"),
        )
        for p in patients
    ]


def load_facility_c():
    with (RAW_DIR / "facility_c_clinic.txt").open() as f:
        reader = csv.DictReader(f, delimiter="|")
        seen = {}
        for row in reader:
            seen.setdefault(row["patient_code"], row)
    return [
        IdentityRecord("facility_c", key, row["full_name"], row["dob"], row["phone"], None)
        for key, row in seen.items()
    ]


def pair_score(a: IdentityRecord, b: IdentityRecord):
    """Returns (method, score) for a cross-source pair."""
    if a.norm_national_id and b.norm_national_id and a.norm_national_id == b.norm_national_id:
        return "deterministic", 1.0

    phone_score = 1.0 if a.norm_phone and b.norm_phone and a.norm_phone == b.norm_phone else 0.0
    dob_score = 1.0 if a.norm_dob and b.norm_dob and a.norm_dob == b.norm_dob else 0.0
    name_score = fuzz.token_sort_ratio(a.norm_name, b.norm_name) / 100.0

    score = 0.4 * phone_score + 0.3 * dob_score + 0.3 * name_score
    return "fuzzy", round(score, 3)


class UnionFind:
    def __init__(self, items):
        self.parent = {item: item for item in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def match():
    all_records = load_nhif() + load_facility_b() + load_facility_c()
    uf = UnionFind([r for r in all_records])

    possible_links = []  # (record_a, record_b, score) for the review band

    for a, b in combinations(all_records, 2):
        if a.source == b.source:
            continue  # matching is a cross-source problem here
        method, score = pair_score(a, b)
        if score >= FUZZY_AUTO_LINK_THRESHOLD:
            uf.union(a, b)
        elif score >= FUZZY_REVIEW_THRESHOLD:
            possible_links.append((a, b, method, score))

    clusters_by_root = {}
    for r in all_records:
        clusters_by_root.setdefault(uf.find(r), []).append(r)

    clusters = []
    record_to_person_id = {}
    for root, members in clusters_by_root.items():
        seed = ",".join(sorted(f"{m.source}:{m.key}" for m in members))
        person_id = str(uuid.uuid5(PERSON_ID_NAMESPACE, seed))
        for m in members:
            record_to_person_id[(m.source, m.key)] = person_id
        clusters.append({
            "person_id": person_id,
            "members": [
                {
                    "source": m.source, "key": m.key, "name": m.name,
                    "dob": m.dob, "phone": m.phone, "national_id": m.national_id,
                }
                for m in members
            ],
        })

    possible_link_out = [
        {
            "person_id_a": record_to_person_id[(a.source, a.key)],
            "person_id_b": record_to_person_id[(b.source, b.key)],
            "record_a": f"{a.source}:{a.key}", "record_b": f"{b.source}:{b.key}",
            "method": method, "score": score,
        }
        for a, b, method, score in possible_links
        # skip pairs that already ended up in the same cluster via another path
        if record_to_person_id[(a.source, a.key)] != record_to_person_id[(b.source, b.key)]
    ]

    clusters, possible_link_out, reviewed_link_out = apply_review_decisions(
        clusters, possible_link_out, load_decisions_map(),
    )

    return {"clusters": clusters, "possible_links": possible_link_out, "reviewed_links": reviewed_link_out}


def apply_review_decisions(clusters, possible_links, decisions_map):
    """Applies human approve/reject decisions on top of the automatic match.
    "approve" merges the two clusters (same effect as an auto fuzzy-link);
    "reject" moves the pair out of possible_links into reviewed_links
    (informational: reviewed, confirmed distinct, no longer flagged)."""
    clusters_by_id = {c["person_id"]: c for c in clusters}
    id_remap = {}

    def resolve(pid):
        while pid in id_remap:
            pid = id_remap[pid]
        return pid

    remaining, reviewed = [], []
    for link in possible_links:
        decision = decisions_map.get(frozenset((link["person_id_a"], link["person_id_b"])))
        a, b = resolve(link["person_id_a"]), resolve(link["person_id_b"])
        if decision == "approve" and a in clusters_by_id and b in clusters_by_id and a != b:
            cluster_a, cluster_b = clusters_by_id.pop(a), clusters_by_id.pop(b)
            merged_members = cluster_a["members"] + cluster_b["members"]
            seed = ",".join(sorted(f"{m['source']}:{m['key']}" for m in merged_members))
            new_id = str(uuid.uuid5(PERSON_ID_NAMESPACE, seed))
            clusters_by_id[new_id] = {"person_id": new_id, "members": merged_members}
            id_remap[a] = new_id
            id_remap[b] = new_id
        elif decision == "reject":
            reviewed.append({**link, "review_decision": "reject"})
        else:
            remaining.append(link)

    return list(clusters_by_id.values()), remaining, reviewed


def main():
    result = match()
    out_path = DATA_DIR / "patient_clusters.json"
    out_path.write_text(json.dumps(result, indent=2))

    multi = [c for c in result["clusters"] if len(c["members"]) > 1]
    single = [c for c in result["clusters"] if len(c["members"]) == 1]
    print(f"Wrote {out_path}")
    print(f"{len(result['clusters'])} distinct people: {len(multi)} multi-source, {len(single)} single-source")
    for c in multi:
        sources = ", ".join(f"{m['source']}:{m['key']}" for m in c["members"])
        print(f"  MERGED  {c['person_id'][:8]}...  <- {sources}")
    for link in result["possible_links"]:
        print(f"  REVIEW  {link['record_a']} <-> {link['record_b']}  score={link['score']} (NOT merged)")
    for link in result.get("reviewed_links", []):
        print(f"  REJECTED (by review)  {link['record_a']} <-> {link['record_b']}  kept separate")


if __name__ == "__main__":
    main()
