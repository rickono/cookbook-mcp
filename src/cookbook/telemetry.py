"""Small event-only logging boundary shared by worker and lightweight supervisor."""

import json


def event(name):
    # Only fixed event names, never exceptions, URLs, IDs or request data.
    print(json.dumps({"event": name}), flush=True)
