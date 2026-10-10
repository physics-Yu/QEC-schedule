"""R4 patch-placement/0.1 output-to-entry and real SA provenance checks."""
from hashlib import sha256
from math import dist,isclose
from pathlib import Path

from .checker import _hash
from .dag_core import DAGAudit,inspect_graph
from .dag_entry import inspect_preinitialized


def inspect_patch_placement(audit,placement,device,dag,observation,pin):
    if placement['schema_version']!='patch-placement/0.1': raise ValueError('Unsupported patch placement')
    if placement['device_hash']!=_hash(device): audit.fail('PLACEMENT_DEVICE_IDENTITY','Placement used a different complete device')
    inspect_preinitialized(audit,placement['initial_state'],device)
    state=placement['initial_state']; data=placement['input']; index=data['patch_index']
    if set(index)!=set(placement['patches']) or len(set(index))!=len(index): audit.fail('PLACEMENT_PATCH_INDEX','Projection index does not cover each patch once')
    graph=inspect_graph(audit,dag['nodes'],dag['edges'])
    if graph is None: return
    depths={}
    for node_id in graph.order: depths[node_id]=max((depths[p]+1 for p in graph.predecessors[node_id]),default=0)
    roles={'CX':['control','target'],'CZ':['left','right']}
    expected={n['id']:{'node_id':n['id'],'patch_operands':[n['patch_operands'][r] for r in roles[n['operation']]],'layer':depths[n['id']]} for n in dag['nodes'] if n['operation'] in roles}
    actual={e['node_id']:e for e in placement['interactions']}
    if actual!=expected or len(actual)!=len(placement['interactions']): audit.fail('PLACEMENT_INTERACTION_SOURCE','Placer interactions/weights/depths differ from the complete logical DAG')
    layers=[]
    for edge in placement['interactions']:
        while len(layers)<=edge['layer']: layers.append([])
        layers[edge['layer']].append([index.index(p) for p in edge['patch_operands']])
    if layers!=data['layers']: audit.fail('PLACEMENT_LAYER_PROJECTION','Raw placer layers do not preserve all directed source interactions')
    if not actual:
        audit.need('NONTRIVIAL_PLACEMENT_NOT_DEMONSTRATED','An empty interaction graph cannot qualify Enola patch optimization'); return
    provenance=placement['enola']; root=Path(__file__).resolve().parents[3]; source_root=root/pin['source_root']; source=source_root/provenance['source_file']
    if not source.resolve().is_relative_to((root/'third_party/enola').resolve()): raise ValueError('Source path outside pinned vendor')
    digest=sha256(source.read_bytes()).hexdigest()
    if provenance['commit']!=pin['commit'] or digest!=pin['source_files_sha256'][provenance['source_file']] or digest!=provenance['source_sha256']:
        audit.fail('PLACER_SOURCE_PIN','Actual SA source differs from the fixed pin/provenance')
    raw=provenance['raw_output']; mapping=raw['best_mapping']; shape=data['effective_grid_shape']
    for name,candidate in [('candidate',mapping),('baseline',placement['cost']['baseline_mapping']),('initial',raw['initial_mapping'])]:
        if len(candidate)!=len(index) or len({tuple(p) for p in candidate})!=len(candidate) or any(len(p)!=2 or any(type(p[a]) is not int or not 0<=p[a]<shape[a] for a in (0,1)) for p in candidate):
            audit.fail('PLACEMENT_DOMAIN','Candidate/baseline must give unique legal finite cells',mapping=name)
    weighted=lambda candidate:sum(max(1-.1*level,.1)*dist(candidate[a],candidate[b]) for level,edges in enumerate(layers) for a,b in edges)
    step=max(device['patch_geometry']['cell_extent_um']); candidate_cost=weighted(mapping); baseline_cost=weighted(placement['cost']['baseline_mapping'])
    for got,want in ((raw['best_cost'],candidate_cost),(placement['cost']['candidate'],candidate_cost),(placement['cost']['baseline'],baseline_cost),(placement['cost']['uniform_cell_step_um'],step),(placement['cost']['candidate_weighted_distance_um'],step*candidate_cost)):
        if not isclose(got,want,rel_tol=1e-8,abs_tol=1e-8): audit.fail('PLACEMENT_COST','Published objective differs from the actual graph and mapping',published=got,recomputed=want)
    transformed={p:{'anchor_um':[data['origin_um'][a]+step*mapping[i][a] for a in (0,1)],'orientation':'x_vertical_z_horizontal'} for i,p in enumerate(index)}
    if placement['placements']!=transformed or state['entry_spec']['placements']!=transformed or state['placement_ref']['artifact_id']!=placement['artifact_id']:
        audit.fail('PLACEMENT_OUTPUT_UNUSED','Observed Enola output does not determine final anchors and t=0 atom positions')
    if observation is None:
        audit.need('PLACER_OBSERVATION_MISSING','An independent actual original SA run observation is required'); return
    if observation['fixture'] or not observation['source_unchanged'] or observation['source_hashes'][provenance['source_file']]!=digest:
        audit.fail('PLACER_OBSERVATION_SOURCE','Observer is a fixture, changed, or observed different source')
    matches=[r for r in observation['records'] if r['source_file']==provenance['source_file'] and r['function']=='run']
    if len(matches)!=1:
        audit.fail('PLACER_RUN_NOT_OBSERVED','Expected one actual original-source SA run for this artifact'); return
    observed=matches[0]
    if observed['input_sha256']!=_hash(observed['inputs']) or observed['output_sha256']!=_hash(observed['output']): audit.fail('PLACER_OBSERVATION_HASH','Observed inputs/output were edited')
    expected_inputs={'chip_dim':data['requested_grid_shape'],'n_qubit':len(index),'list_gate':layers,'l2':False}
    if _hash(observed['inputs'])!=_hash(expected_inputs) or _hash(observed['output']['best_mapping'])!=_hash(mapping) or not isclose(observed['output']['best_cost'],candidate_cost,rel_tol=1e-8,abs_tol=1e-8):
        audit.fail('PLACER_RUN_DETACHED','Recorded raw input/output is unrelated to the returned layout')
    search=placement['search']; moves=observation['call_counts'].get(provenance['source_file']+':make_movement',0)
    if search['moves']!=moves or moves<=0: audit.fail('PLACER_SEARCH_COUNTER','Placement movement attempts differ from independent observation',observed=moves,published=search['moves'])
    if search['complete'] is not True or search['optimality_proven'] is not False: audit.fail('PLACER_SEARCH_CLAIM','Bounded nontrivial SA cannot claim global optimality or incomplete search as completed')
    budgets=observation['effective_placer_budgets']
    if len(budgets)!=1 or budgets[0]['values']['sa_l']!=search['budget']['moves_per_iteration'] or budgets[0]['values']['sa_iter_limit']!=search['budget']['max_iterations']-1 or budgets[0]['values']['sa_init_perturb_num']!=search['budget']['initial_moves']:
        audit.fail('PLACER_EFFECTIVE_BUDGET','Declared placement budget was not the actual initialized search budget')
    audit.metrics.update(placement_candidate_cost=candidate_cost,placement_baseline_cost=baseline_cost,placement_improvement=baseline_cost-candidate_cost,actual_sa_moves=moves,patch_placement_contributed=True,placement_global_optimality=False)


def validate_patch_placement(placement,device,logical_dag,*,observation=None,pin=None):
    audit=DAGAudit('patch_placement',{'placement':placement,'device':device,'logical_dag':logical_dag,'observation':observation,'pin':pin},fixture=placement.get('evidence_scope',{}).get('fixture',False))
    audit.interfaces={'R1-PREINITIALIZED-IF-001':'0.1.0','R2-LOGICAL-DAG-001':'0.1.0-draft','R4-HIERARCHICAL-IF-001':'0.1.0-draft'}
    if pin is None: audit.need('PLACER_PIN_MISSING','Actual R7 vendor source manifest is required')
    else: audit.check('real_patch_placement_and_entry',lambda:inspect_patch_placement(audit,placement,device,logical_dag,observation,pin))
    return audit.report()
