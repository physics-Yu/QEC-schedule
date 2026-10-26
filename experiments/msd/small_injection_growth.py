"""Reproduce fixed-d3 injection acceptance and conditional growth resource costs."""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nadit_physical_compiler.cost import evaluate
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.state import AtomLayout

from modules.codes._support.raw_t_sequence import joint_raw_t_document
from modules.codes.contracts.component import (
    ComponentExpansion,
    InvocationContext,
    MeasurementOutput,
    validate_sequence,
)
from modules.codes.rotated_surface import RawTPostselection, definition, get_component
from modules.codes.rotated_surface.components import SurfaceComponent
from modules.codes.rotated_surface.growth import GrowthComponent
from modules.codes.rotated_surface.probabilities.raw_t import _joint_document

from .calibrate import source_snapshot, summarize
from .standard import ExperimentSpec, build_world


@dataclass(frozen=True)
class ReferenceTimeline:
    """Unobserved conditional-branch cost reference, never a runtime acceptance."""

    parts: tuple[ComponentExpansion, ...]

    @property
    def measurements(self) -> tuple[MeasurementOutput, ...]:
        """Return unobserved outputs used only for structural serialization."""
        return tuple(m for p in self.parts for m in p.measurements)

    @property
    def exit_state(self) -> AtomLayout:
        """Return the reference branch's complete world."""
        return self.parts[-1].exit_state


