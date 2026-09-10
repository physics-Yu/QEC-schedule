import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum


def primitive(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {f.name: primitive(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): primitive(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (set, frozenset)):
        return sorted((primitive(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(value, (tuple, list)):
        return [primitive(v) for v in value]
    return value


def canonical_json(value):
    return json.dumps(primitive(value), sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
