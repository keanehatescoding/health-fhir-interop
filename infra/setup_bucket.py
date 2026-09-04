"""Creates the S3 bucket and uploads the FHIR-ready NDJSON bundles.

Run against floci first for the fast, free iteration loop while the
matching/bundle-building logic is still being tightened, then re-run
identically with --target real once it's settled (HealthLake can only
import from a bucket the real AWS account can see).

Usage:
    python infra/setup_bucket.py --target floci
    python infra/setup_bucket.py --target real
"""
import argparse
import os
import pathlib

from common.aws_client import get_client

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "fhir_ready"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["floci", "real"], required=True)
    parser.add_argument("--prefix", default="fhir-ready")
    args = parser.parse_args()

    s3 = get_client("s3", target=args.target)
    bucket = os.environ.get("S3_BUCKET", "health-fhir-demo")

    existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
    if bucket not in existing:
        region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        if region == "us-east-1":
            s3.create_bucket(Bucket=bucket)
        else:
            s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": region})
        print(f"Created bucket {bucket} ({args.target})")
    else:
        print(f"Bucket {bucket} already exists ({args.target})")

    for path in sorted(DATA_DIR.glob("*.ndjson")):
        key = f"{args.prefix}/{path.name}"
        s3.upload_file(str(path), bucket, key)
        print(f"Uploaded s3://{bucket}/{key}")


if __name__ == "__main__":
    main()
