"""Geometry-independent compiled component identity and explicit instance linking.

The component stores its existing source and complete internal module order.
An instance binds ports and plans/checks transport in the actual world. Native
fixed-fragment materialization remains visible as a legacy adapter counter;
it is never reported as zero if new connection geometry had to be lowered.
"""
from copy import deepcopy
from pathlib import Path
import os

from .fragment_order_binding import OrderInvariantModuleLibrary
from na_pipeline.backend.enola_kernel import StrategyError,digest
from na_pipeline.backend.strategy_template import remap
from .component_schedule import schedule_signature


def _local(q):
    return q.get('local_id', q['id'].rsplit('/', 1)[-1] if '/' in q['id'] else '$atom')


def _site(port, local):
    return port if local == '$atom' else port + '/' + local


class CompiledComponentTemplate:
    def __init__(self,plan):
        self.dags=deepcopy(plan['physical_dags'])
        self.graph=deepcopy(plan['module_composition']['dependency_graph'])
        self.signature,self.semantic_source,self.operations=schedule_signature(self.dags)
        entry={a.get('site_id',a['qubit_id']):a for a in plan['atom_program']['initial_state']['atoms']}
        ports={}
        for dag in self.dags:
            for q in dag['qubits']:
                if q['id'] not in entry:raise StrategyError('COMPONENT_PORT_ABSENT','Compiled input port is absent',qubit=q['id'])
                block=q['block_id'];local=_local(q)
                port=ports.setdefault(block,{'origin':list(entry[q['id']]['position_um']),'sites':{},'aod_group':q['aod_group']})
                port['sites'][local]=[entry[q['id']]['position_um'][i]-port['origin'][i] for i in (0,1)]
        # Port names and intrinsic shapes matter; absolute world coordinates do not.
        self.ports={p:{'sites':v['sites'],'aod_group':v['aod_group'],'transform':'translation_only',
                       'entry_carrier':'SLM','exit_carrier':'SLM'} for p,v in ports.items()}
        op_index={o['id']:i for i,o in enumerate(self.operations)}
        module_index={m['id']:i for i,m in enumerate(self.graph['modules'])}
        self.partition=[{'kind':m['kind'],'operations':[op_index[s] for s in m['source_ids']],
                         'dependencies':[module_index[d] for d in m['dependencies']]} for m in self.graph['modules']]
        normalized={q['id']:f'q:{i}' for i,q in enumerate(q for d in self.dags for q in d['qubits'])}
        normalized.update({b:f'port:{i}' for i,b in enumerate(self.ports)})
        normalized.update({o['id']:f'op:{i}' for i,o in enumerate(self.operations)})
        normalized.update({r:f'result:{i}' for i,r in enumerate(r for o in self.operations for r in o['writes'])})
        normalized.update({g['group_id']:f'group:{i}' for i,g in enumerate(g for d in self.dags for g in d['groups'])})
        definition={'schema_version':'ParametricComponentTemplate/0.1','source':self.semantic_source,
                    'ports':list(self.ports.values()),'module_partition':self.partition,
                    'group_contract':remap({'groups':[g for d in self.dags for g in d['groups']],
                        'readout_services':[s for d in self.dags for s in d.get('readout_services',[])]},normalized),
                    'code_frame_rule':'same intrinsic code-site geometry as the qualified compiled source',
                    'native_2q':'CZ','transport_instantiation_owner':'instance_geometry_adapter'}
        self.template_id='component:'+digest(definition)
        self.definition=definition;self.original_plan_hash=digest(plan)

    def instantiate_source(self,operands,*,namespace,result_bindings=None):
        if not isinstance(namespace,str) or not namespace:raise StrategyError('COMPONENT_NAMESPACE','A nonempty invocation namespace is required')
        if set(operands)!=set(self.ports):raise StrategyError('COMPONENT_OPERAND_PORTS','Bind every declared operand port exactly once')
        if len(set(operands.values()))!=len(operands):raise StrategyError('COMPONENT_OPERAND_ALIAS','Distinct operand patches cannot alias')
        mapping=dict(operands)
        mapping.update({d['artifact_id']:f'{namespace}/dag:{i}' for i,d in enumerate(self.dags)})
        for i,o in enumerate(self.operations):mapping[o['id']]=f'{namespace}/op:{i}'
        results=list(dict.fromkeys(r for o in self.operations for r in o['writes']))
        mapping.update({r:f'{namespace}/result:{i}' for i,r in enumerate(results)})
        groups=[g for d in self.dags for g in d['groups']]
        mapping.update({g['group_id']:f'{namespace}/group:{i}' for i,g in enumerate(groups)})
        for d in self.dags:
            for q in d['qubits']:
                mapping[q['id']]=_site(operands[q['block_id']],_local(q))
        if result_bindings:
            allowed=set(results)|{r for d in self.dags for r in d.get('external_reads',[])}
            if not set(result_bindings)<=allowed:raise StrategyError('COMPONENT_RESULT_PORT','Unknown result port')
            if any(not isinstance(v,str) or not v for v in result_bindings.values()):raise StrategyError('COMPONENT_RESULT_PORT','Result identities must be nonempty strings')
            mapping.update(result_bindings)
        dags=remap(deepcopy(self.dags),mapping)
        return dags

    def bind_graph(self,actual):
        signature,_,ops=schedule_signature(actual)
        if signature!=self.signature:raise StrategyError('COMPONENT_SEMANTICS_CHANGED','Instance changed immutable operations, parameters, ports or dependencies')
        mapping={}
        old_q=[q for d in self.dags for q in d['qubits']];new_q=[q for d in actual for q in d['qubits']]
        if len(old_q)!=len(new_q):raise StrategyError('COMPONENT_DECLARATIONS_CHANGED','Full operand declarations must be preserved')
        for old,new in zip(old_q,new_q,strict=True):
            if (_local(old),old['role'],old['aod_group'])!=(_local(new),new['role'],new['aod_group']):
                raise StrategyError('COMPONENT_DECLARATIONS_CHANGED','Code roles and AOD grouping must be preserved')
            mapping[old['id']]=new['id'];mapping[old['block_id']]=new['block_id']
        for old,new in zip(self.dags,actual,strict=True):mapping[old['artifact_id']]=new['artifact_id']
        for old,new in zip(self.operations,ops,strict=True):
            mapping[old['id']]=new['id']
            for field in ('qubits','reads','writes'):
                mapping.update(zip(old[field],new[field],strict=True))
        declarations={q['id']:q for d in actual for q in d['qubits']}
        for d in self.dags:
            for q in d['qubits']:
                if q['id'] in mapping:mapping[q['block_id']]=declarations[mapping[q['id']]]['block_id']
        for old,new in zip([g for d in self.dags for g in d['groups']], [g for d in actual for g in d['groups']],strict=True):
            mapping[old['group_id']]=new['group_id']
        for old,new in zip(self.dags,actual,strict=True):
            if (remap(old['groups'],mapping)!=new['groups'] or
                    remap(old.get('readout_services',[]),mapping)!=new.get('readout_services',[])):
                raise StrategyError('COMPONENT_GROUPS_CHANGED','Grouping is part of the immutable component')
        graph=remap(deepcopy(self.graph),mapping);by_op={o['id']:o for o in ops}
        for module in graph['modules']:
            fragment=module['dag'];ids=set(module['source_ids'])
            fragment['nodes']=[deepcopy(by_op[s]) for s in module['source_ids']]
            for o in fragment['nodes']:o['after']=[p for p in o['after'] if p in ids]
            fragment['qubits']=[deepcopy(declarations[q['id']]) for q in fragment['qubits']]
            fragment['source_map']={o['id']:{'physical_source_op_id':o['id'],'source_ids':deepcopy(o['source_ids'])} for o in fragment['nodes']}
        graph['source_hashes']=[digest(d) for d in actual]
        graph['component_template_id']=self.template_id
        graph['original_component_plan_hash']=self.original_plan_hash
        return graph


