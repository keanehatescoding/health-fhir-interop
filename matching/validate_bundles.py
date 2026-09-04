"""Re-parses every NDJSON file through fhir.resources.R4B before anything is
uploaded to AWS -- HealthLake import failures are slow to debug (minutes per
cycle), so catching malformed resources locally is cheap insurance.

Run: python matching/validate_bundles.py
"""
import json
import pathlib
import sys

from fhir.resources.R4B import get_fhir_model_class

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "fhir_ready"


def main():
    total = 0
    errors = []
    for path in sorted(DATA_DIR.glob("*.ndjson")):
        resource_type = path.stem
        model_cls = get_fhir_model_class(resource_type)
        with path.open() as f:
            for lineno, line in enumerate(f, start=1):
                total += 1
                try:
                    model_cls.model_validate(json.loads(line))
                except Exception as e:  # noqa: BLE001 - report and keep validating
                    errors.append(f"{path.name}:{lineno}: {e}")

    print(f"Validated {total} resources across {len(list(DATA_DIR.glob('*.ndjson')))} files")
    if errors:
        print(f"{len(errors)} INVALID resources:")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    print("All resources valid FHIR R4B.")


if __name__ == "__main__":
    main()
