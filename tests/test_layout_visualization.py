import importlib.util
from pathlib import Path
import tempfile
import unittest

from qec_schedule.hardware import build_initial_state, load_hardware_config
from qec_schedule.qec import create_code
from qec_schedule.visualization.layout import create_layout_figure, save_layout


@unittest.skipUnless(importlib.util.find_spec("matplotlib"), "Install the visualization extra")
class LayoutTests(unittest.TestCase):
    def test_all_atoms_zones_and_labels_render_without_mutating_state(self):
        config = Path(__file__).resolve().parents[1] / "configs/hardware_default.yaml"
        state = build_initial_state(create_code(), load_hardware_config(config))
        before = state.to_dict()
        figure = create_layout_figure(state)
        axis = figure.axes[0]
        self.assertEqual(len(axis.patches), 4)
        self.assertTrue(axis.yaxis_inverted())
        labels = {text.get_text() for text in axis.texts}
        for atom in state.atoms:
            self.assertIn(atom.assigned_qubit or atom.atom_id, labels)
        self.assertEqual(len(axis.lines), 3)  # Two interaction lanes plus the imaging FOV.
        with tempfile.TemporaryDirectory() as directory:
            output = save_layout(state, Path(directory) / "layout.png")
            self.assertEqual(output.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertGreater(output.stat().st_size, 10000)
        self.assertEqual(state.to_dict(), before)
