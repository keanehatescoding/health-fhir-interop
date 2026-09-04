"""Unit tests for matching/normalize.py -- the value-comparison layer every
identity-matching decision in match_patients.py depends on. A bug here (e.g.
phone normalization silently starting to compare full numbers instead of the
last 9 digits) would change which people get linked without anything else
in the pipeline complaining."""
from matching.normalize import normalize_dob, normalize_name, normalize_national_id, normalize_phone


def test_normalize_national_id_strips_non_digits():
    assert normalize_national_id("234-567-89") == "23456789"


def test_normalize_national_id_none_and_empty():
    assert normalize_national_id(None) is None
    assert normalize_national_id("") is None
    assert normalize_national_id("abc") is None


def test_normalize_phone_collapses_to_last_nine_digits():
    assert normalize_phone("0722100001") == "722100001"
    assert normalize_phone("+254722100001") == "722100001"


def test_normalize_phone_different_numbers_stay_different():
    assert normalize_phone("0722100001") != normalize_phone("0733100001")


def test_normalize_phone_none_and_empty():
    assert normalize_phone(None) is None
    assert normalize_phone("") is None


def test_normalize_dob_handles_both_source_formats():
    assert normalize_dob("1990-05-14") == "1990-05-14"
    assert normalize_dob("14/05/1990") == "1990-05-14"


def test_normalize_dob_unparseable_passed_through():
    assert normalize_dob("not-a-date") == "not-a-date"


def test_normalize_dob_none():
    assert normalize_dob(None) is None


def test_normalize_name_case_punctuation_whitespace_insensitive():
    assert normalize_name("Grace  Wanjiru Njeri") == "grace wanjiru njeri"
    assert normalize_name("Grace W. Njeri.") == "grace w njeri"


def test_normalize_name_none():
    assert normalize_name(None) == ""
