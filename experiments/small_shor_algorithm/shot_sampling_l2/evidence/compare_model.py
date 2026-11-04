"""Independent full-vector checks of L2 pending local operators and OU moments.

NumPy applies every rotation directly to a two-qubit vector, including static
detuning between every event. The engine's lazy 2x2 composition is instrumented
only at measurement boundaries; the production code is not modified.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from decimal import Decimal, localcontext
from pathlib import Path

import numpy as np

LAB = Path(__file__).resolve().parents[1]
ENGINE = LAB.parents[1] / "small_circuit/shor/browser_engine.js"
VALUES = [0.37, 0.61, 0.14, 0.82, 0.23, 0.74, 0.41, 0.56]
X = np.array([[0, 1], [1, 0]], dtype=complex)
Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
Z = np.diag([1, -1]).astype(complex)
H = np.array([[1, 1], [1, -1]], dtype=complex) / math.sqrt(2)


def rotation(axis: np.ndarray, angle: float) -> np.ndarray:
    """Independent Pauli-axis exponential, not the engine's pulse helper."""
    return math.cos(angle / 2) * np.eye(2) - 1j * math.sin(angle / 2) * axis


def matrix_data(matrix: np.ndarray) -> list[float]:
    """Serialize a complex 2x2 matrix for the engine's public event shape."""
    return [float(v) for z in matrix.flat for v in (z.real, z.imag)]


def gate(t: float, q: int, matrix: np.ndarray, guard: dict | None = None) -> dict:
    return {
        "type": "gate",
        "t": t,
        "q": q,
        "matrix": matrix_data(matrix),
        "guard": guard,
        "error": 0,
    }


def flush_pair(t: float) -> list[dict]:
    """CZ squared is identity and flushes pending matrices on both wires."""
    return [{"type": "cz", "t": t, "q": 0, "q2": 1, "error": 0} for _ in range(2)]


def scenarios() -> list[dict]:
    events = [
        gate(0, 0, H),
        gate(0, 1, H),
        {"type": "cz", "t": 12, "q": 0, "q2": 1, "error": 0},
        gate(13, 0, np.diag([1, np.exp(1j * math.pi / 3)])),
        {"type": "pulse", "t": 20, "axis": 0},
        gate(31, 1, rotation(Y, 0.42)),
        gate(42, 0, rotation(Z, -0.61)),
        {"type": "pulse", "t": 53, "axis": 1},
        {"type": "cz", "t": 67, "q": 0, "q2": 1, "error": 0},
        {"type": "pulse", "t": 73, "axis": 0},
        gate(90, 1, np.diag([1, np.exp(0.19j)])),
        {"type": "pulse", "t": 111, "axis": 1},
        *flush_pair(130),
        {"type": "measure", "t": 130, "q": 0, "bit": 0, "error": 0, "release": False},
        {"type": "measure", "t": 130, "q": 1, "bit": 1, "error": 0, "release": False},
    ]
    adaptive = [
        gate(0, 0, H),
        gate(0, 1, H),
        {"type": "cz", "t": 12, "q": 0, "q2": 1, "error": 0},
        *flush_pair(20),
        {"type": "measure", "t": 20, "q": 0, "bit": 0, "error": 0, "release": False},
        gate(30, 1, rotation(Z, 0.71), {"bit": 0, "value": 1}),
        *flush_pair(40),
        {"type": "reset", "t": 40, "q": 0, "error": 0},
        gate(45, 0, H),
        {"type": "pulse", "t": 60, "axis": 0},
        {"type": "cz", "t": 80, "q": 0, "q2": 1, "error": 0},
        *flush_pair(100),
        {"type": "measure", "t": 100, "q": 0, "bit": 0, "error": 0, "release": False},
        {"type": "measure", "t": 100, "q": 1, "bit": 1, "error": 0, "release": False},
    ]
    false_adaptive = [dict(event) for event in adaptive]
    next(event for event in false_adaptive if event.get("guard"))["guard"] = {
        "bit": 0,
        "value": 0,
    }
    targeted = [
        {**event, "targets": [1]} if event["type"] == "pulse" else dict(event)
        for event in events
    ]
    empty_targets = [
        {**event, "targets": []} if event["type"] == "pulse" else dict(event)
        for event in events
    ]
    return [
        {
            "name": "entangled_noncommuting_pulses",
            "events": events,
            "sigmaS": 0,
            "pulseError": 0,
        },
        {
            "name": "static_noise_and_pulse_angle_error",
            "events": events,
            "sigmaS": 0.005,
            "pulseError": 0.08,
        },
        {
            "name": "measurement_reset_and_feedback",
            "events": adaptive,
            "sigmaS": 0.005,
            "pulseError": 0.08,
        },
        {
            "name": "measurement_reset_and_false_feedback",
            "events": false_adaptive,
            "sigmaS": 0.005,
            "pulseError": 0.08,
        },
        {
            "name": "explicit_single_target_in_entangled_state",
            "events": targeted,
            "sigmaS": 0.005,
            "pulseError": 0.17,
        },
        {
            "name": "explicit_empty_target_is_not_global_pulse",
            "events": empty_targets,
            "sigmaS": 0.005,
            "pulseError": 0.17,
        },
    ]


