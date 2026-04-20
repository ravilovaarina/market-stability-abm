"""
H2 volume-matched event-time experiment on the H1 unified environment.

Goal:
    Compare calendar time and event time at the same executed-volume scale.

Calendar branch:
    Run a fixed number of calendar iterations and record cumulative executed
    volume and shock-volume location.

Event-time branch:
    Run until the same cumulative executed volume is reached. Trigger the shock
    when cumulative executed volume reaches the calendar branch's pre-shock
    cumulative volume. This keeps market activity comparable across clocks.

Default run:
    python3 experiment_h2_volume_matched.py
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from typing import Dict, List, Optional, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from AgentBasedModel.agents import Chartist, Random
from AgentBasedModel.events import MarketPriceShock
from AgentBasedModel.simulator import SimulatorInfo
from experiment_h2_event_time import (
    SafeFundamentalist,
    SafeMarketMaker,
    TrendChartist,
    VolumeExchangeAgent,
    max_drawdown,
    mm_stress_ratio,
    patch_order_list_insert,
    price_vol_ratio,
    recovery_time,
    reset_class_ids,
    spread_ratio,
)


DEFAULT_HFT_FRACS = [0.0, 0.2, 0.4, 0.6]
DEFAULT_RUNS = 50
DEFAULT_N_ITER = 500
DEFAULT_SHOCK_IT = 200
DEFAULT_SHOCK_DP = -10
DEFAULT_SPEED_MULTIPLIER = 2
DEFAULT_BOOK_VOLUME = 1000
DEFAULT_SOFTLIMIT = 100
DEFAULT_INFO_LAG = 0
DEFAULT_MAX_EVENT_TICKS = 1500
DEFAULT_OUTPUT_PREFIX = "h2_volume_matched"
DEFAULT_VOL_WINDOW = 10

METRICS = [
    "vol_ratio",
    "spread_ratio",
    "max_drawdown",
    "recovery_time",
    "mm_panic_ratio",
    "total_executed_volume",
    "post_volume",
    "volume_per_tick",
    "realized_vol_per_volume",
]


class LoggingExchange(VolumeExchangeAgent):
    """ExchangeAgent that records filled quantity per simulation tick."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def begin_tick(self):
        self.reset_tick_counters()

    def end_tick(self) -> float:
        return float(self.executed_volume_tick)

    @property
    def cumulative_executed_volume(self) -> float:
        return float(self.executed_volume_total)

    def record_state(self):
        """Compatibility no-op: this H2 branch does not use delayed information."""
        return None


def vol_ratio(info: SimulatorInfo, shock_tick: int) -> float:
    return price_vol_ratio(info, shock_tick=shock_tick, window=DEFAULT_VOL_WINDOW)


def create_population(
    exchange,
    n_chartists=10,
    n_fundamentalists=10,
    n_random=5,
    n_mm=1,
    hft_frac=0.3,
    softlimit=100,
):
    traders = []
    n_fast = int(round(hft_frac * n_chartists))

    for _ in range(n_fundamentalists):
        trader = SafeFundamentalist(exchange, 10**3)
        trader.speed = "slow"
        traders.append(trader)

    for idx in range(n_chartists):
        trader = TrendChartist(exchange, 10**3)
        trader.speed = "fast" if idx < n_fast else "slow"
        traders.append(trader)

    for _ in range(n_random):
        trader = Random(exchange, 10**3)
        trader.speed = "slow"
        traders.append(trader)

    for _ in range(n_mm):
        maker = SafeMarketMaker(exchange, 10**3, softlimit=softlimit)
        maker.speed = "slow"
        traders.append(maker)

    return traders


