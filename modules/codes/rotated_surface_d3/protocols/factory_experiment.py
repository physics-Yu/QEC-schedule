"""Explicit full/fast experiment models with separate supply and final checks.

The theory mode combines a noisy raw-supply event with an independently declared
accepted-input Z-error reference. Its final joint MX event alone controls factory
acceptance. Physical no-fault probabilities remain cost diagnostics. The legacy
physical-no-fault experiment is available only under its explicit separate mode.
"""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from math import isfinite
from re import fullmatch
from typing import Any, Literal

from ...contracts.event_probability import ProbabilityPort
from ...contracts.factory_recipe import FactoryRecipe
from ..probabilities.factory import factory_mx_port, preparation_quality
from ..probabilities.factory import output_quality as factory_output_quality
from .cost_proxy import _routing_port, factory_proxy_recipe
from .factory import factory_recipe
from .factory_backend import _consumption_port

type ExperimentMode = Literal["theory", "physical_no_fault_proxy"]


def _probability(value: object) -> float:
    if (
        not isinstance(value, int | float)
        or type(value) not in (int, float)
        or not isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError(
            "input_z_error must be an explicit finite probability in [0, 1]."
        )
    return float(value)


@lru_cache(maxsize=128, typed=True)
def _final_port(p: float) -> ProbabilityPort:
    return factory_mx_port(input_z_error=p)


@lru_cache(maxsize=128)
def _t_port(p: float) -> ProbabilityPort:
    return _consumption_port({"input_z_error": p})


@dataclass(frozen=True)
class FactoryExperimentModel:
    """Select one named experiment; theory requires an explicit accepted-input p.

    Args:
        mode: ``theory`` or the opt-in legacy ``physical_no_fault_proxy``.
        input_z_error: Independent Z error of accepted, canonical A inputs. This
            must be supplied for theory and omitted for the physical proxy.
    Raises:
        ValueError: Unknown mode, missing/invalid p, or mixed model semantics.
    """

    mode: ExperimentMode = "theory"
    input_z_error: float | None = None

    def __post_init__(self) -> None:
        if self.mode not in ("theory", "physical_no_fault_proxy"):
            raise ValueError("Unknown factory experiment mode.")
        if self.mode == "theory":
            _probability(self.input_z_error)
        elif self.input_z_error is not None:
            raise ValueError("Physical no-fault proxy does not accept input_z_error.")

    def recipe(self) -> FactoryRecipe:
        """Return the unchanged body with the selected final event semantics."""
        return factory_recipe() if self.mode == "theory" else factory_proxy_recipe()

    def case_id(self) -> str:
        """Keep theory sampling identities distinct from historical proxy runs."""
        return (
            "factory-array-theory-v1"
            if self.mode == "theory"
            else "factory-array-cost-proxy-v1"
        )

    def parameters(self, noise_params: Mapping[str, Any]) -> dict[str, Any]:
        """Copy supply noise and explicit quality as distinct named parameters."""
        if not isinstance(noise_params, Mapping) or any(
            not isinstance(k, str) for k in noise_params
        ):
            raise ValueError("Supply noise_params require a string-keyed mapping.")
        result: dict[str, Any] = {
            "noise_model": "noise/v1",
            "noise_params": deepcopy(dict(noise_params)),
        }
        if self.mode == "theory":
            result["input_z_error"] = self.input_z_error
        return result

    def raw_preparation_parameters(
        self, parameters: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        """Validate the experiment and strip p before calling the raw noise model."""
        required = {"noise_model", "noise_params"}
        if self.mode == "theory":
            required.add("input_z_error")
        if (
            not isinstance(parameters, Mapping)
            or set(parameters) != required
            or parameters["noise_model"] != "noise/v1"
        ):
            raise ValueError(
                "Raw supply requires the exact experiment noise/v1 parameters."
            )
        if (
            self.mode == "theory"
            and _probability(parameters["input_z_error"]) != self.input_z_error
        ):
            raise ValueError("Experiment input_z_error parameter changed.")
        copied = self.parameters(parameters["noise_params"])
        copied.pop("input_z_error", None)
        return copied

    def reference_quality(
        self, preparation: str, source_port_sha256: str | None = None
    ) -> dict[str, Any]:
        """Declare assumed quality after accepted canonical raw A, not infer it."""
        if self.mode != "theory":
            raise ValueError("Reference input quality requires the theory experiment.")
        result = preparation_quality(preparation, {"input_z_error": self.input_z_error})
        result.update(
            {
                "actual_quantum_quality_status": "unsupported",
                "input_quality_origin": "explicit_reference_assumption",
                "raw_acceptance_does_not_determine_p": True,
            }
        )
        if source_port_sha256 is not None:
            if (
                not isinstance(source_port_sha256, str)
                or fullmatch(r"[0-9a-f]{64}", source_port_sha256) is None
            ):
                raise ValueError(
                    "Preparation acceptance provenance requires a SHA-256."
                )
            result["preparation_acceptance_port_sha256"] = source_port_sha256
        return result

    def consumption_event(
        self, parameters: Mapping[str, Any] | None
    ) -> ProbabilityPort:
        """Resolve T feedback with the consumer's explicit input quality.

        The consumer may receive raw or distilled quality, so its p need not
        equal this experiment's raw-input p. Equatorial Z mixtures keep MZ fair.
        """
        if self.mode == "physical_no_fault_proxy":
            return _routing_port(parameters)
        if not isinstance(parameters, Mapping) or set(parameters) != {"input_z_error"}:
            raise ValueError("Theory T consumption requires exactly input_z_error.")
        return _t_port(_probability(parameters["input_z_error"]))

    def final_theory_event(
        self, parameters: Mapping[str, Any] | None = None
    ) -> ProbabilityPort:
        """Return the exact joint four-check port, retaining its original hash."""
        if self.mode != "theory":
            raise ValueError("Final theory event requires the theory experiment.")
        if parameters is not None:
            if isinstance(parameters, Mapping) and set(parameters) == {"input_z_error"}:
                if _probability(parameters["input_z_error"]) != self.input_z_error:
                    raise ValueError("Experiment input_z_error parameter changed.")
            else:
                self.raw_preparation_parameters(parameters)
        assert self.input_z_error is not None
        return _final_port(self.input_z_error)

    def output_quality(self, factory_port: ProbabilityPort) -> dict[str, Any]:
        """Return conditional reference output quality for this exact model."""
        if self.mode != "theory":
            raise ValueError(
                "Proxy output quality requires the scoped execution backend."
            )
        if factory_port.content_sha256 != self.final_theory_event().content_sha256:
            raise ValueError(
                "Factory output port differs from this experiment's parameters."
            )
        return factory_output_quality(factory_port)

    def to_dict(self) -> dict[str, Any]:
        """Describe assumptions without promoting reference quality to actual truth."""
        if self.mode == "theory":
            model = self.final_theory_event().to_dict()["model"]
            evidence = model["evidence"]
            acceptance = evidence["acceptance_probability"]
            output_error = evidence["conditional_output_z_error"]
            model_id, assumptions = model["id"], model["assumptions"]
        else:
            acceptance, output_error = None, None
            model_id = "physical_no_fault_cost_proxy"
            assumptions = [
                "Explicit legacy physical no-fault proxy; not a 15-to-1 check-acceptance model",
                "Actual logical input and output quality remain unsupported",
            ]
        return {
            "mode": self.mode,
            "input_z_error": self.input_z_error,
            "case_id": self.case_id(),
            "final_event_selector": self.recipe().final_event.selector,
            "acceptance_model_id": model_id,
            "theoretical_acceptance_probability": acceptance,
            "conditional_output_z_error": output_error,
            "physical_no_fault_controls_acceptance": self.mode
            == "physical_no_fault_proxy",
            "actual_logical_quality_established": False,
            "assumptions": assumptions,
        }
