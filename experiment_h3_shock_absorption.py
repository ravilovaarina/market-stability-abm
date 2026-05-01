"""
experiment_h3_shock_absorption.py
==================================

H3 re-analysis: shock absorption as primary metric.

Uses existing h3_confirmatory_raw.csv — no new simulations needed.

Research question (revised):
  Do information delay and thin order book make the market suffer the shock
  harder — longer recovery time, deeper price drop, and lower stabilization
  price after the shock?

Metrics:
  - recovery_time : iterations until price returns to 90% of pre-shock level
  - max_drawdown  : maximum price drop relative to pre-shock price
  - stabilization_gap : 1 - stabilization_price / pre_shock_price.
                        Higher values mean the market stabilized at a lower
                        price level after the shock.

Statistical test:
  OLS with HC3 standard errors (same method as existing h3_confirmatory_ols_hc3.csv).

  Model per phi:
    metric = b0 + b1*delay + b2*thin_book + b3*(delay x thin_book) + run_FE + e

  b3 is the interaction: does delay hurt more when the book is thin?

  H3 is supported if b3 > 0 and statistically significant.

Also reports:
  - Mann-Whitney U: (lag=0, thick) vs (lag=1, thin) per phi — direct worst-vs-best comparison
  - Descriptive table of means per cell

Outputs:
  - h3_shock_absorption_ols.csv   : OLS HC3 results per phi and metric
  - h3_shock_absorption_mw.csv    : Mann-Whitney results
  - h3_shock_absorption_means.csv : cell means
  - h3_shock_absorption.png       : plots
"""

from __future__ import annotations

import math
import os
from typing import Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

RAW_CSV = "h3_confirmatory_raw.csv"
METRICS = ["recovery_time", "max_drawdown", "stabilization_gap"]
THIN_BOOK = 300
THICK_BOOK = 1500


# ── OLS HC3 ──────────────────────────────────────────────────────────────────

def _normal_p(t: float) -> float:
    return float(math.erfc(abs(t) / math.sqrt(2.0)))


def _ols_hc3(y: np.ndarray, x: np.ndarray) -> Dict[str, np.ndarray]:
    xtx_inv = np.linalg.pinv(x.T @ x)
    beta = xtx_inv @ x.T @ y
    resid = y - x @ beta
    hat = np.sum((x @ xtx_inv) * x, axis=1)
    scale = (resid / np.maximum(1.0 - hat, 1e-9)) ** 2
    meat = x.T @ (x * scale[:, None])
    cov = xtx_inv @ meat @ xtx_inv
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    return {"beta": beta, "se": se}


def fit_ols_hc3(raw: pd.DataFrame) -> pd.DataFrame:
    rows: List[dict] = []
    for phi, sub in raw.groupby("hft_frac"):
        sub = sub.copy().sort_values(["run", "info_lag", "book_volume"]).reset_index(drop=True)
        delay = (sub["info_lag"].astype(int) == 1).astype(float).to_numpy()
        thin  = (sub["book_volume"].astype(int) == THIN_BOOK).astype(float).to_numpy()
        interaction = delay * thin

        runs = sorted(sub["run"].astype(int).unique())
        run_to_idx = {r: i for i, r in enumerate(runs[1:])}
        run_dummies = np.zeros((len(sub), max(len(runs) - 1, 0)), dtype=float)
        for i, r in enumerate(sub["run"].astype(int).to_numpy()):
            if r in run_to_idx:
                run_dummies[i, run_to_idx[r]] = 1.0

        x = np.column_stack([np.ones(len(sub)), delay, thin, interaction, run_dummies])

        for metric in METRICS:
            y = sub[metric].to_numpy(dtype=float)
            res = _ols_hc3(y, x)
            b   = float(res["beta"][3])
            se  = float(res["se"][3])
            t   = b / se if se > 0 else np.nan
            p   = _normal_p(t) if np.isfinite(t) else np.nan
            rows.append({
                "hft_frac":          float(phi),
                "metric":            metric,
                "n_obs":             len(sub),
                "n_runs":            len(runs),
                "b1_delay":          float(res["beta"][1]),
                "b2_thin_book":      float(res["beta"][2]),
                "b3_interaction":    b,
                "se_hc3":            se,
                "t_hc3":             t,
                "p_value":           p,
                "significant_5pct":  bool(p < 0.05) if np.isfinite(p) else False,
                "ci_low":            b - 1.96 * se,
                "ci_high":           b + 1.96 * se,
                "interaction_positive": bool(b > 0),
            })
    return pd.DataFrame(rows)


