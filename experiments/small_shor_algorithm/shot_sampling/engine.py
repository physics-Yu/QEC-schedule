"""Noisy trajectories for one guarded physical schedule, with loss-abort sampling.

Loss is state independent. We first sample the surviving-qubit dynamics, then
sample the first loss along that classical history. Continuation after that loss
is discarded, not claimed to model gates on a missing atom.
"""

from __future__ import annotations

import itertools
import math
import time
from collections import Counter
from functools import lru_cache
from threading import Lock

import numpy as np
from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, ReadoutError, pauli_error

from .plan import load_plan, retime

DEFAULTS = {
    "speed": 1.0,
    "transfer": 15.0,
    "readout": 100.0,
    "singleTime": 1.0,
    "czTime": 0.5,
    "resetTime": 5.0,
    "latency": 0.0,
    "loadLoss": 0.002,
    "storeLoss": 0.002,
    "czLoss": 0.001,
    "imagingLoss": 0.001,
    "singleLoss": 0.0,
    "resetLoss": 0.0,
    "mass": 86.909180531,
    "frequency": 90.0,
    "width": 0.73,
    "temperature": 27.0,
    "depthSpread": 0.0,
    "t2Slm": 1000.0,
    "t2Aod": 1000.0,
    "t2Transfer": 1000.0,
    "singlePauli": 0.0,
    "czPauli": 0.0005,
    "readoutError": 0.001,
    "resetError": 0.001,
}
PROBABILITIES = {
    "loadLoss",
    "storeLoss",
    "czLoss",
    "imagingLoss",
    "singleLoss",
    "resetLoss",
    "singlePauli",
    "czPauli",
    "readoutError",
    "resetError",
}
LOCK = Lock()
KB = 1.380649e-23
HBAR = 1.054571817e-34
AMU = 1.66053906660e-27
GAUSS_X, GAUSS_W = np.polynomial.legendre.leggauss(64)


def parameters(values: dict | None) -> dict:
    """Validate explicit units: microseconds, micrometres, kHz, u, uK; T2 in ms."""
    p = DEFAULTS | (values or {})
    if set(p) != set(DEFAULTS):
        raise ValueError("Unknown parameter names.")
    for name, value in p.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} must be numeric.")
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and nonnegative.")
        if name in PROBABILITIES and value > 1:
            raise ValueError(f"{name} must be between 0 and 1.")
    for name in ("speed", "mass", "frequency", "width"):
        if p[name] == 0:
            raise ValueError(f"{name}=0: no finite physical simulation is defined.")
    if p["speed"] < 0.01:
        raise ValueError("Movement speed must be at least 0.01 um/us.")
    if p["transfer"] > 1000:
        raise ValueError("LOAD/STORE duration must be at most 1000 us.")
    if p["latency"] != 0:
        raise ValueError("Extra readout latency is fixed to zero.")
    return p


def move_loss(distance: float, duration: float, p: dict) -> float:
    """NAL peak-STA escape estimate, once per complete physical Move."""
    if distance == 0:
        return 0.0
    if duration <= 0:
        raise ValueError("A nonzero Move needs positive duration.")
    omega = 2 * math.pi * p["frequency"] * 1000
    mass = p["mass"] * AMU
    depth = mass * omega**2 * (p["width"] * 1e-6) ** 2 / 2
    energy = (
        (50 / 3) * mass * (distance * 1e-6) ** 2 / (omega**2 * (duration * 1e-6) ** 4)
    )
    thermal = KB * p["temperature"] * 1e-6

    def probability(z: np.ndarray | float) -> np.ndarray:
        remaining = depth * (1 + p["depthSpread"] * np.asarray(z)) - energy
        if thermal == 0:
            return np.asarray(remaining <= 0, dtype=float)
        eta = np.clip(remaining / thermal, 0, 745)
        return (1 + eta + eta * eta / 2) * np.exp(-eta)

    spread = p["depthSpread"]
    if spread == 0:
        return float(probability(0))
    low, high = max(-8, -1 / spread), 8
    threshold = (energy / depth - 1) / spread
    cuts = [low] + ([threshold] if low < threshold < high else []) + [high]
    total = weight = 0.0
    for left, right in itertools.pairwise(cuts):
        scale = (right - left) / 2
        z = (right + left) / 2 + scale * GAUSS_X
        w = scale * GAUSS_W * np.exp(-z * z / 2)
        total += float(np.dot(w, probability(z)))
        weight += float(w.sum())
    return min(1.0, max(0.0, total / weight))


