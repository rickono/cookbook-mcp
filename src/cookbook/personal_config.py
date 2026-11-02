"""Personal metadata authority; independent backups and no publication access."""

import os

from .reader_personal import PersonalState


def personal_from_environment(make_store):
    names = (
        "PERSONAL_S3_BUCKET",
        "PERSONAL_AWS_ACCESS_KEY_ID",
        "PERSONAL_AWS_SECRET_ACCESS_KEY",
    )
    if not any(name.startswith("PERSONAL_") for name in os.environ):
        return None
    if any(not os.environ.get(name) for name in names):
        raise ValueError("incomplete personal metadata storage configuration")
    for bucket, credential in (
        ("S3_BUCKET", "AWS_ACCESS_KEY_ID"),
        ("READER_S3_BUCKET", "READER_AWS_ACCESS_KEY_ID"),
        ("REPORTS_S3_BUCKET", "REPORTS_AWS_ACCESS_KEY_ID"),
        ("OWNER_REPORTS_S3_BUCKET", "OWNER_REPORTS_AWS_ACCESS_KEY_ID"),
    ):
        if os.environ[names[0]] == os.environ.get(bucket) or os.environ[
            names[1]
        ] == os.environ.get(credential):
            raise ValueError("personal metadata storage must be separate")
    return PersonalState(
        make_store(
            os.environ.get("PERSONAL_S3_ENDPOINT_URL") or os.environ["S3_ENDPOINT_URL"],
            *(os.environ[name] for name in names),
        )
    )
