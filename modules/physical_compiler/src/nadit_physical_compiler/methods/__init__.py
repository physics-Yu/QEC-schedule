"""Result-level NADiT methods, independent of physical compiler selection."""

from collections.abc import Mapping
from typing import Any

from .stim_export import StimExport, translate

__all__ = ["StimExport", "describe_methods", "run_method"]


def describe_methods() -> dict[str, Any]:
    """Declare the current method, cost dependency and simulation boundary."""
    return {
        "stim/v1": {
            "input": "nadit.result/2",
            "cost_model": "noise/v1",
            "optional_extra": "simulation",
            "options": {"allow_fixed_case": False, "noise_params": {}},
            "annotations": "nadit.stim.annotations/1",
            "output": "nadit.stim/1",
            "scope": (
                "Clifford and Pauli/readout simulation; "
                "loss/leakage reported separately"
            ),
        }
    }


def run_method(
    name: str,
    document: Mapping[str, Any],
    *,
    noise_params: Mapping[str, Any] | None = None,
    annotations: Mapping[str, Any] | None = None,
    allow_fixed_case: bool = False,
) -> StimExport:
    """Translate a validated saved result without invoking any compiler."""
    if name != "stim/v1":
        raise ValueError(f"Unknown NADiT method {name!r}.")
    return translate(
        document,
        noise_params=noise_params,
        annotations=annotations,
        allow_fixed_case=allow_fixed_case,
    )
