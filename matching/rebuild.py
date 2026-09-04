"""Programmatic equivalent of running match_patients.py then
build_fhir_bundles.py in sequence -- used by demo_ui/server.py's review
approve/reject endpoint so a decision is reflected immediately without
shelling out to the CLI scripts.
"""
from matching import build_fhir_bundles, match_patients


def rebuild():
    match_patients.main()
    build_fhir_bundles.main()
