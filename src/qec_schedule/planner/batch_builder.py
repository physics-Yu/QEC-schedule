"""Deterministic grouping of ready semantic requests.

The builder intentionally knows nothing about coordinates or device locks.  It
only applies dependency-ready ordering and atom-disjointness before the
hardware feasibility layer makes a physical decision.
"""
from dataclasses import dataclass

from ..compiler.semantic_requests import (EntangleRequest, MeasureRequest,
                                          PrepareRequest, ResetRequest,
                                          SemanticRequest, SingleQubitRequest)


class _Batch:
    @property
    def request_ids(self):
        return tuple(request.id for request in self.requests)

    @property
    def atoms(self):
        atoms = []
        for request in self.requests:
            atoms.extend(request.atoms if isinstance(request, EntangleRequest) else (request.atom,))
        return tuple(atoms)


@dataclass(frozen=True, init=False)
class RequestBatch(_Batch):
    requests: tuple[SemanticRequest, ...]
    kind: str

    def __init__(self, requests, kind):
        object.__setattr__(self, "requests", tuple(requests))
        object.__setattr__(self, "kind", str(kind))
        if not self.requests:
            raise ValueError("A request batch cannot be empty")
        if len(set(self.request_ids)) != len(self.requests):
            raise ValueError("A request batch cannot contain duplicate requests")
        if len(self.atoms) != len(set(self.atoms)):
            raise ValueError("A request batch cannot reuse an atom")


class EntangleBatch(RequestBatch):
    def __init__(self, requests):
        if not all(isinstance(request, EntangleRequest) for request in requests):
            raise ValueError("EntangleBatch requires EntangleRequest values")
        super().__init__(requests, "ENTANGLE")


class MeasureBatch(RequestBatch):
    def __init__(self, requests):
        if not all(isinstance(request, MeasureRequest) for request in requests):
            raise ValueError("MeasureBatch requires MeasureRequest values")
        super().__init__(requests, "MEASURE")


class SingleQubitBatch(RequestBatch):
    def __init__(self, requests):
        if not all(isinstance(request, SingleQubitRequest) for request in requests):
            raise ValueError("SingleQubitBatch requires SingleQubitRequest values")
        super().__init__(requests, "SINGLE_QUBIT")


class PrepareBatch(RequestBatch):
    def __init__(self, requests):
        if not all(isinstance(request, PrepareRequest) for request in requests):
            raise ValueError("PrepareBatch requires PrepareRequest values")
        super().__init__(requests, "PREPARE")


class ResetBatch(RequestBatch):
    def __init__(self, requests):
        if not all(isinstance(request, ResetRequest) for request in requests):
            raise ValueError("ResetBatch requires ResetRequest values")
        super().__init__(requests, "RESET")


class TransportCandidateBatch(RequestBatch):
    """A named batch for runtime-generated movement candidates."""
    def __init__(self, requests):
        super().__init__(requests, "TRANSPORT")


def _metadata_number(request, key, default=0):
    value = request.metadata.get(key, default)
    return value if type(value) in (int, float) else default


class BatchBuilder:
    """Build the largest deterministic atom-disjoint batch for a family."""

    _types = {
        "ENTANGLE": (EntangleRequest, EntangleBatch),
        "MEASURE": (MeasureRequest, MeasureBatch),
        "SINGLE_QUBIT": (SingleQubitRequest, SingleQubitBatch),
        "PREPARE": (PrepareRequest, PrepareBatch),
        "RESET": (ResetRequest, ResetBatch),
    }

    def _family(self, ready, kind):
        try:
            request_type, batch_type = self._types[kind]
        except KeyError as exc:
            raise ValueError(f"Unknown request family: {kind}") from exc
        candidates = [request for request in ready if isinstance(request, request_type)]
        if not candidates:
            return None
        if kind == "ENTANGLE":
            # A ready frontier can contain more than one layer for custom
            # codes.  Try the earliest physical interaction layer first.
            layer = min((_metadata_number(r, "round", 0), _metadata_number(r, "slot", 0))
                        for r in candidates)
            candidates = [r for r in candidates
                          if (_metadata_number(r, "round", 0), _metadata_number(r, "slot", 0)) == layer]
            candidates.sort(key=lambda r: r.id)
        else:
            candidates.sort(key=lambda r: r.id)
        selected, used = [], set()
        for request in candidates:
            atoms = request.atoms if isinstance(request, EntangleRequest) else (request.atom,)
            if not used.intersection(atoms):
                selected.append(request)
                used.update(atoms)
        return batch_type(tuple(selected)) if selected else None

    def build(self, ready, kind: str, *, limit: int | None = None):
        batch = self._family(tuple(ready), kind)
        if batch is None or limit is None or len(batch.requests) <= limit:
            return batch
        return type(batch)(batch.requests[:limit])

    def candidates(self, ready, kind: str):
        """Yield largest-to-smallest prefixes for feasibility fallback."""
        batch = self._family(tuple(ready), kind)
        if batch is None:
            return
        for size in range(len(batch.requests), 0, -1):
            yield type(batch)(batch.requests[:size])


__all__ = ["RequestBatch", "EntangleBatch", "MeasureBatch", "SingleQubitBatch",
           "PrepareBatch", "ResetBatch", "TransportCandidateBatch", "BatchBuilder"]
