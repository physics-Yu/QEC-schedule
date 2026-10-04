"""Bounded, read-only views of immutable encoded-native reference artifacts.

These are native gate-index / reference projection views, not physical motion
or Executor timelines. The HTTP host belongs to the application; this module
only verifies source bytes and supplies bounded JSON responses.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
import hashlib
import json
from pathlib import Path
import re


SCHEMA = 'encoded-native-view/1'
MAX_PAGE = 100
MAX_GATES = 12
MAX_PROJECTIONS = 64
MAX_LINE_BYTES = 8 * 1024 * 1024
REQUIRED = ('summary.json', 'functions.jsonl', 'native_gates.jsonl',
            'native_projections.jsonl', 'roles.json', 'certificates.json', 'frames.jsonl')


def _digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _integer(value, name, *, maximum=None):
    if type(value) is not int or value < 0 or maximum is not None and value > maximum:
        raise ValueError(f'{name} must be a nonnegative integer' +
                         (f' at most {maximum}' if maximum is not None else ''))
    return value


def _json_line(stream):
    line = stream.readline(MAX_LINE_BYTES + 1)
    if len(line) > MAX_LINE_BYTES:
        raise ValueError('Artifact JSONL line exceeds the bounded reader limit')
    if not line:
        return None, line
    try:
        value = json.loads(line)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError('Artifact JSONL record is not valid JSON') from exc
    if not isinstance(value, dict):
        raise ValueError('Artifact JSONL records must be objects')
    return value, line


class EncodedNativeView:
    """Verify the run once, then expose pages while guarding every source file.

    Artifact hashes bind all global sources. Per-function span hashes, byte
    offsets, record indices and IDs independently bind each displayed function.
    No response loads the complete native gate/projection stream into memory.
    """

    def __init__(self, run_directory):
        self.directory = Path(run_directory).resolve(strict=True)
        self.manifest_path = self.directory / 'manifest.json'
        self.manifest_sha256 = _digest(self.manifest_path)
        self.manifest = json.loads(self.manifest_path.read_text(encoding='utf-8'))
        if self.manifest.get('complete') is not True:
            raise ValueError('Only complete immutable native runs can be displayed')
        if self.manifest.get('physical_executed') is not False:
            raise ValueError('This viewer requires an explicitly nonphysical reference run')
        artifacts = self.manifest.get('artifacts')
        if not isinstance(artifacts, dict) or any(name not in artifacts for name in REQUIRED):
            raise ValueError('Manifest must bind all native visualization source artifacts')
        self._paths, self._stats = {}, {}
        for name, descriptor in artifacts.items():
            if (not isinstance(name, str) or Path(name).name != name or
                    '/' in name or '\\' in name or name in ('.', '..')):
                raise ValueError('Artifact names must be single filenames')
            if not isinstance(descriptor, dict):
                raise ValueError('Artifact descriptor must contain sha256 and bytes')
            path = (self.directory / name).resolve(strict=True)
            if path.parent != self.directory or not path.is_file():
                raise ValueError('Artifact escapes its immutable run directory')
            expected_bytes = _integer(descriptor.get('bytes'), 'artifact bytes')
            expected_hash = descriptor.get('sha256')
            if (not isinstance(expected_hash, str) or len(expected_hash) != 64 or
                    path.stat().st_size != expected_bytes or _digest(path) != expected_hash):
                raise ValueError('Artifact bytes/hash differ from manifest: ' + name)
            self._paths[name], self._stats[name] = path, self._stat(path)
        self._manifest_stat = self._stat(self.manifest_path)
        self.summary = self._load('summary.json')
        self.roles = self._load('roles.json')
        self.certificates = self._load('certificates.json')
        self.frames = {}
        with self._paths['frames.jsonl'].open('rb') as stream:
            while (record := _json_line(stream)[0]) is not None:
                key = record.get('sha256')
                if not isinstance(key, str) or key in self.frames:
                    raise ValueError('Frame snapshots require unique SHA identities')
                self.frames[key] = record
        self.functions = []
        self._by_id = {}
        with self._paths['functions.jsonl'].open('rb') as stream:
            while (record := _json_line(stream)[0]) is not None:
                fid = record.get('function_id')
                if not isinstance(fid, str) or not fid or fid in self._by_id:
                    raise ValueError('Function IDs must be nonempty and unique')
                if record.get('index') != len(self.functions):
                    raise ValueError('Function index must match immutable JSONL ordering')
                for prefix in ('gate', 'projection'):
                    for suffix in ('start', 'count', 'byte_start', 'byte_end'):
                        _integer(record.get(prefix + '_' + suffix), prefix + '_' + suffix)
                    if record[prefix + '_byte_end'] < record[prefix + '_byte_start']:
                        raise ValueError('Function span ends before it begins')
                if record.get('gate_end') != record['gate_start'] + record['gate_count']:
                    raise ValueError('Function gate_end is not the exclusive end index')
                self.functions.append(record)
                self._by_id[fid] = record
        self._verified_spans = OrderedDict()
        self._guard()

    @staticmethod
    def _stat(path):
        value = path.stat()
        return (value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_ino)

    def _guard(self):
        if self._stat(self.manifest_path) != self._manifest_stat:
            raise ValueError('Immutable run manifest changed after verification')
        for name, path in self._paths.items():
            if self._stat(path) != self._stats[name]:
                raise ValueError('Immutable source changed after verification: ' + name)

    def _load(self, name):
        return json.loads(self._paths[name].read_text(encoding='utf-8'))

    def overview(self):
        self._guard()
        kinds = Counter(row.get('kind', 'unknown') for row in self.functions)
        shots = sorted({row['shot_index'] for row in self.functions if row.get('shot_index') is not None})
        return {'schema': SCHEMA, 'manifest_sha256': self.manifest_sha256,
                'summary': self.summary, 'roles': self.roles,
                'function_count': len(self.functions), 'function_kinds': dict(kinds), 'shots': shots,
                'scope': self.manifest.get('scope'), 'physical_executed': False,
                'axis': 'native_gate_index', 'native_time_us': None,
                'source_binding': 'All artifact SHA256/bytes verified; selected spans verified separately'}

    def list_functions(self, *, shot=None, injection=None, kind=None, start=0, count=50):
        self._guard()
        _integer(start, 'start')
        _integer(count, 'count', maximum=MAX_PAGE)
        if shot is not None:
            _integer(shot, 'shot')
        if injection is not None:
            _integer(injection, 'injection')
        rows = (r for r in self.functions if (shot is None or r.get('shot_index') == shot)
                and (injection is None or r.get('injection_index') == injection)
                and (kind is None or r.get('kind') == kind))
        selected, total = [], 0
        for row in rows:
            if start <= total < start + count:
                selected.append({k: row.get(k) for k in ('index', 'function_id', 'kind', 'shot_index',
                    'injection_index', 'namespace', 'epoch', 'gate_start', 'gate_count',
                    'projection_count', 'logical_result', 'conditional_probability')})
            total += 1
        return {'schema': SCHEMA, 'manifest_sha256': self.manifest_sha256,
                'start': start, 'count': len(selected), 'total': total, 'functions': selected}

    @staticmethod
    def _gate_stage(gate, kind):
        """Label groups of actual ID prefixes; never add a quantum operation."""
        gid = gate['id']
        if kind == 'data_encode' and re.search(r'\.reset\d+$', gid):
            return 'data_reset'
        if kind == 'resource_readout_reset':
            return {'H': 'resource_x_basis', 'MEASURE': 'resource_x_readout',
                    'RESET': 'resource_release'}.get(gate['gate_type'], kind)
        for marker, label in (('.prepare.', 'cat_prepare'), ('.verify.r1.', 'cat_verify_1'),
                              ('.verify.r2.', 'cat_verify_2'), ('.readout.', 'cat_readout'),
                              ('.logical_input.', 'raw_magic_input'), ('.encode.', 'css_encoder'),
                              ('.check.', 'producer_syndrome')):
            if marker in gid:
                return label
        if re.search(r'\.couple\d+\.', gid):
            return 'xyz_coupling'
        if kind == 'resource_prepare' and re.search(r'\.reset\d+$', gid):
            return 'resource_reset_17'
        return kind

    def _span_page(self, function, prefix, offset, count, wanted_ids=()):
        name = 'native_gates.jsonl' if prefix == 'gate' else 'native_projections.jsonl'
        begin, end = function[prefix + '_byte_start'], function[prefix + '_byte_end']
        expected_count = function[prefix + '_count']
        expected_start = function[prefix + '_start']
        expected_hash = function['native_sha256' if prefix == 'gate' else 'projection_sha256']
        if end > self._stats[name][0]:
            raise ValueError('Function span escapes its bound source file')
        key = (function['function_id'], prefix)
        verify = key not in self._verified_spans
        digest, selected, related, stages, projection_gates, seen = hashlib.sha256(), [], [], [], [], 0
        participating_qubits = set()
        expected_projections = self._verified_spans.get((function['function_id'], 'gate'), {}).get('projection_gates', [])
        wanted_ids = set(wanted_ids)
        with self._paths[name].open('rb') as stream:
            stream.seek(begin)
            while stream.tell() < end:
                record, raw = _json_line(stream)
                if record is None or stream.tell() > end:
                    raise ValueError('Function byte span does not align to complete JSONL records')
                if verify:
                    digest.update(raw)
                    if record.get('index') != expected_start + seen or record.get('function_id') != function['function_id']:
                        raise ValueError('Function span record index/identity mismatch')
                    if prefix == 'projection' and (seen >= len(expected_projections) or
                            (record.get('native_gate_id'), record.get('kind')) != tuple(expected_projections[seen])):
                        raise ValueError('Projection record does not bind its emitted M/RESET gate')
                if offset <= seen < offset + count:
                    selected.append(record)
                if prefix == 'gate' and verify:
                    participating_qubits.update(record.get('qubit_ids', ()))
                    if record['gate_type'] in ('MEASURE', 'RESET'):
                        projection_gates.append((record['id'], record['gate_type']))
                    label = self._gate_stage(record, function.get('kind'))
                    if stages and stages[-1]['kind'] == label:
                        stages[-1]['gate_count'] += 1
                        stages[-1]['last_native_id'] = record['id']
                    else:
                        stages.append({'kind': label, 'gate_start': record['index'], 'gate_offset': seen,
                                       'gate_count': 1, 'first_native_id': record['id'], 'last_native_id': record['id']})
                if prefix == 'projection' and record.get('native_gate_id') in wanted_ids:
                    related.append(record)
                seen += 1
                if not verify and seen >= offset + count and len(related) == len(wanted_ids):
                    break
            if verify:
                if (seen != expected_count or digest.hexdigest() != expected_hash or
                        prefix == 'projection' and seen != len(expected_projections)):
                    raise ValueError('Function record count/hash differs from its immutable binding')
                self._verified_spans[key] = {'stages': stages, 'projection_gates': projection_gates,
                                             'participating_qubits': sorted(participating_qubits)}
                if len(self._verified_spans) > 128:
                    self._verified_spans.popitem(last=False)

        self._verified_spans.move_to_end(key)
        return {'start': offset, 'total': expected_count, 'records': selected, 'related_records': related,
                'native_stages': self._verified_spans[key]['stages'],
                'participating_qubits': self._verified_spans[key]['participating_qubits'],
                'source_file': name, 'source_sha256': self.manifest['artifacts'][name]['sha256'],
                'span_sha256': expected_hash, 'span_verified': True}

    def function_detail(self, function_id, *, gate_page=0, projection_page=0):
        self._guard()
        _integer(gate_page, 'gate_page')
        _integer(projection_page, 'projection_page')
        if function_id not in self._by_id:
            raise KeyError('Unknown bound function identity')
        function = self._by_id[function_id]
        gates = self._span_page(function, 'gate', gate_page * MAX_GATES, MAX_GATES)
        wanted_ids = [g['id'] for g in gates['records'] if g['gate_type'] in ('MEASURE', 'RESET')]
        projections = self._span_page(function, 'projection', projection_page * MAX_PROJECTIONS, MAX_PROJECTIONS,
                                      wanted_ids=wanted_ids)
        certs = self.certificates.get('certificates', {})
        certificate_ids = function.get('certificate_ids', [])
        if any(cid not in certs for cid in certificate_ids):
            raise ValueError('Function references a missing bound kernel certificate')
        before_key, after_key = function.get('frame_before_sha256'), function.get('frame_after_sha256')
        for key in (before_key, after_key):
            if key is not None and key not in self.frames:
                raise ValueError('Function references a missing bound frame snapshot')
        self._guard()
        next_axis = None
        if function.get('kind') == 'frame_update':
            for row in self.functions[function['index'] + 1:]:
                if row.get('shot_index') != function.get('shot_index'):
                    break
                if row.get('kind') == 'cat_joint':
                    next_axis = {'function_id': row['function_id'], 'logical_pauli': row.get('logical_pauli'),
                                 'source': 'saved_next_cat_joint_function'}
                    break
        return {'schema': SCHEMA, 'manifest_sha256': self.manifest_sha256, 'function': function,
                'gates': gates, 'projections': projections,
                'certificates': {cid: certs[cid] for cid in certificate_ids},
                'frame_before': self.frames.get(before_key), 'frame_after': self.frames.get(after_key),
                'next_saved_axis': next_axis,
                'physical_executed': False, 'axis': 'native_gate_index'}


def render_viewer(destination, *, api_base='/api/encoded-native'):
    """Generate a viewer from the maintained template; artifacts are never edited."""
    if not isinstance(api_base, str) or not api_base.startswith('/') or api_base.startswith('//'):
        raise ValueError('Viewer API base must be a local absolute URL path')
    template = Path(__file__).with_name('encoded_native_viewer.html')
    payload = json.dumps({'api_base': api_base, 'schema': SCHEMA}, ensure_ascii=False).replace('<', '\\u003c')
    html = template.read_text(encoding='utf-8').replace('__ENCODED_NATIVE_CONFIG__', payload)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding='utf-8')
    return destination
