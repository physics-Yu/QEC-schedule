"""Physical circuits for an explicitly scoped d=3 factory protocol.

The coherent raw-state encoder is not a fault-tolerant injection claim.
Boundary gauge fixing has explicit merged checks, not a memory-round surrogate.
"""

from copy import deepcopy

from .surface17 import CHECKS, DATA, FORMALS, LOGICAL_X, LOGICAL_Z, _sign_fix_masks, _syndrome_nodes

FACTORY_BLOCKS = ("W0", "W1", "W2", "W3", "W4", "M", "Y")
BLOCKS = FACTORY_BLOCKS + ("D",)
QUBITS = tuple(f"{b}_{q}" for b in BLOCKS for q in FORMALS) + ("join_probe",)


def _rank(rows):
    basis = {}
    for row in rows:
        while row:
            bit = row.bit_length() - 1
            if bit in basis:
                row ^= basis[bit]
            else:
                basis[bit] = row
                break
    return len(basis)


def reference_css_encoder() -> dict:
    """CNOT synthesis of an invertible basis map, with arbitrary input on d0."""
    columns = [sum(1 << i for i in LOGICAL_X)]
    columns += [sum(1 << i for i in support) for _, basis, support, _ in CHECKS if basis == "X"]
    for i in range(9):
        if _rank(columns + [1 << i]) > len(columns):
            columns.append(1 << i)
        if len(columns) == 9:
            break
    rows = [sum(((column >> i) & 1) << j for j, column in enumerate(columns)) for i in range(9)]
    reduction = []
    for col in range(9):
        pivot = next(row for row in range(col, 9) if rows[row] & (1 << col))
        if pivot != col:
            # Three actual CX gates implement a SWAP; no carrier relabelling.
            for c, t in ((pivot, col), (col, pivot), (pivot, col)):
                rows[t] ^= rows[c]
                reduction.append((c, t))
        for row in range(9):
            if row != col and rows[row] & (1 << col):
                rows[row] ^= rows[col]
                reduction.append((col, row))
    assert rows == [1 << i for i in range(9)]
    return {"columns": columns, "seed": "d0", "plus_inputs": ["d1", "d2", "d3", "d4"],
            "zero_inputs": ["d5", "d6", "d7", "d8"], "cx": [list(pair) for pair in reversed(reduction)]}


def legacy_css_encoder_v2() -> dict:
    """Geometry-ranked equivalent arbitrary-state encoder (not FT injection).

    Fixed result of a bounded 3000-candidate binary synthesis (seed 704),
    minimizing CX count then Manhattan interaction length on the 3x3 patch.
    Single-qubit basis preparation and native CZ lowering are explicit.
    The old full invertible map is retained as an algebraic reference only.
    """
    reference = reference_css_encoder()
    order = [5, 6, 2, 7, 1, 4, 8, 0, 3]
    return {'columns': [reference['columns'][i] for i in order], 'seed': 'd7',
            'plus_inputs': ['d2', 'd4', 'd5', 'd8'], 'zero_inputs': ['d0', 'd1', 'd3', 'd6'],
            'cx': [[8,7],[8,6],[8,5],[8,4],[8,1],[6,5],[4,3],[4,1],[4,0],
                   [5,6],[6,5],[7,6],[7,3],[7,0],[6,7],[2,1]],
            'implementation': 'surface17_native_geometry_ranked_raw_encoder/2',
            'qualification': 'ideal_operator_map_and_device_schedule_only_not_fault_tolerant_injection'}