def _write(path: Path, data: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")


def run_case(
    distance: int, plan: dict[str, Any], noise: dict[str, Any], output: Path
) -> dict[str, Any]:
    """Validate actual trajectories; do not sample or fabricate an accepted event."""
    world = build_world(ExperimentSpec(distance=distance, pipelines=plan["pipelines"]))
    patch = world.patch(plan["factory_index"], plan["patch_role"])
    protocol = RawTPostselection(distance, injection_rounds=plan["injection_rounds"])
    template = protocol.compile(
        world.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
    )
    stage = template.bind(patch.binding).expand(
        InvocationContext(f"d{distance}/seed", 0, 0, world.device, world.state)
    )
    injection = _joint_document(stage.sequence, world.device, distance=3)
    _write(output / f"d{distance}.world.json", world.document())
    _write(output / f"d{distance}.injection.result.json", injection)
    im = summarize(injection)
    ports: dict[str, dict[str, Any]] = {}
    for name, params in (
        ("zero", {}),
        ("readout", {"readout_flip": 0.001}),
        ("illustrative", noise),
    ):
        port = protocol.acceptance_port(
            stage, world.device, noise_params=params, method="exact"
        )
        protocol.validate_acceptance_port(port, template, noise_params=params)
        _write(output / f"d{distance}.{name}.port.json", port.to_dict())
        ports[name] = {
            "acceptance": port.outcome("accepted").probability,
            "content_sha256": port.content_sha256,
        }
    r = plan["injection_rounds"]
    analytic = 0.999 ** (4 * r) * (0.999**r + 0.001**r) ** 4
    if (
        abs(ports["readout"]["acceptance"] - analytic) > 1e-10
        or ports["zero"]["acceptance"] != 1
    ):
        raise ValueError("Independent small-patch acceptance checks failed.")
    growth_metrics = None
    growth_sources: tuple[str, ...] = ()
    if distance > 3:
        # Compile the continuation as a cost reference. No fabricated received
        # bits are passed to the runtime grow() gate, and no state is delivered.
        parts = []
        start, state, base = (
            stage.sequence.results_ready_us,
            stage.sequence.exit_state,
            len(stage.sequence.measurements),
        )
        for r in range(protocol.growth_rounds):
            component = template.growth if r == 0 else template.se_round
            assert component is not None
            part = component.bind(patch.binding).expand(
                InvocationContext(
                    f"d{distance}/growth-reference[{r}]",
                    start,
                    base,
                    world.device,
                    state,
                )
            )
            parts.append(part)
            start, state, base = (
                part.action_end_us,
                part.exit_state,
                base + len(part.measurements),
            )
        validate_sequence((*stage.sequence.parts, *parts))
        growth_sources = (
            GrowthComponent(distance).source_qasm,
            *(
                SurfaceComponent("se_round", distance).source_qasm
                for _ in range(protocol.growth_rounds - 1)
            ),
        )
        growth = joint_raw_t_document(
            ReferenceTimeline(tuple(parts)),
            world.device,
            sources=growth_sources,
            participant_count=definition(distance).atom_count,
            measurements_per_round=definition(distance).check_count,
        )
        _write(output / f"d{distance}.growth.result.json", growth)
        growth_metrics = summarize(growth)
        _write(
            output / f"d{distance}.growth.noise.json",
            evaluate(growth, model="noise/v1", params=noise),
        )
    raw = get_component("raw_t", distance)
    raw_template = raw.compile(
        world.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
    )
    raw_part = raw_template.bind(patch.binding).expand(
        InvocationContext(f"d{distance}/raw-reference", 0, 0, world.device, world.state)
    )
    raw_document = joint_raw_t_document(
        ReferenceTimeline((raw_part,)),
        world.device,
        sources=(raw.source_qasm,),
        participant_count=definition(distance).atom_count,
        measurements_per_round=len(raw_part.measurements),
    )
    _write(output / f"d{distance}.raw.result.json", raw_document)
    p = ports["illustrative"]["acceptance"]
    additive = (
        "execution_duration_us",
        "atom_time_us",
        "atom_idle_us",
        "atom_busy_us",
        "movement_distance_atom_um",
        "transport_elapsed_us",
    )
    expected = {
        key: im[key] / p + (0 if growth_metrics is None else growth_metrics[key])
        for key in additive
    }
    return {
        "distance": distance,
        "protocol": protocol.identity,
        "preparation_sha256": template.content_sha256,
        "injection_active_atoms": 17,
        "target_atoms": definition(distance).atom_count,
        "world_atoms": len(world.state.atoms),
        "injection_detectors": len(stage.sequence.detectors),
        "probabilities": ports,
        "injection_metrics": im,
        "growth_metrics": growth_metrics,
        "raw_unpostselected_metrics": summarize(raw_document),
        "expected_per_output": expected,
        "expected_time_formula": "injection_time / injection_acceptance + growth_time",
        "conditional_output_rate_per_s": 1e6 / expected["execution_duration_us"],
        "expected_injection_attempts": 1 / p,
        "growth_quality_estimated": False,
        "output_frame": "caller must decode and retain/apply",
        "branch_evidence": "unobserved physical cost references; no sampled acceptance or hardware execution",
        "growth_source_sha256": canonical_hash({"sources": list(growth_sources)}),
    }


def main() -> None:
    """Run a frozen plan into a new artifact directory and check source stability."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan",
        type=Path,
        default=Path(__file__).with_name("small_injection_growth_plan.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if plan["schema"] != "nadit.msd.small_injection_growth_plan/1":
        raise ValueError("Unsupported growth experiment plan.")
    noise = json.loads(Path(plan["noise_params"]).read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=False)
    snapshot = source_snapshot()
    _write(args.output / "plan.json", plan)
    _write(args.output / "noise.json", noise)
    rows = []
    for distance in plan["distances"]:
        if (
            6 * plan["pipelines"] * definition(distance).atom_count
            > plan["max_world_atoms"]
        ):
            raise ValueError("Experiment exceeds the frozen world atom budget.")
        row = run_case(distance, plan, noise, args.output)
        rows.append(row)
        _write(args.output / f"d{distance}.summary.json", row)
        print(
            json.dumps(
                {
                    "d": distance,
                    "acceptance": row["probabilities"]["illustrative"]["acceptance"],
                    "expected_us": row["expected_per_output"]["execution_duration_us"],
                }
            ),
            flush=True,
        )
    if snapshot != source_snapshot():
        raise ValueError("Runtime sources changed during this experiment.")
    _write(
        args.output / "summary.json",
        {
            "schema": "nadit.msd.small_injection_growth/1",
            "plan": plan,
            "source_tree_sha256": canonical_hash(snapshot),
            "noise_sha256": canonical_hash(noise),
            "cases": rows,
        },
    )


if __name__ == "__main__":
    main()
