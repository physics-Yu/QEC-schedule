"""Explicit four-zone inventory for the six-patch factory profile.

This profile does not migrate old runtime checkpoints or inherit their geometry
qualification. Idle Y/probe resources can be removed only after a source audit.
"""
from copy import deepcopy

PROFILE = 'surface17-four-zone-six-patch/1'
FACTORY_SLOTS = ('W0', 'W1', 'W2', 'W3', 'W4', 'M')


def obsolete_qubit(qubit):
    return ':Y/' in qubit or qubit.endswith(':join_probe')


def audit_obsolete_resources(dags):
    removed=[];retained=0
    for label,dag in dags:
        for node in dag['nodes']:
            obsolete=[q for q in node['qubits'] if obsolete_qubit(q)]
            if obsolete:
                if node['kind']!='reset' or len(obsolete)!=len(node['qubits']) or node.get('reads') or node.get('writes') or node.get('condition'):
                    raise ValueError('OBSOLETE_RESOURCE_HAS_LIVE_SEMANTICS: '+node['id'])
                removed.append(dict(component=label,source_id=node['id'],qubits=obsolete,reason='cleanup_of_removed_idle_carriers'))
            else:retained+=1
    return dict(passed=True,removed_cleanup_nodes=removed,retained_source_nodes=retained,
                circuit_compiled=False,source_artifacts_modified=False)


def build_four_zone_layout(original):
    d=deepcopy(original)
    d.update(schema_version='FourZoneLayout/1',resource_profile=PROFILE,
        title='四区平台 · compute / processor / reloading / magic factory',
        scope='layout_and_resource_contract_only',layout_rule='two_rows_two_columns',
        circuit_compiled=False,circuit_executed=False,movement_routed=False,
        factory_production_executed=False,user_layout_acceptance='pending',actions=[])
    d['regions']={
        'compute':[80,438,650,1000],
        'processor':[780,438,1460,1000],
        'reloading':[80,-90,650,412],
        'magic':[780,-90,1460,412],
        'measurement':{'x_range_um':[None,None],'y_range_um':[1020,1480],
            'preview_bounds_um':[60,1020,1480,1480],'status':'reserved_geometry_not_routed'},
    }
    d['patches']=[p for p in d['patches'] if p.get('factory_slot')!='Y']
    for p in d['patches']:
        if p.get('factory_id'):
            p['anchor_um'][0]+=800
            p['anchor_um'][1]-=70
            p['zone']='magic'
            p['role']=('raw_magic_input' if p['factory_slot']=='M' else 'distilled_output_and_work' if p['factory_slot']=='W4' else 'distillation_work')
        else:p.update(zone='compute',role='algorithm_data')
    d['atoms']=[a for a in d['atoms'] if not obsolete_qubit(a['id'])]
    for a in d['atoms']:
        if a['aod_group']=='magic':a['xy_um'][0]+=800;a['xy_um'][1]-=70;a['region']='magic'
        else:a['region']='compute'
    for f in d['factories']:
        f.update(atom_count=102,origin_um=[800,f['origin_um'][1]-70],side='lower_right',
            patches=[f['id']+':'+s for s in FACTORY_SLOTS],production_start_group='four_factory_cohort',
            raw_input_patch=f['id']+':M',output_patch=f['id']+':W4')
        f.pop('probe_um',None)
        f['bounds_um']=[790,f['origin_um'][1]-10,1390,f['origin_um'][1]+80]
    d['counts'].update(all_atoms=697,factory_patches=24,factory_probes=0,magic_atoms=408)
    d['aod_groups']={
        'data':{'atom_count':289,'region':'compute_and_processor','resource':'aod:data'},
        'magic':{'atom_count':408,'region':'magic_and_processor_handoff','resource':'aod:magic'},
    }
    d['device_resources']={
        'aod:data':{'home_zone':'compute','allowed_zones':['compute','processor','measurement']},
        'aod:magic':{'home_zone':'magic','allowed_zones':['magic','processor','measurement'],
            'shared_by':['F0','F1','F2','F3'],'cohort_motion_requires_compatible_row_column_waveforms':True},
        'rydberg:data':{'zones':['compute','processor'],'exclusive_per_resource':True},
        'rydberg:magic':{'zones':['magic'],'exclusive_per_resource':True},
        'processor:handoff':{'zone':'processor','purpose':'T_injection_only','requires':['data_ready','accepted_magic_output','carrier_delivery_complete']},
    }
    d['hardware_assumptions']={'source':'explicit_user_instruction_20261009',
        'independent_region_addressed_2q_beams':True,'experimentally_calibrated':False,
        'data_magic_production_mutual_exclusion':False,
        'handoff_transport_and_same_AOD_commands_still_arbitrated':True}
    d['production_policy']={'mode':'four_lines_concurrent_ready_frontier',
        'start_group':['F0','F1','F2','F3'],'native_batch_members_preserved':True,
        'same_stage_cohort_transport':True,'independent_of_data_completion':True,
        'wait_reasons':['own_protocol_dependency','own_inventory_full','shared_magic_AOD_incompatible_command','output_handoff'],
        'new_epoch_requires_cleanup':True,'timer_mints_magic':False,
        'schedule_qualification':'pending'}
    d['processor_interface']={'purpose':'T_injection_only','algorithm_target':'caller_supplied_data_patch',
        'producer_port':'selected_factory:W4','requires_same_carriers':True,
        'permanent_patch_count':0,'non_T_data_gates_zone':'compute','status':'placement_contract_no_transport_bound'}
    d['reloading_interface']={'purpose':'atom_replenishment_reserve','initial_atom_count':0,
        'creates_ready_magic_states':False,'replacement_transport_implemented':False}
    d['removed_resources']=[a['id'] for a in original['atoms'] if obsolete_qubit(a['id'])]
    return d


def validate_layout(d):
    ids=[a['id'] for a in d['atoms']];positions=[tuple(a['xy_um']) for a in d['atoms']]
    assert len(ids)==len(set(ids))==len(set(positions))==697
    assert not any(obsolete_qubit(q) for q in ids)
    assert len(d['removed_resources'])==72
    for p in d['patches']:
        atoms=[a for a in d['atoms'] if a['patch']==p['id']]
        assert len(atoms)==17
        x0,y0,x1,y1=d['regions'][p['zone']]
        assert all(x0<=a['xy_um'][0]<=x1 and y0<=a['xy_um'][1]<=y1 for a in atoms)
    assert len([p for p in d['patches'] if p['zone']=='compute'])==17
    for f in d['factories']:
        assert len([a for a in d['atoms'] if a['patch'] in f['patches']])==102
    assert d['regions']['compute'][2]<d['regions']['magic'][0]
    assert d['regions']['magic'][3]<d['regions']['compute'][1]
    assert d['device_resources']['rydberg:data']['zones']==['compute','processor']
    assert d['device_resources']['rydberg:magic']['zones']==['magic']
    assert d['processor_interface']['purpose']=='T_injection_only'
    return dict(passed=True,atoms=697,data_atoms=289,magic_atoms=408,patches=41,
        removed_atoms=72,factory_count=4,patches_per_factory=6,
        source_scope='static_layout_and_resource_contract',concurrent_schedule_qualified=False,
        user_visual_acceptance='pending')
