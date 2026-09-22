"""Versioned file protocol to the unmodified author compiler, never a fallback."""
import json
import os
from pathlib import Path
import subprocess
from time import perf_counter

ROOT = Path(__file__).resolve().parents[3]


def native_python():
    configured = os.environ.get('QEC_QMAP_PYTHON')
    path = Path(configured) if configured else ROOT / 'artifacts/qmap-native/venv' / (
        'Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not path.is_file():
        raise RuntimeError('Native QMAP is not installed; run tools/setup_qmap_native.py')
    return path


def compile_native(request, directory, *, timeout_s=300):
    """Compile one input; save source NAViz, exact stats and process diagnostics."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    input_path = directory / 'request.json'
    input_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding='utf-8')
    output = directory / 'native.json'
    # Prevent stale success from being consumed after a failed attempt.
    if output.exists():
        output.unlink()
    start = perf_counter()
    proc = subprocess.run([str(native_python()), str(Path(__file__).with_name('worker.py')),
        str(input_path), str(output)], capture_output=True, text=True, encoding='utf-8',
        errors='replace', timeout=timeout_s)
    (directory/'worker.log').write_text(proc.stdout + proc.stderr, encoding='utf-8')
    if proc.returncode or not output.is_file():
        raise RuntimeError(f'Native QMAP failed; see {directory / "worker.log"}: {proc.stderr[-1500:]}')
    result = json.loads(output.read_text(encoding='utf-8'))
    result['process_wall_seconds'] = perf_counter() - start
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
