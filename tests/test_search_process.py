"""Search subprocess custody without starting an engine, parser or model."""

from cookbook.book_search import BookSearch


def test_search_child_does_not_inherit_provider_or_reader_credentials(
    tmp_path, monkeypatch
):
    names = [
        "AWS_SECRET_ACCESS_KEY",
        "S3_BUCKET",
        "COOKBOOK_ALLOWED_SUBJECT",
        "REPORTS_AWS_SECRET_ACCESS_KEY",
        "READER_CLIENT_SECRET",
        "READER_SESSION_KEY",
        "PERSONAL_AWS_SECRET_ACCESS_KEY",
        "OWNER_REPORTS_AWS_SECRET_ACCESS_KEY",
        "OPENAI_API_KEY",
        "TYPESENSE_API_KEY",
    ]
    for name in names:
        monkeypatch.setenv(name, "synthetic-secret")
    monkeypatch.setenv("LANG", "C.UTF-8")
    captured = {}

    class Process:
        stopped = False

        def poll(self):
            return 0 if self.stopped else None

        def terminate(self):
            self.stopped = True

        def wait(self, timeout):
            return 0

    def start(*args, **kwargs):
        captured.update(kwargs)
        return Process()

    engine = BookSearch("/synthetic/typesense-server", tmp_path)
    monkeypatch.setattr("cookbook.book_search.subprocess.Popen", start)
    monkeypatch.setattr(engine, "call", lambda *a, **k: {"ok": True, "version": "30.2"})
    try:
        engine.start()
        leaked = sorted(set(names).intersection(captured["env"]))
        assert leaked == []
        assert captured["env"]["LANG"] == "C.UTF-8"
    finally:
        engine.close()
