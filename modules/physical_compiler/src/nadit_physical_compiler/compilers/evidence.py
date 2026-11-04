"""Optional compiler evidence kept outside the executable result schema."""

from copy import deepcopy
from typing import Any

from ..provenance import canonical_hash
from .registry import identity


def compiler_evidence(
    compiler: object,
    strategy: dict[str, Any],
    document: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Bind a compiler's latest evidence to the canonical saved result bytes.

    Compilers without evidence retain their existing output. The digest uses
    canonical JSON, so whitespace and platform line endings do not change it.
    """
    evidence = getattr(compiler, "last_evidence", None)
    if evidence is None:
        return None
    return {
        "schema": "nadit.compiler-evidence/1",
        "compiler": identity(strategy),
        "result_sha256": canonical_hash(document) if document is not None else None,
        "evidence": deepcopy(evidence),
    }
