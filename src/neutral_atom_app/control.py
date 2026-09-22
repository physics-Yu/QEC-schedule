"""Application composition. The environment never imports this module."""
from dataclasses import dataclass

from neutral_atom_env.environment import NeutralAtomEnv
from neutral_atom_strategies.api import Strategy, FunctionStrategy


@dataclass
class ControlProgram:
    strategy: Strategy

    def run(self, env: NeutralAtomEnv, *, on_event=None):
        if not isinstance(env, NeutralAtomEnv):
            raise TypeError('ControlProgram runs against a NeutralAtomEnv')
        return self.strategy.run(env, on_event=on_event)


def configured_strategy(value):
    """Resolve historical workbench configurations outside the physical package."""
    implementation = value['compiler']
    shared = {'max_decisions': value.get('max_decisions', 10000)}
    if implementation in {'ordered_greedy','smt_ordered','zoned_ids'}:
        from neutral_atom_strategies.scheduling.ordered_controller import run_ordered as runner
        if implementation == 'zoned_ids':
            from neutral_atom_strategies.zoned import run_zoned as runner
        options=dict(shared,strategy=implementation,compile_timeout_s=value.get('compile_timeout_s',300),
                     beam_width=value.get('beam_width',64),plan_budget=value.get('plan_budget',4),
                     route_budget=value.get('route_budget',128),solver_timeout_ms=value.get('solver_timeout_ms',5000),
                     model_budget=value.get('model_budget',24),motion_router=value.get('motion_router','axis_hold'),
                     readout_mode=value.get('readout_mode','adaptive'),
                     readout_candidate_budget=value.get('readout_candidate_budget',16),readout_top_k=value.get('readout_top_k',3))
        if implementation == 'zoned_ids':
            options['site_limit']=value.get('site_limit',8)
            options['restore_layout']=value.get('placement_search',{}).get('terminal_mode','fixed')=='fixed'
    elif implementation in {'qec_ghz2', 'qec_persistent', 'qec_joint', 'qec_temporal', 'qec_temporal_four'}:
        if value['circuit_profile'] == 'qec_temporal_four':
            from neutral_atom_experiments.runners.qec_temporal_four import run_qec_temporal_four as runner
        elif value['circuit_profile'] == 'qec_temporal':
            from neutral_atom_experiments.runners.qec_temporal import run_qec_temporal as runner
        elif implementation == 'qec_joint':
            from neutral_atom_strategies.scheduling.qec_joint import run_qec_joint as runner
        elif implementation == 'qec_persistent':
            from neutral_atom_strategies.scheduling.qec_persistent import run_qec_persistent as runner
        else:
            from neutral_atom_strategies.scheduling.qec import run_qec as runner
        options = dict(shared, candidate_budget=value.get('row_candidate_budget', 4096),
                       route_expansions=value.get('route_expansions', 100000))
    elif implementation in {'patch_symmetric', 'patch_greedy', 'row_symmetric', 'row_greedy'}:
        if implementation.startswith('patch_'):
            from neutral_atom_strategies.scheduling.patch_greedy import run_patch as runner
        else:
            from neutral_atom_strategies.scheduling.row_greedy import run_row as runner
        options = dict(shared, strategy=implementation,
                       candidate_budget=value.get('row_candidate_budget', 4096),
                       route_expansions=value.get('route_expansions', 100000))
    elif implementation in {'basic', 'greedy', 'critical_path', 'lookahead'}:
        from neutral_atom_strategies.scheduling.m4 import run_m4 as runner
        options = dict(shared, strategy=implementation, ready_limit=value.get('ready_limit', 16),
                       site_limit=value.get('site_limit', 4), lookahead_depth=value.get('lookahead_depth', 2),
                       beam_width=value.get('beam_width', 3), rollout_budget=value.get('rollout_budget', 12),
                       adaptive_sites=value.get('ez_policy') == 'adaptive')
    elif implementation in {'resident', 'returning'}:
        from neutral_atom_strategies.scheduling.m3 import run_m3 as runner
        options = dict(shared, compiler=implementation)
    else:
        raise ValueError(f'Unsupported configured strategy: {implementation}')
    return FunctionStrategy(implementation, runner, options)
