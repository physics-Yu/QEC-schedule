"""Standalone offline trace player; does not import or rerun the scheduler."""
import json
from pathlib import Path


def save_animation(trace, path):
    from ..trace import validate_trace
    validate_trace(trace)
    # Escape HTML delimiters even when a user-defined code supplies the identifiers.
    payload = json.dumps(trace, ensure_ascii=True).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    html = Path(__file__).with_name('trace_player.html').read_text(encoding='utf-8')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html.replace('__TRACE_DATA__', payload), encoding='utf-8')
    return path
