"""Workbench product boundary: locked experiments and circuit-independent choices.

Legacy inputs remain supported by workbench.validate_input. This module constrains
the new studio modes without relabelling experiment-specific executors as general.
"""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path


CONFIG_PATH = Path(__file__).resolve().parents[3] / 'configs/studio/workbench.json'
# Executable implementations/generators are code capabilities, not user-extensible imports.
GENERAL_IMPLEMENTATIONS = frozenset({'greedy', 'critical_path', 'lookahead', 'basic', 'returning', 'resident', 'ordered_greedy', 'smt_ordered'})
CIRCUIT_GENERATORS = frozenset({'parallel1q', 'ghz', 'chain', 'mixed', 'rotations', 'empty', 'nonuniform_pairs'})


def load_catalog(path=CONFIG_PATH):
    """Read and check a catalog; runtime uses one snapshot per Python process."""
    path = Path(path)
    value = json.loads(path.read_text(encoding='utf-8'))
    required = {'schema', 'algorithms', 'demos', 'architecture', 'coordinate_mode',
                'compilation_defaults', 'default_algorithm', 'default_circuit',
                'workspace_defaults', 'circuit_presets'}
    if not isinstance(value, dict) or set(value) != required or value['schema'] != 'atom-studio-catalog/v1':
        raise ValueError('Invalid studio catalog schema or fields')
    if value['architecture'] not in {'rigid','row_column','row_column_orthogonal'} or value['coordinate_mode'] != 'relative_offsets':
        raise ValueError('Catalog cannot advertise an unimplemented architecture or coordinate mode')
    def entries(key, allowed=None):
        items = value[key]
        if not isinstance(items, list) or not items or any(not isinstance(i, dict) for i in items):
            raise ValueError(key + ' requires a nonempty list of objects')
        ids = [i.get('id') for i in items]
        if (any(not isinstance(i, str) or not i or not all(c.isascii() and (c.isalnum() or c in '-_') for c in i) for i in ids)
                or len(set(ids)) != len(ids) or allowed is not None and not set(ids) <= allowed):
            raise ValueError('Unknown or duplicate ' + key + ' IDs')
        if any(not isinstance(i.get('label'), str) or not i['label'] for i in items):
            raise ValueError(key + ' requires labels')
        return set(ids)
    algorithms = entries('algorithms', GENERAL_IMPLEMENTATIONS)
    circuits = entries('circuit_presets', CIRCUIT_GENERATORS)
    entries('demos')
    if value['default_algorithm'] not in algorithms or value['default_circuit'] not in circuits:
        raise ValueError('Defaults must reference catalog entries')
    from neutral_atom_app.visualization.workbench import ORDERED_SEARCH_LIMITS, MAX_COMPILE_TIMEOUT_S
    limits = dict(ORDERED_SEARCH_LIMITS, max_decisions=10000, compile_timeout_s=MAX_COMPILE_TIMEOUT_S)
    for budgets in [value['compilation_defaults'], *(a.get('defaults') for a in value['algorithms'])]:
        if (not isinstance(budgets, dict) or set(budgets)-limits.keys() or
                any(type(v) is not int or not 1 <= v <= limits[k] for k, v in budgets.items())):
            raise ValueError('Invalid compilation defaults')
    for algorithm in value['algorithms']:
        if bool(algorithm.get('single_trap')) != (algorithm['id'] in {'returning', 'resident'}):
            raise ValueError('single_trap must match the implemented algorithm capability')
    workspace = value['workspace_defaults']
    if (not isinstance(workspace, dict) or workspace.get('studio') != {'mode': 'custom'} or
            workspace.get('circuit_profile') != 'physical' or
            set(workspace) & {'gates', 'compilation', 'compiler', 'compilation_backend'}):
        raise ValueError('workspace_defaults must contain only custom initial/platform settings')
    for demo in value['demos']:
        filename = demo.get('input_file')
        if not isinstance(filename, str):
            raise ValueError('Demo requires input_file')
        target = (path.parent / filename).resolve()
        if not target.is_relative_to(path.parent.resolve()) or target.suffix != '.json' or not target.is_file():
            raise ValueError('Demo input_file must be an existing JSON inside the catalog directory')
    return value