class ParametricComponentAdapter:
    def __init__(self,device,*,connection_directory=None,budget=None):
        self.device=deepcopy(device)
        if connection_directory is not None and os.name == 'nt':
            resolved=str(Path(connection_directory).resolve())
            connection_directory=resolved if resolved.startswith('\\\\?\\') else '\\\\?\\'+resolved
        self.connections=OrderInvariantModuleLibrary(device,directory=connection_directory,budget=budget)
        self.instances=[]

    def _check_ports(self,template,dags,world):
        old_blocks=list(template.ports);new_blocks=list(dict.fromkeys(q['block_id'] for d in dags for q in d['qubits']))
        if len(old_blocks)!=len(new_blocks):raise StrategyError('COMPONENT_PORT_ARITY','Operand count changed')
        sites={a.get('site_id',a['qubit_id']):a for a in world['atoms']};poses={}
        declared={}
        for d in dags:
            for q in d['qubits']:declared.setdefault(q['block_id'],{})[_local(q)]=q['id']
        for formal,actual in zip(old_blocks,new_blocks,strict=True):
            port=template.ports[formal];locals=list(port['sites'])
            if set(declared[actual])!=set(locals):raise StrategyError('COMPONENT_DECLARATIONS_CHANGED','Code site ports changed')
            try:origin=sites[declared[actual][locals[0]]]['position_um']
            except KeyError as e:raise StrategyError('COMPONENT_SITE_MISSING','Operand code-site port is absent',site=str(e))
            for local,relative in port['sites'].items():
                atom=sites.get(declared[actual][local])
                if atom is None:raise StrategyError('COMPONENT_SITE_MISSING','Operand code-site port is absent',site=declared[actual][local])
                if atom['carrier']!='SLM' or atom['aod_group']!=port['aod_group']:
                    raise StrategyError('COMPONENT_CARRIER_PRECONDITION','This template requires declared SLM entry ports and AOD group',site=actual+'/'+local)
                if any(abs(atom['position_um'][i]-origin[i]-relative[i])>1e-8 for i in (0,1)):
                    raise StrategyError('COMPONENT_CODE_ORIENTATION_OR_SHAPE','Anchor translation is supported; code rotation/deformation needs an explicit code adapter',port=formal,site=local)
            poses[formal]={'patch':actual,'reference_position_um':list(origin)}
        return poses

    def instantiate(self,template,world,*,operands=None,namespace='component-instance',result_bindings=None,dags=None,execution_context=None,allow_connection_planning=True):
        actual=template.instantiate_source(operands,namespace=namespace,result_bindings=result_bindings) if dags is None else deepcopy(dags)
        actual=actual if isinstance(actual,list) else [actual]
        poses=self._check_ports(template,actual,world)
        graph=template.bind_graph(actual)
        self.connections.recipe_graph_provider=lambda _:deepcopy(graph)
        before=self.connections.stats
        plan=self.connections.compose_recipe(actual,world,execution_context=execution_context,build_missing=allow_connection_planning)
        after=self.connections.stats
        counters={k:after[k]-before[k] for k in ('leaf_compile_count','placement_search_count','routing_search_count','bind_count','cache_hit_count','frontier_search_count')}
        if counters['frontier_search_count']:raise StrategyError('COMPONENT_INTERNAL_SELECTION_REPEATED','Frozen component instantiation must not run internal batch selection')
        if schedule_signature(plan['physical_dags'])[0]!=template.signature:raise StrategyError('COMPONENT_INSTANTIATION_CHANGED_SOURCE','Geometry binding changed the component source')
        receipt={'schema_version':'ParametricComponentInstance/0.1','component_template_id':template.template_id,
            'instance_id':'instance:'+digest({'template':template.template_id,'dags':actual,'world':world}),
            'operand_poses':poses,'entry_world_hash':digest(world),'all_world_atoms_checked':len(world['atoms']),
            'template_compile_calls':0,'internal_batch_selection_calls':0,'internal_module_graph_reconstruction_calls':0,
            'source_and_internal_partition_unchanged':True,
            'connection_work':{'legacy_fixed_fragment_materializations':counters['leaf_compile_count'],
                'placement_candidates':counters['placement_search_count'],'routing_calls':counters['routing_search_count'],
                'checked_fragment_bindings':counters['bind_count'],'geometry_cache_hits':counters['cache_hit_count']},
            'connection_work_scope':'fixed native fragments only; existing legacy compile_module builds new motion geometry and emits the unchanged pulse pattern',
            'runtime_results_epochs_tokens_cached':False}
        plan['parametric_component_instance']=receipt;self.instances.append(receipt)
        return plan
