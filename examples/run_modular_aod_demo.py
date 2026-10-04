"""Execute an independently reviewed 34-atom, pure-transport dual-AOD demo."""
import argparse
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8782)
    args = parser.parse_args()
    from neutral_atom_experiments.qec_pbc.modular_aod_demo import run, PROPOSAL
    from neutral_atom_app.modular_aod_report import export_report
    from tools.audit_modular_aod import audit_modular_operations
    result, evidence = run(args.output, geometry_guard=audit_modular_operations)
    result["visualization"] = export_report(result, evidence, args.output)
    (args.output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    names = [Path(__file__).relative_to(ROOT).as_posix(),
             "src/neutral_atom_experiments/qec_pbc/modular_aod_demo.py",
             "src/neutral_atom_app/modular_aod_report.py",
             "src/neutral_atom_strategies/scheduling/aod_modules.py", "tools/audit_modular_aod.py", PROPOSAL,
             "src/neutral_atom_app/native_kernel_view.py", "src/neutral_atom_env/visualization/viewer.py",
             "src/neutral_atom_env/visualization/viewer.js", "src/neutral_atom_env/visualization/viewer-shell.html",
             "src/neutral_atom_env/visualization/summary.py", "src/neutral_atom_env/visualization/theme.py"]
    names.extend(p.relative_to(ROOT).as_posix() for p in (ROOT / "src/neutral_atom_kernel").glob("*.py"))
    names.extend(p.relative_to(ROOT).as_posix()
                 for p in (ROOT / "src/neutral_atom_strategies/native_kernel").glob("*.py"))
    manifest = {"schema": "modular-aod-demo-manifest/1",
                "source_sha256": {n: sha256((ROOT / n).read_bytes()).hexdigest() for n in sorted(set(names))},
                "artifact_sha256": {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(args.output.iterdir())
                                    if p.is_file() and p.name != "manifest.json"},
                "scope": "Explicit two-device pure transport; no native compilation, syndrome or full Shor."}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if result["offline_physical_status"] != "PASS":
        return 1
    if args.serve:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(SimpleHTTPRequestHandler,
                                     directory=str(args.output.resolve())))
        print(f"http://127.0.0.1:{server.server_port}/", flush=True)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
