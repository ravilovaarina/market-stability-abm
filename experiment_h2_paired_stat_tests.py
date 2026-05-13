#!/usr/bin/env python3
"""
H2 paired statistical tests.

This is an analysis-only follow-up for the H2-on-H1 branch. It does not run new
simulations. It uses the paired-difference file produced by
experiment_h2_postshock_volume_windows.py:

    h2_postshock_volume_paired_diffs.csv

Each row is one matched calendar/event-time run. Difference columns are defined
as:

    event_time_metric - calendar_time_metric

For instability metrics, negative values mean event time is lower / more stable.
The script applies:
- bootstrap 95% CI for the mean difference,
- one-sided Wilcoxon signed-rank test for event_time < calendar_time,
- two-sided Wilcoxon test,
- exact sign test for the share of negative differences.

Outputs:
- h2_paired_stat_tests.csv
- h2_paired_stat_tests.md
- h2_paired_stat_tests.png
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Iterable

os.environ.setdefault("MPLCONFIGDIR", "/tmp/1d-abm-mplconfig")
os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import binomtest, wilcoxon


INPUT_CSV = Path("h2_postshock_volume_paired_diffs.csv")
OUT_CSV = Path("h2_paired_stat_tests.csv")
OUT_MD = Path("h2_paired_stat_tests.md")
OUT_PNG = Path("h2_paired_stat_tests.png")

PRIMARY_METRICS = [
    "diff_post_rv_per_volume",
    "diff_post_rv_per_trade",
    "diff_post_vol_per_sqrt_volume",
    "diff_equal_volume_vol_ratio",
    "diff_calendar_style_vol_ratio",
    "diff_spread_ratio",
]

METRIC_LABELS = {
    "diff_post_rv_per_volume": "RV per volume",
    "diff_post_rv_per_trade": "RV per trade",
    "diff_post_vol_per_sqrt_volume": "Vol / sqrt(volume)",
    "diff_equal_volume_vol_ratio": "Equal-volume vol ratio",
    "diff_calendar_style_vol_ratio": "Calendar-style vol ratio",
    "diff_spread_ratio": "Spread ratio",
}


def bootstrap_ci(values: np.ndarray, n_bootstrap: int = 10000, seed: int = 42) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return math.nan, math.nan
    means = rng.choice(values, size=(n_bootstrap, len(values)), replace=True).mean(axis=1)
    return tuple(np.percentile(means, [2.5, 97.5]))


def safe_wilcoxon(values: np.ndarray, alternative: str) -> tuple[float, float]:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    values = values[np.abs(values) > 1e-15]
    if len(values) < 3:
        return math.nan, math.nan
    try:
        res = wilcoxon(values, alternative=alternative, zero_method="wilcox")
        return float(res.statistic), float(res.pvalue)
    except ValueError:
        return math.nan, math.nan


def sign_test(values: np.ndarray, alternative: str = "greater") -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    values = values[np.abs(values) > 1e-15]
    if len(values) == 0:
        return math.nan
    n_negative = int(np.sum(values < 0))
    return float(binomtest(n_negative, n=len(values), p=0.5, alternative=alternative).pvalue)


def rank_biserial_for_lower(values: np.ndarray) -> float:
    """Matched-pairs rank-biserial effect size.

    Positive values mean negative paired differences dominate, i.e. event time is
    lower than calendar time. The range is [-1, 1].
    """
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    values = values[np.abs(values) > 1e-15]
    if len(values) == 0:
        return math.nan
    order = np.argsort(np.abs(values))
    ranks = np.empty(len(values), dtype=float)
    ranks[order] = np.arange(1, len(values) + 1, dtype=float)
    w_negative = float(np.sum(ranks[values < 0]))
    w_positive = float(np.sum(ranks[values > 0]))
    total = w_negative + w_positive
    return (w_negative - w_positive) / total if total else math.nan


def cohen_dz(values: np.ndarray) -> float:
    """Paired standardized mean difference for raw event-calendar differences."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return math.nan
    sd = float(np.std(values, ddof=1))
    if sd <= 1e-15:
        return math.nan
    return float(np.mean(values) / sd)


def holm_adjust(p_values: np.ndarray) -> np.ndarray:
    """Holm-Bonferroni adjusted p-values."""
    p = np.asarray(p_values, dtype=float)
    adjusted = np.full(len(p), np.nan)
    mask = np.isfinite(p)
    valid = p[mask]
    if len(valid) == 0:
        return adjusted
    order = np.argsort(valid)
    ranked = valid[order]
    adj_ranked = np.empty(len(valid), dtype=float)
    running_max = 0.0
    m = len(valid)
    for i, value in enumerate(ranked):
        running_max = max(running_max, (m - i) * value)
        adj_ranked[i] = min(running_max, 1.0)
    valid_adjusted = np.empty(len(valid), dtype=float)
    valid_adjusted[order] = adj_ranked
    adjusted[mask] = valid_adjusted
    return adjusted


