"""Reproduce historical direct-injection raw-T acceptance on admitted physical traces."""

import argparse
import json
from dataclasses import asdict
from hashlib import sha256
from math import sqrt
from pathlib import Path
from time import perf_counter
from typing import Any

from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.contracts.component import InvocationContext
from modules.codes.rotated_surface import DirectRawTPostselection as RawTPostselection
from modules.codes.rotated_surface import definition
from modules.codes.rotated_surface.components import SurfaceComponent
from modules.codes.rotated_surface.probabilities.raw_t import _joint_document

from .calibrate import source_snapshot, summarize
from .standard import STANDARD_ID, ExperimentSpec, build_world

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN = Path(__file__).with_name("raw_t_acceptance_plan.json")


def _write(path: Path, data: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")


def run_case(
    distance: int,
    plan: dict[str, Any],
    noise: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    """Compile once, then evaluate three explicit noise controls on that trace."""
    spec = ExperimentSpec(distance=distance, pipelines=plan["pipelines"])
    if 6 * spec.pipelines * definition(distance).atom_count > plan["max_world_atoms"]:
        raise ValueError("Requested world exceeds the frozen atom budget.")
    world = build_world(spec)
    patch = world.patch(plan["factory_index"], plan["patch_role"])
    if plan.get("schema") != "nadit.msd.raw_t_acceptance_plan/2":
        raise ValueError("Use a version-2 plan with an explicit round policy.")
    protocol = RawTPostselection(
        distance,
        extra_rounds=plan.get("extra_rounds"),
        round_policy=plan["round_policy"],
    )
    started = perf_counter()
    template = protocol.compile(
        world.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
    )
    sequence = template.bind(patch.binding).expand(
        InvocationContext(f"raw-d{distance}", 0, 0, world.device, world.state)
    )
    compile_wall_s = perf_counter() - started
    # This admission repeats semantic validation and preserves real inter-round
    # idle time and the whole occupied world, including spectators.
    document = _joint_document(sequence, world.device, distance=distance)
    _write(output / f"d{distance}.result.json", document)
    _write(output / f"d{distance}.world.json", world.document())
    b = len(SurfaceComponent("raw_t", distance).acceptance_ports)
    m = definition(distance).check_count
    rounds = 1 + protocol.extra_rounds
    p = plan["readout_control_flip"]
    readout_reference = (1 - p) ** (rounds * b) * ((1 - p) ** rounds + p**rounds) ** (
        m - b
    )
    controls = {
        "zero_noise": {},
        "readout_only": {"readout_flip": p},
        "illustrative": noise,
    }
    estimates = {}
    for name, params in controls.items():
        started = perf_counter()
        port = protocol.acceptance_port(
            sequence, world.device, noise_params=params, **plan["estimator"]
        )
        wall = perf_counter() - started
        data = port.to_dict()
        _write(output / f"d{distance}.{name}.port.json", data)
        probability = port.outcome("accepted").probability
        evidence = data["model"]["evidence"]
        reference = {"zero_noise": 1.0, "readout_only": readout_reference}.get(name)
        estimate = evidence["estimator"]
        if reference is not None:
            tolerance = (
                1e-10
                if data["model"]["kind"] == "pauli_exact"
                else max(
                    1e-10, 6 * sqrt(reference * (1 - reference) / estimate["shots"])
                )
            )
            if abs(probability - reference) > tolerance:
                raise ValueError(
                    f"d={distance} {name} fails independent analytic check."
                )
        estimates[name] = {
            "probability": probability,
            "model_kind": data["model"]["kind"],
            "estimator": estimate,
            "analytic_reference": reference,
            "analytic_residual": None if reference is None else probability - reference,
            "analysis_wall_s": wall,
            "port_content_sha256": port.content_sha256,
            "noise_params_hash": evidence["noise_params_hash"],
            "channel_signatures_sha256": evidence["channel_signatures_sha256"],
            "physical_loss": {
                "all_atoms_survive_probability": evidence["physical_loss"][
                    "all_atoms_survive_probability"
                ],
                "event_count": len(evidence["physical_loss"]["events"]),
                "complete_evidence": f"d{distance}.{name}.port.json",
            },
            "logical_error_probability": None,
        }
    physical_metrics = summarize(document)
    return {
        "distance": distance,
        "parameters": asdict(spec),
        "factory_index": plan["factory_index"],
        "patch_role": plan["patch_role"],
        "total_rounds": rounds,
        "extra_rounds": protocol.extra_rounds,
        "round_policy": plan["round_policy"],
        "first_deterministic_checks": b,
        "first_random_checks": m - b,
        "checks_per_round": m,
        "detector_count": len(sequence.detectors),
        "measurement_count": len(sequence.measurements),
        "compile_wall_s": compile_wall_s,
        "physical_metrics": physical_metrics,
        "raw_resources": accepted_resources(
            physical_metrics,
            definition(distance).atom_count,
            estimates["illustrative"]["probability"],
            estimates["illustrative"]["estimator"]["ci95"],
        ),
        "result_sha256": canonical_hash(document),
        "template_content_sha256": sequence.template_content_sha256,
        "raw_primitive_source_sha256": sha256(
            SurfaceComponent("raw_t", distance).source_qasm.encode()
        ).hexdigest(),
        "raw_primitive_template_sha256": sequence.parts[0].template_content_sha256,
        "estimates": estimates,
    }


def accepted_resources(
    metrics: dict[str, Any],
    participants: int,
    probability: float,
    ci95: list[float] | None,
) -> dict[str, Any]:
    """Convert one fixed attempt's resources to independent-repeat expectations.

    Raw preparation resets its participants and ends at the same homes. This
    accounting includes those operations, but excludes canonicalization, resource
    arbitration, and downstream factory work. It is not factory throughput.
    """
    duration = metrics["execution_duration_us"]
    costs = {
        "time_us": duration,
        "participant_atom_time_us": participants * duration,
        "whole_world_atom_time_us": metrics["atom_time_us"],
        "movement_atom_um": metrics["movement_distance_atom_um"],
        "transport_elapsed_us": metrics["transport_elapsed_us"],
        "whole_world_idle_atom_us": metrics["atom_idle_us"],
    }
    interval = ci95 if ci95 is not None else [probability, probability]
    return {
        "participant_atoms": participants,
        "whole_world_atoms": metrics["atom_count"],
        "per_attempt": costs,
        "expected_attempts_per_accepted": 1 / probability if probability else None,
        "expected_per_accepted": {
            key: value / probability if probability else None
            for key, value in costs.items()
        },
        "expected_per_accepted_ci95": {
            key: [
                value / interval[1] if interval[1] else None,
                value / interval[0] if interval[0] else None,
            ]
            for key, value in costs.items()
        },
        "scope": "Identical independent raw postselection attempts only",
        "canonicalization_included": False,
        "physical_loss_counted_as_rejection": False,
        "factory_throughput_estimated": False,
    }


def plot(summary: dict[str, Any], output: Path) -> None:
    """Plot saved acceptance with statistical error bars and explicit controls."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cases = summary["cases"]
    ds = [case["distance"] for case in cases]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), constrained_layout=True)
    for control, label in (
        ("zero_noise", "Explicit zero noise"),
        ("readout_only", "Readout flip only"),
        ("illustrative", "Illustrative full profile"),
    ):
        values = [case["estimates"][control]["probability"] for case in cases]
        cis = [case["estimates"][control]["estimator"]["ci95"] for case in cases]
        low = [
            0 if ci is None else value - ci[0]
            for ci, value in zip(cis, values, strict=True)
        ]
        high = [
            0 if ci is None else ci[1] - value
            for ci, value in zip(cis, values, strict=True)
        ]
        axes[0].errorbar(
            ds, values, yerr=[low, high], marker="o", capsize=4, label=label
        )
    axes[0].set(
        xlabel="Code distance d", ylabel="Detector acceptance probability", xticks=ds
    )
    axes[0].legend(fontsize=8)
    axes[1].plot(
        ds,
        [case["physical_metrics"]["execution_duration_us"] / 1000 for case in cases],
        "o-",
    )
    axes[1].set(
        xlabel="Code distance d", ylabel="Raw attempt + SE time (ms)", xticks=ds
    )
    for ax in axes:
        ax.grid(alpha=0.25)
    policy = summary["plan"]["round_policy"]
    fig.suptitle(
        f"Raw-T postselection, round policy={policy} (N=1, W1)\n"
        "95% MC intervals; illustrative noise, no logical-fidelity claim"
    )
    fig.savefig(output / "raw-t-distance-acceptance.png", dpi=180)
    plt.close(fig)


def main() -> None:
    """Run the frozen bounded experiment and retain ports, traces and provenance."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plot-only", action="store_true")
    args = parser.parse_args()
    if args.plot_only:
        plot(
            json.loads((args.output / "summary.json").read_text(encoding="utf-8")),
            args.output,
        )
        return
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    profile_path = ROOT / plan["noise_profile"]
    profile_bytes = profile_path.read_bytes()
    noise = json.loads(profile_bytes)
    args.output.mkdir(parents=True, exist_ok=False)
    sources = source_snapshot()
    manifest = {
        "schema": "nadit.msd.raw_t_acceptance/2",
        "standard": STANDARD_ID,
        "plan": plan,
        "plan_sha256": canonical_hash(plan),
        "source_fingerprints": sources,
        "source_sha256": canonical_hash(sources),
        "noise_profile_sha256": sha256(profile_bytes).hexdigest(),
        "noise_profile": noise,
        "physical_execution": False,
        "accepted_state_quality_estimated": False,
    }
    _write(args.output / "manifest.json", manifest)
    cases = []
    for distance in plan["distances"]:
        case = run_case(distance, plan, noise, args.output)
        if source_snapshot() != sources or profile_path.read_bytes() != profile_bytes:
            raise ValueError("Sources/noise changed during the frozen experiment.")
        _write(args.output / f"d{distance}.summary.json", case)
        cases.append(case)
        print(
            json.dumps(
                {
                    "distance": distance,
                    "status": "complete",
                    "acceptance": case["estimates"]["illustrative"]["probability"],
                }
            ),
            flush=True,
        )
    summary = {**manifest, "cases": cases}
    _write(args.output / "summary.json", summary)
    plot(summary, args.output)


if __name__ == "__main__":
    main()
