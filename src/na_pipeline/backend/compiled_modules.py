"""Persistent immutable leaf plans and source-preserving recipe composition.

No quantum state, scenario, acceptance, session, token or epoch is cached.
Binding rechecks the complete world through the independent geometry checker.
Readout connectors use absolute ports; other leaves permit rigid translation.
"""
from copy import deepcopy
from pathlib import Path
import json
import math
import time
import ast
from hashlib import sha256

from .enola_kernel import StrategyError, digest
from .geometry import EPS, broadcast_pairs, in_zone
from .physical_dag import compile_physical_dag, finalize_physical_plan, _shift_window
from .strategy_template import remap, geometry_world
from .module_graph import module_graph


def emission_fingerprint(source):
    """Only code that constructs immutable leaf bodies, excluding the linker."""
    tree=ast.parse(source)
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('_translate','_identity')]
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='CompiledModuleLibrary')
    nodes += [n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='compile_module']
    return sha256(ast.dump(ast.Module(body=nodes,type_ignores=[]),include_attributes=False).encode()).hexdigest()


def native_compiler_sources():
    root=Path(__file__).resolve().parents[1]
    excluded={'compiled_modules.py','module_graph.py','logical_components.py'}
    sources={p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest()
             for part in ('backend','device') for p in sorted((root/part).glob('*.py')) if p.name not in excluded}
    sources['backend/compiled_modules.py::template_emission']=emission_fingerprint(Path(__file__).read_text(encoding='utf-8'))
    return sources


