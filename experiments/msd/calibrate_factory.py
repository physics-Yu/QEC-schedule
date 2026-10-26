"""Explicit physical calibration for the generic fast factory; never a fast fallback."""

import json
from collections import Counter
from dataclasses import replace
from math import hypot
from pathlib import Path
from time import perf_counter
from typing import Any

from nadit_physical_compiler.atom_ir import Load, Measure, Move
from nadit_physical_compiler.provenance import canonical_hash

from modules.codes._support.atom_template import (
    AtomComponentTemplate,
    BindingRejected,
    compile_template,
)
from modules.codes.contracts.component import (
    ComponentBinding,
    ComponentDescription,
    ComponentExpansion,
    InvocationContext,
    validate_sequence,
)
from modules.codes.rotated_surface import (
    RawTPostselection,
    TransversalCNOTComponent,
    definition,
    get_component,
)
from modules.codes.rotated_surface.fast_factory import (
    ROLES,
    SCHEMA,
    SurfaceFactoryProfile,
    entry_key,
    required_variants,
)

from .calibrate import source_snapshot
from .standard import STANDARD_ID, ExperimentSpec, build_world


def summarize_parts(
    component: str, parts: tuple[ComponentExpansion, ...]
) -> dict[str, Any]:
    """Preserve actual sequential phases, result times and physical work counts."""
    validate_sequence(parts)
    phases: list[float] = []
    segments: list[dict[str, Any]] = []
    measurement_phases: list[tuple[int, float]] = []
    primitive_counts: Counter[str] = Counter()
    uses_aod, cursor, distance = False, 0.0, 0.0
    categories = {
        "Load": ("transfer", "aod"),
        "Store": ("transfer", "aod"),
        "Move": ("movement", "aod"),
        "Measure": ("measurement", "camera"),
        "Reset": ("reset", "local"),
        "CZPulse": ("gate", "rydberg"),
        "Rotation": ("gate", "local"),
    }
    for part in parts:
        state = part.entry_state
        primitive_counts.update(n.name for n in part.dag.nodes if n.name != "barrier")
        for step in part.program.steps:
            emitted = set()
            for action in step.actions:
                kind = type(action).__name__
                category, resource = categories.get(kind, ("other", "none"))
                if (category, resource) not in emitted:
                    segments.append(
                        {
                            "start_offset_us": cursor,
                            "end_offset_us": cursor + action.duration_us,
                            "category": category,
                            "resource": resource,
                        }
                    )
                    emitted.add((category, resource))
                uses_aod |= isinstance(action, Load)
                if isinstance(action, Move):
                    distance += sum(
                        hypot(
                            target.x - state.atom(atom).position.x,
                            target.y - state.atom(atom).position.y,
                        )
                        for atom, target in action.targets
                    )
                if isinstance(action, Measure):
                    measurement_phases.extend(
                        (len(phases), 0.0) for _ in action.results
                    )
            phases.append(step.duration_us)
            cursor += step.duration_us
            # Movement distances need only position updates, not a second semantic
            # replay: every bound part already passed the physical validator.
            positions = {
                atom: target
                for a in step.actions
                if isinstance(a, Move)
                for atom, target in a.targets
            }
            if positions:
                state = replace(
                    state,
                    atoms=tuple(
                        replace(a, position=positions.get(a.id, a.position))
                        for a in state.atoms
                    ),
                )
    return {
        "component_id": component,
        "phase_durations_us": phases or [0.0],
        "measurement_phases": measurement_phases,
        "cost_segments": segments,
        "primitive_counts": dict(primitive_counts),
        "uses_aod": uses_aod,
        "movement_distance_atom_um": distance,
        "physical_validation": "all_parts_checked",
        "part_hashes": [p.template_content_sha256 for p in parts],
        "correction_envelope": component.endswith("/canonicalize"),
    }