def gamma(duration_us: float, t2_ms: float) -> float:
    if duration_us == 0:
        return 0.0
    return math.inf if t2_ms == 0 else duration_us / (1000 * t2_ms)


def pauli_instruction(probability: float, arity: int):
    """Total probability of a nonidentity Pauli, uniformly distributed."""
    from itertools import product

    labels = ["".join(chars) for chars in product("IXYZ", repeat=arity)]
    return pauli_error(
        [(labels[0], 1 - probability)]
        + [(label, probability / (len(labels) - 1)) for label in labels[1:]]
    ).to_instruction()


@lru_cache(maxsize=2)
def source_plan(n: int) -> dict:
    return load_plan(n)


@lru_cache(maxsize=8)
def prepare(n: int, key: tuple) -> tuple:
    """Compile quantum instructions once per parameter configuration."""
    p = dict(key)
    plan = retime(source_plan(n), p)
    nq, nb = plan["num_qubits"], plan["num_bits"]
    circuit = QuantumCircuit(nq, nb)
    atoms = plan["initial"]["atoms"]
    wires = {a["id"]: a["qubit"] for a in atoms}
    holders = {a["id"]: a["holder"]["kind"] for a in atoms}
    bits = {m["measurement_id"]: m["bit"] for m in plan["measurements"]}
    pending = np.zeros(nq)
    loss_events = []
    gate1 = pauli_instruction(p["singlePauli"], 1) if p["singlePauli"] else None
    gate2 = pauli_instruction(p["czPauli"], 2) if p["czPauli"] else None
    reset_error = (
        pauli_error(
            [("I", 1 - p["resetError"]), ("X", p["resetError"])]
        ).to_instruction()
        if p["resetError"]
        else None
    )

    def flush(q: int) -> None:
        probability = -math.expm1(-float(pending[q])) / 2
        if probability:
            circuit.append(
                pauli_error(
                    [("I", 1 - probability), ("Z", probability)]
                ).to_instruction(),
                [q],
            )
        pending[q] = 0

    def gate(action: dict) -> None:
        kind = action["kind"]
        if kind == "LocalU":
            for atom in action["atoms"]:
                q = wires[atom]
                circuit.u(
                    action["parameters"]["theta"],
                    action["parameters"]["phi"],
                    action["parameters"]["lam"],
                    q,
                )
                if gate1 is not None:
                    circuit.append(gate1, [q])
        elif kind == "CZPulse":
            for first, second in action["pairs"]:
                qubits = [wires[first], wires[second]]
                circuit.cz(*qubits)
                if gate2 is not None:
                    circuit.append(gate2, qubits)

    for step in plan["steps"]:
        transfer_times = {}
        for action in step["actions"]:
            kind, duration = action["kind"], action["duration_us"]
            guard = action.get("guard")
            conditional_bit = bits[guard["measurement_id"]] if guard else None
            if kind == "LocalU":
                # Z dephasing commutes through diagonal gates and Pauli channels.
                # Before a mixing gate it must be materialized on the state.
                if abs(math.sin(action["parameters"]["theta"] / 2)) > 1e-14:
                    for atom in action["atoms"]:
                        flush(wires[atom])
                if guard:
                    with circuit.if_test(
                        (circuit.clbits[conditional_bit], guard["value"])
                    ):
                        gate(action)
                else:
                    gate(action)
            elif kind == "CZPulse":
                gate(action)
            elif kind == "Reset":
                for atom in action["atoms"]:
                    q = wires[atom]
                    pending[q] = 0  # A local reset discards previous Z dephasing.
                    circuit.reset(q)
                    if reset_error is not None:
                        circuit.append(reset_error, [q])
            elif kind == "Measure":
                for result in action["parameters"]["results"]:
                    # Trace schema uses dictionaries, normalized by plan.py.
                    atom, mid = result["atom_id"], result["measurement_id"]
                    pending[wires[atom]] = 0  # Z noise cannot change Z readout.
                    circuit.measure(wires[atom], bits[mid])
            elif kind not in ("Load", "Store", "Move", "Wait"):
                raise ValueError(f"Unsupported physical action {kind}")

            if kind in ("Load", "Store"):
                for atom in action["atoms"]:
                    transfer_times[atom] = duration
            source = {
                "Load": "load",
                "Store": "store",
                "Move": "move",
                "CZPulse": "cz",
                "Measure": "imaging",
                "LocalU": "single",
                "Reset": "reset",
            }.get(kind)
            if source:
                participants = (
                    sorted({x for pair in action["pairs"] for x in pair})
                    if kind == "CZPulse"
                    else action["atoms"]
                )
                distances = {
                    m["atom"]: m["distance_um"] for m in action.get("movement", [])
                }
                for atom in participants:
                    probability = (
                        move_loss(distances[atom], duration, p)
                        if kind == "Move"
                        else p[source + "Loss"]
                    )
                    if probability:
                        loss_events.append(
                            {
                                "time_us": step["start_us"] + duration,
                                "atom": atom,
                                "cause": source,
                                "probability": probability,
                                "bit": conditional_bit,
                                "value": guard["value"] if guard else None,
                            }
                        )

        for atom, kind in holders.items():
            transfer_time = transfer_times.get(atom, 0)
            pending[wires[atom]] += gamma(transfer_time, p["t2Transfer"])
            pending[wires[atom]] += gamma(
                step["duration_us"] - transfer_time,
                p["t2Aod"] if kind == "aod" else p["t2Slm"],
            )
        for action in step["actions"]:
            for atom in action.get("patch", {}).get("atoms", []):
                holders[atom["id"]] = atom["holder"]["kind"]

    noise = NoiseModel()
    if p["readoutError"]:
        r = p["readoutError"]
        noise.add_all_qubit_readout_error(ReadoutError([[1 - r, r], [r, 1 - r]]))
    backend = AerSimulator(
        method="statevector",
        noise_model=noise,
        max_parallel_threads=4,
        max_parallel_shots=4,
    )
    loss_events.sort(key=lambda e: e["time_us"])
    return circuit, backend, plan, loss_events


