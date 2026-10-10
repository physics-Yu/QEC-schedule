"""Independent R1 preinitialized-state/0.1 checks; no startup transport."""
from math import isfinite,dist
from collections import Counter
from .checker import _hash,EPS
from .dag_core import DAGAudit


def inspect_preinitialized(audit,state,device):
    if state['schema_version']!='preinitialized-state/0.1': raise ValueError('Unsupported R1 initial-state schema')
    if state['entry_mode']!='preinitialized' or device['entry_mode']!='preinitialized':
        audit.fail('ENTRY_MODE','The new path requires an explicit preinitialized entry')
    profile=device['grouped_profile']; geometry=device['patch_geometry']
    if profile['schema_version']!='grouped-device-profile/0.2' or geometry['schema_version'] not in ('patch-geometry/0.1','patch-geometry/0.2'): raise ValueError('Unsupported R1 grouped/patch geometry version')
    if 'initialization_zone' in profile or 'patch_initialization' in profile['layouts'] or 'initialization' in device['zones']:
        audit.fail('INITIALIZATION_ZONE_REINTRODUCED','New entry must not restore the old startup zone')
    if state['t_start_us']!=0 or state['startup_actions'] or state['startup_duration_us']!=0 or state['aod_rows'] or state['aod_columns']:
        audit.fail('ENTRY_STARTUP_ACTIONS','Preinitialized t=0 entry cannot contain startup moves/resets/active transport')
    if state['ready_magic_tokens'] or state['results']:
        audit.fail('ENTRY_FREE_MAGIC_OR_RESULTS','Declared prepared qubits do not supply accepted magic or runtime results')
    if state['device_ref']!=device['artifact_id'] or state['device_hash']!=_hash(device): audit.fail('ENTRY_DEVICE_BINDING','Entry belongs to a different device')
    spec=state['entry_spec']; placements=spec['placements']; declarations=spec['patches']; patches=state['patches']
    if state['placement_binding_sha256']!=_hash(placements) or state['placement_ref']!=spec['placement_ref']:
        audit.fail('ENTRY_PLACEMENT_HASH','t=0 placement reference/hash differs from supplied mapping')
    if set(patches)!=set(declarations) or set(placements)!=set(patches): audit.fail('ENTRY_PATCH_COVERAGE','Patch declarations and placements differ')
    atoms={a['atom_id']:a for a in state['atoms']}; traps={t['trap_id']:t for t in state['slm_traps']}
    if len(atoms)!=len(state['atoms']) or len(traps)!=len(state['slm_traps']) or len({a['qubit_id'] for a in atoms.values()})!=len(atoms):
        audit.fail('ENTRY_DUPLICATE_IDENTITY','Initial atom/qubit/trap identities repeat')
    slots=profile['layouts'][geometry['local_layout_id']]['slots']; used=set(); cells=[]
    for lid,patch in patches.items():
        declared=declarations[lid]; anchor=placements[lid]['anchor_um']; orientation=placements[lid]['orientation']
        if declared['basis'] not in ('X','Z') or type(declared['value']) is not int or declared['value'] not in (0,1):
            audit.fail('ENTRY_LOGICAL_STATE','Input must declare a supported encoded Pauli eigenstate',patch_id=lid)
        expected={'kind':'encoded_pauli_eigenstate','basis':declared['basis'],'value':declared['value'],'origin':'declared_precondition'}
        if patch['initial_logical_state']!=expected or patch['code_profile']!=geometry['code_profile'] or not patch['preparation_boundary']:
            audit.fail('ENTRY_ENCODING_ASSUMPTION','Physical product states cannot be inferred to be encoded logical input',patch_id=lid)
        if patch['magic_resource_ready'] is not False: audit.fail('ENTRY_FREE_MAGIC_OR_RESULTS','An initial patch cannot already own an accepted magic token',patch_id=lid)
        if orientation not in geometry['allowed_orientations'] or patch['orientation']!=orientation or patch['anchor_um']!=anchor:
            audit.fail('ENTRY_PATCH_TRANSFORM','Initial orientation/anchor differs from its supported placement',patch_id=lid)
        if len(anchor)!=2 or any(type(v) not in (int,float) or not isfinite(v) for v in anchor): raise ValueError('Finite 2D patch anchor required')
        cells.append((lid,anchor,[anchor[i]+geometry['cell_extent_um'][i] for i in (0,1)]))
        members={a['local_id']:a for a in atoms.values() if a['patch_id']==lid}
        if set(members)!=set(slots) or len(patch['atom_ids'])!=17 or set(patch['atom_ids'])!={a['atom_id'] for a in members.values()}:
            audit.fail('ENTRY_PATCH_MEMBERS','Patch must bind its complete 17-member identity',patch_id=lid)
        data=set(); aux=set()
        for local,definition in slots.items():
            atom=members[local]; aid=atom['atom_id']; used.add(aid)
            expected_position=[anchor[i]+definition['position_um'][i] for i in (0,1)]
            if orientation == 'canonical_rot90':
                if geometry['schema_version'] != 'patch-geometry/0.2' or geometry['cell_extent_um'] != [80.,80.]:
                    audit.fail('ENTRY_ROTATION_PROFILE','Quarter-turn requires the 80 um square v2 profile',patch_id=lid)
                x,y=definition['position_um']
                expected_position=[anchor[0]+y,anchor[1]+80.-x]
            if atom['position_um']!=expected_position or atom['qubit_id']!=f'{lid}/{local}' or atom['carrier']!='SLM' or atom['aod_group']!=declared['aod_group'] or atom['row_id'] is not None or atom['column_id'] is not None:
                audit.fail('ENTRY_ATOM_BINDING','Initial physical identity/carrier/position does not implement placement',patch_id=lid,atom_id=aid)
            if local.startswith('d'):
                data.add(aid)
                if atom['initial_state']!={'kind':'encoded_member','patch_id':lid}: audit.fail('ENTRY_PHYSICAL_ZERO_NOT_ENCODED','Data must belong to a declared encoded block',atom_id=aid)
            else:
                aux.add(aid)
                if atom['initial_state']!={'kind':'physical_basis','basis':'Z','value':0}: audit.fail('ENTRY_AUXILIARY_STATE','Auxiliary entry state must be explicit physical Z=0',atom_id=aid)
            trap=traps[atom['trap_id']]
            if trap['occupant']!=aid or trap['position_um']!=atom['position_um']: audit.fail('ENTRY_SLM_OCCUPANCY','Initial SLM inventory differs from carrier identities',atom_id=aid)
            zone=device['zones'][geometry['anchor_zone_id']]
            for i,axis in enumerate('xy'):
                lo,hi=zone[axis+'_range_um']; coordinate=atom['position_um'][i]
                if lo is not None and coordinate<lo-EPS or hi is not None and coordinate>hi+EPS: audit.fail('ENTRY_OUTSIDE_EZ','Initial atom lies outside the declared zone',atom_id=aid)
        if set(patch['data_atom_ids'])!=data or set(patch['auxiliary_atom_ids'])!=aux:
            audit.fail('ENTRY_ROLE_BINDING','Data/auxiliary role membership changed',patch_id=lid)
    inventory=state.get('resource_inventory')
    if inventory is not None:
        if inventory['schema_version']!='initial-resource-inventory/0.1' or state['resource_inventory_sha256']!=_hash(inventory) or spec.get('resource_inventory')!=inventory:
            audit.fail('ENTRY_RESOURCE_HASH','Initial resource inventory is unknown or differs from its immutable declaration')
        roles=inventory['patch_roles']; extra=inventory['nonpatch_atoms']; slots_seen=set(); role_counts=Counter()
        if set(roles)!=set(patches): audit.fail('ENTRY_RESOURCE_PATCH_COVERAGE','Pool roles must cover every patch exactly once')
        for lid,role in roles.items():
            if role['role'] not in ('algorithm','factory','scratch') or role['slot_id'] in slots_seen: audit.fail('ENTRY_RESOURCE_SLOT_ALIAS','Patch role or stable pool slot is invalid',patch_id=lid)
            slots_seen.add(role['slot_id']); role_counts[role['role']]+=17
            for record in [patches[lid],*(atoms[aid] for aid in patches[lid]['atom_ids'])]:
                if any(record.get(a)!=role[b] for a,b in (('resource_role','role'),('pool_id','pool_id'),('resource_slot_id','slot_id'))): audit.fail('ENTRY_POOL_IDENTITY','Patch/atom pool labels differ from declared finite inventory',patch_id=lid)
        for aid,declaration in extra.items():
            if aid not in atoms or aid in used: audit.fail('ENTRY_NONPATCH_IDENTITY','Nonpatch carrier is absent or aliases a patch'); continue
            atom=atoms[aid]; point=declaration['position_um']; used.add(aid); role_counts[declaration['role']]+=1
            if declaration['slot_id'] in slots_seen: audit.fail('ENTRY_RESOURCE_SLOT_ALIAS','Nonpatch slot aliases another resource',atom_id=aid)
            slots_seen.add(declaration['slot_id'])
            expected={'qubit_id':declaration['qubit_id'],'trap_id':declaration['trap_id'],'position_um':point,'aod_group':declaration['aod_group'],'patch_id':None,'local_id':None,'carrier':'SLM','row_id':None,'column_id':None,'resource_role':declaration['role'],'pool_id':declaration['pool_id'],'resource_slot_id':declaration['slot_id'],'initial_state':{'kind':'physical_basis','basis':declaration['basis'],'value':declaration['value']}}
            if declaration['basis'] not in ('X','Z') or type(declaration['value']) is not int or declaration['value'] not in (0,1) or any(atom.get(k)!=v for k,v in expected.items()): audit.fail('ENTRY_NONPATCH_BINDING','Explicit probe/scratch carrier or prepared state differs from its declared identity',atom_id=aid)
            trap=traps[atom['trap_id']]
            if trap['occupant']!=aid or trap['position_um']!=point: audit.fail('ENTRY_SLM_OCCUPANCY','Nonpatch trap occupancy differs from its carrier',atom_id=aid)
            if any(other!=aid and dist(point,a['position_um'])<=device['geometry']['distance_tolerance_um'] for other,a in atoms.items()): audit.fail('ENTRY_NONPATCH_COLLISION','Nonpatch atom occupies another carrier position',atom_id=aid)
            if any(all(lo[i]<=point[i]<hi[i] for i in (0,1)) for _,lo,hi in cells): audit.fail('ENTRY_NONPATCH_IN_PATCH','Nonpatch site overlaps a reserved patch cell',atom_id=aid)
        expected_counts={'patch_count':len(patches),'patch_atom_count':17*len(patches),'nonpatch_atom_count':len(extra),'total_atom_count':len(atoms),'resource_slot_count':len(slots_seen),'atoms_by_role':dict(sorted(role_counts.items()))}
        if state['resource_counts']!=expected_counts: audit.fail('ENTRY_RESOURCE_COUNT','Physical carrier/resource counts differ from the same finite inventory')
    if used!=set(atoms): audit.fail('ENTRY_EXTRA_ATOMS','Entry contains carriers outside all declared patches and nonpatch inventory')
    for index,(lid,lo,hi) in enumerate(cells):
        for other,olo,ohi in cells[index+1:]:
            if all(max(lo[i],olo[i])<min(hi[i],ohi[i])-EPS for i in (0,1)):
                audit.fail('ENTRY_PATCH_OVERLAP','Finite patch cells overlap',patch_ids=[lid,other])
    receiver=geometry['ports']['measurement_receiver']
    if receiver['anchor_mode']!='global_mz_with_independent_bank_x': audit.fail('MZ_COORDINATE_MODE','MZ coordinates must not inherit patch y translation')
    audit.metrics.update(patch_count=len(patches),atom_count=len(atoms),startup_duration_us=0,magic_initial_ready_inventory=0)


