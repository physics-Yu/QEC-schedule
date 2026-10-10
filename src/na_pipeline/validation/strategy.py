"""T604 strategy qualification. Missing evidence is never a full pass."""
from copy import deepcopy

from .checker import Audit, _contract, _timing, _resources, _hash
from .geometry import check_geometry
from .trace import check_trace
from .strategy_common import StrategyAudit
from .strategy_groups import check_group_source, group_metrics, check_readout_capacity
from .strategy_capture import capture_closure
from .strategy_source import check_strategy_source
from .strategy_enola import check_enola


def inspect_strategy_plan(audit,plan,device,physical=None,trace=None):
    low=Audit()
    low.guard('contract',_contract,plan,device,trace,physical)
    low.guard('timing',_timing,plan,device)
    low.guard('resources',_resources,plan)
    geometry=low.guard('geometry',check_geometry,plan,device)
    if trace is not None: low.guard('trace',check_trace,plan,device,trace,geometry)
    audit.failures.extend(low.failures); audit.unverified.extend(low.unverified)
    audit.metrics.update(low.metrics)
    audit.check('capture_closure',lambda:capture_closure(audit,plan,device))
    if geometry is not None:
        audit.check('readout_capacity',lambda:check_readout_capacity(audit,plan,device,geometry))
    return geometry


def _body_contract(audit,strategy,device):
    if strategy['schema_version']!='compiled-logical-strategy/0.1': audit.fail('STRATEGY_SCHEMA','Unsupported compiled strategy schema')
    body=strategy['body']
    if strategy['strategy_hash']!=_hash(body): audit.fail('STRATEGY_BODY_HASH','Strategy immutable body was changed')
    if body['device_hash']!=_hash(device): audit.fail('STRATEGY_DEVICE_MISMATCH','Strategy was compiled against a different complete device/profile')
    if 'grouped_profile' not in device: audit.fail('GROUPED_DEVICE_REQUIRED','Old device profile does not qualify UA26/27')
    physical=body['physical_program']; contract=physical['strategy_contract']
    if body['strategy_contract']!=contract or contract['schema_version']!='strategy_contract/0.1': audit.fail('STRATEGY_SOURCE_CONTRACT','Embedded physical source and strategy contract differ')
    if contract['contract_hash']!=_hash({k:v for k,v in contract.items() if k!='contract_hash'}): audit.fail('STRATEGY_CONTRACT_HASH','Formal contract hash does not match contents')
    core={k:physical[k] for k in ('qubits','templates','body')}
    if contract['physical_input_hash']!=_hash(core): audit.fail('STRATEGY_PHYSICAL_INPUT_HASH','Physical source body differs from qualified formal contract')
    provenance=body['enola_provenance']
    expected_key=_hash({'physical_program':physical,'device':device,'config':provenance['config'],'compiler_identity':body['compiler_identity'],'enola_commit':provenance['commit'],'enola_router_sha256':provenance['source_sha256']})
    if body['cache_key']!=expected_key: audit.fail('STRATEGY_CACHE_KEY','Cache key does not bind the actual source/device/profile/compiler/pin/config')
    if body['entry']!=body['atom_program']['initial_state']: audit.fail('STRATEGY_ENTRY_BODY','Strategy entry promise differs from the actual relative plan')
    expected_resources=[{'action_id':a['id'],'resources':a['resources'],'t_start_us':a['t_start_us'],'t_end_us':a['t_end_us']} for a in body['atom_program']['actions']]
    if body['resource_intervals']!=expected_resources: audit.fail('STRATEGY_RESOURCE_INTERVALS','Strategy resource table differs from actual relative actions')
    forbidden={'results','published_results','frame','frames','token','tokens','epoch','run_id','call_id','scenario','event_trace','validation_report'}
    def walk(node,path):
        if isinstance(node,dict):
            for key,value in node.items():
                if key in forbidden: audit.fail('STRATEGY_CACHED_INSTANCE_STATE',f'Instance state {key} cannot be in immutable strategy body',path=path+'/'+key)
                walk(value,path+'/'+key)
        elif isinstance(node,list):
            for i,value in enumerate(node): walk(value,f'{path}/{i}')
    walk(body,'body')
    return physical


def validate_strategy(strategy,device,*,enola_evidence=None):
    audit=StrategyAudit('compiled_strategy',{'strategy':strategy,'device':device,'enola_evidence':enola_evidence})
    if not isinstance(strategy,dict) or not strategy.get('body'):
        audit.fail('STRATEGY_INPUT_MISSING','A complete compiled strategy body is required'); return audit.report()
    physical=audit.check('immutable_body',lambda:_body_contract(audit,strategy,device))
    if physical is None: return audit.report()
    from na_pipeline.qec import iter_physical_ops
    ops=audit.check('physical_instance_expansion',lambda:list(iter_physical_ops(physical)))
    if ops is None: return audit.report()
    plan=strategy['body']['atom_program']
    geometry=audit.check('relative_plan_geometry_timing',lambda:inspect_strategy_plan(audit,plan,device,physical))
    audit.check('full_physical_semantics',lambda:check_strategy_source(audit,physical,plan,ops))
    audit.check('source_groups',lambda:check_group_source(audit,physical,ops))
    audit.check('actual_group_metrics',lambda:group_metrics(audit,plan,physical))
    audit.check('real_enola_decisions',lambda:check_enola(audit,strategy,enola_evidence,geometry))
    return audit.report()


def validate_strategy_run(run,device,*,strategies=None,enola_evidence=None):
    audit=StrategyAudit('strategy_run',{'run':run,'device':device,'strategies':strategies,'enola_evidence':enola_evidence})
    if not isinstance(run,dict) or not run.get('instances') or 'atom_program' not in run or 'event_trace' not in run:
        audit.fail('STRATEGY_RUN_INPUT_MISSING','Complete controller instances, shared AtomProgram and EventTrace are required'); return audit.report()
    if run.get('schema_version')!='logical-controller-run/0.1': audit.fail('STRATEGY_RUN_SCHEMA','Unknown controller-run schema')
    strategies=strategies or run.get('strategies')
    if not strategies:
        audit.need('STRATEGY_BODIES_MISSING','Original immutable strategy bodies are required for binding/reuse checks'); return audit.report()
    from .strategy_run import inspect_run
    audit.check('bound_instances_and_history',lambda:inspect_run(audit,run,device,strategies,enola_evidence))
    return audit.report()
