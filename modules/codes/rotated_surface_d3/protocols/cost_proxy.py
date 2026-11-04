"""Explicit ideal routing with disjoint physical cost proxies, never logical truth.

The confirmed quantum body is unchanged. Factory proxy acceptance is a separate
event after final MX readiness, and output X still runs only after acceptance.
Its cost belongs to the downstream consumer scope, beginning at that decision.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from ...contracts.event_probability import ProbabilityPort
from ...contracts.factory_recipe import FactoryRecipe
from ..components.canonicalization import PreparationExpansion
from ..probabilities.t_injection import t_injection_port
from .factory import factory_recipe
from .factory_backend import SurfaceFactoryBackend

ROUTING_REFERENCE = "ideal_cost_proxy.v1"
FACTORY_PROXY_PROTOCOL = "rotated_surface_d3.factory_15_to_1.cost_proxy"
_ROUTING_FIELDS = {
    "routing_reference",
    "actual_quality_status",
    "actual_quality_source_port_sha256",
}


def factory_proxy_recipe() -> FactoryRecipe:
    """Preserve the frozen 4+11 body, selecting a separately named final proxy.

    Final MX measurements still execute, but no physical MX values are invented.
    The factory scope excludes complete raw horizons. Accepted output X and all
    subsequent handoff/algorithm time belong to the downstream consumer scope.
    """
    recipe = factory_recipe()
    return replace(
        recipe,
        protocol_id=FACTORY_PROXY_PROTOCOL,
        final_event=replace(recipe.final_event, selector="factory_cost_proxy"),
    )


def _proxy_quality(
    actual_quality: Mapping[str, Any], source_port_sha256: str
) -> dict[str, Any]:
    """Copy unknown actual quality while explicitly permitting reference routing."""
    if actual_quality.get("status") != "unsupported":
        raise ValueError("Proxy routing requires explicit unsupported actual quality.")
    return {
        "status": "cost_proxy_routing",
        "actual_quality": json.loads(json.dumps(actual_quality, allow_nan=False)),
        "routing_reference": {
            "id": ROUTING_REFERENCE,
            "purpose": "ideal logical action routing for a cost-model experiment",
            "actual_quantum_quality_inferred": False,
        },
        "consumption_parameters": {
            "routing_reference": ROUTING_REFERENCE,
            "actual_quality_status": "unsupported",
            "actual_quality_source_port_sha256": source_port_sha256,
        },
        "logical_success_probability": None,
    }


def _routing_port(parameters: Mapping[str, Any] | None) -> ProbabilityPort:
    """Require an explicit reference marker, not an assumed zero input error."""
    if (
        not isinstance(parameters, Mapping)
        or set(parameters) != _ROUTING_FIELDS
        or parameters["routing_reference"] != ROUTING_REFERENCE
        or parameters["actual_quality_status"] != "unsupported"
        or not isinstance(parameters["actual_quality_source_port_sha256"], str)
        or re.fullmatch(
            r"[0-9a-f]{64}", parameters["actual_quality_source_port_sha256"]
        )
        is None
    ):
        raise ValueError(
            "T consumption requires the explicit cost-proxy routing marker."
        )
    reference = t_injection_port()
    document = reference.to_dict()
    document["port_id"] = "rotated_surface_d3.t_consumption.reference_routing"
    document["protocol_id"] = "rotated_surface_d3.t_consumption.reference_routing"
    document["model"] = {
        "id": "t_consumption.ideal_routing_cost_proxy.v1",
        "kind": "ideal_exact",
        "assumptions": [
            "Ideal T teleportation is used solely to route the selected actions",
            "Actual raw or factory resource quantum quality remains unsupported",
            "Fair m0/m1 outcomes are reference events, not observed physical bits",
            "No conditional quantum probabilities for actual noisy inputs are claimed",
        ],
        "parameters": dict(parameters),
        "evidence": {
            "reference_port_sha256": reference.content_sha256,
            "reference_calculation": "canonical ideal T-consumption Kraus operators",
            "physical_measurement_values_claimed": False,
            "logical_success_probability": None,
            "routing_only": True,
        },
    }
    return ProbabilityPort.from_dict(document)


@dataclass(frozen=True)
class SurfaceCostProxyBackend(SurfaceFactoryBackend):
    """Opt-in routing adapter for the user-selected physical no-fault experiment.

    Actual raw detector/byproduct events and their physical reset/correction
    actions use the ordinary backend. Explicit proxy markers allow subsequent
    ideal-reference routing while retaining unknown actual quantum quality.
    Scoped physical reports are supplied by the logical execution owner.
    """

    def preparation_event(
        self,
        preparation: str,
        source: PreparationExpansion,
        parameters: Mapping[str, Any] | None = None,
    ) -> ProbabilityPort:
        """Require actual noise/v1 raw feedback; other preparation is reference-only."""
        name = preparation.removeprefix("rotated_surface_d3/")
        if name == "raw_t_postselection" and (
            not isinstance(parameters, Mapping)
            or parameters.get("noise_model") != "noise/v1"
        ):
            raise ValueError("Cost proxy raw preparation requires explicit noise/v1.")
        if name != "raw_t_postselection" and parameters:
            raise ValueError(
                "Proxy work-state preparation has only the ideal reference."
            )
        return super().preparation_event(preparation, source, parameters)

    def preparation_quality_from_event(
        self,
        preparation: str,
        source: PreparationExpansion,
        port: ProbabilityPort,
        values: Mapping[str, object],
        parameters: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Wrap the actual unsupported result, preserving all event/source evidence."""
        actual = super().preparation_quality_from_event(
            preparation, source, port, values, parameters
        )
        return _proxy_quality(actual, port.content_sha256)

    def preparation_quality(
        self, preparation: str, parameters: Mapping[str, object] | None = None
    ) -> dict[str, Any]:
        """Reject source-free quality inference in this explicit proxy mode."""
        raise ValueError(
            "Cost proxy quality requires the actual source and joint event."
        )

    def resolve_event(
        self, selector: str, parameters: Mapping[str, Any] | None = None
    ) -> ProbabilityPort:
        """Resolve reference routing only with its marker; factory needs real scope."""
        if selector == "t_consumption":
            return _routing_port(parameters)
        if selector in ("factory_mx", "factory_cost_proxy"):
            raise ValueError(
                "Factory cost proxy requires an actual scoped noise report."
            )
        return super().resolve_event(selector, parameters)

    def factory_proxy_event(
        self, noise_report: Mapping[str, Any], scope_evidence: Mapping[str, Any]
    ) -> ProbabilityPort:
        """Build the separate factory accept/retry proxy from a scoped cost report."""
        from ..probabilities.cost_proxy import factory_proxy_port

        return factory_proxy_port(noise_report, scope_evidence)

    def algorithm_proxy_event(
        self, noise_report: Mapping[str, Any], scope_evidence: Mapping[str, Any]
    ) -> ProbabilityPort:
        """Build a downstream no-fault evaluation without asserting logical success."""
        from ..probabilities.cost_proxy import algorithm_proxy_port

        return algorithm_proxy_port(noise_report, scope_evidence)

    def output_quality(self, factory_port: ProbabilityPort) -> dict[str, Any]:
        """Expose unknown output quality and its still-unassessed delivery boundary.

        Call only after a possible accepted proxy outcome and the actual output X.
        The original factory decision is not revisited after executing that X.
        """
        doc = factory_port.to_dict()
        model = doc["model"]
        if (
            factory_port.port_id != FACTORY_PROXY_PROTOCOL
            or factory_port.protocol_id != FACTORY_PROXY_PROTOCOL
            or factory_port.protocol_version != "1"
            or model["id"] != "factory_15_to_1.no_fault_cost_proxy.v1"
            or model["kind"] != "estimated"
            or model["evidence"].get("logical_success_probability", "missing")
            is not None
        ):
            raise ValueError("Output quality requires the explicit factory cost proxy.")
        if factory_port.outcome("accepted").probability <= 0:
            raise ValueError("Factory proxy has no possible accepted output.")
        scope = model["evidence"]["scope"]
        if scope["stage"] != "factory":
            raise ValueError("Output quality requires a factory proxy scope.")
        quality = _proxy_quality(
            {
                "status": "unsupported",
                "source_proxy_port_sha256": factory_port.content_sha256,
                "logical_success_probability": None,
                "reasons": [
                    "Raw residual quality and excluded-world exposure are unknown",
                    "Selected operations' no-fault proxy does not certify logical A",
                ],
            },
            factory_port.content_sha256,
        )
        quality["delivery_assessment"] = {
            "status": "pending",
            "owner": "downstream_consumer",
            "start_us": scope["window_us"][1],
            "includes": ["accepted_output_x", "handoff_wait", "consumer_segment"],
            "factory_proxy_not_retroactively_extended": True,
        }
        return quality
