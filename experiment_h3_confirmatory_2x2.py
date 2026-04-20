#!/usr/bin/env python3
"""
H3 confirmatory 2x2 experiment.

Focused test of the delay x thin-book interaction in the clean H3 design.

Default final run:
    python3 experiment_h3_confirmatory_2x2.py

Rebuild outputs from raw CSV:
    python3 experiment_h3_confirmatory_2x2.py --plot-from-raw
"""

from __future__ import annotations

import argparse
import math
from typing import Dict, Iterable, List, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from tqdm import tqdm

from experiment_h3_liquidity_depth import aggregate, run_one
from experiment_h3_volatility_clustering import bootstrap_ci


DEFAULT_HFT_FRACS = [0.2, 0.4]
DEFAULT_INFO_LAGS = [0, 1]
DEFAULT_BOOK_VOLUMES = [300, 1500]
DEFAULT_RUNS = 200
DEFAULT_N_ITER = 500
DEFAULT_SHOCK_IT = 200
DEFAULT_SHOCK_DP = -10
DEFAULT_SPEED_MULTIPLIER = 2
DEFAULT_SOFTLIMIT = 100
DEFAULT_RETURN_WINDOW = 10
DEFAULT_OUTPUT_PREFIX = "h3_confirmatory"

CONFIRMATORY_METRICS = [
    "acf_abs_ret_1",
    "acf_abs_ret_5",
    "high_vol_cluster_share",
    "vol_ratio",
    "vol_persistence",
]


def output_paths(prefix: str) -> Dict[str, str]:
    return {
        "raw": f"{prefix}_raw.csv",
        "agg": f"{prefix}_agg.csv",
        "cell_interactions": f"{prefix}_cell_interactions.csv",
        "run_interactions": f"{prefix}_run_interactions.csv",
        "ols": f"{prefix}_ols_hc3.csv",
        "metrics_png": f"{prefix}_metrics.png",
        "interaction_png": f"{prefix}_interactions.png",
    }


def run_experiment(args: argparse.Namespace) -> pd.DataFrame:
    rows: List[Dict[str, float]] = []
    grid = [
        (phi, lag, book_volume, run)
        for phi in args.hft_frac
        for lag in args.info_lag
        for book_volume in args.book_volume
        for run in range(args.runs)
    ]
    for phi, lag, book_volume, run in tqdm(grid, desc="H3 confirmatory 2x2"):
        rows.append(
            run_one(
                hft_frac=float(phi),
                info_lag=int(lag),
                book_volume=int(book_volume),
                run=int(run),
                n_iter=args.n_iter,
                shock_it=args.shock_it,
                shock_dp=args.shock_dp,
                speed_multiplier=args.speed_multiplier,
                softlimit=args.softlimit,
                return_window=args.return_window,
            )
        )
    return pd.DataFrame(rows)


def compute_cell_interactions(
    agg: pd.DataFrame,
    *,
    baseline_lag: int = 0,
    delay_lag: int = 1,
    thin_book_volume: int = 300,
    deep_book_volume: int = 1500,
    metrics: Iterable[str] = CONFIRMATORY_METRICS,
) -> pd.DataFrame:
    rows = []
    for phi in sorted(agg["hft_frac"].unique()):
        sub = agg[agg["hft_frac"].round(10) == round(float(phi), 10)]
        cells = {
            (int(r.info_lag), int(r.book_volume)): r for r in sub.itertuples(index=False)
        }
        base = cells[(baseline_lag, deep_book_volume)]
        delay = cells[(delay_lag, deep_book_volume)]
        thin = cells[(baseline_lag, thin_book_volume)]
        combined = cells[(delay_lag, thin_book_volume)]
        for metric in metrics:
            col = f"{metric}_mean"
            interaction = (
                getattr(combined, col)
                - getattr(delay, col)
                - getattr(thin, col)
                + getattr(base, col)
            )
            rows.append(
                {
                    "hft_frac": float(phi),
                    "metric": metric,
                    "baseline": float(getattr(base, col)),
                    "delay_only": float(getattr(delay, col)),
                    "thin_book_only": float(getattr(thin, col)),
                    "combined": float(getattr(combined, col)),
                    "interaction": float(interaction),
                }
            )
    return pd.DataFrame(rows)


