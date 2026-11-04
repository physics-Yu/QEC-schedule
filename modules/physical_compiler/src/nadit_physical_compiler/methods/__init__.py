"""Result-level NADiT methods, independent of physical compiler selection."""

from collections.abc import Mapping
from typing import Any, Literal, overload

from . import retiming
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
        },
        "retiming/v1": {
            "input": "nadit.result/2",
            "cost_model": "additive",
            "options": {"error_params": {}},
            "output": retiming.SCHEMA,
            "scope": "Feedback-free fixed schedule and additive-cost reference check.",
        },
    }


@overload
def run_method(
    name: Literal["stim/v1"],
    document: Mapping[str, Any],
    *,
    noise_params: Mapping[str, Any] | None = None,
    annotations: Mapping[str, Any] | None = None,
    allow_fixed_case: bool = False,
) -> StimExport: ...


@overload
def run_method(
    name: Literal["retiming/v1"],
    document: Mapping[str, Any],
    *,
    error_params: Mapping[str, Any] | None = None,
) -> dict[str, Any]: ...


@overload
def run_method(
    name: str,
    document: Mapping[str, Any],
    *,
    noise_params: Mapping[str, Any] | None = None,
    annotations: Mapping[str, Any] | None = None,
    allow_fixed_case: bool = False,
    error_params: Mapping[str, Any] | None = None,
) -> StimExport | dict[str, Any]: ...


def run_method(
    name: str,
    document: Mapping[str, Any],
    *,
    noise_params: Mapping[str, Any] | None = None,
    annotations: Mapping[str, Any] | None = None,
    allow_fixed_case: bool = False,
    error_params: Mapping[str, Any] | None = None,
) -> StimExport | dict[str, Any]:
    """Translate or re-time a validated saved result without recompiling."""
    if name == "retiming/v1":
        if annotations is not None or noise_params is not None or allow_fixed_case:
            raise ValueError("retiming/v1 accepts only additive error_params.")
        if error_params is not None and not isinstance(error_params, Mapping):
            raise ValueError("retiming/v1 error parameters must be a JSON object.")
        result = retiming.export(document)
        result["acceptance"] = retiming.accept(document, result, error_params or {})
        return result
    if name != "stim/v1":
        raise ValueError(f"Unknown NADiT method {name!r}.")
    if error_params is not None:
        raise ValueError(
            "stim/v1 expects noise_params; error_params belongs to retiming/v1."
        )
    return translate(
        document,
        noise_params=noise_params,
        annotations=annotations,
        allow_fixed_case=allow_fixed_case,
    )
