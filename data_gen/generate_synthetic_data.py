"""Generates 3 synthetic, deliberately-fragmented health record sources.

Cast of 9 synthetic people, each engineered to exercise a specific part of
the identity-matching logic in matching/match_patients.py:

  P1 Grace Wanjiru Njeri   - NHIF + Facility B + Facility C (the "hero" patient:
                             NHIF<->FacB merge deterministically on national_id,
                             FacC joins via fuzzy phone+dob+name match)
  P2 John Otieno Omondi    - NHIF + Facility B, clean deterministic national_id match
  P3 Mary Achieng Odhiambo - NHIF + Facility C, fuzzy match only (FacC has no national id)
  P4 Peter Kamau Mwangi    - Facility B + Facility C only (no NHIF), fuzzy match
                             bridges two facilities directly
  P5 Susan Nyambura Kariuki- NHIF + Facility B, deterministic match despite name
                             spelling variance and DOB format difference.
                             ALSO the consent demo case: she permitted NHIF to
                             share, but explicitly DENIED Facility B -- matching
                             still links the two records (identity resolution is
                             independent of consent), but the unified view must
                             withhold the Facility B clinical data.
  P6 David Kiprotich Rono  - NHIF only (single source)
  P7 Alice Wambui Gitau    - Facility B only (single source)
  P8 James Mutisya Kyalo   - Facility C only (single source)
  P9 James Mutisya Kyalo   - NHIF only; SAME NAME as P8 and SAME dob, but a
                             different national_id/phone -- a genuinely
                             different person. Score lands in the "possible
                             match, needs review" band (name + dob match,
                             phone doesn't) so the matcher must NOT
                             auto-merge P8/P9 just because the names match.

Every source record carries a per-(person, source) consent flag
("permit"/"deny") for whether that source may be shared into the unified
interoperability record -- this is separate from identity matching: a
"deny" source still gets matched/linked (the platform must still know it's
the same person), but its clinical data is withheld at query time.

Run: python data_gen/generate_synthetic_data.py
Writes: data/raw/nhif_claims.csv
        data/raw/facility_b_akuh.json
        data/raw/facility_c_clinic.txt   (pipe-delimited, no national id column)
"""
import csv
import json
import pathlib

RAW_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw"


def nhif_rows():
    return [
        # P1
        dict(nhif_member_no="NHIF-10001", national_id="23456789",
             full_name="Grace Wanjiru Njeri", dob="1990-05-14", gender="F",
             phone="0722100001", claim_id="CLM-30001", facility_name="Nairobi West Hospital",
             service_date="2024-01-10", diagnosis_code="E11.9", procedure_desc="Diabetes review",
             amount_kes="4500", claim_status="PAID", consent_to_share="permit"),
        dict(nhif_member_no="NHIF-10001", national_id="23456789",
             full_name="Grace Wanjiru Njeri", dob="1990-05-14", gender="F",
             phone="0722100001", claim_id="CLM-30002", facility_name="Nairobi West Hospital",
             service_date="2024-06-02", diagnosis_code="J06.9", procedure_desc="Upper respiratory infection",
             amount_kes="1800", claim_status="PAID", consent_to_share="permit"),
        # P2
        dict(nhif_member_no="NHIF-10002", national_id="31122334",
             full_name="John Otieno Omondi", dob="1982-02-11", gender="M",
             phone="0733200002", claim_id="CLM-30003", facility_name="Kisumu County Hospital",
             service_date="2024-03-05", diagnosis_code="I10", procedure_desc="Hypertension checkup",
             amount_kes="2500", claim_status="PAID", consent_to_share="permit"),
        # P3
        dict(nhif_member_no="NHIF-10003", national_id="40556677",
             full_name="Mary Achieng Odhiambo", dob="1985-09-01", gender="F",
             phone="0733200003", claim_id="CLM-30004", facility_name="Nyanza Provincial Hospital",
             service_date="2024-02-14", diagnosis_code="O26.9", procedure_desc="Antenatal checkup",
             amount_kes="3000", claim_status="PAID", consent_to_share="permit"),
        # P5 - consented to NHIF sharing
        dict(nhif_member_no="NHIF-10005", national_id="60778899",
             full_name="Susan Nyambura Kariuki", dob="1988-03-22", gender="F",
             phone="0700500005", claim_id="CLM-30005", facility_name="Thika Level 5 Hospital",
             service_date="2024-04-18", diagnosis_code="N39.0", procedure_desc="UTI treatment",
             amount_kes="2200", claim_status="PAID", consent_to_share="permit"),
        # P6 - single source
        dict(nhif_member_no="NHIF-10006", national_id="70889900",
             full_name="David Kiprotich Rono", dob="1975-11-02", gender="M",
             phone="0722600006", claim_id="CLM-30006", facility_name="Eldoret Referral Hospital",
             service_date="2024-05-09", diagnosis_code="M54.5", procedure_desc="Lower back pain",
             amount_kes="1500", claim_status="PAID", consent_to_share="permit"),
        # P9 - same name/dob as FacC's P8, different national_id/phone -> review case
        dict(nhif_member_no="NHIF-10009", national_id="99001122",
             full_name="James Mutisya Kyalo", dob="1980-02-08", gender="M",
             phone="0755900009", claim_id="CLM-30007", facility_name="Machakos Level 5 Hospital",
             service_date="2024-07-01", diagnosis_code="J45.9", procedure_desc="Asthma review",
             amount_kes="2000", claim_status="PAID", consent_to_share="permit"),
    ]


