"""
experiment_speed_delay_mannwhitney.py
====================================

Additional Mann-Whitney analysis on top of existing unified raw results.

Goals:
1. Measure the effect of speed_multiplier at fixed phi (using the speed grid).
2. Measure the effect of info_lag at fixed phi (using the delay grid).
3. Save tables and plots into separate files without touching old outputs.

This script reuses existing CSV files and does NOT run new simulations.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/1d-abm-mplconfig")
os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

from experiments.paths import result_path


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    speed_path = result_path("h1", "raw", "unified_speed_raw.csv")
    delay_path = result_path("h1", "raw", "unified_delay_raw.csv")

    if not speed_path.exists():
        raise FileNotFoundError(f"Missing file: {speed_path}")
    if not delay_path.exists():
        raise FileNotFoundError(f"Missing file: {delay_path}")

    return pd.read_csv(speed_path), pd.read_csv(delay_path)


def mann_whitney_compare(a: np.ndarray, b: np.ndarray, alternative: str = "less"):
    if len(a) < 3 or len(b) < 3:
        return None, None
    stat, p = mannwhitneyu(a, b, alternative=alternative)
    return stat, p


def analyze_speed_effect(df_speed: pd.DataFrame, phi_values=None, baseline_speed=1) -> pd.DataFrame:
    if phi_values is None:
        phi_values = [0.2, 0.4, 0.6, 0.8, 1.0]

    rows = []
    speed_mults = sorted(df_speed["speed_mult"].unique())

    for phi in phi_values:
        baseline = df_speed[
            (df_speed["speed_mult"] == baseline_speed) &
            (df_speed["hft_frac"] == phi)
        ]["vol_ratio"].values

        for sm in speed_mults:
            if sm == baseline_speed:
                continue
            treatment = df_speed[
                (df_speed["speed_mult"] == sm) &
                (df_speed["hft_frac"] == phi)
            ]["vol_ratio"].values

            stat, p = mann_whitney_compare(baseline, treatment, alternative="less")
            rows.append({
                "comparison": "speed_effect",
                "phi": phi,
                "baseline_speed": baseline_speed,
                "speed_mult": sm,
                "baseline_mean": float(np.mean(baseline)) if len(baseline) else np.nan,
                "treatment_mean": float(np.mean(treatment)) if len(treatment) else np.nan,
                "U_stat": stat,
                "p_value": p,
                "significant": bool(p < 0.05) if p is not None else False,
            })

    return pd.DataFrame(rows)


def analyze_delay_effect(df_delay: pd.DataFrame, phi_values=None, baseline_lag=0) -> pd.DataFrame:
    if phi_values is None:
        phi_values = [0.2, 0.4, 0.6, 0.8, 1.0]

    rows = []
    info_lags = sorted(df_delay["info_lag"].unique())

    for phi in phi_values:
        baseline = df_delay[
            (df_delay["info_lag"] == baseline_lag) &
            (df_delay["hft_frac"] == phi)
        ]["vol_ratio"].values

        for lag in info_lags:
            if lag == baseline_lag:
                continue
            treatment = df_delay[
                (df_delay["info_lag"] == lag) &
                (df_delay["hft_frac"] == phi)
            ]["vol_ratio"].values

            stat, p = mann_whitney_compare(baseline, treatment, alternative="less")
            rows.append({
                "comparison": "delay_effect",
                "phi": phi,
                "baseline_lag": baseline_lag,
                "info_lag": lag,
                "baseline_mean": float(np.mean(baseline)) if len(baseline) else np.nan,
                "treatment_mean": float(np.mean(treatment)) if len(treatment) else np.nan,
                "U_stat": stat,
                "p_value": p,
                "significant": bool(p < 0.05) if p is not None else False,
            })

    return pd.DataFrame(rows)


def plot_speed_effect(results: pd.DataFrame, out_path: str) -> None:
    phi_values = sorted(results["phi"].unique())
    fig, axes = plt.subplots(1, len(phi_values), figsize=(4.8 * len(phi_values), 4), sharey=True)

    if len(phi_values) == 1:
        axes = [axes]

    for ax, phi in zip(axes, phi_values):
        sub = results[results["phi"] == phi].sort_values("speed_mult")
        heights = [-np.log10(p) if pd.notna(p) and p > 0 else 0 for p in sub["p_value"]]
        colors = ["forestgreen" if s else "gray" for s in sub["significant"]]
        ax.bar(sub["speed_mult"].astype(str), heights, color=colors)
        ax.axhline(-np.log10(0.05), color="red", ls="--", lw=1)
        ax.set_title(f"Speed effect at phi={phi}")
        ax.set_xlabel("speed_multiplier")
        ax.grid(alpha=0.25, axis="y")

    axes[0].set_ylabel("-log10(p-value)")
    fig.suptitle("Mann-Whitney: effect of speed at fixed phi", fontsize=13, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_delay_effect(results: pd.DataFrame, out_path: str) -> None:
    phi_values = sorted(results["phi"].unique())
    fig, axes = plt.subplots(1, len(phi_values), figsize=(4.8 * len(phi_values), 4), sharey=True)

    if len(phi_values) == 1:
        axes = [axes]

    for ax, phi in zip(axes, phi_values):
        sub = results[results["phi"] == phi].sort_values("info_lag")
        heights = [-np.log10(p) if pd.notna(p) and p > 0 else 0 for p in sub["p_value"]]
        colors = ["royalblue" if s else "gray" for s in sub["significant"]]
        ax.bar(sub["info_lag"].astype(str), heights, color=colors)
        ax.axhline(-np.log10(0.05), color="red", ls="--", lw=1)
        ax.set_title(f"Delay effect at phi={phi}")
        ax.set_xlabel("info_lag")
        ax.grid(alpha=0.25, axis="y")

    axes[0].set_ylabel("-log10(p-value)")
    fig.suptitle("Mann-Whitney: effect of delay at fixed phi", fontsize=13, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    df_speed, df_delay = load_data()

    speed_results = analyze_speed_effect(df_speed)
    delay_results = analyze_delay_effect(df_delay)

    speed_csv = result_path("robustness", "raw", "speed_effect_mannwhitney.csv")
    delay_csv = result_path("robustness", "raw", "delay_effect_mannwhitney.csv")
    speed_png = result_path("robustness", "figures", "speed_effect_mannwhitney.png")
    delay_png = result_path("robustness", "figures", "delay_effect_mannwhitney.png")

    speed_results.to_csv(speed_csv, index=False)
    delay_results.to_csv(delay_csv, index=False)
    plot_speed_effect(speed_results, speed_png)
    plot_delay_effect(delay_results, delay_png)

    print("Saved:")
    print(f"  {speed_csv}")
    print(f"  {delay_csv}")
    print(f"  {speed_png}")
    print(f"  {delay_png}")


if __name__ == "__main__":
    main()
