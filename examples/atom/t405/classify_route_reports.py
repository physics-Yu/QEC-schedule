"""Read-only attribution of frozen candidate-to-motion reports; no compilation."""
import argparse
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True); parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    compressed = args.plan.read_bytes(); raw_report = args.report.read_bytes()
    plan = json.loads(gzip.decompress(compressed)); report = json.loads(raw_report)
    ids = {f["source_id"] for f in report["failures"] if f["code"] == "ENOLA_ROUTE_MOTION_UNUSED"}
    actions = {a["id"]: a for a in plan["atom_program"]["actions"]}
    classified = []
    for receipt in plan["enola"]["route_decisions"]:
        if not receipt.get("accepted"): continue
        pulse = actions[receipt["pulse_action_id"]]
        for index in receipt["selected_indices"]:
            candidate = receipt["candidates"][index]
            if candidate["op_id"] not in ids: continue
            legs = []
            for aid in receipt["action_ids"]:
                action = actions[aid]
                if action["kind"] != "move" or action["t_end_us"] > pulse["t_start_us"]: continue
                for tr in action["payload"]["trajectories"]:
                    if tr["atom_id"] == candidate["mover"]:
                        legs.append({"action_id": aid, "from_um": tr["from_um"], "to_um": tr["to_um"],
                                     "t_start_us": action["t_start_us"], "t_end_us": action["t_end_us"]})
            legs.sort(key=lambda x: (x["t_start_us"], x["t_end_us"], x["action_id"]))
            point = candidate["from_um"]; previous_end = -1.; continuous = True
            for leg in legs:
                continuous &= leg["from_um"] == point and leg["t_start_us"] >= previous_end
                point, previous_end = leg["to_um"], leg["t_end_us"]
            endpoint = point == candidate["to_um"]
            kind = ("zero_displacement" if not legs else "single_segment" if len(legs) == 1 else "continuous_multisegment") if continuous and endpoint else "actual_unresolved_mismatch"
            drops = [{"action_id": aid, "position_um": b["position_um"]} for aid in receipt["action_ids"]
                     for a in [actions[aid]] if a["kind"] == "drop" and a["t_end_us"] <= pulse["t_start_us"]
                     for b in a["payload"]["bindings"] if b["atom_id"] == candidate["mover"]]
            classified.append({"source_id": candidate["op_id"], "candidate_index": index, "candidate": candidate,
                               "pulse_action_id": pulse["id"], "pulse_start_us": pulse["t_start_us"], "classification": kind,
                               "continuous": continuous, "endpoint_matches": endpoint, "legs": legs, "pre_pulse_drops": drops,
                               "single_leg_direct_match": any(l["from_um"] == candidate["from_um"] and l["to_um"] == candidate["to_um"] for l in legs)})
    result = {"schema_version": "R4FrozenRouteAttribution/0.1", "source_report_sha256": sha256(raw_report).hexdigest(),
              "physical_plan_byte_sha256": sha256(compressed).hexdigest(), "requested_sources": len(ids), "classified_sources": len(classified),
              "classes": dict(Counter(r["classification"] for r in classified)), "records": classified,
              "recompiled": False, "search_calls": 0, "source_unchanged": args.plan.read_bytes() == compressed and args.report.read_bytes() == raw_report,
              "original_router_return_provenance": "still_unverified_in_frozen_observer", "acceptance_owner": "R6",
              "interpretation": "A continuous polyline may have no single direct from-to segment; this does not relax global geometry or pulse checks."}
    args.out.write_bytes((json.dumps(result, ensure_ascii=False, indent=2)+"\n").encode())
    print(json.dumps({k: v for k, v in result.items() if k != "records"}, ensure_ascii=False))
    if len(classified) != len(ids) or result["classes"].get("actual_unresolved_mismatch") or not result["source_unchanged"]: raise SystemExit(2)


if __name__ == "__main__": main()
