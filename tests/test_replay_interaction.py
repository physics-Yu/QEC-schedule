"""Interaction controls consume real Executor recordings, never edit physical state."""
from pathlib import Path
import subprocess

from neutral_atom_env.simulation.milestone1_factory import make_single_gate_state
from neutral_atom_env.simulation.scheduler import EagerScheduler
from neutral_atom_env.visualization import VisualRecorder


def test_replay_controls_and_static_preview(tmp_path):
    state=make_single_gate_state()
    recorder=VisualRecorder(state)
    initial=tmp_path/'initial.html';recorder.write(initial)
    assert EagerScheduler(state).run(on_event=recorder.observe).status=='completed'
    executed=tmp_path/'executed.html';recorder.write(executed)
    subprocess.run(['node',str(Path(__file__).with_name('replay_interaction_controls.cjs')),str(executed),str(initial)],
                   check=True,capture_output=True,text=True)
