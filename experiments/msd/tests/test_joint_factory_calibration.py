"""Actual one-device joint raw-A and mixed-frontier physical witnesses."""

from experiments.msd.joint_factory_calibration import compile_joint_group
from experiments.msd.standard import ExperimentSpec, build_world


def test_shared_vertical_raw_se_is_jointly_compiled_and_noise_uses_that_trace(tmp_path):
    world = build_world(ExperimentSpec(3, 2))
    members = ("raw_t_postselection:factory0/R", "raw_t_postselection:factory1/R")

    def compile_members(selected):
        return compile_joint_group(
            world,
            selected,
            family="test-world",
            noise_params={},
            shots=16,
            seed=0,
            output=tmp_path,
        )

    joint = compile_members(members)
    serial = sum(sum(compile_members((m,))["phase_durations_us"]) for m in members)
    assert sum(joint["phase_durations_us"]) < serial
    assert joint["schedule"]["concurrency"]["maximum_factories_in_transport_batch"] == 2
    assert joint["factory_concurrency"]["peak_active_factories"] == 2
    assert joint["factory_concurrency"]["shared_transport_batches"] > 0
    for member in members:
        assert len(joint["members"][member]["measurement_phases"]) == 24
        port = joint["raw_ports"][member]
        assert port["outcomes"][0]["probability"] == 1
        assert port["model"]["evidence"]["joint_trace_sha256"] == joint["trace_sha256"]
    mixed = compile_members((members[0], "transversal_cnot:factory1/W1,factory1/W2"))
    assert mixed["validation_ok"]
    assert mixed["raw_ports"][members[0]]["outcomes"][0]["probability"] == 1
