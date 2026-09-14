"""SLM visibility controls on a real small Executor recording."""
from dataclasses import replace
from pathlib import Path
import shutil
import subprocess

import pytest


def test_closed_and_empty_slm_layers_preserve_atoms_and_aod(tmp_path):
    from neutral_atom_env.domain.models import StaticTrap, GridCoord, Position2D
    from neutral_atom_env.simulation.milestone1_factory import make_single_gate_state
    from neutral_atom_env.simulation.scheduler import EagerScheduler
    from neutral_atom_env.visualization import VisualRecorder

    node=shutil.which('node')
    if not node:pytest.skip('Node is required for the viewer control check')
    state=make_single_gate_state()
    traps=dict(state.world.traps)
    traps['empty_on']=StaticTrap('empty_on',GridCoord(-1,-8),Position2D(-5,-40))
    traps['empty_off']=StaticTrap('empty_off',GridCoord(5,-8),Position2D(25,-40),enabled=False)
    state=replace(state,world=replace(state.world,traps=traps),slm_enabled=None)
    recorder=VisualRecorder(state)
    assert EagerScheduler(state).run(on_event=recorder.observe).status=='completed'
    html=tmp_path/'slm-layers.html'
    recorder.write(html)
    result=subprocess.run([node,str(Path(__file__).with_name('slm_display_controls.cjs')),str(html)],
                          capture_output=True,text=True,check=True)
    assert 'PASS' in result.stdout

