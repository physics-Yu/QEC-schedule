"""Headless custom-circuit layout compilation; no UI and no live-state mutation."""
from dataclasses import asdict
from hashlib import sha256
import json

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate
from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_strategies.placement import PlacementProblem, SearchConfig, Site, optimize_initial


def platform_placement_problem(circuit, platform, initial_mapping, *, locked=None, storage_ids=None,
                               include_disabled=False):
    """Layout proposal for an existing platform, usable before env.create.

    By default only already-enabled storage SLMs are available. Free placement
    explicitly includes disabled sites; its execution adapter prepares initial
    support before creating the environment. This extractor never changes the
    hardware geometry or any runtime state.
    """
    from neutral_atom_env.domain.models import ZoneType
    def within(trap, kind):
        return any(z.zone_type == kind and z.bounds.contains(trap.position) for z in platform.world.zones)
    def site(trap):
        return Site(trap.id, trap.position.x_um, trap.position.y_um)
    storage = tuple(site(t) for t in platform.world.traps.values()
                    if (t.enabled or include_disabled) and within(t,ZoneType.STORAGE))
    if storage_ids is not None:
        ids = set(storage_ids)
        if not ids <= {s.id for s in storage}:
            raise ValueError('Candidate sites must be existing eligible storage SLMs')
        storage = tuple(s for s in storage if s.id in ids)
    interaction = tuple(site(t) for t in platform.world.traps.values() if within(t,ZoneType.ENTANGLEMENT))
    return PlacementProblem(circuit, tuple(initial_mapping), storage, interaction,
        tuple(initial_mapping.items()), tuple((locked or {}).items()),
        platform.aod.rows, platform.aod.columns, platform.hardware)


def compile_platform_layout(circuit, platform, initial_mapping, *, locked=None, config=SearchConfig()):
    """Cheap legacy proxy proposal; use optimize_compiled_layout for timed search."""
    problem = platform_placement_problem(circuit,platform,initial_mapping,locked=locked)
    return optimize_initial(problem, config)


def parse_request(raw):
    allowed = {'schema', 'qubits', 'gates', 'storage', 'interaction_sites', 'initial_mapping',
               'locked', 'aod', 'hardware', 'search'}
    if set(raw) - allowed:
        raise ValueError(f'Unknown placement fields: {sorted(set(raw)-allowed)}')
    if raw.get('schema') != 'initial-placement/1':
        raise ValueError('Expected schema initial-placement/1')
    aod = raw.get('aod', {})
    if set(aod) - {'rows', 'columns'}:
        raise ValueError('AOD placement capacity accepts rows and columns only')
    circuit = PhysicalCircuit(tuple(PhysicalGate(**g) for g in raw['gates']))
    problem = PlacementProblem(circuit, tuple(raw['qubits']),
        tuple(Site(**s) for s in raw['storage']), tuple(Site(**s) for s in raw['interaction_sites']),
        tuple(raw['initial_mapping'].items()), tuple(raw.get('locked', {}).items()),
        aod.get('rows', 16), aod.get('columns', 16),
        HardwareConfig(**raw.get('hardware', {'backend': 'row_column_orthogonal'})))
    return problem, SearchConfig(**raw.get('search', {}))


def compile_layout(raw):
    """Return unchanged full circuit plus estimated layout candidates and provenance.

    Caller may pass selected mapping to NeutralAtomEnv.create BEFORE execution.
    An already-loaded array requires real transport, not replacing its mapping.
    """
    problem, config = parse_request(raw)
    result = optimize_initial(problem, config)
    circuit = asdict(problem.circuit)
    digest = sha256(json.dumps(circuit, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return dict(schema='initial-placement-result/1', **asdict(result),
                circuit=circuit, circuit_sha256=digest, search=asdict(config),
                input=raw, initialization='prepared mapping; no assembly motion included')