class VolumeMatchedSimulator:
    def __init__(
        self,
        exchange,
        traders,
        *,
        shock_dp: float,
        speed_multiplier: int,
        mode: str,
        shock_it: Optional[int] = None,
        shock_volume: Optional[float] = None,
    ):
        self.exchange = exchange
        self.traders = traders
        self.shock_dp = shock_dp
        self.speed_multiplier = speed_multiplier
        self.mode = mode
        self.shock_it = shock_it
        self.shock_volume = shock_volume
        self.info = SimulatorInfo(exchange, traders)
        self.tick_volumes: List[float] = []
        self.cumulative_volumes: List[float] = []
        self.shock_tick: Optional[int] = None
        self.shock_triggered = False

    def _payments(self):
        for trader in self.traders:
            trader.cash += trader.assets * self.exchange.dividend()
            trader.cash += trader.cash * self.exchange.risk_free

    def _maybe_shock(self, it: int):
        if self.shock_triggered:
            return
        if self.mode == "calendar":
            if self.shock_it is not None and it == self.shock_it:
                MarketPriceShock(it, self.shock_dp).link(self).call(it)
                self.shock_tick = it
                self.shock_triggered = True
        elif self.mode == "event_time":
            if self.shock_volume is not None and self.exchange.cumulative_executed_volume >= self.shock_volume:
                MarketPriceShock(it, self.shock_dp).link(self).call(it)
                self.shock_tick = it
                self.shock_triggered = True
        else:
            raise ValueError(f"Unknown mode: {self.mode}")

    def step(self, it: int):
        self.exchange.begin_tick()
        self._maybe_shock(it)

        self.exchange.record_state()
        self.info.capture()

        for trader in self.traders:
            if isinstance(trader, Chartist) and type(trader).__name__ != "Universalist":
                trader.change_sentiment(self.info)

        fast = [t for t in self.traders if getattr(t, "speed", "slow") == "fast"]
        slow = [t for t in self.traders if getattr(t, "speed", "slow") != "fast"]

        for _ in range(self.speed_multiplier):
            random.shuffle(fast)
            for trader in fast:
                trader.call()

        random.shuffle(slow)
        for trader in slow:
            trader.call()

        tick_volume = self.exchange.end_tick()
        self.tick_volumes.append(tick_volume)
        self.cumulative_volumes.append(self.exchange.cumulative_executed_volume)

        self._payments()
        self.exchange.generate_dividend()

    def run_calendar(self, n_iter: int, silent=True):
        for it in tqdm(range(n_iter), desc="H2 calendar", disable=silent):
            self.step(it)
        return self

    def run_until_volume(self, target_volume: float, max_ticks: int, silent=True):
        for it in tqdm(range(max_ticks), desc="H2 event-time", disable=silent):
            if self.exchange.cumulative_executed_volume >= target_volume and self.shock_triggered:
                break
            self.step(it)
        return self


def safe_std(values: Sequence[float]) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0


def price_returns(prices: Sequence[float]) -> np.ndarray:
    prices_arr = np.asarray(prices, dtype=float)
    if len(prices_arr) < 2:
        return np.array([], dtype=float)
    prev = prices_arr[:-1]
    nxt = prices_arr[1:]
    mask = np.isfinite(prev) & np.isfinite(nxt) & (np.abs(prev) > 1e-12)
    out = np.full_like(prev, np.nan, dtype=float)
    out[mask] = (nxt[mask] - prev[mask]) / prev[mask]
    return out


def volume_window_indices(cumulative: Sequence[float], start_volume: float, end_volume: float) -> List[int]:
    return [
        idx
        for idx, vol in enumerate(cumulative)
        if float(vol) >= float(start_volume) and float(vol) <= float(end_volume)
    ]


def realized_vol_per_volume(sim: VolumeMatchedSimulator, shock_tick: int, post_volume: float) -> float:
    prices = sim.info.prices
    returns = price_returns(prices)
    if len(returns) == 0 or shock_tick is None:
        return 0.0
    cumulative = sim.cumulative_volumes
    if not cumulative:
        return 0.0
    shock_volume = cumulative[min(shock_tick, len(cumulative) - 1)]
    idxs = volume_window_indices(cumulative, shock_volume, shock_volume + post_volume)
    idxs = [i for i in idxs if i < len(returns)]
    if len(idxs) < 3:
        return 0.0
    vol = safe_std(returns[idxs])
    return vol / np.sqrt(max(post_volume, 1.0))


