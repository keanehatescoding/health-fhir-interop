"""Deletes the HealthLake data store -- run this immediately after the demo,
since the store bills per active hour.

Run: python infra/delete_healthlake_store.py
"""
from common.aws_client import get_client
from infra.state import load

def main():
    state = load()
    if "datastore_id" not in state:
        print("No datastore_id in infra/.state.json -- nothing to delete.")
        return

    healthlake = get_client("healthlake", target="real")
    healthlake.delete_fhir_datastore(DatastoreId=state["datastore_id"])
    print(f"Delete requested for data store {state['datastore_id']}. "
          "It will move to DELETING then disappear; billing stops once deleted.")


if __name__ == "__main__":
    main()
