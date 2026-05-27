"""
experiment_h3_final_summary.py
==============================

Final H3 synthesis. This script does not run new simulations.

It combines the already completed H3 outputs:
  - exploratory softlimit interaction bootstrap
  - depth-based interaction bootstrap
  - confirmatory shock-absorption OLS HC3 test
  - confirmatory worst-vs-best Mann-Whitney test

The goal is to make the final H3 conclusion reproducible and explicit:
which effects survive multiple-testing correction, which direction they have,
and whether they support the original superadditive delay x illiquidity claim.

Outputs:
  - h3_final_summary_clustering_interactions.csv
  - h3_final_summary_shock_absorption.csv
  - h3_final_summary.png
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable
import os

os.environ.setdefault("MPLCONFIGDIR", "/tmp/1d-abm-mplconfig")
os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = PROJECT_ROOT / "results" / "h3"

SOFTLIMIT_BOOTSTRAP = RESULTS_ROOT / "clustering" / "tables" / "h3_clustering_interactions_bootstrap.csv"
DEPTH_BOOTSTRAP = RESULTS_ROOT / "depth" / "tables" / "h3_depth_interactions_bootstrap.csv"
SHOCK_OLS = RESULTS_ROOT / "shock_absorption" / "tables" / "h3_shock_absorption_ols.csv"
SHOCK_MW = RESULTS_ROOT / "shock_absorption" / "tables" / "h3_shock_absorption_mw.csv"

OUT_CLUSTERING = RESULTS_ROOT / "summary" / "tables" / "h3_final_summary_clustering_interactions.csv"
OUT_SHOCK = RESULTS_ROOT / "summary" / "tables" / "h3_final_summary_shock_absorption.csv"
OUT_MD = RESULTS_ROOT / "summary" / "tables" / "h3_final_summary.md"
OUT_PNG = RESULTS_ROOT / "summary" / "figures" / "h3_final_summary.png"

ALPHA = 0.05
CORE_CLUSTERING_METRICS = {"acf_abs_ret_1", "acf_abs_ret_5", "vol_persistence"}
SHOCK_METRICS = {"recovery_time", "max_drawdown", "stabilization_gap"}


def _holm_adjust(p_values: Iterable[float]) -> np.ndarray:
    p = np.asarray(list(p_values), dtype=float)
    out = np.full(len(p), np.nan)
    valid = np.isfinite(p)
    if not valid.any():
        return out

    idx = np.where(valid)[0]
    order = idx[np.argsort(p[valid])]
    m = len(order)
    adjusted_sorted = np.empty(m, dtype=float)
    running_max = 0.0
    for rank, original_idx in enumerate(order):
        adjusted = (m - rank) * p[original_idx]
        running_max = max(running_max, adjusted)
        adjusted_sorted[rank] = min(running_max, 1.0)

    for rank, original_idx in enumerate(order):
        out[original_idx] = adjusted_sorted[rank]
    return out


def _bh_adjust(p_values: Iterable[float]) -> np.ndarray:
    p = np.asarray(list(p_values), dtype=float)
    out = np.full(len(p), np.nan)
    valid = np.isfinite(p)
    if not valid.any():
        return out

    idx = np.where(valid)[0]
    order = idx[np.argsort(p[valid])]
    m = len(order)
    sorted_p = p[order]
    adjusted_sorted = np.empty(m, dtype=float)
    running_min = 1.0
    for rank in range(m - 1, -1, -1):
        adjusted = sorted_p[rank] * m / (rank + 1)
        running_min = min(running_min, adjusted)
        adjusted_sorted[rank] = min(running_min, 1.0)

    for rank, original_idx in enumerate(order):
        out[original_idx] = adjusted_sorted[rank]
    return out


def _add_corrections(df: pd.DataFrame, p_col: str, group_cols: list[str] | None = None) -> pd.DataFrame:
    df = df.copy()
    df["p_holm"] = np.nan
    df["p_bh"] = np.nan

    if group_cols:
        groups = df.groupby(group_cols, dropna=False).groups.values()
    else:
        groups = [df.index]

    for idx in groups:
        idx = list(idx)
        p_values = df.loc[idx, p_col].to_numpy(dtype=float)
        df.loc[idx, "p_holm"] = _holm_adjust(p_values)
        df.loc[idx, "p_bh"] = _bh_adjust(p_values)

    df["significant_holm_5pct"] = df["p_holm"] < ALPHA
    df["significant_bh_5pct"] = df["p_bh"] < ALPHA
    return df


def build_clustering_summary() -> pd.DataFrame:
    soft = pd.read_csv(SOFTLIMIT_BOOTSTRAP)
    soft["experiment"] = "softlimit_liquidity_proxy"
    soft["liquidity_setting"] = "softlimit=" + soft["softlimit"].astype(str)

    depth = pd.read_csv(DEPTH_BOOTSTRAP)
    depth["experiment"] = "book_depth"
    depth["liquidity_setting"] = "book_volume=" + depth["book_volume"].astype(str)

    common_cols = [
        "experiment",
        "hft_frac",
        "info_lag",
        "liquidity_setting",
        "metric",
        "interaction_point",
        "interaction_boot_mean",
        "ci_low",
        "ci_high",
        "p_two_sided",
        "ci_excludes_zero",
        "positive_point",
    ]
    combined = pd.concat([soft[common_cols], depth[common_cols]], ignore_index=True)
    combined = _add_corrections(combined, "p_two_sided")

    combined["metric_family"] = np.where(
        combined["metric"].isin(CORE_CLUSTERING_METRICS),
        "core_clustering",
        "context",
    )
    combined["supports_original_h3"] = (
        combined["metric"].isin(CORE_CLUSTERING_METRICS)
        & combined["positive_point"]
        & combined["significant_bh_5pct"]
    )
    combined["contradicts_original_h3"] = (
        combined["metric"].isin(CORE_CLUSTERING_METRICS)
        & ~combined["positive_point"]
        & combined["significant_bh_5pct"]
    )
    return combined.sort_values(
        ["experiment", "hft_frac", "info_lag", "liquidity_setting", "metric"]
    ).reset_index(drop=True)


def build_shock_summary() -> pd.DataFrame:
    ols = pd.read_csv(SHOCK_OLS)
    ols["test"] = "OLS_HC3_delay_x_thin_book"
    ols["effect_estimate"] = ols["b3_interaction"]
    ols["effect_direction"] = np.where(ols["effect_estimate"] > 0, "worse_under_combination", "not_worse")
    ols["comparison"] = "factorial interaction"
    ols = ols[
        [
            "test",
            "hft_frac",
            "metric",
            "comparison",
            "effect_estimate",
            "effect_direction",
            "p_value",
            "ci_low",
            "ci_high",
            "n_obs",
            "n_runs",
        ]
    ]

    mw = pd.read_csv(SHOCK_MW)
    mw["test"] = "Mann_Whitney_worst_vs_best"
    mw["effect_estimate"] = mw["difference"]
    mw["effect_direction"] = np.where(mw["effect_estimate"] > 0, "worst_case_higher", "worst_case_not_higher")
    mw["comparison"] = "lag=1 thin book minus lag=0 deep book"
    mw["ci_low"] = np.nan
    mw["ci_high"] = np.nan
    mw["n_obs"] = mw["n_best"] + mw["n_worst"]
    mw["n_runs"] = mw[["n_best", "n_worst"]].min(axis=1)
    mw = mw[
        [
            "test",
            "hft_frac",
            "metric",
            "comparison",
            "effect_estimate",
            "effect_direction",
            "p_value",
            "ci_low",
            "ci_high",
            "n_obs",
            "n_runs",
        ]
    ]

    combined = pd.concat([ols, mw], ignore_index=True)
    combined = _add_corrections(combined, "p_value", group_cols=["test"])
    combined["supports_shock_absorption_h3"] = (
        combined["metric"].isin(SHOCK_METRICS)
        & (combined["effect_estimate"] > 0)
        & combined["significant_bh_5pct"]
    )
    return combined.sort_values(["test", "hft_frac", "metric"]).reset_index(drop=True)


def _count_lines(df: pd.DataFrame, label: str, support_col: str, contradiction_col: str | None = None) -> list[str]:
    lines = [f"### {label}"]
    lines.append("")
    lines.append(f"- Total tested rows: {len(df)}")
    lines.append(f"- BH-significant rows at 5%: {int(df['significant_bh_5pct'].sum())}")
    lines.append(f"- Holm-significant rows at 5%: {int(df['significant_holm_5pct'].sum())}")
    lines.append(f"- Positive/supporting rows after BH: {int(df[support_col].sum())}")
    if contradiction_col:
        lines.append(f"- Negative/contradicting rows after BH: {int(df[contradiction_col].sum())}")
    return lines


def _markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "None."

    display = df.copy()
    for col in display.columns:
        if pd.api.types.is_float_dtype(display[col]):
            display[col] = display[col].map(lambda value: "" if pd.isna(value) else f"{value:.6g}")
        else:
            display[col] = display[col].map(lambda value: "" if pd.isna(value) else str(value))

    headers = list(display.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in display.iterrows():
        lines.append("| " + " | ".join(str(row[col]) for col in headers) + " |")
    return "\n".join(lines)


def write_markdown(clustering: pd.DataFrame, shock: pd.DataFrame) -> None:
    shock_support = shock[shock["supports_shock_absorption_h3"]]
    clustering_support = clustering[clustering["supports_original_h3"]]
    clustering_negative = clustering[clustering["contradicts_original_h3"]]

    lines: list[str] = [
        "# H3 Final Statistical Summary",
        "",
        "This file is generated by `experiment_h3_final_summary.py`.",
        "It does not run new simulations; it summarizes completed H3 outputs.",
        "",
    ]
    lines.extend(_count_lines(
        clustering,
        "Original H3: delay x illiquidity -> stronger volatility clustering",
        "supports_original_h3",
        "contradicts_original_h3",
    ))
    lines.append("")
    lines.extend(_count_lines(
        shock,
        "Revised H3: delay x thin book -> weaker shock absorption",
        "supports_shock_absorption_h3",
    ))
    lines.append("")

    lines.extend([
        "## Main conclusion",
        "",
        "- The original volatility-clustering interaction is not robustly confirmed.",
        "- Several exploratory interaction cells are significant, but signs are mixed.",
        "- After correction, supporting clustering interactions exist only locally, not as a stable cross-design pattern.",
        "- The revised shock-absorption interpretation has partial support: the worst-case market has a clearly larger max drawdown, while recovery-time interaction is significant only for `hft_frac=0.2` and does not survive Holm correction across the OLS family.",
        "",
    ])

    lines.append("## Supporting clustering interactions after BH")
    lines.append("")
    if clustering_support.empty:
        lines.append("None.")
    else:
        keep = [
            "experiment", "hft_frac", "info_lag", "liquidity_setting", "metric",
            "interaction_point", "p_two_sided", "p_bh", "p_holm",
        ]
        lines.append(_markdown_table(clustering_support[keep]))
    lines.append("")

    lines.append("## Contradicting clustering interactions after BH")
    lines.append("")
    if clustering_negative.empty:
        lines.append("None.")
    else:
        keep = [
            "experiment", "hft_frac", "info_lag", "liquidity_setting", "metric",
            "interaction_point", "p_two_sided", "p_bh", "p_holm",
        ]
        lines.append(_markdown_table(clustering_negative[keep]))
    lines.append("")

    lines.append("## Shock-absorption support after BH")
    lines.append("")
    if shock_support.empty:
        lines.append("None.")
    else:
        keep = [
            "test", "hft_frac", "metric", "effect_estimate",
            "p_value", "p_bh", "p_holm", "effect_direction",
        ]
        lines.append(_markdown_table(shock_support[keep]))
    lines.append("")

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def plot_summary(clustering: pd.DataFrame, shock: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("H3 final synthesis after multiple-testing correction", fontweight="bold")

    labels = ["supporting", "contradicting", "mixed / not significant"]
    support = int(clustering["supports_original_h3"].sum())
    contradict = int(clustering["contradicts_original_h3"].sum())
    other = len(clustering) - support - contradict
    axes[0].bar(labels, [support, contradict, other], color=["#2E7D32", "#C62828", "#90A4AE"])
    axes[0].set_title("Original H3 clustering interactions")
    axes[0].set_ylabel("Number of tested cells")
    axes[0].tick_params(axis="x", rotation=20)

    shock_plot = (
        shock.assign(support=shock["supports_shock_absorption_h3"].astype(int))
        .groupby(["test", "metric"])["support"]
        .sum()
        .reset_index()
    )
    x_labels = shock_plot["test"].str.replace("_", "\n") + "\n" + shock_plot["metric"]
    axes[1].bar(np.arange(len(shock_plot)), shock_plot["support"], color="#1565C0")
    axes[1].set_xticks(np.arange(len(shock_plot)))
    axes[1].set_xticklabels(x_labels, rotation=45, ha="right")
    axes[1].set_title("Revised H3 shock-absorption support")
    axes[1].set_ylabel("BH-significant supporting phi cells")
    axes[1].set_ylim(0, max(2, int(shock_plot["support"].max()) + 1))

    for ax in axes:
        ax.grid(axis="y", alpha=0.25)

    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=160, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    missing = [str(path) for path in [SOFTLIMIT_BOOTSTRAP, DEPTH_BOOTSTRAP, SHOCK_OLS, SHOCK_MW] if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required H3 output files: " + ", ".join(missing))

    clustering = build_clustering_summary()
    shock = build_shock_summary()

    clustering.to_csv(OUT_CLUSTERING, index=False)
    shock.to_csv(OUT_SHOCK, index=False)
    plot_summary(clustering, shock)

    print("Wrote:")
    print(f"  {OUT_CLUSTERING}")
    print(f"  {OUT_SHOCK}")
    print(f"  {OUT_PNG}")


if __name__ == "__main__":
    main()
