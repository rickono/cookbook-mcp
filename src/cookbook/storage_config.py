"""Fail-closed opt-in for separate metadata storage authorities."""

import os


def separate_store(make_store, *, prefix, label, exclusions):
    from .hosted import https_url

    if not any(name.startswith(prefix + "_") for name in os.environ):
        return None
    names = tuple(
        prefix + suffix
        for suffix in ("_S3_BUCKET", "_AWS_ACCESS_KEY_ID", "_AWS_SECRET_ACCESS_KEY")
    )
    if any(not os.environ.get(name) for name in names):
        raise ValueError(f"incomplete {label} storage configuration")
    for bucket, credential in exclusions:
        if os.environ[names[0]] == os.environ.get(bucket) or os.environ[
            names[1]
        ] == os.environ.get(credential):
            raise ValueError(f"{label} storage must be separate")
    endpoint = os.environ.get(prefix + "_S3_ENDPOINT_URL") or os.environ.get(
        "S3_ENDPOINT_URL", ""
    )
    return make_store(https_url(endpoint), *(os.environ[name] for name in names))
