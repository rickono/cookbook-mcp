"""Explicit separate reports-only authority for owner observations."""

import os

from .owner_reports import OwnerReports


def owner_reports_from_environment(make_store):
    names = (
        "OWNER_REPORTS_S3_BUCKET",
        "OWNER_REPORTS_AWS_ACCESS_KEY_ID",
        "OWNER_REPORTS_AWS_SECRET_ACCESS_KEY",
    )
    if not any(name.startswith("OWNER_REPORTS_") for name in os.environ):
        return None
    if any(not os.environ.get(name) for name in names):
        raise ValueError("incomplete owner reports storage configuration")
    for bucket, credential in (
        ("S3_BUCKET", "AWS_ACCESS_KEY_ID"),
        ("READER_S3_BUCKET", "READER_AWS_ACCESS_KEY_ID"),
        ("REPORTS_S3_BUCKET", "REPORTS_AWS_ACCESS_KEY_ID"),
    ):
        if os.environ[names[0]] == os.environ.get(bucket) or os.environ[
            names[1]
        ] == os.environ.get(credential):
            raise ValueError("owner reports storage must be separate")
    return OwnerReports(
        make_store(
            os.environ.get("OWNER_REPORTS_S3_ENDPOINT_URL")
            or os.environ["S3_ENDPOINT_URL"],
            *(os.environ[name] for name in names),
        )
    )
