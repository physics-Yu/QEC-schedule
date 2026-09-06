from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from qec_schedule.compiler import PhysicalCircuit, PhysicalGate
from qec_schedule.hardware import ActionTiming, AtomState, HardwareState, build_initial_state, load_hardware_config
from qec_schedule.lowering import LegacyGateLowerer, RoundRobinDestinations
from tests.test_step1 import RepetitionCode
from qec_schedule.qec import create_code


CONFIG = Path(__file__).resolve().parents[1] / "configs/hardware_default.yaml"


class GateLoweringTests(unittest.TestCase):
    def setUp(self):
        self.config = load_hardware_config(CONFIG)
        self.code = create_code()
        self.state = build_initial_state(self.code, self.config)
        self.lowerer = LegacyGateLowerer(self.config.timing)

    def lower(self, *gates):
        return self.lowerer.lower(PhysicalCircuit(tuple(self.state.qubit_to_atom), gates), self.state)

    def test_cz_moves_both_atoms_to_one_pair_and_returns_home(self):
        plan = self.lower(PhysicalGate("cz", "CZ", ("L0:d0", "L0:d1")))
        self.assertEqual(len(plan.actions), 13)
        self.assertEqual(Counter(a.action_type.value for a in plan.actions), {"PICKUP":4, "MOVE":4, "DROPOFF":4, "ENTANGLE":1})
        pulse = next(a for a in plan.actions if a.action_type == "ENTANGLE")
        self.assertEqual({s.site for s in pulse.sources}, {"e0a", "e0b"})
        self.assertEqual(pulse.source_zone, "entangling")
        self.assertEqual(len(pulse.dependencies), 2)
        actions = {a.id: a for a in plan.actions}
        self.assertTrue(all(actions[d].action_type == "DROPOFF" for d in pulse.dependencies))
        for tail in plan.gate_completion["cz"]:
            self.assertEqual(actions[tail].target_zone, "storage")
        self.assertEqual(plan.home_sites, plan.planned_final_sites)
        lease = next(r for r in plan.reservations if r.id == "cz/pair")
        self.assertEqual({r.resource:r.units for r in lease.required_resources},
                         {"pair/entangling/p0":1, "zone/entangling":2, "site/e0a":1, "site/e0b":1})
        self.assertEqual(set(lease.release_after), set(plan.gate_completion["cz"]))

    def test_single_qubit_gates_are_stationary(self):
        for kind in ("H", "X", "Y", "Z", "PREPARE", "RESET"):
            plan = self.lower(PhysicalGate("g", kind, ("L0:d0",)))
            self.assertEqual(len(plan.actions), 1)
            self.assertEqual(plan.actions[0].sources, plan.actions[0].targets)
            self.assertEqual(plan.actions[0].source_zone, "storage")
            self.assertIsNone(plan.actions[0].start_time)

    def test_measurement_holds_site_until_reset_and_return(self):
        plan = self.lower(PhysicalGate("m", "MEASURE_Z", ("L0:aX0",)),
                          PhysicalGate("r", "RESET", ("L0:aX0",), ("m",)))
        self.assertEqual([a.action_type.value for a in plan.actions_for_gate("m")], ["PICKUP", "MOVE", "DROPOFF", "MEASURE"])
        reset = plan.actions_for_gate("r")
        self.assertEqual([a.action_type.value for a in reset], ["RESET", "PICKUP", "MOVE", "DROPOFF"])
        self.assertEqual(reset[0].source_zone, "measurement")
        self.assertEqual(reset[-1].target_zone, "storage")
        lease = next(r for r in plan.reservations if r.id == "m/measurement")
        self.assertEqual(lease.release_after, (reset[-1].id,))
        self.assertEqual(plan.home_sites, plan.planned_final_sites)
        terminal = self.lower(PhysicalGate("m", "MEASURE_Z", ("L0:aX0",)))
        self.assertEqual(next(r for r in terminal.reservations if r.id == "m/measurement").release_after, ())
        atom = self.state.qubit_to_atom["L0:aX0"]
        self.assertEqual(terminal.planned_final_sites[atom].zone, "measurement")

    def test_repeated_measurement_and_followup_one_qubit(self):
        plan = self.lower(PhysicalGate("m", "MEASURE_Z", ("L0:aX0",)),
                          PhysicalGate("m2", "MEASURE_Z", ("L0:aX0",), ("m",)),
                          PhysicalGate("h", "H", ("L0:aX0",), ("m2",)))
        self.assertEqual(len(plan.actions_for_gate("m2")), 1)
        h = plan.actions_for_gate("h")
        self.assertEqual([a.action_type.value for a in h], ["PICKUP", "MOVE", "DROPOFF", "SINGLE_QUBIT"])
        self.assertEqual(h[-1].source_zone, "storage")
        self.assertEqual(next(r for r in plan.reservations if r.id == "m/measurement").release_after, (h[-2].id,))

    def test_cnot_and_measure_x_basis_changes(self):
        plan = self.lower(PhysicalGate("cx", "CNOT", ("L0:d0", "L0:d1")))
        self.assertEqual(len(plan.actions), 15)
        for action in (plan.actions[0], plan.actions[-1]):
            self.assertEqual(action.action_type, "SINGLE_QUBIT")
            self.assertEqual(action.metadata["gate"], "H")
            self.assertEqual(action.atoms, (self.state.qubit_to_atom["L0:d1"],))
        mx = self.lower(PhysicalGate("mx", "MEASURE_X", ("L0:d0",)))
        self.assertEqual(mx.actions[0].metadata["gate"], "H")
        self.assertEqual(mx.actions[-1].action_type, "MEASURE")
        self.assertEqual(mx.actions[-1].metadata["basis"], "Z")

    def test_transport_durations_custody_and_configurable_timing(self):
        gate = PhysicalGate("cz", "CZ", ("L0:d0", "L0:d1"))
        circuit = PhysicalCircuit(tuple(self.state.qubit_to_atom), (gate,))
        timing = replace(self.config.timing, move_speed=2, pickup_duration=3, entangle_duration=5)
        plan = LegacyGateLowerer(timing).lower(circuit, self.state)
        by_id = {a.id:a for a in plan.actions}
        for action in plan.actions:
            if action.action_type == "MOVE":
                self.assertAlmostEqual(action.duration, action.sources[0].position.distance_to(action.targets[0].position)/2)
                lease = next(r for r in plan.reservations if r.id == action.metadata["transport_id"])
                self.assertEqual(by_id[lease.acquire_before[0]].action_type, "PICKUP")
                self.assertEqual(by_id[lease.release_after[0]].action_type, "DROPOFF")
                self.assertIn("device/aod", {r.resource for r in lease.required_resources})
            elif action.action_type == "PICKUP": self.assertEqual(action.duration, 3)
            elif action.action_type == "ENTANGLE": self.assertEqual(action.duration, 5)
        for value in (0, -1, float("nan"), True):
            with self.assertRaises(ValueError): ActionTiming(move_speed=value)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hardware.yaml"
            original = CONFIG.read_text(encoding="utf-8")
            path.write_text(original.replace("move_speed: 1.0", "move_speed: 2.5"), encoding="utf-8")
            self.assertEqual(load_hardware_config(path).timing.move_speed, 2.5)
            path.write_text(original.replace("move_speed: 1.0", "move_speed: 0"), encoding="utf-8")
            with self.assertRaises(ValueError): load_hardware_config(path)
            path.write_text(original.replace("move_speed: 1.0", "move_speeed: 1.0"), encoding="utf-8")
            with self.assertRaises(ValueError): load_hardware_config(path)

    def test_gate_dependencies_and_independent_pairs(self):
        plan = self.lower(PhysicalGate("a", "CZ", ("L0:d0", "L0:d1")),
                          PhysicalGate("b", "CZ", ("L0:d2", "L0:d3")),
                          PhysicalGate("h", "H", ("L0:d0",), ("a",)))
        a_ids = {a.id for a in plan.actions_for_gate("a")}
        self.assertFalse(any(set(b.dependencies) & a_ids for b in plan.actions_for_gate("b")))
        self.assertEqual(set(plan.actions_for_gate("h")[0].dependencies), set(plan.gate_completion["a"]))
        pulses = [a for a in plan.actions if a.action_type == "ENTANGLE"]
        self.assertEqual([a.metadata["pair_slot"] for a in pulses], ["p0", "p1"])

    def test_full_round_and_endpoint_replay_without_mutating_input(self):
        before = self.state.to_dict()
        circuit = self.code.syndrome_round()
        plan = self.lowerer.lower(circuit, self.state)
        self.assertEqual(len(plan.actions), 440)
        self.assertEqual(Counter(a.action_type.value for a in plan.actions),
                         {"PICKUP":112, "MOVE":112, "DROPOFF":112, "ENTANGLE":24,
                          "SINGLE_QUBIT":56, "PREPARE":8, "RESET":8, "MEASURE":8})
        self.assertEqual(len(plan.reservations), 144)
        # Independent serial endpoint replay: no production event engine/timing.
        snapshot = self.state
        done = set()
        for action in plan.actions:
            self.assertTrue(set(action.dependencies) <= done)
            atoms = snapshot.atoms_by_id
            updated = dict(atoms)
            for atom_id, source, target in zip(action.atoms, action.sources, action.targets):
                atom = atoms[atom_id]
                self.assertEqual(atom.position, source.position)
                if action.action_type == "PICKUP":
                    self.assertEqual((atom.zone, atom.site_id), (source.zone, source.site))
                    updated[atom_id] = replace(atom, state=AtomState.MOVING, zone=None, site_id=None)
                elif action.action_type == "MOVE":
                    self.assertEqual(atom.state, AtomState.MOVING)
                    updated[atom_id] = replace(atom, position=target.position)
                elif action.action_type == "DROPOFF":
                    self.assertEqual(atom.state, AtomState.MOVING)
                    updated[atom_id] = replace(atom, state=AtomState.IDLE, zone=target.zone, site_id=target.site)
                else:
                    self.assertEqual(atom.state, AtomState.IDLE)
                    self.assertEqual((atom.zone, atom.site_id), (source.zone, source.site))
            snapshot = replace(snapshot, atoms=tuple(updated.values()))  # Capacity + endpoint collision check.
            done.add(action.id)
        self.assertEqual(snapshot, self.state)
        self.assertEqual(before, self.state.to_dict())
        self.assertFalse(json.loads(json.dumps(plan.to_dict()))["scheduled"])
        self.assertTrue(all(a.start_time is None for a in plan.actions))

    def test_multiple_rounds_code_replacement_and_small_zones(self):
        for primitive in ("CZ", "CNOT"):
            circuit = self.code.syndrome_round(rounds=3, primitive=primitive)
            plan = self.lowerer.lower(circuit, self.state)
            self.assertEqual(len(plan.actions), 1320)
            self.assertEqual(len(plan.gate_completion), len(circuit.gates))
            self.assertEqual(plan.planned_final_sites, plan.home_sites)
        code = RepetitionCode()
        plan = self.lowerer.lower(code.syndrome_round(), build_initial_state(code, self.config))
        self.assertEqual(sum(a.action_type == "ENTANGLE" for a in plan.actions), 4)
        # Requests may share finite resources; no artificial ordering is added.
        small = replace(self.state, zones=tuple(replace(z, capacity=1) if z.id == "measurement" else z for z in self.state.zones))
        self.assertEqual(len(self.lowerer.lower(self.code.syndrome_round(), small).actions), 440)

    def test_invalid_inputs_and_unavailable_zones(self):
        gate = PhysicalGate("cz", "CZ", ("L0:d0", "L0:d1"))
        circuit = PhysicalCircuit(tuple(self.state.qubit_to_atom), (gate,))
        no_pairs = replace(self.state, zones=tuple(z for z in self.state.zones if z.id != "entangling"))
        with self.assertRaises(ValueError): self.lowerer.lower(circuit, no_pairs)
        small = replace(self.state, zones=tuple(replace(z, capacity=1) if z.id == "entangling" else z for z in self.state.zones))
        with self.assertRaises(ValueError): self.lowerer.lower(circuit, small)
        with self.assertRaises(ValueError): self.lower(PhysicalGate("p", "PREPARE", ("L0:d0",), metadata={"state":"+"}))
        with self.assertRaises(ValueError): self.lower(PhysicalGate("a", "H", ("L0:d0",)), PhysicalGate("b", "H", ("L0:d0",)))
        with self.assertRaises(ValueError): self.lowerer.lower(PhysicalCircuit(("unknown",), ()), self.state)
        lost = replace(self.state.atoms[0], state="LOST", zone=None, site_id=None)
        with self.assertRaises(ValueError): self.lowerer.lower(circuit, replace(self.state, atoms=(lost, *self.state.atoms[1:])))
        no_measure = replace(self.state, zones=tuple(z for z in self.state.zones if z.id != "measurement"))
        with self.assertRaises(ValueError): self.lowerer.lower(PhysicalCircuit(("L0:d0",), (PhysicalGate("m", "MEASURE_Z", ("L0:d0",)),)), no_measure)

    def test_placement_policy_and_ir_validation(self):
        class LastSlot(RoundRobinDestinations):
            def pair(self, gate, candidates, index): return candidates[-1]
        circuit = PhysicalCircuit(("L0:d0", "L0:d1"), (PhysicalGate("cz", "CZ", ("L0:d0", "L0:d1")),))
        plan = LegacyGateLowerer(destinations=LastSlot()).lower(circuit, self.state)
        self.assertEqual(next(a for a in plan.actions if a.action_type == "ENTANGLE").metadata["pair_slot"], "p3")
        with self.assertRaises(ValueError): replace(plan.actions[0], start_time=0)
        with self.assertRaises(ValueError): replace(plan.actions[0], duration=-1)
        with self.assertRaises(ValueError): replace(plan, actions=(replace(plan.actions[0], dependencies=("missing",)), *plan.actions[1:]))
        with self.assertRaises(ValueError): replace(plan, gate_completion={})
        with self.assertRaises(ValueError): replace(plan, gate_completion={"cz":(plan.actions[0].id,)})
        with self.assertRaises(TypeError): plan.gate_completion["cz"] = ()


if __name__ == "__main__": unittest.main()
