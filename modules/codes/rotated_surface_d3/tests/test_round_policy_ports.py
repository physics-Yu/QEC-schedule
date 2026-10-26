"""Normal R=d ports and factory admission cannot reuse historical R2 metadata."""

import pytest

from modules.codes.contracts.component import InvocationContext
from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.rotated_surface_d3.components.canonicalization import (
    CorrectionDecision,
)
from modules.codes.rotated_surface_d3.probabilities.preparation import preparation_port
from modules.codes.rotated_surface_d3.probabilities.raw_t import (
    raw_t_ideal_port,
    raw_t_pauli_port,
)
from modules.codes.rotated_surface_d3.protocols.factory_backend import (
    SurfaceFactoryBackend,
)
from modules.codes.rotated_surface_d3.protocols.factory_world import make_factory_world
from modules.codes.rotated_surface_d3.protocols.raw_t_postselection import (
    RawTPostselection,
)

NORMAL = {
    "distance": 3,
    "extra_rounds": 2,
    "total_rounds": 3,
    "round_policy": "distance",
}


def test_default_binary_and_joint_ports_declare_current_three_round_protocol():
    binary = raw_t_ideal_port()
    joint = preparation_port("raw_t_postselection")
    for port in (binary, joint):
        assert port.protocol_version == "2"
        parameters = port.to_dict()["model"]["parameters"]
        assert {key: parameters[key] for key in NORMAL} == NORMAL
    assert binary.to_dict()["model"]["evidence"]["detector_count"] == 20
    assert joint.to_dict()["model"]["evidence"]["detectors"] == 20
    control = raw_t_ideal_port(1, round_policy="explicit_control")
    assert control.to_dict()["model"]["parameters"]["total_rounds"] == 2
    assert control.content_sha256 != binary.content_sha256
    assert binary.content_sha256 == raw_t_ideal_port(2).content_sha256
    with pytest.raises(ValueError, match="total_rounds"):
        raw_t_ideal_port(1)
    with pytest.raises(ValueError, match="total_rounds"):
        preparation_port("raw_t_postselection", extra_rounds=1)


@pytest.fixture(scope="module")
def factory_source():
    world = make_factory_world()
    backend = SurfaceFactoryBackend(world.device)
    binding = world.bindings["R"]
    bound = backend.bind_call("raw_t_postselection", (binding,))
    source = bound.expand(
        InvocationContext("normal-r3", 0, 1000, world.device, world.world_state)
    )
    return world, backend, bound, source


def test_normal_source_has_twenty_exact_detectors_and_no_old_cache_key(factory_source):
    world, backend, bound, source = factory_source
    assert len(source.parts) == source.total_rounds == 3
    assert len(source.detectors) == 20
    assert bound.result_count == len(source.measurements) == 24
    port = raw_t_pauli_port(source, world.device, noise_params={})
    assert port.outcome("accepted").probability == 1
    assert port.to_dict()["model"]["kind"] == "pauli_exact"
    assert port.to_dict()["model"]["evidence"]["center_t_identity_checks"] == 20
    explicit = backend.bind_call(
        "raw_t_postselection", (world.bindings["R"],), (("extra_rounds", 2),)
    )
    assert explicit.expander.template is bound.expander.template
    spec = backend.describe_execution("raw_t_postselection", (world.bindings["R"],))
    assert spec.result_count == 24
    assert (
        backend.resolve_event("preparation:raw_t_postselection").protocol_version == "2"
    )
    for method in (backend.bind_call, backend.describe_execution):
        with pytest.raises(ValueError, match="total_rounds"):
            method(
                "raw_t_postselection", (world.bindings["R"],), (("extra_rounds", 1),)
            )


def test_factory_rejects_explicit_control_source_before_ideal_or_noisy_event(
    factory_source,
):
    world, backend, _, _ = factory_source
    patch = world.patch("R")
    template = RawTPostselection(
        extra_rounds=1, round_policy="explicit_control"
    ).compile(
        world.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
    )
    source = template.bind(patch.binding).expand(
        InvocationContext("historical-r2", 0, 2000, world.device, world.world_state)
    )
    for parameters in (None, {"noise_model": "noise/v1", "noise_params": {}}):
        with pytest.raises(ValueError, match="round policy"):
            backend.preparation_event("raw_t_postselection", source, parameters)


@pytest.mark.parametrize("change", ("old_version", "old_rounds", "control_label"))
def test_factory_canonicalization_rejects_stale_port_metadata(factory_source, change):
    _, backend, _, source = factory_source
    document = preparation_port("raw_t_postselection").to_dict()
    if change == "old_version":
        document["protocol_version"] = "1"
    elif change == "old_rounds":
        document["model"]["parameters"].update(extra_rounds=1, total_rounds=2)
    else:
        document["model"]["parameters"]["round_policy"] = "explicit_control"
    old = ProbabilityPort.from_dict(document)
    decision = CorrectionDecision(
        source.parts[0].invocation_id,
        "coarse",
        old.content_sha256,
        0,
        True,
        source.results_ready_us,
    )
    with pytest.raises(ValueError, match="old or different round policy"):
        backend.bind_canonicalization("raw_t_postselection", source, decision, old)
