"""Independent signed certificate for a complete Surface-17 S-SE instrument."""
from .semantic_qec import REFERENCE
from .semantic_common import conjugate,multiply


def inspect_s_se(audit,dag,graph):
    ids=[q['id'] for q in dag['qubits']]
    if len(ids)!=17 or {q.rsplit('/',1)[-1] for q in ids}!={*[f'd{i}' for i in range(9)],*[f'{a}{i}' for a in ('x','z') for i in range(4)]}:
        audit.fail('S_SE_CODE_PORTS','S-SE requires one complete Surface-17 code block');return
    index={q:i for i,q in enumerate(ids)};prefix=ids[0].rsplit('/',1)[0]
    def mask(indices):return sum(1<<index[prefix+'/d'+str(i)] for i in indices)
    data={q for q in ids if q.rsplit('/',1)[-1].startswith('d')};aux=set(ids)-data
    reads=[o for o in dag['nodes'] if o['kind']=='measure']
    if len(reads)!=8 or {o['qubits'][0] for o in reads}!=aux:
        audit.fail('S_SE_READOUT','Each of the eight auxiliaries must be read once')
    if any(set(o['qubits'])&data for o in dag['nodes'] if o['kind'] in ('reset','measure')):
        audit.fail('S_SE_LIVE_DATA_DESTROYED','S-SE cannot reset or measure data')
    gates=[o for o in dag['nodes'] if o['kind']=='gate']
    if any(o['condition'] for o in gates):
        audit.fail('S_SE_CONDITION','This certificate covers the unconditional full S-SE circuit');return
    def image(p):
        for o in gates:p=conjugate(p,o['params']['name'],[index[q] for q in o['qubits']])
        return p
    stabilizers=[(mask(s),0,0) if b=='X' else (0,mask(s),0) for b,s in REFERENCE]
    stabilizers += [(0,1<<index[q],0) for q in aux]
    output={(0,0,0)}
    for p in stabilizers:
        transformed=image(p);output|={multiply(q,transformed) for q in list(output)}
    if not all(p in output for p in stabilizers):
        audit.fail('S_SE_CODE_OR_ANCILLA_EXIT','Unitary round must restore the encoded stabilizers and disentangled Z-readout auxiliaries')
    x=(mask((0,3,6)),0,0);z=(0,mask((0,1,2)),0)
    y=multiply(x,z);y=(*y[:2],(y[2]+(1 if dag['operation']=='S' else -1))%4)
    if multiply(image(x),y) not in output or multiply(image(z),z) not in output:
        audit.fail('S_SE_LOGICAL_PHASE','Wrong signed logical S/S-dagger action')
    audit.metrics.update(s_se_signed_stabilizers_checked=16,s_se_logical_paulis_checked=2,
                         certificate_scope='encoded noiseless operator map; no noisy decoding or fault-distance claim')
