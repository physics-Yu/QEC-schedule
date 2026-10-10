"""Byte-bound hierarchical artifact envelope; never grants domain qualification."""
from __future__ import annotations

import hashlib
import gzip
import json
from pathlib import Path
import re

VERSION = 'r7-hierarchical-bundle/0.1'
ROLES = frozenset({'device','initial_state','logical_dag','patch_placement','logical_schedule','physical_dag','physical_dags','physical_dag_bundle','resource_requirements','resource_pool','atom','scenario','trace','validation','placement_evidence','enola_evidence','source_program','factory_ledger','postprocess','chunk_manifest'})
CORE = frozenset({'device','initial_state','logical_dag','patch_placement','logical_schedule','atom','scenario','trace','source_program'})
R6_NAMES = {'atom':'atom_program','trace':'event_trace','placement_evidence':'enola_evidence'}


def _object(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise ValueError('BUNDLE_DUPLICATE_JSON_KEY: '+key)
        result[key] = value
    return result


def _constant(value):
    raise ValueError('BUNDLE_NONFINITE_JSON: '+value)


def decode(raw):
    return json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)


def load_bundle(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    manifest = decode(raw)
    if not isinstance(manifest,dict) or manifest.get('schema_version') != VERSION:
        raise ValueError('BUNDLE_SCHEMA_UNSUPPORTED')
    if manifest.get('entry_mode') != 'preinitialized':
        raise ValueError('BUNDLE_PREINITIALIZED_ENTRY_REQUIRED')
    if not isinstance(manifest.get('bundle_id'),str) or not manifest['bundle_id'] or type(manifest.get('fixture')) is not bool:
        raise ValueError('BUNDLE_IDENTITY_REQUIRED')
    if manifest.get('kb_revision') != 'kb-0006':
        raise ValueError('BUNDLE_KB_REVISION_UNSUPPORTED')
    if not isinstance(manifest.get('files'),list) or not manifest['files']:
        raise ValueError('BUNDLE_FILES_REQUIRED')
    values, receipts = {}, {}
    for item in manifest['files']:
        role = item.get('role')
        if role not in ROLES:
            raise ValueError('BUNDLE_ROLE_UNSUPPORTED: '+str(role))
        if role in values:
            raise ValueError('BUNDLE_DUPLICATE_ROLE: '+role)
        rel = Path(item.get('path',''))
        target = (path.parent/rel).resolve()
        if rel.is_absolute() or not str(item.get('path','')) or not target.is_relative_to(path.parent):
            raise ValueError('BUNDLE_PATH_ESCAPE: '+str(rel))
        expected = item.get('byte_sha256','')
        if not re.fullmatch('[0-9a-f]{64}',expected):
            raise ValueError('BUNDLE_SHA256_REQUIRED: '+role)
        data = target.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise ValueError('BUNDLE_BYTE_HASH_MISMATCH: '+role)
        value = decode(gzip.decompress(data) if target.suffix=='.gz' else data)
        if not isinstance(value,(dict,list)):
            raise ValueError('BUNDLE_STRUCTURED_JSON_REQUIRED: '+role)
        if isinstance(value,dict) and (value.get('fixture') is True or value.get('provenance',{}).get('fixture') is True) and not manifest['fixture']:
            raise ValueError('BUNDLE_FIXTURE_MISMATCH: '+role)
        values[role] = value
        receipts[role] = {'path':str(rel),'bytes':len(data),'byte_sha256':actual,'schema_version':value.get('schema_version') if isinstance(value,dict) else None}
    if 'physical_dag' in values and 'physical_dags' in values:
        raise ValueError('BUNDLE_AMBIGUOUS_PHYSICAL_DAG_INPUT')
    if 'placement_evidence' in values and 'enola_evidence' in values:
        raise ValueError('BUNDLE_AMBIGUOUS_ENOLA_EVIDENCE')
    device = values.get('device',{})
    if isinstance(device,dict) and ('initialization' in device.get('zones',{}) or device.get('grouped_profile',{}).get('initialization_zone') is not None):
        raise ValueError('BUNDLE_LEGACY_INITIALIZATION_ZONE')
    atom = values.get('atom',{})
    if isinstance(atom,dict) and any(a.get('payload',{}).get('purpose') == 'patch_initialization_transport' for a in atom.get('actions',[])):
        raise ValueError('BUNDLE_LEGACY_STARTUP_TRANSPORT')
    missing = sorted(CORE-values.keys())
    if not {'physical_dag','physical_dags'} & values.keys():
        missing.append('physical_dag_or_physical_dags')
    receipt = {'schema_version':'r7-hierarchical-bundle-inspection/0.1','bundle_id':manifest['bundle_id'],'bundle_path':str(path),'bundle_byte_sha256':hashlib.sha256(raw).hexdigest(),'entry_mode':'preinitialized','kb_revision':manifest['kb_revision'],'fixture':manifest['fixture'],'files':receipts,'missing_core_roles':missing,'status':'byte_verified_partial' if missing else 'byte_verified_no_semantic_acceptance','domain_validation_performed':False,'full_program_passed':False,'user_visual_acceptance':'pending'}
    trace=values.get('trace',{})
    if isinstance(trace,dict) and trace.get('schema_version')=='event-session-trace/0.2':
        from .history import materialize_history
        chunks=values.get('chunk_manifest',{})
        if chunks.get('schema_version')!='r7-history-files/0.1' or not isinstance(chunks.get('files'),list):
            raise ValueError('BUNDLE_HISTORY_MANIFEST_REQUIRED')
        if len(chunks['files'])!=len(trace.get('history_chunks',[])):
            raise ValueError('BUNDLE_HISTORY_COVERAGE')
        chunk_paths=[]
        for item,record in zip(chunks['files'],trace['history_chunks'],strict=True):
            rel=Path(item.get('path',''));target=(path.parent/rel).resolve()
            if not item.get('path') or rel.is_absolute() or not target.is_relative_to(path.parent):
                raise ValueError('BUNDLE_HISTORY_PATH_ESCAPE')
            if item.get('byte_sha256')!=record['byte_sha256']:
                raise ValueError('BUNDLE_HISTORY_HASH_BINDING')
            chunk_paths.append(target)
        display,_,verified=materialize_history(trace,chunk_paths=chunk_paths)
        receipt['history']={'chunk_count':len(verified),'byte_and_chain_verified':True,'files':verified,
                            'merged_event_count':len(display['events']),'merged_result_count':len(display['results'])}
    return manifest,values,receipt


def r6_input(values):
    result = {R6_NAMES.get(k,k):v for k,v in values.items() if k != 'validation'}
    if 'physical_dag' in result:
        result['physical_dags'] = [result.pop('physical_dag')]
    return result