def create_simulator(
    *,
    seed: int,
    hft_frac: float,
    mode: str,
    shock_dp: float,
    speed_multiplier: int,
    shock_it: Optional[int] = None,
    shock_volume: Optional[float] = None,
    book_volume: int = DEFAULT_BOOK_VOLUME,
    info_lag: int = DEFAULT_INFO_LAG,
    softlimit: int = DEFAULT_SOFTLIMIT,
) -> VolumeMatchedSimulator:
    patch_order_list_insert()
    reset_class_ids()
    random.seed(seed)
    np.random.seed(seed)
    exchange = LoggingExchange(price=100, std=25, volume=book_volume, rf=5e-4)
    traders = create_population(
        exchange,
        n_chartists=10,
        n_fundamentalists=10,
        n_random=5,
        n_mm=1,
        hft_frac=hft_frac,
        softlimit=softlimit,
    )
    return VolumeMatchedSimulator(
        exchange,
        traders,
        shock_dp=shock_dp,
        speed_multiplier=speed_multiplier,
        mode=mode,
        shock_it=shock_it,
        shock_volume=shock_volume,
    )


def run_pair(
    *,
    hft_frac: float,
    run: int,
    n_iter: int,
    shock_it: int,
    shock_dp: float,
    speed_multiplier: int,
    max_event_ticks: int,
    book_volume: int,
    info_lag: int,
    softlimit: int,
) -> List[Dict[str, float]]:
    base_seed = run * 100000 + int(round(hft_frac * 10)) * 1000 + speed_multiplier * 100 + 22

    calendar = create_simulator(
        seed=base_seed,
        hft_frac=hft_frac,
        mode="calendar",
        shock_dp=shock_dp,
        speed_multiplier=speed_multiplier,
        shock_it=shock_it,
        book_volume=book_volume,
        info_lag=info_lag,
        softlimit=softlimit,
    )
    calendar.run_calendar(n_iter, silent=True)

    total_volume = calendar.exchange.cumulative_executed_volume
    shock_volume = calendar.cumulative_volumes[shock_it] if len(calendar.cumulative_volumes) > shock_it else total_volume * shock_it / n_iter
    post_volume = max(total_volume - shock_volume, 1.0)

    event_time = create_simulator(
        seed=base_seed,
        hft_frac=hft_frac,
        mode="event_time",
        shock_dp=shock_dp,
        speed_multiplier=speed_multiplier,
        shock_volume=shock_volume,
        book_volume=book_volume,
        info_lag=info_lag,
        softlimit=softlimit,
    )
    event_time.run_until_volume(total_volume, max_ticks=max_event_ticks, silent=True)

    rows = []
    for mode, sim in [("calendar", calendar), ("event_time", event_time)]:
        actual_shock_tick = sim.shock_tick if sim.shock_tick is not None else shock_it
        total_executed_volume = sim.exchange.cumulative_executed_volume
        post_executed_volume = max(total_executed_volume - (sim.cumulative_volumes[actual_shock_tick] if actual_shock_tick < len(sim.cumulative_volumes) else 0), 0)
        rows.append(
            {
                "mode": mode,
                "run": run,
                "seed": base_seed,
                "hft_frac": hft_frac,
                "speed_mult": speed_multiplier,
                "info_lag": info_lag,
                "book_volume": book_volume,
                "softlimit": softlimit,
                "n_ticks": len(sim.info.prices),
                "shock_tick": actual_shock_tick,
                "calendar_target_ticks": n_iter,
                "target_total_volume": total_volume,
                "target_shock_volume": shock_volume,
                "total_executed_volume": total_executed_volume,
                "post_volume": post_executed_volume,
                "volume_match_error": total_executed_volume - total_volume,
                "volume_per_tick": total_executed_volume / max(len(sim.info.prices), 1),
                "vol_ratio": vol_ratio(sim.info, actual_shock_tick),
                "spread_ratio": spread_ratio(sim.info, actual_shock_tick),
                "max_drawdown": max_drawdown(sim.info, actual_shock_tick),
                "recovery_time": recovery_time(sim.info, actual_shock_tick),
                "mm_panic_ratio": mm_stress_ratio(sim.info, actual_shock_tick, softlimit),
                "realized_vol_per_volume": realized_vol_per_volume(sim, actual_shock_tick, post_volume),
                "shock_triggered": bool(sim.shock_triggered),
            }
        )
    return rows


