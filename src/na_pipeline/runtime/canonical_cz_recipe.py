"""Canonical-layout CZ using transport before/after one existing CZ batch.

If the qualified bare CZ pairs left[i] with right[P(i)], move the right data
carriers by inverse(P), pulse equal-index pairs, and move by P to restore them.
The induced physical pairs are exactly the original nine pairs. No H or SWAP
gate is introduced. This new geometry recipe requires native qualification.
"""
from copy import deepcopy
from na_pipeline.backend.enola_kernel import StrategyError, digest
from na_pipeline.qec import validate_physical_dag
from .parametric_component import CompiledComponentTemplate


def derive_canonical_cz_recipe(transport_plan, transport_validation, transport_device,
                               bare_plan, bare_validation, device):
    for p,v,d in [(transport_plan,transport_validation,transport_device), (bare_plan,bare_validation,device)]:
        if (v.get('passed') is not True or v.get('input_sha256',{}).get('physical_plan')!=digest(p)
                or v.get('input_sha256',{}).get('device')!=digest(d)):
            raise StrategyError('CZ_ADAPTER_PARENT_HASH','Both original source qualifications must match')
    bare = bare_plan['physical_dags'][0]
    pair_by_left = {}
    for n in bare['nodes']:
        if n['kind']!='gate' or n['params']!={'name':'CZ'} or len(n['qubits'])!=2:
            raise StrategyError('CZ_ADAPTER_SOURCE','Require exactly the existing nine bare physical CZs')
        left,right = n['qubits']
        if not left.startswith('left/d') or not right.startswith('right/d'):
            raise StrategyError('CZ_ADAPTER_PORTS','Require original left/right information carriers')
        pair_by_left[int(left.rsplit('d',1)[1])] = int(right.rsplit('d',1)[1])
    if set(pair_by_left)!=set(range(9)) or set(pair_by_left.values())!=set(range(9)) or len(bare['nodes'])!=9:
        raise StrategyError('CZ_ADAPTER_BIJECTION','Nine distinct pair endpoints are required')
    permutation = [pair_by_left[i] for i in range(9)]
    inverse = [permutation.index(i) for i in range(9)]
    virtual = deepcopy(transport_plan)
    dag = virtual['physical_dags'][0]
    nodes = dag['nodes']
    if (len(nodes)!=11 or [n['kind'] for n in nodes]!=['permute']+['gate']*9+['permute']
            or any(n['params']!={'name':'CZ'} or n['qubits']!=['left/d'+str(i),'right/d'+str(i)] for i,n in enumerate(nodes[1:10]))):
        raise StrategyError('CZ_ADAPTER_TRANSPORT_SOURCE','Require the existing transport / equal-index CZ / transport skeleton')
    for n in (nodes[0],nodes[-1]):
        if n['qubits']!=['right/d'+str(i) for i in range(9)]:
            raise StrategyError('CZ_ADAPTER_TRANSPORT_PORTS','Transport must retain all nine target carriers')
    nodes[0]['params']['destination_indices'] = inverse
    nodes[-1]['params']['destination_indices'] = permutation
    for n, direction in ((nodes[0], 'inverse_bare_CZ_pairing'), (nodes[-1], 'restore_canonical_sites')):
        n['metadata'] = {**n.get('metadata', {}), 'protocol': 'canonical_CZ_carrier_alignment',
                         'permutation': direction, 'quantum_effect': 'transport_only_no_H'}
    graph = virtual['module_composition']['dependency_graph']
    if [m['kind'] for m in graph['modules']] != ['permute','entangling_layer','permute']:
        raise StrategyError('CZ_ADAPTER_PARTITION','Keep the original complete nine-pair physical pulse')
    byid = {n['id']:n for n in nodes}
    for m in graph['modules']:
        for n in m['dag']['nodes']:
            n['params'] = deepcopy(byid[n['id']]['params'])
            if 'metadata' in byid[n['id']]:
                n['metadata'] = deepcopy(byid[n['id']]['metadata'])
        validate_physical_dag(m['dag'])
    validate_physical_dag(dag)
    graph['source_hashes'] = [digest(dag)]
    template = CompiledComponentTemplate(virtual)
    template.original_plan_hash = digest(transport_plan)
    template.input_boundary = {'kind':'canonical_CZ_transport_adapter','current_bare_CZ_plan':digest(bare_plan)}
    # Symbolic carrier tracking: no wavefunction or measurement is simulated.
    occupants = list(range(9))
    def move(xs,p):
        result = [None]*9
        for i,j in enumerate(p): result[j]=xs[i]
        return result
    middle = move(occupants,inverse)
    restored = move(middle,permutation)
    if middle!=permutation or restored!=occupants:
        raise StrategyError('CZ_ADAPTER_SYMBOLIC_PROOF','Adapter must reproduce exact pairs and restore identity')
    template.derivation = {'schema_version':'CanonicalCZTransportRecipe/0.1','bare_plan_sha256':digest(bare_plan),
        'transport_parent_sha256':digest(transport_plan),'enter_destinations':inverse,'exit_destinations':permutation,
        'effective_right_partners':middle,'expected_right_partners':permutation,'final_carrier_order':restored,
        'symbolic_pair_equivalence':True,'native_CZ_batch_count':1,'native_CZ_pairs':9,
        'added_quantum_gates':[],'geometry_qualification_inherited':False,'native_bodies_imported_from_old_device':False}
    return template
