"""Creates the AWS HealthLake FHIR R4 data store.

REQUIRES REAL AWS -- HealthLake is not emulated by floci at all.

Kick this off as early as possible in a hackathon build: creation takes real
wall-clock minutes and the store bills per active hour, so start it before
touching Phases 1-3 (which are all local/floci and can run in parallel while
this provisions).

Run: python infra/create_healthlake_store.py
"""
import os
import time

from common.aws_client import get_client
from infra.state import save

POLL_SECONDS = 15
MAX_WAIT_SECONDS = 20 * 60


def main():
    healthlake = get_client("healthlake", target="real")
    name = os.environ.get("HEALTHLAKE_DATASTORE_NAME", "ke-health-demo")

    existing = healthlake.list_fhir_datastores(
        Filter={"DatastoreName": name}
    ).get("DatastorePropertiesList", [])
    if existing:
        props = existing[0]
        print(f"Data store '{name}' already exists: {props['DatastoreId']} ({props['DatastoreStatus']})")
    else:
        resp = healthlake.create_fhir_datastore(
            DatastoreName=name,
            DatastoreTypeVersion="R4",
        )
        print(f"Creating data store {resp['DatastoreId']} ...")
        props = healthlake.describe_fhir_datastore(DatastoreId=resp["DatastoreId"])["DatastoreProperties"]

    datastore_id = props["DatastoreId"]
    waited = 0
    while props["DatastoreStatus"] == "CREATING":
        if waited >= MAX_WAIT_SECONDS:
            raise TimeoutError(f"Data store still CREATING after {MAX_WAIT_SECONDS}s")
        print(f"  status=CREATING, waited {waited}s...")
        time.sleep(POLL_SECONDS)
        waited += POLL_SECONDS
        props = healthlake.describe_fhir_datastore(DatastoreId=datastore_id)["DatastoreProperties"]

    if props["DatastoreStatus"] != "ACTIVE":
        raise RuntimeError(f"Data store ended in unexpected status: {props['DatastoreStatus']}")

    endpoint = props["DatastoreEndpoint"]
    print(f"Data store ACTIVE: {datastore_id}")
    print(f"Endpoint: {endpoint}")
    save(datastore_id=datastore_id, datastore_endpoint=endpoint)


if __name__ == "__main__":
    main()
