"""Accepted reports must remain bound to their audited committed recording."""
import hashlib
import json

import pytest

from neutral_atom_experiments.qec_pbc.native_parallel_report import render_report


def report_inputs(directory, *, replay=True, replace_recording=False):
    original = b'{"operations":[]}'
    (directory/'recording.json').write_bytes(original + (b'\n' if replace_recording else b''))
    (directory/'summary.json').write_text(json.dumps({
        'status': 'completed', 'audit': {'independent_plan_replay_equal': replay}}))
    (directory/'independent-audit.json').write_text(json.dumps({
        'passed': True, 'artifact_sha256': {'recording.json': hashlib.sha256(original).hexdigest()}}))


def test_completed_label_cannot_hide_skipped_original_state_replay(tmp_path):
    report_inputs(tmp_path, replay=None)
    with pytest.raises(ValueError, match='original-state replay'):
        render_report(tmp_path)


def test_recording_replacement_cannot_reuse_stale_independent_acceptance(tmp_path):
    report_inputs(tmp_path, replace_recording=True)
    with pytest.raises(ValueError, match='independently audited artifact'):
        render_report(tmp_path)
