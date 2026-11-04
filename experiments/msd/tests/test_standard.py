"""Windows checkout line endings must preserve the MSD reference identity."""

from hashlib import sha256

from experiments.msd.standard import REFERENCE_PATH, ExperimentSpec, build_world


def test_world_reference_hash_matches_lf_source():
    canonical_bytes = REFERENCE_PATH.read_bytes().replace(b"\r\n", b"\n")
    world = build_world(ExperimentSpec(distance=3, pipelines=1)).document()
    assert world["reference_sha256"] == sha256(canonical_bytes).hexdigest()
