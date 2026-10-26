"""Code-owned calibrated events for the common logical factory coordinator."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ...contracts.event_probability import ProbabilityPort
from .cost_proxy import ROUTING_REFERENCE, _proxy_quality
from .factory_experiment import FactoryExperimentModel
from .fast_cost import FastCostCall, evaluate_factory_cost, factory_probability_port
from .fast_profile import FastProfile


class FastCostBackend:
    """Keep joint raw events and recompute factory exposure from current timing.

    Raw supply uses the calibrated joint preparation distribution. In theory
    mode, the joint final checks and output quality use an explicit iid Z-input
    reference. Full-line physical cost is a separate diagnostic and never changes
    those checks. The old raw-excluded cost proxy remains an explicit mode.
    """

    def __init__(
        self,
        profile: FastProfile,
        execution: Any,
        *,
        factory_id: str,
        experiment_model: FactoryExperimentModel,
    ) -> None:
        if factory_id not in {f.factory_id for f in execution.layout.factories}:
            raise ValueError("UNKNOWN_FAST_FACTORY_OWNER")
        self.profile, self.execution, self.factory_id = profile, execution, factory_id
        self.experiment_model = experiment_model
        self._batch = re.compile(r"^" + re.escape(factory_id) + r"/batch\[\d+\]/")
        self._patches = dict(execution.layout.bindings)
        self.raw_horizons: dict[str, dict[str, Any]] = {}
        self.factory_reports: dict[str, dict[str, Any]] = {}
        self._preparation_ports = {
            name: profile.preparation_port(name)
            for name in ("initialize_plus", "raw_t_postselection")
        }
        self._consumption_port = (
            profile.consumption_port()
            if experiment_model.mode == "physical_no_fault_proxy"
            else None
        )

    def _scope(self, invocation_id: str) -> str:
        match = self._batch.match(invocation_id)
        if match is None:
            raise ValueError("INVALID_FAST_FACTORY_SCOPE")
        return match.group(0).removesuffix("/")

    def _parameters(self, parameters: Mapping[str, Any] | None) -> None:
        if parameters != self.experiment_model.parameters(self.profile.noise_params):
            raise ValueError("FAST_NOISE_PARAMETERS_DIFFER_FROM_CALIBRATION")

    def preparation_event(
        self, preparation: str, source: Any, parameters: Mapping[str, Any] | None = None
    ) -> ProbabilityPort:
        """Use one joint acceptance/class draw and remember each own raw horizon."""
        self._parameters(parameters)
        if (
            self.execution.source(source.invocation_id) != source
            or source.representation != "logical_estimate"
            or source.component_id != preparation
        ):
            raise ValueError("INVALID_FAST_PREPARATION_SOURCE")
        scope = self._scope(source.invocation_id)
        port = self._preparation_ports[preparation]
        if preparation == "raw_t_postselection":
            record = {
                "factory_id": self.factory_id,
                "scope_id": scope,
                "source_invocation": source.invocation_id,
                "start_us": source.start_us,
                "results_ready_us": source.results_ready_us,
                "port_sha256": port.content_sha256,
                "representation": "logical_estimate",
            }
            previous = self.raw_horizons.get(source.invocation_id)
            if previous is not None and previous != record:
                raise ValueError("FAST_RAW_HORIZON_CHANGED")
            self.raw_horizons[source.invocation_id] = record
        return port

    def resolve_event(
        self, selector: str, parameters: Mapping[str, Any] | None = None
    ) -> ProbabilityPort:
        """Allow ideal routing only with the explicit unsupported-quality marker."""
        if selector != "t_consumption":
            raise ValueError("FAST_EVENT_REQUIRES_SCOPED_SOURCE")
        if self.experiment_model.mode == "theory":
            return self.experiment_model.consumption_event(parameters)
        if (
            not isinstance(parameters, Mapping)
            or set(parameters)
            != {
                "routing_reference",
                "actual_quality_status",
                "actual_quality_source_port_sha256",
            }
            or parameters["routing_reference"] != ROUTING_REFERENCE
            or parameters["actual_quality_status"] != "unsupported"
            or not isinstance(parameters["actual_quality_source_port_sha256"], str)
            or re.fullmatch(
                r"[0-9a-f]{64}", parameters["actual_quality_source_port_sha256"]
            )
            is None
        ):
            raise ValueError("FAST_T_ROUTING_MARKER_REQUIRED")
        assert self._consumption_port is not None
        return self._consumption_port

    def resolve_event_from_sources(
        self,
        selector: str,
        parts: tuple[Any, ...],
        parameters: Mapping[str, Any],
        *,
        event_id: str,
    ) -> ProbabilityPort:
        """Evaluate the line's current schedule, including peer waits, once."""
        expected = (
            "factory_mx"
            if self.experiment_model.mode == "theory"
            else "factory_cost_proxy"
        )
        if selector != expected:
            return self.resolve_event(selector, parameters)
        self._parameters(parameters)
        scope = self._scope(event_id)
        if not parts or any(
            self._scope(p.invocation_id) != scope
            or p.results_ready_us > self.execution.clock_us
            or self.execution.source(p.invocation_id) != p
            for p in parts
        ):
            raise ValueError("FAST_FACTORY_EVENT_BEFORE_OWN_RESULTS")
        records = [
            call
            for call in self.execution.calls
            if call["invocation_id"].startswith(scope + "/")
        ]
        if not records:
            raise ValueError("FAST_FACTORY_WITHOUT_CALLS")
        calls = tuple(
            FastCostCall(
                call["invocation_id"],
                call["component_id"],
                tuple(self._patches[name] for name in call["participant_blocks"]),
                call["start_us"],
                call["selection"],
                call["parameters"],
            )
            for call in records
        )
        window = (min(call.start_us for call in calls), self.execution.clock_us)
        horizons = tuple(
            (row["start_us"], row["results_ready_us"])
            for row in self.raw_horizons.values()
            if row["scope_id"] == scope
        )
        report = evaluate_factory_cost(
            self.profile,
            calls,
            layout=self.execution.layout,
            factory_id=self.factory_id,
            window=window,
            raw_horizons=horizons,
            scope="full_line_diagnostic"
            if self.experiment_model.mode == "theory"
            else "legacy_raw_excluded_proxy",
        )
        port = (
            self.experiment_model.final_theory_event(parameters)
            if self.experiment_model.mode == "theory"
            else factory_probability_port(self.profile, report)
        )
        self.factory_reports[event_id] = {
            "report": report,
            "port_sha256": port.content_sha256,
            "acceptance_model": self.experiment_model.mode,
            "factory_acceptance_probability": sum(
                outcome.probability
                for outcome in port.outcomes
                if dict(outcome.values).get("accepted") is True
            ),
            "conditional_output_z_error": port.to_dict()["model"]["evidence"].get(
                "conditional_output_z_error"
            ),
        }
        return port

    def preparation_quality_from_event(
        self,
        preparation: str,
        source: Any,
        port: ProbabilityPort,
        values: Mapping[str, Any],
        parameters: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._parameters(parameters)
        if (
            values.get("accepted") is not True
            or port != self._preparation_ports[preparation]
            or self.execution.source(source.invocation_id) != source
            or source.representation != "logical_estimate"
            or source.component_id != preparation
            or dict(values)
            not in [
                dict(outcome.values)
                for outcome in port.outcomes
                if outcome.probability > 0
            ]
        ):
            raise ValueError("FAST_QUALITY_REQUIRES_ACCEPTED_PREPARATION")
        self._scope(source.invocation_id)
        if self.experiment_model.mode == "theory":
            return self.experiment_model.reference_quality(
                preparation, source_port_sha256=port.content_sha256
            )
        return self._quality(port)

    def preparation_quality(
        self, preparation: str, parameters: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        raise ValueError("FAST_QUALITY_REQUIRES_JOINT_EVENT")

    @staticmethod
    def _quality(port: ProbabilityPort) -> dict[str, Any]:
        return _proxy_quality(
            {
                "status": "unsupported",
                "representation": "logical_estimate",
                "logical_success_probability": None,
                "reason": "Calibrated cost event does not establish conditional logical quality",
            },
            port.content_sha256,
        )

    def output_quality(self, factory_port: ProbabilityPort) -> dict[str, Any]:
        if self.experiment_model.mode == "theory":
            if factory_port.content_sha256 not in {
                row["port_sha256"] for row in self.factory_reports.values()
            }:
                raise ValueError("FAST_OUTPUT_REQUIRES_OWN_FACTORY_EVENT")
            return self.experiment_model.output_quality(factory_port)
        if (
            factory_port.port_id != "rotated_surface_d3.factory_15_to_1.cost_proxy"
            or factory_port.to_dict()["model"]["id"]
            != "factory_15_to_1.calibrated_no_fault_proxy.v1"
            or factory_port.outcome("accepted").probability <= 0
            or factory_port.content_sha256
            not in {row["port_sha256"] for row in self.factory_reports.values()}
        ):
            raise ValueError("FAST_OUTPUT_REQUIRES_OWN_FACTORY_PROXY")
        result = self._quality(factory_port)
        result["delivery_assessment"] = "output_X_and_post_decision_wait_not_assessed"
        return result
