"""Bind eight real published bits to R6's independent integer CF conclusion."""
from .checker import _hash
from .semantic_frontend import _post_expected


def inspect_postprocess_value(audit,action,bits,value):
    params=action['payload']['params'];reads=action['payload']['reads']
    if len(bits)!=8 or any(type(b) is not int or b not in (0,1) for b in bits) or reads!=params['bits_msb_first']:
        audit.fail('trace','POSTPROCESS_INPUT','Postprocessing must preserve exactly eight actual bits in original MSB-first order');return
    n,a=params['N'],params['a'];y=sum(b<<(7-i) for i,b in enumerate(bits))
    status,period,factors=_post_expected(y,n,a)
    expected={'schema_version':'PhasePostprocess/0.1.0','origin':'fake','input_bits_msb_first':bits,'N':n,'a':a,'phase_numerator':y,'phase_denominator':256,'status':status,'period':period,'factors':factors,'minimal_order_proven':False,'quantum_state_simulated':False,'hardware_executed':False,'loss_enabled':False}
    if not isinstance(value,dict) or any(value.get(k)!=v for k,v in expected.items()):
        audit.fail('trace','POSTPROCESS_VALUE','Postprocess conclusion differs from the independent exact-integer check; a failed phase cannot be hardcoded to 3 and 5');return
    if value['provenance']['input_sha256']!=_hash({'bits_msb_first':bits,'N':n,'a':a,'origin':'fake'}):audit.fail('trace','POSTPROCESS_INPUT_HASH','Postprocessor is detached from these actual published phase bits')
