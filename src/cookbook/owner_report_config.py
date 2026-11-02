"""Explicit separate reports-only authority for owner observations."""

from .owner_reports import OwnerReports
from .storage_config import separate_store


def owner_reports_from_environment(make_store):
    store = separate_store(
        make_store,
        prefix="OWNER_REPORTS",
        label="owner reports",
        exclusions=(
            ("S3_BUCKET", "AWS_ACCESS_KEY_ID"),
            ("READER_S3_BUCKET", "READER_AWS_ACCESS_KEY_ID"),
            ("REPORTS_S3_BUCKET", "REPORTS_AWS_ACCESS_KEY_ID"),
        ),
    )
    return OwnerReports(store) if store is not None else None
