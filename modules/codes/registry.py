"""Explicit dispatch to concrete code-owned compilation entries."""

from .contracts import CodeEntry
from .rotated_surface_d3.entry import compilation_entry as d3_entry
from .rotated_surface_d5.entry import compilation_entry as d5_entry
from .rotated_surface_d9.entry import compilation_entry as d9_entry
from .rotated_surface_d11.entry import compilation_entry as d11_entry

_ENTRIES = {
    "rotated_surface_d3": d3_entry,
    "rotated_surface_d5": d5_entry,
    "rotated_surface_d9": d9_entry,
    "rotated_surface_d11": d11_entry,
}


def get_entry(code: str, scheme: str) -> CodeEntry:
    """Load an explicitly named entry; unknown codes or schemes raise ValueError."""
    if code not in _ENTRIES:
        raise ValueError(f"UNKNOWN_CODE: {code!r}; choose one of {tuple(_ENTRIES)}.")
    entry = _ENTRIES[code]()
    if scheme != entry.scheme:
        raise ValueError(f"UNKNOWN_SCHEME: {scheme!r} for {code!r}.")
    return entry
