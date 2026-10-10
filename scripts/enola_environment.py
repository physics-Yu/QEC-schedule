"""R7-only Enola source/dependency provenance. No compiler fallback or vendor edits."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "third_party/enola"
SOURCE = VENDOR / "upstream"
COMMIT = "2944dbf4e163e8d2eeeec607add0d9139edce689"
DEPS = {"networkx": "3.5", "rustworkx": "0.17.1", "numpy": "2.3.5"}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", str(SOURCE), *args], text=True, encoding="utf-8").strip()


def source_files():
    if not (SOURCE/'.git').exists():
        # R7's byte-verified export deliberately omits .git. Check every
        # selected source against the original pinned tree, not a new pin.
        manifest=json.loads((VENDOR/'pin.json').read_bytes())
        expected=manifest['source_files_sha256']
        tree=hashlib.sha256(json.dumps(expected,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if manifest['commit']!=COMMIT or tree!=manifest['source_tree_sha256']:
            raise ValueError('ENOLA_PIN_MISMATCH')
        for name,value in expected.items():
            path=(SOURCE/name).resolve()
            if not path.is_relative_to(SOURCE.resolve()) or not path.is_file():
                raise ValueError(f'ENOLA_SOURCE_MISSING: {name}')
            if sha(path)!=value:raise ValueError(f'ENOLA_SOURCE_CHANGED: {name}')
        extra={p.relative_to(SOURCE).as_posix() for p in (SOURCE/'enola').rglob('*.py')}-expected.keys()
        if extra:raise ValueError(f'ENOLA_EXTRA_SOURCE: {sorted(extra)}')
        return dict(expected)
    entries = git("ls-tree", "-r", COMMIT, "LICENSE", "README.md", "run.py", "enola").splitlines()
    result = {}
    for entry in entries:
        left, name = entry.split("\t")
        mode, kind, object_id = left.split()
        path = SOURCE / name
        if kind != "blob" or not path.is_file():
            raise ValueError(f"ENOLA_SOURCE_MISSING: {name}")
        data = path.read_bytes()
        actual = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        if actual != object_id:
            raise ValueError(f"ENOLA_SOURCE_CHANGED: {name}")
        result[name] = hashlib.sha256(data).hexdigest()
    extra = {p.relative_to(SOURCE).as_posix() for p in (SOURCE / "enola").rglob("*.py")} - result.keys()
    if extra:
        raise ValueError(f"ENOLA_EXTRA_SOURCE: {sorted(extra)}")
    return result


def lock_dependencies():
    lines = ["# Python >=3.12. Exact versions and PyPI wheel hashes; source builds excluded."]
    records = {}
    for name, version in DEPS.items():
        url = f"https://pypi.org/pypi/{name}/{version}/json"
        with urllib.request.urlopen(url, timeout=30) as response:
            metadata = json.load(response)
        wheels = [f for f in metadata["urls"] if f["packagetype"] == "bdist_wheel" and not f["yanked"]]
        if not wheels:
            raise ValueError(f"No unyanked wheel: {name}")
        lines.append(f"{name}=={version} \\")
        hashes = sorted({item["digests"]["sha256"] for item in wheels})
        lines.extend("    --hash=sha256:" + h + (" \\" if i < len(hashes) - 1 else "") for i, h in enumerate(hashes))
        records[name] = {"version": version, "metadata_url": url, "requires_python": metadata["info"]["requires_python"], "requires_dist": metadata["info"]["requires_dist"], "license_expression": metadata["info"].get("license_expression"), "wheel_files": [{"filename": f["filename"], "sha256": f["digests"]["sha256"], "url": f["url"]} for f in wheels]}
    (VENDOR / "requirements.lock").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    write(VENDOR / "dependency-sources.json", records)


def pin():
    actual = git("rev-parse", "HEAD")
    if actual != COMMIT:
        raise ValueError(f"ENOLA_WRONG_COMMIT: {actual}")
    files = source_files()
    manifest = {"schema_version": "enola-source-pin/0.1.0", "repository": "https://github.com/UCLA-VAST/Enola", "commit": COMMIT, "source_root": "third_party/enola/upstream", "source_selection": ["enola/**", "LICENSE", "README.md", "run.py"], "omitted": "upstream examples, videos and fidelity reports; not required by core imports", "source_files_sha256": files, "source_tree_sha256": hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "license_files": [{"path": "LICENSE", "sha256": files["LICENSE"], "declared_license": "BSD-3-Clause", "copyright": "2024 UCLA VAST Lab"}], "attribution": "Upstream README credits OLSQ-DPQA for codegen and Misra-Gries-coloring for scheduler. Original source, notice and README preserved.", "dependencies_lock": "third_party/enola/requirements.lock", "dependencies_lock_sha256": sha(VENDOR / "requirements.lock"), "dependencies": DEPS, "verification_status": "git_blob_identity_verified_environment_pending", "created_at_utc": datetime.now(timezone.utc).isoformat(), "integration_qualified": False}
    write(VENDOR / "pin.json", manifest)
    return manifest


def verify():
    manifest = json.loads((VENDOR / "pin.json").read_bytes())
    git_worktree=(SOURCE/'.git').exists()
    if manifest["commit"] != COMMIT or (git_worktree and git("rev-parse", "HEAD") != COMMIT):
        raise ValueError("ENOLA_PIN_MISMATCH")
    if source_files() != manifest["source_files_sha256"]:
        raise ValueError("ENOLA_SOURCE_HASH_MISMATCH")
    if sha(VENDOR / "requirements.lock") != manifest["dependencies_lock_sha256"]:
        raise ValueError("ENOLA_DEPENDENCY_LOCK_CHANGED")
    versions = {name: importlib.metadata.version(name) for name in DEPS}
    if versions != DEPS:
        raise ValueError(f"ENOLA_DEPENDENCY_VERSION_MISMATCH: {versions}")
    sys.path.insert(0, str(SOURCE))
    from enola.enola import Enola
    import enola.enola
    if Path(enola.enola.__file__).resolve() != (SOURCE / "enola/enola.py").resolve():
        raise ValueError("ENOLA_IMPORT_ORIGIN_MISMATCH")
    return {"schema_version": "enola-environment-receipt/0.1.0", "source_verification_mode":"git_blob_identity" if git_worktree else "frozen_export_original_sha256_pin", "verified_at_utc": datetime.now(timezone.utc).isoformat(), "pin_byte_sha256": sha(VENDOR / "pin.json"), "commit": COMMIT, "source_tree_sha256": manifest["source_tree_sha256"], "python": sys.version, "executable": sys.executable, "platform": platform.platform(), "dependencies": versions, "import_origin": str(Path(enola.enola.__file__).resolve()), "callable": str(Enola), "source_and_import_verified": True, "integration_qualified": False, "unsupported_dependency_paths": ["routing_strategy=mis requires external mis/redumis binary; not installed", "upstream QASM/animation/fidelity tools are not the current pipeline"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("pin", "verify"))
    parser.add_argument("--out", type=Path, default=ROOT / "scripts/outputs/T703/environment.json")
    args = parser.parse_args()
    if args.action == "pin":
        lock_dependencies()
        result = pin()
    else:
        result = verify()
        write(args.out, result)
    print(json.dumps({key: result[key] for key in ("commit", "source_tree_sha256", "dependencies", "verification_status", "source_and_import_verified") if key in result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
