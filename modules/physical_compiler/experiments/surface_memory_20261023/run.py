"""Frozen, bounded server execution with atomic per-stage checkpoints."""

import concurrent.futures
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOURNAL_LOCK = threading.Lock()


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    tmp.replace(path)


class Campaign:
    def __init__(self, root):
        self.root = root.resolve()
        self.manifest = read(root / "manifest.json")
        self.manifest_hash = digest(root / "manifest.json")
        self.source = Path(self.manifest["source"])
        self.cwd = self.source / "modules/physical_compiler"
        self.python = self.cwd / ".venv/bin/python"
        self.env = {
            **os.environ,
            **{
                key: "1"
                for key in (
                    "OMP_NUM_THREADS",
                    "OPENBLAS_NUM_THREADS",
                    "MKL_NUM_THREADS",
                    "NUMEXPR_NUM_THREADS",
                )
            },
            "PYTHONUNBUFFERED": "1",
        }
        self.budget = self.manifest["config"]["budget"]
        self.verify()

    def verify(self):
        if digest(self.root / "manifest.json") != self.manifest_hash:
            raise RuntimeError("Campaign manifest changed")
        for base, records in (
            (self.source, self.manifest["source_hashes"]),
            (self.root, self.manifest["inputs"]),
            (HERE, self.manifest["harness_hashes"]),
        ):
            for path, expected in records.items():
                if digest(base / path) != expected:
                    raise RuntimeError(f"Frozen content changed: {base / path}")

    def stage(self, case, phase, destination, shard=None, shots=None):
        self.verify()
        destination.mkdir(parents=True, exist_ok=True)
        key = phase if shard is None else f"sample-{shard:02d}"
        status_path = destination / f"{key}.status.json"
        if status_path.exists():
            old = read(status_path)
            if old["manifest_hash"] != self.manifest_hash:
                raise RuntimeError("Resume manifest differs")
            if old["status"] != "running":
                for path, expected in old.get("outputs", {}).items():
                    if digest(destination / path) != expected:
                        raise RuntimeError(f"Completed output changed: {path}")
                return old
        cmd = [
            str(self.python),
            str(HERE / "worker.py"),
            phase,
            str(self.root),
            case["label"],
            str(destination),
        ]
        if shard is not None:
            cmd += [str(shard), str(shots)]
        timeout = self.budget[
            {
                "compile": "compile_timeout_s",
                "export": "export_timeout_s",
                "sample": "shard_timeout_s",
            }[phase]
        ]
        record = {
            "manifest_hash": self.manifest_hash,
            "case": case["label"],
            "run_id": case["run_id"],
            "phase": phase,
            "shard": shard,
            "status": "running",
            "started_at": time.time(),
            "command": cmd,
        }
        write(status_path, record)
        start = time.monotonic()
        with (destination / f"{key}.log").open("w") as log:
            process = subprocess.Popen(
                cmd,
                cwd=self.cwd,
                env=self.env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            record["pid"] = process.pid
            write(status_path, record)
            try:
                code = process.wait(timeout=timeout)
                status = "ok" if code == 0 else "failed"
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                code, status = process.returncode, "timeout"
        self.verify()
        outputs = {
            "compile": ["result.json", "compile-metrics.json"],
            "export": ["circuit.stim", "export.json"],
            "sample": [f"shards/{shard:02d}.json"] if shard is not None else [],
        }[phase]
        record.update(
            status=status,
            exit_code=code,
            elapsed_s=time.monotonic() - start,
            finished_at=time.time(),
            outputs={name: digest(destination / name) for name in outputs}
            if status == "ok"
            else {},
        )
        write(status_path, record)
        with JOURNAL_LOCK:
            with (self.root / "events.jsonl").open("a") as journal:
                journal.write(json.dumps(record) + "\n")
            print(
                json.dumps(
                    {
                        k: record[k]
                        for k in ("case", "phase", "shard", "status", "elapsed_s")
                    }
                ),
                flush=True,
            )
        return record

    def pipeline(self, case, smoke=False):
        destination = self.root / ("smoke" if smoke else "runs") / case["label"]
        for phase in ("compile", "export"):
            if self.stage(case, phase, destination)["status"] != "ok":
                return False
        if smoke:
            return self.stage(case, "sample", destination, 0, 128)["status"] == "ok"
        return True

    def run(self, smoke):
        cases = self.manifest["cases"]
        if smoke:
            cases = [c for c in cases if c["distance"] == 3 and c["basis"] == "z"]
            outcomes = [self.pipeline(c, True) for c in cases]
            write(
                self.root / "smoke-check.json",
                {
                    "manifest_hash": self.manifest_hash,
                    "ok": all(outcomes),
                    "cases": [c["label"] for c in cases],
                },
            )
            if not all(outcomes):
                raise RuntimeError("Server smoke failed; formal campaign not started")
            return
        checked = read(self.root / "smoke-check.json")
        if not checked["ok"] or checked["manifest_hash"] != self.manifest_hash:
            raise RuntimeError("Matching server smoke evidence required")
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.budget["compile_workers"]
        ) as pool:
            ready = list(pool.map(self.pipeline, cases))
        tasks = [
            (case, i)
            for case, ok in zip(cases, ready, strict=True)
            if ok
            for i in range(self.budget["shards"])
        ]

        def sample(task):
            case, i = task
            return self.stage(
                case,
                "sample",
                self.root / "runs" / case["label"],
                i,
                self.budget["shots_per_shard"],
            )

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.budget["sample_workers"]
        ) as pool:
            list(pool.map(sample, tasks))
        self.verify()
        subprocess.run(
            [str(self.python), str(HERE / "report.py"), str(self.root)],
            cwd=self.cwd,
            env=self.env,
            check=True,
        )


if __name__ == "__main__":
    command, root = sys.argv[1:]
    root = Path(root)
    with (root / "run.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        Campaign(root).run(command == "smoke")
