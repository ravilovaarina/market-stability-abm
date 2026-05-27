"""
H3: volatility clustering from information delay and liquidity constraints.

This experiment runs on the H1 unified calendar-time environment. It changes
two factors:
  - information delay: info_lag
  - liquidity constraint: MarketMaker softlimit

Main H3 metrics are autocorrelations of absolute post-shock price returns and
rolling-volatility persistence. Standard H1 metrics are also kept for context.

Default final run:
    python experiments/h3/experiment_h3_volatility_clustering.py

Rebuild plots / aggregate files from existing raw CSV:
    python experiments/h3/experiment_h3_volatility_clustering.py --plot-from-raw
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

os.environ.setdefault("MPLCONFIGDIR", "/tmp/1d-abm-mplconfig")
os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from AgentBasedModel.agents import ExchangeAgent
from AgentBasedModel.events import MarketPriceShock
from experiments.h1.experiment_unified import (
    SimulatorUnified,
    create_population,
    max_drawdown,
    recovery_time,
    spread_ratio,
    vol_ratio,
)


DEFAULT_HFT_FRACS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
DEFAULT_INFO_LAGS = [0, 1, 3, 5, 10]
DEFAULT_SOFTLIMITS = [20, 50, 100]
DEFAULT_RUNS = 30
DEFAULT_N_ITER = 500
DEFAULT_SHOCK_IT = 200
DEFAULT_SHOCK_DP = -10
DEFAULT_SPEED_MULTIPLIER = 2
DEFAULT_OUTPUT_PREFIX = "h3_clustering"
OUTPUT_ROOT = PROJECT_ROOT / "results" / "h3" / "clustering"

STANDARD_METRICS = [
    "vol_ratio",
    "spread_ratio",
    "max_drawdown",
    "recovery_time",
    "mm_panic_ratio",
]

CLUSTERING_METRICS = [
    "acf_abs_ret_1",
    "acf_abs_ret_5",
    "vol_persistence",
    "high_vol_cluster_share",
]

ALL_METRICS = STANDARD_METRICS + CLUSTERING_METRICS


def safe_corr(x: Sequence[float], y: Sequence[float]) -> float:
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    mask = np.isfinite(x_arr) & np.isfinite(y_arr)
    x_arr = x_arr[mask]
    y_arr = y_arr[mask]
    if len(x_arr) < 3 or len(y_arr) < 3:
        return 0.0
    if np.std(x_arr) < 1e-12 or np.std(y_arr) < 1e-12:
        return 0.0
    return float(np.corrcoef(x_arr, y_arr)[0, 1])


def price_returns(prices: Sequence[float]) -> np.ndarray:
    prices_arr = np.asarray(prices, dtype=float)
    if len(prices_arr) < 2:
        return np.array([], dtype=float)
    prev = prices_arr[:-1]
    nxt = prices_arr[1:]
    mask = np.isfinite(prev) & np.isfinite(nxt) & (np.abs(prev) > 1e-12)
    returns = np.zeros_like(prev, dtype=float)
    returns[mask] = (nxt[mask] - prev[mask]) / prev[mask]
    returns[~mask] = np.nan
    return returns


def autocorr_abs_returns(returns: np.ndarray, lag: int) -> float:
    abs_returns = np.abs(np.asarray(returns, dtype=float))
    if lag <= 0 or len(abs_returns) <= lag + 2:
        return 0.0
    return safe_corr(abs_returns[lag:], abs_returns[:-lag])


def rolling_std(values: np.ndarray, window: int) -> np.ndarray:
    if len(values) < window:
        return np.array([], dtype=float)
    return (
        pd.Series(values, dtype="float64")
        .rolling(window=window, min_periods=window)
        .std()
        .to_numpy()
    )


def clustering_metrics(info, shock_it=200, return_window=10) -> Dict[str, float]:
    returns = price_returns(info.prices)
    if len(returns) == 0:
        return {
            "acf_abs_ret_1": 0.0,
            "acf_abs_ret_5": 0.0,
            "vol_persistence": 0.0,
            "high_vol_cluster_share": 0.0,
        }

    pre_returns = returns[: max(shock_it - 1, 0)]
    post_returns = returns[shock_it:]

    acf1 = autocorr_abs_returns(post_returns, lag=1)
    acf5 = autocorr_abs_returns(post_returns, lag=5)

    rolling = rolling_std(returns, window=return_window)
    if len(rolling) == 0:
        vol_persistence = 0.0
        high_vol_share = 0.0
    else:
        # Rolling value at index i summarizes returns ending around i + window - 1.
        split = max(shock_it - return_window, 0)
        pre_vol = rolling[:split]
        post_vol = rolling[shock_it:]

        vol_persistence = safe_corr(post_vol[1:], post_vol[:-1]) if len(post_vol) > 3 else 0.0

        pre_vol = pre_vol[np.isfinite(pre_vol)]
        post_vol = post_vol[np.isfinite(post_vol)]
        if len(pre_vol) > 3 and len(post_vol) > 0:
            threshold = float(np.quantile(pre_vol, 0.9))
            high_vol_share = float(np.mean(post_vol > threshold))
        else:
            high_vol_share = 0.0

    return {
        "acf_abs_ret_1": acf1,
        "acf_abs_ret_5": acf5,
        "vol_persistence": vol_persistence,
        "high_vol_cluster_share": high_vol_share,
    }


def run_one(
    hft_frac: float,
    info_lag: int,
    softlimit: int,
    run: int,
    n_iter: int,
    shock_it: int,
    shock_dp: float,
    speed_multiplier: int,
    return_window: int,
) -> Dict[str, float]:
    seed = (
        run * 100000
        + int(hft_frac * 10) * 1000
        + int(info_lag) * 100
        + int(softlimit)
        + int(speed_multiplier)
    )
    random.seed(seed)
    np.random.seed(seed)

    exchange = ExchangeAgent(price=100, std=25, volume=1000, rf=5e-4)
    traders = create_population(
        exchange,
        n_chartists=10,
        n_fundamentalists=10,
        n_random=5,
        n_mm=1,
        hft_frac=hft_frac,
        info_lag=info_lag,
        softlimit=softlimit,
    )
    sim = SimulatorUnified(
        exchange=exchange,
        traders=traders,
        events=[MarketPriceShock(shock_it, shock_dp)],
    )
    sim.simulate(n_iter, silent=True, speed_multiplier=speed_multiplier)
    info = sim.info

    row = {
        "run": run,
        "seed": seed,
        "hft_frac": hft_frac,
        "info_lag": info_lag,
        "softlimit": softlimit,
        "speed_mult": speed_multiplier,
        "n_iter": n_iter,
        "shock_it": shock_it,
        "shock_dp": shock_dp,
        "vol_ratio": vol_ratio(info, shock_it),
        "spread_ratio": spread_ratio(info, shock_it),
        "max_drawdown": max_drawdown(info, shock_it),
        "recovery_time": recovery_time(info, shock_it),
        "mm_panic_ratio": info.mm_panic_ratio(from_it=shock_it),
    }
    row.update(clustering_metrics(info, shock_it=shock_it, return_window=return_window))
    return row


def bootstrap_ci(data: Sequence[float], n_bootstrap=1000, ci=0.95, seed=42):
    values = np.asarray(data, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return np.nan, np.nan
    rng = np.random.RandomState(seed)
    means = [np.mean(rng.choice(values, size=len(values), replace=True)) for _ in range(n_bootstrap)]
    alpha = (1 - ci) / 2
    return tuple(np.percentile(means, [alpha * 100, (1 - alpha) * 100]))


def aggregate(raw: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["info_lag", "softlimit", "hft_frac"]
    rows = []
    for keys, sub in raw.groupby(group_cols):
        row = dict(zip(group_cols, keys))
        row["n_runs"] = len(sub)
        for metric in ALL_METRICS:
            values = sub[metric].dropna().values
            row[f"{metric}_mean"] = float(np.mean(values)) if len(values) else np.nan
            row[f"{metric}_std"] = float(np.std(values, ddof=1)) if len(values) > 1 else np.nan
            lo, hi = bootstrap_ci(values)
            row[f"{metric}_ci_low"] = lo
            row[f"{metric}_ci_high"] = hi
        rows.append(row)
    return pd.DataFrame(rows).sort_values(group_cols).reset_index(drop=True)


def compute_interactions(
    agg: pd.DataFrame,
    baseline_lag: int = 0,
    baseline_softlimit: int = 100,
) -> pd.DataFrame:
    metrics = CLUSTERING_METRICS + ["vol_ratio"]
    rows = []
    index = {
        (float(r.hft_frac), int(r.info_lag), int(r.softlimit)): r
        for r in agg.itertuples(index=False)
    }

    hft_fracs = sorted(agg["hft_frac"].unique())
    lags = [int(x) for x in sorted(agg["info_lag"].unique()) if int(x) != baseline_lag]
    softlimits = [
        int(x)
        for x in sorted(agg["softlimit"].unique())
        if int(x) != baseline_softlimit
    ]

    for phi in hft_fracs:
        for lag in lags:
            for softlimit in softlimits:
                base = index.get((float(phi), baseline_lag, baseline_softlimit))
                delay = index.get((float(phi), lag, baseline_softlimit))
                liquidity = index.get((float(phi), baseline_lag, softlimit))
                combined = index.get((float(phi), lag, softlimit))
                if base is None or delay is None or liquidity is None or combined is None:
                    continue
                row = {
                    "hft_frac": phi,
                    "info_lag": lag,
                    "softlimit": softlimit,
                    "baseline_lag": baseline_lag,
                    "baseline_softlimit": baseline_softlimit,
                }
                for metric in metrics:
                    col = f"{metric}_mean"
                    value = (
                        getattr(combined, col)
                        - getattr(delay, col)
                        - getattr(liquidity, col)
                        + getattr(base, col)
                    )
                    row[f"interaction_{metric}"] = float(value)
                    row[f"baseline_{metric}"] = float(getattr(base, col))
                    row[f"delay_only_{metric}"] = float(getattr(delay, col))
                    row[f"liquidity_only_{metric}"] = float(getattr(liquidity, col))
                    row[f"combined_{metric}"] = float(getattr(combined, col))
                rows.append(row)
    return pd.DataFrame(rows)


def output_paths(prefix: str) -> Dict[str, str]:
    return {
        "raw": str(OUTPUT_ROOT / "raw" / f"{prefix}_raw.csv"),
        "agg": str(OUTPUT_ROOT / "tables" / f"{prefix}_agg.csv"),
        "interactions": str(OUTPUT_ROOT / "tables" / f"{prefix}_interactions.csv"),
        "metrics_png": str(OUTPUT_ROOT / "figures" / f"{prefix}_metrics.png"),
        "heatmap_acf1_png": str(OUTPUT_ROOT / "figures" / f"{prefix}_heatmap_acf1.png"),
        "heatmap_interaction_png": str(OUTPUT_ROOT / "figures" / f"{prefix}_heatmap_interaction.png"),
    }


def plot_metrics(raw: pd.DataFrame, agg: pd.DataFrame, output_path: str):
    metrics = [
        ("acf_abs_ret_1", "ACF |returns| lag 1"),
        ("acf_abs_ret_5", "ACF |returns| lag 5"),
        ("vol_persistence", "Rolling volatility persistence"),
        ("high_vol_cluster_share", "High-volatility cluster share"),
        ("vol_ratio", "Volatility ratio"),
    ]
    softlimits = sorted(agg["softlimit"].unique())
    lags = sorted(agg["info_lag"].unique())
    colors = plt.cm.viridis(np.linspace(0.1, 0.9, len(lags)))

    fig, axes = plt.subplots(
        len(metrics),
        len(softlimits),
        figsize=(5.2 * len(softlimits), 3.4 * len(metrics)),
        sharex=True,
    )
    if len(metrics) == 1:
        axes = np.array([axes])
    if len(softlimits) == 1:
        axes = axes.reshape(len(metrics), 1)

    for row_idx, (metric, title) in enumerate(metrics):
        for col_idx, softlimit in enumerate(softlimits):
            ax = axes[row_idx, col_idx]
            for lag, color in zip(lags, colors):
                data = agg[(agg["softlimit"] == softlimit) & (agg["info_lag"] == lag)]
                if data.empty:
                    continue
                ax.plot(
                    data["hft_frac"],
                    data[f"{metric}_mean"],
                    marker="o",
                    linewidth=1.8,
                    label=f"lag={lag}",
                    color=color,
                )
                ax.fill_between(
                    data["hft_frac"],
                    data[f"{metric}_ci_low"],
                    data[f"{metric}_ci_high"],
                    color=color,
                    alpha=0.12,
                    linewidth=0,
                )
            ax.axhline(0, color="black", linewidth=0.7, alpha=0.45)
            ax.set_title(f"{title}, softlimit={softlimit}")
            ax.set_xlabel("HFT share phi")
            ax.grid(True, alpha=0.25)
            if col_idx == 0:
                ax.set_ylabel(metric)
            if row_idx == 0 and col_idx == len(softlimits) - 1:
                ax.legend(frameon=False, fontsize=8)

    fig.suptitle("H3: volatility clustering metrics by delay and liquidity constraint", y=0.995)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def plot_acf_heatmap(agg: pd.DataFrame, output_path: str):
    softlimits = sorted(agg["softlimit"].unique())
    fig, axes = plt.subplots(1, len(softlimits), figsize=(5.6 * len(softlimits), 4.6), sharey=True)
    if len(softlimits) == 1:
        axes = [axes]

    for ax, softlimit in zip(axes, softlimits):
        sub = agg[agg["softlimit"] == softlimit]
        pivot = sub.pivot(index="info_lag", columns="hft_frac", values="acf_abs_ret_1_mean")
        sns.heatmap(pivot, annot=True, fmt=".2f", cmap="RdYlBu_r", center=0, ax=ax)
        ax.set_title(f"ACF |returns| lag 1, softlimit={softlimit}")
        ax.set_xlabel("HFT share phi")
        ax.set_ylabel("info_lag")

    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def plot_interaction_heatmap(interactions: pd.DataFrame, output_path: str):
    if interactions.empty:
        return
    softlimits = sorted(interactions["softlimit"].unique())
    fig, axes = plt.subplots(1, len(softlimits), figsize=(5.8 * len(softlimits), 4.6), sharey=True)
    if len(softlimits) == 1:
        axes = [axes]

    for ax, softlimit in zip(axes, softlimits):
        sub = interactions[interactions["softlimit"] == softlimit]
        pivot = sub.pivot(index="info_lag", columns="hft_frac", values="interaction_acf_abs_ret_1")
        sns.heatmap(pivot, annot=True, fmt=".2f", cmap="RdYlGn", center=0, ax=ax)
        ax.set_title(f"Interaction in ACF lag 1, softlimit={softlimit}")
        ax.set_xlabel("HFT share phi")
        ax.set_ylabel("info_lag")

    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def summarize_results(agg: pd.DataFrame, interactions: pd.DataFrame) -> str:
    lines = []
    best_acf = agg.sort_values("acf_abs_ret_1_mean", ascending=False).head(5)
    lines.append("Top ACF |returns| lag 1 regimes:")
    lines.append(best_acf[["info_lag", "softlimit", "hft_frac", "acf_abs_ret_1_mean", "vol_ratio_mean"]].to_string(index=False))
    if not interactions.empty:
        best_inter = interactions.sort_values("interaction_acf_abs_ret_1", ascending=False).head(8)
        lines.append("\nTop positive interaction terms for ACF lag 1:")
        lines.append(best_inter[["info_lag", "softlimit", "hft_frac", "interaction_acf_abs_ret_1"]].to_string(index=False))
    return "\n".join(lines)


def run_experiment(args):
    paths = output_paths(args.output_prefix)

    if args.plot_from_raw:
        raw = pd.read_csv(paths["raw"])
        agg = aggregate(raw)
        interactions = compute_interactions(
            agg,
            baseline_lag=min(args.info_lag),
            baseline_softlimit=max(args.softlimit),
        )
        agg.to_csv(paths["agg"], index=False)
        interactions.to_csv(paths["interactions"], index=False)
        if not args.no_plots:
            plot_metrics(raw, agg, paths["metrics_png"])
            plot_acf_heatmap(agg, paths["heatmap_acf1_png"])
            plot_interaction_heatmap(interactions, paths["heatmap_interaction_png"])
        print("\nRebuilt from raw CSV:")
        print(f"  {paths['agg']}")
        print(f"  {paths['interactions']}")
        if not args.no_plots:
            print(f"  {paths['metrics_png']}")
            print(f"  {paths['heatmap_acf1_png']}")
            print(f"  {paths['heatmap_interaction_png']}")
        print("\n" + summarize_results(agg, interactions))
        return raw, agg, interactions

    records: List[Dict[str, float]] = []
    total = len(args.info_lag) * len(args.softlimit) * len(args.hft_frac) * args.runs
    progress = tqdm(total=total, desc="H3 clustering grid")

    for lag in args.info_lag:
        for softlimit in args.softlimit:
            for phi in args.hft_frac:
                for run in range(args.runs):
                    records.append(
                        run_one(
                            hft_frac=phi,
                            info_lag=lag,
                            softlimit=softlimit,
                            run=run,
                            n_iter=args.n_iter,
                            shock_it=args.shock_it,
                            shock_dp=args.shock_dp,
                            speed_multiplier=args.speed_multiplier,
                            return_window=args.return_window,
                        )
                    )
                    progress.update(1)
    progress.close()

    raw = pd.DataFrame(records)
    agg = aggregate(raw)
    interactions = compute_interactions(
        agg,
        baseline_lag=min(args.info_lag),
        baseline_softlimit=max(args.softlimit),
    )

    raw.to_csv(paths["raw"], index=False)
    agg.to_csv(paths["agg"], index=False)
    interactions.to_csv(paths["interactions"], index=False)

    if not args.no_plots:
        plot_metrics(raw, agg, paths["metrics_png"])
        plot_acf_heatmap(agg, paths["heatmap_acf1_png"])
        plot_interaction_heatmap(interactions, paths["heatmap_interaction_png"])

    print("\nSaved:")
    for key in ["raw", "agg", "interactions"]:
        print(f"  {paths[key]}")
    if not args.no_plots:
        for key in ["metrics_png", "heatmap_acf1_png", "heatmap_interaction_png"]:
            print(f"  {paths[key]}")

    print("\n" + summarize_results(agg, interactions))
    return raw, agg, interactions


def parse_args():
    parser = argparse.ArgumentParser(description="Run H3 volatility clustering experiment.")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--n-iter", type=int, default=DEFAULT_N_ITER)
    parser.add_argument("--shock-it", type=int, default=DEFAULT_SHOCK_IT)
    parser.add_argument("--shock-dp", type=float, default=DEFAULT_SHOCK_DP)
    parser.add_argument("--speed-multiplier", type=int, default=DEFAULT_SPEED_MULTIPLIER)
    parser.add_argument("--hft-frac", type=float, nargs="+", default=DEFAULT_HFT_FRACS)
    parser.add_argument("--info-lag", type=int, nargs="+", default=DEFAULT_INFO_LAGS)
    parser.add_argument("--softlimit", type=int, nargs="+", default=DEFAULT_SOFTLIMITS)
    parser.add_argument("--return-window", type=int, default=10)
    parser.add_argument("--output-prefix", default=DEFAULT_OUTPUT_PREFIX)
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument("--plot-from-raw", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run_experiment(parse_args())
