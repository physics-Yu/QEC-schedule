"""Tests of shared-CZ rendezvous, identity, and rejection; no compiler calls."""
import unittest
from copy import deepcopy
from relink_dual_aod_demo import link_pair, check_resources, validate_endpoints_and_pulses


def leaf(group, distance):
    atoms=['d','m'];times=[(0,1,'gate'),(1,101,'pickup'),(101,101+distance,'move'),
        (101+distance,102+distance,'gate'),(102+distance,102+2*distance,'move'),(102+2*distance,202+2*distance,'drop')]
    return [dict(id=group+str(i),kind=k,t_start_us=s,t_end_us=e,atoms=[group],
        payload=dict(name='CZ' if i==3 else 'H' if i==0 else '',aod_group=group),
        resources=['global'] if i==3 else [group]) for i,(s,e,k) in enumerate(times)]


class DualAODTests(unittest.TestCase):
    def test_both_faster_and_slower_data_wait_for_shared_resource(self):
        for distance in (5,200):
            data,magic=leaf('data',distance),leaf('magic',18)
            original=deepcopy(data);offsets,end,wait=link_pair(data,magic)
            schedule=deepcopy(data+magic)
            for a in schedule[:len(data)]:
                a['t_start_us']+=offsets[a['id']];a['t_end_us']+=offsets[a['id']]
            self.assertEqual(original,data)
            self.assertGreater(wait['outbound_wait_us'],0)
            self.assertGreaterEqual(schedule[3]['t_start_us'],magic[-1]['t_end_us'])
            self.assertLess(schedule[2]['t_start_us'],magic[4]['t_end_us'])
            check_resources(schedule)
    def test_resource_conflict_is_not_ignored(self):
        with self.assertRaisesRegex(ValueError,'RESOURCE_OVERLAP'):
            check_resources([dict(id='a',resources=['beam'],t_start_us=0,t_end_us=2),
                             dict(id='b',resources=['beam'],t_start_us=1,t_end_us=3)])
    def test_unintended_global_pair_is_rejected(self):
        atoms=[dict(atom_id=str(i),position_um=p,carrier='SLM') for i,p in enumerate([(0,0),(2,0),(10,0),(12,0)])]
        pulse=dict(id='pulse',kind='gate',t_start_us=0,t_end_us=1,payload=dict(name='CZ',pairs=[['0','1']]))
        with self.assertRaisesRegex(AssertionError,'CZ_PAIR_SET_CHANGED'):
            validate_endpoints_and_pulses([pulse],atoms)
    def test_late_capture_rejected(self):
        data=leaf('data',10);magic=leaf('magic',5)
        data[1]['t_end_us']=110
        with self.assertRaisesRegex(AssertionError,'CAPTURE_MUST_FINISH'):
            link_pair(data,magic)


if __name__=='__main__':unittest.main()
