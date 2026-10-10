"""Independent Surface-17 generator/circuit algebra read from JSON artifacts."""
from collections import Counter
from itertools import combinations, product

from .semantic_common import SemanticAudit, symplectic, multiply, conjugate, span_basis, in_span

# Independently transcribed from Tomita--Svore v2 Table 2. No R3 constants or
# check functions are imported. Qubit numbering is the documented row-major map.
REFERENCE = [('X',(0,1,3,4)),('X',(1,2)),('X',(4,5,7,8)),('X',(6,7)),
             ('Z',(0,3)),('Z',(1,2,4,5)),('Z',(3,4,6,7)),('Z',(5,8))]


def _pauli(basis, support, qubits):
    mask=sum(1<<qubits.index(q) for q in support)
    return (mask,0,0) if basis=='X' else (0,mask,0)


def audit_surface17(program: dict) -> dict:
    audit=SemanticAudit('surface17',program)
    code=program.get('metadata',{}).get('code_definition',{})
    templates=program.get('templates',{})
    data=[f'd{i}' for i in range(9)]
    generators=[]
    lx=lz=None

    def code_algebra():
        nonlocal generators,lx,lz
        checks=code['stabilizers']
        audit.require(code['data_qubits']==data and len(checks)==8,'CODE_INVENTORY','Expected nine row-major data qubits and eight checks')
        observed={(s['pauli'],tuple(sorted(int(q[1:]) for q in s['support']))) for s in checks}
        audit.require(observed==set(REFERENCE) and all(s['sign']==1 for s in checks),'STABILIZER_REFERENCE','Generators differ from the cited Surface-17 reference')
        generators=[_pauli(s['pauli'],s['support'],data) for s in checks]
        audit.require(all(symplectic(a,b)==0 for a,b in combinations(generators,2)),'NONCOMMUTING_STABILIZERS','Generators must commute')
        pivots=span_basis([x|(z<<9) for x,z,p in generators])
        audit.require(len(pivots)==8,'STABILIZER_RANK','Rank must be 8, encoding one logical qubit')
        lx=_pauli('X',code['logical_x'],data); lz=_pauli('Z',code['logical_z'],data)
        audit.require(symplectic(lx,lz)==1 and all(not symplectic(l,g) for l in (lx,lz) for g in generators),'LOGICAL_PAULI','Logical representatives must commute with checks and anticommute with each other')
        minimum=None; tested=0
        for weight in (1,2,3):
            found=False
            for support in combinations(range(9),weight):
                for kinds in product((1,2,3),repeat=weight):
                    x=sum(1<<q for q,k in zip(support,kinds) if k&1)
                    z=sum(1<<q for q,k in zip(support,kinds) if k&2)
                    tested+=1
                    if all(not symplectic((x,z,0),g) for g in generators) and not in_span(x|(z<<9),pivots): found=True
            if found: minimum=weight; break
        audit.require(minimum==3,'STATIC_CODE_DISTANCE','Minimal checked logical Pauli weight is not three')
        audit.metrics.update(stabilizer_rank=len(pivots),static_code_distance=minimum,paulis_enumerated=tested)

    audit.check('code_generators_logical_distance',code_algebra)

    def syndrome(template, stage):
        formals=template['qubits']; ops=[n['op'] for n in template['body']]
        ancillas=[s['ancilla'] for s in code['stabilizers']]
        first=next(i for i,op in enumerate(ops) if op['kind']=='reset' and op['qubits'][0] in ancillas)
        prefix,body=ops[:first],ops[first:]
        expected_prefix=[('reset',None,q) for q in data]
        if stage=='prepare_plus': expected_prefix += [('gate','H',q) for q in data]
        actual_prefix=[(o['kind'],o['params'].get('name'),o['qubits'][0]) for o in prefix]
        audit.require(actual_prefix==(expected_prefix if stage.startswith('prepare') else []),'PREPARATION_PREFIX','Incorrect physical reset/H initialization',template['template_id'])
        audit.require(all(o['params'].get('basis')=='Z' for o in prefix if o['kind']=='reset'),'PREPARATION_BASIS','Data initialization must reset to Z=+1',template['template_id'])
        resets=[o for o in body if o['kind']=='reset']
        audit.require(Counter(q for o in resets for q in o['qubits'])==Counter(ancillas) and all(o['params'].get('basis')=='Z' for o in resets),'ANCILLA_INITIALIZATION','Each syndrome ancilla must reset once in Z',template['template_id'])
        unconditioned=[o for o in body if o['kind']=='gate' and o['condition'] is None]
        audit.require(max(body.index(o) for o in resets)<min(body.index(o) for o in unconditioned),'ANCILLA_RESET_ORDER','Ancilla resets must precede this round of extraction',template['template_id'])
        measurements=[o for o in body if o['kind']=='measure']
        audit.require(max(body.index(o) for o in unconditioned)<min(body.index(o) for o in measurements),'SYNDROME_READOUT_ORDER','All entangling/basis gates must precede readouts',template['template_id'])
        audit.require(len(measurements)==8 and {o['qubits'][0] for o in measurements}==set(ancillas),'SYNDROME_MEASUREMENTS','Eight ancilla measurements required',template['template_id'])
        for check in code['stabilizers']:
            anc=check['ancilla']; record=next(o for o in measurements if o['qubits']==[anc])
            audit.require(record['params'].get('basis')=='Z' and len(record['writes'])==1,'SYNDROME_BASIS','Syndrome must write a unique Z result',record['id'])
            pauli=_pauli('Z',[anc],formals)
            for op in reversed(unconditioned):
                name=op['params']['name']; inverse={'S':'SDG','SDG':'S'}.get(name,name)
                pauli=conjugate(pauli,inverse,[formals.index(q) for q in op['qubits']])
            expected=multiply(_pauli(check['pauli'],check['support'],formals),_pauli('Z',[anc],formals))
            audit.require(pauli==expected,'SYNDROME_OBSERVABLE','Backward readout is not exactly the named stabilizer times its own initial Z',record['id'])
        # There can be no data reset/measurement or hidden gate after readouts.
        allowed={'gate','reset','measure'}
        audit.require(all(o['kind'] in allowed and (o['kind'] not in ('reset','measure') or set(o['qubits'])<=set(ancillas)) for o in body),'SYNDROME_DATA_LIFECYCLE','Syndrome must retain all data carriers',template['template_id'])
        corrections=[o for o in body if o['condition'] is not None]
        if stage=='memory_round':
            audit.require(not corrections,'MEMORY_CORRECTION','Memory template unexpectedly applies sign correction')
            return
        random_basis='X' if stage=='prepare_zero' else 'Z'
        random_checks=[s for s in code['stabilizers'] if s['pauli']==random_basis]
        result_for={s['id']:next(o['writes'][0] for o in measurements if o['qubits']==[s['ancilla']]) for s in random_checks}
        measurement_ids={o['id'] for o in measurements}
        for op in corrections:
            audit.require(op['kind']=='gate' and op['params'].get('name')==('Z' if random_basis=='X' else 'X') and op['condition']['equals']==1 and op['condition']['bit'] in result_for.values() and op['condition']['bit'] in op['reads'] and measurement_ids<=set(op['after']),'INITIALIZATION_CORRECTION','Sign fix must follow all measurements and bind the correct syndrome',op['id'])
        for mask in range(16):
            values={result_for[s['id']]:(mask>>i)&1 for i,s in enumerate(random_checks)}
            correction=(0,0,0)
            for op in corrections:
                if values.get(op['condition']['bit'])==op['condition']['equals']:
                    correction=multiply(correction,_pauli(op['params']['name'],op['qubits'],data))
            for s,g in zip(code['stabilizers'],generators):
                bit=values.get(result_for.get(s['id']),0)
                audit.require(symplectic(correction,g)==bit,'SIGN_FIX_SYNDROME',f'Incorrect correction for syndrome {mask:04b}',template['template_id'])
            audit.require(not symplectic(correction,lx) and not symplectic(correction,lz),'SIGN_FIX_LOGICAL','Projection sign correction changes logical information',template['template_id'])
        audit.metrics[f'{stage}_sign_patterns']=16

    for template in templates.values():
        stage=template.get('metadata',{}).get('stage')
        if stage in ('memory_round','prepare_zero','prepare_plus'):
            audit.check(stage,lambda t=template,s=stage:syndrome(t,s))

    def transverse():
        t=next(t for t in templates.values() if t['metadata']['stage']=='logical_cx')
        q=t['qubits']; ops=[n['op'] for n in t['body']]
        audit.require(len(ops)==9 and all(o['kind']=='gate' and o['params']=={'name':'CX'} and o['condition'] is None for o in ops),'TRANSVERSAL_CONTENT','Transversal CX requires nine unconditional physical CX')
        def move(pauli):
            for op in ops: pauli=conjugate(pauli,op['params']['name'],[q.index(x) for x in op['qubits']])
            return pauli
        def mapped(p,prefix):
            x,z,r=p
            return (sum(1<<q.index(f'{prefix}{i}') for i in range(9) if x&(1<<i)),sum(1<<q.index(f'{prefix}{i}') for i in range(9) if z&(1<<i)),r)
        gens=[mapped(g,b) for b in ('c','t') for g in generators]
        pivots=span_basis([x|(z<<18) for x,z,r in gens])
        audit.require(all(in_span(a[0]|(a[1]<<18),pivots) and a[2]==0 for a in map(move,gens)),'TRANSVERSAL_STABILIZERS','CX does not preserve joint code stabilizers')
        xc,zc,xt,zt=mapped(lx,'c'),mapped(lz,'c'),mapped(lx,'t'),mapped(lz,'t')
        for source,target in ((xc,multiply(xc,xt)),(zc,zc),(xt,xt),(zt,multiply(zc,zt))):
            audit.require(move(source)==target,'TRANSVERSAL_LOGICAL_ACTION','Logical Pauli action/direction is not CX')
        audit.metrics['transversal_logical_images']=4
    audit.check('transversal_cnot',transverse)

    def structure():
        body=program['body']
        stages=[templates[n['template_id']]['metadata']['stage'] for n in body]
        audit.require(stages==['prepare_plus','prepare_zero','memory_round','memory_round','logical_cx','memory_round','memory_round','destructive_z_readout_reset','destructive_z_readout_reset'],'SLICE_PROTOCOL_ORDER','Two-block protocol order changed')
        for n in body:
            audit.require(n['kind']=='call' and len(set(n['bindings'].values()))==len(n['bindings']),'INSTANCE_BINDING','Template call aliases physical qubits',n['id'])
        for node,block in zip(body,['control','target','control','target',None,'control','target','control','target']):
            if block:
                expected={q:f'{block}/{q}' for q in templates[node['template_id']]['qubits']}
            else:
                expected={f'{p}{i}':f'{b}/d{i}' for p,b in [('c','control'),('t','target')] for i in range(9)}
            audit.require(node['bindings']==expected,'BLOCK_BINDING','Protocol call is bound to the wrong logical block or direction',node['id'])
        readout=next(t for t in templates.values() if t['metadata']['stage']=='destructive_z_readout_reset')
        ops=[n['op'] for n in readout['body']]
        reads=[o for o in ops if o['kind']=='measure']; resets=[o for o in ops if o['kind']=='reset']
        audit.require([o['qubits'][0] for o in reads]==data and Counter(q for o in resets for q in o['qubits'])==Counter(readout['qubits']) and all(o['params'].get('basis')=='Z' for o in reads+resets) and max(ops.index(o) for o in reads)<min(ops.index(o) for o in resets),'FINAL_READOUT_RESET','Terminal measurement/reset inventory, basis or order changed')
        parity=[f'm_{q}' for q in code['logical_z']]
        audit.require(readout['metadata']['logical_z_result_parity']==parity,'LOGICAL_READOUT_PARITY','Logical Z readout must match its physical support')
    audit.check('two_block_protocol_structure',structure)
    return audit.report()