def css_encoder() -> dict:
    """Nine-CX arbitrary-seed isometry, selected with actual joint routing.

    Bounded reverse CSS disentangling: width 256, depth limit 14, followed by
    independent signed X/Y/Z and full stabilizer checks. Among the qualified
    candidates, this assignment uses six CZ broadcasts for one or four patches
    on the current canonical 100-us transfer model. Not a fault-tolerance claim.
    """
    gates=[[5,4],[5,2],[4,7],[1,2],[5,8],[3,4],[4,1],[6,7],[3,0]]
    columns=[]
    for i in range(9):
        x=1<<i
        for c,t in gates:
            if x>>c&1:x^=1<<t
        columns.append(x)
    return {'columns':columns,'seed':'d4','plus_inputs':['d1','d3','d5','d6'],
            'zero_inputs':['d0','d2','d7','d8'],'cx':gates,
            'implementation':'surface17_parallel_raw_encoder/3','source_CX_depth':4,
            'qualification':'signed_arbitrary_seed_isometry_and_bounded_device_schedule_not_fault_tolerant_injection'}


def merged_zz_checks(a="A", b="B") -> list[dict]:
    """Explicit gauge-fixed code. G0*G1*G2 is the logical ZZ measurement."""
    checks = []
    for name, basis, support, _ in CHECKS:
        if basis == "X" and name in {"x0", "x1"}:
            checks.append({"id": f"merged_{name}", "basis": "X", "probe": f"{a}_{name}",
                           "support": [f"{block}_d{i}" for block in (a, b) for i in support]})
        else:
            for block in (a, b):
                checks.append({"id": f"{block}_{name}", "basis": basis, "probe": f"{block}_{name}",
                               "support": [f"{block}_d{i}" for i in support]})
    for i, probe in enumerate((f"{b}_x0", f"{b}_x1", "join_probe")):
        checks.append({"id": f"g{i}", "basis": "Z", "probe": probe,
                       "support": [f"{a}_d{i}", f"{b}_d{i}"]})
    return checks


