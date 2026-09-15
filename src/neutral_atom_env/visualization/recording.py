"""Read-only simulation observer. Static geometry once, changed atoms per event."""
from collections import Counter
from math import ceil, floor
import json
from pathlib import Path
from neutral_atom_env.replay.serializer import primitive, canonical_json
from neutral_atom_env.replay.trajectory import axes_from_dict, target_axes
from neutral_atom_env.domain.models import Position2D
from neutral_atom_env.domain.operations import TaskIntent
from neutral_atom_env.visualization.theme import VisualTheme
from neutral_atom_env.visualization.summary import operation_category, movement_mode, summarize_intervals
from neutral_atom_env.simulation.quantum_effects import condition_applies
from neutral_atom_env.statistics import AtomStatistics


class VisualRecorder:
    def __init__(self,state,theme=None):
        self.theme=theme or VisualTheme.load()
        self.backend=state.hardware.backend
        world=state.world;s=world.grid_spacing_um
        def axis(lo,hi,origin):
            return [origin+i*s for i in range(ceil((lo-origin)/s),floor((hi-origin)/s)+1)]
        xs=axis(world.bounds.lower.x_um,world.bounds.upper.x_um,world.grid_origin.x_um)
        ys=axis(world.bounds.lower.y_um,world.bounds.upper.y_um,world.grid_origin.y_um)
        from neutral_atom_env.hardware.trap_spacing import minimum_trap_spacing
        self.scene=primitive({'bounds':world.bounds,'spacing_um':s,'grid_x':xs,'grid_y':ys,'slm_clearance_um':state.hardware.slm_clearance_um,'aod_minimum_spacing_um':minimum_trap_spacing(state.hardware),'raman_minimum_separation_um':state.hardware.raman_minimum_separation_um,
            'candidates':[Position2D(x,y) for x in xs for y in ys if world.is_candidate_site(Position2D(x,y))],
            'zones':world.zones,'traps':tuple(t for _,t in sorted(world.traps.items()))})
        self.frames=[];self.operations=[];self.plans={};self._atoms={};self._operation_keys=set();self._last_plan=None
        self._initial_time=state.time_us;self._version=None;self.metrics={}
        self._slm=None
        self.atom_statistics=AtomStatistics(state.atoms,state.dag.circuit.gates)
        self._statistics_unavailable=None
        self.observe(state)

    def observe(self,state,event=None):
        """Pass directly to EagerScheduler.run(on_event=...). Does not retain state or trace."""
        if self._version is not None and state.version<=self._version:
            raise ValueError('VisualRecorder requires increasing committed versions')
        if self.frames and state.time_us<self.frames[-1]['time']:
            raise ValueError('VisualRecorder requires monotonic simulation time')
        self._version=state.version
        if self.atom_statistics is not None:
            for raw in state.trace.records[self.atom_statistics.processed_records:]:
                record=json.loads(raw)
                if record['event']['event_type'].startswith('gate_'):
                    # LogicalTestExecutor demonstrations contain no physical execution.
                    self._statistics_unavailable='Logical-only trace has no physical atom accounting'
                    self.atom_statistics=None
                    break
                self.atom_statistics.consume(record)
            if self.atom_statistics is not None and not state.trace.records:
                self.atom_statistics.time_us=state.time_us
        runtime=state.active_plan
        if runtime:
            self._last_plan=runtime.plan
            if runtime.plan.id not in self.plans:
                from neutral_atom_env.hardware import get_backend
                from neutral_atom_env.domain.aod import motion_target
                plan=runtime.plan;axes=state.aod.configured(plan.initial_aod_configuration)
                loaded={q:h.holder_id for q,h in (plan.initial_placement or ()) if h.holder_type.value=='mobile'}
                paths={q:[axes.position(cell)] for q,cell in loaded.items()}
                for b in plan.bindings:paths.setdefault(b.atom_id,[])
                for op in plan.operations:
                    if op.operation_type.value=='entangling_pulse':break
                    if op.operation_type.value=='aod_load':
                        loaded.update({b.atom_id:b.cell for b in (op.transfer_bindings or plan.bindings)})
                        for b in (op.transfer_bindings or plan.bindings):paths[b.atom_id].append(axes.position(b.cell))
                    elif op.operation_type.value in ('aod_park','aod_offload'):
                        for b in (op.transfer_bindings or plan.bindings):loaded.pop(b.atom_id,None)
                    elif op.operation_type.value=='aod_recapture':
                        loaded.update({b.atom_id:b.cell for b in op.transfer_bindings})
                    elif op.operation_type.value=='aod_move':
                        axes=get_backend(state.hardware).target_aod(axes,motion_target(op))
                        if loaded:
                            for q,cell in loaded.items():paths.setdefault(q,[]).append(axes.position(cell))
                self.plans[plan.id]=primitive({'id':plan.id,'planner_id':plan.planner_id,'paths':paths,
                    'gate_ids':sorted(plan.intent.gate_ids),
                    'requested':sorted(plan.requested_atom_ids),'gate_id':next(iter(sorted(plan.intent.gate_ids)),None) if len(plan.intent.gate_ids)==1 else None,
                    'task_id':plan.intent.task_id if isinstance(plan.intent,TaskIntent) else None,
                    'task_phase':plan.intent.phase if isinstance(plan.intent,TaskIntent) else None,
                    'operation_intervals':plan.operation_intervals,'execution_mode':plan.execution_mode})
        active=self._last_plan
        gate_id=next(iter(sorted(active.intent.gate_ids)),None) if active and len(active.intent.gate_ids)==1 else None
        if runtime and runtime.plan.execution_mode=='scheduled':
            gate_id=next((o.gate_id for o in runtime.plan.operations if o.id in dict(runtime.running_operations) and o.gate_id),None)
        gate=state.dag.nodes[gate_id] if gate_id else None
        activity={q:('controlling' if not condition_applies(state,node.gate) else 'measuring' if node.gate.gate_type in {'MEASURE','MZ'} else 'resetting' if node.gate.gate_type=='RESET' else 'gating')
                  for node in state.dag.nodes.values() if node.status.value=='running' for q in node.gate.qubit_ids}
        aod=primitive(state.aod)
        source_axes=state.aod.configuration()
        end_axes=target_axes(aod,primitive(runtime.plan.operations[runtime.operation_index])) if state.aod.is_moving and runtime else None
        updates=[]
        for key,atom in sorted(state.atoms.items()):
            holder=state.placement.atom_to_holder[key]
            actually_moving=holder.holder_type.value=='mobile' and state.aod.is_moving
            if actually_moving and end_axes:
                cell=holder.holder_id
                actually_moving=(abs(source_axes.x_um[cell.column]-end_axes.x_um[cell.column])>=1e-12
                                 or abs(source_axes.y_um[cell.row]-end_axes.y_um[cell.row])>=1e-12)
            value=primitive({'id':key,'holder':holder,'position':state.placement.position(key,state.world,state.aod),
                'activity':activity.get(key,'lost' if holder.holder_type.value=='lost' else
                       'moving' if actually_moving else 'idle'),
                'measured':atom.measured})
            if self._atoms.get(key)!=value:updates.append(value);self._atoms[key]=value
        aod=primitive(state.aod);movement=None
        running = ([(o,t) for key,t in runtime.running_operations for o in runtime.plan.operations if o.id==key]
                   if runtime and runtime.plan.execution_mode=='scheduled' else
                   [(runtime.plan.operations[runtime.operation_index],runtime.operation_started_us)]
                   if runtime and runtime.operation_started_us is not None else [])
        for op,started in running:
            value=primitive(op);kind=op.operation_type.value
            if kind=='aod_move':
                movement={'start':started,'duration':op.duration_us,'target':value['target_pose'],
                    'target_axes':primitive(target_axes(aod,value)),'profile':'cubic' if self.backend in {'row_column','row_column_orthogonal'} else 'linear'}
            key=(runtime.plan.id,op.id)
            if key not in self._operation_keys:
                self._operation_keys.add(key)
                effect_id=op.gate_id if runtime.plan.execution_mode=='scheduled' else gate_id
                effect_ids=op.effect_gate_ids or ((effect_id,) if effect_id else ())
                effect=state.dag.nodes.get(effect_id or next(iter(effect_ids),None))
                applied_by_gate={g:condition_applies(state,state.dag.nodes[g].gate) for g in effect_ids}
                applied=any(applied_by_gate.values()) if effect_ids else True
                record={'operation_type':kind,'moving_atom_ids':tuple(state.placement.mobile_occupancy.values()),
                        'applied':applied,
                        'source_configuration':primitive(state.aod.configuration()),
                        'target_configuration':primitive(target_axes(aod,value)) if kind=='aod_move' else None}
                op_index=runtime.plan.operations.index(op)
                pulse_seen=any(o.operation_type.value=='entangling_pulse' for o in runtime.plan.operations[:op_index])
                phase=op.task_phase or (active.intent.phase if isinstance(active.intent,TaskIntent) else None)
                interval=next((i for i in active.operation_intervals if i.operation_id==op.id),None)
                self.operations.append({'index':len(self.operations),'label':op.label,'kind':kind,
                    'start':started,'end':started+op.duration_us,
                    'plan_id':runtime.plan.id,'gate_id':effect_id,'captured':sorted(b.atom_id for b in op.transfer_bindings) if op.transfer_bindings else sorted(active.captured_atom_ids),
                    'gate_ids':list(effect_ids),'batch_size':len(effect_ids),'applied':applied,'measurement_results':{},
                    'planner_id':runtime.plan.planner_id,'transfer_phase':op.transfer_phase,
                    'gate_type':effect.gate.gate_type if effect else None,
                    'qubit_ids':[q for g in effect_ids for q in state.dag.nodes[g].gate.qubit_ids],
                    'intended_pairs':[list(state.dag.nodes[g].gate.qubit_ids) for g in effect_ids] if kind=='entangling_pulse' else [],
                    'parameters':list(effect.gate.parameters) if effect else [],
                    'u_parameters_rad':effect.gate.u_parameters if effect and kind=='raman_rotation' else None,
                    'target_holders':primitive({q:state.placement.atom_to_holder[q] for g in effect_ids for q in state.dag.nodes[g].gate.qubit_ids}) if effect and kind=='raman_rotation' else {},
                    'task_id':active.intent.task_id if isinstance(active.intent,TaskIntent) else None,
                    'task_phase':phase,'effect_gate_id':op.gate_id,'depends_on':list(op.depends_on),
                    'resources':list(interval.resources) if interval else list(active.resources),
                    'category':operation_category(record,pulse_seen or phase=='cleanup'),'mode':movement_mode(record),
                    'moving_count':len(state.placement.mobile_occupancy) if kind=='aod_move' else 0})
                if kind=='raman_rotation' and len(effect_ids)>1:
                    self.operations[-1].update({
                        'applied_by_gate':applied_by_gate,
                        'applied_gate_ids':[g for g in effect_ids if applied_by_gate[g]],
                        'gate_qubits':{g:list(state.dag.nodes[g].gate.qubit_ids) for g in effect_ids},
                        'u_parameters_by_gate':{g:list(state.dag.nodes[g].gate.u_parameters) for g in effect_ids},
                    })
        for recorded in self.operations:
            if recorded['kind']=='measurement':
                recorded['measurement_results']={g:state.measurement_results[g] for g in recorded['gate_ids'] if g in state.measurement_results}
                flips={g:state.dag.nodes[g].gate.readout_flip for g in recorded['gate_ids']}
                if any(flips.values()):
                    recorded['readout_flips']=flips
                    recorded['measurement_true_results']={g:bit ^ int(flips[g])
                        for g,bit in recorded['measurement_results'].items()}
        counts=Counter(node.status.value for node in state.dag.nodes.values())
        running_gate_ids=[g for op,_ in running for g in op.effect_gate_ids]
        ready=[g.id for g in state.dag.ready_gates()]
        slm=dict(state.slm_enabled)
        slm_update=slm if slm!=self._slm else None
        self._slm=slm
        self.frames.append({'time':state.time_us,'version':state.version,'atom_updates':updates,'plan_id':active.id if active else None,
            'aod':aod,'axes':primitive(axes_from_dict(aod)),'movement':movement,
            'slm_enabled':slm_update,'transfer':primitive(state.transfer),
            'gate_status':'running' if running_gate_ids else gate.status.value if gate else 'idle',
            'active_gate_ids':running_gate_ids,
            'measurement_results':dict(state.measurement_results),'quantum_tracking':state.quantum_state is not None,
            'gate_label':('Parallel '+state.dag.nodes[running_gate_ids[0]].gate.gate_type+' × '+str(len(running_gate_ids))+' · '+', '.join(running_gate_ids)) if len(running_gate_ids)>1 else
                (f"{gate_id} {gate.gate.gate_type}" + (f"[{', '.join(f'{v:.5g}' for v in gate.gate.parameters)} rad]" if gate.gate.parameters else '') + f"({', '.join(gate.gate.qubit_ids)})") if gate else '未执行门操作',
            'active_operations':[o.id for o,_ in running],
            'requested':list(gate.gate.qubit_ids) if gate else sorted(active.requested_atom_ids) if active else [],
            'ready_frontier':ready[:20],'ready_count':len(ready),'gate_counts':dict(counts),
            'gate_statuses':{k:n.status.value for k,n in list(state.dag.nodes.items())[:12]},
            'label':state.trace.records and json.loads(state.trace.records[-1]).get('label','') or 'Initial'})
        self.metrics=state.metrics()

    def payload(self):
        start=max(self._initial_time,self.metrics.get('episode_start_us') or self._initial_time)
        summary=summarize_intervals(self.operations,start,self.frames[-1]['time'],self.metrics,allow_overlap=any(p.get('execution_mode')=='scheduled' for p in self.plans.values()))
        first=self.operations[0] if self.operations else {}
        # Serialization detaches caller-owned data from this recorder's internal buffers.
        return json.loads(canonical_json({'format':'neutral-atom-view/2','scene':self.scene,'frames':self.frames,
            'theme':self.theme,'backend':self.backend,'duration':self.frames[-1]['time'],'start_time':self._initial_time,
            'operations':self.operations,'plans':list(self.plans.values()),'summary':summary,
            'atom_statistics':self.atom_statistics.report() if self.atom_statistics is not None else None,
            'atom_statistics_unavailable':self._statistics_unavailable,'requested':self.frames[0]['requested'],
            'captured':first.get('captured',[]),'gate_label':self.frames[0]['gate_label']}))

    def write(self,path):
        from neutral_atom_env.visualization.viewer import write_html
        return write_html(self.payload(),path)

    def write_json(self,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(canonical_json(self.payload()),encoding='utf-8')
        return path

    @classmethod
    def from_snapshots(cls,snapshots,theme=None):
        from neutral_atom_env.simulation.state import SimulationState
        iterator=iter(snapshots)
        def restore(value):return SimulationState.restore(value if isinstance(value,str) else canonical_json(value))
        recorder=cls(restore(next(iterator)),theme)
        for saved in iterator:recorder.observe(restore(saved))
        return recorder
