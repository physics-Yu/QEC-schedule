"""Dependency tasks reuse isolated workers, durable journals and bounded retries."""

import errno
import json
import sys
import time
from pathlib import Path

import pytest

from nadit_physical_compiler.experiments import journal, runner
from nadit_physical_compiler.provenance import canonical_hash


def task(mode: str, **payload: object) -> dict:
    body = {
        "kind": "msd.fixture",
        "payload": {"mode": mode, **payload},
        "dependencies": [],
        "timeout_s": 5,
        "max_attempts": 2,
        "memory_bytes": 512 * 1024**2,
    }
    return {"task_id": canonical_hash(body), **body}


def plan(*tasks: dict) -> dict:
    return {
        "schema": "nadit.task_plan/1",
        "tasks": list(tasks),
        "source_paths": [],
        "budget": {"campaign_timeout_s": 20, "max_storage_bytes": 20_000_000},
    }


def windows_denied(path, code=5):
    error = PermissionError(
        errno.EACCES, "synthetic Windows file sharing denial", str(path)
    )
    if code is not None:
        error.winerror = code
    return error


def test_atomic_replace_releases_existing_reader_without_nonatomic_delete(
    tmp_path, monkeypatch
):
    """A real Windows reader lacks delete sharing; POSIX may replace immediately."""
    path = tmp_path / "campaign_status.json"
    path.write_text('{"old":true}', encoding="utf-8")
    held_reader = path.open("rb")
    sleeps = []

    def release_reader(delay):
        sleeps.append(delay)
        assert json.loads(path.read_text()) == {"old": True}
        assert json.loads(path.with_suffix(".json.tmp").read_text()) == {"new": True}
        held_reader.close()

    monkeypatch.setattr(time, "sleep", release_reader)
    try:
        journal.write_json(path, {"new": True})
        assert json.loads(path.read_text()) == {"new": True}
        assert sleeps == ([0.01] if sys.platform == "win32" else [])
    finally:
        held_reader.close()


def test_handshake_read_transient_permission_denial_does_not_abort_or_retry_task(
    tmp_path, executor, monkeypatch
):
    original = Path.read_text
    denied = []

    def read_handshake(path, *args, **kwargs):
        if path.name.endswith(".started.json") and not denied:
            denied.append(str(path))
            raise windows_denied(path, None)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(journal, "_WINDOWS", True, raising=False)
    monkeypatch.setattr(Path, "read_text", read_handshake)
    one = task("sleep", seconds=0.3)
    report = runner.run_task_plan(
        plan(one), tmp_path / "campaign", task_executor=executor
    )
    assert len(denied) == 1
    assert report["statuses"] == {"ok": 1}
    assert report["tasks"][one["task_id"]]["attempts"] == 1
    assert report["tasks"][one["task_id"]]["software_failures"] == 0


@pytest.fixture
def executor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    module = tmp_path / "fixture_task_executor.py"
    module.write_text(
        """
import hashlib
import json
import os
import time
from pathlib import Path
from nadit_physical_compiler.provenance import canonical_hash

def execute_task(task):
    p=task["payload"]
    mode=p["mode"]
    if mode=="dependent" and not Path(p["marker"]).exists():
        return {"status":"needs_dependencies", "dependency_requests":[p["request"]],
                "software_seconds":{"lookup":0.01}}
    if mode in ("create", "drift"):
        Path(p["marker"]).write_text("done", encoding="utf-8")
    if mode=="create":
        return {"status":"ok", "result":{"cached":True}, "artifacts":[{
            "path":p["marker"], "hash_kind":"bytes",
            "sha256":hashlib.sha256(Path(p["marker"]).read_bytes()).hexdigest()}]}
    if mode=="late_miss" and not Path(p["once"]).exists():
        Path(p["once"]).write_text("missed", encoding="utf-8")
        return {"status":"needs_dependencies", "dependency_requests":[p["request"]]}
    if mode=="defer_once" and not Path(p["marker"]).exists():
        Path(p["marker"]).write_text("deferred", encoding="utf-8")
        return {"status":"deferred", "retry_after_s":0.01}
    if mode=="sleep":
        time.sleep(p["seconds"])
    if mode=="error":
        raise RuntimeError("fixture failure")
    if mode=="partial":
        return {"status":"software_error", "reason":"later cycle failed",
                "result":{"prior_outputs":[{"cycle":0}]}}
    if mode=="crash":
        os._exit(7)
    if mode=="large":
        return {"status":"ok", "result":{"bytes":"x"*1000000}}
    if mode=="fill":
        Path(p["marker"]).write_bytes(b"x"*p["bytes"])
        return {"status":"ok", "result":{"filled":True}}
    return {"status":"ok", "result":{"value":p.get("value", 1)},
            "software_seconds":{"execution":0.02}}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "PYTHONPATH",
        str(tmp_path)
        + __import__("os").pathsep
        + __import__("os").environ.get("PYTHONPATH", ""),
    )
    monkeypatch.setattr(
        runner,
        "code_version",
        lambda **kwargs: {
            "commit": "fixture",
            "dirty": False,
            "source_hash": "fixture",
        },
    )
    monkeypatch.setattr(runner, "check_version", lambda expected: None)
    return "fixture_task_executor:execute_task"
