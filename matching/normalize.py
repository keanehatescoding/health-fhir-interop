"""Normalization helpers so the same real-world value compares equal across
sources that format it differently (phone punctuation, DOB order, name case)."""
import re
from datetime import datetime

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y")


def normalize_national_id(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return digits or None


def normalize_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None
    # collapse to last 9 digits so "0722100001" and "+254722100001" match
    return digits[-9:]


def normalize_dob(value: str | None) -> str | None:
    if not value:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return value


def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[.,]", "", value).strip().lower()
    return re.sub(r"\s+", " ", cleaned)
