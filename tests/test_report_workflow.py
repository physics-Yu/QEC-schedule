import json
from dataclasses import replace
import pytest
from neutral_atom_env.testing import acceptance
from neutral_atom_env.testing.scenarios import Evidence, Frame
from neutral_atom_env.testing.theme import VisualTheme
from neutral_atom_env.simulation import make_demo_state
from neutral_atom_env.world.config import LayoutConfig
from neutral_atom_env.domain.errors import ValidationError


def test_report_rerender_does_not_run_scenarios(tmp_path, monkeypatch):
    calls=[]
    state=make_demo_state();before=state.snapshot()
    def scenario():
        calls.append(1)
        return Evidence({'valid':True},(Frame('world','Read-only scene',before),))
    monkeypatch.setattr(acceptance,'SCENARIOS',(('one','One','Does it work?',scenario),))
    acceptance.build_report(tmp_path)
    results=(tmp_path/'results.json').read_bytes()
    def fail():raise AssertionError('Scenario must not run during re-render')
    monkeypatch.setattr(acceptance,'SCENARIOS',(('one','One','Does it work?',fail),))
    acceptance.render_report(tmp_path,replace(VisualTheme.load(),static_color='#654321'))
    assert len(calls)==1 and (tmp_path/'results.json').read_bytes()==results
    assert '#654321' in (tmp_path/'one/world.svg').read_text(encoding='utf-8')
    assert state.snapshot()==before


def test_failed_report_replaces_prior_pass(tmp_path,monkeypatch):
    (tmp_path/'index.html').write_text('OLD PASS',encoding='utf-8')
    def failed():raise AssertionError('Expected scenario failure')
    monkeypatch.setattr(acceptance,'SCENARIOS',(('failure','Failure','Question',failed),))
    with pytest.raises(RuntimeError):acceptance.build_report(tmp_path)
    data=json.loads((tmp_path/'results.json').read_text(encoding='utf-8'))
    assert not data[0]['passed']
    assert 'OLD PASS' not in (tmp_path/'index.html').read_text(encoding='utf-8')
    assert 'Expected scenario failure' in (tmp_path/'index.html').read_text(encoding='utf-8')


def test_overlapping_zones_rejected():
    world=LayoutConfig().build()
    zones=list(world.zones)
    zones[1]=replace(zones[1],bounds=zones[0].bounds)
    with pytest.raises(ValidationError,match='OVERLAPPING_ZONES'):replace(world,zones=tuple(zones))
