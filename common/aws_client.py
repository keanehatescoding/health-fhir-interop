"""Single place that decides whether a boto3 client talks to floci or real AWS.

Usage:
    from common.aws_client import get_client
    s3 = get_client("s3")                # honors .env / .env.real via env vars
    s3 = get_client("s3", target="floci") # force floci regardless of env
    s3 = get_client("healthlake", target="real")  # HealthLake is never on floci
"""
import os

import boto3
from dotenv import load_dotenv

_HEALTHLAKE_UNAVAILABLE_ON_FLOCI = {"healthlake"}

_loaded = False


def _ensure_env_loaded():
    global _loaded
    if _loaded:
        return
    # .env (floci defaults) loads first, then .env.real overrides for
    # anything doing real-AWS work in the same process.
    load_dotenv(".env")
    load_dotenv(".env.real", override=True)
    _loaded = True


def get_client(service_name: str, target: str | None = None):
    """Return a boto3 client for `service_name`.

    target: "floci" | "real" | None (None = infer from AWS_ENDPOINT_URL env var,
    which is set by .env for floci and absent for real AWS).
    """
    _ensure_env_loaded()

    if service_name in _HEALTHLAKE_UNAVAILABLE_ON_FLOCI and target == "floci":
        raise RuntimeError(
            f"'{service_name}' is not emulated by floci. "
            "Use target='real' (or unset AWS_ENDPOINT_URL) for this service."
        )

    endpoint_url = None
    if target == "floci":
        endpoint_url = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
    elif target == "real":
        endpoint_url = None
    else:
        endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
        if service_name in _HEALTHLAKE_UNAVAILABLE_ON_FLOCI:
            endpoint_url = None

    kwargs = dict(
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
        kwargs["aws_access_key_id"] = os.environ.get("AWS_ACCESS_KEY_ID", "test")
        kwargs["aws_secret_access_key"] = os.environ.get("AWS_SECRET_ACCESS_KEY", "test")

    return boto3.client(service_name, **kwargs)
