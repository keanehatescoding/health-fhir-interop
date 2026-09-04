"""Unit tests for matching/match_patients.py's scoring and clustering logic --
the code that decides whether two records from different sources are the same
person, need human review, or are distinct. This is the part of the pipeline
the CI drift-check (.github/workflows/validate-bundles.yml) can't protect:
drift-check only proves a code change produces the SAME output as before, not
that the scoring is CORRECT. These tests pin the actual matching behavior."""
from matching.match_patients import (
    FUZZY_AUTO_LINK_THRESHOLD,
    FUZZY_REVIEW_THRESHOLD,
    IdentityRecord,
    UnionFind,
    apply_review_decisions,
    pair_score,
)


def rec(source, key, name, dob, phone, national_id=None):
    return IdentityRecord(source, key, name, dob, phone, national_id)


def test_pair_score_same_national_id_is_deterministic_full_match():
    a = rec("nhif", "N1", "Grace Wanjiru Njeri", "1990-05-14", "0722100001", "23456789")
    b = rec("facility_b", "F1", "Grace W. Njeri", "1990-05-14", "+254722100002", "234-56-789")
    method, score = pair_score(a, b)
    assert method == "deterministic"
    assert score == 1.0


def test_pair_score_matching_phone_dob_name_is_auto_link():
    a = rec("nhif", "N1", "Grace Wanjiru Njeri", "1990-05-14", "0722100001")
    b = rec("facility_c", "C1", "Grace Wanjiru", "14/05/1990", "+254722100001")
    method, score = pair_score(a, b)
    assert method == "fuzzy"
    assert score >= FUZZY_AUTO_LINK_THRESHOLD


def test_pair_score_only_name_similarity_falls_below_review_band():
    a = rec("nhif", "N1", "Grace Wanjiru Njeri", "1990-05-14", "0722100001")
    b = rec("facility_c", "C1", "Grace Wanjiru Njeri", "1985-01-01", "0733999999")
    method, score = pair_score(a, b)
    assert method == "fuzzy"
    # name matches exactly (0.3) but phone and dob both differ -> 0.3, below the 0.5 review floor
    assert score < FUZZY_REVIEW_THRESHOLD


def test_pair_score_completely_different_people_scores_below_review_band():
    a = rec("nhif", "N1", "Grace Wanjiru Njeri", "1990-05-14", "0722100001")
    b = rec("facility_c", "C2", "James Otieno", "1975-03-02", "0700000000")
    _, score = pair_score(a, b)
    # negligible incidental name-character overlap, not a real match signal
    assert score < FUZZY_REVIEW_THRESHOLD


def test_union_find_merges_transitively():
    uf = UnionFind(["a", "b", "c", "d"])
    uf.union("a", "b")
    uf.union("b", "c")
    assert uf.find("a") == uf.find("c")
    assert uf.find("a") != uf.find("d")


def make_cluster(person_id, *members):
    return {"person_id": person_id, "members": [{"source": s, "key": k} for s, k in members]}


def test_apply_review_decisions_approve_merges_clusters():
    clusters = [make_cluster("p1", ("nhif", "N1")), make_cluster("p2", ("facility_c", "C1"))]
    links = [{"person_id_a": "p1", "person_id_b": "p2", "record_a": "nhif:N1",
              "record_b": "facility_c:C1", "method": "fuzzy", "score": 0.6}]
    decisions = {frozenset(("p1", "p2")): "approve"}

    new_clusters, remaining, reviewed = apply_review_decisions(clusters, links, decisions)

    assert remaining == []
    assert reviewed == []
    assert len(new_clusters) == 1
    merged_keys = {(m["source"], m["key"]) for m in new_clusters[0]["members"]}
    assert merged_keys == {("nhif", "N1"), ("facility_c", "C1")}


def test_apply_review_decisions_reject_moves_link_to_reviewed_not_remaining():
    clusters = [make_cluster("p1", ("nhif", "N1")), make_cluster("p2", ("facility_c", "C1"))]
    links = [{"person_id_a": "p1", "person_id_b": "p2", "record_a": "nhif:N1",
              "record_b": "facility_c:C1", "method": "fuzzy", "score": 0.6}]
    decisions = {frozenset(("p1", "p2")): "reject"}

    new_clusters, remaining, reviewed = apply_review_decisions(clusters, links, decisions)

    assert remaining == []
    assert len(reviewed) == 1
    assert reviewed[0]["review_decision"] == "reject"
    assert {c["person_id"] for c in new_clusters} == {"p1", "p2"}


def test_apply_review_decisions_no_decision_stays_pending():
    clusters = [make_cluster("p1", ("nhif", "N1")), make_cluster("p2", ("facility_c", "C1"))]
    links = [{"person_id_a": "p1", "person_id_b": "p2", "record_a": "nhif:N1",
              "record_b": "facility_c:C1", "method": "fuzzy", "score": 0.6}]

    new_clusters, remaining, reviewed = apply_review_decisions(clusters, links, {})

    assert remaining == links
    assert reviewed == []
    assert len(new_clusters) == 2
