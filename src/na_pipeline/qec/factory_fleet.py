"""Explicit replicated factory inventory; production has no data operand."""
from copy import deepcopy
from .hierarchical_binding import physical_resource_requirements
from .factory import _name


def factory_fleet_requirements(logical_dag, factory_ids):
    ids=list(factory_ids)
    if not ids or len(set(ids))!=len(ids):raise ValueError('FACTORY_FLEET_IDS: nonempty unique factory identities required')
    for fid in ids:_name(fid,'factory_id')
    algorithm={p['patch_id'] for p in logical_dag['patches']}
    if any(fid+':'+s in algorithm for fid in ids for s in ('W0','W1','W2','W3','W4','M','Y','join_probe')):
        raise ValueError('FACTORY_FLEET_ALIAS: factory slots collide with algorithm patches')
    parts=[physical_resource_requirements(logical_dag,factory_id=f) for f in ids]
    result=deepcopy(parts[0]);result['factory_id']='factory-fleet'
    result['factories']={};result['patches']={};result['nonpatch_atoms']=[];result['physical_qubit_ids']=[]
    for fid,part in zip(ids,parts,strict=True):
        owned=[p for p,r in part['patches'].items() if r['role']=='factory']
        probe=part['nonpatch_atoms'][0]['physical_qubit_id']
        result['factories'][fid]={'factory_id':fid,'patches':owned,'probe':probe,
            'exclusive_resources':[fid+':mutex',*owned,probe],'output_patch':fid+':W4',
            'physical_qubit_ids':[q for q in part['physical_qubit_ids'] if any(q.startswith(p+'/') for p in owned) or q==probe],
            'ready_capacity':1,'production_data_operand':None}
        for p,r in part['patches'].items():
            if p in result['patches'] and r['role']=='factory':raise ValueError('FACTORY_FLEET_ALIAS')
            result['patches'][p]={**deepcopy(r),**({'factory_id':fid} if r['role']=='factory' else {})}
        result['nonpatch_atoms'] += [{**deepcopy(r),'factory_id':fid} for r in part['nonpatch_atoms']]
        result['physical_qubit_ids'] += [q for q in part['physical_qubit_ids'] if q not in result['physical_qubit_ids']]
    result['physical_qubit_count']=len(result['physical_qubit_ids'])
    result['factory_count']=len(ids);result['maximum_ready_outputs']=len(ids)
    result['factory_slots']={f:deepcopy(p['factory_slots']) for f,p in zip(ids,parts,strict=True)}
    result['counts'].update(factory_patches=7*len(ids),factory_atoms=120*len(ids),
        nonpatch_atoms=len(ids),magic_aod_atoms=120*len(ids))
    result['lease_rules']={'production':{'exclusive':'selected line factory resources only','data_target':None},
        'consumption':{'exclusive':'same producer resources plus actual data target','release':'after actual output consumption and cleanup'}}
    result['shared_phase_scratch']=None
    result['fleet_contract']={'schema_version':'FactoryFleetResources/0.1','private_factory_carriers_per_line':120,
        'output_carrier_policy':'hold_same_W4_until_consumed_and_cleaned','new_batch_requires_own_cleanup':True,
        'device_resources':'shared; line replication does not replicate AODs or lasers',
        'data_maintenance_owner':'algorithm_scheduler'}
    return result
