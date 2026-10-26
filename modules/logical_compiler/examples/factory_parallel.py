"""Compare declared component batching with a same-device serial frontier.

The first initial raw attempts share one physical start. Only failed preparations
are resubmitted. Proxy probabilities remain code-owned and logical success stays
unknown. This entry does not introduce inventory, prefetch or factory concurrency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.rotated_surface_d3.protocols.factory_world import (
    FactoryWorldConfig,
    make_factory_world,
)
from modules.logical_compiler.examples.factory_proxy import (
    ProxyRun,
    _source_hashes,
    run_proxy_case,
)
from modules.logical_compiler.src.scheduling import ComponentScheduler

DEFAULT_CONFIG = (
    Path(__file__).resolve().parents[1] / "configs/factory_parallel_reference.json"
)


def load_configuration(
    document: Mapping[str, Any],
) -> tuple[FactoryWorldConfig, int | None]:
    """Validate an explicit code entry, Device inventory and parallelism limit."""
    if (
        set(document) != {"schema", "code", "world", "max_parallel"}
        or document["schema"] != "nadit.factory_component_schedule/1"
        or document["code"] != "rotated_surface_d3"
    ):
        raise ValueError(
            "INVALID_PARALLEL_CONFIG: explicit supported code and schema required"
        )
    world = document["world"]
    if (
        not isinstance(world, dict)
        or set(world) != {"aod_ids", "role_aod_ids", "block_spacing_columns"}
        or not isinstance(world["aod_ids"], list)
        or not isinstance(world["role_aod_ids"], dict)
    ):
        raise ValueError("INVALID_PARALLEL_CONFIG: explicit AOD allocation required")
    maximum = document["max_parallel"]
    ComponentScheduler(max_parallel=maximum)
    return FactoryWorldConfig(
        aod_ids=tuple(world["aod_ids"]),
        role_aod_ids=tuple(world["role_aod_ids"].items()),
        block_spacing_columns=world["block_spacing_columns"],
    ), maximum


def run_scheduled_case(
    seed: int,
    noise_params: Mapping[str, Any],
    output: str | Path,
    *,
    mode: Literal["serial", "parallel"],
    configuration: Mapping[str, Any],
) -> ProxyRun:
    """Run one complete finite factory case through the chosen component policy.

    Both modes use identical code, Device and seeded event identities. The code
    validates participant projections before assigning noisy parallel raw events.
    Existing output paths are refused by the standard exporter.
    """
    from modules.codes.rotated_surface_d3.protocols.parallel_backend import (
        SurfaceParallelCostBackend,
    )

    config, maximum = load_configuration(configuration)
    world = make_factory_world(config)
    return run_proxy_case(
        seed,
        noise_params,
        output,
        world=world,
        backend=SurfaceParallelCostBackend(world.device),
        scheduler=ComponentScheduler(mode=mode, max_parallel=maximum),
    )


def run_comparison(
    seed: int,
    noise_params: Mapping[str, Any],
    output: str | Path,
    *,
    configuration: Mapping[str, Any],
) -> dict[str, Any]:
    """Freeze, compile both policies and replay parallel once; export comparison.

    Success requires a real parallel initial wave, a local rejection/retry,
    completed unique output consumption and matching repeated static case bytes.
    Proxy false is allowed; it never means the selected actions failed to compile.
    """
    from modules.logical_compiler.examples.parallel_report import (
        write_parallel_comparison,
    )

    destination = Path(output).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    frozen = _source_hashes()
    runs = {}
    policies: tuple[tuple[str, Literal["serial", "parallel"]], ...] = (
        ("serial", "serial"),
        ("parallel", "parallel"),
        ("parallel-replay", "parallel"),
    )
    for name, mode in policies:
        if _source_hashes() != frozen:
            raise ValueError("EXPERIMENT_SOURCE_CHANGED")
        print(f"Compiling {name}, seed={seed}", flush=True)
        run = run_scheduled_case(
            seed,
            noise_params,
            destination / name,
            mode=mode,
            configuration=configuration,
        )
        if run.case.status != "complete":
            raise ValueError(
                f"SCHEDULED_CASE_INCOMPLETE: {name}: {run.case.to_dict()['failure']}"
            )
        if run.manifest["source_stable"] is not True:
            raise ValueError("EXPERIMENT_SOURCE_CHANGED")
        runs[name] = run
    if _source_hashes() != frozen:
        raise ValueError("EXPERIMENT_SOURCE_CHANGED")
    left = (destination / "parallel/case.json").read_bytes()
    right = (destination / "parallel-replay/case.json").read_bytes()
    if left != right:
        raise ValueError("PARALLEL_REPLAY_DIFFERED")
    serial, parallel = (runs[name].case.to_dict() for name in ("serial", "parallel"))
    for key in ("device", "entry_state"):
        if serial["physical"][key] != parallel["physical"][key]:
            raise ValueError(f"COMPARISON_PHYSICAL_INPUT_MISMATCH: {key}")
    if serial["reference_parameters"] != parallel["reference_parameters"]:
        raise ValueError("COMPARISON_NOISE_INPUT_MISMATCH")
    configured_aods = configuration["world"]["aod_ids"]
    actual_aods = [aod["id"] for aod in parallel["physical"]["device"]["aods"]]
    if actual_aods != configured_aods:
        raise ValueError("COMPARISON_AOD_INVENTORY_MISMATCH")
    raw_first = [
        c
        for c in parallel["calls"]
        if c["component_id"] == "raw_t_postselection"
        and "/initial/" in c["invocation_id"]
        and "/attempt[0]/" in c["invocation_id"]
    ]
    if len(raw_first) != 4 or len({c["start_us"] for c in raw_first}) != 1:
        raise ValueError("FOUR_INITIAL_RAW_STARTS_NOT_PARALLEL")
    first_ids = {call["invocation_id"] for call in raw_first}
    first_batch = next(
        (
            batch
            for batch in parallel["physical"]["parallel_batches"]
            if {member["invocation_id"] for member in batch["members"]} == first_ids
        ),
        None,
    )
    if first_batch is None or not first_batch["validation"]["ok"]:
        raise ValueError("INITIAL_RAW_BATCH_NOT_PHYSICALLY_VERIFIED")
    if len(actual_aods) == 1 and first_batch["mode"] != "shared_aod_lockstep":
        raise ValueError("INITIAL_RAW_BATCH_NOT_USING_SHARED_AOD")
    rejects = [
        e
        for e in parallel["events"]
        if "/initial/" in e["occurrence"]["invocation_id"]
        and e["values"].get("accepted") is False
    ]
    if not rejects:
        raise ValueError("ACCEPTANCE_WITNESS_HAS_NO_INITIAL_REJECTION")
    comparison = write_parallel_comparison(
        serial,
        parallel,
        destination,
        serial_evaluation=runs["serial"].evaluation,
        parallel_evaluation=runs["parallel"].evaluation,
    )
    acceptance = {
        "schema": "nadit.factory_parallel_acceptance/1",
        "seed": seed,
        "source_files_sha256": frozen,
        "device_sha256": canonical_hash(parallel["physical"]["device"]),
        "entry_world_sha256": canonical_hash(parallel["physical"]["entry_state"]),
        "configuration": dict(configuration),
        "aod_count": len(actual_aods),
        "aod_ids": actual_aods,
        "initial_batch_mode": first_batch["mode"],
        "noise_parameters": dict(noise_params),
        "parallel_case_sha256": hashlib.sha256(left).hexdigest(),
        "parallel_replay_byte_identical": True,
        "initial_raw_start_us": raw_first[0]["start_us"],
        "initial_raw_rejections": len(rejects),
        "physical_validation_ok": {
            name: run.case.physical is not None and run.case.physical.validation["ok"]
            for name, run in runs.items()
        },
        "logical_success": None,
    }
    (destination / "acceptance.json").write_text(
        json.dumps(acceptance, indent=2) + "\n", encoding="utf-8"
    )
    return comparison


def main(argv: list[str] | None = None) -> int:
    """Read explicit device/noise configuration and save one compared case."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--noise-params", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--seed", type=int, default=12909)
    parser.add_argument(
        "--mode", choices=("serial", "parallel", "compare"), default="compare"
    )
    args = parser.parse_args(argv)
    configuration = json.loads(args.config.read_text("utf-8"))
    params = json.loads(args.noise_params.read_text("utf-8"))
    if args.mode == "compare":
        run_comparison(args.seed, params, args.output, configuration=configuration)
        print("Compared and reproduced both completed schedules", flush=True)
        return 0
    run = run_scheduled_case(
        args.seed, params, args.output, mode=args.mode, configuration=configuration
    )
    print(
        json.dumps(
            {"status": run.case.status, "failure": run.case.to_dict()["failure"]}
        ),
        flush=True,
    )
    return 0 if run.case.status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
