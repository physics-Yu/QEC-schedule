"""D04 delta tests: finite declared carriers, not a full Shor pool certificate."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from na_pipeline.device import DeviceModelError, build_preinitialized_state, preinitialized_device, validate_preinitialized_state

ROOT = Path(__file__).resolve().parents[2]


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.device = preinitialized_device()
        self.example = json.loads((ROOT / 'configs/device/resource_inventory_examples.json').read_text(encoding='utf-8'))
        self.inventory = self.example['resource_inventory']

    def build(self):
        return build_preinitialized_state(self.device, self.example['patches'], self.example['placements'],
                                         placement_ref=self.example['placement_ref'], resource_inventory=self.inventory)

    def expect(self, code):
        with self.assertRaises(DeviceModelError) as caught:
            self.build()
        self.assertEqual(caught.exception.errors[0]['code'], code)

    def test_one_probe_adds_one_atom_not_seventeen(self):
        state = self.build()
        self.assertEqual(state['resource_counts']['total_atom_count'], 52)
        self.assertEqual(state['resource_counts']['patch_atom_count'], 51)
        self.assertEqual(state['resource_counts']['nonpatch_atom_count'], 1)
        probe = next(a for a in state['atoms'] if a['atom_id'] == 'atom:parity_probe0')
        self.assertIsNone(probe['patch_id'])
        self.assertIsNone(probe['local_id'])
        self.assertEqual(probe['qubit_id'], 'parity_probe0')
        self.assertEqual(probe['position_um'], [240, 120])
        self.assertEqual(probe['resource_role'], 'probe')
        self.assertEqual(len(state['slm_traps']), 52)
        self.assertEqual(validate_preinitialized_state(state, self.device), [])

    def test_factory_scratch_roles_and_empty_ready_tokens(self):
        state = self.build()
        self.assertEqual(state['patches']['F0']['resource_role'], 'factory')
        self.assertEqual(state['patches']['Y0']['resource_role'], 'scratch')
        self.assertEqual(state['ready_magic_tokens'], [])
        self.assertEqual(state['results'], {})
        self.assertEqual(state['startup_actions'], [])
        self.assertFalse(state['patches']['F0']['magic_resource_ready'])

    def test_old_patch_only_fixture_is_exactly_compatible(self):
        old = json.loads((ROOT / 'configs/device/preinitialized_state_fixture.json').read_text(encoding='utf-8'))
        rebuilt = build_preinitialized_state(self.device, **old['entry_spec'])
        self.assertEqual(rebuilt, old)
        self.assertNotIn('resource_inventory', rebuilt)
        self.assertEqual(validate_preinitialized_state(old, self.device), [])

    def test_recorded_real_algorithm_entry_still_valid_without_rerunning_placer(self):
        placement = json.loads((ROOT / 'knowledge/roles/R1/evidence/T103/full-shor-entry/patch-placement.json').read_text(encoding='utf-8'))
        self.assertEqual(validate_preinitialized_state(placement['initial_state'], self.device), [])
        self.assertEqual(len(placement['initial_state']['atoms']), 85)

    def test_patch_roles_must_cover_exactly_existing_patches(self):
        del self.inventory['patch_roles']['F0']
        self.expect('RESOURCE_PATCH_COVERAGE')

    def test_stable_slot_cannot_alias_patch_and_probe(self):
        self.inventory['nonpatch_atoms']['atom:parity_probe0']['slot_id'] = self.inventory['patch_roles']['F0']['slot_id']
        self.expect('RESOURCE_SLOT_ALIAS')

    def test_atom_qubit_and_trap_aliases_rejected(self):
        for key, value, code in [('qubit_id', 'L0/d0', 'QUBIT_ID_ALIAS'), ('trap_id', 'slm:L0/d0', 'TRAP_ID_ALIAS')]:
            with self.subTest(key=key):
                self.setUp()
                self.inventory['nonpatch_atoms']['atom:parity_probe0'][key] = value
                self.expect(code)
        self.setUp()
        spec = self.inventory['nonpatch_atoms'].pop('atom:parity_probe0')
        self.inventory['nonpatch_atoms']['atom:L0/d0'] = spec
        self.expect('ATOM_ID_ALIAS')

    def test_same_position_conflict_and_empty_patch_cell_are_distinct(self):
        self.inventory['nonpatch_atoms']['atom:parity_probe0']['position_um'] = [0, 0]
        self.expect('RESOURCE_OCCUPIED')
        self.inventory['nonpatch_atoms']['atom:parity_probe0']['position_um'] = [35, 35]
        self.expect('RESOURCE_IN_PATCH_CELL')

    def test_outside_zone_and_invalid_position(self):
        self.inventory['nonpatch_atoms']['atom:parity_probe0']['position_um'] = [240, 1010]
        self.expect('RESOURCE_OUTSIDE_ZONE')
        self.inventory['nonpatch_atoms']['atom:parity_probe0']['position_um'] = [True, 0]
        self.expect('INVALID_POSITION')

    def test_probe_can_be_explicitly_parked_in_mz(self):
        self.inventory['nonpatch_atoms']['atom:parity_probe0']['position_um'] = [240, 1020]
        state = self.build()
        trap = next(t for t in state['slm_traps'] if t['trap_id'] == 'slm:parity_probe0')
        self.assertEqual(trap['zone_id'], 'measurement')
        self.assertEqual(validate_preinitialized_state(state, self.device), [])

    def test_raw_magic_carrier_is_not_a_prepared_t_state(self):
        probe = self.inventory['nonpatch_atoms']['atom:parity_probe0']
        probe['role'] = 'raw_magic_carrier'
        self.assertEqual(self.build()['ready_magic_tokens'], [])
        probe['basis'] = 'T'
        self.expect('INITIAL_RESOURCE_STATE')

    def test_unknown_group_and_inventory_flags_rejected(self):
        self.inventory['nonpatch_atoms']['atom:parity_probe0']['aod_group'] = 'new_undeclared_aod'
        self.expect('UNKNOWN_AOD_GROUP')
        self.setUp()
        self.inventory['ready_tokens'] = ['T0']
        self.expect('RESOURCE_INVENTORY_FIELDS')

    def test_two_probes_can_share_pool_but_not_identity_or_position(self):
        p2 = deepcopy(self.inventory['nonpatch_atoms']['atom:parity_probe0'])
        p2.update(qubit_id='parity_probe1', trap_id='slm:parity_probe1', slot_id='parity:probe1', position_um=[250, 120])
        self.inventory['nonpatch_atoms']['atom:parity_probe1'] = p2
        state = self.build()
        self.assertEqual(state['resource_counts']['total_atom_count'], 53)
        self.assertEqual(state['resource_counts']['atoms_by_role']['probe'], 2)
        p2['position_um'] = [240, 120]
        self.expect('RESOURCE_OCCUPIED')

    def test_input_independence_and_inventory_hash_binding(self):
        before = deepcopy(self.example)
        first = self.build()
        self.assertEqual(before, self.example)
        self.inventory['nonpatch_atoms']['atom:parity_probe0']['position_um'] = [250, 120]
        second = self.build()
        self.assertNotEqual(first['resource_inventory_sha256'], second['resource_inventory_sha256'])
        self.assertNotEqual(first['artifact_id'], second['artifact_id'])
        first['atoms'][-1]['position_um'][0] = 999
        self.assertNotEqual(first['atoms'][-1]['position_um'], second['atoms'][-1]['position_um'])

    def test_appending_undeclared_carrier_cannot_pass_entry_validation(self):
        state = self.build()
        added = deepcopy(state['atoms'][-1]); added['atom_id'] = 'phantom'
        state['atoms'].append(added)
        self.assertTrue(validate_preinitialized_state(state, self.device))
        state = self.build(); state['resource_counts']['total_atom_count'] += 1
        self.assertTrue(validate_preinitialized_state(state, self.device))

    def test_fixture_origin_cannot_be_upgraded_by_real_placement_label(self):
        self.example['placement_ref']['fixture'] = False
        self.assertTrue(self.build()['provenance']['fixture'])
        self.inventory['provenance']['fixture'] = False
        self.assertFalse(self.build()['provenance']['fixture'])

    def test_empty_nonpatch_set_with_complete_patch_roles(self):
        self.inventory['nonpatch_atoms'] = {}
        state = self.build()
        self.assertEqual(state['resource_counts']['nonpatch_atom_count'], 0)
        self.assertEqual(len(state['atoms']), 51)

    def test_malformed_inventory_and_missing_initial_state_fail(self):
        for bad in ([], {}, None):
            if bad is None:
                probe = self.inventory['nonpatch_atoms']['atom:parity_probe0']
                del probe['basis']
                self.expect('NONPATCH_ATOM_FIELDS')
            else:
                self.inventory = bad
                self.expect('RESOURCE_INVENTORY_FIELDS')
            self.setUp()


if __name__ == '__main__':
    unittest.main()
