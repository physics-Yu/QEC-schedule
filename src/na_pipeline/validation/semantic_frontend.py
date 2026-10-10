"""Static full-operator, rational QPE and integer postprocessing audits."""
from fractions import Fraction
from math import sqrt, pi, gcd

from .semantic_common import SemanticAudit


def operator_matrix(ops, qubits):
    """Construct the entire small operator, never a state or sampled outcome."""
    size=1<<len(qubits)
    matrix=[[complex(r==c) for c in range(size)] for r in range(size)]
    s=1/sqrt(2)
    gates={'H':((s,s),(s,-s)),'X':((0,1),(1,0)),'Z':((1,0),(0,-1)),
           'S':((1,0),(0,1j)),'SDG':((1,0),(0,-1j)),
           'T':((1,0),(0,complex(s,s))),'TDG':((1,0),(0,complex(s,-s)))}
    for op in ops:
        if op['kind']!='gate' or op['condition'] is not None or op['reads'] or op['writes']:
            raise ValueError('arithmetic template must be an unconditional operator')
        name=op['params']['name']; indices=[qubits.index(q) for q in op['qubits']]
        if len(indices)!=(2 if name=='CX' else 1) or len(set(indices))!=len(indices) or set(op['params'])!={'name'}:
            raise ValueError('unsupported arithmetic arity or gate parameter')
        if name=='CX':
            control,target=indices
            for row in range(size):
                if row&(1<<control) and not row&(1<<target):
                    partner=row^(1<<target)
                    matrix[row],matrix[partner]=matrix[partner],matrix[row]
        else:
            gate=gates[name]; target=indices[0]
            for row in range(size):
                if row&(1<<target): continue
                partner=row|(1<<target); a,b=matrix[row],matrix[partner]
                matrix[row]=[gate[0][0]*x+gate[0][1]*y for x,y in zip(a,b)]
                matrix[partner]=[gate[1][0]*x+gate[1][1]*y for x,y in zip(a,b)]
    return matrix


def _angle(params):
    a=params['angle_pi']
    return Fraction(a['numerator'],a['denominator'])


