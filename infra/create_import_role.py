"""Creates the IAM role AWS HealthLake assumes to read the FHIR NDJSON from
S3 and write import-job results back to S3.

REQUIRES REAL AWS -- IAM CRUD works on floci but can't validate the actual
trust HealthLake checks, so this always targets real AWS.

Run: python infra/create_import_role.py
"""
import json
import os
import time

from common.aws_client import get_client
from infra.state import save

ROLE_NAME = "health-fhir-demo-healthlake-import-role"
POLICY_NAME = "health-fhir-demo-healthlake-import-policy"

TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "healthlake.amazonaws.com"},
        "Action": "sts:AssumeRole",
    }],
}


def build_access_policy(bucket):
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:ListBucket"],
                "Resource": f"arn:aws:s3:::{bucket}",
            },
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject"],
                "Resource": f"arn:aws:s3:::{bucket}/*",
            },
        ],
    }


def main():
    iam = get_client("iam", target="real")
    bucket = os.environ.get("S3_BUCKET", "health-fhir-demo-real")

    try:
        resp = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(TRUST_POLICY),
            Description="Lets AWS HealthLake read/write the demo S3 bucket for FHIR import jobs",
        )
        role_arn = resp["Role"]["Arn"]
        print(f"Created role {role_arn}")
    except iam.exceptions.EntityAlreadyExistsException:
        role_arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
        print(f"Role already exists: {role_arn}")

    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName=POLICY_NAME,
        PolicyDocument=json.dumps(build_access_policy(bucket)),
    )
    print(f"Attached inline policy scoped to bucket {bucket}")

    # IAM role creation has an eventual-consistency lag before other services
    # can reliably assume it -- HealthLake import jobs commonly fail on the
    # very next call otherwise.
    print("Waiting 10s for IAM role propagation...")
    time.sleep(10)

    save(role_arn=role_arn, bucket=bucket)
    print(f"Saved role_arn to infra/.state.json")


if __name__ == "__main__":
    main()
