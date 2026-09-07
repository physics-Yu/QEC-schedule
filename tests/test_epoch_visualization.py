"""R10 regression tests for trace-derived animation and timeline output."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

from qec_schedule.hardware import load_hardware_config
from qec_schedule.simulation import run_cycle
from qec_schedule.trace import frame_at
from qec_schedule.visualization.animation import create_matplotlib_animation, save_animation
from qec_schedule.visualization.timeline import save_timeline


@unittest.skipUnless(importlib.util.find_spec("matplotlib"), "Install the visualization extra")
class EpochVisualizationTests(unittest.TestCase):
    def test_visualizations_replay_the_epoch_trace(self):
        trace, _ = run_cycle(load_hardware_config(Path("configs/hardware_default.yaml")))
        rydberg = next(epoch for epoch in trace["epochs"] if epoch["type"] == "RYDBERG")
        frame = frame_at(trace, (rydberg["start_time"] + rydberg["end_time"]) / 2)
        self.assertEqual(len(frame["active_pairs"]), 6)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            html = save_animation(trace, directory / "animation.html")
            content = html.read_text(encoding="utf-8")
            self.assertIn("trace.epochs", content)
            self.assertIn("active_pairs", content)
            self.assertNotIn("trace.actions", content)
            timeline = save_timeline(trace, directory / "timeline.png")
            self.assertEqual(timeline.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            animation = create_matplotlib_animation(trace, frames=4)
            self.assertIsNotNone(animation)


if __name__ == "__main__":
    unittest.main()
