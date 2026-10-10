"""Explicit physical-circuit input with contiguous parallel measurement blocks."""
from copy import deepcopy

from .enola_kernel import StrategyError, digest
from .physical_dag import compile_physical_dag


def measurement_circuit_dag(circuit, initial_state):
    """Preserve source records; consecutive distinct-Z measurements share a frontier."""
    from na_pipeline.qec.physical_dag import validate_physical_dag
    if circuit.get('schema_version') != 'measurement-circuit/0.1':
        raise StrategyError('MEASUREMENT_CIRCUIT_SCHEMA', 'measurement-circuit/0.1 required')
    config = circuit.get('measurement')
    if not isinstance(config,dict) or config.get('placement') not in {'zac_style_min_cost_matching','rigid_array_translation'} or config != {'zone_id': 'measurement', 'parallel_contiguous': True,
                  'placement': config['placement'], 'return_to_source': True}:
        raise StrategyError('MEASUREMENT_CONFIG_UNSUPPORTED', 'Explicit supported measurement configuration required')
    nodes, edges, frontier, source_map, writers = [], [], [], {}, {}
    ops = circuit['operations']
    if len({o['id'] for o in ops}) != len(ops):
        raise StrategyError('PHYSICAL_ID_COLLISION', 'Source operation IDs must be unique')
    i, batch = 0, 0
    while i < len(ops):
        segment = [ops[i]]
        if ops[i]['kind'] == 'measure':
            while i+len(segment) < len(ops) and ops[i+len(segment)]['kind'] == 'measure':
                segment.append(ops[i+len(segment)])
            qubits = [o['qubits'][0] for o in segment if len(o['qubits']) == 1]
            if len(qubits) != len(segment) or len(set(qubits)) != len(qubits):
                raise StrategyError('READOUT_QUBIT_ALIAS', 'Consecutive measurements must address distinct single qubits')
            batch += 1
        new_frontier = []
        for source in segment:
            op = deepcopy(source)
            if op.get('after') or op.get('reads') or op.get('condition'):
                raise StrategyError('MEASUREMENT_CIRCUIT_CONTROL_UNSUPPORTED', 'This linear preview input does not infer explicit feedback or reorder supplied dependencies')
            for key in ('id','kind','qubits','params','source_ids'):
                if key not in op:
                    raise StrategyError('MEASUREMENT_CIRCUIT_FIELD', 'Missing source field', field=key)
            op.update(after=list(frontier), reads=[], condition=None, writes=op.get('writes', []))
            op.setdefault('metadata', {})
            if op['kind'] == 'measure':
                if op['params'].get('basis') != 'Z' or len(op['writes']) != 1:
                    raise StrategyError('UNSUPPORTED_MEASUREMENT', 'Explicit physical Z measurement with one output required')
                op['metadata']['measurement_batch'] = f"{circuit['artifact_id']}/readout-{batch}"
                op['metadata']['measurement_placement'] = config['placement']
            for dep in frontier:
                edges.append({'source': dep, 'target': op['id'], 'kind': 'protocol'})
            for bit in op['writes']:
                if bit in writers:
                    raise StrategyError('PHYSICAL_RESULT_ALIAS', 'Duplicate result identity', result=bit)
                writers[bit] = op['id']
            nodes.append(op);new_frontier.append(op['id'])
            source_map[op['id']] = {'source_ids': list(op['source_ids']), 'input_operation_id': source['id']}
        frontier = new_frontier
        i += len(segment)
    dag = {'schema_version': 'PhysicalDAG/0.1.0', 'artifact_id': circuit['artifact_id']+'/physical-dag',
           'entry_mode': 'preinitialized', 'provenance': {'producer': 'measurement_circuit/0.1', 'fixture': True},
           'quantum_state_simulated': False, 'hardware_executed': False, 'loss_enabled': False,
           'qubits': [{'id': a['qubit_id'], 'aod_group': a['aod_group']} for a in initial_state['atoms']],
           'nodes': nodes, 'edges': edges, 'groups': [], 'roots': [n['id'] for n in nodes if not n['after']],
           'terminals': frontier, 'result_producers': writers, 'source_map': source_map,
           'external_reads': [], 'execution_guard': None, 'input_circuit_hash': digest(circuit)}
    validate_physical_dag(dag)
    return dag


def compile_measurement_circuit(circuit, device, initial_state, *, budget=None):
    dag = measurement_circuit_dag(circuit, initial_state)
    plan = compile_physical_dag(dag, device, initial_state, budget=budget)
    plan['input_circuit'] = deepcopy(circuit)
    return plan
