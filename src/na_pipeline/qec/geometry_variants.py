"""Geometry-aware equivalent representatives of the fixed ZZ instrument.

Half-turn is a code automorphism preserving logical X/Z modulo stabilizers.
We select top/bottom Z representatives independently, then assign resettable
syndrome probes. This is not a claim of a newly fault-tolerant surgery circuit.
"""
from copy import deepcopy
from itertools import product
import math

ROT180 = {**{f'd{i}': f'd{8-i}' for i in range(9)}, 'x0':'x2', 'x2':'x0', 'x1':'x3', 'x3':'x1',
          'z0':'z3', 'z3':'z0', 'z1':'z2', 'z2':'z1'}


def resolve_geometry_variants(dag, world):
    if dag.get('geometry_variant_selection'):
        return deepcopy(dag)
    result = deepcopy(dag)
    sites = {a.get('site_id', a['qubit_id']): a for a in world['atoms']}
    scopes = {}
    for o in result['nodes']:
        scope = o.get('metadata', {}).get('joint_zz_geometry_scope')
        if scope:
            key = o['id'].rsplit('/', 1)[0] + '/' + scope
            scopes.setdefault(key, []).append(o)
    selections = []
    for scope, ops in scopes.items():
        g0 = [o for o in ops if o.get('metadata', {}).get('joint_check') == 'g0'][:2]
        if len(g0) != 2:
            raise ValueError('ZZ_VARIANT_SOURCE_UNRECOGNIZED')
        # New Z gauges couple data -> probe, once from each operand.
        blocks = [o['qubits'][0].rsplit('/', 1)[0] for o in g0]
        if len(set(blocks)) != 2:
            raise ValueError('ZZ_VARIANT_OPERANDS_ALIAS')
        allowed = [q for q, a in sites.items() if q.rsplit('/',1)[0] in blocks and q.rsplit('/',1)[-1] in ROT180 and not q.rsplit('/',1)[-1].startswith('d') and a['carrier'] == 'SLM']
        old_probes = {o['qubits'][1] for o in ops if o.get('metadata', {}).get('joint_check', '').startswith('g')}
        allowed = sorted(set(allowed) | old_probes)
        choices = []
        for flags in product((False, True), repeat=2):
            mapping = {q: block + '/' + ROT180[q.rsplit('/',1)[-1]] for block, flag in zip(blocks, flags) if flag
                       for q in sites if q.rsplit('/',1)[0] == block and q.rsplit('/',1)[-1] in ROT180}
            cost = 0.; assignment = {}
            checks = {}
            for o in ops:
                instrument = o.get('metadata', {}).get('joint_check_instrument')
                if instrument and o['params'].get('name') == 'CX':
                    checks.setdefault(instrument, []).append(o)
            for instrument, couplings in checks.items():
                # The common syndrome carrier is the probe, never a data site.
                common = set(couplings[0]['qubits'])
                for o in couplings[1:]: common &= set(o['qubits'])
                probes = [q for q in common if not q.rsplit('/',1)[-1].startswith('d')]
                if len(probes) != 1: raise ValueError('ZZ_CHECK_PROBE_AMBIGUOUS')
                old = probes[0]
                support = [mapping.get(q, q) for o in couplings for q in o['qubits'] if q != old]
                ranked = [(sum(math.dist(sites[q]['position_um'], sites[p]['position_um']) for q in support), p) for p in allowed]
                value, chosen = min(ranked)
                cost += value; assignment[instrument] = (old, chosen)
            # Distance between the logical representatives breaks otherwise
            # identical probe-placement scores deterministically.
            distance = sum(math.dist(sites[mapping.get(blocks[0]+f'/d{i}',blocks[0]+f'/d{i}')]['position_um'],
                                     sites[mapping.get(blocks[1]+f'/d{i}',blocks[1]+f'/d{i}')]['position_um']) for i in range(3))
            choices.append((cost, distance, flags, mapping, assignment))
        cost, distance, flags, mapping, assignment = min(choices, key=lambda c: c[:3])
        for o in ops:
            instrument = o.get('metadata', {}).get('joint_check_instrument')
            old, probe = assignment.get(instrument, (None, None))
            o['qubits'] = [probe if q == old else mapping.get(q, q) for q in o['qubits']]
        # Group bindings belong to the split rounds, where the half-turn also
        # relabels the check ancillas. Their result IDs retain source provenance.
        opids = {o['id'] for o in ops}
        for g in result['groups']:
            if all(m['measurement_op_id'] in opids for m in g['members']):
                for m in g['members']:
                    m['physical_qubit_id'] = mapping.get(m['physical_qubit_id'], m['physical_qubit_id'])
                    m['local_id'] = m['physical_qubit_id'].rsplit('/',1)[-1]
        selections.append({'scope': scope, 'operand_blocks': blocks, 'half_turn_variants': list(flags),
                           'representatives': [[mapping.get(b+f'/d{i}', b+f'/d{i}') for i in range(3)] for b in blocks],
                           'probe_assignments': {k: v[1] for k,v in assignment.items()}, 'distance_score_um': cost,
                           'candidate_count': 4, 'metric': 'sum_probe_to_support_distance_then_representative_distance',
                           'logical_equivalence': 'surface17_half_turn_automorphism', 'fault_tolerance': 'unverified'})
    if selections:
        # Changing auxiliary assignment introduces new physical identity edges.
        # Original protocol fences remain; add precise last-use edges as well.
        last = {}; existing = {(e['source'],e['target']) for e in result['edges']}
        for o in result['nodes']:
            for q in o['qubits']:
                if q in last and last[q] not in o['after']:
                    o['after'].append(last[q])
                last[q] = o['id']
            for dep in o['after']:
                if (dep,o['id']) not in existing:
                    result['edges'].append({'source':dep,'target':o['id'],'kind':'quantum'}); existing.add((dep,o['id']))
        targets={e['target'] for e in result['edges']};sources={e['source'] for e in result['edges']}
        byid={o['id']:o for o in result['nodes']}
        for e in result['edges']:
            if 'qubits' in e:e['qubits']=sorted(set(byid[e['source']]['qubits']) & set(byid[e['target']]['qubits']))
        result['roots']=[o['id'] for o in result['nodes'] if o['id'] not in targets]
        result['terminals']=[o['id'] for o in result['nodes'] if o['id'] not in sources]
        from .physical_dag import _readout_services
        result['readout_services']=_readout_services(result['nodes'],result['qubits'],result['groups'])
        result['geometry_variant_selection'] = selections
    return result
