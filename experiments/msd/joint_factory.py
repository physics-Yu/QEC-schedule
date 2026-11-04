"""Calibrate actual shared-AOD frontiers, freeze them, then run the fast kernel."""

import argparse
import json
from hashlib import sha256
from pathlib import Path
from statistics import fmean
from typing import Any

from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.rotated_surface.joint_factory_profile import (
    JointSurfaceFactoryProfile,
    joint_key,
)
from modules.logical_compiler.examples.surface_factory_fast import run_surface_factory

from .calibrate import source_snapshot
from .joint_factory_calibration import compile_joint_group
from .standard import ExperimentSpec, build_world


def joint_source_snapshot() -> dict[str, str]:
    """Include the logical scheduler and example adapter as campaign inputs."""
    snapshot = source_snapshot()
    root = Path(__file__).resolve().parents[2]
    for path in (root / "modules/logical_compiler").rglob("*.py"):
        if "tests" not in path.parts:
            snapshot[path.relative_to(root).as_posix()] = sha256(
                path.read_bytes()
            ).hexdigest()
    return snapshot


class CalibrationProfile(JointSurfaceFactoryProfile):
    """Explicit offline builder; it is never used for reported fast timings."""

    def __init__(
        self, document: dict[str, Any], *, output: Path, shots: int, seed: int
    ) -> None:
        super().__init__(document)
        self.world = build_world(ExperimentSpec(self.distance, self.factory_count))
        self.output, self.shots, self.seed = output, shots, seed

    def group(self, members: tuple[str, ...]) -> dict[str, Any]:
        key = joint_key(members)
        if key not in self.groups:
            path = self.output / f"{key}.group.json"
            if path.exists():
                self.groups[key] = json.loads(path.read_text(encoding="utf-8"))
                trace = json.loads(
                    (self.output / f"{key}.trace.json").read_text(encoding="utf-8")
                )
                if canonical_hash(trace) != self.groups[key]["trace_sha256"]:
                    raise ValueError("CACHED_JOINT_TRACE_HASH_MISMATCH")
            else:
                self.groups[key] = compile_joint_group(
                    self.world,
                    members,
                    family=self.joint_family,
                    noise_params=self.noise_params,
                    shots=self.shots,
                    seed=self.seed,
                    output=self.output,
                )
                print(
                    json.dumps(
                        {
                            "d": self.distance,
                            "N": self.factory_count,
                            "groups": len(self.groups),
                            "members": len(members),
                            "duration_us": sum(self.groups[key]["phase_durations_us"]),
                            "calibration_seconds": self.groups[key][
                                "calibration_wall_seconds"
                            ],
                        }
                    ),
                    flush=True,
                )
        return super().group(members)


def run_cell(
    base_profile: Path, output: Path, *, seeds: tuple[int, ...], shots: int = 65536
) -> None:
    """Record source-frozen joint coverage then execute identical seeds without compilation."""
    output.mkdir(parents=True, exist_ok=True)
    if (output / "summary.json").exists():
        raise ValueError("Completed experiment output already exists")
    snapshot = joint_source_snapshot()
    document = json.loads(base_profile.read_text(encoding="utf-8"))
    world = build_world(ExperimentSpec(document["distance"], document["factory_count"]))
    if document["world_sha256"] != canonical_hash(world.document()):
        raise ValueError("Base profile layout differs from the current agreed world")
    metadata = {
        "world": world.document(),
        "noise": document["noise_params"],
        "sources": snapshot,
        "acceptance_shots": shots,
        "acceptance_seed": 20261024,
    }
    document["joint_calibration"] = {
        "family": canonical_hash(metadata),
        "inputs": metadata,
        "limits": {"max_rows": None, "max_columns": None, "max_readout_atoms": None},
    }
    profile = CalibrationProfile(
        document, output=output / "groups", shots=shots, seed=20261024
    )
    for seed in seeds:
        run_surface_factory(profile, seed=seed, input_z_error=0.01)
    if joint_source_snapshot() != snapshot:
        raise ValueError("Joint calibration sources changed during experiment")
    frozen = profile.to_dict()
    (output / "profile.json").write_text(
        json.dumps(frozen, separators=(",", ":")), encoding="utf-8"
    )
    fast = JointSurfaceFactoryProfile(frozen)
    samples = []
    for seed in seeds:
        result = run_surface_factory(fast, seed=seed, input_z_error=0.01)
        samples.append(result["summary"])
        if seed == seeds[0]:
            (output / "case.json").write_text(
                json.dumps(result["case"], separators=(",", ":")), encoding="utf-8"
            )
    elapsed = sum(s["makespan_us"] for s in samples)
    summary = {
        "distance": fast.distance,
        "factory_count": fast.factory_count,
        "seeds": seeds,
        "hardware": "one shared AOD; original standard/2",
        "mean_makespan_us": fmean(s["makespan_us"] for s in samples),
        "outputs": sum(s["outputs"] for s in samples),
        "outputs_per_second": sum(s["outputs"] for s in samples) * 1e6 / elapsed,
        "mean_fast_seconds": fmean(s["software_wall_seconds"] for s in samples),
        "joint_calibrations": len(fast.groups),
        "source_snapshot_sha256": canonical_hash(snapshot),
        "profile_sha256": fast.profile_sha256,
        "samples": samples,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "samples"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(16)))
    parser.add_argument("--shots", type=int, default=65536)
    args = parser.parse_args()
    run_cell(args.base_profile, args.output, seeds=tuple(args.seeds), shots=args.shots)
