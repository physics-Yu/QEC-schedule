"""Produce every supported surface component in the current MSD device world."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.contracts.component import InvocationContext, validate_sequence
from modules.codes.rotated_surface.catalog import COMPONENT_NAMES, get_protocol
from modules.codes.rotated_surface.staged_raw_t import RawTPostselection
from modules.codes.rotated_surface.transversal import TransversalCNOTComponent

from .calibrate import source_snapshot
from .component_export import export_component, export_sequence_viewer, write_json
from .standard import STANDARD_ID, ExperimentSpec, build_world


def build_distance(
    distance: int,
    output: Path,
    *,
    operations: tuple[str, ...] = COMPONENT_NAMES,
    noise_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile every requested operation, preserving physical and stage semantics.

    Raw postselection exports separate injection and conditional growth parts.
    Its finite binary acceptance port is calculated only when explicit noise is
    supplied. Other operations are independent component calls, not a factory run.
    """
    if (
        not operations
        or len(set(operations)) != len(operations)
        or set(operations) - set(COMPONENT_NAMES)
    ):
        raise ValueError("Select distinct supported component names.")
    world = build_world(ExperimentSpec(distance=distance))
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "world.json", world.document())
    patch = world.patch(0, "R")
    rows = {}
    for name in operations:
        component = get_protocol(name, distance)
        context = InvocationContext(
            f"d{distance}/{name}", 0, 0, world.device, world.state
        )
        if isinstance(component, RawTPostselection):
            template = component.compile(
                world.device,
                home_sites=patch.home_sites,
                origin=patch.binding.origin,
                aod_id=patch.binding.aod_id,
            )
            bound = template.bind(patch.binding)
            stage = bound.expand(context)
            directory = output / name
            directory.mkdir()
            parts = list(stage.sequence.parts)
            stage_metrics = []
            for r, part in enumerate(parts):
                seed_template = (
                    template.injection.raw_t if r == 0 else template.injection.se_round
                )
                stage_metrics.append(
                    export_component(
                        seed_template, part, world.device, directory / f"injection-{r}"
                    )
                )
            start, state, base = (
                stage.sequence.results_ready_us,
                stage.sequence.exit_state,
                len(stage.sequence.measurements),
            )
            for r in range(component.growth_rounds):
                selected = template.growth if r == 0 else template.se_round
                assert selected is not None
                part = selected.bind(patch.binding).expand(
                    InvocationContext(
                        f"{context.invocation_id}/conditional-growth[{r}]",
                        start,
                        base,
                        world.device,
                        state,
                    )
                )
                stage_metrics.append(
                    export_component(
                        selected, part, world.device, directory / f"growth-{r}"
                    )
                )
                parts.append(part)
                start, state, base = (
                    part.action_end_us,
                    part.exit_state,
                    base + len(part.measurements),
                )
            validate_sequence(parts)
            export_sequence_viewer(
                tuple(parts),
                world.device,
                directory / "index.html",
                title=f"d{distance} conditional raw-T postselection and growth",
            )
            acceptance = None
            if noise_params is not None:
                port = component.acceptance_port(
                    stage, world.device, noise_params=noise_params, method="exact"
                )
                component.validate_acceptance_port(
                    port, template, noise_params=noise_params
                )
                write_json(directory / "acceptance.port.json", port.to_dict())
                acceptance = port.outcome("accepted").probability
            row = {
                "protocol": component.identity,
                "template_sha256": template.content_sha256,
                "injection_duration_us": stage.sequence.results_ready_us,
                "growth_duration_us": parts[-1].results_ready_us
                - stage.sequence.results_ready_us,
                "conditional_path_duration_us": parts[-1].results_ready_us,
                "acceptance_probability": acceptance,
                "measurement_count": sum(len(p.measurements) for p in parts),
                "injection_detectors": len(stage.sequence.detectors),
                "stages": stage_metrics,
                "execution_scope": "unobserved conditional cost reference; grow requires an accepted runtime event",
                "quality_estimated": False,
            }
            write_json(directory / "protocol.json", row)
        else:
            if isinstance(component, TransversalCNOTComponent):
                control, target = world.patch(0, "W1"), world.patch(0, "W2")
                joint = component.compile(
                    world.device,
                    control_home_sites=control.home_sites,
                    target_home_sites=target.home_sites,
                    control_origin=control.binding.origin,
                    target_origin=target.binding.origin,
                    aod_id=control.binding.aod_id,
                )
                atomic = joint.atomic
                expansion = joint.bind(control.binding, target.binding).expand(context)
            else:
                atomic = component.compile(
                    world.device,
                    home_sites=patch.home_sites,
                    origin=patch.binding.origin,
                    aod_id=patch.binding.aod_id,
                )
                expansion = atomic.bind(patch.binding).expand(context)
            row = export_component(atomic, expansion, world.device, output / name)
        rows[name] = row
        print(
            json.dumps(
                {
                    "distance": distance,
                    "component": name,
                    "status": "validated_exported",
                }
            ),
            flush=True,
        )
    manifest = {
        "schema": "nadit.surface_component_bundle/1",
        "standard": STANDARD_ID,
        "distance": distance,
        "world_atoms": len(world.state.atoms),
        "parameters": asdict(world.spec),
        "operations": rows,
        "physical_execution": False,
        "measurement_evidence": "unobserved",
        "factory_backend_implemented": False,
    }
    write_json(output / "manifest.json", manifest)
    links = "\n".join(
        f'<li><a href="{name}/index.html">{name}</a></li>' for name in operations
    )
    (output / "index.html").write_text(
        f'<!doctype html><meta charset="utf-8"><title>d{distance} components</title><h1>d{distance} surface components</h1><p>MSD standard/2, 10 us transfers. Unobserved physical action traces; no logical-error or factory-execution claim.</p><ul>{links}</ul>',
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    """Produce d9/d11 by default, with explicit distance and output selection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distances", type=int, nargs="+", default=[9, 11])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--noise",
        type=Path,
        default=Path("modules/physical_compiler/cost_params/noise_illustrative.json"),
    )
    args = parser.parse_args()
    if len(set(args.distances)) != len(args.distances) or any(
        d < 5 or d % 2 == 0 for d in args.distances
    ):
        parser.error("Choose distinct odd target distances >= 5.")
    args.output.mkdir(parents=True, exist_ok=False)
    snapshot = source_snapshot()
    noise = json.loads(args.noise.read_text(encoding="utf-8"))
    write_json(args.output / "source-snapshot.json", snapshot)
    write_json(args.output / "noise.json", noise)
    manifests = [
        build_distance(d, args.output / f"d{d}", noise_params=noise)
        for d in args.distances
    ]
    if snapshot != source_snapshot():
        raise ValueError("Runtime sources changed during component production.")
    write_json(
        args.output / "manifest.json",
        {
            "schema": "nadit.surface_component_production/1",
            "standard": STANDARD_ID,
            "source_tree_sha256": canonical_hash(snapshot),
            "noise_sha256": canonical_hash(noise),
            "cases": manifests,
        },
    )


if __name__ == "__main__":
    main()
