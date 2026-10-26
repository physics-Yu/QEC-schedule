"""Plot measured component scaling and an explicit vertical factory layout."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


def main() -> None:
    """Read a completed survey and save standalone scientific PNG figures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("survey", type=Path)
    args = parser.parse_args()
    records = json.loads((args.survey / "summary.json").read_text(encoding="utf-8"))[
        "records"
    ]
    rows = [row["result"] for row in records if row["status"] == "passed"]
    fig, axes = plt.subplots(2, 2, figsize=(10, 7), constrained_layout=True)
    for ax, operation in zip(
        axes.flat, ("se_round", "logical_s", "raw_t", "transversal_cnot"), strict=True
    ):
        selected = [row for row in rows if row["operation"] == operation]
        for count in sorted({row["parameters"]["pipelines"] for row in selected}):
            cells = sorted(
                (row for row in selected if row["parameters"]["pipelines"] == count),
                key=lambda row: row["parameters"]["distance"],
            )
            ax.plot(
                [row["parameters"]["distance"] for row in cells],
                [row["metrics"]["execution_duration_us"] / 1000 for row in cells],
                marker="o",
                label=f"N={count}, bottom row",
            )
        ax.set(title=operation, xlabel="Code distance d", ylabel="Component time (ms)")
        ax.grid(alpha=0.25)
        if selected:
            ax.legend(fontsize=8)
        else:
            ax.text(
                0.5,
                0.5,
                "No successful calibration",
                ha="center",
                transform=ax.transAxes,
            )
    fig.suptitle(
        "Component calibration in complete worlds\n"
        "Not factory throughput or output-error scaling",
        fontsize=13,
    )
    fig.savefig(args.survey / "component-scaling.png", dpi=180)
    plt.close(fig)

    world = json.loads(
        (args.survey / "representative-world.json").read_text(encoding="utf-8")
    )
    distance, pipelines = (
        world["parameters"][key] for key in ("distance", "pipelines")
    )
    atoms = {atom["id"]: atom["position"] for atom in world["entry_state"]["atoms"]}
    bounds = world["device"]["aods"][0]["workspace"]
    fig, ax = plt.subplots(figsize=(11, 7), constrained_layout=True)
    ax.axhspan(50, bounds["y_max"], color="#d7edf7", label="Unbounded readout: y >= 50")
    ax.axhspan(
        bounds["y_min"], 0, color="#eef4e7", label="Unbounded gates/storage: y <= 0"
    )
    ax.axhline(0, color="#666", linewidth=0.8)
    ax.axhline(50, color="#666", linewidth=0.8)
    for patch in world["patches"]:
        positions = [atoms[atom] for atom in patch["binding"]["atom_ids"]]
        xs, ys = ([p[key] for p in positions] for key in ("x", "y"))
        x, y, width, height = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
        ax.add_patch(
            Rectangle(
                (x, y), width, height, fill=False, linewidth=1, edgecolor="#315370"
            )
        )
        ax.text(
            x + width / 2,
            y + height / 2,
            f"F{patch['factory_index']}: {patch['role']}",
            ha="center",
            va="center",
            fontsize=8,
        )
    ax.annotate(
        "50 um transport-only gap",
        xy=((bounds["x_min"] + bounds["x_max"]) / 2, 25),
        ha="center",
        fontsize=9,
    )
    ax.set(
        xlim=(bounds["x_min"], bounds["x_max"]),
        ylim=(bounds["y_min"], bounds["y_max"]),
        xlabel="x (um)",
        ylabel="y (um)",
        title=f"Captured d={distance}, N={pipelines} layout: factories top to bottom",
    )
    ax.set_aspect("equal")
    ax.legend(loc="upper right", fontsize=8)
    fig.savefig(args.survey / "vertical-layout.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
