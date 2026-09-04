"""Kicks off a StartFHIRImportJob pulling the FHIR NDJSON from the real S3
bucket into the HealthLake data store, and polls it to completion.

REQUIRES REAL AWS. Run infra/setup_bucket.py --target real,
infra/create_healthlake_store.py, and infra/create_import_role.py first.

Run: python infra/run_import.py [--prefix fhir-ready]
"""
import argparse
import time

from common.aws_client import get_client
from infra.state import load

POLL_SECONDS = 15
MAX_WAIT_SECONDS = 20 * 60


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="fhir-ready")
    args = parser.parse_args()

    state = load()
    for key in ("datastore_id", "role_arn", "bucket"):
        if key not in state:
            raise RuntimeError(
                f"Missing '{key}' in infra/.state.json -- run create_healthlake_store.py "
                "and create_import_role.py first."
            )

    healthlake = get_client("healthlake", target="real")

    resp = healthlake.start_fhir_import_job(
        JobName="health-fhir-demo-import",
        InputDataConfig={"S3Uri": f"s3://{state['bucket']}/{args.prefix}/"},
        JobOutputDataConfig={"S3Configuration": {"S3Uri": f"s3://{state['bucket']}/import-output/"}},
        DatastoreId=state["datastore_id"],
        DataAccessRoleArn=state["role_arn"],
    )
    job_id = resp["JobId"]
    print(f"Started import job {job_id}, status={resp['JobStatus']}")

    waited = 0
    status = resp["JobStatus"]
    while status in ("SUBMITTED", "IN_PROGRESS", "QUEUED"):
        if waited >= MAX_WAIT_SECONDS:
            raise TimeoutError(f"Import job still {status} after {MAX_WAIT_SECONDS}s")
        time.sleep(POLL_SECONDS)
        waited += POLL_SECONDS
        job = healthlake.describe_fhir_import_job(
            DatastoreId=state["datastore_id"], JobId=job_id
        )["ImportJobProperties"]
        status = job["JobStatus"]
        print(f"  status={status}, waited {waited}s...")

    if status != "COMPLETED":
        print(f"Import job ended with status={status}. Check the output S3 "
              f"prefix (s3://{state['bucket']}/import-output/) for per-resource error details.")
        raise SystemExit(1)

    print(f"Import job COMPLETED: {job_id}")


if __name__ == "__main__":
    main()