# ── Mann-Whitney ──────────────────────────────────────────────────────────────

def run_mann_whitney(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Compare best-case (lag=0, thick book) vs worst-case (lag=1, thin book).
    H3 alternative: worst-case > best-case (one-sided).
    """
    rows: List[dict] = []
    for phi, sub in raw.groupby("hft_frac"):
        best  = sub[(sub["info_lag"] == 0) & (sub["book_volume"] == THICK_BOOK)]
        worst = sub[(sub["info_lag"] == 1) & (sub["book_volume"] == THIN_BOOK)]
        for metric in METRICS:
            a = best[metric].dropna().to_numpy()
            b = worst[metric].dropna().to_numpy()
            if len(a) < 3 or len(b) < 3:
                continue
            stat, p = mannwhitneyu(a, b, alternative="less")
            rows.append({
                "hft_frac":       float(phi),
                "metric":         metric,
                "group_best_mean":  float(np.mean(a)),
                "group_worst_mean": float(np.mean(b)),
                "difference":       float(np.mean(b) - np.mean(a)),
                "U_stat":           float(stat),
                "p_value":          float(p),
                "significant_5pct": bool(p < 0.05),
                "n_best":           len(a),
                "n_worst":          len(b),
            })
    return pd.DataFrame(rows)


# ── Cell means ───────────────────────────────────────────────────────────────

def cell_means(raw: pd.DataFrame) -> pd.DataFrame:
    means = (
        raw.groupby(["hft_frac", "info_lag", "book_volume"])[METRICS]
        .agg(["mean", "std", "count"])
        .round(3)
        .reset_index()
    )
    means.columns = [
        "_".join(str(part) for part in col if str(part))
        if isinstance(col, tuple)
        else str(col)
        for col in means.columns
    ]
    return means


# ── Plot ─────────────────────────────────────────────────────────────────────

def plot(ols: pd.DataFrame, raw: pd.DataFrame, path: str) -> None:
    fig, axes = plt.subplots(2, len(METRICS), figsize=(5.5 * len(METRICS), 9))
    fig.suptitle(
        "H3: Shock absorption — delay × book depth interaction",
        fontsize=14, fontweight="bold"
    )

    phi_values = sorted(raw["hft_frac"].unique())
    colors = {
        (0, THICK_BOOK): "#2196F3",
        (0, THIN_BOOK):  "#64B5F6",
        (1, THICK_BOOK): "#F44336",
        (1, THIN_BOOK):  "#EF9A9A",
    }
    labels = {
        (0, THICK_BOOK): "lag=0, thick book",
        (0, THIN_BOOK):  "lag=0, thin book",
        (1, THICK_BOOK): "lag=1, thick book",
        (1, THIN_BOOK):  "lag=1, thin book (worst case)",
    }

    metric_titles = {
        "recovery_time": "Recovery time",
        "max_drawdown": "Maximum drawdown",
        "stabilization_gap": "Stabilization gap",
    }

    for col, metric in enumerate(METRICS):
        ax_means = axes[0, col]
        for (lag, bv), grp in raw.groupby(["info_lag", "book_volume"]):
            means = [grp[grp["hft_frac"] == phi][metric].mean() for phi in phi_values]
            ax_means.plot(
                phi_values, means,
                marker="o", color=colors[(lag, bv)],
                label=labels[(lag, bv)], linewidth=1.8
            )
        ax_means.set_title(f"{metric_titles.get(metric, metric)} — cell means by phi")
        ax_means.set_xlabel("hft_frac (phi)")
        ax_means.set_ylabel(metric)
        ax_means.legend(fontsize=8)
        ax_means.grid(alpha=0.3)

        ax_int = axes[1, col]
        ols_m = ols[ols["metric"] == metric].sort_values("hft_frac")
        x = np.arange(len(ols_m))
        bars = ax_int.bar(
            x, ols_m["b3_interaction"],
            color=["#4CAF50" if v > 0 else "#F44336" for v in ols_m["b3_interaction"]],
            alpha=0.75, zorder=3
        )
        ax_int.errorbar(
            x, ols_m["b3_interaction"],
            yerr=[
                ols_m["b3_interaction"].values - ols_m["ci_low"].values,
                ols_m["ci_high"].values - ols_m["b3_interaction"].values,
            ],
            fmt="none", color="black", capsize=5, linewidth=1.5, zorder=4
        )
        ax_int.axhline(0, color="black", linewidth=0.8, linestyle="--")
        ax_int.set_xticks(x)
        ax_int.set_xticklabels([f"phi={v:g}" for v in ols_m["hft_frac"]])
        ax_int.set_title(f"{metric_titles.get(metric, metric)} — OLS b3 (delay x thin) + 95% CI")
        ax_int.set_ylabel("interaction coefficient")
        ax_int.grid(alpha=0.3, axis="y", zorder=0)

        for i, (_, row) in enumerate(ols_m.iterrows()):
            sig = "*" if row["significant_5pct"] else ""
            if not sig:
                continue
            span = max(abs(ols_m["ci_high"].max() - ols_m["ci_low"].min()), 1e-6)
            y = row["ci_high"] + 0.04 * span
            ax_int.text(i, y, sig, ha="center", fontsize=14, color="black")

    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Plot saved: {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not os.path.exists(RAW_CSV):
        raise FileNotFoundError(f"Raw data not found: {RAW_CSV}\nRun from the h3-volatility-clustering branch root.")

    print(f"Loading {RAW_CSV}...")
    raw = pd.read_csv(RAW_CSV)
    missing_metrics = [m for m in METRICS if m not in raw.columns]
    if missing_metrics:
        missing = ", ".join(missing_metrics)
        raise ValueError(
            f"{RAW_CSV} is missing required metric(s): {missing}.\n"
            "Re-run experiment_h3_confirmatory_2x2.py after the stabilization "
            "metrics have been added to experiment_h3_liquidity_depth.py."
        )
    print(f"  {len(raw)} rows, phi values: {sorted(raw['hft_frac'].unique())}")
    print(f"  info_lag values: {sorted(raw['info_lag'].unique())}")
    print(f"  book_volume values: {sorted(raw['book_volume'].unique())}")

    print("\nFitting OLS HC3...")
    ols = fit_ols_hc3(raw)
    ols.to_csv("h3_shock_absorption_ols.csv", index=False)
    print("  Saved: h3_shock_absorption_ols.csv")

    print("\nOLS HC3 results (interaction b3):")
    print(ols[["hft_frac", "metric", "b1_delay", "b2_thin_book",
               "b3_interaction", "se_hc3", "t_hc3", "p_value", "significant_5pct"]].to_string(index=False))

    print("\nRunning Mann-Whitney (best vs worst case)...")
    mw = run_mann_whitney(raw)
    mw.to_csv("h3_shock_absorption_mw.csv", index=False)
    print("  Saved: h3_shock_absorption_mw.csv")

    print("\nMann-Whitney results:")
    print(mw[["hft_frac", "metric", "group_best_mean", "group_worst_mean",
              "difference", "p_value", "significant_5pct"]].to_string(index=False))

    print("\nCell means:")
    means = cell_means(raw)
    means.to_csv("h3_shock_absorption_means.csv", index=False)
    print("  Saved: h3_shock_absorption_means.csv")

    print("\nPlotting...")
    plot(ols, raw, "h3_shock_absorption.png")

    print("\n=== SUMMARY ===")
    for metric in METRICS:
        sig = ols[(ols["metric"] == metric) & (ols["significant_5pct"])]
        print(f"{metric}: {len(sig)}/{len(ols[ols['metric']==metric])} phi values show significant interaction (p<0.05)")
    print()
    for metric in METRICS:
        sig = mw[(mw["metric"] == metric) & (mw["significant_5pct"])]
        print(f"{metric} Mann-Whitney: {len(sig)}/{len(mw[mw['metric']==metric])} phi values — worst > best (p<0.05)")


if __name__ == "__main__":
    main()
