"""Source identity, decision correspondence and independent call observations."""
from collections import Counter
from hashlib import sha256
from pathlib import Path, PurePosixPath

from .checker import _hash


def _compatible(a,b):
    sign=lambda x:(x>0)-(x<0)
    return all(sign(a[i]-b[i])==sign(a[j]-b[j]) for i,j in ((0,1),(2,3)))


def check_enola(audit,strategy,evidence,geometry):
    body=strategy['body']; provenance=body['enola_provenance']; plan=body['atom_program']
    if body['backend_used']!='enola_function_kernel':
        audit.fail('BACKEND_NOT_ENOLA','T000 requires the declared real Enola kernel, not fallback'); return
    if evidence is None:
        audit.need('ENOLA_OBSERVATION_MISSING','Provide independently observed original-function calls and the actual R7 pin manifest'); return
    pin=evidence['pin']
    observation=evidence.get('observations',{}).get(strategy['strategy_hash'],evidence.get('observation'))
    root=Path(__file__).resolve().parents[3]
    source_root=(root/pin['source_root']).resolve()
    if not source_root.is_relative_to(root/'third_party'/'enola'):
        audit.fail('ENOLA_SOURCE_ROOT','Pin source_root must identify this repository vendor directory'); return
    source_key=provenance['source_file']; raw=(source_root/source_key).read_bytes(); actual=sha256(raw).hexdigest()
    license_hash=sha256((source_root/'LICENSE').read_bytes()).hexdigest()
    if pin['commit']!=provenance['commit'] or pin['repository']!=provenance['repository'] or actual!=pin['source_files_sha256'][source_key] or actual!=provenance['source_sha256'] or license_hash!=provenance['license_sha256']:
        audit.fail('ENOLA_PIN_MISMATCH','Actual source/license, R7 manifest and strategy provenance differ')
    dependency_lock=(root/pin['dependencies_lock']).resolve()
    if not dependency_lock.is_relative_to(root/'third_party'/'enola') or sha256(dependency_lock.read_bytes()).hexdigest()!=pin['dependencies_lock_sha256']:
        audit.fail('ENOLA_DEPENDENCY_PIN','Dependency lock differs from the source manifest')
    if observation is None:
        audit.need('ENOLA_OBSERVATION_MISSING','No independent call record is associated with this strategy hash'); return
    if observation.get('fixture') or observation.get('source_unchanged') is not True or observation['source_sha256']!=actual:
        audit.fail('ENOLA_OBSERVATION_SOURCE','Call observation is fixture, stale, or from a different source')
    project_counts=observation.get('project_search_counts')
    if project_counts is None or observation.get('project_sources_unchanged') is not True:
        audit.need('COMPILE_SEARCH_OBSERVATION_MISSING','Actual project layout/routing call observation is required')
    elif plan['stats'].get('routing_search_count')!=project_counts.get('enola_kernel.py:group_route',0):
        audit.fail('ROUTING_SEARCH_COUNTER_MISMATCH','Published routing_search_count omits or adds actual group_route searches',published=plan['stats'].get('routing_search_count'),observed=project_counts.get('enola_kernel.py:group_route',0))
    for path,value in observation.get('project_source_hashes',{}).items():
        # Observation paths describe the producer host, not the verifier host.
        # The immutable identity is keyed by filename on both platforms; keep
        # the exact byte digest comparison when normalizing path separators.
        name=PurePosixPath(path.replace('\\','/')).name
        if body['compiler_identity'].get(name)!=value:
            audit.fail('COMPILER_OBSERVATION_IDENTITY','Observed compiler source differs from immutable compiler identity',resource=name)
    observed=Counter()
    for record in observation['records']:
        if record['input_sha256']!=_hash(record['inputs']) or record['output_sha256']!=_hash(record['output']):
            audit.fail('ENOLA_OBSERVATION_HASH','Observed function input/output hash is inconsistent')
        observed[(record['function'],_hash(record['inputs']),_hash(record['output']))]+=record.get('count',1)
    observed_counts=Counter()
    for (function,_,_),count in observed.items(): observed_counts[function]+=count
    if dict(observed_counts)!=provenance['call_counts'] or sum(observed_counts.values())!=observation['record_count']:
        audit.fail('ENOLA_FUNCTION_COUNTER_MISMATCH','Function counters do not equal the observed original-source returns')
    decisions=provenance['decisions']; by_id={a['id']:a for a in plan['actions']}; needed=Counter(); linked=set()
    for decision in decisions:
        candidates=decision['candidates']; selected=decision['selected_indices']; conflicts={tuple(sorted(e)) for e in decision['conflicts']}
        if decision['input_hash']!=_hash(candidates): audit.fail('ENOLA_INPUT_HASH','Decision input hash does not match candidates')
        core={key:decision[key] for key in ('input_hash','candidates','conflicts','selected_indices','selected_op_ids')}; core['action_ids']=[]
        if decision['decision_hash']!=_hash(core): audit.fail('ENOLA_DECISION_HASH','Decision hash does not bind the immutable selection input/output')
        if len(selected)!=len(set(selected)) or any(type(i) is not int or not 0<=i<len(candidates) for i in selected):
            audit.fail('ENOLA_SELECTION_RANGE','Invalid selected indices'); continue
        if any(i in selected and j in selected for i,j in conflicts): audit.fail('ENOLA_NONINDEPENDENT_SELECTION','Selected candidates share a conflict edge')
        if any(i not in selected and not any(tuple(sorted((i,j))) in conflicts for j in selected) for i in range(len(candidates))):
            audit.fail('ENOLA_NONMAXIMAL_SELECTION','Returned set is not maximal for its actual input graph')
        for i,a in enumerate(candidates):
            if a['vector']!=[a['from_um'][1],a['to_um'][1],a['from_um'][0],a['to_um'][0]]: audit.fail('ENOLA_CANDIDATE_VECTOR','Compatibility vector differs from candidate positions')
            for j in range(i+1,len(candidates)):
                b=candidates[j]; valid=_compatible(a['vector'],b['vector'])
                needed[('compatible_2D',_hash({'a':a['vector'],'b':b['vector']}),_hash(valid))]+=1
                if (not valid or a['op_id']==b['op_id'] or set(a['pair'])&set(b['pair']) or a['aod_group']!=b['aod_group']) and (i,j) not in conflicts:
                    audit.fail('ENOLA_REQUIRED_CONFLICT_MISSING','Graph omits a shared-axis/source/atom/group conflict')
        needed[('maximalis_solve_sort',_hash({'n':len(candidates),'edges':decision['conflicts']}),_hash(selected))]+=1
        selected_ops=[candidates[i]['op_id'] for i in selected]
        if selected_ops!=decision['selected_op_ids']: audit.fail('ENOLA_SELECTED_SOURCE','Selected source operations differ from the selected indices')
        if decision.get('accepted') is not True:
            if not decision.get('rejection'): audit.fail('ENOLA_REJECTED_DECISION_REASON','Unused kernel decision requires explicit project-constraint reason')
            continue
        pulse=by_id[decision['pulse_action_id']]; linked.add(pulse['id'])
        if pulse['payload'].get('enola_decision_hash')!=decision['decision_hash'] or set(pulse['payload']['physical_op_ids'])!=set(selected_ops):
            audit.fail('ENOLA_OUTPUT_UNUSED','Accepted decision does not determine its actual source pulse',action_id=pulse['id'])
        if not set(decision['action_ids'])<=set(by_id) or pulse['id'] not in decision['action_ids']:
            audit.fail('ENOLA_ACTION_LINK','Decision points to absent/unrelated output actions')
        if geometry is not None:
            actual_atoms=geometry['snapshots'][(pulse['id'],'before')]
            for i in selected:
                candidate=candidates[i]
                if actual_atoms[candidate['mover']]['position_um']!=candidate['to_um']:
                    audit.fail('ENOLA_TARGET_NOT_USED','Selected Enola candidate position does not occur at its actual pulse',action_id=pulse['id'],resource=candidate['mover'])
    absent=sum(max(0,count-observed[key]) for key,count in needed.items())
    if absent: audit.fail('ENOLA_CALL_NOT_OBSERVED',f'{absent} declared upstream calls were not independently observed')
    pulses={a['id'] for a in plan['actions'] if a['kind']=='gate' and a['payload'].get('name')=='CZ'}
    if not pulses or linked!=pulses: audit.fail('ENOLA_PULSE_COVERAGE','All native CZ pulses must be tied to accepted actual kernel decisions')
    audit.metrics['enola']={'commit':provenance['commit'],'source_sha256':actual,'accepted_decisions':len(linked),'total_decisions':len(decisions),'observed_function_returns':sum(observed.values()),'required_function_returns':sum(needed.values()),'project_search_counts':project_counts,'backend_scope':'original compatibility + greedy maximal independent set; project full-cycle adapter'}
