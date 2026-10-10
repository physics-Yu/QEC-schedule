"""Independent fixed-point INTEGER intervals for 2x2 gate-word certificates.

This implementation does not import the producer's Decimal arithmetic, gate
table, certificate code, or acceptance function. All roundoff is bounded with
integer floor/ceiling, including the final norm. No state is represented.
"""
from fractions import Fraction
from hashlib import sha256
from math import factorial, isqrt
import json

from .checker import _hash

SCALE=10**140


def _ceil_div(n,d): return -((-n)//d)


class I:
    __slots__=('lo','hi')
    def __init__(self,lo,hi=None): self.lo,self.hi=lo,lo if hi is None else hi
    @classmethod
    def rational(cls,value):
        value=Fraction(value)
        return cls(value.numerator*SCALE//value.denominator,_ceil_div(value.numerator*SCALE,value.denominator))
    def __add__(self,b): return I(self.lo+b.lo,self.hi+b.hi)
    def __neg__(self): return I(-self.hi,-self.lo)
    def __sub__(self,b): return self+-b
    def __mul__(self,b):
        corners=[a*c for a in (self.lo,self.hi) for c in (b.lo,b.hi)]
        return I(min(corners)//SCALE,_ceil_div(max(corners),SCALE))
    def div(self,n):
        if n<=0: raise ValueError('positive integer denominator required')
        return I(self.lo//n,_ceil_div(self.hi,n))


ZERO,ONE=I(0),I(SCALE)


def _pi():
    def atan(q):
        partial=Fraction(0)
        for n in range(230): partial += Fraction((-1)**n,(2*n+1)*q**(2*n+1))
        next_term=Fraction(1,461*q**461)
        return partial,partial+next_term
    a,b=atan(5),atan(239)
    return I(I.rational(16*a[0]-4*b[1]).lo,I.rational(16*a[1]-4*b[0]).hi)


PI=_pi()
root=isqrt(SCALE*SCALE//2)
HALF_ROOT=I(root,root+1)


def _phase(angle):
    value=Fraction(angle['numerator'],angle['denominator'])%2
    if value>1: value-=2
    x=PI*I.rational(value); x2=-(x*x)
    c,s=ONE,x; ct,st=ONE,x
    for n in range(1,110):
        ct=(ct*x2).div((2*n-1)*(2*n)); st=(st*x2).div((2*n)*(2*n+1))
        c=c+ct; s=s+st
    # Taylor/Lagrange remainder for degree 219; |argument| < 4.
    remainder=_ceil_div(4**220*SCALE,factorial(220))
    pad=I(-remainder,remainder)
    return c+pad,s+pad


def _plus(a,b): return a[0]+b[0],a[1]+b[1]
def _times(a,b): return a[0]*b[0]-a[1]*b[1],a[0]*b[1]+a[1]*b[0]
def _matmul(a,b): return [[_plus(_times(a[r][0],b[0][c]),_times(a[r][1],b[1][c])) for c in range(2)] for r in range(2)]


def _bound(word,angle,phase):
    z,o=(ZERO,ZERO),(ONE,ZERO); h=(HALF_ROOT,ZERO)
    matrices={'H':[[h,h],[h,(-HALF_ROOT,ZERO)]],'X':[[z,o],[o,z]],'Z':[[o,z],[z,(-ONE,ZERO)]],
              'S':[[o,z],[z,(ZERO,ONE)]],'SDG':[[o,z],[z,(ZERO,-ONE)]],
              'T':[[o,z],[z,(HALF_ROOT,HALF_ROOT)]],'TDG':[[o,z],[z,(HALF_ROOT,-HALF_ROOT)]]}
    matrix=[[o,z],[z,o]]
    if not 1<=len(word)<=1000: raise ValueError('word length outside 1..1000 supported certificate profile')
    for name in word: matrix=_matmul(matrices[name],matrix)
    scalar=_phase(phase)
    matrix=[[_times(scalar,entry) for entry in row] for row in matrix]
    target=[[o,z],[z,_phase(angle)]]
    squared=0
    for r in range(2):
        for c in range(2):
            for component in (0,1):
                delta=matrix[r][c][component]-target[r][c][component]
                squared+=max(abs(delta.lo),abs(delta.hi))**2
    upper=isqrt(squared)+1
    return Fraction(upper,SCALE),matrix


def _decimal(value):
    n=value.numerator*SCALE//value.denominator
    return f'{n//SCALE}.{n%SCALE:0140d}'


def check_synthesis(audit,program):
    instances=[n for n in program['body'] if n.get('synthesis_certificate_ref')]
    if program['synthesis'].get('status')!='complete':
        audit.unverified.append({'code':'SYNTHESIS_UNRESOLVED','message':'Exact small-angle source lacks completed word certificates'})
        return
    audit.require(len(instances)==15,'SYNTHESIS_INSTANCE_COUNT','All fifteen small rotations must remain present')
    reviewed={}; phase_records=[]; claimed_total=Fraction(0); independent_total=Fraction(0)
    for node in instances:
        ref=node['synthesis_certificate_ref']; template=program['templates'][ref]
        metadata=template['metadata']; source=node['logical_source_op']; angle=source['params']['angle_pi']
        audit.require(metadata['angle_pi']==angle and metadata.get('coherent_quantum_control_supported') is False and node['condition_scope']=='classical','SYNTHESIS_PHASE_SCOPE','Phase-sensitive word is only qualified in a classical branch',node['id'])
        word=[]
        for index,item in enumerate(template['body']):
            op=item['op']; word.append(op['params']['name'])
            audit.require(op['kind']=='gate' and op['qubits']==['q'] and op['condition'] is None and not op['reads'] and not op['writes'] and op['after']==([] if not index else [template['body'][index-1]['op']['id']]),'SYNTHESIS_WORD_STRUCTURE','Certificate word must be sequential unconditional 1q gates',node['id'])
        certificate=program['synthesis_certificates'][ref]
        if ref not in reviewed:
            independent,matrix=_bound(word,angle,metadata['global_phase_pi'])
            recorded=Fraction(certificate['operator_error_upper_bound'])
            audit.require(independent<=recorded,'SYNTHESIS_BOUND_UNDERSTATED','Independent integer-interval upper bound exceeds the producer certificate',ref)
            audit.require(certificate['angle_pi']==angle and certificate['global_phase_pi']==metadata['global_phase_pi'] and certificate['phase_sensitive'] is True and certificate['phase_optimized'] is False,'SYNTHESIS_CERTIFICATE_BINDING','Certificate angle/global-phase semantics differ',ref)
            audit.require(certificate['gate_word_sha256']==sha256(json.dumps(word,separators=(',',':')).encode()).hexdigest() and certificate['gate_count']==len(word) and certificate['t_count']==word.count('T') and certificate['tdg_count']==word.count('TDG') and program['template_hashes'][ref]==_hash(template),'SYNTHESIS_WORD_DIGEST','Certificate does not bind the actual gate word',ref)
            for r in range(2):
                for c in range(2):
                    for k,key in enumerate(('real','imag')):
                        enclosure=certificate['corrected_matrix_intervals'][r][c][key]
                        ours=matrix[r][c][k]
                        audit.require(Fraction(enclosure[0])<=Fraction(ours.lo,SCALE)<=Fraction(ours.hi,SCALE)<=Fraction(enclosure[1]),'SYNTHESIS_MATRIX_ENCLOSURE','Producer matrix interval does not enclose independent interval',ref)
            reviewed[ref]={'independent_upper_bound':_decimal(independent),'producer_upper_bound':certificate['operator_error_upper_bound'],'gate_count':len(word),'t_like':word.count('T')+word.count('TDG')}
        budget=Fraction(str(source['params']['error_budget']))
        claimed=Fraction(certificate['operator_error_upper_bound'])
        audit.require(claimed<=budget,'SYNTHESIS_LOCAL_BUDGET','Certified instance bound exceeds allocated budget',node['id'])
        claimed_total+=claimed; independent_total+=Fraction(reviewed[ref]['independent_upper_bound'])
        phase_records.append({'source_operation_id':node['id'],'condition':node['condition'],'global_phase_pi':metadata['global_phase_pi'],'semantics':'exp(i*pi*phase)*chronological_word','scope':'classical_branch_global_not_quantum_control'})
    audit.require(program.get('branch_global_phases')==phase_records,'BRANCH_PHASE_LEDGER','Branch-global scalar phases missing or altered')
    budget=Fraction(str(program['synthesis']['path_error_budget']))
    recorded_path=Fraction(program['synthesis']['certified_path_error_upper_bound'])
    audit.require(independent_total<=recorded_path<=budget and claimed_total<=recorded_path,'SYNTHESIS_PATH_BUDGET','Path bound does not cover all instances or exceeds total budget')
    unconditional=0; conditional={}
    for node in program['body']:
        if node['kind']=='op': ops=[node['op']]; condition=node['op']['condition']
        else: ops=[n['op'] for n in program['templates'][node['template_id']]['body']]; condition=node.get('condition')
        count=sum(o['kind']=='gate' and o['params']['name'] in ('T','TDG') for o in ops)
        if condition: conditional[condition['bit']]=conditional.get(condition['bit'],0)+count
        else: unconditional+=count
    conditional={key:value for key,value in conditional.items() if value}
    summary=program['resource_summary']
    audit.require(summary['unconditional_t_like']==unconditional and summary['conditional_t_like_by_bit_equals_one']==conditional and summary['total_t_like']==unconditional+sum(conditional.values()),'T_DEMAND_COUNT','T demand summary differs from actual conditioned words')
    audit.metrics.update(synthesis_method='independent integer intervals, 140 decimal fixed-point places, explicit series remainder',synthesis_words=reviewed,independent_path_upper_bound=_decimal(independent_total),unconditional_t_like=unconditional,all_conditions_true_t_like=unconditional+sum(conditional.values()))
