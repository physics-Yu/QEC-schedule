"""Structured compiler outcomes shared by CLI and experiment workers."""

from copy import deepcopy
from typing import Any


class SearchExhausted(ValueError):
    """A bounded placement search ended without a completed goal."""


class BoundedSearchFailure(ValueError):
    """A proof-producing search returned no schedule, retaining its exact status."""

    def __init__(self, evidence: dict[str, Any]) -> None:
        self.evidence = deepcopy(evidence)
        self.status = str(evidence["status"])
        self.budget_hit = bool(evidence.get("budget_hit", False))
        super().__init__(f"Bounded search returned {self.status}")

    def document(self) -> dict[str, Any]:
        """Return a machine-readable outcome without equating UNSAT to timeout."""
        return {
            "status": self.status,
            "budget_hit": self.budget_hit,
            "reason": str(self),
            "evidence": deepcopy(self.evidence),
        }
