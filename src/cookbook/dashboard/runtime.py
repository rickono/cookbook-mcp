"""Independent bounded observations and atomic dashboard-owned snapshots."""

import copy
import json
import os
import threading
import time
from pathlib import Path

from .metadata import assemble, read_json, read_source, require
from .remote import collect_remote


class Dashboard:
    def __init__(self, config, *, clock=time.time, reader=read_source):
        self.config = config
        if config.get("reader_origin"):
            from urllib.parse import urlsplit

            origin = urlsplit(config["reader_origin"])
            require(
                origin,
                origin.scheme == "https"
                and bool(origin.hostname)
                and not any(
                    (
                        origin.username,
                        origin.password,
                        origin.path,
                        origin.query,
                        origin.fragment,
                    )
                ),
            )
        self.clock, self.reader = clock, reader
        self.lock = threading.RLock()
        self.sources = config.get("sources", [])
        require(self.sources, len({s["id"] for s in self.sources}) == len(self.sources))
        require(self.sources, len(self.sources) <= 256)
        self.storage = Path(config["storage"]).resolve()
        # Never let retention or snapshot writes touch an input location.
        for s in self.sources:
            if "path" in s:
                p = Path(s["path"]).resolve()
                require(
                    p,
                    p != self.storage
                    and self.storage not in p.parents
                    and p not in self.storage.parents,
                )
        for p in config.get("usage", []):
            require(p, self.storage not in Path(p).resolve().parents)
        self.storage.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.observations, self.flights, self.due = {}, {}, {}
        self.bearer = None
        self.storage_error = None
        self.last_saved = None
        self.stop = threading.Event()
        saved = self.storage / "snapshot.json"
        if saved.exists():
            try:
                data, _ = read_json(saved)
                require(data, data["version"] == "dashboard-snapshot.v1")
                self.observations = {
                    o["id"]: {**o, "status": "unknown"}
                    for o in data["observations"]
                    if o["id"] in {s["id"] for s in self.sources}
                }
            except (OSError, ValueError, KeyError):
                self.storage_error = "previous snapshot unavailable"

    @classmethod
    def from_file(cls, path):
        config, _ = read_json(path)
        require(config, config.get("version") == "dashboard-config.v1")
        base = Path(path).resolve().parent
        config["storage"] = str(base / config["storage"])
        for s in config.get("sources", []):
            if "path" in s:
                s["path"] = str(base / s["path"])
        config["usage"] = [str(base / p) for p in config.get("usage", [])]
        return cls(config)

    def _launch(self, source):
        flight = {"started": time.monotonic(), "done": False, "timeout": False}
        self.flights[source["id"]] = flight

        def work():
            try:
                flight["data"] = (
                    collect_remote(source, self.bearer)
                    if source["kind"] == "remote"
                    else self.reader(source)
                )
            except Exception:  # noqa: BLE001 - redacted observation boundary
                flight["error"] = True
            finally:
                flight["done"] = True

        threading.Thread(target=work, daemon=True, name="dashboard-reader").start()

    def tick(self, *, force=False):
        with self.lock:
            now = self.clock()
            previous_observations = dict(self.observations)
            changed = False
            for source in self.sources:
                sid, remote = source["id"], source["kind"] == "remote"
                flight = self.flights.get(sid)
                if flight:
                    deadline = 20 if remote else 5
                    timed_out = time.monotonic() - flight["started"] > deadline
                    if flight["done"] or (timed_out and not flight["timeout"]):
                        previous = self.observations.get(sid, {})
                        failed = flight.get("error") or timed_out or flight["timeout"]
                        self.observations[sid] = {
                            "id": sid,
                            "remote": remote,
                            "status": "unknown" if failed else "ok",
                            "observed_at": previous.get("observed_at")
                            if failed
                            else now,
                            "attempted_at": now,
                            "data": previous.get("data") if failed else flight["data"],
                            "historical_at": source.get("historical_at"),
                            "error": "observation unavailable, timed out or unsupported"
                            if failed
                            else None,
                        }
                        changed = True
                        if flight["done"]:
                            del self.flights[sid]
                            self.due[sid] = now + (300 if remote else 30)
                        else:
                            flight["timeout"] = True
                if sid not in self.flights and (force or now >= self.due.get(sid, 0)):
                    self._launch(source)
            if changed and not self._save():
                self.observations = previous_observations

    def refresh(self, *, wait=False):
        self.tick(force=True)
        if wait:
            until = time.monotonic() + (
                20.1 if any(s["kind"] == "remote" for s in self.sources) else 5.1
            )
            while self.flights and time.monotonic() < until:
                time.sleep(0.01)
                self.tick()
        return self.snapshot()

    def snapshot(self):
        with self.lock:
            now = self.clock()
            observations = []
            for s in self.sources:
                obs = copy.deepcopy(
                    self.observations.get(
                        s["id"],
                        {
                            "id": s["id"],
                            "status": "unknown",
                            "observed_at": None,
                            "data": None,
                            "error": "not yet observed",
                        },
                    )
                )
                age = (
                    now - obs["observed_at"]
                    if obs.get("observed_at") is not None
                    else None
                )
                obs["stale"] = age is not None and age > (
                    600 if s["kind"] == "remote" else 60
                )
                observations.append(obs)
            books = assemble(observations, now)
            included = [b for b in books if b["membership"] == "included"]
            summary = {
                "included": len(included),
                "undecided": sum(b["membership"] == "undecided" for b in books),
                "conflict": sum(b["membership"] == "conflict" for b in books),
                "excluded": sum(b["membership"] == "excluded" for b in books),
                "held": sum(bool(b["holds"]) for b in included),
                "attention": sum(b["attention"] for b in included),
            }
            return {
                "version": "dashboard-snapshot.v1",
                "at": now,
                "books": books,
                "summary": summary,
                "observations": observations,
                "storage_error": self.storage_error,
                "refreshing": bool(self.flights),
                "owner_queue_total": None
                if any(o["status"] != "ok" or o["stale"] for o in observations)
                or not self.config.get("owner_queue_complete", False)
                else sum(len(b["queue"]) for b in books),
            }

    def _save(self):
        snapshot = {
            "version": "dashboard-snapshot.v1",
            "observations": list(self.observations.values()),
        }
        encoded = json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()
        # Volatile attempted/observation times do not create identical history records.
        signature = json.dumps(
            [
                {k: v for k, v in o.items() if k not in {"attempted_at", "observed_at"}}
                for o in snapshot["observations"]
            ],
            sort_keys=True,
        )
        limit = min(self.config.get("max_storage_bytes", 100 * 1024**2), 100 * 1024**2)
        current = self.storage / "snapshot.json"
        history = sorted(self.storage.glob("history-*.json"))
        try:
            now = self.clock()
            for p in list(history):
                if now - p.stat().st_mtime > 30 * 86400:
                    p.unlink()
                    history.remove(p)
            # Budget includes old snapshot + temp replacement + optional history.
            needed = len(encoded) * (2 if signature != self.last_saved else 1) + (
                current.stat().st_size if current.exists() else 0
            )
            while history and needed + sum(p.stat().st_size for p in history) > limit:
                history.pop(0).unlink()
            if needed + sum(p.stat().st_size for p in history) > limit:
                raise OSError("storage cap")
            temporary = self.storage / "snapshot.tmp"
            with temporary.open("wb") as f:
                os.chmod(temporary, 0o600)
                f.write(encoded)
                f.flush()
                os.fsync(f.fileno())
            if signature != self.last_saved:
                h = self.storage / f"history-{time.time_ns():020d}.json"
                h.write_bytes(encoded)
                h.chmod(0o600)
            os.replace(temporary, current)
            self.last_saved = signature
            self.storage_error = None
            return True
        except OSError:
            self.storage_error = "snapshot storage failed; previous snapshot retained"
            return False

    def run(self):
        self.tick(force=True)
        while not self.stop.wait(0.1):
            self.tick()
