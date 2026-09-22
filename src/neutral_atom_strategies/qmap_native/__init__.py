"""Author QMAP C++ decision layer with an explicit local physical adapter.

No dependency on mqt is imported into the application's Python environment.
The isolated worker owns the author's scheduler, reuse, IDS, router and codegen.
"""
from .client import compile_native

__all__ = ['compile_native']