def calibrate_factory(
    distance: int,
    count: int,
    *,
    noise_params: dict[str, Any],
    output: Path,
    shots: int = 65536,
    seed: int = 20261024,
) -> SurfaceFactoryProfile:
    """Calibrate complete finite component coverage at each actual module position.

    This stage compiles atoms and may be expensive. Subsequent fast runs read
    the resulting profile only. Source snapshots and explicit noise are frozen.
    """
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    snapshot = source_snapshot()
    world = build_world(ExperimentSpec(distance=distance, pipelines=count))
    entries, ports, patches = {}, {}, []
    all_homes = tuple(h for p in world.patches for h in p.home_sites)
    cache: dict[
        tuple[str, tuple[tuple[float, float], ...]], list[AtomComponentTemplate]
    ] = {}
    for p in world.patches:
        patches.append(
            {
                "block_id": p.binding.block_id,
                "factory_id": f"factory{p.factory_index}",
                "role": p.role,
                "slot": ROLES.index(p.role),
                "origin": [p.binding.origin.x, p.binding.origin.y],
            }
        )

    def ordinary(
        component: str,
        selected: tuple[Any, ...],
        invocation: str,
        *,
        start: float = 0,
        base: int = 0,
    ) -> ComponentExpansion:
        if component == "pauli_correction_envelope":
            code = definition(distance)
            source = "\n".join(
                [
                    "OPENQASM 3.0;",
                    'include "stdgates.inc";',
                    f"qubit[{code.atom_count}] q;",
                    *(f"y q[{q}];" for q in range(code.data_count)),
                    "",
                ]
            )
            description = ComponentDescription(
                f"rotated_surface_d{distance}",
                component,
                "1",
                code.roles,
                (),
                ("Worst-case cost reference only",),
                ("One addressed Pauli layer; decoder chooses actual axes",),
            )
            corrections = ()
        else:
            c = (
                TransversalCNOTComponent(distance)
                if component == "transversal_cnot"
                else get_component(component, distance)
            )
            source, description = c.source_qasm, c.description
            corrections = ()
        first = selected[0].binding
        binding = ComponentBinding(
            "+".join(p.binding.block_id for p in selected),
            first.origin,
            tuple(a for p in selected for a in p.binding.atom_ids),
            first.aod_id,
        )
        homes = tuple(h for p in selected for h in p.home_sites)
        key = (
            component,
            tuple(
                (
                    p.binding.origin.x - first.origin.x,
                    p.binding.origin.y - first.origin.y,
                )
                for p in selected
            ),
        )
        context = InvocationContext(invocation, start, base, world.device, world.state)
        for template in cache.get(key, ()):
            try:
                return template.bind(binding).expand(context)
            except BindingRejected:
                pass  # Explicit calibration may recompile a changed placement.
        template = compile_template(
            description,
            source,
            world.device,
            home_sites=homes,
            origin=first.origin,
            aod_id=first.aod_id,
            expected_values=(None,) * len(description.measurements),
            corrections=corrections,
            spectator_home_sites=tuple(h for h in all_homes if h not in homes),
        )
        cache.setdefault(key, []).append(template)
        return template.bind(binding).expand(context)

    for index in range(count):
        prepared = {}
        for component, roles in required_variants(distance):
            selected = tuple(world.patch(index, role) for role in roles)
            key = entry_key(component, tuple(p.binding.block_id for p in selected))
            patch = selected[0]
            if component == "raw_t_postselection":
                protocol = RawTPostselection(distance)
                template = protocol.compile(
                    world.device,
                    home_sites=patch.home_sites,
                    origin=patch.binding.origin,
                    aod_id=patch.binding.aod_id,
                )
                stage = template.bind(patch.binding).expand(
                    InvocationContext(key, 0, 0, world.device, world.state)
                )
                prepared[roles[0]] = template
                parts = stage.sequence.parts
                port = protocol.acceptance_port(
                    stage,
                    world.device,
                    noise_params=noise_params,
                    method="monte_carlo",
                    shots=shots,
                    seed=seed,
                    batch_size=min(shots, 65536),
                )
                full = port.to_dict()
                (output / f"factory{index}-{roles[0]}.acceptance.json").write_text(
                    json.dumps(full, separators=(",", ":")), encoding="utf-8"
                )
                full["model"]["evidence"] = {
                    "source_port_sha256": port.content_sha256,
                    "estimator": full["model"]["evidence"]["estimator"],
                    "preparation_sha256": stage.preparation_sha256,
                    "noise_params_hash": full["model"]["evidence"]["noise_params_hash"],
                    "scope": "single-call physical acceptance; retained atoms; no growth quality estimate",
                }
                ports[patch.binding.block_id] = full
            elif component.endswith("/canonicalize"):
                collected = []
                start, base = 0.0, 0
                if component.startswith("raw_t") and distance > 3:
                    template = prepared[roles[0]]
                    for r in range(distance):
                        t = template.growth if r == 0 else template.se_round
                        assert t is not None
                        part = t.bind(patch.binding).expand(
                            InvocationContext(
                                f"{key}/growth[{r}]",
                                start,
                                base,
                                world.device,
                                world.state,
                            )
                        )
                        collected.append(part)
                        start, base = part.action_end_us, base + len(part.measurements)
                collected.append(
                    ordinary(
                        "pauli_correction_envelope",
                        selected,
                        key + "/pauli",
                        start=start,
                        base=base,
                    )
                )
                parts = tuple(collected)
            else:
                parts = (ordinary(component, selected, key),)
            entries[key] = summarize_parts(component, parts)
        print(
            json.dumps(
                {
                    "calibrated_distance": distance,
                    "factory": index,
                    "entries": len(entries),
                    "wall_seconds": perf_counter() - started,
                }
            ),
            flush=True,
        )
    if snapshot != source_snapshot():
        raise ValueError("Runtime sources changed during calibration.")
    assert world.device.readout is not None
    document = {
        "schema": SCHEMA,
        "standard": STANDARD_ID,
        "distance": distance,
        "factory_count": count,
        "noise_params": noise_params,
        "patches": patches,
        "entries": entries,
        "raw_ports": ports,
        "world_sha256": canonical_hash(world.document()),
        "source_tree_sha256": canonical_hash(snapshot),
        "calibration_wall_seconds": perf_counter() - started,
        "timing": {
            "load_us": world.device.timing.load_us,
            "store_us": world.device.timing.store_us,
            "measure_us": world.device.readout.duration_us,
            "result_processing_us": world.device.readout.latency_us,
        },
        "scope": "single-component physical calibrations; conservative shared-AOD resource estimates; decoder-conditioned correction-layer envelope",
    }
    profile = SurfaceFactoryProfile(document)
    (output / "profile.json").write_text(
        json.dumps(document, separators=(",", ":")), encoding="utf-8"
    )
    (output / "world.json").write_text(
        json.dumps(world.document(), separators=(",", ":")), encoding="utf-8"
    )
    return profile