def bh_adjust(p_values: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg FDR adjusted p-values."""
    p = np.asarray(p_values, dtype=float)
    adjusted = np.full(len(p), np.nan)
    mask = np.isfinite(p)
    valid = p[mask]
    if len(valid) == 0:
        return adjusted
    order = np.argsort(valid)
    ranked = valid[order]
    m = len(valid)
    adj_ranked = np.empty(len(valid), dtype=float)
    running_min = 1.0
    for i in range(m - 1, -1, -1):
        running_min = min(running_min, ranked[i] * m / (i + 1))
        adj_ranked[i] = running_min
    valid_adjusted = np.empty(len(valid), dtype=float)
    valid_adjusted[order] = np.clip(adj_ranked, 0.0, 1.0)
    adjusted[mask] = valid_adjusted
    return adjusted


def analyze(df: pd.DataFrame, metrics: Iterable[str] = PRIMARY_METRICS) -> pd.DataFrame:
    rows = []
    for phi, sub in df.groupby("hft_frac"):
        for metric in metrics:
            values = sub[metric].dropna().to_numpy(dtype=float)
            ci_low, ci_high = bootstrap_ci(values, seed=1000 + int(round(float(phi) * 100)) + len(metric))
            w_less, p_less = safe_wilcoxon(values, alternative="less")
            w_two, p_two = safe_wilcoxon(values, alternative="two-sided")
            p_sign = sign_test(values, alternative="greater")
            rows.append(
                {
                    "hft_frac": float(phi),
                    "metric": metric,
                    "metric_label": METRIC_LABELS.get(metric, metric),
                    "n_pairs": int(len(values)),
                    "mean_diff": float(np.mean(values)),
                    "median_diff": float(np.median(values)),
                    "cohen_dz": cohen_dz(values),
                    "rank_biserial_lower": rank_biserial_for_lower(values),
                    "ci_low": float(ci_low),
                    "ci_high": float(ci_high),
                    "negative_share": float(np.mean(values < 0)),
                    "positive_share": float(np.mean(values > 0)),
                    "wilcoxon_less_stat": w_less,
                    "wilcoxon_less_p": p_less,
                    "wilcoxon_two_sided_stat": w_two,
                    "wilcoxon_two_sided_p": p_two,
                    "sign_test_negative_p": p_sign,
                    "event_time_lower_bootstrap": bool(ci_high < 0),
                    "event_time_higher_bootstrap": bool(ci_low > 0),
                    "event_time_lower_wilcoxon_5pct": bool(np.isfinite(p_less) and p_less < 0.05),
                    "event_time_lower_sign_5pct": bool(np.isfinite(p_sign) and p_sign < 0.05),
                }
            )
    results = pd.DataFrame(rows)
    results["wilcoxon_less_p_holm_all"] = holm_adjust(results["wilcoxon_less_p"].to_numpy())
    results["wilcoxon_less_p_bh_all"] = bh_adjust(results["wilcoxon_less_p"].to_numpy())
    results["wilcoxon_less_holm_5pct"] = results["wilcoxon_less_p_holm_all"] < 0.05
    results["wilcoxon_less_bh_5pct"] = results["wilcoxon_less_p_bh_all"] < 0.05

    # Also adjust inside each metric family across phi values. This is less
    # conservative and useful when interpreting one metric at a time.
    results["wilcoxon_less_p_holm_by_metric"] = np.nan
    results["wilcoxon_less_p_bh_by_metric"] = np.nan
    for metric, idx in results.groupby("metric").groups.items():
        idx = list(idx)
        pvals = results.loc[idx, "wilcoxon_less_p"].to_numpy()
        results.loc[idx, "wilcoxon_less_p_holm_by_metric"] = holm_adjust(pvals)
        results.loc[idx, "wilcoxon_less_p_bh_by_metric"] = bh_adjust(pvals)
    results["wilcoxon_less_holm_by_metric_5pct"] = results["wilcoxon_less_p_holm_by_metric"] < 0.05
    results["wilcoxon_less_bh_by_metric_5pct"] = results["wilcoxon_less_p_bh_by_metric"] < 0.05
    return results


def fmt_num(value: float) -> str:
    if not np.isfinite(value):
        return "NA"
    if abs(value) < 0.001 and value != 0:
        return f"{value:.3e}"
    return f"{value:.4f}"


def write_markdown(results: pd.DataFrame) -> None:
    lines = [
        "# H2 Paired Statistical Tests",
        "",
        "Input: `h2_postshock_volume_paired_diffs.csv`.",
        "",
        "All differences are `event time - calendar time`. For instability metrics, negative values mean event time is lower / more stable.",
        "",
        "Tests:",
        "- bootstrap 95% CI for the mean paired difference;",
        "- one-sided Wilcoxon signed-rank test with alternative `event time < calendar time`;",
        "- exact sign test for whether negative differences are more frequent than positive ones.",
        "",
        "## Results",
        "",
        "| phi | metric | mean diff | 95% CI | negative share | effect size | Wilcoxon p (<0) | Holm p | BH p | conclusion |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]

    for row in results.itertuples(index=False):
        if row.event_time_lower_bootstrap or row.wilcoxon_less_bh_5pct:
            conclusion = "event time lower"
        elif row.event_time_higher_bootstrap:
            conclusion = "event time higher"
        else:
            conclusion = "not significant / mixed"
        lines.append(
            f"| {row.hft_frac:.1f} | {row.metric_label} | {fmt_num(row.mean_diff)} | "
            f"[{fmt_num(row.ci_low)}, {fmt_num(row.ci_high)}] | "
            f"{row.negative_share:.2f} | {fmt_num(row.rank_biserial_lower)} | "
            f"{fmt_num(row.wilcoxon_less_p)} | {fmt_num(row.wilcoxon_less_p_holm_all)} | "
            f"{fmt_num(row.wilcoxon_less_p_bh_all)} | {conclusion} |"
        )

    primary = results[results["metric"].isin(PRIMARY_METRICS)]
    supported = primary[
        primary["event_time_lower_bootstrap"] | primary["wilcoxon_less_bh_5pct"]
    ]
    supported_uncorrected = primary[
        primary["event_time_lower_bootstrap"] | primary["event_time_lower_wilcoxon_5pct"]
    ]
    higher = primary[primary["event_time_higher_bootstrap"]]

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            f"Across the primary H2 metrics, {len(supported_uncorrected)} out of {len(primary)} phi-metric cells show uncorrected statistical evidence that event time is lower than calendar time by either bootstrap CI or one-sided Wilcoxon at the 5% level.",
            f"After Benjamini-Hochberg correction across all H2 paired tests, {int(primary['wilcoxon_less_bh_5pct'].sum())} Wilcoxon cells remain significant; after Holm correction, {int(primary['wilcoxon_less_holm_5pct'].sum())} remain significant.",
            f"{len(higher)} cells show bootstrap evidence that event time is higher.",
            "",
            "The result is therefore not a universal stabilization result. It is a regime-dependent clock effect: event-time measurement can reduce some post-shock volatility/spread measures, but the evidence is uneven across HFT shares and metrics.",
        ]
    )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def plot_results(results: pd.DataFrame) -> None:
    metrics = PRIMARY_METRICS[:4]
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), sharex=True)
    axes = axes.ravel()

    for ax, metric in zip(axes, metrics):
        sub = results[results["metric"] == metric].sort_values("hft_frac")
        x = np.arange(len(sub))
        y = sub["mean_diff"].to_numpy()
        yerr = np.vstack([y - sub["ci_low"].to_numpy(), sub["ci_high"].to_numpy() - y])
        colors = [
            "#2E7D32" if lo < 0 and hi < 0 else "#C62828" if lo > 0 and hi > 0 else "#757575"
            for lo, hi in zip(sub["ci_low"], sub["ci_high"])
        ]
        ax.bar(x, y, color=colors, alpha=0.8)
        ax.errorbar(x, y, yerr=yerr, fmt="none", ecolor="black", capsize=4, lw=1)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels([f"{v:.1f}" for v in sub["hft_frac"]])
        ax.set_title(METRIC_LABELS.get(metric, metric))
        ax.set_xlabel("HFT fraction (phi)")
        ax.set_ylabel("event - calendar")
        ax.grid(axis="y", alpha=0.25)

    fig.suptitle("H2 paired differences: event time minus calendar time", fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(f"Missing {INPUT_CSV}. Run experiment_h2_postshock_volume_windows.py first.")
    df = pd.read_csv(INPUT_CSV)
    results = analyze(df)
    results.to_csv(OUT_CSV, index=False)
    write_markdown(results)
    plot_results(results)
    print(f"Saved {OUT_CSV}")
    print(f"Saved {OUT_MD}")
    print(f"Saved {OUT_PNG}")


if __name__ == "__main__":
    main()