def validate_preinitialized_entry(state,device):
    audit=DAGAudit('preinitialized_entry',{'initial_state':state,'device':device},fixture=state.get('provenance',{}).get('fixture',False))
    audit.interfaces={'R1-PREINITIALIZED-IF-001':'0.2.0' if 'resource_inventory' in state else '0.1.0'}
    audit.check('initial_encoded_identity_and_geometry',lambda:inspect_preinitialized(audit,state,device))
    return audit.report()


def inspect_mz_receiver(audit,actions,geometry,device):
    slots=device['grouped_profile']['layouts']['ancilla_readout']['slots']
    for action in actions:
        if action['kind']!='measure': continue
        site=action['payload'].get('site_id')
        if action['payload'].get('bank_id')=='rigid-mz':
            profile=device.get('rigid_readout',{})
            if profile.get('schema_version') not in {'rigid-readout-profile/0.1','rigid-readout-profile/0.2','rigid-readout-profile/0.3'}:
                audit.need('RIGID_MZ_PROFILE_MISSING','Rigid readout needs its declared finite lattice profile',action_id=action['id']);continue
            parts=site.split(':') if isinstance(site,str) else []
            signed_x=profile.get('schema_version')=='rigid-readout-profile/0.3' and device['zones']['measurement']['x_range_um']==[None,None]
            if len(parts)!=3 or parts[0]!='grid' or not parts[2].isdigit() or not ((parts[1].isdigit() or parts[1].startswith('-') and parts[1][1:].isdigit()) if signed_x else parts[1].isdigit()):
                audit.fail('RIGID_MZ_SITE_ID','Grid receiver has an invalid site identity',action_id=action['id']);continue
            ix,iy=map(int,parts[1:])
            target=[profile['site_origin_um'][0]+ix*profile['site_pitch_um'],profile['site_origin_um'][1]+iy*profile['site_pitch_um']]
            before=geometry['snapshots'][(action['id'],'before')]
            for aid in action['atoms']:
                if dist(before[aid]['position_um'],target)>EPS:
                    audit.fail('RIGID_MZ_SITE_POSITION','Measured position differs from the independently reconstructed lattice site',action_id=action['id'],atom_id=aid)
            continue
        if site not in slots:
            audit.need('MZ_SITE_MAPPING_UNSUPPORTED','Physical readout site needs an explicit R1 receiver-slot mapping',action_id=action['id']); continue
        before=geometry['snapshots'][(action['id'],'before')]
        for aid in action['atoms']:
            if abs(before[aid]['position_um'][1]-slots[site]['position_um'][1])>EPS:
                audit.fail('MZ_PATCH_Y_TRANSLATION','Readout y differs from its fixed global MZ receiver',action_id=action['id'],atom_id=aid)


def inspect_inventory_continuity(audit,initial,committed_states,*,required_qubit_ids=()):
    """D04: a finite initial world is the only carrier pool in the no-loss run."""
    bindings={a['atom_id']:a['qubit_id'] for a in initial['atoms']}
    if not set(required_qubit_ids)<=set(bindings.values()):
        audit.fail('INITIAL_RESOURCE_INVENTORY_INCOMPLETE','Factory/scratch/probe requirements are not present in the declared initial world',missing_qubits=sorted(set(required_qubit_ids)-set(bindings.values())))
    for index,state in enumerate(committed_states):
        actual={a['atom_id']:a['qubit_id'] for a in state['atoms']}
        if actual!=bindings or len(actual)!=len(state['atoms']):
            audit.fail('WORLD_CARRIER_INVENTORY_CHANGED','A later window invented, removed, replaced or aliased a carrier',window=index,added_atoms=sorted(set(actual)-set(bindings)),missing_atoms=sorted(set(bindings)-set(actual)))
    audit.metrics['initial_carrier_count']=len(bindings)
