"""Run only inside an isolated T703 server project, under jobs.py budgets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
import venv

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=("single", "two", "coupled"))
    parser.add_argument("--fake-value", choices=(0, 1), type=int, default=0)
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        raise RuntimeError("REMOTE_PYTHON_TOO_OLD")
    environment = ROOT / "scripts/.venv"
    # Ubuntu's system Python may omit ensurepip. Stay entirely in this project.
    venv.EnvBuilder(with_pip=False).create(environment)
    python = environment / "bin/python"
    output = ROOT / "scripts/outputs/T703"
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / "temporary"
    temporary.mkdir(exist_ok=True)
    os.environ["TMPDIR"] = str(temporary)
    os.environ["PIP_CACHE_DIR"] = str(output / "pip-cache")
    bootstrap_version = "25.2"
    metadata_url = f"https://pypi.org/pypi/pip/{bootstrap_version}/json"
    with urllib.request.urlopen(metadata_url, timeout=30) as response:
        metadata = json.load(response)
    wheel = next(f for f in metadata["urls"] if f["filename"].endswith("py3-none-any.whl") and not f["yanked"])
    with urllib.request.urlopen(wheel["url"], timeout=30) as response:
        raw = response.read()
    if hashlib.sha256(raw).hexdigest() != wheel["digests"]["sha256"]:
        raise ValueError("PIP_BOOTSTRAP_HASH_MISMATCH")
    bootstrap = output / wheel["filename"]
    bootstrap.write_bytes(raw)
    (output / "bootstrap-receipt.json").write_bytes((json.dumps({"version": bootstrap_version, "source": metadata_url, "wheel_url": wheel["url"], "sha256": wheel["digests"]["sha256"], "scope": "project-only zip-import bootstrap; no system package changes"}, indent=2) + "\n").encode())
    pip_code = "import sys,runpy; sys.path.insert(0," + repr(str(bootstrap)) + "); runpy.run_module('pip',run_name='__main__')"
    subprocess.run([str(python), "-c", pip_code, "install", "--only-binary=:all:", "--require-hashes", "--report", str(output / "remote-pip-install.json"), "-r", str(ROOT / "third_party/enola/requirements.lock")], check=True)
    return subprocess.run([str(python), "-m", "na_pipeline", "strategy", "run", "--request", str(output / "requests" / (args.case + ".json")), "--out", str(output / "remote-run"), "--fake-value", str(args.fake_value)], cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