NODE = r"""
const fs=require('fs'), E=require(process.argv[1]), I=E._internal;
const input=JSON.parse(fs.readFileSync(0,'utf8')), results=[];
for(const test of input.scenarios){
 let k=0;const rng=()=>input.values[(k++)%input.values.length], captures=[];
 const original=I.State.prototype.measure;
 I.State.prototype.measure=function(q,rng,release){
  const vector=Array.from({length:this.size},(_,i)=>[this.r[i],this.i[i]]);
  const value=original.call(this,q,rng,release);captures.push({q,value,vector});return value;
 };
 try{I.runLevel2({events:test.events,num_qubits:2,rates:{sigmaS:test.sigmaS,sigmaF:0,tauC:50}},
   {pulseError:test.pulseError},2,1,rng);}finally{I.State.prototype.measure=original;}
 results.push({name:test.name,captures});
}
const small=[1e-2,1e-4,1e-6,1e-8,1e-10].map(x=>{
 let a=0;const v=I.ouStep(0,x*50,.02,50,()=>a++===0?1:0);
 let b=0;const w=I.ouStep(0,x*50,.02,50,()=>b++===0?0:1);
 return {x,g:I.echoG(x),historicalEcho:x+4*Math.expm1(-x/2)-Math.expm1(-x),h:I.ramseyH(x),v1:v[0]*v[0]+w[0]*w[0],
   v2:v[1]*v[1]+w[1]*w[1],cov:v[0]*v[1]+w[0]*w[1]};
});
process.stdout.write(JSON.stringify({results,small}));
"""


def apply_local(state: np.ndarray, q: int, matrix: np.ndarray) -> np.ndarray:
    """Apply the immediate full-space Kronecker operator in little-endian order."""
    full = np.kron(np.eye(2), matrix) if q == 0 else np.kron(matrix, np.eye(2))
    return full @ state


def compare(test: dict, observed: dict) -> dict:
    state = np.array([1, 0, 0, 0], dtype=complex)
    eps = [
        test["sigmaS"]
        * math.sqrt(-2 * math.log(VALUES[2 * q]))
        * math.cos(2 * math.pi * VALUES[2 * q + 1])
        for q in range(2)
    ]
    clock, index, errors = 0, 0, []
    classical = [0, 0]
    for event in test["events"]:
        dt = event["t"] - clock
        for q in range(2):
            state = apply_local(state, q, rotation(Z, eps[q] * dt))
        clock = event["t"]
        kind = event["type"]
        if kind == "gate":
            guard = event.get("guard")
            if guard and classical[guard["bit"]] != guard["value"]:
                continue
            values = event["matrix"]
            matrix = np.array(
                [complex(*values[i : i + 2]) for i in range(0, 8, 2)]
            ).reshape(2, 2)
            state = apply_local(state, event["q"], matrix)
        elif kind == "pulse":
            matrix = rotation(
                X if event["axis"] == 0 else Y, math.pi * (1 + test["pulseError"])
            )
            for q in event.get("targets", range(2)):
                state = apply_local(state, q, matrix)
        elif kind == "cz":
            state[3] *= -1
        elif kind in ("measure", "reset"):
            capture = observed["captures"][index]
            index += 1
            actual = np.array([complex(*x) for x in capture["vector"]])
            overlap = np.vdot(state, actual)
            phase = overlap / abs(overlap) if overlap else 1.0
            errors.append(float(np.max(np.abs(actual - phase * state))))
            q, value = event["q"], capture["value"]
            state[np.array([(i >> q) & 1 for i in range(4)]) != value] = 0
            state /= np.linalg.norm(state)
            if kind == "reset":
                if value:
                    state = apply_local(state, q, X)
            else:
                classical[event["bit"]] = value
    return {
        "name": test["name"],
        "checkpoints": index,
        "max_amplitude_error": max(errors),
    }


def small_moments(record: dict) -> dict:
    with localcontext() as context:
        context.prec = 85
        x = Decimal(str(record["x"]))
        a = (-x).exp()
        expected = {
            "g": x - 3 + 4 * (-x / 2).exp() - a,
            "h": x - 1 + a,
            "v1": Decimal(".0004") * (1 - a * a),
            "v2": Decimal(1) * (2 * x - 3 + 4 * a - a * a),
            "cov": Decimal(".02") * (1 - a) ** 2,
        }
    relative = {
        key: abs(record[key] / float(value) - 1) for key, value in expected.items()
    }
    return {
        "x": record["x"],
        "echo_decimal": str(expected["g"]),
        "echo_engine": record["g"],
        "echo_historical_formula": record["historicalEcho"],
        "max_relative_error": max(relative.values()),
    }


def main() -> None:
    tests = scenarios()
    result = subprocess.run(
        ["node", "-e", NODE, str(ENGINE)],
        input=json.dumps({"scenarios": tests, "values": VALUES}),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    data = json.loads(result.stdout)
    report = {
        "engine_source": "experiments/small_circuit/shor/browser_engine.js",
        "engine_file_sha256": hashlib.sha256(ENGINE.read_bytes()).hexdigest(),
        "scope": "Independent immediate full-vector evolution vs pending 2x2 engine; OU covariance vs 85-digit Decimal reference.",
        "state_evolution": [
            compare(a, b) for a, b in zip(tests, data["results"], strict=True)
        ],
        "small_argument_moments": [small_moments(row) for row in data["small"]],
    }
    report["within_tolerance"] = all(
        row["max_amplitude_error"] < 1e-12 for row in report["state_evolution"]
    ) and all(
        row["max_relative_error"] < 1e-7 for row in report["small_argument_moments"]
    )
    output = LAB / "build/independent-model.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(output)
    if not report["within_tolerance"]:
        raise SystemExit("Numerical discrepancy exceeds the declared tolerance.")


if __name__ == "__main__":
    main()
