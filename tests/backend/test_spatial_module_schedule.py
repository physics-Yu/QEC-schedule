"""Real two-AOD transport overlap must still pass independent event geometry."""
import unittest
from na_pipeline.backend import LogicalComponentCompiler
from na_pipeline.backend.compiled_modules import CompiledModuleLibrary
from na_pipeline.device import canonical_surface17_device, build_preinitialized_state
from na_pipeline.runtime import run, make_scenario
from na_pipeline.validation.dag_physical import validate_physical_plan


class SpatialScheduleTests(unittest.TestCase):
    def exercise(self, separate=True):
        device = canonical_surface17_device()
        world = build_preinitialized_state(device,
            {p:dict(aod_group=g,basis='Z',value=0) for p,g in [('a','data'),('b','magic' if separate else 'data')]},
            {p:dict(anchor_um=[x,900],orientation='x_vertical_z_horizontal') for p,x in [('a',0),('b',200)]},
            placement_ref=dict(artifact_id='test',producer='R0',fixture=True))
        front = LogicalComponentCompiler(device)
        dags=[]
        for p in ('a','b'):
            formals=front.describe('MEASURE_Z')['formal_qubits']
            dags.append(front.instantiate('MEASURE_Z',namespace=p,
                qubit_bindings={q['id']:p+'/'+q['id'].rsplit('/',1)[1] for q in formals}))
            for q in dags[-1]['qubits']: q['aod_group']='data' if p=='a' or not separate else 'magic'
        lib=CompiledModuleLibrary(device);lib.spatial_parallel=True
        plan=lib.compose_recipe(dags,world,build_missing=True)
        atom=plan['atom_program'];trace=run(atom,make_scenario(atom),device)
        report=validate_physical_plan(plan,device,trace=trace)
        self.assertTrue(report['passed'],report['failures'])
        return atom

    def test_two_aod_readouts_overlap_with_full_validation(self):
        atom=self.exercise()
        moves={g:[a for a in atom['actions'] if a['kind']=='move' and a['payload']['aod_group']==g] for g in ('data','magic')}
        self.assertTrue(any(max(a['t_start_us'],b['t_start_us'])<min(a['t_end_us'],b['t_end_us'])
                            for a in moves['data'] for b in moves['magic']))

    def test_one_aod_does_not_independently_move_two_arrays(self):
        atom=self.exercise(False)
        moves=[a for a in atom['actions'] if a['kind']=='move']
        for i,a in enumerate(moves):
            for b in moves[i+1:]:
                self.assertFalse(max(a['t_start_us'],b['t_start_us'])<min(a['t_end_us'],b['t_end_us']))

if __name__=='__main__': unittest.main()
