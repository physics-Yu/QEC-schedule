from dataclasses import FrozenInstanceError, replace
import json
import math
from pathlib import Path
import tempfile
import unittest

from qec_schedule.hardware import (Atom, AtomState, AtomType, Bounds, HardwareConfig, HardwareState,
                                  PairSlot, Position, TrapSite, Zone, build_initial_state, load_hardware_config)
from qec_schedule.qec import create_code
from tests.test_step1 import RepetitionCode

CONFIG = Path(__file__).resolve().parents[1] / "configs/hardware_default.yaml"


class HardwareTests(unittest.TestCase):
    def setUp(self):
        self.config = load_hardware_config(CONFIG)
        self.code = create_code()
        self.state = build_initial_state(self.code, self.config)

    def test_default_mapping_counts_and_units(self):
        self.assertEqual(len(self.state.atoms), 21)
        self.assertEqual(len(self.state.qubit_to_atom), 17)
        self.assertEqual([len(self.state.atoms_in_zone(z)) for z in ("storage", "measurement", "entangling", "reservoir")], [17, 0, 0, 4])
        self.assertEqual(sum(a.atom_type == AtomType.DATA for a in self.state.atoms), 9)
        self.assertEqual(sum(a.syndrome_basis == "X" for a in self.state.atoms), 4)
        self.assertEqual(sum(a.syndrome_basis == "Z" for a in self.state.atoms), 4)
        self.assertEqual(self.state.atom_for_qubit("L0:d0").position, Position(10, 12))
        self.assertEqual(self.state.atom_for_qubit("L0:d8").position, Position(30, 32))
        self.assertTrue(all(a.state == AtomState.IDLE for a in self.state.atoms))
        self.assertTrue(all(a.assigned_qubit is None for a in self.state.atoms if a.atom_type == AtomType.RESERVOIR))
        self.assertEqual(json.loads(json.dumps(self.state.to_dict()))["units"], {"length":"um", "time":"us"})
        self.assertEqual(self.state.to_dict(), build_initial_state(self.code, self.config).to_dict())

    def test_replaceable_code_and_explicit_placement(self):
        alt = build_initial_state(RepetitionCode(), self.config)
        self.assertEqual(set(alt.qubit_to_atom), {"b0", "b1", "b2", "a0", "a1"})
        self.assertEqual(len(alt.atoms), 9)
        renamed = build_initial_state(create_code(block_id="Other"), self.config)
        self.assertTrue(all(q.startswith("Other:") for q in renamed.qubit_to_atom))
        positions = {a.assigned_qubit: a.site_id for a in self.state.atoms if a.assigned_qubit is not None}
        positions["L0:d0"], positions["L0:d1"] = positions["L0:d1"], positions["L0:d0"]
        changed = build_initial_state(self.code, self.config, placements=positions)
        self.assertEqual(changed.atom_for_qubit("L0:d0").position, Position(20, 12))
        with self.assertRaises(ValueError): build_initial_state(self.code, self.config, placements={})
        positions["L0:d0"] = "m0"
        with self.assertRaises(ValueError): build_initial_state(self.code, self.config, placements=positions)
        positions["L0:d0"] = positions["L0:d1"]
        with self.assertRaises(ValueError): build_initial_state(self.code, self.config, placements=positions)

    def test_immutability_and_lookup_errors(self):
        with self.assertRaises(FrozenInstanceError): self.state.current_time = 2
        with self.assertRaises(FrozenInstanceError): self.state.atoms[0].position = Position(0, 0)
        with self.assertRaises(TypeError): self.state.qubit_to_atom["L0:d0"] = "other"
        with self.assertRaises(KeyError): self.state.atom_for_qubit("missing")
        with self.assertRaises(KeyError): self.state.atoms_in_zone("missing")

    def test_geometry_bounds_and_finite_values(self):
        self.assertEqual(Position(0, 0).distance_to(Position(3, 4)), 5)
        bounds = Bounds(0, 0, 10, 10)
        self.assertTrue(bounds.contains(Position(0, 10)))
        self.assertFalse(bounds.contains(Position(10.1, 0)))
        self.assertFalse(bounds.overlaps(Bounds(10, 0, 20, 10)))
        for bad in (math.nan, math.inf, True, "1"):
            with self.assertRaises(ValueError): Position(bad, 0)
            with self.assertRaises(ValueError): replace(self.state, current_time=bad)
        with self.assertRaises(ValueError): Bounds(0, 0, 0, 1)
        with self.assertRaises(ValueError): replace(self.state, current_time=-1)
        with self.assertRaises(ValueError): replace(self.state, min_atom_separation=0)

    def test_capacity_and_zone_overlap(self):
        storage, *others = self.config.zones
        too_small = replace(storage, capacity=16)
        config = replace(self.config, zones=(too_small, *others))
        with self.assertRaises(ValueError): build_initial_state(self.code, config)
        with self.assertRaises(ValueError): replace(self.state, zones=config.zones)
        with self.assertRaises(ValueError): replace(storage, capacity=18)
        with self.assertRaises(ValueError): replace(storage, capacity=True)
        with self.assertRaises(ValueError): replace(self.config, reservoir_atoms=7)
        overlap = replace(others[0], bounds=Bounds(0, 0, 45, 99))
        with self.assertRaises(ValueError): replace(self.config, zones=(storage, overlap, *others[1:]))

    def test_sites_pairs_and_operation_capabilities(self):
        storage = self.config.zones[0]
        entangle = self.state.zones_by_id["entangling"]
        self.assertTrue(storage.allows("LOCAL_1Q"))
        self.assertFalse(storage.allows("ENTANGLE"))
        self.assertEqual(len(entangle.pair_slots), 4)
        with self.assertRaises(ValueError): replace(storage, sites=(TrapSite("bad", Position(1000, 0)),) + storage.sites[1:])
        with self.assertRaises(ValueError): replace(storage, sites=(storage.sites[0],) + storage.sites[:-1])
        with self.assertRaises(ValueError): replace(entangle, pair_slots=(PairSlot("bad", ("e0a", "unknown")),))
        with self.assertRaises(ValueError): replace(entangle, pair_slots=entangle.pair_slots + (PairSlot("bad", ("e0a", "e1a")),))
        with self.assertRaises(ValueError): replace(storage, allowed_operations=frozenset(("ENTANGLE",)))
        with self.assertRaises(ValueError): replace(storage, allowed_operations=frozenset(("MEASURE",)))

    def test_duplicate_ids_and_occupancy(self):
        atom = self.state.atoms[0]
        with self.assertRaises(ValueError): replace(self.state, atoms=self.state.atoms + (atom,))
        with self.assertRaises(ValueError): replace(self.state, atoms=self.state.atoms + (replace(atom, atom_id="other"),))
        occupant = replace(atom, atom_id="other", assigned_qubit="other")
        with self.assertRaises(ValueError): replace(self.state, atoms=self.state.atoms + (occupant,))
        with self.assertRaises(ValueError): replace(self.state, zones=self.state.zones + (self.state.zones[0],))
        measurement = self.state.zones_by_id["measurement"]
        conflicting = replace(measurement, sites=(replace(measurement.sites[0], id="s0"), *measurement.sites[1:]))
        with self.assertRaises(ValueError): replace(self.state, zones=tuple(conflicting if z.id == measurement.id else z for z in self.state.zones))

    def test_positions_and_separation(self):
        atom = self.state.atoms[0]
        for bad in (replace(atom, position=Position(11, 12)), replace(atom, zone="missing"), replace(atom, site_id="m0")):
            with self.assertRaises(ValueError): replace(self.state, atoms=(bad, *self.state.atoms[1:]))
        with self.assertRaises(ValueError): replace(self.state, min_atom_separation=5)
        moving = Atom("moving", "other", "DATA", Position(10.5, 12), None, None, "MOVING")
        with self.assertRaises(ValueError): replace(self.state, atoms=self.state.atoms + (moving,))
        apart = replace(moving, position=Position(50, 50))
        updated = replace(self.state, atoms=self.state.atoms + (apart,))
        self.assertEqual(len(updated.atoms_in_zone("storage")), 17)

    def test_state_semantics_and_lost_occupancy(self):
        atom = self.state.atoms[0]
        with self.assertRaises(ValueError): replace(atom, state=AtomState.MOVING)
        with self.assertRaises(ValueError): replace(self.state, atoms=(replace(atom, state="MEASURING"), *self.state.atoms[1:]))
        lost = replace(atom, state="LOST", zone=None, site_id=None)
        updated = replace(self.state, atoms=(lost, *self.state.atoms[1:]))
        self.assertEqual(len(updated.atoms_in_zone("storage")), 16)
        self.assertEqual(updated.qubit_to_atom[atom.assigned_qubit], atom.atom_id)
        with self.assertRaises(ValueError): replace(atom, assigned_qubit=None)
        with self.assertRaises(ValueError): replace(atom, syndrome_basis="X")
        with self.assertRaises(ValueError): replace(self.state.atoms[-1], assigned_qubit="L0")

    def test_strict_yaml_rejects_typos_units_and_duplicate_keys(self):
        original = CONFIG.read_text(encoding="utf-8")
        bad_contents = (
            original + "\nreservoir_atoms: 2\n",
            original.replace("length: um", "length: mm"),
            original.replace("capacity: 17", "capcity: 17"),
            original.replace("schema_version: 1", "schema_version: true"),
            original.replace("[10, 12]", "[10]"),
            "!!python/object/apply:os.system ['echo forbidden']",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hardware.yaml"
            for content in bad_contents:
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError): load_hardware_config(path)


if __name__ == "__main__":
    unittest.main()
