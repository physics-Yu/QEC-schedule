"""Live local Clifford frames around the existing component/event interfaces."""
from copy import deepcopy
from na_pipeline.qec.clifford_frame import CliffordFrame, realize_gate
from .window_binding import bind_physical_plan
from .scenario import make_scenario


class LogicalFrameSession:
    """The caller supplies a live EventSession; immutable modules hold no frame.

    The optional adaptive_runner must drive the existing FactoryExecution to a
    consumed token in this same session. No accepted magic is manufactured here.
    """
    def __init__(self, compiler, session):
        self.compiler, self.session = compiler, session
        self.frames = {p:CliffordFrame() for p in session.initial_state['patches']}
        self.code_states = {p:'canonical_surface17_site_binding' for p in self.frames}
        self.events = []; self.physical_plans = []; self.failure = None

    def plan(self, gate, blocks):
        if self.failure: raise ValueError('FRAME_SESSION_FAILED: inspect preserved partial history')
        if self.session.snapshot()['in_flight']: raise ValueError('FRAME_REQUIRES_COMMITTED_FRONTIER')
        if any(self.code_states.get(b)=='destructively_measured' for b in blocks) and gate!='RESET_Z':
            raise ValueError('FRAME_BLOCK_ALREADY_MEASURED')
        result,_ = realize_gate(gate,blocks,self.frames)
        result.update(run_id=self.session.run_id, frame_revision=len(self.events), time_us=self.session.now_us)
        return result

    def run_gate(self, gate, blocks, *, scenario_value=0, adaptive_runner=None):
        realization = self.plan(gate,blocks)
        if any(p['component_id'] in ('T','TDG') for p in realization['physical_components']) and adaptive_runner is None:
            raise ValueError('FRAME_ADAPTIVE_RUNNER_REQUIRED: use same-session FactoryExecution')
        _,after = realize_gate(gate,blocks,self.frames)
        start = self.session.now_us; receipts = []; last = None
        try:
            for i,p in enumerate(realization['physical_components']):
                name = p['component_id']
                if name in ('T','TDG'):
                    receipt = adaptive_runner(name,p['blocks'][0],self.session,self.compiler)
                    if receipt.get('run_id')!=self.session.run_id or receipt.get('token_status')!='consumed':
                        raise ValueError('FRAME_ADAPTIVE_CONSUMPTION_NOT_COMMITTED')
                    receipts.append(receipt); continue
                spec = self.compiler.describe(name)
                formals = list(dict.fromkeys(q['id'].rsplit('/',1)[0] for q in spec['formal_qubits']))
                if len(formals)!=len(p['blocks']): raise ValueError('FRAME_COMPONENT_BINDING_ARITY')
                binding = {q['id']:p['blocks'][formals.index(q['id'].rsplit('/',1)[0])]+'/'+q['id'].rsplit('/',1)[1]
                           for q in spec['formal_qubits']}
                namespace=f'frame:{len(self.events)}:{i}'
                dag=self.compiler.instantiate(name,qubit_bindings=binding,namespace=namespace)
                world=self.session.snapshot()['world_state']
                dag=self.compiler.resolve_geometry(dag,world)
                self.compiler.build_dependencies(dag,world)
                context=self.session.compilation_context(dag)
                plan=self.compiler.compose_recipe(dag,world,execution_context=context)
                atom=bind_physical_plan(plan,context)
                scenario=make_scenario(atom,value=scenario_value)
                self.session.submit(atom,scenario,expected_revision=context['revision']); self.session.advance()
                self.physical_plans.append({'component_id':name,'physical_plan':plan,'atom_program':atom,'scenario':scenario})
                receipts.append({'component_id':name,'atom_program_ref':atom['artifact_id'],'end_us':self.session.now_us,
                                 'action_count':len(atom['actions']),'reason':p['reason']})
                last=(name,dag)
        except Exception as error:
            self.failure={'error':str(error),'realization':realization,'committed_receipts':receipts}
            raise
        record={**realization,'kind':'frame_update' if realization['software_only'] else 'physical_realization',
                'end_us':self.session.now_us,'hardware_duration_us':self.session.now_us-start,
                'receipts':receipts,'atom_positions_changed_by_frame':False}
        if realization['observable_binding'] is not None:
            name,dag=last
            # Instantiated public ports retain the namespace-qualified result.
            result_id=dag['component_binding']['logical_result_ports']['value']
            raw=self.session.results[result_id]
            record['logical_result']={'physical_result_id':result_id,'physical_value':raw['value'],
                                      'value':raw['value'] ^ realization['observable_binding']['xor_result'],
                                      'ready_us':raw['ready_us'],'origin':'fake_plus_frame_pullback'}
            self.code_states[blocks[0]]='destructively_measured'
        if gate=='RESET_Z': self.code_states[blocks[0]]='canonical_surface17_site_binding'
        self.frames.update(after); self.events.append(record)
        return deepcopy(record)

    def snapshot(self):
        return {'schema_version':'LogicalFrameContext/0.1','run_id':self.session.run_id,
                'revision':len(self.events),'frames':{b:f.record() for b,f in self.frames.items()},
                'code_states':dict(self.code_states),'events':deepcopy(self.events),'failure':deepcopy(self.failure),
                'quantum_state_simulated':False,'hardware_executed':False}
