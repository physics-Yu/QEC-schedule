"""Independent invariants for the ZAC frontend/physical adapter boundary."""
from collections import Counter
from copy import deepcopy
from itertools import product
from pathlib import Path
import ast
import random
import types

import pytest
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.operations import OperationType as K
from neutral_atom_experiments.zac_reuse import (DEFAULT_SOURCE, demos, normalize_spec,
                                               make_state, frontend, run_one)
from neutral_atom_strategies.scheduling.zac_reuse import ZACPlacementStrategy
from neutral_atom_strategies.scheduling.ordered_greedy import new_builder


@pytest.mark.parametrize('raw',[
    {'atom_count':True,'pairs':[[0,1]]}, {'atom_count':129,'pairs':[[0,1]]},
    {'atom_count':2,'pairs':[]}, {'atom_count':2,'pairs':[[0,0]]},
    {'atom_count':2,'pairs':[[0,2]]}, {'atom_count':2,'pairs':[[0,1.0]]},
])
def test_bad_circuit_rejected(raw):
    with pytest.raises(ValueError):
        normalize_spec(raw)


def test_geometry_uses_existing_physical_limits():
    state=make_state(normalize_spec(demos()['cross']))
    assert state.hardware.interaction_distance_um == 2
    assert state.hardware.minimum_clearance_um == 1
    assert state.hardware.minimum_axis_spacing_um == 1.01
    assert state.hardware.ez_neighbor_guard_enabled
    assert all(state.slm_enabled[h.holder_id] for h in state.placement.atom_to_holder.values())
    assert not any(state.aod.enabled_rows)
    assert not any(state.aod.enabled_columns)


def test_sz_pulse_is_rejected_without_live_mutation():
    env=NeutralAtomEnv(make_state(normalize_spec(demos()['cross'])))
    before=env.snapshot()
    p=new_builder(env.state,('g0000','g0001'))
    with pytest.raises(ValidationError):
        p.add(K.ENTANGLING_PULSE,'Cannot pulse storage atoms',gate_ids=('g0000','g0001'))
    assert env.snapshot() == before


@pytest.mark.skipif(not (DEFAULT_SOURCE/'zac/zac.py').exists(),reason='Fetch original ZAC sources first')
def test_original_reuse_matching_against_exhaustive_oracle():
    # Execute precisely the original method body, independently of our adapter.
    # No full compiler run is needed to check the combinatorial matching rule.
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import maximum_bipartite_matching
    tree=ast.parse((DEFAULT_SOURCE/'zac/zac.py').read_text())
    klass=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ZAC')
    method=next(n for n in klass.body if isinstance(n,ast.FunctionDef) and n.name=='collect_reuse_qubit')
    ns=dict(csr_matrix=csr_matrix,maximum_bipartite_matching=maximum_bipartite_matching)
    exec(compile(ast.Module(body=[method],type_ignores=[]),'<original-zac-reuse>','exec'),ns)
    rng=random.Random(20260920)
    for _ in range(120):
        n=8
        def layer():
            values=list(range(n));rng.shuffle(values)
            return [values[i:i+2] for i in range(0,2*rng.randint(1,4),2)]
        previous,current=layer(),layer()
        obj=types.SimpleNamespace(n_q=n,gate_scheduling=[previous,current])
        ns['collect_reuse_qubit'](obj)
        same=[g for g in current if any(set(g)==set(p) for p in previous)]
        fixed={q for g in same for q in g}
        edges=[[i for i,p in enumerate(previous) if set(p)&set(g)]
               for g in current if g not in same]
        best=0
        for choices in product(*[[-1]+e for e in edges]):
            used=[c for c in choices if c!=-1]
            if len(set(used))==len(used):best=max(best,len(used))
        retained=obj.reuse_qubit[0]
        assert len(retained)==len(fixed)+best
        assert fixed<=retained
        assert retained<=set(sum(previous,[]))&set(sum(current,[]))
        for g in current:
            if g not in same:assert len(set(g)&retained)<=1
        for g in previous:
            if not set(g)<=fixed:assert len(set(g)&retained)<=1


@pytest.mark.skipif(not (DEFAULT_SOURCE/'zac/zac.py').exists(),reason='Fetch original ZAC sources first')
def test_real_physical_repeat_and_changed_initial_state(tmp_path):
    spec=normalize_spec(dict(name='two atoms / two CZ',atom_count=2,pairs=[[0,1],[0,1]]))
    placement=frontend(spec,DEFAULT_SOURCE,tmp_path/'upstream',True)
    assert placement['selected_reuse']==[[0,1],[]]
    result,payload=run_one(spec,placement,tmp_path/'physical')
    assert result['status']=='completed',result['error']
    assert result['replay_equal'] and result['effects_once'] and result['terminal_verified']
    assert all(r['passed'] for r in result['reuse_audit'])
    pulses=[o for o in payload['operations'] if o['kind']=='entangling_pulse']
    assert len(pulses)==2
    assert pulses[0]['end']==pulses[1]['start']  # zero invented return/pickup between repeated stages
    assert Counter(g for o in pulses for g in o['gate_ids'])==Counter({'g0000':1,'g0001':1})
    env=NeutralAtomEnv(make_state(spec));before=env.snapshot()
    changed=deepcopy(placement);changed['mappings'][0].reverse()
    with pytest.raises(ValueError,match='initial state'):
        ZACPlacementStrategy(changed).run(env)
    assert env.snapshot()==before
