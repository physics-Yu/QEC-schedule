"""Surface-17 S-SE in the project's row-major code convention.

The mid-cycle construction follows Chen et al., arXiv:2412.01391v1,
Fig. 2. Transposing their code coordinates yields the existing SE order.
Only gate connectivity is specified here: the physical compiler must find
legal routes on the actual device, with no assumed diagonal AOD extension.
"""
from .surface17 import FORMALS, _syndrome_nodes

VERSION = "surface17-neutral-s-se/1"
SOURCE = "https://arxiv.org/html/2412.01391v1"
FOLD_CZ = (("d0", "d8"), ("d1", "d5"), ("d3", "d7"), ("x0", "x2"))
FOLD_S = ("d2", "d4", "d6")
FOLD_SDG = ("z1", "z2")


def append_s_se(circuit, block, sign, prefix):
    if sign not in (-1, 1):
        raise ValueError("S-SE sign must be +1 or -1")
    inserted = False
    for node in _syndrome_nodes():
        op = node["op"]
        if op.get("metadata", {}).get("syndrome_layer") == 2 and not inserted:
            # The morphing operation depends on the COMPLETE half-cycle,
            # including operations on qubits disjoint from its own support.
            circuit.fence([f'{block}_{q}' for q in FORMALS])
            meta = {"protocol": VERSION, "source": SOURCE, "se_stage": "half_cycle_fold"}
            for i, (a, b) in enumerate(FOLD_CZ):
                circuit.gate(f"{prefix}_fold_cz{i}", "CZ", [f"{block}_{a}", f"{block}_{b}"], metadata=meta)
            for qs, positive in ((FOLD_S, True), (FOLD_SDG, False)):
                name = "S" if (sign == 1) == positive else "SDG"
                for q in qs:
                    circuit.gate(f"{prefix}_fold_{q}", name, [f"{block}_{q}"], metadata=meta)
            circuit.fence([f'{block}_{q}' for q in FORMALS])
            inserted = True
        circuit.add(prefix + "_" + op["id"], op["kind"], [f"{block}_{q}" for q in op["qubits"]], op["params"],
                    reads=[prefix + "_" + r for r in op["reads"]], writes=[prefix + "_" + r for r in op["writes"]],
                    after=[prefix + "_" + d for d in op["after"]], metadata={**op.get("metadata", {}), "protocol": VERSION, "source": SOURCE})
    for q in FORMALS[9:]:
        circuit.add(prefix + "_service_reset_" + q, "reset", [f"{block}_{q}"], {"basis": "Z"},
                    after=[prefix + "_measure_" + q])
    circuit.fence([f'{block}_{q}' for q in FORMALS])
