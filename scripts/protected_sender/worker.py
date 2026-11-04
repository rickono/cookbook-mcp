"""Dispatch boundary: live access cannot be enabled by CLI/config/environment."""

import json
from pathlib import Path

from guard import require_sender
from ledger import reserve
from protocol import credential, digest, load_packet, reject_ambient_overrides
from transport import require_fixture_endpoint, transaction


def dispatch_synthetic(directory, seal, ledger, endpoint, *, seconds=240):
    """Exercise admission and transport together; only loopback is permitted.

    No settlement is inferred from a successful HTTP reply. Synthetic billing
    reconciliation is explicit, just as real usage reconciliation must be.
    """
    _, remaining = require_sender()
    reject_ambient_overrides()
    require_fixture_endpoint(endpoint)
    packet, _, scopes = load_packet(directory, seal)
    credential(Path(directory) / "secret")
    for name in ("response.json", "receipt.json"):
        path = Path(directory) / name
        if path.exists() or path.is_symlink():
            raise ValueError("Retained output requires a fresh dispatch directory")
    deadline = min(seconds, 240, remaining - 30)
    if deadline <= 0:
        raise ValueError("Insufficient watchdog margin for transaction and cleanup")
    semantic = {
        k: v
        for k, v in packet.items()
        if k not in {"request_id", "maximum_cost", "input_tokens", "output_tokens"}
    }
    identity = digest(
        json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
    )
    reserve(ledger, packet["request_id"], identity, packet["maximum_cost"], scopes)
    _, remaining = require_sender()
    deadline = min(deadline, remaining - 30)
    if deadline <= 0:
        raise ValueError(
            "Watchdog margin exhausted during admission; liability retained"
        )
    response = transaction(
        directory,
        endpoint,
        request_digest=packet["request_sha256"],
        seconds=deadline,
        synthetic=True,
    )
    with Path(directory, "receipt.json").open("x") as receipt:
        receipt.write(
            json.dumps(
                {
                    "request_id": packet["request_id"],
                    "seal": seal,
                    "response_sha256": digest(response),
                    "outcome": "received_unreviewed",
                    "charge": "uncertain",
                    "synthetic": True,
                }
            )
        )
    return response


def main():
    require_sender()
    raise PermissionError(
        "Live dispatch disabled: account/data controls, verified adapters, reconciled "
        "ledger, frozen roster and concrete workload authorization are outstanding"
    )


if __name__ == "__main__":
    main()
