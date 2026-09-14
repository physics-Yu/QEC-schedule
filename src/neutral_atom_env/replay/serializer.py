import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from functools import lru_cache


@lru_cache(maxsize=8192)
def _string_sort_key(value):
    # Immutable strings only: no caller-owned JSON lists/dicts are cached.
    # Keep the historical JSON ordering, including escapes and Unicode.
    return json.dumps(value,sort_keys=True)


def _set_sort_key(value):
    return _string_sort_key(value) if type(value) is str else json.dumps(value,sort_keys=True)


def primitive(value):
    # Serialized DAGs contain many repeated gate-ID strings. Exact types keep
    # str/IntEnum subclasses on the normal enum conversion path below.
    if value is None or type(value) in (str,int,float,bool):
        return value
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        # Opt-in only: preserve the historical serialization of every existing
        # field while absent readout_flip=False keeps schema19 bytes unchanged.
        return {f.name: primitive(getattr(value, f.name)) for f in fields(value)
                if not (f.metadata.get('omit_if_false') and getattr(value, f.name) is False)}
    if isinstance(value, Mapping):
        return {str(k): primitive(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (set, frozenset)):
        return sorted((primitive(v) for v in value), key=_set_sort_key)
    if isinstance(value, (tuple, list)):
        return [primitive(v) for v in value]
    return value


def canonical_json(value):
    return json.dumps(primitive(value), sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
