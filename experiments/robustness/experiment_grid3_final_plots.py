"""
experiment_grid3_final_plots.py
===============================

Plot the final Unified Experiment Grid 3 results.

This script does not run simulations. It reads the final combined-grid output
from `unified_combined_raw.csv` and creates:
- `unified_combined_metrics.png`
- `unified_combined_heatmap.png`
- `unified_combined_tipping.csv`
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("MPLCONFIGDIR", "/tmp/1d-abm-mplconfig")
os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from experiments.paths import result_path


METRICS = [
    ("vol_ratio", "Volatility ratio (after/before)"),
    ("spread_ratio", "Spread ratio (after/before)"),
    ("max_drawdown", "Max drawdown"),
    ("recovery_time", "Recovery time (iterations)"),
    ("mm_panic_ratio", "MarketMaker panic ratio"),
]

THRESHOLD_MULTIPLIER = 1.3


def load_grid3() -> pd.DataFrame:
    path = result_path("h1", "raw", "unified_combined_raw.csv")
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run experiment_unified.py first."
        )

    df = pd.read_csv(path)
    expected = {
        "hft_frac",
        "info_lag",
        "speed_mult",
        "vol_ratio",
        "spread_ratio",
        "max_drawdown",
        "recovery_time",
        "mm_panic_ratio",
        "run",
    }
    missing = expected.difference(df.columns)
    if missing:
        raise ValueError(f"Missing expected columns in unified_combined_raw.csv: {sorted(missing)}")

    return df


def aggregate(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(["speed_mult", "info_lag", "hft_frac"])
        .agg(
            vol_ratio_mean=("vol_ratio", "mean"),
            vol_ratio_std=("vol_ratio", "std"),
            spread_ratio_mean=("spread_ratio", "mean"),
            spread_ratio_std=("spread_ratio", "std"),
            drawdown_mean=("max_drawdown", "mean"),
            drawdown_std=("max_drawdown", "std"),
            recovery_mean=("recovery_time", "mean"),
            recovery_std=("recovery_time", "std"),
            mm_panic_mean=("mm_panic_ratio", "mean"),
            mm_panic_std=("mm_panic_ratio", "std"),
            n_runs=("vol_ratio", "count"),
        )
        .reset_index()
    )


def bootstrap_ci(data, n_bootstrap=1000, ci=0.95, seed=42):
    rng = np.random.RandomState(seed)
    data = np.asarray(data)
    if len(data) <= 1:
        value = float(np.mean(data)) if len(data) else np.nan
        return value, value

    means = []
    for _ in range(n_bootstrap):
        sample = rng.choice(data, size=len(data), replace=True)
        means.append(np.mean(sample))

    alpha = (1 - ci) / 2
    return np.percentile(means, [alpha * 100, (1 - alpha) * 100])


def find_tipping_point(means: pd.Series, multiplier=THRESHOLD_MULTIPLIER):
    if 0.0 not in means.index:
        return None, np.nan, np.nan

    baseline = float(means.loc[0.0])
    threshold = baseline * multiplier

    for phi, value in means.sort_index().items():
        if phi == 0.0:
            continue
        if value >= threshold:
            return float(phi), baseline, threshold

    return None, baseline, threshold


def build_tipping_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (speed_mult, info_lag), sub in df.groupby(["speed_mult", "info_lag"]):
        means = sub.groupby("hft_frac")["vol_ratio"].mean().sort_index()
        phi_star, baseline, threshold = find_tipping_point(means)
        rows.append(
            {
                "speed_mult": int(speed_mult),
                "info_lag": int(info_lag),
                "baseline_vol_ratio": baseline,
                "threshold_1_3x": threshold,
                "phi_star": phi_star,
                "max_vol_ratio": float(means.max()),
                "phi_at_max": float(means.idxmax()),
                "n_runs_per_phi_min": int(sub.groupby("hft_frac").size().min()),
                "n_runs_per_phi_max": int(sub.groupby("hft_frac").size().max()),
            }
        )
    return pd.DataFrame(rows).sort_values(["speed_mult", "info_lag"])


def plot_metrics(df_raw: pd.DataFrame, out_path: str) -> None:
    speed_mults = sorted(df_raw["speed_mult"].unique())
    info_lags = sorted(df_raw["info_lag"].unique())
    colors = plt.cm.plasma(np.linspace(0.15, 0.85, len(info_lags)))

    fig, axes = plt.subplots(
        len(METRICS),
        len(speed_mults),
        figsize=(5.7 * len(speed_mults), 3.2 * len(METRICS)),
        sharex=True,
    )

    if len(speed_mults) == 1:
        axes = np.asarray(axes).reshape(len(METRICS), 1)

    for col_idx, speed_mult in enumerate(speed_mults):
        for row_idx, (metric, title) in enumerate(METRICS):
            ax = axes[row_idx, col_idx]

            for info_lag, color in zip(info_lags, colors):
                sub = df_raw[
                    (df_raw["speed_mult"] == speed_mult)
                    & (df_raw["info_lag"] == info_lag)
                ]
                grouped = sub.groupby("hft_frac")[metric]
                means = grouped.mean().sort_index()

                ci_lo = []
                ci_hi = []
                for phi in means.index:
                    values = grouped.get_group(phi).values
                    lo, hi = bootstrap_ci(values)
                    ci_lo.append(lo)
                    ci_hi.append(hi)

                ax.plot(
                    means.index,
                    means.values,
                    "o-",
                    color=color,
                    lw=2,
                    ms=4,
                    label=f"lag={info_lag}",
                )
                ax.fill_between(means.index, ci_lo, ci_hi, alpha=0.13, color=color)

                if metric == "vol_ratio":
                    phi_star, baseline, threshold = find_tipping_point(means)
                    if not np.isnan(baseline):
                        ax.axhline(baseline, color=color, lw=0.8, ls="--", alpha=0.35)
                        ax.axhline(threshold, color=color, lw=0.9, ls=":", alpha=0.45)
                    if phi_star is not None:
                        ax.axvline(phi_star, color=color, lw=0.9, ls=":", alpha=0.35)

            if row_idx == 0:
                ax.set_title(f"speed x{speed_mult}", fontsize=11, fontweight="bold")
            if col_idx == 0:
                ax.set_ylabel(title)
            if row_idx == len(METRICS) - 1:
                ax.set_xlabel("HFT fraction (phi)")

            ax.grid(alpha=0.25)
            if row_idx == 0 and col_idx == len(speed_mults) - 1:
                ax.legend(fontsize=8, title="info_lag")

    fig.suptitle(
        "Grid 3: Combined speed + information delay effect\n"
        "10 Fund + 10 TrendChartists + 5 Random + 1 MM | 30 runs | Shading = 95% bootstrap CI",
        fontsize=13,
        fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.965])
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_heatmap(df_raw: pd.DataFrame, tipping: pd.DataFrame, out_path: str) -> None:
    speed_mults = sorted(df_raw["speed_mult"].unique())
    fig, axes = plt.subplots(1, len(speed_mults), figsize=(5.6 * len(speed_mults), 5), sharey=True)

    if len(speed_mults) == 1:
        axes = [axes]

    vmin = df_raw.groupby(["speed_mult", "info_lag", "hft_frac"])["vol_ratio"].mean().min()
    vmax = df_raw.groupby(["speed_mult", "info_lag", "hft_frac"])["vol_ratio"].mean().max()

    for ax, speed_mult in zip(axes, speed_mults):
        sub = df_raw[df_raw["speed_mult"] == speed_mult]
        pivot = (
            sub.groupby(["info_lag", "hft_frac"])["vol_ratio"]
            .mean()
            .unstack("hft_frac")
            .sort_index()
        )

        im = ax.imshow(
            pivot.values,
            aspect="auto",
            origin="lower",
            cmap="RdYlGn_r",
            vmin=vmin,
            vmax=vmax,
        )

        ax.set_title(f"speed x{speed_mult}", fontsize=11, fontweight="bold")
        ax.set_xlabel("HFT fraction (phi)")
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels([f"{x:.1f}" for x in pivot.columns])
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels([str(int(x)) for x in pivot.index])

        for y, info_lag in enumerate(pivot.index):
            for x, phi in enumerate(pivot.columns):
                value = pivot.loc[info_lag, phi]
                ax.text(x, y, f"{value:.2f}", ha="center", va="center", fontsize=8)

            row = tipping[
                (tipping["speed_mult"] == speed_mult)
                & (tipping["info_lag"] == info_lag)
            ]
            if not row.empty and pd.notna(row.iloc[0]["phi_star"]):
                phi_star = row.iloc[0]["phi_star"]
                if phi_star in list(pivot.columns):
                    x_star = list(pivot.columns).index(phi_star)
                    ax.scatter(
                        [x_star],
                        [y],
                        marker="s",
                        s=160,
                        facecolors="none",
                        edgecolors="black",
                        linewidths=1.5,
                    )

    axes[0].set_ylabel("info_lag")
    cbar = fig.colorbar(im, ax=axes, fraction=0.035, pad=0.03)
    cbar.set_label("Mean vol_ratio")
    fig.suptitle(
        "Grid 3 heatmap: mean vol_ratio by speed, delay, and HFT fraction\n"
        "Black square = first phi crossing 1.3x baseline",
        fontsize=13,
        fontweight="bold",
    )
    fig.subplots_adjust(left=0.06, right=0.88, bottom=0.12, top=0.82, wspace=0.16)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    df = load_grid3()
    tipping = build_tipping_table(df)

    tipping_path = result_path("h1", "raw", "unified_combined_tipping.csv")
    metrics_path = result_path("h1", "figures", "unified_combined_metrics.png")
    heatmap_path = result_path("h1", "figures", "unified_combined_heatmap.png")

    tipping.to_csv(tipping_path, index=False)
    plot_metrics(df, metrics_path)
    plot_heatmap(df, tipping, heatmap_path)

    print("Saved:")
    print(f"  {tipping_path}")
    print(f"  {metrics_path}")
    print(f"  {heatmap_path}")
    print()
    print(tipping.to_string(index=False))


if __name__ == "__main__":
    main()
