"""Basic complete Shor driver: opaque reusable components, one committed frontier."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from na_pipeline.qec import materialize_physical_node
from .pipeline import HierarchicalPipeline, save_artifact
from .engine import digest
from .errors import fail


class ComponentPipeline(HierarchicalPipeline):
    """Use existing factory lifecycle unchanged; no new cross-component optimizer."""
    def step(self):
        if self.factory is not None or self.exhausted or self.scheduler.snapshot()['complete']:
            return super().step()
        skips = self.scheduler.commit_ready_skips()
        if skips:
            self._persist_frontier()
            return {'kind': 'logical_skips', 'count': len(skips), 'time_us': self.session.now_us}
        ready = self.scheduler.ready_set()
        if not ready:
            fail('PIPELINE_NO_READY_NODE', 'No causal component is ready')
        static = [n for n in ready if self.scheduler.nodes[n]['operation'] not in ('T', 'TDG')]
        if not static:
            return super().step()
        # Basic baseline: reuse whole calls. A ready call runs to its boundary.
        # Factory internals retain their already compiled parallel operations.
        chosen = [static[0]]
        graph = materialize_physical_node(self.bundle, chosen[0])
        if graph['operation'] in ('S', 'SDG'):
            # Current S-SE has exactly one patch and no Y/probe scratch.
            # The legacy resource bundle retains the pool for T; do not lease
            # unused scratch or invent cleanup operations for this component.
            target = self.scheduler.nodes[chosen[0]]['patch_operands']['block']
            if {q['block_id'] for q in graph['qubits']} != {target}:
                fail('PIPELINE_S_COMPONENT_SUPPORT', 'S-SE must use only its actual target patch')
            graph['required_leases'] = [target]
            graph['logical_binding']['resource_binding_correction'] = 'surface17_s_se_uses_no_phase_scratch'
        context, plan, atom = self._plan([graph])
        proposal = self.scheduler.propose_joint(plan)
        scenario = self._scenario([graph], atom)
        self.session.submit(atom, scenario, expected_revision=context['revision'])
        self.scheduler.reserve_joint(plan, proposal)
        self._advance_window(atom); self.scheduler.advance(self.session.now_us)
        if any(r not in self.session.results for r in graph['result_producers']):
            fail('PIPELINE_RESULTS_NOT_COMMITTED', 'Component results must actually publish')
        nid = chosen[0]
        summary = plan['node_summaries'][graph['artifact_id']]
        end = max([self.session.completed[a] for a in summary['action_ids']]
                  + [self.session.results[r]['ready_us'] for r in graph['result_producers']])
        self.scheduler.complete(nid, {'node_id': nid, 'completed_us': end,
            'physical_plan_ref': atom['artifact_id'], 'event_trace_ref': self.session.run_id+'/trace/'+str(self.session.revision)},
            {r: self.session.results[r] for r in self.scheduler.nodes[nid]['writes']})
        self._archive_window(plan, atom, scenario, context)
        self._persist_frontier()
        return {'kind': 'logical_component', 'logical_nodes': chosen,
                'operation': graph['operation'], 'time_us': self.session.now_us, 'windows': self.window_count}

    def _archive_window(self, plan, atom, scenario, context):
        stem = f'window-{self.window_count:07d}'
        ref = save_artifact(self.out/'windows'/(stem+'-'+digest(atom)[:16]+'.json.gz'),
            {'physical_plan': plan, 'atom_program': atom, 'scenario': scenario, 'context': context}, immutable=True)
        # A following adaptive stage may still read an earlier physical result.
        # Retain all results within an active factory, then retire its history.
        keep = set(self.logical['result_types'])
        if self.factory is not None:
            keep.update(self.session.results)
        record = self.session.retire_committed(self.out/'history'/(stem+'.json.gz'), keep_result_ids=keep)
        index = {'window': ref, 'history': record, 'index': self.window_count,
                 'logical_nodes': [d.get('logical_binding', {}).get('logical_node_id') for d in plan['physical_dags']],
                 'operations': [d['operation'] for d in plan['physical_dags']],
                 'start_us': context['time_us'], 'end_us': self.session.now_us,
                 'actions': len(atom['actions']), 'recipe_id': plan.get('strategy_binding', {}).get('strategy_id')}
        save_artifact(self.out/'window-index'/(stem+'.json'), index, immutable=True)
        self.window_count += 1
        return ref

    def status(self):
        result = super().status()
        result.update(pipeline_mode='opaque_component_baseline',
            cross_component_optimization=False, component_internal_source_changed=False,
            component_pipeline_source_hash=sha256(Path(__file__).read_bytes()).hexdigest())
        return result
