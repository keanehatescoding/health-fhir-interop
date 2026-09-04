# Demo Runbook

## What this is

A hackathon prototype showing how AWS HealthLake can unify a patient's
fragmented medical history across NHIF (Kenya's national insurer) and
private facilities. Synthetic data only. See `/home/keane/.claude/plans/inherited-wobbling-moore.md`
for the full design.

## One-time setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # floci / mock-mode defaults, safe to commit-ignore
```

## Local pipeline (no AWS needed at all for this part)

```bash
python data_gen/generate_synthetic_data.py   # writes data/raw/*
python -m matching.match_patients            # identity resolution -> data/patient_clusters.json
python -m matching.build_fhir_bundles        # -> data/fhir_ready/*.ndjson
python -m matching.validate_bundles          # FHIR R4B validation before any upload
```

Expected: 9 distinct people, 5 merged multi-source clusters, 1 pair flagged
"needs review" (James Mutisya Kyalo, NHIF vs Facility C — same name/DOB,
different phone, correctly NOT auto-merged), and 15 `Consent` resources (one
per person/source relationship) — one of them, Susan Nyambura Kariuki's
Facility B consent, is deliberately `deny` to exercise the consent-gating
path: identity matching still links NHIF↔Facility B for her, but
`query_api.apply_consent_filter` withholds Facility B's clinical resources
from her unified view at query time.

## floci (local AWS emulator) — for iterating on the S3 upload step

```bash
floci start                                          # https://floci.io
python infra/setup_bucket.py --target floci
```

## Real AWS — required for HealthLake itself (floci does not emulate it)

Start this early; data store creation takes real wall-clock minutes and
bills while active.

```bash
cp .env.real.example .env.real     # fill in real AWS credentials
python infra/create_healthlake_store.py     # poll to ACTIVE
python infra/create_import_role.py          # IAM role HealthLake assumes
python infra/setup_bucket.py --target real
python infra/run_import.py                  # poll to COMPLETED

# when done demoing:
python infra/delete_healthlake_store.py     # stop billing
```

To point the demo at the real store instead of the local mock, set
`HEALTHLAKE_MODE=real` in `.env` (or `.env.real`).

## Demo UI

```bash
python -m demo_ui.server            # http://localhost:5000
```

Defaults to `HEALTHLAKE_MODE=mock`, which reads the exact same FHIR
resources built above straight from `data/fhir_ready/*.ndjson` — the whole
demo works with zero AWS cost/latency, and is the safe fallback if the live
AWS call ever misbehaves mid-pitch.

`?patient=<person_id>` deep-links directly to one patient's before/after
view (person IDs are listed by `GET /api/patients`) — handy for jumping
straight to a specific demo scenario without clicking through the picker.

## Live demo flow

1. Picker defaults to **Grace Wanjiru Njeri** (the "hero" patient, all 3 sources).
   - Left ("Before"): NHIF claim (`NHIF-10001`), Facility B/AKUH record
     (`MRN AKUH-2024-00931`), Facility C clinic record (`CLX-7001`) — point
     out none of the IDs match syntactically, and Facility C has no
     national ID at all.
   - Right ("After"): one unified timeline, one canonical `Patient`, with
     an identifier badge strip showing all 4 source IDs resolved to it.
2. Switch to **James Mutisya Kyalo** to show the flagged review case: two
   people with the same name and DOB, correctly kept as separate records
   linked via FHIR `Patient.link` (`type=seealso`) rather than blindly
   merged — the human-review path. Click **Reject (keep separate)** to show
   a data steward confirming they're distinct (banner turns green, stays
   informational, no more buttons) — or click **Approve merge** instead to
   show the opposite call: the two records merge into one canonical
   `Patient` with both sources, live, no pipeline restart needed (the
   decision is saved to `data/review_decisions.json` and the whole
   matching+FHIR pipeline rebuilds in-process). Either action is fully
   reversible by posting the opposite decision for the same pair.
3. Switch to **Susan Nyambura Kariuki** to show consent enforcement: her
   "Before" panel shows a red "sharing DENIED" badge on her Facility B card,
   and her "After" panel shows NHIF matched and merged as normal but a red
   withheld-notice explaining that 3 Facility B records are excluded because
   she never consented to that source being shared — directly answers "does
   this respect patient consent, or does it just merge everything?"
4. (Optional) Switch `HEALTHLAKE_MODE=real` and re-run the "After" call
   live against the real HealthLake data store, or open the AWS Console
   FHIR data browser, to prove it's a real managed store.

## Known limitations (say these out loud in the pitch)

- Synthetic data, 9 people — not a claim of production readiness.
- Matching uses fixed-weight heuristics (national ID exact match, else
  phone/DOB/name fuzzy score), not a validated MPI model.
- floci never touches HealthLake itself — only the S3/IAM pieces around it
  are locally emulated; the import and query steps always require real AWS.
