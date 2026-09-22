"""Actual spawned workers, fixed wave ordering and stable completion semantics."""
import json
from dataclasses import replace
from neutral_atom_app.placement_workbench import default_input,build_problem
from neutral_atom_app.placement_execution import optimize_free_layout
from neutral_atom_strategies.placement import CompilerSearchConfig
from neutral_atom_env import NeutralAtomEnv


def small_problem():
    raw=default_input();raw.update(atom_count=2,source_rows=2,source_columns=2,aod_rows=2,aod_columns=2,
        gates=[dict(id='cz0',gate_type='CZ',qubit_ids=['Q000','Q001']),
               dict(id='h',gate_type='H',qubit_ids=['Q000']),
               dict(id='cz1',gate_type='CZ',qubit_ids=['Q000','Q001'])])
    return build_problem(raw)[1:4]


def test_spawned_parallel_matches_same_serial_waves_and_skips_final_return(tmp_path):
    circuit,platform,mapping=small_problem()
    config=CompilerSearchConfig(max_evaluations=5,proposal_pool=256,allow_vacancies=True,batch_size=2,exhaustive_limit=0)
    serial=optimize_free_layout(circuit,platform,mapping,config=config,workers=1,terminal_mode='stable',
        compiler_options={'compile_timeout_s':60},output=tmp_path/'serial')
    parallel=optimize_free_layout(circuit,platform,mapping,config=config,workers=2,terminal_mode='stable',
        compiler_options={'compile_timeout_s':60},output=tmp_path/'parallel')
    assert [t.mapping for t in serial.trials]==[t.mapping for t in parallel.trials]
    assert [t.evaluation.total_time_us for t in serial.trials]==[t.evaluation.total_time_us for t in parallel.trials]
    assert all(t.evaluation.valid for t in parallel.trials)
    assert parallel.selected.index==serial.selected.index
    pids=set()
    for t in parallel.trials:
        folder=tmp_path/'parallel'/f'trial-{t.index:04d}'
        r=json.loads((folder/'result.json').read_text(encoding='utf-8'));pids.add(r['worker_pid'])
        assert r['terminal_mode']=='stable' and r['replay_equal']
        assert not any(d['kind'] in {'Return to initial SLM','terminal'} for d in r['execution']['decision_log'])
        state=NeutralAtomEnv.restore((folder/'final.json').read_text(encoding='utf-8')).state
        assert state.dag.completed and state.transfer is None and not state.aod.is_moving
        # The final CZ's physical return/offload remains counted, never truncate at its pulse.
        assert state.time_us>state.metrics()['logical_completion_elapsed_us']
        assert {q:h.holder_id for q,h in state.placement.atom_to_holder.items()}!=mapping
    assert len(pids)==2


def test_parallel_protocol_callback_stays_in_parent(tmp_path):
    circuit,platform,mapping=small_problem()
    r=optimize_free_layout(circuit,platform,mapping,workers=2,terminal_mode='stable',
        config=CompilerSearchConfig(max_evaluations=2,allow_vacancies=True),
        verify_protocol=lambda state:False,output=tmp_path)
    assert r.status=='no_valid_execution'
    assert all('Protocol verification failed' in t.evaluation.failure for t in r.trials)


def test_saved_input_without_new_fields_preserves_legacy_contract():
    raw=default_input()
    for key in ('workers','proposal_pool','terminal_mode'):raw.pop(key)
    value,*_=build_problem(raw)
    assert (value['workers'],value['proposal_pool'],value['terminal_mode'])==(1,64,'fixed')


def test_fixed_terminal_also_works_across_spawn_boundary(tmp_path):
    circuit,platform,mapping=small_problem()
    result=optimize_free_layout(circuit,platform,mapping,workers=2,terminal_mode='fixed',
        config=CompilerSearchConfig(max_evaluations=3,allow_vacancies=True),output=tmp_path)
    assert all(t.evaluation.valid for t in result.trials)
    for t in result.trials:
        env=NeutralAtomEnv.restore((tmp_path/f'trial-{t.index:04d}'/'final.json').read_text(encoding='utf-8'))
        assert not env.pending
        assert {q:h.holder_id for q,h in env.state.placement.atom_to_holder.items()}==mapping
        assert env.state.slm_enabled=={s:t.enabled for s,t in platform.world.traps.items()}
