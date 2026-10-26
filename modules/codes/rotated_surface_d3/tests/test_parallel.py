"""Code-owned metadata admission and reproducible local parallel templates."""

from dataclasses import FrozenInstanceError, replace
from itertools import pairwise

import pytest
from nadit_physical_compiler.device import Position, Region
from nadit_physical_compiler.state import AODGrid

from modules.codes._support import atom_template
from modules.codes.contracts.component import InvocationContext
from modules.codes.contracts.parallel import (
    ComponentExecutionSpec,
    SharedAODClaim,
    SpaceClaim,
)
from modules.codes.rotated_surface_d3.protocols.factory_backend import (
    SurfaceFactoryBackend,
)
from modules.codes.rotated_surface_d3.protocols.factory_world import (
    FactoryWorldConfig,
    make_factory_world,
)


@pytest.fixture(scope="module")
def parallel_world():
    return make_factory_world(
        FactoryWorldConfig(
            aod_ids=("one", "two", "three", "four"),
            role_aod_ids=(
                ("W2", "one"),
                ("W3", "two"),
                ("W4", "three"),
                ("W5", "four"),
            ),
        )
    )


def test_execution_contract_is_immutable_and_json_ready():
    space = SpaceClaim(Region(0, 0, 10, 20), "transport")
    spec = ComponentExecutionSpec(
        "toy",
        "prepare",
        "wave",
        ("A",),
        (space,),
        ("aod:one",),
        "independent_aods_lockstep",
        8,
    )
    assert spec.to_dict()["spaces"][0]["region"]["y_max"] == 20
    with pytest.raises(FrozenInstanceError):
        spec.result_count = 0
    for changes in (
        {"result_count": True},
        {"result_count": -1},
        {"parallel_mode": "guess"},
        {"participant_blocks": ("A", "A")},
        {"waveform_key": None},
        {"exclusive_resources": ("aod:x", "aod:x")},
    ):
        with pytest.raises(ValueError):
            replace(spec, **changes)


def test_declarations_do_not_compile_bind_or_expand(parallel_world, monkeypatch):
    backend = SurfaceFactoryBackend(parallel_world.device)

    def forbidden(*args, **kwargs):
        raise AssertionError("Declaration must not compile, bind or expand")

    monkeypatch.setattr(atom_template, "compile_physical", forbidden)
    monkeypatch.setattr(SurfaceFactoryBackend, "bind_call", forbidden)
    specs = [
        backend.describe_execution(
            "raw_t_postselection", (parallel_world.bindings[role],)
        )
        for role in ("W2", "W3", "W4", "W5")
    ]
    assert len({spec.waveform_key for spec in specs}) == 1
    assert all(
        spec.parallel_mode == "shared_aod_lockstep" and spec.result_count == 16
        for spec in specs
    )
    assert {spec.exclusive_resources for spec in specs} == {()}
    assert {spec.shared_aod.aod_id for spec in specs} == {"one", "two", "three", "four"}
    assert all(
        a.spaces[0].region.x_max < b.spaces[0].region.x_min for a, b in pairwise(specs)
    )


@pytest.mark.parametrize(
    "name,count",
    [
        ("se_round", 8),
        ("raw_t", 8),
        ("initialize_0", 8),
        ("initialize_plus", 8),
        ("raw_t_postselection", 16),
        ("logical_s", 8),
        ("logical_x", 0),
        ("logical_z", 0),
    ],
)
def test_supported_translated_calls_reuse_one_exact_relative_template(
    parallel_world, monkeypatch, name, count
):
    backend = SurfaceFactoryBackend(parallel_world.device)
    first = backend.bind_call(name, (parallel_world.bindings["W5"],))

    def forbidden(*args, **kwargs):
        raise AssertionError("Same waveform must reuse its canonical relative template")

    monkeypatch.setattr(atom_template, "compile_physical", forbidden)
    second = backend.bind_call(name, (parallel_world.bindings["W2"],))
    assert first.result_count == second.result_count == count
    assert first.expander.template is second.expander.template
    for index, call in enumerate((first, second)):
        output = call.expand(
            InvocationContext(
                f"copy-{index}",
                0,
                100 * index,
                parallel_world.device,
                parallel_world.world_state,
            )
        )
        parts = getattr(output, "parts", (output,))
        assert parts[-1].exit_state == parallel_world.world_state
        assert all(
            result.value is None for part in parts for result in part.measurements
        )
        binding = parallel_world.bindings["W5" if index == 0 else "W2"]
        envelope = backend.describe_execution(name, (binding,)).spaces[0].region
        for part in parts:
            for step in part.program.steps:
                for action in step.actions:
                    if hasattr(action, "grid"):
                        assert all(
                            envelope.y_min <= row.coordinate <= envelope.y_max
                            for row in action.grid.rows
                        )
                        assert all(
                            envelope.x_min <= column.coordinate <= envelope.x_max
                            for column in action.grid.columns
                        )
                    coverage = getattr(action, "coverage", None)
                    if isinstance(coverage, Region):
                        assert envelope.contains(
                            Position(coverage.x_min, coverage.y_min)
                        )
                        assert envelope.contains(
                            Position(coverage.x_max, coverage.y_max)
                        )