class Circuit:
    """Local template composer. Every required order is an explicit edge."""

    def __init__(self):
        self.nodes = []
        self.last = {}
        self.writers = {}
        self.barrier = []
        self.classical_frontier = []
        self.local_barriers = {}

    def add(self, id, kind, qubits=(), params=None, *, reads=(), writes=(), after=(), condition=None, metadata=None):
        reads = list(reads)
        if condition is not None and condition["bit"] not in reads:
            reads.append(condition["bit"])
        predecessors = list(after) + self.barrier
        predecessors += [self.last[q] for q in qubits if q in self.last]
        predecessors += [dep for q in qubits for dep in self.local_barriers.get(q, [])]
        predecessors += [self.writers[bit] for bit in reads]
        op = {"id": id, "kind": kind, "qubits": list(qubits), "params": dict(params or {}),
              "reads": reads, "writes": list(writes), "after": list(dict.fromkeys(predecessors)),
              "source_ids": [f"R3:T302:{id}"], "condition": deepcopy(condition)}
        if metadata is not None:
            op["metadata"] = deepcopy(metadata)
        self.nodes.append({"kind": "op", "op": op})
        for q in qubits:
            self.last[q] = id
        for bit in writes:
            self.writers[bit] = id
        if kind == "classical":
            self.classical_frontier.append(id)
        return id

    def fence(self, qubits=None):
        # Stage-internal protocol boundary; no zero-cost physical action.
        if qubits is None:
            self.barrier = list(dict.fromkeys(self.last.values())) + self.classical_frontier
        else:
            deps = list(dict.fromkeys(self.last[q] for q in qubits if q in self.last))
            for q in qubits:
                self.local_barriers[q] = deps

    def gate(self, id, name, qubits, **kwargs):
        return self.add(id, "gate", qubits, {"name": name}, **kwargs)

    def reset(self, prefix, qubits):
        for q in qubits:
            self.add(f"{prefix}_{q}", "reset", [q], {"basis": "Z"})

    def xor(self, id, reads, result):
        self.add(id, "classical", params={"operation": "xor"}, reads=reads, writes=[result])
        return result

    def syndrome(self, block, prefix, rounds=3):
        outputs = {}
        for r in range(rounds):
            p = f"{prefix}_r{r}_"
            for node in _syndrome_nodes():
                op = node["op"]
                self.add(p + op["id"], op["kind"], [f"{block}_{q}" for q in op["qubits"]], op["params"],
                         reads=[p + bit for bit in op["reads"]], writes=[p + bit for bit in op["writes"]],
                         after=[p + dep for dep in op["after"]], metadata={**op.get("metadata", {}),
                             'phase': 'SE', 'logical_block': block, 'se_round': r, 'se_instance': prefix})
            outputs = {q: p + f"m_{q}" for q in FORMALS[9:]}
        return outputs

    def prepare(self, block, state, prefix):
        if state not in {"A", "Y+", "Y-", "plus", "zero"}:
            raise ValueError("unsupported raw state")
        if state in {"zero", "plus", "Y+", "Y-"}:
            from .surface17 import _templates
            basis = "zero" if state == "zero" else "plus"
            for node in _templates()[f"s17.prepare_{basis}.v1"]["body"]:
                op = node["op"]
                condition = deepcopy(op["condition"])
                if condition:
                    condition["bit"] = prefix + "_" + condition["bit"]
                self.add(prefix + "_" + op["id"], op["kind"], [f"{block}_{q}" for q in op["qubits"]], op["params"],
                         reads=[prefix + "_" + r for r in op["reads"]], writes=[prefix + "_" + r for r in op["writes"]],
                         after=[prefix + "_" + d for d in op["after"]], condition=condition,
                         metadata={**op.get("metadata", {}), "preparation": "neutral_atom_stabilizer_projection/1",
                                   "source": "https://www.nature.com/articles/s41586-023-06927-3"})
            for q in FORMALS[9:]:
                self.add(prefix + "_service_reset_" + q, "reset", [f"{block}_{q}"], {"basis": "Z"},
                         after=[prefix + "_measure_" + q])
            self.fence([f'{block}_{q}' for q in FORMALS])
            if state in {"Y+", "Y-"}:
                self.clifford_phase(block, 1 if state == "Y+" else -1, prefix + "_phase")
            return
        enc = css_encoder()
        start = len(self.nodes)
        self.reset(prefix + "_reset", [f"{block}_{q}" for q in FORMALS])
        if state != "zero":
            self.gate(prefix + "_seed_h", "H", [f"{block}_{enc['seed']}"])
        source_gate = {"A": "T", "Y+": "S", "Y-": "SDG"}.get(state)
        if source_gate:
            self.gate(prefix + "_seed_phase", source_gate, [f"{block}_{enc['seed']}"],
                      metadata={"raw_state": state, "injection_scheme": enc['implementation'], 'fault_tolerance': 'unverified'})
        for q in enc["plus_inputs"]:
            self.gate(prefix + "_anc_h_" + q, "H", [f"{block}_{q}"])
        for n, (c, t) in enumerate(enc["cx"]):
            self.gate(f"{prefix}_encode_{n}", "CX", [f"{block}_d{c}", f"{block}_d{t}"])
        for node in self.nodes[start:]:
            node['op'].setdefault('metadata', {}).update(phase='raw_encoding', logical_block=block,
                encoder_implementation=enc['implementation'])
        self.syndrome(block, prefix + "_qec")

    def transversal(self, control, target, prefix):
        if control == target:
            raise ValueError("transversal operands alias")
        for i in range(9):
            self.gate(f"{prefix}_{i}", "CX", [f"{control}_d{i}", f"{target}_d{i}"],
                      metadata={'phase':'logical_CNOT','logical_cohort':{'schema_version':'logical-coupling-cohort/0.1',
                                'local_id':prefix,'size':9,'index':i,'operation':'CX'}})

    def logical_z(self, block, prefix, bit=None):
        for i in LOGICAL_Z:
            self.gate(f"{prefix}_{i}", "Z", [f"{block}_d{i}"],
                      condition=None if bit is None else {"bit": bit, "equals": 1})

    def read_logical(self, block, basis, prefix):
        if basis not in {"X", "Z"}:
            raise ValueError("unsupported destructive logical basis")
        if basis == "X":
            for q in DATA:
                self.gate(f"{prefix}_basis_{q}", "H", [f"{block}_{q}"])
        for q in DATA:
            self.add(f"{prefix}_read_{q}", "measure", [f"{block}_{q}"], {"basis": "Z"}, writes=[f"{prefix}_m_{q}"])
        support = LOGICAL_X if basis == "X" else LOGICAL_Z
        result = self.xor(prefix + "_parity", [f"{prefix}_m_d{i}" for i in support], prefix + "_logical")
        self.reset(prefix + "_cleanup", [f"{block}_{q}" for q in FORMALS])
        return result

    def measure_check(self, check, prefix):
        start = len(self.nodes)
        probe, basis = check["probe"], check["basis"]
        self.reset(prefix + "_reset", [probe])
        if basis == "X":
            self.gate(prefix + "_prepare", "H", [probe])
        for i, q in enumerate(check["support"]):
            pair = [probe, q] if basis == "X" else [q, probe]
            self.gate(f"{prefix}_cx{i}", "CX", pair,
                      metadata={"joint_check": check["id"], "check_weight": len(check["support"]),
                                "implementation": "boundary_gauge_fixing_v1"})
        if basis == "X":
            self.gate(prefix + "_basis", "H", [probe])
        result = prefix + "_m"
        self.add(prefix + "_read", "measure", [probe], {"basis": "Z"}, writes=[result])
        # Explicit sequential check circuit avoids an unqualified interleaving.
        self.fence()
        for node in self.nodes[start:]:
            node['op'].setdefault('metadata', {})['joint_check_instrument'] = prefix
        return result

    def joint_zz(self, a, b, prefix):
        if a == b:
            raise ValueError("joint operands alias")
        start = len(self.nodes)
        checks = merged_zz_checks(a, b)
        self.fence()
        gauges = []
        for r in range(3):
            gauges = []
            for check in checks:
                bit = self.measure_check(check, f"{prefix}_merge_r{r}_{check['id']}")
                if check["id"].startswith("g"):
                    gauges.append(bit)
        parity = self.xor(prefix + "_zz_parity", gauges, prefix + "_zz")
        # Split back to the two declared Surface-17 codes; retain all costs.
        self.fence()
        for block in (a, b):
            split = self.syndrome(block, f"{prefix}_split_{block}")
            self.fence()
            for j, mask in enumerate(_sign_fix_masks("X")):
                for i in range(9):
                    if mask & (1 << i):
                        self.gate(f"{prefix}_split_fix_{block}_{j}_{i}", "Z", [f"{block}_d{i}"],
                                  condition={"bit": split[f"x{j}"], "equals": 1})
        self.reset(prefix + "_join_cleanup", ["join_probe"])
        self.fence()
        for node in self.nodes[start:]:
            node['op'].setdefault('metadata', {})['joint_zz_geometry_scope'] = prefix
        return parity

    def clifford_phase(self, block, sign, prefix):
        if block == "Y" or sign not in (1, -1):
            raise ValueError("invalid Clifford phase target or sign")
        from .neutral_clifford import append_s_se
        append_s_se(self, block, sign, prefix)

    def cleanup_factory(self, prefix):
        self.fence()
        self.reset(prefix, [f"{b}_{q}" for b in FACTORY_BLOCKS for q in FORMALS] + ["join_probe"])


def template(id, circuit, purpose):
    return {"template_id": id, "qubits": list(QUBITS), "body": circuit.nodes,
            "metadata": {"protocol": "15to1-litinski-positive-T/1", "purpose": purpose,
                         "distance": 3, "rounds": 3,
                         "boundary": "gauge_fixing_zz_weight8" if any(n['op'].get('metadata', {}).get('joint_check') for n in circuit.nodes) else "encoded_cnot_injection_Z_readout",
                         "source": "https://arxiv.org/html/1808.02892v3#S3.SS1",
                         "injection": css_encoder()['implementation'],
                         "clifford_phase": "surface17-neutral-s-se/1",
                         "ft_qualification": "unverified", "quantum_state_simulated": False}}
