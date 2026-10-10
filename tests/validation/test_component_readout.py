import unittest
from na_pipeline.validation.dag_core import DAGAudit
from na_pipeline.validation.strategy_groups import group_metrics


class ComponentReadoutTimingTests(unittest.TestCase):
    def check(self,move_start):
        def action(identity,kind,start,end,**payload):
            return {'id':identity,'kind':kind,'atoms':['a'],'t_start_us':start,'t_end_us':end,'payload':payload,'resources':['a']}
        actions=[action('drop','drop',0,10),action('m','measure',10,20,result_id='r',result_ready_us=20),
                 action('pick','pickup',20,120,group_id='g',purpose='rigid_measurement_return'),
                 action('reset','reset',120,121,carrier_at_reset={'a':'AOD'}),action('return','move',move_start,140,group_id='g',purpose='rigid_measurement_return')]
        member={'physical_qubit_id':'q','measurement_op_id':'source-m','result_id':'r','post_readout_reset_op_id':'source-reset'}
        plan={'actions':actions,'source_map':{'source-m':['m'],'source-reset':['reset']},'initial_state':{'atoms':[{'qubit_id':'q','atom_id':'a'}]}}
        physical={'strategy_contract':{'groups':[{'group_id':'g','purpose':'maintenance_readout','members':[member]}]}}
        audit=DAGAudit('test',{});group_metrics(audit,plan,physical)
        return audit.failures

    def test_stationary_pickup_then_aod_reset_then_move(self):
        self.assertEqual(self.check(121),[])

    def test_return_translation_before_reset_remains_rejected(self):
        self.assertIn('GROUP_RETURN_BEFORE_RESET',[f['code'] for f in self.check(120)])

    def test_factory_original_service_resets_are_not_counted_twice(self):
        from copy import deepcopy
        from na_pipeline.qec import build_factory15to1_protocol,build_factory_physical_dag
        from na_pipeline.validation.stream_factory import _template
        protocol=build_factory15to1_protocol();dag=build_factory_physical_dag(protocol,'initialize')
        audit=DAGAudit('factory-source',{});_template(audit,dag,protocol)
        self.assertEqual(audit.failures,[])
        broken=deepcopy(dag);broken['nodes'].pop(0)
        audit=DAGAudit('factory-source-negative',{});_template(audit,broken,protocol)
        self.assertTrue(audit.failures)
