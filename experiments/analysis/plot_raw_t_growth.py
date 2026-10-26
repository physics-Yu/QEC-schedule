"""Plot saved MSD summaries without importing or changing compiler sources."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main() -> None:
    """Save scaling and a representative geometric deformation layout."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = json.loads(args.summary.read_text(encoding="utf-8"))["cases"]
    distances = [c["distance"] for c in cases]
    acceptance = [c["probabilities"]["illustrative"]["acceptance"] for c in cases]
    injection = [
        c["injection_metrics"]["execution_duration_us"] / p / 1000
        for c, p in zip(cases, acceptance, strict=True)
    ]
    growth = [
        0
        if c["growth_metrics"] is None
        else c["growth_metrics"]["execution_duration_us"] / 1000
        for c in cases
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.5), layout="constrained")
    axes[0].plot(distances, acceptance, "o-", color="#176b9c")
    axes[0].set(
        xlabel="Target distance",
        ylabel="Injection acceptance",
        ylim=(0, 1),
        xticks=distances,
    )
    for d, p in zip(distances, acceptance, strict=True):
        axes[0].annotate(
            f"{100 * p:.2f}%",
            (d, p),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
        )
    axes[1].bar(
        distances, injection, label="Injection including retries", color="#176b9c"
    )
    axes[1].bar(
        distances, growth, bottom=injection, label="Growth once", color="#dd9039"
    )
    axes[1].set(
        xlabel="Target distance",
        ylabel="Expected time per output (ms)",
        xticks=distances,
    )
    axes[1].legend(fontsize=8)
    fig.suptitle(
        "Fixed d3 injection: three postselected rounds; ordinary target growth"
    )
    fig.savefig(args.output / "small-injection-growth-scaling.png", dpi=180)
    fig.savefig(args.output / "small-injection-growth-scaling.svg")
    plt.close(fig)

    d = max(distances)
    fig, ax = plt.subplots(figsize=(5, 6), layout="constrained")
    ax.axhspan(50, 85, color="#e5f1e6", label="Readout: upper half-plane")
    ax.axhspan(-2 * d * 10, 0, color="#f2f3f5")
    groups = {
        "d3 injected data": ([], [], "#176b9c"),
        "New |+> data": ([], [], "#dd9039"),
        "New |0> data": ([], [], "#715ba6"),
    }
    for row in range(d):
        for col in range(d):
            key = (
                "d3 injected data"
                if row >= d - 3 and col < 3
                else "New |+> data"
                if row < d - 3
                else "New |0> data"
            )
            xs, ys, _ = groups[key]
            xs.append((2 * col + 1) * 10)
            ys.append((2 * row + 1 - 2 * d) * 10)
    for label, (xs, ys, color) in groups.items():
        ax.scatter(xs, ys, color=color, s=45, label=label)
    ax.annotate("50 um gap", (2 * d * 10 - 10, 25), ha="right", va="center")
    ax.axhline(0, color="#777777", linewidth=0.8)
    ax.axhline(50, color="#777777", linewidth=0.8)
    ax.set(
        xlabel="Local x (um)",
        ylabel="Device y (um)",
        title=f"Target d={d}: data initialization regions",
        xlim=(0, 2 * d * 10),
        ylim=(-2 * d * 10, 85),
        aspect="equal",
    )
    ax.legend(loc="upper right", fontsize=8)
    fig.savefig(args.output / "small-injection-growth-layout.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