_CONFIG = load_catalog()
ALGORITHMS = tuple(_CONFIG['algorithms'])
DEMOS = tuple(_CONFIG['demos'])
_DEMO_INPUTS = {d['id']: json.loads((CONFIG_PATH.parent / d['input_file']).read_text(encoding='utf-8'))
                for d in DEMOS}


def catalog():
    return deepcopy(_CONFIG)


@lru_cache(maxsize=8)
def _demo_base(identifier):
    from neutral_atom_app.visualization.workbench import validate_input
    spec = next((d for d in DEMOS if d['id'] == identifier), None)
    if spec is None:
        raise ValueError('Unknown studio demo')
    value = deepcopy(_DEMO_INPUTS[identifier])
    if 'studio' in value:
        raise ValueError('Demo input files must not embed studio mode metadata')
    return validate_input(value)


def demo_input(identifier):
    value = deepcopy(_demo_base(identifier))
    value['studio'] = {'mode': 'demo', 'demo_id': identifier}
    return value


def configuration_issue(value):
    """Planning capability, distinct from representable hardware geometry."""
    from neutral_atom_app.visualization.workbench import aod_shape, aod_offsets, M4_STRATEGIES
    ordered=value['compiler'] in {'ordered_greedy','smt_ordered'}
    backend=value.get('aod_backend','rigid')
    if ordered and backend not in {'row_column','row_column_orthogonal'}:
        return '有序轴策略需要 row_column 或 row_column_orthogonal 后端；请在平台配置中选择，线路和原子布局不变。'
    if not ordered and backend!='rigid':
        return '旧策略仅接入 rigid 后端；请显式切换平台或选择新版有序策略。'
    if value.get('studio', {}).get('mode') != 'custom':
        return None
    rows, columns = aod_shape(value)
    y, x = aod_offsets(value, rows, columns)
    if (value['compiler'] in M4_STRATEGIES and rows*columns > 1 and
            (rows != 1 or y != (0,) or x != tuple(i*10 for i in range(columns)))):
        return ('当前通用多交点规划器仅支持单行、10 μm 等间距 AOD。此几何可预览和保存，'
                '但尚不能由该规划器编译；请使用 1 × 1 或列偏移 0, 10, 20… 的单行阵列。')
    return None


def validate_studio(raw, normalized):
    """Validate the new UI boundary after physical input normalization."""
    if 'studio' not in raw:
        return normalized  # Historical API compatibility, never silently converted.
    studio = raw['studio']
    if not isinstance(studio, dict) or studio.get('mode') not in {'custom', 'demo'}:
        raise ValueError('studio.mode must be custom or demo')
    if studio['mode'] == 'demo':
        if set(studio) != {'mode', 'demo_id'} or not isinstance(studio['demo_id'], str):
            raise ValueError('Demo requires its catalog demo_id')
        expected = _demo_base(studio['demo_id'])
        if normalized != expected:
            raise ValueError('Demo configuration and circuit are locked; start a custom workspace to edit')
    else:
        if set(studio) != {'mode'}:
            raise ValueError('Custom workspace cannot carry demo settings')
        if (normalized['circuit_profile'] != 'physical' or
                normalized['layout'] not in {'row', 'grid', 'shuffled'} or
                normalized['compiler'] not in {a['id'] for a in ALGORITHMS}):
            raise ValueError('Custom mode requires a general algorithm and row/grid/shuffled physical layout; specialized QEC/patch algorithms belong to demos')
        if normalized.get('ez_policy') != 'adaptive':
            raise ValueError('Custom mode uses demand-driven EZ sites')
    normalized['studio'] = deepcopy(studio)
    if studio['mode'] == 'custom':
        normalized['compilation_backend']['configuration_error'] = configuration_issue(normalized)
    return normalized