def _post_expected(y,N,a):
    common=gcd(N,a)
    if common!=1: return 'success',None,sorted([common,N//common])
    if y==0: return 'failed',None,[]
    # Build Euclidean quotients first, then reconstruct each prefix from its
    # reciprocal tail; deliberately do not call R2's convergent recurrence.
    n,d=y,256; terms=[]
    while d:
        terms.append(n//d); n,d=d,n%d
    for end in range(1,len(terms)+1):
        candidate=Fraction(terms[end-1])
        for term in reversed(terms[:end-1]): candidate=term+1/candidate
        q=candidate.denominator
        if not 2<=q<N or abs(Fraction(y,256)-candidate)>Fraction(1,2*q*q) or q%2 or pow(a,q,N)!=1: continue
        root=pow(a,q//2,N)
        if root in (1,N-1): continue
        proper=[v for v in (gcd(root-1,N),gcd(root+1,N)) if 1<v<N]
        if proper:
            divisor=min(proper)
            return 'success',q,sorted([divisor,N//divisor])
    return 'failed',None,[]


def audit_shor15(program: dict, postprocess_results: list[dict] | None = None) -> dict:
    audit=SemanticAudit('shor15',program)
    templates=program.get('templates',{})

    def dependency_contract():
        def sequence(nodes,formals=None):
            previous={}; ancestors={}; producers={}
            for node in nodes:
                if node['kind']=='op':
                    op=node['op']; oid=op['id']; qubits=op['qubits']; deps=op['after']; reads=op['reads']; writes=op['writes']; condition=op['condition']
                else:
                    oid=node['id']; qubits=list(node['bindings'].values()); deps=node['after']; reads=[]; writes=[]; condition=node.get('condition')
                if condition: reads=list(set(reads)|{condition['bit']})
                audit.require(oid not in ancestors and all(d in ancestors for d in deps),'LOGICAL_DEPENDENCY','Duplicate or forward dependency',oid)
                reach=set(deps)
                for d in deps: reach |= ancestors.get(d,set())
                for q in qubits:
                    audit.require(q not in previous or previous[q] in reach,'LOGICAL_QUBIT_ORDER','Required same-qubit operation order is missing',oid)
                    previous[q]=oid
                for bit in reads:
                    audit.require(bit in producers and producers[bit] in reach,'LOGICAL_RESULT_DEPENDENCY','Result producer is not a causal ancestor',oid)
                for bit in writes:
                    audit.require(bit not in producers,'LOGICAL_RESULT_REUSED','Logical result is written by multiple instances',oid)
                    producers[bit]=oid
                ancestors[oid]=reach
        sequence(program['body'])
        for template in templates.values(): sequence(template['body'])
    audit.check('logical_dependency_contract',dependency_contract)

    def permutations():
        errors={}; tested=0
        for multiplier in (1,2,4):
            template=next(t for t in templates.values() if t['metadata'].get('protocol')=='controlled-full-permutation-mod15' and t['metadata'].get('multiplier')==multiplier)
            formals=template['formal_qubits']
            audit.require(formals==['ctrl','w0','w1','w2','w3'],'MODULAR_QUBIT_ORDER','Arithmetic bit order changed')
            ops=[n['op'] for n in template['body']]
            matrix=operator_matrix(ops,formals)
            maximum=0.
            for column in range(32):
                control=column&1; x=column>>1
                target=x if not control or x==15 else (multiplier*x)%15
                row=(target<<1)|control
                maximum=max(maximum,max(abs(matrix[r][column]-int(r==row)) for r in range(32)))
                tested+=1
            audit.require(maximum<1e-12,'MODULAR_OPERATOR',f'U{multiplier} is not the full phase-correct controlled permutation',template['template_id'])
            errors[str(multiplier)]=maximum
        audit.metrics.update(controlled_inputs_checked=tested,operator_dimension=32,operator_max_entry_errors=errors,operator_comparison='floating complete matrix; tolerance 1e-12')
    audit.check('full_modular_operators',permutations)

    def qpe():
        algorithm=program['algorithm']
        audit.require(all(algorithm[k]==v for k,v in {'N':15,'a':2,'work_bits':4,'phase_bits':8,'extension_x15':'fixed'}.items()),'ALGORITHM_CONFIG','Task fixes N15 a2 four work bits and eight sequential phase bits')
        original=[]
        for node in program['body']:
            if node.get('synthesis_certificate_ref'):
                src=node['logical_source_op']
                audit.require(node['id']==src['id'] and node['condition']==src['condition'] and node['bindings']=={'q':'ctrl'} and node.get('condition_scope')=='classical' and node['after']==src['after'],'SYNTHESIS_SOURCE_BINDING','Lowered feedback call changed its original condition/target/order',node['id'])
                original.append({'kind':'op','op':src})
            else: original.append(node)
        cursor=0; angles={}; producer_ids={}; observed_ids=[]
        def take(kind,name,qubits,oid,writes=None):
            nonlocal cursor
            node=original[cursor]; cursor+=1
            audit.require(node['kind']=='op','QPE_STRUCTURE','Expected an explicit source operation',oid)
            op=node['op']; observed_ids.append(op['id'])
            audit.require(op['id']==oid and op['kind']==kind and op['qubits']==qubits and (name is None or op['params'].get('name')==name),'QPE_OPERATION','Round operation/binding/order changed',oid)
            if kind=='reset': audit.require(op['params']=={'basis':'Z','value':0},'QPE_RESET','Reset must prepare computational zero',oid)
            if name in ('H','X') or kind in ('reset','measure'):
                audit.require(op['condition'] is None and not op['reads'],'QPE_UNCONDITIONAL','Preparation and readout cannot become conditional',oid)
            if writes is not None:
                audit.require(op['writes']==writes and op['params'].get('basis')=='Z','QPE_MEASUREMENT','Wrong phase bit or basis',oid)
                for bit in writes: producer_ids[bit]=oid
            return op
        for i in range(4): take('reset',None,[f'w{i}'],f'init/reset_w{i}')
        take('gate','X',['w0'],'init/work_one')
        for j in range(7,-1,-1):
            take('reset',None,['ctrl'],f'round{j}/reset')
            take('gate','H',['ctrl'],f'round{j}/prepare')
            call=original[cursor]; cursor+=1
            template=templates[call['template_id']]
            audit.require(call['kind']=='call' and call['id']==f'round{j}/multiply' and call['repeat']==1 and call['bindings']=={q:q for q in ['ctrl','w0','w1','w2','w3']} and template['metadata'].get('multiplier')==pow(2,1<<j,15),'QPE_CONTROLLED_POWER','Round uses the wrong controlled multiplier/power/binding',f'round{j}')
            angles[j]=[]
            for k in range(j+1,8):
                expected=Fraction(-1,1<<(k-j)); name='SDG' if k-j==1 else 'TDG' if k-j==2 else 'P'
                op=take('gate',name,['ctrl'],f'round{j}/feedback_from_{k}')
                angle=_angle(op['params']); angles[j].append((k,angle))
                audit.require(angle==expected and abs(op['params']['angle_rad']-float(angle)*pi)<1e-14 and op['params']['phase_convention']=='diag(1,exp(i*theta))','FEEDBACK_ANGLE','Feedback angle/sign/phase convention changed',op['id'])
                audit.require(op['condition']=={'bit':f'phase[{k}]','equals':1} and op['reads']==[f'phase[{k}]'] and producer_ids[f'phase[{k}]'] in op['after'],'FEEDBACK_CAUSALITY','Feedback must reference its previously measured bit',op['id'])
            take('gate','H',['ctrl'],f'round{j}/readout_h')
            take('measure',None,['ctrl'],f'round{j}/measure',[f'phase[{j}]'])
        take('reset',None,['ctrl'],'release/control_reset')
        audit.require(cursor==len(original),'EXTRA_LOGICAL_OPERATIONS','Unexpected operation outside the reviewed algorithm')
        audit.require(program['bit_order']['measurement_order']==[f'phase[{j}]' for j in range(7,-1,-1)] and program['bit_order']['postprocess']=='phase[0..7]_msb_first','PHASE_BIT_ORDER','Declared bit order disagrees with schedule')
        for y in range(256):
            bits=[(y>>(7-k))&1 for k in range(8)]
            for j in range(8):
                remainder=(Fraction(y,256)*(1<<j)+sum((bits[k]*angle/2 for k,angle in angles[j]),Fraction(0)))%1
                audit.require(remainder==Fraction(bits[j],2),'QPE_PHASE_IDENTITY',f'Phase-tail cancellation failed for phase={y}/256, round={j}')
        audit.metrics.update(exact_phase_words_checked=256,phase_round_identities=2048,feedback_instances=28)
    audit.check('qpe_structure_and_rational_feedback',qpe)

    def postprocess():
        if postprocess_results is None:
            audit.unverified.append({'code':'POSTPROCESS_INPUTS_MISSING','message':'Supply actual postprocess outputs for all N15 a2 phase words'})
            return
        seen=set()
        for r in postprocess_results:
            N,a=r['N'],r['a']; bits=r['input_bits_msb_first']
            audit.require(len(bits)==8 and all(type(b) is int and b in (0,1) for b in bits),'POSTPROCESS_INPUT_BITS','Expected exactly eight integer bits')
            y=sum(v<<(7-i) for i,v in enumerate(bits))
            expected=_post_expected(y,N,a)
            audit.require((r['status'],r['period'],r['factors'])==expected,'POSTPROCESS_SEMANTICS',f'Incorrect CF/period/factors for N={N},a={a},y={y}')
            audit.require(r['phase_numerator']==y and r['phase_denominator']==256 and r['origin'] in ('fake','externally_supplied_unverified') and r['quantum_state_simulated'] is False and r['hardware_executed'] is False,'POSTPROCESS_PROVENANCE','Bit order or evidence claim changed')
            if N==15 and a==2: seen.add(y)
        if seen!=set(range(256)): audit.unverified.append({'code':'POSTPROCESS_COVERAGE','message':'N15 a2 coverage is incomplete'})
        audit.metrics['postprocess_cases']=len(postprocess_results)
    audit.check('classical_postprocessing',postprocess)
    from .semantic_rotation import check_synthesis
    audit.check('independent_synthesis_certificates',lambda:check_synthesis(audit,program))
    return audit.report()
