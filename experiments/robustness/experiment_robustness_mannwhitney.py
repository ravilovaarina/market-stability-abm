"""
experiment_robustness_mannwhitney.py
======================================

Mann-Whitney U tests for two robustness experiments:
  1. shock_magnitude  — does the tipping point hold across different shock sizes?
  2. noisy_delay      — does delaying only Random agents create instability?

Uses existing CSV files — no new simulations needed.

Logic:
  For each secondary parameter (shock_dp or info_lag), at each phi:
    H0: vol_ratio at phi == vol_ratio at phi=0 (same distribution)
    H1: vol_ratio at phi > vol_ratio at phi=0  (one-sided, alternative="greater")
  p < 0.05 → this phi is significantly more volatile than the no-HFT baseline.

Tipping point phi*:
  Smallest phi where p < 0.05 AND mean(vol_ratio) >= 1.3 * mean(vol_ratio at phi=0).
  (Both conditions required to avoid catching noise.)

Outputs:
  - robustness_mw_shock_magnitude.csv
  - robustness_mw_noisy_delay.csv
  - robustness_mw_shock_magnitude.png
  - robustness_mw_noisy_delay.png
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/1d-abm-mplconfig")
os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

THRESHOLD_MULT = 1.3

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "results" / "h1" / "robustness" / "raw"
TABLE_DIR = PROJECT_ROOT / "results" / "h1" / "robustness" / "tables"
FIGURE_DIR = PROJECT_ROOT / "results" / "h1" / "robustness" / "figures"
TABLE_DIR.mkdir(parents=True, exist_ok=True)
FIGURE_DIR.mkdir(parents=True, exist_ok=True)


# ── Core test ─────────────────────────────────────────────────────────────────

def mann_whitney_vs_baseline(df: pd.DataFrame,
                              group_col: str,
                              phi_col: str = "hft_frac",
                              metric: str = "vol_ratio") -> pd.DataFrame:
    """
    For each value in group_col (e.g. shock_dp or info_lag),
    compare vol_ratio at each phi against phi=0 baseline.
    """
    rows = []
    for group_val, grp in df.groupby(group_col):
        baseline = grp[grp[phi_col] == 0.0][metric].values
        baseline_mean = float(np.mean(baseline))
        threshold = THRESHOLD_MULT * baseline_mean

        for phi_val, phi_grp in grp.groupby(phi_col):
            treatment = phi_grp[metric].values
            if phi_val == 0.0:
                rows.append({
                    group_col:          group_val,
                    phi_col:            phi_val,
                    "baseline_mean":    round(baseline_mean, 4),
                    "treatment_mean":   round(baseline_mean, 4),
                    "threshold_1_3x":   round(threshold, 4),
                    "above_threshold":  False,
                    "U_stat":           None,
                    "p_value":          None,
                    "significant":      False,
                    "tipping_point":    False,
                    "n_baseline":       len(baseline),
                    "n_treatment":      len(treatment),
                })
                continue

            stat, p = mannwhitneyu(baseline, treatment, alternative="less")
            treatment_mean = float(np.mean(treatment))
            above = treatment_mean >= threshold
            significant = bool(p < 0.05)

            rows.append({
                group_col:          group_val,
                phi_col:            phi_val,
                "baseline_mean":    round(baseline_mean, 4),
                "treatment_mean":   round(treatment_mean, 4),
                "threshold_1_3x":   round(threshold, 4),
                "above_threshold":  above,
                "U_stat":           round(float(stat), 1),
                "p_value":          round(float(p), 5),
                "significant":      significant,
                "tipping_point":    False,
                "n_baseline":       len(baseline),
                "n_treatment":      len(treatment),
            })

    result = pd.DataFrame(rows)

    # mark tipping point: first phi (per group) where both conditions hold
    for group_val, grp_idx in result.groupby(group_col).groups.items():
        grp = result.loc[grp_idx].sort_values(phi_col)
        for idx, row in grp.iterrows():
            if row["significant"] and row["above_threshold"]:
                result.at[idx, "tipping_point"] = True
                break

    return result


# ── Plot ──────────────────────────────────────────────────────────────────────

def plot_results(result: pd.DataFrame,
                 group_col: str,
                 group_label: str,
                 title: str,
                 output_path: str) -> None:
    group_values = sorted(result[group_col].unique())
    n = len(group_values)
    fig, axes = plt.subplots(1, n, figsize=(4 * n, 5), sharey=True)
    if n == 1:
        axes = [axes]

    cmap = plt.get_cmap("tab10", n)

    for ax, (gval, color) in zip(axes, zip(group_values, cmap.colors if hasattr(cmap, "colors") else [cmap(i) for i in range(n)])):
        sub = result[result[group_col] == gval].sort_values("hft_frac")
        phis = sub["hft_frac"].values
        means = sub["treatment_mean"].values
        threshold = sub["threshold_1_3x"].iloc[0]
        baseline_mean = sub["baseline_mean"].iloc[0]

        ax.plot(phis, means, marker="o", color=color, linewidth=2, label="mean vol_ratio")
        ax.axhline(threshold, color="red", linestyle="--", linewidth=1.2, label=f"threshold ({THRESHOLD_MULT}×baseline)")
        ax.axhline(baseline_mean, color="gray", linestyle=":", linewidth=1, label="baseline (phi=0)")

        # mark significant points
        sig = sub[sub["significant"]]
        if not sig.empty:
            ax.scatter(sig["hft_frac"], sig["treatment_mean"],
                       color="orange", zorder=5, s=80, label="p<0.05")

        # mark tipping point
        tp = sub[sub["tipping_point"]]
        if not tp.empty:
            ax.scatter(tp["hft_frac"], tp["treatment_mean"],
                       color="red", marker="*", zorder=6, s=200,
                       label=f"φ*={tp['hft_frac'].iloc[0]:.1f}")

        ax.set_title(f"{group_label} = {gval}", fontsize=11)
        ax.set_xlabel("hft_frac (φ)")
        ax.set_ylabel("mean vol_ratio" if ax == axes[0] else "")
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)

    fig.suptitle(title, fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Plot saved: {output_path}")


# ── Summary printer ───────────────────────────────────────────────────────────

def print_summary(result: pd.DataFrame, group_col: str, name: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    for gval, grp in result.groupby(group_col):
        tp = grp[grp["tipping_point"]]
        phi_star = tp["hft_frac"].iloc[0] if not tp.empty else "not found"
        sig_phis = grp[grp["significant"]]["hft_frac"].tolist()
        print(f"  {group_col}={gval:>6}:  φ* = {phi_star}  |  significant at φ = {sig_phis}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # ── 1. Shock magnitude ────────────────────────────────────────────────────
    shock_raw = RAW_DIR / "shock_magnitude_raw.csv"
    shock_csv = TABLE_DIR / "robustness_mw_shock_magnitude.csv"
    shock_png = FIGURE_DIR / "robustness_mw_shock_magnitude.png"
    noisy_raw = RAW_DIR / "noisy_delay_raw.csv"
    noisy_csv = TABLE_DIR / "robustness_mw_noisy_delay.csv"
    noisy_png = FIGURE_DIR / "robustness_mw_noisy_delay.png"

    print(f"Loading {shock_raw}...")
    sm = pd.read_csv(shock_raw)
    print(f"  {len(sm)} rows")

    print("Running Mann-Whitney for shock_magnitude...")
    sm_result = mann_whitney_vs_baseline(sm, group_col="shock_dp")
    sm_result.to_csv(shock_csv, index=False)
    print(f"  Saved: {shock_csv}")

    print_summary(sm_result, "shock_dp", "SHOCK MAGNITUDE robustness")

    plot_results(
        sm_result,
        group_col="shock_dp",
        group_label="shock size",
        title="H1 robustness: tipping point across shock sizes (Mann-Whitney)",
        output_path=shock_png,
    )

    # ── 2. Noisy delay ────────────────────────────────────────────────────────
    print(f"\nLoading {noisy_raw}...")
    nd = pd.read_csv(noisy_raw)
    print(f"  {len(nd)} rows")

    print("Running Mann-Whitney for noisy_delay...")
    nd_result = mann_whitney_vs_baseline(nd, group_col="info_lag")
    nd_result.to_csv(noisy_csv, index=False)
    print(f"  Saved: {noisy_csv}")

    print_summary(nd_result, "info_lag", "NOISY DELAY mechanism isolation")

    plot_results(
        nd_result,
        group_col="info_lag",
        group_label="info_lag",
        title="H1 mechanism: delay on Random agents only (Mann-Whitney)",
        output_path=noisy_png,
    )

    # ── Combined summary ──────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("  FINAL SUMMARY")
    print("="*60)
    print("\nShock magnitude — tipping points found:")
    tp_sm = sm_result[sm_result["tipping_point"]][["shock_dp", "hft_frac", "treatment_mean", "p_value"]]
    print(tp_sm.to_string(index=False) if not tp_sm.empty else "  None found")

    print("\nNoisy delay — tipping points found:")
    tp_nd = nd_result[nd_result["tipping_point"]][["info_lag", "hft_frac", "treatment_mean", "p_value"]]
    print(tp_nd.to_string(index=False) if not tp_nd.empty else "  None found (expected — this is a negative result)")


if __name__ == "__main__":
    main()
