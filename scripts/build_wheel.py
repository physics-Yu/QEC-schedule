"""Build in an R7-owned snapshot so setuptools does not write in other role paths."""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/environment/R7/wheel")
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    # The interpreter must have the pinned build dependency available already.
    import importlib.metadata
    if importlib.metadata.version("setuptools") != "84.0.0":
        raise ValueError("Use the documented bundled build interpreter with setuptools==84.0.0")
    with tempfile.TemporaryDirectory(prefix="build-", dir=ROOT / "scripts") as temp:
        stage = Path(temp)
        shutil.copy2(ROOT / "pyproject.toml", stage)
        shutil.copytree(ROOT / "src/na_pipeline", stage / "src/na_pipeline", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (stage / "viewer").mkdir()
        for name in ("__init__.py", "viewer.html", "viewer.css", "viewer.js"):
            shutil.copy2(ROOT / "viewer" / name, stage / "viewer" / name)
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-build-isolation", "--no-deps", "--wheel-dir", str(args.out), str(stage)], check=True)
    wheel = args.out / "na_pipeline-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as archive:
        required = {"na_pipeline/cli.py", "viewer/__init__.py", "viewer/viewer.js", "viewer/viewer.css", "viewer/viewer.html"}
        required.update(p.relative_to(ROOT / "src").as_posix() for p in (ROOT / "src/na_pipeline").rglob("*.py"))
        missing = required - set(archive.namelist())
        if missing:
            raise ValueError(f"Wheel missing package files: {sorted(missing)}")
    print(f"{wheel}\nsha256={hashlib.sha256(wheel.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
