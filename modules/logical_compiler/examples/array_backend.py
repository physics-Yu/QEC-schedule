"""Separate factory reference checks from costs in the actual shared timeline."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.contracts.component import ComponentExpansion
from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
    FactoryExperimentModel,
)
from modules.logical_compiler.examples.factory_noise import CostNoiseBackend
from modules.logical_compiler.examples.factory_proxy import (
    _included_intervals,
    _raw_union,
    _scope_evidence,
)
from modules.logical_compiler.src.protocols.participant_cost import (
    evaluate_participant_cost,
)
from modules.logical_compiler.src.protocols.physical import PhysicalContext


class ArrayCostBackend(CostNoiseBackend):
    """Preserve raw feedback and apply the explicitly selected final-check model."""

    def __init__(
        self,
        backend: Any,
        output_carrier: str,
        physical: PhysicalContext,
        *,
        factory_id: str,
        atom_ids: tuple[int, ...],
        experiment_model: FactoryExperimentModel,
    ) -> None:
        super().__init__(backend, output_carrier)
        self.proxy_backend: Any = backend
        self.experiment_model = experiment_model
        if not factory_id or not atom_ids or len(set(atom_ids)) != len(atom_ids):
            raise ValueError(
                "INVALID_FACTORY_OWNER: identity and distinct atoms required"
            )
        self.factory_id, self.atom_ids, self.physical = (
            factory_id,
            tuple(sorted(atom_ids)),
            physical,
        )
        self._batch = re.compile(r"^" + re.escape(factory_id) + r"/batch\[\d+\]/")
        self.raw_horizons: dict[str, dict[str, Any]] = {}
        self.factory_reports: dict[str, dict[str, Any]] = {}

    def _event_parameters(
        self, preparation: str, parameters: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        if preparation != "raw_t_postselection":
            return {}
        return self.experiment_model.raw_preparation_parameters(parameters)

    def preparation_quality_from_event(
        self,
        preparation: str,
        source: Any,
        port: ProbabilityPort,
        values: Mapping[str, Any],
        parameters: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Keep an assumed accepted-input quality distinct from raw detector cost."""
        actual = super().preparation_quality_from_event(
            preparation,
            source,
            port,
            values,
            self._event_parameters(preparation, parameters),
        )
        if self.experiment_model.mode == "physical_no_fault_proxy":
            return actual
        byproduct = values.get("byproduct_class")
        if (
            values.get("accepted") is not True
            or type(byproduct) is not int
            or not 0 <= byproduct < 16
        ):
            raise ValueError("ACCEPTED_RAW_REFERENCE_REQUIRES_CANONICAL_BRANCH")
        quality = self.experiment_model.reference_quality(
            preparation, source_port_sha256=port.content_sha256
        )
        quality["raw_conditional_physical_quality"] = actual.get(
            "actual_quality", actual
        )
        return quality

    def resolve_event(
        self, selector: str, parameters: Mapping[str, Any] | None = None
    ) -> ProbabilityPort:
        """Route consumption through the selected model; final checks require scope."""
        if selector == "t_consumption":
            return self.experiment_model.consumption_event(parameters)
        if selector in ("factory_mx", "factory_cost_proxy"):
            raise ValueError("FACTORY_EVENT_REQUIRES_READY_SOURCES")
        return super().resolve_event(selector, parameters)

    def output_quality(self, factory_port: ProbabilityPort) -> dict[str, Any]:
        """Return conditional reference output quality only for a theoretical check."""
        if self.experiment_model.mode == "theory":
            return self.experiment_model.output_quality(factory_port)
        return super().output_quality(factory_port)

    def _scope(self, invocation_id: str) -> str:
        match = self._batch.match(invocation_id)
        if match is None:
            raise ValueError(f"INVALID_FACTORY_SCOPE: {invocation_id}")
        return match.group(0).removesuffix("/")

    def describe_execution(
        self,
        component_id: str,
        participant_bindings: tuple[Any, ...],
        parameters: tuple[tuple[str, Any], ...] = (),
    ) -> Any:
        """Return code-owned claims without binding or physical expansion."""
        return self.backend.describe_execution(
            component_id, participant_bindings, parameters
        )

    def preparation_event(
        self,
        preparation: str,
        source: Any,
        parameters: Mapping[str, Any] | None = None,
    ) -> ProbabilityPort:
        """Attach shared execution evidence and remember only this line's raw horizons."""
        batch = None
        if preparation == "raw_t_postselection":
            first = source.parts[0]
            scope = self._scope(first.invocation_id)
            batch = self.physical.batch_for(first.invocation_id)
            if batch is not None:
                self.proxy_backend.register_parallel_source(
                    source,
                    program=batch.program,
                    entry_world=batch.entry_world,
                    evidence=batch.to_dict(),
                )
        port = super().preparation_event(
            preparation, source, self._event_parameters(preparation, parameters)
        )
        if preparation == "raw_t_postselection":
            record = {
                "factory_id": self.factory_id,
                "scope_id": scope,
                "source_invocation": first.invocation_id,
                "part_invocations": [part.invocation_id for part in source.parts],
                "start_us": first.start_us,
                "results_ready_us": source.results_ready_us,
                "port_sha256": port.content_sha256,
                "parallel_batch_id": None if batch is None else batch.batch_id,
            }
            previous = self.raw_horizons.get(first.invocation_id)
            if previous is not None and previous != record:
                raise ValueError("RAW_HORIZON_BINDING_CHANGED")
            self.raw_horizons[first.invocation_id] = record
        return port

    def resolve_event_from_sources(
        self,
        selector: str,
        parts: tuple[ComponentExpansion, ...],
        parameters: Mapping[str, Any],
        *,
        event_id: str,
    ) -> ProbabilityPort:
        """Evaluate a ready joint check and separately record this line's costs."""
        if selector not in ("factory_mx", "factory_cost_proxy"):
            return self.resolve_event(selector, parameters)
        theory = self.experiment_model.mode == "theory"
        expected = "factory_mx" if theory else "factory_cost_proxy"
        if selector != expected:
            raise ValueError("FACTORY_MODEL_SELECTOR_MISMATCH")
        scope = self._scope(event_id)
        if not parts or any(
            part.results_ready_us > self.physical.clock_us for part in parts
        ):
            raise ValueError("FACTORY_PROXY_BEFORE_RESULTS_READY")
        for part in parts:
            if not part.invocation_id.startswith(scope + "/"):
                raise ValueError("FACTORY_CHECK_SOURCE_SCOPE_MISMATCH")
            try:
                committed = self.physical.source(part.invocation_id)
            except KeyError as error:
                raise ValueError("FACTORY_CHECK_SOURCE_NOT_COMMITTED") from error
            if committed is not part:
                raise ValueError("FACTORY_CHECK_SOURCE_NOT_COMMITTED")
        invocations = [
            item
            for item in self.physical.invocations
            if item.invocation_id.startswith(scope + "/")
        ]
        if not invocations:
            raise ValueError("FACTORY_PROXY_WITHOUT_PHYSICAL_BATCH")
        start, end = min(item.start_us for item in invocations), self.physical.clock_us
        horizons = tuple(
            (item["start_us"], item["results_ready_us"])
            for item in self.raw_horizons.values()
            if item["scope_id"] == scope
        )
        excluded = () if theory else _raw_union(start, end, horizons)
        report = evaluate_participant_cost(
            self.physical.finalize(),
            parameters["noise_params"],
            participant_atom_ids=self.atom_ids,
            include_intervals=((start, end),)
            if theory
            else _included_intervals(start, end, excluded),
            owner_id=self.factory_id,
        )
        evidence = _scope_evidence(
            report,
            scope_id=event_id,
            stage="factory",
            window=(start, end),
            excluded=excluded,
        )
        evidence.update(
            factory_id=self.factory_id,
            participant_selection=report["participant_selection"],
            raw_attempt_intervals_us=[list(pair) for pair in horizons],
            raw_exclusion_semantics="none; all line carriers retained"
            if theory
            else "own_line_atoms_during_own_raw_horizon_union",
            peer_wait_exposure="included_throughout_final_check_window"
            if theory
            else "included_outside_this_line_raw_horizons",
            cost_scope="full_line_diagnostic" if theory else "legacy_nonraw_proxy",
            controls_factory_acceptance=not theory,
            coverage={
                "participant_atom_count": len(self.atom_ids),
                "all_carriers_full_window": theory,
                "raw_actions_included": theory,
                "raw_physical_loss_included": theory,
                "other_patch_wait_during_raw_included": theory,
                "included_atom_time_us": len(self.atom_ids)
                * sum(
                    b - a for a, b in report["interval_selection"]["include_intervals"]
                ),
                "later_output_correction_and_storage_included": False,
                "legacy_coverage_gap": None
                if theory
                else (
                    "Raw intervals omit raw loss and other-carrier waiting; this is not a complete physical-cost diagnostic"
                ),
            },
        )
        port: ProbabilityPort = (
            self.experiment_model.final_theory_event(parameters)
            if theory
            else self.proxy_backend.factory_proxy_event(report, evidence)
        )
        self.factory_reports[event_id] = {
            "report": report,
            "report_content_sha256": canonical_hash(report),
            "scope_evidence": evidence,
            "port_sha256": port.content_sha256,
            "controls_factory_acceptance": not theory,
            "purpose": "physical_no_fault_cost_diagnostic"
            if theory
            else "legacy_physical_no_fault_acceptance_proxy",
        }
        return port