def sample(
    n: int, values: dict | None = None, shots: int = 1000, seed: int = 17, **kwargs
) -> dict:
    """Sample noisy Born outcomes and independent first-loss events."""
    if "parameters" in kwargs:
        values = kwargs.pop("parameters")
    if kwargs:
        raise ValueError("Unknown sample arguments.")
    if n not in (15, 21) or not isinstance(shots, int) or not 1 <= shots <= 10000:
        raise ValueError("Choose N=15/21 and 1..10000 shots.")
    if not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError("seed must be a 32-bit unsigned integer.")
    p = parameters(values)
    start = time.perf_counter()
    with LOCK:
        before = prepare.cache_info().hits
        circuit, backend, plan, events = prepare(n, tuple(sorted(p.items())))
        hit = prepare.cache_info().hits > before
        prepared = time.perf_counter()
        result = backend.run(
            circuit, shots=shots, seed_simulator=seed, memory=True
        ).result()
    if not result.success:
        raise RuntimeError(str(result.status))
    raw = Counter(result.get_memory())
    rng = np.random.default_rng(np.random.SeedSequence([seed, 0x4C4F5353]))
    histogram, by_cause, by_atom = Counter(), Counter(), Counter()
    lost = 0
    for bitstring, count in sorted(raw.items()):
        probabilities = [
            e["probability"]
            if e["bit"] is None or int(bitstring[-1 - e["bit"]]) == e["value"]
            else 0
            for e in events
        ]
        cumulative = 1 - np.cumprod(1 - np.asarray(probabilities))
        indices = np.searchsorted(cumulative, rng.random(count), side="right")
        survived = int(np.count_nonzero(indices == len(events)))
        if survived:
            histogram[bitstring] += survived
        for idx, number in Counter(indices[indices < len(events)]).items():
            event = events[int(idx)]
            lost += number
            by_cause[event["cause"]] += number
            by_atom[str(event["atom"])] += number
    elapsed = time.perf_counter() - start
    return {
        "schema": "nadit.shor-shots/1",
        "n": n,
        "shots": shots,
        "seed": seed,
        "parameters": p,
        "histogram": dict(sorted(histogram.items())),
        "valid_shots": shots - lost,
        "lost_shots": lost,
        "first_loss_by_cause": dict(by_cause),
        "first_loss_by_atom": dict(by_atom),
        "elapsed_seconds": elapsed,
        "preparation_seconds": prepared - start,
        "plan_duration_us": plan["duration_us"],
        "cache_hit": hit,
        "bit_order": "highest classical bit on the left; integer=int(bitstring,2)",
        "policy": "fixed slots; false guard is idle; state-independent first-loss abort",
        "compiled_programs": 1,
        "circuit_provenance": plan.get("provenance", {}),
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=15)
    parser.add_argument("--shots", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    print(
        json.dumps(
            sample(args.n, shots=args.shots, seed=args.seed),
            ensure_ascii=False,
            indent=2,
        )
    )