def test_distinct_protocol_parameters_have_distinct_waveforms(parallel_world):
    backend = SurfaceFactoryBackend(parallel_world.device)
    binding = (parallel_world.bindings["W2"],)
    specs = [
        backend.describe_execution(name, binding)
        for name in (
            "se_round",
            "initialize_0",
            "initialize_plus",
            "raw_t",
            "raw_t_postselection",
        )
    ]
    specs.append(
        backend.describe_execution(
            "raw_t_postselection", binding, (("extra_rounds", 2),)
        )
    )
    assert len({spec.waveform_key for spec in specs}) == len(specs)
    assert specs[-1].result_count == 24


@pytest.mark.parametrize(
    "name",
    [
        "initialize_0/canonicalize",
        "initialize_plus/canonicalize",
        "raw_t_postselection/canonicalize",
    ],
)
def test_canonicalization_has_pure_local_execution_spec(
    parallel_world, monkeypatch, name
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Canonicalization metadata must not compile")

    monkeypatch.setattr(atom_template, "compile_physical", forbidden)
    backend = SurfaceFactoryBackend(parallel_world.device)
    spec = backend.describe_execution(name, (parallel_world.bindings["W2"],))
    assert spec.result_count == 0 and spec.waveform_key is not None
    assert spec.parallel_mode == "local_parallel"
    assert spec.exclusive_resources == ()
    with pytest.raises(ValueError):
        backend.describe_execution(
            name, (parallel_world.bindings["W2"],), (("mode", "parallel"),)
        )


@pytest.mark.parametrize("name", ["logical_x", "logical_z"])
def test_local_pauli_claims_no_aod_on_single_aod_device(name):
    world = make_factory_world()
    backend = SurfaceFactoryBackend(world.device)
    first, second = (
        backend.describe_execution(name, (world.bindings[role],))
        for role in ("W2", "W3")
    )
    assert first.parallel_mode == second.parallel_mode == "local_parallel"
    assert first.waveform_key == second.waveform_key
    assert first.exclusive_resources == second.exclusive_resources == ()
    assert first.spaces[0].region.x_max < second.spaces[0].region.x_min


def test_s_keeps_real_transport_claims(parallel_world):
    backend = SurfaceFactoryBackend(parallel_world.device)
    first = backend.describe_execution("logical_s", (parallel_world.bindings["W2"],))
    second = backend.describe_execution("logical_s", (parallel_world.bindings["W3"],))
    assert first.waveform_key == second.waveform_key
    assert first.exclusive_resources == second.exclusive_resources == ()
    assert first.shared_aod.aod_id == "one"
    assert second.shared_aod.aod_id == "two"
    assert first.result_count == second.result_count == 8


def test_cnot_uses_control_aod_and_preserves_both_default_bindings(parallel_world):
    backend = SurfaceFactoryBackend(parallel_world.device)
    participants = (parallel_world.bindings["W2"], parallel_world.bindings["W3"])
    spec = backend.describe_execution("transversal_cnot", participants)
    assert spec.parallel_mode == "shared_aod_lockstep" and spec.waveform_key is not None
    assert spec.participant_blocks == tuple(p.block_id for p in participants)
    assert spec.exclusive_resources == ()
    assert spec.shared_aod.aod_id == "one"
    expansion = backend.bind_call("transversal_cnot", participants).expand(
        InvocationContext(
            "joint-cx", 0, 0, parallel_world.device, parallel_world.world_state
        )
    )
    assert (
        expansion.participant_bindings
        == expansion.exit_participant_bindings
        == participants
    )
    assert expansion.exit_state == parallel_world.world_state


def test_local_corrections_and_paulis_share_control_family(parallel_world, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Local execution metadata must not compile")

    monkeypatch.setattr(atom_template, "compile_physical", forbidden)
    backend = SurfaceFactoryBackend(parallel_world.device)
    specs = tuple(
        backend.describe_execution(name, (parallel_world.bindings["W2"],))
        for name in (
            "initialize_0/canonicalize",
            "initialize_plus/canonicalize",
            "raw_t_postselection/canonicalize",
            "logical_x",
            "logical_z",
        )
    )
    assert len({spec.waveform_key for spec in specs}) == 1
    assert len({spec.component_id for spec in specs}) == len(specs)
    assert all(
        spec.parallel_mode == "local_parallel"
        and spec.shared_aod is None
        and spec.exclusive_resources == ()
        and spec.result_count == 0
        for spec in specs
    )


def test_unsupported_control_profile_is_conservative_exclusive(parallel_world):
    limited = replace(
        parallel_world.device,
        readout=replace(parallel_world.device.readout, max_atoms=7),
    )
    spec = SurfaceFactoryBackend(limited).describe_execution(
        "se_round", (parallel_world.bindings["W2"],)
    )
    assert spec.parallel_mode == "exclusive" and spec.waveform_key is None


def test_shared_aod_claim_validation_and_serialization():
    claim = SharedAODClaim("one", "same-rows", 0, 62, 4, 4, 4, 16, "camera", 8, 32, 1)
    spec = ComponentExecutionSpec(
        "toy", "se", "wave", ("p",), (), (), "shared_aod_lockstep", 8, claim
    )
    assert spec.to_dict()["shared_aod"] == claim.to_dict()
    for changes in (
        {"column_min": float("nan")},
        {"column_max": -1},
        {"peak_rows": True},
        {"max_columns": 3},
        {"max_rows": 0},
        {"max_readout_atoms": 7},
        {"min_spacing": -1},
        {"row_trajectory_key": ""},
    ):
        with pytest.raises(ValueError):
            replace(claim, **changes)
    for changes in (
        {"shared_aod": None},
        {"exclusive_resources": ("aod:one",)},
        {"parallel_mode": "independent_aods_lockstep"},
    ):
        with pytest.raises(ValueError):
            replace(spec, **changes)


def test_single_aod_profile_declares_exact_shared_capacity_and_rows():
    world = make_factory_world()
    device = replace(
        world.device,
        aods=(replace(world.device.aods[0], max_rows=4, max_columns=16),),
        readout=replace(world.device.readout, max_atoms=32),
    )
    backend = SurfaceFactoryBackend(device)
    specs = [
        backend.describe_execution("se_round", (world.bindings[role],))
        for role in ("W2", "W3", "W4", "W5")
    ]
    assert all(spec.parallel_mode == "shared_aod_lockstep" for spec in specs)
    claims = [spec.shared_aod for spec in specs]
    assert len({claim.row_trajectory_key for claim in claims}) == 1
    assert [(claim.column_min, claim.column_max) for claim in claims] == [
        (100, 162),
        (200, 262),
        (300, 362),
        (400, 462),
    ]
    assert all(
        (
            claim.peak_rows,
            claim.peak_columns,
            claim.peak_readout_atoms,
            claim.max_rows,
            claim.max_columns,
            claim.max_readout_atoms,
            claim.min_spacing,
        )
        == (4, 4, 8, 4, 16, 32, 1)
        for claim in claims
    )


def test_role_aod_configuration_rejects_unknown_or_repeated_bindings():
    for mapping in (
        (("unknown", "one"),),
        (("W2", "missing"),),
        (("W2", "one"), ("W2", "one")),
        {"W2": "one"},
    ):
        with pytest.raises(ValueError):
            FactoryWorldConfig(aod_ids=("one",), role_aod_ids=mapping)


@pytest.fixture(scope="module")
def canonical_call(parallel_world):
    backend = SurfaceFactoryBackend(parallel_world.device)
    source = backend.bind_call(
        "initialize_plus", (parallel_world.bindings["W2"],)
    ).expand(
        InvocationContext(
            "prepare-W2", 0, 0, parallel_world.device, parallel_world.world_state
        )
    )
    port = backend.resolve_event("preparation:initialize_plus")
    decision = backend.correction_decision(
        source,
        event_id="chosen-prepare-event",
        probability_port=port,
        values={"accepted": True, "byproduct_class": 1},
        available_at_us=source.results_ready_us,
    )
    return source, backend.bind_canonicalization(
        "initialize_plus", source, decision, port
    )


def test_canonicalization_keeps_unrelated_patch_physical_changes(
    parallel_world, canonical_call
):
    source, call = canonical_call
    atoms = list(source.exit_state.atoms)
    first, second = atoms[0], atoms[1]
    atoms[0] = replace(first, position=second.position, holder=second.holder)
    atoms[1] = replace(second, position=first.position, holder=first.holder)
    changed = replace(source.exit_state, atoms=tuple(atoms))
    output = call.expand(
        InvocationContext(
            "correct-W2", source.results_ready_us, 1000, parallel_world.device, changed
        )
    )
    assert output.expansion.entry_state == output.expansion.exit_state == changed
    assert output.source_measurements == source.measurements
    assert all(result.value is None for result in output.source_measurements)


@pytest.mark.parametrize(
    "change", ["local_atoms", "wire_map", "active_grid", "missing_atom"]
)
def test_canonicalization_does_not_ignore_local_or_world_identity_changes(
    parallel_world, canonical_call, change
):
    source, call = canonical_call
    world = source.exit_state
    if change == "local_atoms":
        atoms = list(world.atoms)
        first, second = atoms[17], atoms[18]
        atoms[17] = replace(first, position=second.position, holder=second.holder)
        atoms[18] = replace(second, position=first.position, holder=first.holder)
        world = replace(world, atoms=tuple(atoms))
    elif change == "wire_map":
        world = replace(world, qubit_to_atom=world.qubit_to_atom[::-1])
    elif change == "active_grid":
        world = replace(world, aod_grids=(AODGrid("one"),))
    else:
        world = replace(
            world, atoms=world.atoms[1:], qubit_to_atom=world.qubit_to_atom[1:]
        )
    with pytest.raises(ValueError, match="exit"):
        call.expand(
            InvocationContext(
                "bad-correction",
                source.results_ready_us,
                1000,
                parallel_world.device,
                world,
            )
        )
