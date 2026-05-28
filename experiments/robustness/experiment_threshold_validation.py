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
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/1d-abm-mplconfig")
os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


THRESHOLDS = [1.1, 1.2, 1.3, 1.4, 1.5]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "results" / "h1" / "raw"
TABLE_DIR = PROJECT_ROOT / "results" / "h1" / "robustness" / "tables"
FIGURE_DIR = PROJECT_ROOT / "results" / "h1" / "robustness" / "figures"
TABLE_DIR.mkdir(parents=True, exist_ok=True)
FIGURE_DIR.mkdir(parents=True, exist_ok=True)


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


def load_raw() -> pd.DataFrame:
    path = RAW_DIR / "unified_all_raw.csv"
    if not path.exists():
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


def main() -> None:
    df = load_raw()

    summary = build_summary(df)

    csv_out = TABLE_DIR / "threshold_validation_summary.csv"
    plot_out = FIGURE_DIR / "threshold_validation.png"
    heatmap_out = FIGURE_DIR / "threshold_validation_heatmap.png"

    summary.to_csv(csv_out, index=False)
    plot_threshold_validation(df, plot_out)
    plot_phi_star_heatmap(summary, heatmap_out)

    print("Saved:")
    print(f"  {csv_out}")
    print(f"  {plot_out}")
    print(f"  {heatmap_out}")
    print("\nSummary:")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
