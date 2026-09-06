"""AOD acceptance case plus dependency-frontier inspection, NOT a scheduler."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from qec_schedule.hardware import Position, build_initial_state, load_hardware_config
from qec_schedule.lowering import GateLowerer, MoveRequest, MovementPlanner, SiteRef, TransportCatalog
from qec_schedule.qec import create_code


def ten_translations(timing):
    return tuple(MoveRequest.translation_request(
        f"demo/t{i}", f"demo/atom{i}", SiteRef("demo_source", f"demo/s{i}", Position(5+2*i, 5)),
        SiteRef("demo_target", f"demo/t{i}", Position(5+2*i, 15)), timing) for i in range(10))


def inspect_frontiers(plan, planner):
    """Complete eligible work symbolically to inspect later dependency frontiers.

    No zone capacity, competing laser, trajectory, duration, or event-time model
    is applied. Returned counts are inspection results, not scheduled epoch counts.
    """
    catalog = TransportCatalog(plan)
    done, frontiers = set(), []
    while len(done) < len(plan.actions):
        epochs = planner.plan_ready(catalog, done)
        local = [a.id for a in plan.actions if a.id not in done and a.id not in catalog.transport_action_ids
                 and set(a.dependencies) <= done]
        if not epochs and not local:
            raise RuntimeError("Dependency inspection made no progress")
        frontiers.append({"index": len(frontiers), "nontransport_actions": local,
                          "epochs": [e.to_dict() for e in epochs]})
        done.update(local)
        done.update(a for e in epochs for r in e.requests for a in r.action_ids)
    return catalog, frontiers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "configs/hardware_default.yaml")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    args = parser.parse_args()
    try:
        config = load_hardware_config(args.config)
        planner = MovementPlanner(config.aod)
        acceptance = planner.plan(ten_translations(config.timing))
        code = create_code()
        plan = GateLowerer(config.timing).lower(code.syndrome_round(rounds=args.rounds), build_initial_state(code, config))
        catalog, frontiers = inspect_frontiers(plan, planner)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "aod_epochs.json"
    payload = {"schema_version": 1, "kind": "aod_compatibility_inspection", "scheduled": False,
               "units": {"length": "um", "time": "us"}, "controller": config.aod.to_dict(),
               "ten_atom_acceptance": [e.to_dict() for e in acceptance],
               "transport_count": len(catalog.requests), "dependency_frontiers": frontiers,
               "original_reservations": [r.to_dict() for r in plan.reservations]}
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Acceptance: 10 equal-displacement atoms -> {len(acceptance)} epoch(s)")
    for epoch in acceptance:
        data = epoch.to_dict()
        print(f"  atoms={len(epoch.atoms)}, tones={data['tone_counts']}, duration={epoch.duration:g} us, AOD units=1")
    print(f"Surface-code requests: {len(catalog.requests)} transports")
    print(f"Dependency inspection: {len(frontiers)} frontiers, {sum(len(f['epochs']) for f in frontiers)} candidate epochs")
    print("NOT SCHEDULED: candidates retain site/zone reservations; no hardware execution time is reported.")
    print(f"Epochs: {output.resolve()}")


if __name__ == "__main__": main()
