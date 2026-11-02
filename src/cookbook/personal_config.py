"""Personal metadata authority; independent backups and no publication access."""

from .reader_personal import PersonalState
from .storage_config import separate_store


def personal_from_environment(make_store):
    store = separate_store(
        make_store,
        prefix="PERSONAL",
        label="personal metadata",
        exclusions=(
            ("S3_BUCKET", "AWS_ACCESS_KEY_ID"),
            ("READER_S3_BUCKET", "READER_AWS_ACCESS_KEY_ID"),
            ("REPORTS_S3_BUCKET", "REPORTS_AWS_ACCESS_KEY_ID"),
            ("OWNER_REPORTS_S3_BUCKET", "OWNER_REPORTS_AWS_ACCESS_KEY_ID"),
        ),
    )
    return PersonalState(store) if store is not None else None