def compute_run_interactions(
    raw: pd.DataFrame,
    *,
    baseline_lag: int = 0,
    delay_lag: int = 1,
    thin_book_volume: int = 300,
    deep_book_volume: int = 1500,
    metrics: Iterable[str] = CONFIRMATORY_METRICS,
) -> pd.DataFrame:
    rows = []
    for phi in sorted(raw["hft_frac"].unique()):
        sub_phi = raw[raw["hft_frac"].round(10) == round(float(phi), 10)]
        for run in sorted(sub_phi["run"].unique()):
            sub = sub_phi[sub_phi["run"] == run]
            cells = {
                (int(r.info_lag), int(r.book_volume)): r for r in sub.itertuples(index=False)
            }
            if not all(
                key in cells
                for key in [
                    (baseline_lag, deep_book_volume),
                    (delay_lag, deep_book_volume),
                    (baseline_lag, thin_book_volume),
                    (delay_lag, thin_book_volume),
                ]
            ):
                continue
            base = cells[(baseline_lag, deep_book_volume)]
            delay = cells[(delay_lag, deep_book_volume)]
            thin = cells[(baseline_lag, thin_book_volume)]
            combined = cells[(delay_lag, thin_book_volume)]
            row = {"hft_frac": float(phi), "run": int(run)}
            for metric in metrics:
                row[f"interaction_{metric}"] = float(
                    getattr(combined, metric)
                    - getattr(delay, metric)
                    - getattr(thin, metric)
                    + getattr(base, metric)
                )
            rows.append(row)
    return pd.DataFrame(rows)


def summarize_run_interactions(
    run_interactions: pd.DataFrame,
    *,
    metrics: Iterable[str] = CONFIRMATORY_METRICS,
) -> pd.DataFrame:
    rows = []
    for phi, sub in run_interactions.groupby("hft_frac"):
        for metric in metrics:
            col = f"interaction_{metric}"
            values = sub[col].dropna().to_numpy(dtype=float)
            lo, hi = bootstrap_ci(values)
            rows.append(
                {
                    "hft_frac": float(phi),
                    "metric": metric,
                    "n_runs": int(len(values)),
                    "run_interaction_mean": float(np.mean(values)),
                    "run_interaction_std": float(np.std(values, ddof=1)),
                    "ci_low": lo,
                    "ci_high": hi,
                    "positive_share": float(np.mean(values > 0)),
                }
            )
    return pd.DataFrame(rows)


def _normal_p_value(t_value: float) -> float:
    return float(math.erfc(abs(t_value) / math.sqrt(2.0)))


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


def fit_ols_hc3(
    raw: pd.DataFrame,
    *,
    metrics: Iterable[str] = CONFIRMATORY_METRICS,
    thin_book_volume: int = 300,
) -> pd.DataFrame:
    rows = []
    for phi, sub in raw.groupby("hft_frac"):
        sub = sub.copy().sort_values(["run", "info_lag", "book_volume"]).reset_index(drop=True)
        delay = (sub["info_lag"].astype(int) == 1).astype(float).to_numpy()
        thin = (sub["book_volume"].astype(int) == thin_book_volume).astype(float).to_numpy()
        interaction = delay * thin

        runs = sorted(sub["run"].astype(int).unique())
        run_to_idx = {run: idx for idx, run in enumerate(runs[1:])}
        run_dummies = np.zeros((len(sub), max(len(runs) - 1, 0)), dtype=float)
        for i, run in enumerate(sub["run"].astype(int).to_numpy()):
            if run in run_to_idx:
                run_dummies[i, run_to_idx[run]] = 1.0

        x = np.column_stack(
            [
                np.ones(len(sub), dtype=float),
                delay,
                thin,
                interaction,
                run_dummies,
            ]
        )
        for metric in metrics:
            y = sub[metric].to_numpy(dtype=float)
            result = _ols_hc3(y, x)
            beta = float(result["beta"][3])
            se = float(result["se"][3])
            t_value = beta / se if se > 0 else np.nan
            p_value = _normal_p_value(t_value) if np.isfinite(t_value) else np.nan
            rows.append(
                {
                    "hft_frac": float(phi),
                    "metric": metric,
                    "n_obs": int(len(sub)),
                    "n_runs": int(len(runs)),
                    "coef_delay_x_thin": beta,
                    "se_hc3": se,
                    "t_hc3": float(t_value),
                    "p_normal_approx": float(p_value),
                    "ci_low": beta - 1.96 * se,
                    "ci_high": beta + 1.96 * se,
                    "positive": bool(beta > 0),
                    "ci_excludes_zero": bool((beta - 1.96 * se > 0) or (beta + 1.96 * se < 0)),
                }
            )
    return pd.DataFrame(rows)