def _translate(value, offset):
    if isinstance(value, list):
        return [_translate(v, offset) for v in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for k, v in value.items():
        if k in ('position_um', 'from_um', 'to_um') and isinstance(v, list) and len(v) == 2:
            out[k] = [v[i] + offset[i] for i in (0, 1)]
        elif k == 'intersections_um':
            out[k] = [[p[i] + offset[i] for i in (0, 1)] for p in v]
        elif k in ('x_um', 'y_um') and isinstance(v, list):
            out[k] = [x + offset[0 if k == 'x_um' else 1] for x in v]
        else:
            out[k] = _translate(v, offset)
    return out


def _identity(dag, world, device, compiler_hash):
    clean, _ = geometry_world(world, device)
    sites = {a.get('site_id', a['qubit_id']): a for a in clean['atoms']}
    qs = list(dict.fromkeys(q for o in dag['nodes'] for q in o['qubits']))
    qmap = {q: f'port/q{i}' for i, q in enumerate(qs)}
    ids = {o['id']: f'op:{i}' for i, o in enumerate(dag['nodes'])}
    writes = list(dict.fromkeys(r for o in dag['nodes'] for r in o['writes']))
    reads = list(dict.fromkeys(r for o in dag['nodes'] for r in o['reads'] if r not in writes))
    ids.update({r: f'result:{i}' for i, r in enumerate(writes)})
    ids.update({r: f'input:{i}' for i, r in enumerate(reads)})
    ids.update(qmap)
    ids.update({g['group_id']: f'group:{i}' for i, g in enumerate(dag['groups'])})
    absolute = any(o['kind'] == 'measure' for o in dag['nodes'])
    origin = [0., 0.] if absolute or not qs else list(sites[qs[0]]['position_um'])
    geometry = []
    for q in qs:
        if q not in sites:
            raise StrategyError('MODULE_SITE_MISSING', 'Code-site port is absent', qubit=q)
        a = sites[q]
        geometry.append({'site': qmap[q], 'position_um': [a['position_um'][i] - origin[i] for i in (0, 1)],
                         'aod_group': a['aod_group'], 'role': next(t['role'] for t in dag['qubits'] if t['id'] == q)})
    nodes = remap([{k: deepcopy(o[k]) for k in ('id', 'kind', 'qubits', 'params', 'after', 'reads', 'writes', 'condition')} for o in dag['nodes']], ids)
    # Group member source hints can point outside the fragment. Only its actual
    # measured/reset bindings are part of this atomic connector contract.
    groups = remap([{'members': [{k: m[k] for k in ('physical_qubit_id', 'local_id', 'measurement_op_id', 'post_readout_reset_op_id', 'result_id')} for m in g['members']]} for g in dag['groups']], ids)
    core = {'schema_version': 'CompiledModule/0.1', 'device': digest(device), 'compiler': compiler_hash,
            'operations': nodes, 'groups': groups, 'entry_ports': geometry,
            'coordinate_support': 'absolute_global_mz_connector' if absolute else 'rigid_translation_no_zone_rotation'}
    return digest(core), core, ids, origin, sites, qs


def retain_compatible_aod(plan):
    """Fuse an exact return/drop -> local-1Q -> recapture boundary.

    No routing search, new path, changed pulse, or suspended commit is allowed.
    Both complete recipes still enter/exit with empty AOD. Leaf references keep
    their original immutable bodies; removed transfers are explicit link edits.
    """
    actions=plan['atom_program']['actions'];removed={};cuts=[];holds=[]
    for i,drop in enumerate(actions):
        if drop['kind']!='drop' or drop['payload'].get('purpose')!='enola_cz_return':continue
        between=[];pickup=None
        for later in actions[i+1:]:
            if later['kind']=='gate' and later['payload'].get('name')!='CZ':between.append(later);continue
            if later['kind']=='pickup' and later['payload'].get('purpose')=='enola_cz_transport':pickup=later
            break
        if pickup is None or set(drop['atoms'])!=set(pickup['atoms']):continue
        ds={b['atom_id']:b for b in drop['payload']['bindings']};ps={b['atom_id']:b for b in pickup['payload']['bindings']}
        if any(ds[a]['from_trap_id']!=ps[a]['to_trap_id'] or ds[a]['to_trap_id']!=ps[a]['from_trap_id']
               or any(ds[a][k]!=ps[a][k] for k in ('position_um','row_id','column_id')) for a in ds):continue
        spans=[(a['t_start_us'],a['t_end_us']) for a in (drop,pickup)]
        # Compression must not truncate another simultaneous action or latency.
        if any(a['id'] not in (drop['id'],pickup['id']) and any(max(a['t_start_us'],s)<min(a['t_end_us'],e)-EPS for s,e in spans) for a in actions):continue
        if any(a['kind']=='measure' and any(max(a['t_end_us'],s)<min(a['payload']['result_ready_us'],e)-EPS for s,e in spans) for a in actions):continue
        removed[drop['id']]=drop;removed[pickup['id']]=pickup;cuts+=spans
        holds.append({'drop_action_id':drop['id'],'pickup_action_id':pickup['id'],'atoms':list(drop['atoms']),
                      'start_us':drop['t_start_us'],'end_us':pickup['t_end_us'],
                      'aod_group':pickup['payload']['aod_group'],'bindings':deepcopy(pickup['payload']['bindings']),
                      'intervening_action_ids':[a['id'] for a in between],
                      'same_positions_axes_and_carriers':True})
    receipt={'schema_version':'CompositeAODResidency/0.1','policy':'exact_same_array_at_home_between_CZ_batches',
             'merged_boundaries':holds,'removed_actions':list(removed.values()),
             'external_commit_boundary':'empty_AOD','routing_search_calls':0,
             'scope':'within one composite only; measurement transfers and nonmatching arrays retained'}
    if not removed:
        plan['aod_residency']=receipt;return plan
    cuts.sort()
    def clock(t):return t-sum(max(0.,min(t,e)-s) for s,e in cuts if t>s)
    def timing(value):
        if isinstance(value,list):return [timing(v) for v in value]
        if not isinstance(value,dict):return deepcopy(value)
        out={}
        for k,v in value.items():
            if k in {'start_us','end_us','t_start_us','t_end_us','time_us','result_ready_us','earliest_ready_us','measurement_start_us','measurement_end_us','readout_start_us','readout_end_us','required_end_us'} and type(v) in (int,float):out[k]=clock(v)
            elif k=='earliest_readout_us':out[k]={a:clock(t) for a,t in v.items()}
            else:out[k]=timing(v)
        return out
    def predecessors(ids):
        answer=[]
        for aid in ids:
            answer.extend(predecessors(removed[aid]['depends_on']) if aid in removed else [aid])
        return list(dict.fromkeys(answer))
    atom=plan['atom_program'];atom['actions']=[timing(a) for a in actions if a['id'] not in removed]
    for a in atom['actions']:a['depends_on']=predecessors(a['depends_on'])
    atom['source_map']={s:[a for a in ids if a not in removed] for s,ids in atom['source_map'].items()}
    atom['groups']=timing(atom['groups'])
    total=sum(e-s for s,e in cuts)
    for k in ('duration_us','t_end_us'):atom['stats'][k]-=total
    atom['stats']['action_count']=len(atom['actions'])
    plan['result_ready_offsets_us']={r:clock(t) for r,t in plan['result_ready_offsets_us'].items()}
    plan['measurement_placements']=timing(plan['measurement_placements']);plan['ready_decisions']=timing(plan['ready_decisions'])
    plan['resource_intervals']=[{'resource_id':r,'start_us':a['t_start_us'],'end_us':a['t_end_us'],'units':1,'action_id':a['id']} for a in atom['actions'] for r in a['resources']]
    for m in plan['module_composition']['instances']:
        m['start_us']=clock(m['start_us']);m['end_us']=clock(m['end_us'])
        m['schedule_constraints']=timing(m['schedule_constraints'])
        for constraint in m['schedule_constraints']:
            if 'terminal_action_ids' in constraint:
                constraint['terminal_action_ids']=predecessors(constraint['terminal_action_ids'])
    receipt.update(merged_boundaries=timing(holds),saved_transfer_us=total,
                   removed_action_ids=list(removed),original_program_actions_sha256=digest(actions))
    plan['aod_residency']=receipt
    return plan


class CompiledModuleLibrary:
    def __init__(self, device, *, directory=None, budget=None, enola_root=None):
        self.device = deepcopy(device); self.budget = deepcopy(budget); self.enola_root = enola_root
        self.directory = Path(directory) if directory is not None else None
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True)
        # Recipe-builder edits invalidate their changed operation signatures,
        # not every unrelated native leaf. Shared native compiler/device rule
        # edits still invalidate all products affected by that common backend.
        self.compiler_sources = native_compiler_sources()
        self.compiler_hash = digest(self.compiler_sources)
        self.cache = {}
        self.frontiers = {}
        self.counters = {k: 0 for k in ('leaf_compile_count', 'cache_hit_count', 'bind_count', 'bind_rejection_count',
                                        'connector_compile_count', 'connector_miss_count', 'variant_miss_count',
                                        'placement_search_count', 'routing_search_count', 'composition_count', 'import_count', 'frontier_search_count')}
        self.timings = {k: 0. for k in ('compile_seconds', 'bind_seconds', 'composition_seconds')}

    @property
    def stats(self):
        return {**self.counters, **self.timings}

    def _read(self, key):
        if key not in self.cache:
            self.cache[key] = []
            if self.directory:
                for p in sorted(self.directory.glob(key + '-*.json')):
                    item = json.loads(p.read_bytes())
                    if digest(item['body']) != item['hash']:
                        raise StrategyError('MODULE_HASH_MISMATCH', 'Persisted module body changed', path=str(p))
                    self.cache[key].append(item); self.counters['import_count'] += 1
        return self.cache[key]

    def compile_module(self, dag, world):
        """Build one missing leaf variant, never a composite or a runtime state."""
        key, core, ids, origin, sites, qs = _identity(dag, world, self.device, self.compiler_hash)
        started = time.perf_counter()
        plan = compile_physical_dag(dag, self.device, world, budget=self.budget, enola_root=self.enola_root, defer_runtime_inputs=True)
        self.timings['compile_seconds'] += time.perf_counter() - started
        stats = plan['atom_program']['stats']
        self.counters['leaf_compile_count'] += 1
        self.counters['placement_search_count'] += stats['placement_candidate_count']
        self.counters['routing_search_count'] += stats['routing_search_count']
        if core['coordinate_support'].startswith('absolute'):
            self.counters['connector_compile_count'] += 1
        # A captured spectator is an explicit geometry witness, not silently
        # discarded to obtain a cache hit. Broadcast-only spectators are checked
        # against the new full world on every binding.
        moving = list(dict.fromkeys(a for action in plan['atom_program']['actions']
                                   if not (action['kind'] == 'gate' and action['payload']['name'] == 'CZ') for a in action['atoms']))
        aids = list(dict.fromkeys([sites[q]['atom_id'] for q in qs] + moving))
        atoms = {a['atom_id']: a for a in plan['atom_program']['initial_state']['atoms']}
        amap = {a: f'carrier:{i}' for i, a in enumerate(aids)}
        witnesses = []
        main = {sites[q]['atom_id']: ids[q] for q in qs}
        for aid in aids:
            a = atoms[aid]
            witnesses.append({'atom': amap[aid], 'site_port': main.get(aid), 'aod_group': a['aod_group'],
                              'relative_position': [a['position_um'][i] - origin[i] for i in (0, 1)]})
        actionmap = {a['id']: f'action:{i}' for i, a in enumerate(plan['atom_program']['actions'])}
        trapids = set()
        for a in plan['atom_program']['actions']:
            for b in a['payload'].get('bindings', []):
                trapids.update((b['from_trap_id'], b['to_trap_id']))
            for b in a['payload'].get('site_bindings', []):
                trapids.add(b['destination_trap_id'])
        trapids.update(atoms[a]['trap_id'] for a in aids)
        traps = [t for t in plan['atom_program']['initial_state']['slm_traps'] if t['trap_id'] in trapids]
        tmap = {t['trap_id']: f'site:{i}' for i, t in enumerate(traps)}
        # Resource strings are typed references too; recursive substitution must
        # not leave atom/trap identities embedded in resource names.
        mapping = {**ids, **amap, **tmap, **actionmap}
        mapping.update({'atom:' + a: 'atom:' + f for a, f in amap.items()})
        mapping.update({'trap:' + a: 'trap:' + f for a, f in tmap.items()})
        body_plan = deepcopy(plan)
        body_plan['atom_program']['initial_state'] = {'atoms': [atoms[a] for a in aids], 'slm_traps': traps, 'aod_rows': [], 'aod_columns': []}
        body_plan['exit_state']['atoms'] = [a for a in body_plan['exit_state']['atoms'] if a['atom_id'] in amap]
        body_plan['exit_state']['slm_traps'] = [t for t in body_plan['exit_state']['slm_traps'] if t['trap_id'] in tmap]
        for a in body_plan['atom_program']['actions']:
            if a['kind'] == 'gate' and a['payload']['name'] == 'CZ':
                a['atoms'] = [v for v in a['atoms'] if v in amap]
                a['resources'] = [r for r in a['resources'] if not r.startswith('atom:') or r in mapping]
        body_plan = _translate(remap(body_plan, mapping), [-x for x in origin])
        # Immutable compile bodies carry geometry only, not entry runtime fields.
        for state in (body_plan['atom_program']['initial_state'], body_plan['exit_state']):
            for a in state['atoms']:
                for k in list(a):
                    if k not in ('atom_id', 'position_um', 'carrier', 'trap_id', 'aod_group', 'row_id', 'column_id', 'site_id'):
                        a.pop(k)
        body_plan.pop('execution_context', None)
        body_plan.pop('enola', None)
        body_plan['atom_program']['stats'].pop('compile_wall_seconds', None)
        body = {'key': key, 'identity': core, 'witnesses': witnesses, 'template': body_plan,
                'compiler_sources': self.compiler_sources,
                'source_mapping': ids, 'origin': origin,
                'compilation_provenance': deepcopy(plan['enola']),
                'support': {'runtime_cached': False, 'full_scene_bind_check_required': True,
                            'translation': not core['coordinate_support'].startswith('absolute'), 'rotation': False}}
        hashed = digest(body)
        artifact = {'schema_version': 'CompiledModule/0.1', 'hash': hashed, 'body': body}
        self._read(key).append(deepcopy(artifact))
        if self.directory:
            path = self.directory / (key + '-' + hashed + '.json')
            import uuid
            temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
            temporary.write_text(json.dumps(artifact, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
            temporary.replace(path)
        return artifact

    def bind_module(self, module, dag, world, *, instance_id):
        started = time.perf_counter()
        if len({a.get('site_id',a['qubit_id']) for a in world['atoms']}) != len(world['atoms']):
            raise StrategyError('MODULE_SITE_ALIAS', 'Every code site in the complete world must have one carrier')
        if digest(module['body']) != module['hash']:
            raise StrategyError('MODULE_HASH_MISMATCH', 'Immutable leaf body changed')
        key, core, ids, origin, sites, qs = _identity(dag, world, self.device, self.compiler_hash)
        body = module['body']
        if key != body['key'] or core != body['identity']:
            raise StrategyError('MODULE_PORT_MISMATCH', 'Source/device/entry ports require a distinct variant')
        mapping = {v: k for k, v in ids.items()}
        current = {a['atom_id']: a for a in world['atoms']}
        for w in body['witnesses']:
            pos = [w['relative_position'][i] + origin[i] for i in (0, 1)]
            if w['site_port'] is not None:
                atom = sites[mapping[w['site_port']]]
            else:
                found = [a for a in current.values() if math.dist(a['position_um'], pos) <= EPS]
                if len(found) != 1:
                    raise StrategyError('MODULE_CAPTURE_WITNESS', 'Captured spectator footprint changed')
                atom = found[0]
            if atom['aod_group'] != w['aod_group'] or math.dist(atom['position_um'], pos) > EPS:
                raise StrategyError('MODULE_CAPTURE_WITNESS', 'Carrier witness geometry changed')
            mapping[w['atom']] = atom['atom_id']
            mapping['atom:' + w['atom']] = 'atom:' + atom['atom_id']
        template = _translate(deepcopy(body['template']), origin)
        traps = {t['trap_id']: deepcopy(t) for t in world['slm_traps']}
        for t in template['atom_program']['initial_state']['slm_traps']:
            matches = [v for v in traps.values() if math.dist(v['position_um'], t['position_um']) <= EPS and v['zone_id'] == t['zone_id']]
            if len(matches) > 1:
                raise StrategyError('MODULE_SITE_ALIAS', 'Multiple static traps at one port')
            if matches:
                actual = matches[0]
            else:
                actual = {**deepcopy(t), 'trap_id': 'slm:module:' + digest({'position': t['position_um'], 'zone': t['zone_id']})[:24], 'occupant': None}
                traps[actual['trap_id']] = actual
            expected = mapping.get(t['occupant'], t['occupant'])
            if actual['occupant'] != expected:
                raise StrategyError('MODULE_SITE_OCCUPIED', 'Required temporary/entry site occupancy changed')
            mapping[t['trap_id']] = actual['trap_id']; mapping['trap:' + t['trap_id']] = 'trap:' + actual['trap_id']
        for a in template['atom_program']['actions']:
            mapping[a['id']] = instance_id + '/' + a['id']
        result = remap(template, mapping); atom = result['atom_program']
        atom['initial_state'] = {'atoms': deepcopy(world['atoms']), 'slm_traps': deepcopy(list(traps.values())), 'aod_rows': [], 'aod_columns': []}
        atom['artifact_id'] = instance_id
        atom['complete'] = True
        atom['provenance'].update(backend_used='compiled_module_binding', module_hash=module['hash'], original_search_repeated=False)
        ops = {o['id']: o for o in dag['nodes']}
        zone = {'bounds_um': [self.device['zones'][self.device['broadcast']['zone_id']][k] for k in ('x_range_um', 'y_range_um')]}
        scene = deepcopy(current)
        for a in atom['actions']:
            p = a['payload']; source = [ops[i] for i in p['physical_op_ids']]
            a['source_ids'] = list(dict.fromkeys(s for o in source for s in (o['id'], *o['source_ids'])))
            p['source_op_records'] = {o['id']: {k: deepcopy(o[k]) for k in ('qubits', 'params', 'reads', 'writes', 'condition')} for o in source}
            if len(source) == 1:
                o = source[0]; p.update(physical_op_id=o['id'], params=deepcopy(o['params']), source_reads=o['reads'], source_writes=o['writes'], source_metadata=deepcopy(o.get('metadata', {})))
            if a['kind'] == 'move':
                for t in p['trajectories']:
                    scene[t['atom_id']]['position_um'] = list(t['to_um'])
            if a['kind'] == 'gate' and p['name'] == 'CZ':
                pairs = broadcast_pairs(list(scene.values()), zone, self.device['geometry']['gate_pair_distance_um'], self.device['geometry']['distance_tolerance_um'])
                if pairs != sorted(sorted(v) for v in p['pairs']):
                    raise StrategyError('MODULE_BROADCAST_CONFLICT', 'Full world changes the cached broadcast pairs')
                a['atoms'] = sorted(i for i, v in scene.items() if in_zone(v['position_um'], zone))
                a['resources'] = sorted({r for r in a['resources'] if not r.startswith('atom:')} | {'atom:' + i for i in a['atoms']})
        exit_atoms = deepcopy(current)
        for a in result['exit_state']['atoms']:
            exit_atoms[a['atom_id']].update({k: deepcopy(a[k]) for k in ('position_um', 'carrier', 'trap_id', 'row_id', 'column_id', 'site_id') if k in a})
        for t in traps.values(): t['occupant'] = None
        for a in exit_atoms.values(): traps[a['trap_id']]['occupant'] = a['atom_id']
        result['exit_state'] = {'atoms': list(exit_atoms.values()), 'slm_traps': list(traps.values()), 'aod_rows': [], 'aod_columns': []}
        result['source'] = {'operations': deepcopy(dag['nodes']), 'groups': deepcopy(dag['groups'])}
        result['physical_dags'] = [deepcopy(dag)]
        result['resource_intervals'] = [{'resource_id': r, 'start_us': a['t_start_us'], 'end_us': a['t_end_us'], 'units': 1, 'action_id': a['id']} for a in atom['actions'] for r in a['resources']]
        atom['stats'].update(atom_count=len(current), routing_search_count=0, placement_candidate_count=0, compile_wall_seconds=0.)
        atom['stats']['t_start_us'] = min(a['t_start_us'] for a in atom['actions'])
        atom['stats']['duration_us'] = atom['stats']['t_end_us'] - atom['stats']['t_start_us']
        # Independent replay checks carrier transitions, all Cartesian sweeps,
        # zones, dynamic axes, rebind arrival and global broadcast occupancy.
        from na_pipeline.validation.dag_physical import validate_physical_plan
        # Reuse only a static full-scene binding proof. Namespace/result values,
        # events, tokens and epochs are never memoized. Every trap/port above is
        # still checked on every call, including newly declared empty sites.
        _, support = geometry_world(world, self.device)
        proof_key = digest({'module':module['hash'], 'world':support, 'core':core,
                            'ports':{ids[q]:q for q in qs}, 'origin':origin})
        proofs = getattr(self, '_scene_proofs', {})
        reused_proof = proof_key in proofs
        if reused_proof:
            report = {'failures':[]}
        else:
            report = validate_physical_plan(result, self.device)
        # A leaf's declared external result ports have no local producer. Their
        # real producer/ready edge is checked after linking, never fabricated.
        failures = [f for f in report['failures'] if not (f['code'] == 'RESULT_UNKNOWN' and f.get('resource') in dag['external_reads'])]
        if failures:
            self.counters['bind_rejection_count'] += 1
            raise StrategyError('MODULE_FULL_SCENE_REJECTED', 'Static full-world module binding failed', failures=failures)
        proofs[proof_key] = True
        self._scene_proofs = proofs
        self.counters['bind_count'] += 1; self.timings['bind_seconds'] += time.perf_counter() - started
        result['module_binding'] = {'module_hash': module['hash'], 'variant_key': key, 'instance_id': instance_id,
                                    'static_scene_proof_sha256':proof_key, 'static_scene_proof_reused':reused_proof,
                                    'world_hash': digest(world), 'search_calls': 0, 'checked_atoms': len(current),
                                    'deferred_external_ports': list(dag['external_reads']),
                                    'static_geometry_passed': True, 'execution_qualified': False}
        result['module_binding']['artifact_ref'] = {'store': 'compiled-modules', 'file': key + '-' + module['hash'] + '.json'}
        result['enola'] = {'original_compile_receipts_ref': deepcopy(result['module_binding']['artifact_ref']),
                           'module_hash': module['hash'], 'search_repeated': False,
                           'receipt_scope': 'immutable module build coordinates and source identities; binding recorded separately'}
        return result

    def get_or_build(self, dag, world, *, instance_id, build_missing=True):
        key = _identity(dag, world, self.device, self.compiler_hash)[0]
        rejected = []
        for artifact in self._read(key):
            try:
                result = self.bind_module(artifact, dag, world, instance_id=instance_id)
            except StrategyError as exc:
                rejected.append({'module_hash': artifact['hash'], 'reason': exc.code}); continue
            self.counters['cache_hit_count'] += 1
            result['module_binding'].update(cache_hit=True, misses=rejected)
            return result
        if not build_missing:
            raise StrategyError('MODULE_DEPENDENCY_MISSING', 'Build dependency before composing this recipe', key=key, rejected=rejected)
        self.counters['variant_miss_count'] += 1
        if any(o['kind'] == 'measure' for o in dag['nodes']): self.counters['connector_miss_count'] += 1
        artifact = self.compile_module(dag, world)
        result = self.bind_module(artifact, dag, world, instance_id=instance_id)
        result['module_binding'].update(cache_hit=False, misses=rejected or [{'reason': 'variant_not_built'}])
        return result

    def compose_recipe(self, dags, world, *, execution_context=None, build_missing=False):
        started = time.perf_counter(); before = self.stats
        dags = dags if isinstance(dags, list) else [dags]
        source_hashes = [digest(d) for d in dags]
        current = deepcopy(world); cursor = 0.; results = []
        scheduled = {}; resource_owner = {}; source_release = {}; result_release = {}
        source_operations = {o['id']: o for d in dags for o in d['nodes']}
        frontier_evidence = []
        spatial = []
        spatial_parallel = getattr(self, 'spatial_parallel', False)
        def footprint(plan):
            actions = plan['atom_program']['actions']
            touched = {i for a in actions for i in a['atoms']}
            points = [a['position_um'] for a in plan['atom_program']['initial_state']['atoms'] if a['atom_id'] in touched]
            for a in actions:
                for t in a['payload'].get('trajectories', []):
                    points.extend([t['from_um'], t['to_um']])
                points.extend(b['position_um'] for b in a['payload'].get('bindings', []) if 'position_um' in b)
            return [min(p[0] for p in points), min(p[1] for p in points),
                    max(p[0] for p in points), max(p[1] for p in points)] if points else None
        def conflicts(a, b):
            # Conservative swept rectangle includes every linear trajectory,
            # capture intersection and stationary operand. Unknown means lock.
            if a is None or b is None: return True
            return not (a[2]+10 < b[0] or b[2]+10 < a[0] or a[3]+10 < b[1] or b[3]+10 < a[1])
        def select_couplings(operations):
            from .frontier_store import select_frontier
            selector = getattr(self, 'frontier_selector', select_frontier)
            selected, evidence = selector(self, operations, current, build_missing=build_missing)
            # The geometry-keyed file is only a lookup index: concurrent cold
            # builders may publish different namespace-bound receipts to it.
            # Freeze the exact receipt used by THIS binding under its body hash
            # before exposing a provenance reference in an immutable plan.
            if self.directory and evidence.get('schema_version') != 'ReusedComponentBatch/0.1':
                item=next(v for v in self.frontiers.values() if v['hash']==evidence['decision_hash'])
                raw=json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
                name='frontier-proof-'+item['hash']+'.json';path=self.directory/name
                import uuid
                temporary=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
                temporary.write_bytes(raw)
                if path.exists():
                    if path.read_bytes()!=raw:raise StrategyError('FRONTIER_PROOF_COLLISION','Immutable decision proof changed')
                    temporary.unlink()
                else:temporary.replace(path)
                evidence['lookup_file']=evidence['artifact_file'];evidence['artifact_file']=name
            frontier_evidence.append(evidence)
            return selected
        def consume(node):
            nonlocal current, cursor
            instance = 'module-instance:' + digest({'source': source_hashes, 'world': digest(world), 'module': node['id']})[:24]
            plan = self.get_or_build(node['dag'], current, instance_id=instance, build_missing=build_missing)
            if node['kind']=='entangling_layer':
                pulses=[a for a in plan['atom_program']['actions'] if a['payload'].get('name')=='CZ']
                if len(pulses)!=1:
                    raise StrategyError('COMMITTED_BATCH_RESERIALIZED','A qualified frontier batch must remain one physical pulse',source_ids=node['source_ids'],pulses=len(pulses))
            current = deepcopy(plan['exit_state'])
            actions = plan['atom_program']['actions']
            resources = {r for a in actions for r in a['resources']}
            # Bound leaves were routed against complete, static entry scenes.
            # Serialize changes to that scene until joint continuous routing
            # is qualified; disjoint local work can overlap their transport.
            moving = any(a['kind'] in ('move', 'pickup', 'drop', 'rebind') for a in actions)
            box = footprint(plan) if spatial_parallel else None
            if moving and not spatial_parallel:
                resources.add('composition:geometry_scene')
            if spatial_parallel:
                # Different row IDs are not permission to independently steer
                # one physical AOD. Keep each complete group exclusive.
                resources.update('composition:aod:'+a['payload']['aod_group'] for a in actions
                                 if a['payload'].get('aod_group') and a['kind'] in ('move','pickup','drop'))
            external = {d for sid in node['source_ids'] for d in source_operations[sid]['after'] if d not in node['source_ids']}
            reasons = [{'module_id': source_release[d]['module_id'], 'source_id':d,
                        'reason':'source_dependency', 'required_end_us':source_release[d]['end_us'],
                        'terminal_action_ids':source_release[d]['terminals']} for d in sorted(external)]
            reasons += [{'module_id': resource_owner[r]['module_id'],
                         'reason':'compiler_static_scene_limit' if r=='composition:geometry_scene' else 'resource_reservation',
                         'resource':r,'required_end_us':resource_owner[r]['end_us'],
                         'terminal_action_ids':resource_owner[r]['terminals']}
                        for r in sorted(resources) if r in resource_owner]
            if spatial_parallel:
                reasons += [dict(module_id=v['id'], reason='swept_geometry_conflict',
                                 required_end_us=v['end'], terminal_action_ids=v['terminals'])
                            for v in spatial if (moving or v['moving']) and conflicts(box, v['box'])]
            for action in actions:
                for r in action['payload'].get('reads', []):
                    if r in result_release:
                        producer=result_release[r]
                        reasons.append({'module_id':producer['module_id'],'result_id':r,
                            'reason':'classical_result_ready','required_end_us':max(0.,producer['ready_us']+
                                self.device['timings_us']['feedback_latency']-action['t_start_us']),
                            'terminal_action_ids':producer['terminals']})
            start = max((r['required_end_us'] for r in reasons), default=0.)
            terminals = list(dict.fromkeys(a for r in reasons for a in r['terminal_action_ids']))
            if start: _shift_window(plan, start)
            for a in actions:
                if not a['depends_on']: a['depends_on'] = list(terminals)
            end = plan['atom_program']['stats']['t_end_us']
            cursor = max(cursor, end)
            plan['module_binding'].update(kind=node['kind'], dependency_ids=node['dependencies'],
                                          source_ids=node['source_ids'], start_us=start, end_us=end,
                                          schedule_constraints=reasons, reserved_resources=sorted(resources))
            depended = {d for a in actions for d in a['depends_on']}
            scheduled[node['id']] = {'end_us': end, 'terminals': [a['id'] for a in actions if a['id'] not in depended]}
            by_action = {a['id']:a for a in actions}
            for sid in node['source_ids']:
                owned = [by_action[i] for i in plan['atom_program']['source_map'][sid]]
                stop = max(a['t_end_us'] for a in owned)
                source_release[sid] = {'module_id':node['id'],'end_us':stop,
                    'terminals':[a['id'] for a in owned if abs(a['t_end_us']-stop)<EPS]}
                for r in source_operations[sid]['writes']:
                    result_release[r]={'module_id':node['id'],'ready_us':plan['result_ready_offsets_us'][r],
                        'terminals':[a['id'] for a in owned if r in a['payload'].get('writes',[])]}
            for r in resources:
                owned = actions if r.startswith('composition:') else [a for a in actions if r in a['resources']]
                stop = max(a['t_end_us'] for a in owned)
                resource_owner[r] = {'module_id':node['id'],'end_us':stop,
                    'terminals':[a['id'] for a in owned if abs(a['t_end_us']-stop)<EPS]}
            if spatial_parallel:
                spatial.append(dict(id=node['id'], box=box, moving=moving, end=end,
                                    terminals=scheduled[node['id']]['terminals']))
                plan['module_binding']['swept_bounds_um'] = box
            results.append(plan)
        frozen_provider = getattr(self, 'recipe_graph_provider', None)
        if frozen_provider is not None:
            graph = frozen_provider(dags)
            for node in graph['modules']:
                consume(node)
            graph['joint_frontiers'] = []
            graph['frontier_policy'] = 'instantiate_frozen_component_recipe/1'
        else:
            graph = module_graph(dags, select_couplings=select_couplings, consume_module=consume)
            graph['joint_frontiers'] = frontier_evidence
            graph['frontier_policy'] = 'reopen_all_blocks_after_each_physical_batch/1'
        if not results:
            raise StrategyError('EMPTY_MODULE_RECIPE', 'A recipe must contain operations')
        merged = deepcopy(results[0]); atom = merged['atom_program']
        atom['actions'] = sorted([a for p in results for a in p['atom_program']['actions']],
                                 key=lambda a: (a['t_start_us'], a['t_end_us'], a['id']))
        initial_traps = {t['trap_id']: deepcopy(t) for t in world['slm_traps']}
        for p in results:
            for t in p['atom_program']['initial_state']['slm_traps']:
                if t['trap_id'] not in initial_traps: initial_traps[t['trap_id']] = {**deepcopy(t), 'occupant': None}
        # A physical plan is relative to t=0. Only the session binder attaches
        # its absolute clock; copying world.time_us here breaks later windows.
        atom['initial_state'] = {'atoms':deepcopy(world['atoms']), 'slm_traps':list(initial_traps.values()),
                                 'aod_rows':[], 'aod_columns':[]}
        atom['source_map'] = {k: v for p in results for k, v in p['atom_program']['source_map'].items()}
        atom['groups'] = [g for p in results for g in p['atom_program']['groups']]
        atom['artifact_id'] = 'module-composition:' + digest(graph['source_hashes'])[:24]
        atom['stats'].update(physical_op_count=sum(len(d['nodes']) for d in dags), action_count=len(atom['actions']),
                             t_start_us=0., t_end_us=cursor, duration_us=cursor, routing_search_count=0, placement_candidate_count=0)
        merged['exit_state'] = current
        merged['source'] = {'operations': [deepcopy(o) for d in dags for o in d['nodes']], 'groups': [deepcopy(g) for d in dags for g in d['groups']]}
        projected={o['id']:o for o in merged['source']['operations']}
        for d in dags:
            for edge in d['edges']:
                after=projected[edge['target']]['after']
                if edge['source'] not in after:after.append(edge['source'])
        merged['result_ready_offsets_us'] = {k: v for p in results for k, v in p['result_ready_offsets_us'].items()}
        merged['resource_intervals'] = [v for p in results for v in p['resource_intervals']]
        merged['ready_decisions'] = [v for p in results for v in p['ready_decisions']]
        merged['measurement_placements'] = [v for p in results for v in p['measurement_placements']]
        merged['enola'] = {'backend_used': 'compiled_module_composition', 'module_evidence': [p['enola'] for p in results]}
        merged.pop('module_binding', None)
        self.counters['composition_count'] += 1; self.timings['composition_seconds'] += time.perf_counter() - started
        merged['module_composition'] = {'schema_version': 'ModuleComposition/0.1', 'dependency_graph': graph,
                                      'schedule_policy': 'source_ports_and_resource_release/2',
                                      'geometry_overlap': 'disjoint_swept_rectangles_10um_and_exclusive_aod' if spatial_parallel else 'static_scene_mutations_serial_local_work_may_overlap',
                                      'instances': [p['module_binding'] for p in results], 'counters_before': before,
                                      'counters_after': self.stats, 'whole_stage_fallback': False,
                                      'cached_runtime_state': False, 'user_visual_acceptance': 'pending'}
        original=deepcopy(merged)
        merged=retain_compatible_aod(merged)
        merged=finalize_physical_plan(merged,dags,self.device,world,execution_context)
        if merged['aod_residency'].get('removed_action_ids'):
            from na_pipeline.validation.dag_physical import validate_physical_plan
            check=validate_physical_plan(merged,self.device)
            unresolved=[v for v in check['unverified'] if v['code']!='PHYSICAL_TRACE_MISSING']
            if check['failures'] or unresolved:
                rejected=deepcopy(merged['aod_residency'])
                merged=finalize_physical_plan(original,dags,self.device,world,execution_context)
                merged['aod_residency']={'schema_version':'CompositeAODResidency/0.1','merged_boundaries':[],
                    'saved_transfer_us':0.,'rejected_proposal':rejected,'validation_failures':check['failures'],'unverified':check['unverified']}
            else:merged['aod_residency']['independent_static_validation_passed']=True
        return merged
