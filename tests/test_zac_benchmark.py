"""Independent workload contracts and honest handling of incomplete timings."""
from collections import Counter
import pytest
from neutral_atom_experiments.zac_benchmark import workload
from neutral_atom_experiments.zac_benchmark_report import rows_from_manifest
from neutral_atom_experiments.zac_reuse import normalize_spec, make_state


@pytest.mark.parametrize('n', [16, 32, 64, 128])
@pytest.mark.parametrize('family', ['repeat', 'butterfly', 'random'])
def test_full_matching_layers_and_scaled_hardware(n, family):
    case = workload(n, 8, family)
    pairs = case['spec']['pairs']
    assert len(pairs) == 4 * n
    for i in range(8):
        layer = pairs[i*n//2:(i+1)*n//2]
        assert Counter(q for pair in layer for q in pair) == Counter(range(n))
    state = make_state(case['spec'])
    assert state.aod.rows * state.aod.columns <= 128
    assert len(state.atoms) == n
    assert len(set(state.placement.atom_to_holder.values())) == n
    assert state.hardware.interaction_distance_um == 2
    assert state.hardware.minimum_clearance_um == 1
    assert state.hardware.ez_neighbor_guard_enabled
    if family == 'repeat':
        assert pairs[:n//2] == pairs[n//2:n]
    else:
        assert pairs[:n//2] != pairs[n//2:n]


def test_seed_reproduction_and_timeout_validation():
    assert workload(32,8,'random',5) == workload(32,8,'random',5)
    assert workload(32,8,'random',5)['spec']['pairs'] != workload(32,8,'random',6)['spec']['pairs']
    for timeout in [True, 0, float('nan'), 7201]:
        with pytest.raises(ValueError):
            normalize_spec(dict(atom_count=32,pairs=[[0,31]],timeout_s=timeout))


def test_failed_prefix_is_not_a_completed_benchmark_time():
    case = workload(16,8,'random')
    case['variants'] = {'reuse':dict(status='failed', result=dict(
        metrics=dict(episode_wall_time_us=123,completed_gate_count=8),
        error=dict(code='ZAC_TRANSFER_EXHAUSTED'), replay_equal=True,
        effects_once=False, terminal_verified=False))}
    row = rows_from_manifest(dict(cases=[case]))[0]
    assert row['total_us'] is None
    assert row['prefix_us'] == 123
    assert row['replay_equal'] is True
    assert row['effects_once'] is False
    assert 'ZAC_TRANSFER_EXHAUSTED' in row['error']


def test_spare_axes_use_bounds_and_common_indices_without_relaxing_spacing():
    from neutral_atom_strategies.motion.bounded_spare_axes import bounded_spare_axes
    from neutral_atom_env.domain.errors import ValidationError
    start, end = (0, 90), (30, 100)
    a, b = bounded_spare_axes(start,end,32,-20,120,1.01)
    assert len(a) == len(b) == 32
    for values in (a,b):
        assert values[0] >= -20 and values[-1] <= 120
        assert all(y-x > 1.01 for x,y in zip(values,values[1:]))
    assert [a.index(x) for x in start] == [b.index(x) for x in end]
    # Endpoints can each fit an array but cannot share active-cell identity.
    with pytest.raises(ValidationError,match='AXIS_BOUNDS'):
        bounded_spare_axes((0,),(100,),64,-20,120,1.01)


def test_bounded_spares_single_atom_transfer_executes_and_replays():
    from neutral_atom_env import NeutralAtomEnv
    from neutral_atom_env.domain.errors import ValidationError
    from neutral_atom_strategies.motion.ordered_transfer import OrderedTransfer
    from neutral_atom_strategies.scheduling.ordered_greedy import new_builder, finish
    spec = normalize_spec(dict(atom_count=32,pairs=[[0,31]]))
    env = NeutralAtomEnv(make_state(spec))
    initial = env.snapshot()
    target = {'Q031':'Z2_R1_C7'}
    with pytest.raises(ValidationError,match='AXIS_BOUNDS'):
        OrderedTransfer().transfer_group(new_builder(env.state),target)
    assert env.snapshot() == initial
    builder = new_builder(env.state)
    OrderedTransfer(bounded_spares=True).transfer_group(builder,target)
    plan = finish(builder)
    env.submit(plan)
    env.run()
    assert env.state.placement.atom_to_holder['Q031'].holder_id == target['Q031']
    assert env.state.metrics()['captured_atom_count_total'] == 1
    replay = NeutralAtomEnv.restore(initial)
    replay.submit(plan)
    replay.run()
    assert replay.snapshot() == env.snapshot()
