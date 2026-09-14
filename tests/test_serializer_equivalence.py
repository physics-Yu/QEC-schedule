import json
from collections.abc import Mapping
from dataclasses import fields,is_dataclass,dataclass
from enum import Enum,IntEnum

from neutral_atom_env.replay.serializer import primitive,canonical_json


def original(value):
    if isinstance(value,Enum):return value.value
    if is_dataclass(value):return {f.name:original(getattr(value,f.name)) for f in fields(value)}
    if isinstance(value,Mapping):return {str(k):original(v) for k,v in sorted(value.items(),key=lambda kv:str(kv[0]))}
    if isinstance(value,(set,frozenset)):return sorted((original(v) for v in value),key=lambda v:json.dumps(v,sort_keys=True))
    if isinstance(value,(tuple,list)):return [original(v) for v in value]
    return value


def test_fast_primitive_preserves_escaped_set_order_and_enum_semantics():
    class S(str,Enum):VALUE='value'
    class I(IntEnum):VALUE=3
    @dataclass(frozen=True)
    class Example:
        ids:frozenset
        values:tuple
    value=Example(frozenset({'Q000','Q001','\n','"','\\','你好','\t','a'}),
                  (S.VALUE,I.VALUE,None,True,1,1.5,{'bits':(0,1)}))
    expected=json.dumps(original(value),sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    assert canonical_json(value)==expected
    first=primitive(value);first['values'][-1]['bits'].append(9)
    assert primitive(value)==original(value)  # No cached mutable serialization.
