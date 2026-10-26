"""Small actual calibration and fast factory handoff, without a noise campaign."""

from experiments.msd.calibrate_factory import calibrate_factory
from modules.codes.rotated_surface.fast_factory import required_variants
from modules.logical_compiler.examples.surface_factory_fast import run_surface_factory


def test_d3_actual_calibration_matches_frozen_timing_and_fast_handoff(tmp_path):
    profile = calibrate_factory(
        3, 1, noise_params={}, output=tmp_path / "profile", shots=16
    )
    doc = profile.to_dict()
    assert doc["timing"] == {
        "load_us": 10,
        "store_us": 10,
        "measure_us": 100,
        "result_processing_us": 0,
    }
    assert len(profile.entries) == len(required_variants(3))
    raw = profile.entries["raw_t_postselection:factory0/R"]
    assert raw.claim["result_count"] == 24
    assert abs(raw.action_duration_us - 2374.4524714035933) < 1e-7
    result = run_surface_factory(profile, seed=0, input_z_error=0)
    assert result["summary"]["outputs"] == 1
    assert result["summary"]["raw_attempts"] == 15
    assert result["summary"]["makespan_us"] > 15 * raw.action_duration_us
