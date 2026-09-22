"""Independent placement trials through the ordinary physical controller."""
from concurrent.futures import ProcessPoolExecutor
from contextlib import nullcontext
from dataclasses import replace
from hashlib import sha256
import json
import multiprocessing
from pathlib import Path
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.platform import initialize
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_strategies.placement import CompilerSearchConfig, PhysicalEvaluation, optimize_with_compiler
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from .placement import platform_placement_problem
from .placement_worker import execute_candidate


def optimize_compiled_layout(circuit, platform, initial_mapping, *, locked=None,
                            storage_ids=None, config=CompilerSearchConfig(),
                            compiler_options=None, seed=0, quantum_state=None,
                            terminal_target=None, verify_protocol=None,
                            output=None, on_trial=None, free_placement=False,
                            terminal_mode='fixed', workers=1):
    """Choose complete duration under a fixed or stable completion contract.

    fixed restores original absolute holders, masks and AOD configuration.
    stable finishes all gates and accepted services, omitting final layout return.
    Both retain per-CZ return, physical stability and independent replay checks.
    Initial assembly is excluded; workers never share a live environment.
    """
    if terminal_mode not in {'fixed','stable'}:raise ValueError('Unknown terminal mode')
    if terminal_mode=='stable' and terminal_target is not None:
        raise ValueError('Stable completion cannot specify fixed terminal target')
    if type(workers) is not int or not 1<=workers<=8:raise ValueError('workers must be 1..8')
    initial_mapping=dict(initial_mapping)
    problem=platform_placement_problem(circuit,platform,initial_mapping,
        locked=locked,storage_ids=storage_ids,include_disabled=free_placement)
    options=dict(compiler_options or {})
    if {'terminal_target','on_event','restore_layout'} & options.keys():
        raise ValueError('Terminal and observer must not be overridden in compiler_options')
    base=replace(initialize(circuit,platform,initial_mapping,seed=seed),quantum_state=quantum_state)
    def prepare(mapping):
        if not free_placement:
            return replace(initialize(circuit,platform,dict(mapping),seed=seed),quantum_state=quantum_state)
        from neutral_atom_env.domain.models import HolderRef,HolderType
        from neutral_atom_env.world import PlacementState
        switches=dict(base.slm_enabled)
        for site in initial_mapping.values():switches[site]=False
        for q,site in mapping:switches[site]=True
        return replace(base,placement=PlacementState({q:HolderRef(HolderType.STATIC,s) for q,s in mapping}),
                       slm_enabled=switches)
    terminal=(terminal_target if terminal_target is not None else initial_terminal(base)) if terminal_mode=='fixed' else None
    config=replace(config,batch_size=workers) if workers>1 else config
    contract=dict(circuit=circuit,platform=platform,compiler_options=options,seed=seed,
        quantum_state=quantum_state.to_dict() if quantum_state is not None else None,
        terminal=terminal,terminal_mode=terminal_mode,workers=workers,initial_mapping=initial_mapping,
        search=config,candidate_sites=problem.storage,locked=problem.locked,free_placement=free_placement,
        initial_support_policy='prepare occupied candidate SLMs' if free_placement else 'preserve platform switches',
        initialization='prepared atoms; initial assembly excluded',
        objective='complete physical service to stable state; no final layout return' if terminal_mode=='stable'
                  else 'complete simulation time including fixed absolute terminal',
        protocol_verifier='provided' if verify_protocol else 'not_provided')
    contract_hash=sha256(canonical_json(contract).encode()).hexdigest()
    directory=Path(output) if output is not None else None
    if directory:
        directory.mkdir(parents=True,exist_ok=True)
        (directory/'contract.json').write_text(canonical_json(contract),encoding='utf-8')
    number=0
    context=ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) if workers>1 else nullcontext(None)
    with context as pool:
        def evaluate_batch(mappings):
            nonlocal number
            pending=[]
            for mapping in mappings:
                folder=directory/f'trial-{number:04d}' if directory else None
                number+=1
                request=dict(initial=NeutralAtomEnv(prepare(mapping)).snapshot(),directory=str(folder) if folder else None,
                    mapping=mapping,contract=contract_hash,options=options,terminal=terminal,
                    terminal_mode=terminal_mode,return_final=verify_protocol is not None)
                try:
                    future=pool.submit(execute_candidate,request) if pool else execute_candidate(request)
                except Exception as error:future=error
                pending.append((future,folder))
            results=[]
            for future,folder in pending:
                seconds=0.
                try:
                    if isinstance(future,Exception):raise future
                    value,seconds,final=future.result() if pool else future
                    if value.valid and verify_protocol is not None and not verify_protocol(NeutralAtomEnv.restore(final).state):
                        raise AssertionError('Protocol verification failed')
                except Exception as error:
                    failure=f'{type(error).__name__}: {error}'
                    value=PhysicalEvaluation(False,failure=failure,evidence=str(folder/'result.json') if folder else None)
                    if folder:
                        folder.mkdir(parents=True,exist_ok=True);path=folder/'result.json'
                        report=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
                        report.update(valid=False,failure=failure)
                        path.write_text(canonical_json(report),encoding='utf-8')
                results.append((value,seconds))
            return results
        search=optimize_with_compiler
        if free_placement:
            from neutral_atom_strategies.placement.free import optimize_free_placement
            search=optimize_free_placement
        result=search(problem,lambda m:evaluate_batch((m,))[0][0],config=config,
            contract=f'ordered-controller fixed circuit/platform/options; completion={terminal_mode}; sha256={contract_hash}',
            on_trial=on_trial,evaluate_batch=evaluate_batch)
    result=replace(result,diagnostics=dict(result.diagnostics,workers=workers,terminal_mode=terminal_mode))
    if directory:(directory/'search.json').write_text(canonical_json(result),encoding='utf-8')
    return result


def optimize_free_layout(circuit,platform,initial_mapping,*,config=None,**options):
    """Search all eligible storage sites, preparing their initial SLM support."""
    return optimize_compiled_layout(circuit,platform,initial_mapping,
        config=config or CompilerSearchConfig(allow_vacancies=True),free_placement=True,**options)
