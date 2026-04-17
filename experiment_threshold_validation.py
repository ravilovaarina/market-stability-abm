"""
experiment_threshold_validation.py
==================================

Small follow-up analysis for validating the 30% tipping-point rule
on top of the existing unified experiment raw results.

Goal:
1. Reuse existing unified raw CSV files, without running new simulations.
2. Compare several qualitatively different regimes.
3. Show how the estimated tipping point phi* changes when the threshold
   moves from 1.1x to 1.5x of the baseline.

Recommended regimes:
- speed x2: key clean result
- speed x3, lag=1: strong combined result
- speed x3, lag=5: regime with no tipping at 1.3x
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


THRESHOLDS = [1.1, 1.2, 1.3, 1.4, 1.5]


@dataclass(frozen=True)
class Regime:
    name: str
    grid: str
    speed_mult: int
    info_lag: int
    note: str


REGIMES = [
    Regime(
        name="speed_x2",
        grid="speed",
        speed_mult=2,
        info_lag=0,
        note="Key clean speed regime",
    ),
    Regime(
        name="combined_speed_x3_lag1",
        grid="combined",
        speed_mult=3,
        info_lag=1,
        note="Strong combined regime with stable tipping",
    ),
    Regime(
        name="combined_speed_x3_lag5",
        grid="combined",
        speed_mult=3,
        info_lag=5,
        note="Combined regime where 1.3x tipping disappears",
    ),
]


def load_raw(base_dir: str) -> pd.DataFrame:
    path = os.path.join(base_dir, "unified_all_raw.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Cannot find {path}. Run experiment_unified.py first or place unified_all_raw.csv in the repo."
        )
    return pd.read_csv(path)


def subset_regime(df: pd.DataFrame, regime: Regime) -> pd.DataFrame:
    sub = df[
        (df["grid"] == regime.grid)
        & (df["speed_mult"] == regime.speed_mult)
        & (df["info_lag"] == regime.info_lag)
    ].copy()
    if sub.empty:
        raise ValueError(f"No data found for regime {regime}")
    return sub


def aggregate_means(sub: pd.DataFrame, metric: str = "vol_ratio") -> pd.DataFrame:
    return (
        sub.groupby("hft_frac")[metric]
        .agg(["mean", "std", "count"])
        .reset_index()
        .sort_values("hft_frac")
    )


def find_tipping_point(agg: pd.DataFrame, threshold_multiplier: float) -> float | None:
    baseline = agg.loc[agg["hft_frac"] == 0.0, "mean"]
    if baseline.empty:
        return None

    threshold = float(baseline.iloc[0]) * threshold_multiplier
    for _, row in agg.iterrows():
        if row["hft_frac"] == 0.0:
            continue
        if row["mean"] >= threshold:
            return float(row["hft_frac"])
    return None


def analyze_regime(sub: pd.DataFrame, regime: Regime) -> tuple[pd.DataFrame, dict[float, float | None]]:
    agg = aggregate_means(sub, metric="vol_ratio")
    tipping = {mult: find_tipping_point(agg, mult) for mult in THRESHOLDS}
    return agg, tipping


def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for regime in REGIMES:
        sub = subset_regime(df, regime)
        agg, tipping = analyze_regime(sub, regime)
        baseline = float(agg.loc[agg["hft_frac"] == 0.0, "mean"].iloc[0])
        row = {
            "regime": regime.name,
            "grid": regime.grid,
            "speed_mult": regime.speed_mult,
            "info_lag": regime.info_lag,
            "baseline_vol_ratio": baseline,
            "note": regime.note,
        }
        for mult, phi_star in tipping.items():
            row[f"phi_star_{mult:.1f}x"] = phi_star
        rows.append(row)
    return pd.DataFrame(rows)


def plot_threshold_validation(df: pd.DataFrame, out_path: str) -> None:
    fig, axes = plt.subplots(1, len(REGIMES), figsize=(16, 4.8), sharey=True)
    colors = plt.cm.viridis(np.linspace(0.2, 0.8, len(THRESHOLDS)))

    for ax, regime in zip(axes, REGIMES):
        sub = subset_regime(df, regime)
        agg, tipping = analyze_regime(sub, regime)
        baseline = float(agg.loc[agg["hft_frac"] == 0.0, "mean"].iloc[0])

        ax.plot(agg["hft_frac"], agg["mean"], "o-", color="black", lw=2, label="mean vol_ratio")

        for color, mult in zip(colors, THRESHOLDS):
            threshold = baseline * mult
            label = f"{mult:.1f}x baseline"
            ax.axhline(threshold, color=color, ls="--", lw=1.4, alpha=0.9, label=label)
            phi_star = tipping[mult]
            if phi_star is not None:
                ax.axvline(phi_star, color=color, ls=":", lw=1.2, alpha=0.9)

        title = regime.name.replace("_", " ")
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("HFT fraction (phi)")
        ax.grid(alpha=0.25)

        text_lines = [f"baseline={baseline:.2f}"]
        text_lines.extend(
            f"{mult:.1f}x -> phi*={tipping[mult] if tipping[mult] is not None else '—'}"
            for mult in THRESHOLDS
        )
        ax.text(
            0.02,
            0.98,
            "\n".join(text_lines),
            transform=ax.transAxes,
            va="top",
            ha="left",
            fontsize=8,
            bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "0.8"},
        )

    axes[0].set_ylabel("Mean vol_ratio")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, frameon=False)
    fig.suptitle(
        "Threshold validation: how estimated tipping point phi* changes with the threshold",
        fontsize=13,
        fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.9])
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_phi_star_heatmap(summary: pd.DataFrame, out_path: str) -> None:
    cols = [f"phi_star_{mult:.1f}x" for mult in THRESHOLDS]
    labels = [f"{mult:.1f}x" for mult in THRESHOLDS]
    plot_df = summary.set_index("regime")[cols].copy()

    data = plot_df.to_numpy(dtype=float)
    masked = np.ma.masked_invalid(data)

    fig, ax = plt.subplots(figsize=(8.5, 3.8))
    im = ax.imshow(masked, aspect="auto", cmap="YlGnBu", vmin=0.0, vmax=1.0)

    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_yticks(range(len(plot_df.index)))
    ax.set_yticklabels([idx.replace("_", " ") for idx in plot_df.index])
    ax.set_xlabel("Threshold")
    ax.set_title("Estimated tipping point phi* across thresholds", fontsize=12, fontweight="bold")

    for i in range(masked.shape[0]):
        for j in range(masked.shape[1]):
            val = data[i, j]
            text = "—" if np.isnan(val) else f"{val:.1f}"
            ax.text(j, i, text, ha="center", va="center", color="black", fontsize=10, fontweight="bold")

    plt.colorbar(im, ax=ax, fraction=0.05, label="phi*")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def format_phi(value: float | None) -> str:
    return "—" if value is None or pd.isna(value) else f"{value:.1f}"


def write_markdown_report(summary: pd.DataFrame, out_path: str) -> None:
    lines = [
        "# Threshold Validation Report",
        "",
        "This report validates whether the 30% rule (`1.3x baseline`) is a reasonable",
        "working definition of a tipping point across several representative regimes.",
        "",
        "Selected regimes:",
    ]
    for regime in REGIMES:
        lines.append(
            f"- `{regime.name}`: grid=`{regime.grid}`, speed_mult=`{regime.speed_mult}`, "
            f"info_lag=`{regime.info_lag}`. {regime.note}."
        )

    lines.extend(
        [
            "",
            "## Summary table",
            "",
            "| Regime | Baseline vol_ratio | 1.1x | 1.2x | 1.3x | 1.4x | 1.5x |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )

    for _, row in summary.iterrows():
        lines.append(
            "| "
            + f"{row['regime']} | {row['baseline_vol_ratio']:.2f} | "
            + f"{format_phi(row['phi_star_1.1x'])} | "
            + f"{format_phi(row['phi_star_1.2x'])} | "
            + f"{format_phi(row['phi_star_1.3x'])} | "
            + f"{format_phi(row['phi_star_1.4x'])} | "
            + f"{format_phi(row['phi_star_1.5x'])} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `1.3x` should not be presented as a mathematically unique threshold.",
            "- It can be presented as the main working threshold because it is stricter than `1.1x` and `1.2x`,",
            "  which often trigger very early crossings, but less restrictive than `1.5x`, which can remove",
            "  tipping points even in meaningful regimes.",
            "- The strongest empirical justification comes from `speed_x2`.",
            "- The combined regimes show that the same threshold remains interpretable outside the clean speed-only setup,",
            "  but not every regime produces a tipping point at `1.3x`.",
        ]
    )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    df = load_raw(base_dir)

    summary = build_summary(df)

    csv_out = os.path.join(base_dir, "threshold_validation_summary.csv")
    plot_out = os.path.join(base_dir, "threshold_validation.png")
    heatmap_out = os.path.join(base_dir, "threshold_validation_heatmap.png")
    md_out = os.path.join(base_dir, "threshold_validation_report.md")

    summary.to_csv(csv_out, index=False)
    plot_threshold_validation(df, plot_out)
    plot_phi_star_heatmap(summary, heatmap_out)
    write_markdown_report(summary, md_out)

    print("Saved:")
    print(f"  {csv_out}")
    print(f"  {plot_out}")
    print(f"  {heatmap_out}")
    print(f"  {md_out}")
    print("\nSummary:")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
