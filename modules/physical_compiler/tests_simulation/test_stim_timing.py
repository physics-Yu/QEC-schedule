"""Independent mixed-duration AtomStep and measurement-order fixture."""

from math import exp, pi
from typing import Any

import pytest
import stim

from nadit_physical_compiler.atom_ir import (
    AtomProgram,
    AtomStep,
    Measure,
    Reset,
    Rotation,
    Wait,
)
from nadit_physical_compiler.capabilities import LocalControl, ReadoutCapability
from nadit_physical_compiler.compiler import (
    CompilationResult,
    CompiledOperation,
    MeasurementRecord,
)
from nadit_physical_compiler.device import (
    Device,
    Position,
    Region,
    SLMSite,
    Timing,
    Zone,
)
from nadit_physical_compiler.frontend import loads_qasm
from nadit_physical_compiler.methods import run_method
from nadit_physical_compiler.serialization import encode_result
from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder
from nadit_physical_compiler.validation import validate_result


def timed_document() -> dict[str, Any]:
    dag = loads_qasm(
        'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; bit[2] c; '
        "reset q[0]; rx(pi/2) q[1]; c[0]=measure q[0]; c[1]=measure q[1];"
    )
    device = Device(
        "timing",
        (Zone("all", Region(0, 0, 20, 20), ("reset", "rotate", "measure")),),
        (SLMSite("a", Position(0, 0)), SLMSite("b", Position(10, 0))),
        (),
        Timing(10, 10, 1),
        local=LocalControl("local", 2, 5),
        readout=ReadoutCapability("readout", 10, 7, 5, True, ("slm",), 2),
    )
    layout = AtomLayout(
        (
            AtomState(7, Position(0, 0), SLMHolder("a")),
            AtomState(91, Position(10, 0), SLMHolder("b")),
        ),
        qubit_to_atom=(7, 91),
    )
    first, second = dag.nodes[2].result, dag.nodes[3].result
    assert first is not None and second is not None
    program = AtomProgram(
        (
            AtomStep(
                (
                    Reset("local", (7,), duration_us=5, source_ids=(0,)),
                    Rotation(
                        "local", (91,), "X", pi / 2, duration_us=2, source_ids=(1,)
                    ),
                )
            ),
            AtomStep(
                (
                    Measure(
                        "readout",
                        ((91, second), (7, first)),
                        True,
                        duration_us=10,
                        source_ids=(3, 2),
                    ),
                    Wait(duration_us=12),
                )
            ),
        )
    )
    result = CompilationResult(
        program,
        layout,
        (
            CompiledOperation(0, "emitted", 0, 5),
            CompiledOperation(1, "emitted", 0, 2),
            CompiledOperation(2, "emitted", 5, 15),
            CompiledOperation(3, "emitted", 5, 15),
        ),
        (MeasurementRecord(second, 1, 22), MeasurementRecord(first, 1, 22)),
        (),
    )
    report = validate_result(result, entry_state=layout, device=device, dag=dag)
    assert report["ok"], report
    return encode_result(
        result,
        entry_state=layout,
        device=device,
        dag=dag,
        inputs={"qasm_sha256": "a" * 64, "device_sha256": "b" * 64},
        job={"strategy": {"kind": "search_smarter"}},
        provenance={},
        validation=report,
    )


def test_idle_noise_order_and_real_record_mapping() -> None:
    doc = timed_document()
    annotations = {
        "schema": "nadit.stim.annotations/1",
        "qasm_sha256": "a" * 64,
        "measurement_ids": [2, 3],
        "detectors": [{"measurement_ids": [2], "coordinates": [0, 0, 0]}],
    }
    exported = run_method(
        "stim/v1",
        doc,
        annotations=annotations,
        noise_params={"exposure": {"slm_t2_us": 100}},
    )
    assert exported.report["measurement_records"] == {"3": 0, "2": 1}
    circuit = stim.Circuit(exported.circuit)
    instructions = list(circuit)
    # q1's rotation finishes at 2, followed by 3 us idle before readout starts at 5.
    short = [
        i
        for i in instructions
        if i.name == "Z_ERROR"
        and i.gate_args_copy() == pytest.approx([(1 - exp(-3 / 100)) / 2])
    ]
    assert len(short) == 1
    assert short[0].targets_copy()[0].value == 1
    assert instructions.index(short[0]) < next(
        i for i, v in enumerate(instructions) if v.name == "M"
    )
    assert circuit.num_ticks == 2
    assert str(instructions[-1]) == "DETECTOR(0, 0, 0) rec[-1]"
    # The saved FakeBackend bits are both 1; physical reset still makes q0 measure 0.
    assert not circuit.compile_sampler(seed=1).sample(32)[:, 1].any()
    assert exported.report["duration_us"] == 22