def plot_metrics(agg: pd.DataFrame, output_path: str) -> None:
    metrics = [
        ("acf_abs_ret_1", "ACF |returns| lag 1"),
        ("acf_abs_ret_5", "ACF |returns| lag 5"),
        ("high_vol_cluster_share", "High-vol cluster share"),
        ("vol_ratio", "Volatility ratio"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), sharex=True)
    axes = axes.ravel()
    for ax, (metric, title) in zip(axes, metrics):
        for lag in sorted(agg["info_lag"].unique()):
            for book_volume, style in [(300, "-"), (1500, "--")]:
                sub = agg[
                    (agg["info_lag"] == lag) & (agg["book_volume"] == book_volume)
                ].sort_values("hft_frac")
                label = f"lag={lag}, book={book_volume}"
                ax.plot(
                    sub["hft_frac"],
                    sub[f"{metric}_mean"],
                    marker="o",
                    linestyle=style,
                    label=label,
                )
                ax.fill_between(
                    sub["hft_frac"],
                    sub[f"{metric}_ci_low"],
                    sub[f"{metric}_ci_high"],
                    alpha=0.12,
                    linewidth=0,
                )
        ax.set_title(title)
        ax.set_xlabel("HFT share phi")
        ax.set_ylabel(metric)
        ax.grid(True, alpha=0.25)
    axes[0].legend(fontsize=8)
    fig.suptitle("H3 confirmatory 2x2 metrics", fontsize=15, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def plot_interactions(ols: pd.DataFrame, run_summary: pd.DataFrame, output_path: str) -> None:
    metrics = ["acf_abs_ret_1", "acf_abs_ret_5", "high_vol_cluster_share", "vol_ratio"]
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), sharey=False)
    axes = axes.ravel()
    for ax, metric in zip(axes, metrics):
        ols_sub = ols[ols["metric"] == metric].sort_values("hft_frac")
        run_sub = run_summary[run_summary["metric"] == metric].sort_values("hft_frac")
        x = np.arange(len(ols_sub))
        ax.errorbar(
            x - 0.08,
            ols_sub["coef_delay_x_thin"],
            yerr=[
                ols_sub["coef_delay_x_thin"] - ols_sub["ci_low"],
                ols_sub["ci_high"] - ols_sub["coef_delay_x_thin"],
            ],
            fmt="o",
            capsize=4,
            label="OLS run FE + HC3",
        )
        ax.errorbar(
            x + 0.08,
            run_sub["run_interaction_mean"],
            yerr=[
                run_sub["run_interaction_mean"] - run_sub["ci_low"],
                run_sub["ci_high"] - run_sub["run_interaction_mean"],
            ],
            fmt="s",
            capsize=4,
            label="paired run interaction",
        )
        ax.axhline(0, color="black", linewidth=0.9)
        ax.set_xticks(x)
        ax.set_xticklabels([f"phi={v:g}" for v in ols_sub["hft_frac"]])
        ax.set_title(metric)
        ax.grid(True, alpha=0.25)
    axes[0].legend(fontsize=9)
    fig.suptitle("H3 confirmatory interaction estimates", fontsize=15, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def write_outputs(raw: pd.DataFrame, prefix: str) -> Dict[str, pd.DataFrame]:
    paths = output_paths(prefix)
    agg = aggregate(raw)
    cell_interactions = compute_cell_interactions(agg)
    run_interactions = compute_run_interactions(raw)
    run_summary = summarize_run_interactions(run_interactions)
    ols = fit_ols_hc3(raw)

    raw.to_csv(paths["raw"], index=False)
    agg.to_csv(paths["agg"], index=False)
    cell_interactions.to_csv(paths["cell_interactions"], index=False)
    run_interactions.to_csv(paths["run_interactions"], index=False)
    ols.to_csv(paths["ols"], index=False)

    plot_metrics(agg, paths["metrics_png"])
    plot_interactions(ols, run_summary, paths["interaction_png"])

    summary = ols.merge(
        run_summary,
        on=["hft_frac", "metric"],
        how="left",
        suffixes=("_ols", "_run"),
    )
    print("\nConfirmatory interaction summary:")
    cols = [
        "hft_frac",
        "metric",
        "coef_delay_x_thin",
        "se_hc3",
        "ci_low_ols",
        "ci_high_ols",
        "p_normal_approx",
        "run_interaction_mean",
        "ci_low_run",
        "ci_high_run",
        "positive_share",
    ]
    # Column names after merge are clearer if normalized here.
    summary = summary.rename(
        columns={
            "ci_low_ols": "ci_low_ols",
            "ci_high_ols": "ci_high_ols",
            "ci_low_run": "ci_low_run",
            "ci_high_run": "ci_high_run",
        }
    )
    if "ci_low_ols" not in summary.columns:
        summary = summary.rename(columns={"ci_low": "ci_low_ols", "ci_high": "ci_high_ols"})
    if "ci_low_run" not in summary.columns:
        summary = summary.rename(
            columns={"ci_low_run": "ci_low_run", "ci_high_run": "ci_high_run"}
        )
    display_cols = [c for c in cols if c in summary.columns]
    print(summary[display_cols].round(6).to_string(index=False))
    print("\nSaved:")
    for path in paths.values():
        print(f"  {path}")
    return {
        "raw": raw,
        "agg": agg,
        "cell_interactions": cell_interactions,
        "run_interactions": run_interactions,
        "run_summary": run_summary,
        "ols": ols,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run H3 confirmatory 2x2 experiment.")
    parser.add_argument("--hft-frac", type=float, nargs="+", default=DEFAULT_HFT_FRACS)
    parser.add_argument("--info-lag", type=int, nargs="+", default=DEFAULT_INFO_LAGS)
    parser.add_argument("--book-volume", type=int, nargs="+", default=DEFAULT_BOOK_VOLUMES)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--n-iter", type=int, default=DEFAULT_N_ITER)
    parser.add_argument("--shock-it", type=int, default=DEFAULT_SHOCK_IT)
    parser.add_argument("--shock-dp", type=float, default=DEFAULT_SHOCK_DP)
    parser.add_argument("--speed-multiplier", type=int, default=DEFAULT_SPEED_MULTIPLIER)
    parser.add_argument("--softlimit", type=int, default=DEFAULT_SOFTLIMIT)
    parser.add_argument("--return-window", type=int, default=DEFAULT_RETURN_WINDOW)
    parser.add_argument("--output-prefix", default=DEFAULT_OUTPUT_PREFIX)
    parser.add_argument("--plot-from-raw", action="store_true")
    return parser.parse_args()


def validate_grid(args: argparse.Namespace) -> None:
    if sorted(args.info_lag) != [0, 1]:
        raise ValueError("Confirmatory design requires --info-lag 0 1.")
    if sorted(args.book_volume) != [300, 1500]:
        raise ValueError("Confirmatory design requires --book-volume 300 1500.")


def main() -> None:
    args = parse_args()
    validate_grid(args)
    paths = output_paths(args.output_prefix)
    if args.plot_from_raw:
        raw = pd.read_csv(paths["raw"])
    else:
        raw = run_experiment(args)
    write_outputs(raw, args.output_prefix)


if __name__ == "__main__":
    sns.set_theme(style="whitegrid")
    main()