def bootstrap_ci(values: Sequence[float], n_bootstrap=1000, ci=0.95, seed=42):
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    means = [np.mean(rng.choice(arr, size=len(arr), replace=True)) for _ in range(n_bootstrap)]
    alpha = (1 - ci) / 2
    return tuple(np.percentile(means, [alpha * 100, (1 - alpha) * 100]))


def aggregate(raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, sub in raw.groupby(["mode", "hft_frac"]):
        mode, phi = keys
        row = {"mode": mode, "hft_frac": phi, "n_runs": len(sub)}
        for metric in METRICS + ["n_ticks", "volume_match_error"]:
            values = sub[metric].dropna().values
            row[f"{metric}_mean"] = float(np.mean(values)) if len(values) else np.nan
            row[f"{metric}_std"] = float(np.std(values, ddof=1)) if len(values) > 1 else np.nan
            lo, hi = bootstrap_ci(values)
            row[f"{metric}_ci_low"] = lo
            row[f"{metric}_ci_high"] = hi
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["mode", "hft_frac"]).reset_index(drop=True)


def paired_differences(raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (phi, run), sub in raw.groupby(["hft_frac", "run"]):
        if set(sub["mode"]) != {"calendar", "event_time"}:
            continue
        cal = sub[sub["mode"] == "calendar"].iloc[0]
        evt = sub[sub["mode"] == "event_time"].iloc[0]
        row = {"hft_frac": phi, "run": run}
        for metric in METRICS + ["n_ticks"]:
            row[f"diff_{metric}"] = float(evt[metric] - cal[metric])
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_differences(diffs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for phi, sub in diffs.groupby("hft_frac"):
        row = {"hft_frac": phi, "n_pairs": len(sub)}
        for col in [c for c in diffs.columns if c.startswith("diff_")]:
            values = sub[col].dropna().values
            row[f"{col}_mean"] = float(np.mean(values)) if len(values) else np.nan
            lo, hi = bootstrap_ci(values)
            row[f"{col}_ci_low"] = lo
            row[f"{col}_ci_high"] = hi
            row[f"{col}_positive_share"] = float(np.mean(values > 0)) if len(values) else np.nan
        rows.append(row)
    return pd.DataFrame(rows).sort_values("hft_frac").reset_index(drop=True)


def output_paths(prefix: str) -> Dict[str, str]:
    return {
        "raw": f"{prefix}_raw.csv",
        "agg": f"{prefix}_agg.csv",
        "diffs": f"{prefix}_paired_diffs.csv",
        "diff_summary": f"{prefix}_diff_summary.csv",
        "metrics_png": f"{prefix}_metrics.png",
        "diff_png": f"{prefix}_diffs.png",
    }


def plot_metrics(agg: pd.DataFrame, path: str):
    metrics = [
        ("vol_ratio", "Volatility ratio"),
        ("realized_vol_per_volume", "Realized vol per volume"),
        ("max_drawdown", "Max drawdown"),
        ("recovery_time", "Recovery time"),
        ("n_ticks", "Ticks used"),
    ]
    modes = ["calendar", "event_time"]
    colors = {"calendar": "#2c7fb8", "event_time": "#d95f0e"}
    fig, axes = plt.subplots(len(metrics), 1, figsize=(7.2, 3.0 * len(metrics)), sharex=True)
    if len(metrics) == 1:
        axes = [axes]
    for ax, (metric, title) in zip(axes, metrics):
        for mode in modes:
            sub = agg[agg["mode"] == mode]
            if sub.empty:
                continue
            ax.plot(sub["hft_frac"], sub[f"{metric}_mean"], marker="o", label=mode, color=colors[mode])
            ax.fill_between(
                sub["hft_frac"],
                sub[f"{metric}_ci_low"],
                sub[f"{metric}_ci_high"],
                color=colors[mode],
                alpha=0.15,
                linewidth=0,
            )
        ax.set_title(title)
        ax.set_ylabel(metric)
        ax.grid(True, alpha=0.25)
    axes[-1].set_xlabel("HFT share phi")
    axes[0].legend(frameon=False)
    fig.suptitle("H2 volume-matched calendar vs event time", y=0.995)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_diffs(diff_summary: pd.DataFrame, path: str):
    metrics = [
        ("diff_vol_ratio", "Event - calendar: vol_ratio"),
        ("diff_realized_vol_per_volume", "Event - calendar: realized vol per volume"),
        ("diff_max_drawdown", "Event - calendar: max drawdown"),
        ("diff_n_ticks", "Event - calendar: ticks"),
    ]
    fig, axes = plt.subplots(1, len(metrics), figsize=(5.0 * len(metrics), 4.0))
    if len(metrics) == 1:
        axes = [axes]
    for ax, (metric, title) in zip(axes, metrics):
        ax.axhline(0, color="black", linewidth=0.8)
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
    total = len(args.hft_frac) * args.runs
    progress = tqdm(total=total, desc="H2 volume-matched pairs")
    for phi in args.hft_frac:
        for run in range(args.runs):
            records.extend(
                run_pair(
                    hft_frac=phi,
                    run=run,
                    n_iter=args.n_iter,
                    shock_it=args.shock_it,
                    shock_dp=args.shock_dp,
                    speed_multiplier=args.speed_multiplier,
                    max_event_ticks=args.max_event_ticks,
                    book_volume=args.book_volume,
                    info_lag=args.info_lag,
                    softlimit=args.softlimit,
                )
            )
            progress.update(1)
    progress.close()

    raw = pd.DataFrame(records)
    agg = aggregate(raw)
    diffs = paired_differences(raw)
    diff_summary = summarize_differences(diffs)

    raw.to_csv(paths["raw"], index=False)
    agg.to_csv(paths["agg"], index=False)
    diffs.to_csv(paths["diffs"], index=False)
    diff_summary.to_csv(paths["diff_summary"], index=False)

    if not args.no_plots:
        plot_metrics(agg, paths["metrics_png"])
        plot_diffs(diff_summary, paths["diff_png"])

    print("\nSaved:")
    for key in ["raw", "agg", "diffs", "diff_summary"]:
        print(f"  {paths[key]}")
    if not args.no_plots:
        print(f"  {paths['metrics_png']}")
        print(f"  {paths['diff_png']}")
    print("\nDiff summary:")
    print(
        diff_summary[
            [
                "hft_frac",
                "diff_vol_ratio_mean",
                "diff_vol_ratio_ci_low",
                "diff_vol_ratio_ci_high",
                "diff_realized_vol_per_volume_mean",
                "diff_realized_vol_per_volume_ci_low",
                "diff_realized_vol_per_volume_ci_high",
                "diff_n_ticks_mean",
            ]
        ].to_string(index=False)
    )
    return raw, agg, diffs, diff_summary


def parse_args():
    parser = argparse.ArgumentParser(description="Run volume-matched H2 event-time experiment.")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--n-iter", type=int, default=DEFAULT_N_ITER)
    parser.add_argument("--shock-it", type=int, default=DEFAULT_SHOCK_IT)
    parser.add_argument("--shock-dp", type=float, default=DEFAULT_SHOCK_DP)
    parser.add_argument("--speed-multiplier", type=int, default=DEFAULT_SPEED_MULTIPLIER)
    parser.add_argument("--hft-frac", type=float, nargs="+", default=DEFAULT_HFT_FRACS)
    parser.add_argument("--book-volume", type=int, default=DEFAULT_BOOK_VOLUME)
    parser.add_argument("--softlimit", type=int, default=DEFAULT_SOFTLIMIT)
    parser.add_argument("--info-lag", type=int, default=DEFAULT_INFO_LAG)
    parser.add_argument("--max-event-ticks", type=int, default=DEFAULT_MAX_EVENT_TICKS)
    parser.add_argument("--output-prefix", default=DEFAULT_OUTPUT_PREFIX)
    parser.add_argument("--no-plots", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run_experiment(parse_args())
