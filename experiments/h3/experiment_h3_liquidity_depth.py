"""
H3-clean: shock absorption from information delay and order-book depth.

This is a cleaner H3 follow-up. Instead of using MarketMaker softlimit as the
liquidity proxy, it varies the initial order-book depth via ExchangeAgent.volume.
The revised H3 interpretation focuses on whether the market absorbs the shock
better or worse, so the raw output includes recovery time and post-shock
stabilization-price metrics in addition to the earlier clustering diagnostics.

Default final run:
    python experiments/h3/experiment_h3_liquidity_depth.py

Rebuild plots / aggregates from existing raw CSV:
    python experiments/h3/experiment_h3_liquidity_depth.py --plot-from-raw
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path
from typing import Dict, List, Sequence

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
from experiments.h3.experiment_h3_volatility_clustering import (
    ALL_METRICS,
    CLUSTERING_METRICS,
    STANDARD_METRICS,
    bootstrap_ci,
    clustering_metrics,
)
from experiments.h1.experiment_unified import (
    SimulatorUnified,
    create_population,
    max_drawdown,
    recovery_time,
    spread_ratio,
    vol_ratio,
)


DEFAULT_HFT_FRACS = [0.0, 0.2, 0.4, 0.6]
DEFAULT_INFO_LAGS = [0, 1, 3, 5]
DEFAULT_BOOK_VOLUMES = [300, 600, 1000, 1500]
DEFAULT_RUNS = 30
DEFAULT_N_ITER = 500
DEFAULT_SHOCK_IT = 200
DEFAULT_SHOCK_DP = -10
DEFAULT_SPEED_MULTIPLIER = 2
DEFAULT_SOFTLIMIT = 100
DEFAULT_OUTPUT_PREFIX = "h3_depth"
OUTPUT_ROOT = PROJECT_ROOT / "results" / "h3" / "depth"
STABILIZATION_WINDOW = 50

SHOCK_ABSORPTION_METRICS = [
    "stabilization_price",
    "stabilization_price_ratio",
    "stabilization_gap",
]

ALL_DEPTH_METRICS = ALL_METRICS + SHOCK_ABSORPTION_METRICS


def stabilization_metrics(info, shock_it: int = 200, window: int = STABILIZATION_WINDOW) -> Dict[str, float]:
    """Measure the price level where the market settles after the shock.

    `stabilization_price` is the mean price in the last `window` simulated
    iterations. `stabilization_gap` is expressed relative to the pre-shock
    price, so larger values mean a worse post-shock stabilization level.
    """
    if len(info.prices) <= shock_it:
        return {
            "stabilization_price": np.nan,
            "stabilization_price_ratio": np.nan,
            "stabilization_gap": np.nan,
        }

    pre_price = float(info.prices[shock_it - 1])
    tail = info.prices[max(shock_it, len(info.prices) - window):]
    stabilization_price = float(np.mean(tail)) if tail else np.nan
    if not np.isfinite(pre_price) or abs(pre_price) < 1e-12:
        ratio = np.nan
    else:
        ratio = stabilization_price / pre_price
    return {
        "stabilization_price": stabilization_price,
        "stabilization_price_ratio": ratio,
        "stabilization_gap": 1.0 - ratio if np.isfinite(ratio) else np.nan,
    }


def run_one(
    hft_frac: float,
    info_lag: int,
    book_volume: int,
    run: int,
    n_iter: int,
    shock_it: int,
    shock_dp: float,
    speed_multiplier: int,
    softlimit: int,
    return_window: int,
) -> Dict[str, float]:
    seed = (
        run * 1000000
        + int(round(hft_frac * 10)) * 10000
        + int(info_lag) * 1000
        + int(book_volume)
        + int(speed_multiplier) * 10
    )
    random.seed(seed)
    np.random.seed(seed)

    exchange = ExchangeAgent(price=100, std=25, volume=book_volume, rf=5e-4)
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
        "book_volume": book_volume,
        "speed_mult": speed_multiplier,
        "softlimit": softlimit,
        "n_iter": n_iter,
        "shock_it": shock_it,
        "shock_dp": shock_dp,
        "vol_ratio": vol_ratio(info, shock_it),
        "spread_ratio": spread_ratio(info, shock_it),
        "max_drawdown": max_drawdown(info, shock_it),
        "recovery_time": recovery_time(info, shock_it),
        "mm_panic_ratio": info.mm_panic_ratio(from_it=shock_it),
    }
    row.update(stabilization_metrics(info, shock_it=shock_it))
    row.update(clustering_metrics(info, shock_it=shock_it, return_window=return_window))
    return row


def aggregate(raw: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["info_lag", "book_volume", "hft_frac"]
    rows = []
    for keys, sub in raw.groupby(group_cols):
        row = dict(zip(group_cols, keys))
        row["n_runs"] = len(sub)
        for metric in ALL_DEPTH_METRICS:
            if metric not in sub.columns:
                continue
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
    baseline_book_volume: int = 1500,
) -> pd.DataFrame:
    metrics = CLUSTERING_METRICS + ["vol_ratio"]
    rows = []
    index = {
        (float(r.hft_frac), int(r.info_lag), int(r.book_volume)): r
        for r in agg.itertuples(index=False)
    }

    hft_fracs = sorted(agg["hft_frac"].unique())
    lags = [int(x) for x in sorted(agg["info_lag"].unique()) if int(x) != baseline_lag]
    book_volumes = [
        int(x)
        for x in sorted(agg["book_volume"].unique())
        if int(x) != baseline_book_volume
    ]

    for phi in hft_fracs:
        for lag in lags:
            for book_volume in book_volumes:
                base = index.get((float(phi), baseline_lag, baseline_book_volume))
                delay = index.get((float(phi), lag, baseline_book_volume))
                liquidity = index.get((float(phi), baseline_lag, book_volume))
                combined = index.get((float(phi), lag, book_volume))
                if base is None or delay is None or liquidity is None or combined is None:
                    continue
                row = {
                    "hft_frac": phi,
                    "info_lag": lag,
                    "book_volume": book_volume,
                    "baseline_lag": baseline_lag,
                    "baseline_book_volume": baseline_book_volume,
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
    del raw
    metrics = [
        ("acf_abs_ret_1", "ACF |returns| lag 1"),
        ("acf_abs_ret_5", "ACF |returns| lag 5"),
        ("high_vol_cluster_share", "High-volatility cluster share"),
        ("vol_ratio", "Volatility ratio"),
        ("mm_panic_ratio", "MM panic ratio"),
    ]
    book_volumes = sorted(agg["book_volume"].unique())
    lags = sorted(agg["info_lag"].unique())
    colors = plt.cm.viridis(np.linspace(0.1, 0.9, len(lags)))

    fig, axes = plt.subplots(
        len(metrics),
        len(book_volumes),
        figsize=(5.0 * len(book_volumes), 3.2 * len(metrics)),
        sharex=True,
    )
    if len(metrics) == 1:
        axes = np.array([axes])
    if len(book_volumes) == 1:
        axes = axes.reshape(len(metrics), 1)

    for row_idx, (metric, title) in enumerate(metrics):
        for col_idx, book_volume in enumerate(book_volumes):
            ax = axes[row_idx, col_idx]
            for lag, color in zip(lags, colors):
                data = agg[(agg["book_volume"] == book_volume) & (agg["info_lag"] == lag)]
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
            ax.set_title(f"{title}, book_volume={book_volume}")
            ax.set_xlabel("HFT share phi")
            ax.grid(True, alpha=0.25)
            if col_idx == 0:
                ax.set_ylabel(metric)
            if row_idx == 0 and col_idx == len(book_volumes) - 1:
                ax.legend(frameon=False, fontsize=8)

    fig.suptitle("H3-clean: volatility clustering by delay and order-book depth", y=0.995)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def plot_acf_heatmap(agg: pd.DataFrame, output_path: str):
    book_volumes = sorted(agg["book_volume"].unique())
    fig, axes = plt.subplots(1, len(book_volumes), figsize=(5.1 * len(book_volumes), 4.5), sharey=True)
    if len(book_volumes) == 1:
        axes = [axes]

    for ax, book_volume in zip(axes, book_volumes):
        sub = agg[agg["book_volume"] == book_volume]
        pivot = sub.pivot(index="info_lag", columns="hft_frac", values="acf_abs_ret_1_mean")
        sns.heatmap(pivot, annot=True, fmt=".2f", cmap="RdYlBu_r", center=0, ax=ax)
        ax.set_title(f"ACF |returns| lag 1, book_volume={book_volume}")
        ax.set_xlabel("HFT share phi")
        ax.set_ylabel("info_lag")

    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def plot_interaction_heatmap(interactions: pd.DataFrame, output_path: str):
    if interactions.empty:
        return
    book_volumes = sorted(interactions["book_volume"].unique())
    fig, axes = plt.subplots(1, len(book_volumes), figsize=(5.2 * len(book_volumes), 4.5), sharey=True)
    if len(book_volumes) == 1:
        axes = [axes]

    for ax, book_volume in zip(axes, book_volumes):
        sub = interactions[interactions["book_volume"] == book_volume]
        pivot = sub.pivot(index="info_lag", columns="hft_frac", values="interaction_acf_abs_ret_1")
        sns.heatmap(pivot, annot=True, fmt=".2f", cmap="RdYlGn", center=0, ax=ax)
        ax.set_title(f"Interaction in ACF lag 1, book_volume={book_volume}")
        ax.set_xlabel("HFT share phi")
        ax.set_ylabel("info_lag")

    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def summarize_results(agg: pd.DataFrame, interactions: pd.DataFrame) -> str:
    lines = []
    best_acf = agg.sort_values("acf_abs_ret_1_mean", ascending=False).head(8)
    lines.append("Top ACF |returns| lag 1 regimes:")
    lines.append(
        best_acf[
            ["info_lag", "book_volume", "hft_frac", "acf_abs_ret_1_mean", "acf_abs_ret_5_mean", "vol_ratio_mean"]
        ].to_string(index=False)
    )
    if not interactions.empty:
        best_inter = interactions.sort_values("interaction_acf_abs_ret_1", ascending=False).head(8)
        lines.append("\nTop positive interaction terms for ACF lag 1:")
        lines.append(
            best_inter[
                ["info_lag", "book_volume", "hft_frac", "interaction_acf_abs_ret_1", "interaction_acf_abs_ret_5"]
            ].to_string(index=False)
        )
    return "\n".join(lines)


def run_experiment(args):
    paths = output_paths(args.output_prefix)

    if args.plot_from_raw:
        raw = pd.read_csv(paths["raw"])
        agg = aggregate(raw)
        interactions = compute_interactions(
            agg,
            baseline_lag=0,
            baseline_book_volume=max(args.book_volume),
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
    total = len(args.info_lag) * len(args.book_volume) * len(args.hft_frac) * args.runs
    progress = tqdm(total=total, desc="H3 depth grid")

    for lag in args.info_lag:
        for book_volume in args.book_volume:
            for phi in args.hft_frac:
                for run in range(args.runs):
                    records.append(
                        run_one(
                            hft_frac=phi,
                            info_lag=lag,
                            book_volume=book_volume,
                            run=run,
                            n_iter=args.n_iter,
                            shock_it=args.shock_it,
                            shock_dp=args.shock_dp,
                            speed_multiplier=args.speed_multiplier,
                            softlimit=args.softlimit,
                            return_window=args.return_window,
                        )
                    )
                    progress.update(1)
    progress.close()

    raw = pd.DataFrame(records)
    agg = aggregate(raw)
    interactions = compute_interactions(
        agg,
        baseline_lag=0,
        baseline_book_volume=max(args.book_volume),
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
    parser = argparse.ArgumentParser(description="Run H3-clean order-book depth experiment.")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--n-iter", type=int, default=DEFAULT_N_ITER)
    parser.add_argument("--shock-it", type=int, default=DEFAULT_SHOCK_IT)
    parser.add_argument("--shock-dp", type=float, default=DEFAULT_SHOCK_DP)
    parser.add_argument("--speed-multiplier", type=int, default=DEFAULT_SPEED_MULTIPLIER)
    parser.add_argument("--softlimit", type=int, default=DEFAULT_SOFTLIMIT)
    parser.add_argument("--hft-frac", type=float, nargs="+", default=DEFAULT_HFT_FRACS)
    parser.add_argument("--info-lag", type=int, nargs="+", default=DEFAULT_INFO_LAGS)
    parser.add_argument("--book-volume", type=int, nargs="+", default=DEFAULT_BOOK_VOLUMES)
    parser.add_argument("--return-window", type=int, default=10)
    parser.add_argument("--output-prefix", default=DEFAULT_OUTPUT_PREFIX)
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument("--plot-from-raw", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run_experiment(parse_args())
