"""Public orchestration API; any QECCode implementation may supply the circuit."""
import json
from pathlib import Path
from .hardware import build_initial_state
from .lowering import GateLowerer, LegacyGateLowerer
from .qec import create_code
from .scheduler import RuntimeScheduler
from .scheduler.engine import Scheduler
from .trace import metrics


def run_cycle(config, *, code=None, rounds=1, primitive='CZ', device_capacities=None,
              rydberg_parallel_pairs=None):
    code = create_code() if code is None else code
    state = build_initial_state(code, config)
    circuit = code.syndrome_round(rounds=rounds, primitive=primitive)
    plan = GateLowerer().lower(circuit, state)
    trace = RuntimeScheduler(config, device_capacities=device_capacities,
                             rydberg_parallel_pairs=rydberg_parallel_pairs).run(plan, state)
    trace['configuration'] = {'code': code.name, 'rounds': rounds, 'primitive': primitive,
                              'timing': config.timing.to_dict(), 'aod': config.aod.to_dict(),
                              'zones': [zone.to_dict() for zone in config.zones],
                              'device_capacities': {key: value for key, value in trace['resource_capacities'].items()
                                                    if key.startswith('device/')},
                              'rydberg_parallel_pairs': rydberg_parallel_pairs}
    result = metrics(trace)
    trace['metrics'] = result
    return trace, result


def run_legacy_cycle(config, *, code=None, rounds=1, primitive='CZ', device_capacities=None):
    """Migration helper for callers that still consume the action IR."""
    code = create_code() if code is None else code
    state = build_initial_state(code, config)
    circuit = code.syndrome_round(rounds=rounds, primitive=primitive)
    plan = LegacyGateLowerer(config.timing).lower(circuit, state)
    trace = Scheduler(config, device_capacities=device_capacities).run(plan, state)
    trace['configuration'] = {'code': code.name, 'rounds': rounds, 'primitive': primitive,
                              'timing': config.timing.to_dict(), 'aod': config.aod.to_dict(),
                              'zones': [zone.to_dict() for zone in config.zones],
                              'device_capacities': {key: value for key, value in trace['resource_capacities'].items()
                                                    if key.startswith('device/')}}
    return trace, metrics(trace)


def save_run(trace, result_metrics, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, data in [('trace', trace), ('metrics', result_metrics)]:
        (output_dir / f'{name}.json').write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
