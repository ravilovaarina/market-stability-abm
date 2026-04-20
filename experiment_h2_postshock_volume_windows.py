#!/usr/bin/env python3
"""
H2 improved: post-shock volume-window comparison.

This experiment compares calendar time and event time on equal post-shock
executed-volume windows. Vstar is calibrated from the calendar run's post-shock
executed volume per tick, not from pre-shock activity.

Default run:
    python3 experiment_h2_postshock_volume_windows.py
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from typing import Dict, List, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from tqdm import tqdm

from experiment_h2_event_time import (
    apply_payments,
    build_simulation,
    call_traders_fast_first,
    mm_stress_ratio,
    price_vol_ratio,
    spread_ratio,
    update_behaviour,
)


DEFAULT_HFT_FRACS = [0.0, 0.2, 0.4, 0.6]
DEFAULT_RUNS = 50
DEFAULT_N_TICKS = 500
DEFAULT_SHOCK_TICK = 200
DEFAULT_SHOCK_DP = -10
DEFAULT_SPEED_MULTIPLIER = 2
DEFAULT_MAX_SUB_ITERS = 50
DEFAULT_SOFTLIMIT = 100
DEFAULT_N_RANDOM = 5
DEFAULT_OUTPUT_PREFIX = "h2_postshock_volume"
DEFAULT_VOL_WINDOW = 10

PRIMARY_METRICS = [
    "post_rv_per_volume",
    "post_rv_per_trade",
    "post_vol_per_sqrt_volume",
]

METRICS = [
    *PRIMARY_METRICS,
    "equal_volume_vol_ratio",
    "calendar_style_vol_ratio",
    "spread_ratio",
    "mm_stress_ratio",
    "post_window_volume",
    "post_window_trades",
    "target_post_volume",
    "post_volume_error",
    "avg_sub_iters",
    "threshold_hit_rate",
    "book_depleted_rate",
]


@dataclass
class LoggedRun:
    sim: object
    tick_volumes: List[float]
    tick_trades: List[float]
    cumulative_volumes: List[float]
    cumulative_trades: List[float]
    sub_iters: List[int]
    threshold_hits: List[bool]
    depleted: List[bool]


def price_returns(prices: Sequence[float]) -> np.ndarray:
    arr = np.asarray(prices, dtype=float)
    if len(arr) < 2:
        return np.array([], dtype=float)
    prev = arr[:-1]
    nxt = arr[1:]
    mask = np.isfinite(prev) & np.isfinite(nxt) & (np.abs(prev) > 1e-12)
    out = np.full(len(prev), np.nan, dtype=float)
    out[mask] = (nxt[mask] - prev[mask]) / prev[mask]
    return out


def _run_common_after_trading(sim):
    apply_payments(sim)
    sim.exchange.generate_dividend()


def simulate_calendar_logged(
    sim,
    *,
    n_ticks: int,
    speed_multiplier: int,
) -> LoggedRun:
    tick_volumes: List[float] = []
    tick_trades: List[float] = []
    cumulative_volumes: List[float] = []
    cumulative_trades: List[float] = []
    depleted: List[bool] = []

    for tick in range(n_ticks):
        sim.exchange.reset_tick_counters()
        if sim.events:
            for event in sim.events:
                event.call(tick)

        sim.info.capture()
        depleted.append(sim.exchange.is_book_depleted())
        update_behaviour(sim)
        call_traders_fast_first(sim.traders, speed_multiplier=speed_multiplier)

        tick_volumes.append(float(sim.exchange.executed_volume_tick))
        tick_trades.append(float(sim.exchange.executed_trades_tick))
        cumulative_volumes.append(float(sim.exchange.executed_volume_total))
        cumulative_trades.append(float(sim.exchange.executed_trades_total))
        _run_common_after_trading(sim)

    return LoggedRun(
        sim=sim,
        tick_volumes=tick_volumes,
        tick_trades=tick_trades,
        cumulative_volumes=cumulative_volumes,
        cumulative_trades=cumulative_trades,
        sub_iters=[1 for _ in tick_volumes],
        threshold_hits=[True for _ in tick_volumes],
        depleted=depleted,
    )


def simulate_event_time_logged(
    sim,
    *,
    n_ticks: int,
    volume_threshold: int,
    speed_multiplier: int,
    max_sub_iters: int,
) -> LoggedRun:
    tick_volumes: List[float] = []
    tick_trades: List[float] = []
    cumulative_volumes: List[float] = []
    cumulative_trades: List[float] = []
    sub_iters_by_tick: List[int] = []
    threshold_hits: List[bool] = []
    depleted: List[bool] = []

    for tick in range(n_ticks):
        sim.exchange.reset_tick_counters()
        if sim.events:
            for event in sim.events:
                event.call(tick)

        sim.info.capture()
        depleted.append(sim.exchange.is_book_depleted())
        update_behaviour(sim)

        sub_iters = 0
        while sim.exchange.executed_volume_tick < volume_threshold and sub_iters < max_sub_iters:
            call_traders_fast_first(sim.traders, speed_multiplier=speed_multiplier)
            sub_iters += 1

        hit = sim.exchange.executed_volume_tick >= volume_threshold
        threshold_hits.append(bool(hit))
        sub_iters_by_tick.append(int(sub_iters))
        tick_volumes.append(float(sim.exchange.executed_volume_tick))
        tick_trades.append(float(sim.exchange.executed_trades_tick))
        cumulative_volumes.append(float(sim.exchange.executed_volume_total))
        cumulative_trades.append(float(sim.exchange.executed_trades_total))
        _run_common_after_trading(sim)

    return LoggedRun(
        sim=sim,
        tick_volumes=tick_volumes,
        tick_trades=tick_trades,
        cumulative_volumes=cumulative_volumes,
        cumulative_trades=cumulative_trades,
        sub_iters=sub_iters_by_tick,
        threshold_hits=threshold_hits,
        depleted=depleted,
    )


def interval_indices_by_volume(
    tick_volumes: Sequence[float],
    *,
    start_tick: int,
    direction: str,
    target_volume: float,
) -> List[int]:
    if target_volume <= 0:
        return []
    total = 0.0
    idxs: List[int] = []
    if direction == "forward":
        iterator = range(start_tick, len(tick_volumes))
    elif direction == "backward":
        iterator = range(start_tick - 1, -1, -1)
    else:
        raise ValueError(f"Unknown direction: {direction}")

    for idx in iterator:
        idxs.append(idx)
        total += float(tick_volumes[idx])
        if total >= target_volume:
            break
    return sorted(idxs)


def window_stats(logged: LoggedRun, idxs: Sequence[int]) -> Dict[str, float]:
    returns = price_returns(logged.sim.info.prices)
    idxs = [int(i) for i in idxs if 0 <= int(i) < len(returns)]
    if not idxs:
        return {
            "rv": 0.0,
            "rv_per_volume": 0.0,
            "rv_per_trade": 0.0,
            "vol_per_sqrt_volume": 0.0,
            "volume": 0.0,
            "trades": 0.0,
            "n_return_ticks": 0,
        }

    vals = np.asarray([returns[i] for i in idxs], dtype=float)
    vals = vals[np.isfinite(vals)]
    volume = float(sum(logged.tick_volumes[i] for i in idxs))
    trades = float(sum(logged.tick_trades[i] for i in idxs))
    rv = float(np.sum(vals**2)) if len(vals) else 0.0
    vol = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
    return {
        "rv": rv,
        "rv_per_volume": rv / max(volume, 1.0),
        "rv_per_trade": rv / max(trades, 1.0),
        "vol_per_sqrt_volume": vol / math.sqrt(max(volume, 1.0)),
        "volume": volume,
        "trades": trades,
        "n_return_ticks": int(len(vals)),
    }


def compute_volume_window_metrics(
    logged: LoggedRun,
    *,
    shock_tick: int,
    target_post_volume: float,
    softlimit: int,
) -> Dict[str, float]:
    post_idxs = interval_indices_by_volume(
        logged.tick_volumes,
        start_tick=shock_tick,
        direction="forward",
        target_volume=target_post_volume,
    )
    pre_available = float(sum(logged.tick_volumes[:shock_tick]))
    pre_target = min(float(target_post_volume), pre_available)
    pre_idxs = interval_indices_by_volume(
        logged.tick_volumes,
        start_tick=shock_tick,
        direction="backward",
        target_volume=pre_target,
    )

    post = window_stats(logged, post_idxs)
    pre = window_stats(logged, pre_idxs)
    equal_volume_vol_ratio = post["rv_per_volume"] / (pre["rv_per_volume"] + 1e-12)

    return {
        "post_rv": post["rv"],
        "pre_rv": pre["rv"],
        "post_rv_per_volume": post["rv_per_volume"],
        "post_rv_per_trade": post["rv_per_trade"],
        "post_vol_per_sqrt_volume": post["vol_per_sqrt_volume"],
        "equal_volume_vol_ratio": float(equal_volume_vol_ratio),
        "post_window_volume": post["volume"],
        "pre_window_volume": pre["volume"],
        "post_window_trades": post["trades"],
        "pre_window_trades": pre["trades"],
        "post_window_ticks": post["n_return_ticks"],
        "pre_window_ticks": pre["n_return_ticks"],
        "target_post_volume": float(target_post_volume),
        "post_volume_error": post["volume"] - float(target_post_volume),
        "calendar_style_vol_ratio": price_vol_ratio(
            logged.sim.info, shock_tick=shock_tick, window=DEFAULT_VOL_WINDOW
        ),
        "spread_ratio": spread_ratio(logged.sim.info, shock_tick=shock_tick),
        "mm_stress_ratio": mm_stress_ratio(
            logged.sim.info, shock_tick=shock_tick, softlimit=softlimit
        ),
        "avg_sub_iters": float(np.mean(logged.sub_iters)) if logged.sub_iters else 0.0,
        "threshold_hit_rate": float(np.mean(logged.threshold_hits)) if logged.threshold_hits else 0.0,
        "book_depleted_rate": float(np.mean(logged.depleted)) if logged.depleted else 0.0,
    }


def run_pair(
    *,
    hft_frac: float,
    run: int,
    n_ticks: int,
    shock_tick: int,
    shock_dp: float,
    speed_multiplier: int,
    max_sub_iters: int,
    softlimit: int,
    n_random: int,
) -> List[Dict[str, float]]:
    seed = run * 100000 + int(round(hft_frac * 10)) * 1000 + speed_multiplier * 100 + 31
    calendar_sim = build_simulation(
        hft_frac=hft_frac,
        shock_tick=shock_tick,
        shock_dp=shock_dp,
        seed=seed,
        softlimit=softlimit,
        n_random=n_random,
    )
    calendar = simulate_calendar_logged(
        calendar_sim,
        n_ticks=n_ticks,
        speed_multiplier=speed_multiplier,
    )

    post_ticks = max(n_ticks - shock_tick, 1)
    calendar_post_volume = float(sum(calendar.tick_volumes[shock_tick:]))
    vstar = max(1, int(round(calendar_post_volume / post_ticks)))

    event_sim = build_simulation(
        hft_frac=hft_frac,
        shock_tick=shock_tick,
        shock_dp=shock_dp,
        seed=seed,
        softlimit=softlimit,
        n_random=n_random,
    )
    event_time = simulate_event_time_logged(
        event_sim,
        n_ticks=n_ticks,
        volume_threshold=vstar,
        speed_multiplier=speed_multiplier,
        max_sub_iters=max_sub_iters,
    )

    rows: List[Dict[str, float]] = []
    for mode, logged in [("calendar", calendar), ("event_time", event_time)]:
        metrics = compute_volume_window_metrics(
            logged,
            shock_tick=shock_tick,
            target_post_volume=calendar_post_volume,
            softlimit=softlimit,
        )
        rows.append(
            {
                "mode": mode,
                "run": run,
                "seed": seed,
                "hft_frac": hft_frac,
                "n_ticks": n_ticks,
                "shock_tick": shock_tick,
                "shock_dp": shock_dp,
                "speed_multiplier": speed_multiplier,
                "vstar_postshock": vstar if mode == "event_time" else np.nan,
                "calendar_post_volume": calendar_post_volume,
                "total_executed_volume": float(logged.sim.exchange.executed_volume_total),
                "total_executed_trades": float(logged.sim.exchange.executed_trades_total),
                **metrics,
            }
        )
    return rows


def bootstrap_ci(values: Sequence[float], n_boot: int = 1000, seed: int = 20260420):
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return np.nan, np.nan
    if len(arr) == 1:
        return float(arr[0]), float(arr[0])
    rng = np.random.default_rng(seed)
    samples = rng.choice(arr, size=(n_boot, len(arr)), replace=True).mean(axis=1)
    return tuple(np.percentile(samples, [2.5, 97.5]))


def aggregate(raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (mode, phi), sub in raw.groupby(["mode", "hft_frac"]):
        row = {"mode": mode, "hft_frac": phi, "n_runs": len(sub)}
        for metric in METRICS + ["total_executed_volume", "total_executed_trades", "vstar_postshock"]:
            vals = sub[metric].dropna().to_numpy(dtype=float)
            row[f"{metric}_mean"] = float(np.mean(vals)) if len(vals) else np.nan
            row[f"{metric}_std"] = float(np.std(vals, ddof=1)) if len(vals) > 1 else np.nan
            lo, hi = bootstrap_ci(vals)
            row[f"{metric}_ci_low"] = lo
            row[f"{metric}_ci_high"] = hi
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["mode", "hft_frac"]).reset_index(drop=True)


def paired_diffs(raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (phi, run), sub in raw.groupby(["hft_frac", "run"]):
        if set(sub["mode"]) != {"calendar", "event_time"}:
            continue
        cal = sub[sub["mode"] == "calendar"].iloc[0]
        evt = sub[sub["mode"] == "event_time"].iloc[0]
        row = {"hft_frac": phi, "run": run}
        for metric in METRICS + ["total_executed_volume", "total_executed_trades"]:
            row[f"diff_{metric}"] = float(evt[metric] - cal[metric])
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_diffs(diffs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for phi, sub in diffs.groupby("hft_frac"):
        row = {"hft_frac": phi, "n_pairs": len(sub)}
        for col in [c for c in diffs.columns if c.startswith("diff_")]:
            vals = sub[col].dropna().to_numpy(dtype=float)
            row[f"{col}_mean"] = float(np.mean(vals)) if len(vals) else np.nan
            lo, hi = bootstrap_ci(vals)
            row[f"{col}_ci_low"] = lo
            row[f"{col}_ci_high"] = hi
            row[f"{col}_positive_share"] = float(np.mean(vals > 0)) if len(vals) else np.nan
        rows.append(row)
    return pd.DataFrame(rows).sort_values("hft_frac").reset_index(drop=True)


def output_paths(prefix: str) -> Dict[str, str]:
    return {
        "raw": f"{prefix}_raw.csv",
        "agg": f"{prefix}_agg.csv",
        "diffs": f"{prefix}_paired_diffs.csv",
        "diff_summary": f"{prefix}_diff_summary.csv",
        "metrics_png": f"{prefix}_metrics.png",
        "diffs_png": f"{prefix}_diffs.png",
    }


def plot_metrics(agg: pd.DataFrame, path: str):
    metrics = [
        ("post_rv_per_volume", "Post-shock realized variance per volume"),
        ("post_rv_per_trade", "Post-shock realized variance per trade"),
        ("post_vol_per_sqrt_volume", "Post-shock volatility per sqrt(volume)"),
        ("equal_volume_vol_ratio", "Equal-volume vol ratio"),
        ("threshold_hit_rate", "Event-time threshold hit rate"),
    ]
    colors = {"calendar": "#2b8cbe", "event_time": "#e34a33"}
    fig, axes = plt.subplots(len(metrics), 1, figsize=(8, 3.0 * len(metrics)), sharex=True)
    if len(metrics) == 1:
        axes = [axes]
    for ax, (metric, title) in zip(axes, metrics):
        for mode, color in colors.items():
            sub = agg[agg["mode"] == mode]
            if sub.empty:
                continue
            ax.plot(sub["hft_frac"], sub[f"{metric}_mean"], marker="o", color=color, label=mode)
            ax.fill_between(
                sub["hft_frac"],
                sub[f"{metric}_ci_low"],
                sub[f"{metric}_ci_high"],
                color=color,
                alpha=0.15,
                linewidth=0,
            )
        ax.set_title(title)
        ax.grid(True, alpha=0.25)
        ax.set_ylabel(metric)
    axes[0].legend(frameon=False)
    axes[-1].set_xlabel("HFT share phi")
    fig.suptitle("H2 improved: equal post-shock volume windows", y=0.995)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_diffs(diff_summary: pd.DataFrame, path: str):
    metrics = [
        ("diff_post_rv_per_volume", "Event - calendar: RV per volume"),
        ("diff_post_rv_per_trade", "Event - calendar: RV per trade"),
        ("diff_post_vol_per_sqrt_volume", "Event - calendar: vol/sqrt(volume)"),
        ("diff_equal_volume_vol_ratio", "Event - calendar: equal-volume vol ratio"),
    ]
    fig, axes = plt.subplots(1, len(metrics), figsize=(5.2 * len(metrics), 4.0))
    if len(metrics) == 1:
        axes = [axes]
    for ax, (metric, title) in zip(axes, metrics):
        ax.axhline(0, color="black", linewidth=0.9)
        ax.plot(diff_summary["hft_frac"], diff_summary[f"{metric}_mean"], marker="o", color="#756bb1")
        ax.fill_between(
            diff_summary["hft_frac"],
            diff_summary[f"{metric}_ci_low"],
            diff_summary[f"{metric}_ci_high"],
            color="#756bb1",
            alpha=0.15,
            linewidth=0,
        )
        ax.set_title(title)
        ax.set_xlabel("HFT share phi")
        ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def run_experiment(args):
    paths = output_paths(args.output_prefix)
    records: List[Dict[str, float]] = []
    grid = [(phi, run) for phi in args.hft_frac for run in range(args.runs)]
    for phi, run in tqdm(grid, desc="H2 post-shock volume pairs"):
        records.extend(
            run_pair(
                hft_frac=float(phi),
                run=int(run),
                n_ticks=args.n_ticks,
                shock_tick=args.shock_tick,
                shock_dp=args.shock_dp,
                speed_multiplier=args.speed_multiplier,
                max_sub_iters=args.max_sub_iters,
                softlimit=args.softlimit,
                n_random=args.n_random,
            )
        )

    raw = pd.DataFrame(records)
    agg = aggregate(raw)
    diffs = paired_diffs(raw)
    diff_summary = summarize_diffs(diffs)

    raw.to_csv(paths["raw"], index=False)
    agg.to_csv(paths["agg"], index=False)
    diffs.to_csv(paths["diffs"], index=False)
    diff_summary.to_csv(paths["diff_summary"], index=False)
    if not args.no_plots:
        plot_metrics(agg, paths["metrics_png"])
        plot_diffs(diff_summary, paths["diffs_png"])

    print("\nSaved:")
    for key, path in paths.items():
        if args.no_plots and key.endswith("png"):
            continue
        print(f"  {path}")
    print("\nPrimary paired differences:")
    cols = [
        "hft_frac",
        "diff_post_rv_per_volume_mean",
        "diff_post_rv_per_volume_ci_low",
        "diff_post_rv_per_volume_ci_high",
        "diff_post_rv_per_trade_mean",
        "diff_post_rv_per_trade_ci_low",
        "diff_post_rv_per_trade_ci_high",
        "diff_post_vol_per_sqrt_volume_mean",
        "diff_post_vol_per_sqrt_volume_ci_low",
        "diff_post_vol_per_sqrt_volume_ci_high",
    ]
    print(diff_summary[cols].to_string(index=False))
    return raw, agg, diffs, diff_summary


def parse_args():
    parser = argparse.ArgumentParser(description="Run improved H2 post-shock volume-window experiment.")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--n-ticks", type=int, default=DEFAULT_N_TICKS)
    parser.add_argument("--shock-tick", type=int, default=DEFAULT_SHOCK_TICK)
    parser.add_argument("--shock-dp", type=float, default=DEFAULT_SHOCK_DP)
    parser.add_argument("--speed-multiplier", type=int, default=DEFAULT_SPEED_MULTIPLIER)
    parser.add_argument("--max-sub-iters", type=int, default=DEFAULT_MAX_SUB_ITERS)
    parser.add_argument("--softlimit", type=int, default=DEFAULT_SOFTLIMIT)
    parser.add_argument("--n-random", type=int, default=DEFAULT_N_RANDOM)
    parser.add_argument("--hft-frac", type=float, nargs="+", default=DEFAULT_HFT_FRACS)
    parser.add_argument("--output-prefix", default=DEFAULT_OUTPUT_PREFIX)
    parser.add_argument("--no-plots", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run_experiment(parse_args())