def facility_b_patients():
    return [
        # P1
        {
            "mrn": "AKUH-2024-00931",
            "demographics": {"name": "Grace W. Njeri", "dateOfBirth": "1990-05-14",
                              "sex": "F", "nationalIdNumber": "23456789",
                              "contactPhone": "+254722100001", "consentToShare": "permit"},
            "visits": [
                {"visitDate": "2024-08-20", "chiefComplaint": "Follow-up on blood sugar control",
                 "diagnosis": {"code": "E11.9", "text": "Type 2 diabetes mellitus"},
                 "notes": "Patient reports improved adherence to metformin. HbA1c trending down."},
            ],
        },
        # P2
        {
            "mrn": "AKUH-2024-00877",
            "demographics": {"name": "John O. Omondi", "dateOfBirth": "1982-02-11",
                              "sex": "M", "nationalIdNumber": "31122334",
                              "contactPhone": "+254733200002", "consentToShare": "permit"},
            "visits": [
                {"visitDate": "2024-09-02", "chiefComplaint": "Chest tightness on exertion",
                 "diagnosis": {"code": "I10", "text": "Essential hypertension"},
                 "notes": "BP 148/94. Advised lifestyle changes, started amlodipine 5mg."},
            ],
        },
        # P4
        {
            "mrn": "AKUH-2024-01203",
            "demographics": {"name": "Peter Kamau Mwangi", "dateOfBirth": "1978-12-20",
                              "sex": "M", "nationalIdNumber": "55667788",
                              "contactPhone": "+254711300004", "consentToShare": "permit"},
            "visits": [
                {"visitDate": "2024-03-15", "chiefComplaint": "Persistent cough for 3 weeks",
                 "diagnosis": {"code": "A15.0", "text": "Pulmonary tuberculosis"},
                 "notes": "Sputum test positive. Started on TB treatment regimen."},
            ],
        },
        # P5 - explicitly DENIED sharing from Facility B (consent demo case)
        {
            "mrn": "AKUH-2024-01450",
            "demographics": {"name": "Susan N. Kariuki", "dateOfBirth": "22/03/1988",
                              "sex": "F", "nationalIdNumber": "60778899",
                              "contactPhone": "+254700500005", "consentToShare": "deny"},
            "visits": [
                {"visitDate": "2024-10-11", "chiefComplaint": "Recurrent UTI symptoms",
                 "diagnosis": {"code": "N39.0", "text": "Urinary tract infection"},
                 "notes": "Third episode this year. Referred for urology review."},
            ],
        },
        # P7 - single source
        {
            "mrn": "AKUH-2024-01888",
            "demographics": {"name": "Alice Wambui Gitau", "dateOfBirth": "1992-07-18",
                              "sex": "F", "nationalIdNumber": "81990011",
                              "contactPhone": "+254733700007", "consentToShare": "permit"},
            "visits": [
                {"visitDate": "2024-11-04", "chiefComplaint": "Annual wellness check",
                 "diagnosis": {"code": "Z00.0", "text": "General medical examination"},
                 "notes": "No abnormal findings. Routine bloodwork ordered."},
            ],
        },
    ]


def facility_c_rows():
    # pipe-delimited, NO national id column at all -- forces fuzzy matching
    return [
        # P1
        dict(patient_code="CLX-7001", full_name="Grace Wanjiru", dob="14/05/1990",
             phone="0722-100-001", visit_date="2025-01-08",
             diagnosis_text="Mild flu symptoms, prescribed rest and fluids", consent="permit"),
        # P3
        dict(patient_code="CLX-7003", full_name="Mary Achieng", dob="01/09/1985",
             phone="0733-200-003", visit_date="2025-01-15",
             diagnosis_text="Routine antenatal follow-up, all normal", consent="permit"),
        # P4
        dict(patient_code="CLX-7004", full_name="Peter K. Mwangi", dob="20/12/1978",
             phone="0711-300-004", visit_date="2025-02-02",
             diagnosis_text="TB medication refill, tolerating treatment well", consent="permit"),
        # P8 - single source, but shares name+dob with NHIF's P9 (different person)
        dict(patient_code="CLX-7008", full_name="James Mutisya Kyalo", dob="08/02/1980",
             phone="0744-800-008", visit_date="2025-02-20",
             diagnosis_text="Minor laceration on left hand, cleaned and dressed", consent="permit"),
    ]


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    nhif_path = RAW_DIR / "nhif_claims.csv"
    with nhif_path.open("w", newline="") as f:
        rows = nhif_rows()
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    facb_path = RAW_DIR / "facility_b_akuh.json"
    facb_path.write_text(json.dumps(facility_b_patients(), indent=2))

    facc_path = RAW_DIR / "facility_c_clinic.txt"
    rows = facility_c_rows()
    with facc_path.open("w") as f:
        f.write("|".join(rows[0].keys()) + "\n")
        for r in rows:
            f.write("|".join(str(v) for v in r.values()) + "\n")

    print(f"Wrote {nhif_path}")
    print(f"Wrote {facb_path}")
    print(f"Wrote {facc_path}")


if __name__ == "__main__":
    main()
