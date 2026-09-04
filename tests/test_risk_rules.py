"""Unit tests for the RISK_RULES lookup table and derivation logic in
matching/build_fhir_bundles.py -- the hereditary-risk feature. A bug here
(e.g. a rule's keyword no longer matching the raw condition text, or
duplicate predictions for the same outcome) would silently drop or duplicate
risk flags without validate_bundles.py noticing, since the output is still
valid FHIR either way."""
from matching.build_fhir_bundles import RISK_RULES, build_risk_assessment, match_risk_rule


def test_match_risk_rule_matches_known_conditions_case_insensitively():
    assert match_risk_rule("Type 2 Diabetes")["outcome_text"] == "Type 2 diabetes mellitus"
    assert match_risk_rule("hypertension")["outcome_text"] == "Essential hypertension"
    assert match_risk_rule("Breast Cancer, stage II")["outcome_text"] == "Breast cancer"
    assert match_risk_rule("coronary artery disease")["outcome_text"] == "Coronary artery disease"


def test_match_risk_rule_no_match_for_unrelated_condition():
    assert match_risk_rule("seasonal flu") is None


def test_match_risk_rule_handles_none_and_empty():
    assert match_risk_rule(None) is None
    assert match_risk_rule("") is None


def test_every_risk_rule_has_required_fields():
    for rule in RISK_RULES:
        assert rule["match"]
        assert rule["outcome_code"]
        assert rule["outcome_text"]
        assert rule["qualitative_risk"] in ("low", "moderate", "high")
        assert rule["screening"]


def entry(relationship, condition_text, onset_age):
    return {"relationship": relationship, "condition_text": condition_text, "onset_age": onset_age}


def test_build_risk_assessment_produces_one_prediction_per_matched_condition():
    entries = [entry("father", "type 2 diabetes", 45), entry("mother", "hypertension", 50)]
    ra = build_risk_assessment("p1", "nhif", entries, ["fmh1", "fmh2"], "ra1")
    outcomes = {p.outcome.text for p in ra.prediction}
    assert outcomes == {"Type 2 diabetes mellitus", "Essential hypertension"}


def test_build_risk_assessment_deduplicates_same_outcome_from_multiple_relatives():
    entries = [entry("father", "type 2 diabetes", 45), entry("brother", "diabetes mellitus type 2", 30)]
    ra = build_risk_assessment("p1", "nhif", entries, ["fmh1", "fmh2"], "ra1")
    assert len(ra.prediction) == 1


def test_build_risk_assessment_skips_unmatched_conditions():
    entries = [entry("father", "seasonal flu", 45)]
    assert build_risk_assessment("p1", "nhif", entries, ["fmh1"], "ra1") is None


def test_build_risk_assessment_returns_none_when_no_entries():
    assert build_risk_assessment("p1", "nhif", [], [], "ra1") is None


def test_build_risk_assessment_rationale_names_relative_and_screening():
    entries = [entry("father", "type 2 diabetes", 45)]
    ra = build_risk_assessment("p1", "nhif", entries, ["fmh1"], "ra1")
    rationale = ra.prediction[0].rationale
    assert "Father" in rationale
    assert "age 45" in rationale
    assert "HbA1c" in rationale
