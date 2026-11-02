"""Real provider error contracts at the conditional-write boundary; no network."""

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from cookbook.storage import Conflict, S3Store


@pytest.mark.parametrize(
    "code,expected,error_type",
    [
        ("ObjectLockedByBucketPolicy", None, Conflict),
        ("ObjectLockedByBucketPolicy", '"prior"', ClientError),
        ("AccessDenied", None, ClientError),
    ],
)
def test_locked_create_is_a_conflict_but_other_failures_remain_errors(
    code, expected, error_type
):
    client = boto3.client(
        "s3",
        endpoint_url="https://synthetic.invalid",
        region_name="auto",
        aws_access_key_id="synthetic",
        aws_secret_access_key="synthetic",
    )
    parameters = {
        "Bucket": "synthetic-reports",
        "Key": "owner-observations/receipts/synthetic.json",
        "Body": b"{}",
        **({"IfMatch": expected} if expected else {"IfNoneMatch": "*"}),
    }
    with Stubber(client) as stub:
        stub.add_client_error(
            "put_object",
            service_error_code=code,
            http_status_code=403 if code == "AccessDenied" else 409,
            expected_params=parameters,
        )
        with pytest.raises(error_type):
            S3Store(client, "synthetic-reports").put_bytes(
                parameters["Key"], b"{}", expected=expected
            )
        stub.assert_no_pending_responses()
