"""Run and export one real serial six-patch factory-to-T protocol case.

Use ``python -m modules.logical_compiler.examples.factory_to_t --output NEW_DIR``.
All atom actions and timing come from code-owned components. Coarse protocol
events are selected separately; physical measurement values remain unobserved.
Adversarial scenarios explicitly inject test fixtures, not physical noise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any

from nadit_physical_compiler.visualization.export import write_html

from modules.codes.contracts.component import ComponentBinding
from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.factory_recipe import ResourcePreparation
from modules.codes.rotated_surface_d3.protocols.factory import (
    factory_recipe,
    t_consumption_recipe,
)
from modules.codes.rotated_surface_d3.protocols.factory_backend import (
    SurfaceFactoryBackend,
)
from modules.codes.rotated_surface_d3.protocols.factory_world import (
    FactoryWorld,
    make_factory_world,
)
from modules.logical_compiler.src.protocols.experiment_ledger import build_ledger_record
from modules.logical_compiler.src.protocols.factory import (
    FactoryCase,
    FactoryExecutor,
    FactoryLimits,
)
from modules.logical_compiler.src.protocols.physical import PhysicalContext
from modules.logical_compiler.src.protocols.resources import ResourceError

SCENARIOS = (
    "ideal",
    "startup-retry",
    "rotation-retry",
    "supply-exhaustion",
    "batch-retry",
    "batch-exhaustion",
    "consumption-failure",
    "output-hold",
)
_REJECT_RAW = {
    "startup-retry": frozenset({1}),
    "rotation-retry": frozenset({5}),
    "supply-exhaustion": frozenset({5, 6}),
}
_DEFAULT_SEEDS = {"batch-retry": 2, "batch-exhaustion": 1}


@dataclass
class _ScenarioBackend:
    """Test-only perturbations around a real immutable-template backend.

    Raw ordinals count raw preparation event requests, including retries, from
    zero. All non-rejected joint tables and all physical actions remain real.
    """

    backend: SurfaceFactoryBackend
    scenario: str
    output_carrier: str
    raw_ordinal: int = 0

    def bind_call(
        self,
        component_id: str,
        participant_bindings: tuple[ComponentBinding, ...],
        parameters: tuple[tuple[str, Any], ...] = (),
    ) -> Any:
        if (
            self.scenario == "consumption-failure"
            and component_id == "logical_mz"
            and tuple(binding.block_id for binding in participant_bindings)
            == (self.output_carrier,)
        ):
            raise ValueError(
                "TEST_FIXTURE_CONSUMPTION_FAILURE: "
                "algorithm W1 MZ binding rejected after committed CX"
            )
        return self.backend.bind_call(component_id, participant_bindings, parameters)

    def bind_canonicalization(
        self,
        preparation: str,
        source: Any,
        decision: Any,
        probability_port: ProbabilityPort,
    ) -> Any:
        return self.backend.bind_canonicalization(
            preparation, source, decision, probability_port
        )

    def correction_decision(
        self,
        source: Any,
        *,
        event_id: str,
        probability_port: ProbabilityPort,
        values: Mapping[str, object],
        available_at_us: float,
    ) -> Any:
        return self.backend.correction_decision(
            source,
            event_id=event_id,
            probability_port=probability_port,
            values=values,
            available_at_us=available_at_us,
        )

    def resolve_event(
        self,
        selector: str,
        parameters: Mapping[str, Any] | None = None,
    ) -> ProbabilityPort:
        port = self.backend.resolve_event(selector, parameters)
        if selector != "preparation:raw_t_postselection":
            return port
        ordinal = self.raw_ordinal
        self.raw_ordinal += 1
        if ordinal not in _REJECT_RAW.get(self.scenario, frozenset()):
            return port
        document = port.to_dict()
        document["model"] = {
            "id": "test_fixture.forced_raw_rejection.v1",
            "kind": "test_fixture",
            "assumptions": [
                (
                    "Deterministic control-flow fixture "
                    "with real physical component actions"
                ),
                "Not a physical acceptance or quantum-state probability model",
                "All sixteen accepted byproduct classes are retained at zero mass",
            ],
            "parameters": {"scenario": self.scenario, "raw_ordinal": ordinal},
            "evidence": {"wrapped_ideal_port_sha256": port.content_sha256},
        }
        for outcome in document["outcomes"]:
            outcome["probability"] = 1.0 if outcome["key"] == "rejected" else 0.0
        return ProbabilityPort.from_dict(document)

    def preparation_quality(
        self,
        preparation: str,
        parameters: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.backend.preparation_quality(preparation, parameters)

    def output_quality(self, factory_port: ProbabilityPort) -> dict[str, Any]:
        return self.backend.output_quality(factory_port)


@dataclass(frozen=True)
class ExampleRun:
    """One independent run; the executor is retained for ownership inspection."""

    case: FactoryCase
    executor: FactoryExecutor
    manifest: dict[str, Any]
    output: Path | None


def _source_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[3]
    paths = (
        "modules/logical_compiler/examples/factory_to_t.py",
        "modules/logical_compiler/src/protocols/factory.py",
        "modules/logical_compiler/src/protocols/physical.py",
        "modules/logical_compiler/src/protocols/assembly.py",
        "modules/logical_compiler/src/protocols/events.py",
        "modules/logical_compiler/src/protocols/resources.py",
        "modules/codes/rotated_surface_d3/protocols/factory.py",
        "modules/codes/rotated_surface_d3/protocols/factory_backend.py",
        "modules/codes/rotated_surface_d3/protocols/factory_world.py",
        "modules/codes/rotated_surface_d3/probabilities/factory.py",
    )
    return {
        path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths
    }


def _manifest(
    case: FactoryCase,
    scenario: str,
    input_z_error: float,
    hold_check: dict[str, Any] | None,
) -> dict[str, Any]:
    document = case.to_dict()
    physical = document["physical"]
    calls = document["calls"]
    output_id = document["output_token_id"]
    tokens = document["resources"]["tokens"]
    actions = (
        []
        if case.physical is None
        else [action for step in case.physical.program.steps for action in step.actions]
    )
    models = document["probability_models"]
    return {
        "schema": "nadit.factory_example_manifest/1",
        "scenario": scenario,
        "case_id": document["case_id"],
        "seed": document["seed"],
        "status": document["status"],
        "failure": document["failure"],
        "duration_us": document["duration_us"],
        "code": document["code"],
        "protocol_id": document["recipe"]["protocol_id"],
        "protocol_version": document["recipe"]["version"],
        "execution_mode": "serial",
        "supply_mode": "on_demand",
        "inventory_maintenance": "not_implemented",
        "input_z_error": input_z_error,
        "input_quality_status": "ideal_reference"
        if input_z_error == 0
        else "assumed_reference",
        "scopes": {
            "actions": "Real code-owned components in one continuous 102-atom world",
            "timing": "Actual component action durations and explicit waits",
            "physical_execution": False,
            "physical_measurement_values": "unobserved",
            "full_quantum_simulation": False,
            "global_frame": "not_implemented",
            "preparation_probabilities": (
                "Ideal joint acceptance/byproduct reference "
                "except explicit rejection fixtures"
            ),
            "input_quality": (
                "Independent accepted canonical A Z-error assumption; "
                "not inferred from rejection"
            ),
            "physical_noise": "No calibrated hardware, loss or storage-quality claim",
            "event_fixture": scenario in _REJECT_RAW,
            "physical_failure_fixture": scenario == "consumption-failure",
        },
        "fixture_rejected_raw_ordinals": sorted(_REJECT_RAW.get(scenario, frozenset())),
        "counts": {
            "protocol_calls": len(calls),
            "primitive_component_parts": 0
            if physical is None
            else len(physical["parts"]),
            "atom_steps": 0
            if case.physical is None
            else len(case.physical.program.steps),
            "atom_actions": len(actions),
            "atoms": 0 if case.physical is None else len(case.physical.world.atoms),
            "pending_physical_results": 0
            if case.physical is None
            else len(case.physical.pending_measurements),
            "raw_preparation_attempts": sum(
                call["component_id"] == "raw_t_postselection" for call in calls
            ),
            "raw_resource_tokens": sum(
                token["token_id"] != output_id for token in tokens
            ),
            "factory_cnot_calls": sum(
                call["component_id"] == "transversal_cnot"
                and call["invocation_id"].startswith("factory/")
                for call in calls
            ),
            "algorithm_cnot_calls": sum(
                call["component_id"] == "transversal_cnot"
                and call["invocation_id"].startswith("algorithm/")
                for call in calls
            ),
            "batches_started": sum(
                mark["kind"] == "batch_started" for mark in document["milestones"]
            ),
        },
        "output_token_id": output_id,
        "algorithm_consumed_token_id": document["algorithm_consumed_token_id"],
        "carriers": [
            {key: carrier[key] for key in ("carrier_id", "epoch", "owner", "phase")}
            for carrier in document["resources"]["carriers"]
        ],
        "output_hold_check": hold_check,
        "physical_validation": None if physical is None else physical["validation"],
        "probability_models": [
            {
                "content_sha256": key,
                "model_id": value["model"]["id"],
                "kind": value["model"]["kind"],
            }
            for key, value in models.items()
        ],
        "source_files_sha256": _source_hashes(),
        "files_sha256": {},
    }


def _export(case: FactoryCase, manifest: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    (output / "case.json").write_text(case.to_json(), encoding="utf-8")
    if case.physical is not None:
        bundle = case.physical
        program = bundle.to_dict()["program"]
        (output / "atom-program.json").write_text(
            json.dumps(program, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        (output / "atom-program.txt").write_text(
            bundle.program.to_text(), encoding="utf-8"
        )
        trace = bundle.build_trace(
            title=f"Factory to T: {manifest['scenario']} / {manifest.get('execution_mode', 'serial')} / seed {manifest['seed']}",
            description=(
                "Real selected actions; coarse protocol events; "
                f"physical measurements pending. {manifest.get('execution_mode', 'serial').capitalize()} component scheduling; on-demand supply; "
                "no inventory maintenance."
            ),
        )
        trace["component_schedule"] = case.to_dict().get("component_schedule")
        (output / "trace.json").write_text(
            json.dumps(trace, sort_keys=True, separators=(",", ":"), allow_nan=False),
            encoding="utf-8",
        )
        write_html((trace,), output / "index.html", title="NADiT factory-to-T case")
    manifest["files_sha256"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.iterdir())
        if path.is_file()
    }
    record = build_ledger_record(case.to_dict(), manifest)
    experiment = output / "experiment.json"
    experiment.write_text(
        json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    manifest["files_sha256"][experiment.name] = hashlib.sha256(
        experiment.read_bytes()
    ).hexdigest()
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def run_example(
    scenario: str = "ideal",
    *,
    seed: int | None = None,
    input_z_error: float | None = None,
    output: str | Path | None = None,
    world: FactoryWorld | None = None,
    backend: SurfaceFactoryBackend | None = None,
) -> ExampleRun:
    """Execute one fresh case and optionally export it into a new directory.

    Args:
        scenario: One of SCENARIOS, selecting explicit bounds and test injections.
        seed: Override deterministic defaults; outcome paths may then differ.
        input_z_error: Explicit accepted-input quality assumption; defaults to .01
            for the two batch-rejection examples and zero for other examples.
        output: New directory; an existing path is rejected before execution.
        world: Optional immutable six-patch geometry reused by integration tests.
        backend: Optional same-device template cache; contains no case outcomes.

    Returns:
        Case, runtime executor and manifest. Expected failure scenarios retain
        their validated physical prefixes and explicit terminal failure statuses.

    Raises:
        ValueError: A scenario, parameter or backend/world pairing is invalid.
        FileExistsError: The output path already exists; no files are overwritten.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario {scenario!r}; choose from {SCENARIOS}")
    chosen_seed = _DEFAULT_SEEDS.get(scenario, 0) if seed is None else seed
    if type(chosen_seed) is not int:
        raise ValueError("seed must be an integer")
    p = (
        (0.01 if scenario in _DEFAULT_SEEDS else 0.0)
        if input_z_error is None
        else input_z_error
    )
    if type(p) not in (int, float) or not isfinite(p) or not 0 <= p <= 1:
        raise ValueError("input_z_error must be a finite probability in [0, 1]")
    destination = None if output is None else Path(output).expanduser().resolve()
    if destination is not None and destination.exists():
        raise FileExistsError(f"Output directory must be new: {destination}")
    factory_world = world or make_factory_world()
    real_backend = backend or SurfaceFactoryBackend(factory_world.device)
    if real_backend.device != factory_world.device:
        raise ValueError("backend and world must use the same Device")
    role_bindings = factory_world.bindings
    physical = PhysicalContext(
        factory_world.device, factory_world.world_state, role_bindings.values()
    )
    wrapped = _ScenarioBackend(real_backend, scenario, role_bindings["W1"].block_id)
    executor = FactoryExecutor(
        code="rotated_surface_d3",
        recipe=factory_recipe(),
        backend=wrapped,
        physical=physical,
        role_bindings={
            role: binding.block_id for role, binding in role_bindings.items()
        },
        distance=3,
        case_id=f"factory-to-t-{scenario}",
        seed=chosen_seed,
        limits=FactoryLimits(
            raw_attempts=2 if scenario == "supply-exhaustion" else 3,
            batches=2 if scenario == "batch-retry" else 1,
        ),
        reference_parameters={"input_z_error": float(p)},
    )
    if scenario == "output-hold":
        case = executor.run()
    else:
        case = executor.run(
            algorithm_preparation=ResourcePreparation(
                "data",
                "W2",
                "initialize_plus",
                "preparation:initialize_plus",
                "initialize_plus",
                None,
                "working",
            ),
            algorithm_consumption=t_consumption_recipe(
                "W2", "W1", key="output-consumption"
            ),
        )
    hold_check = None
    if scenario == "output-hold" and case.status == "complete":
        before = executor.ledger.snapshot()
        try:
            executor.ledger.begin_preparation(
                role_bindings["W1"].block_id,
                owner="forbidden-reset-probe",
                at_us=physical.clock_us,
            )
        except ResourceError as error:
            hold_check = {
                "reset_rejected": True,
                "reason": str(error),
                "ledger_unchanged": executor.ledger.snapshot() == before,
            }
        else:
            raise RuntimeError(
                "OUTPUT_HOLD_VIOLATION: ledger allowed resetting a protected output"
            )
    manifest = _manifest(case, scenario, float(p), hold_check)
    if destination is not None:
        _export(case, manifest, destination)
    return ExampleRun(case, executor, manifest, destination)


def main(argv: list[str] | None = None) -> int:
    """Run the explicit example CLI and print a compact outcome summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New output directory; existing paths are refused",
    )
    parser.add_argument("--scenario", choices=SCENARIOS, default="ideal")
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--input-z-error",
        type=float,
        help="Assumed independent accepted-input Z-error probability",
    )
    arguments = parser.parse_args(argv)
    run = run_example(
        arguments.scenario,
        seed=arguments.seed,
        input_z_error=arguments.input_z_error,
        output=arguments.output,
    )
    print(
        json.dumps(
            {
                key: run.manifest[key]
                for key in (
                    "scenario",
                    "case_id",
                    "seed",
                    "status",
                    "duration_us",
                    "counts",
                )
            },
            indent=2,
        )
    )
    print(f"Artifacts: {run.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
