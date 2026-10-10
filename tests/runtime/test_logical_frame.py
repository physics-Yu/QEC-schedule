import unittest
from na_pipeline.backend import LogicalComponentCompiler
from na_pipeline.device import canonical_surface17_device, build_preinitialized_state
from na_pipeline.runtime import EventSession, LogicalFrameSession
from na_pipeline.qec.clifford_frame import CliffordFrame, realize_gate


class LogicalFrameTests(unittest.TestCase):
    def new(self):
        device=canonical_surface17_device()
        world=build_preinitialized_state(device,
            {p:{'aod_group':'data','basis':'Z','value':0} for p in ('A','B')},
            {p:{'anchor_um':[i*100.,900.],'orientation':'x_vertical_z_horizontal'} for i,p in enumerate(('A','B'))},
            placement_ref={'artifact_id':'frame-test','producer':'R0','fixture':True})
        return LogicalFrameSession(LogicalComponentCompiler(device),EventSession(device,world,run_id='frame-test'))

    def test_signed_H_and_all_24_local_cliffords(self):
        identity=CliffordFrame(); h=identity.prepend('H')
        self.assertEqual(h.observable('Y'),('Y',-1))
        self.assertEqual(h.prepend('H'),identity)
        seen={identity}; pending=[identity]
        while pending:
            f=pending.pop(0)
            for g in ('H','S'):
                nxt=f.prepend(g)
                if nxt not in seen:seen.add(nxt);pending.append(nxt)
        self.assertEqual(len(seen),24)
        for f in seen:
            restored=identity
            for g in f.word():restored=restored.prepend(g)
            self.assertEqual(f,restored)

    def test_H_H_never_creates_atom_actions_or_moves_identity(self):
        live=self.new(); before=live.session.snapshot()['world_state']
        for _ in range(2):self.assertTrue(live.run_gate('H',['A'])['software_only'])
        self.assertEqual(live.frames['A'],CliffordFrame())
        self.assertEqual(live.session.snapshot()['world_state'],before)
        self.assertEqual(live.session.now_us,0.)
        self.assertFalse(live.session.actions)

    def test_H_to_SE_maintains_actual_code_without_flushing(self):
        live=self.new();live.run_gate('H',['A']);record=live.run_gate('SE',['A'])
        self.assertFalse(record['materialized_blocks'])
        self.assertEqual(live.frames['A'].observable('Z'),('X',1))
        self.assertEqual([r['component_id'] for r in record['receipts']],['SE'])
        self.assertLessEqual(live.session.now_us,1889.)  # retain SE performance under improved endpoint selection

    def test_H_to_Z_readout_really_uses_X_chain(self):
        live=self.new();live.run_gate('H',['A']);record=live.run_gate('MEASURE_Z',['A'],scenario_value=1)
        self.assertEqual(record['observable_binding']['physical_axis'],'X')
        self.assertEqual(record['logical_result']['value'],1)
        self.assertEqual(record['receipts'][0]['component_id'],'MEASURE_X')
        with self.assertRaisesRegex(ValueError,'ALREADY_MEASURED'):live.run_gate('SE',['A'])

    def test_H_to_CZ_uses_reversed_CX_and_keeps_frame(self):
        live=self.new();live.run_gate('H',['A']);record=live.run_gate('CZ',['A','B'])
        self.assertEqual(record['physical_components'][0]['component_id'],'CX')
        self.assertEqual(record['physical_components'][0]['blocks'],['B','A'])
        self.assertFalse(record['materialized_blocks'])
        self.assertEqual(live.frames['A'].observable('Z'),('X',1))

    def test_T_requires_real_protocol_and_charges_materialization(self):
        live=self.new();live.run_gate('H',['A']);record=live.plan('T',['A'])
        self.assertEqual([p['component_id'] for p in record['physical_components']],['H','T'])
        self.assertEqual(record['materialized_blocks'],['A'])
        with self.assertRaisesRegex(ValueError,'ADAPTIVE_RUNNER_REQUIRED'):live.run_gate('T',['A'])
        self.assertEqual(live.session.now_us,0.)
