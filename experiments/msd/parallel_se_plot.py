"""Plot actual joint-SE makespan, same-layout controls, and an execution trace."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from nadit_physical_compiler.atom_ir import CZPulse, Load, Measure, Move, Reset, Store
from nadit_physical_compiler.serialization import decode_result


def main() -> None:
    """Read saved results only; do not recompute geometry or scheduling."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("survey", type=Path)
    args = parser.parse_args()
    summary = json.loads((args.survey / "summary.json").read_text(encoding="utf-8"))
    rows = [c for c in summary["comparisons"] if "joint_round_us" in c]
    distances = sorted({r["parameters"]["distance"] for r in rows})
    if not distances:
        raise ValueError("No complete parallel-SE comparisons available to plot.")
    fig, axes = plt.subplots(
        2,
        len(distances),
        figsize=(4.3 * len(distances), 7.2),
        squeeze=False,
        constrained_layout=True,
    )
    for column, distance in enumerate(distances):
        data = sorted(
            (r for r in rows if r["parameters"]["distance"] == distance),
            key=lambda r: r["parameters"]["pipelines"],
        )
        ns = [r["parameters"]["pipelines"] for r in data]
        ax = axes[0, column]
        for field, label, marker in (
            ("joint_round_us", "Actual joint SE", "o"),
            ("slowest_solo_us", "Slowest solo reference", "x"),
            ("serial_round_us", "Actual serial control", "s"),
        ):
            ax.plot(ns, [r[field] / 1000 for r in data], marker=marker, label=label)
        ax.set(
            title=f"d={distance}",
            xlabel="Factories N",
            ylabel="Whole-round time (ms)",
            xticks=ns,
        )
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8)
        ax = axes[1, column]
        for field, label in (
            ("position_effect_us", "Solo position effect"),
            ("net_joint_effect_us", "Net joint-scheduling effect"),
        ):
            ax.plot(ns, [r[field] / 1000 for r in data], marker="o", label=label)
        ax.axhline(0, color="black", linewidth=0.7)
        ax.set(xlabel="Factories N", ylabel="Signed time contribution (ms)", xticks=ns)
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8)
    fig.suptitle(
        "One W1 SE per factory, one complete world, one shared AOD\n"
        "Same layout/timing in joint and control runs",
        fontsize=13,
    )
    fig.savefig(args.survey / "parallel-se-scaling.png", dpi=180)
    plt.close(fig)

    # Actual action source IDs distinguish participants from ambient illumination.
    d = min(distances)
    n = max(
        r["parameters"]["pipelines"] for r in rows if r["parameters"]["distance"] == d
    )
    document = json.loads(
        (args.survey / f"d{d}-n{n}-joint.result.json").read_text(encoding="utf-8")
    )
    result = decode_result(document)
    node_owners = document["se_instances"]["node_owners"]
    wires = document["entry_state"]["qubit_to_atom"]
    atom_owners = {atom: i // (2 * d * d - 1) for i, atom in enumerate(wires)}
    colors = {
        "transport": "#4477aa",
        "CZ": "#cc6677",
        "readout": "#228833",
        "reset": "#aa3377",
        "local": "#ddaa33",
    }
    fig, ax = plt.subplots(figsize=(11, 2.2 + 0.6 * n), constrained_layout=True)
    for start, step in result.program.timeline():
        for action in step.actions:
            if isinstance(action, Load | Store):
                owners = {atom_owners.get(b[0], -1) for b in action.bindings}
                category = "transport"
            elif isinstance(action, Move):
                owners = {atom_owners.get(a, -1) for a, _ in action.targets}
                category = "transport"
            else:
                owners = {node_owners[i] for i in action.source_ids}
                category = (
                    "CZ"
                    if isinstance(action, CZPulse)
                    else "readout"
                    if isinstance(action, Measure)
                    else "reset"
                    if isinstance(action, Reset)
                    else "local"
                )
            for owner in owners - {-1}:
                ax.broken_barh(
                    [(start / 1000, action.duration_us / 1000)],
                    (owner - 0.34, 0.68),
                    facecolors=colors[category],
                    linewidth=0,
                )
    ax.set(
        yticks=list(range(n)),
        yticklabels=[f"Factory {i}: W1" for i in range(n)],
        xlabel="Actual global time (ms)",
        ylim=(-0.65, n - 0.35),
        title=f"Joint d={d}, N={n} SE: participant actions; spectator light excluded",
    )
    ax.invert_yaxis()
    ax.legend(
        handles=[Patch(color=c, label=k) for k, c in colors.items()],
        ncol=5,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        fontsize=9,
    )
    fig.savefig(args.survey / "parallel-se-timeline.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
