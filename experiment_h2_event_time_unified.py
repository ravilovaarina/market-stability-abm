"""
H2 on H1 unified environment: calendar time vs event time / volume clock.

This experiment intentionally reuses the H1 unified machinery from
experiment_unified.py. The calendar branch should therefore be comparable to
the H1 unified speed grid, especially speed_multiplier=2.

Default final-candidate run:
    python3 experiment_h2_event_time_unified.py

Outputs by default:
    h2_unified_calibrated_raw.csv
    h2_unified_calibrated_agg.csv
    h2_unified_calibrated_tipping.csv
    h2_unified_calibrated_stats.csv
    h2_unified_calibrated_metrics.png
    h2_unified_calibrated_heatmap.png
    h2_unified_calibrated_tipping.png
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.stats import mannwhitneyu
from tqdm import tqdm

from AgentBasedModel.agents import Chartist, ExchangeAgent
from AgentBasedModel.events import MarketPriceShock
from AgentBasedModel.simulator import SimulatorInfo
from AgentBasedModel.utils import Order

from experiment_unified import (
    SimulatorUnified,
    create_population,
    max_drawdown,
    recovery_time,
    spread_ratio,
    vol_ratio,
)


DEFAULT_HFT_FRACS = [round(x, 1) for x in np.linspace(0.0, 1.0, 11)]
DEFAULT_VSTAR_MULTIPLIERS = [0.5, 1.0, 1.5]
DEFAULT_VSTARS = [5, 10, 15]
DEFAULT_RUNS = 30
DEFAULT_N_ITER = 500
DEFAULT_SHOCK_IT = 200
DEFAULT_SHOCK_DP = -10
DEFAULT_SPEED_MULTIPLIER = 2
DEFAULT_INFO_LAG = 0
DEFAULT_SOFTLIMIT = 100
DEFAULT_MAX_SUB_ITERS = 50
DEFAULT_OUTPUT_PREFIX = "h2_unified_calibrated"


@dataclass
class Diagnostics:
    avg_sub_iters: float = 1.0
    max_sub_iters_observed: int = 1
    threshold_hit_rate: float = 1.0
    executed_volume_total: int = 0
    book_depleted_rate: float = 0.0


class VolumeExchangeAgent(ExchangeAgent):
    """H1 ExchangeAgent plus executed-volume counters.

    Order matching behavior is kept equivalent to the H1 branch. The override
    only records matched quantity after each limit or market order.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executed_volume_tick = 0
        self.executed_volume_total = 0
        self.executed_trades_tick = 0
        self.executed_trades_total = 0

    def reset_tick_counters(self):
        self.executed_volume_tick = 0
        self.executed_trades_tick = 0

    def _record_execution(self, qty):
        qty = int(max(qty, 0))
        if qty <= 0:
            return
        self.executed_volume_tick += qty
        self.executed_volume_total += qty
        self.executed_trades_tick += 1
        self.executed_trades_total += 1

    def is_book_depleted(self):
        return self.spread() is None

    def limit_order(self, order: Order):
        spread = self.spread()
        if spread is None:
            if order.order_type == "bid":
                self.order_book["bid"].insert(order)
            elif order.order_type == "ask":
                self.order_book["ask"].insert(order)
            return

        bid, ask = spread["bid"], spread["ask"]
        t_cost = self.transaction_cost
        if not bid or not ask:
            return

        qty_before = order.qty
        if order.order_type == "bid":
            if order.price >= ask:
                order = self.order_book["ask"].fulfill(order, t_cost)
                self._record_execution(qty_before - order.qty)
            if order.qty > 0:
                self.order_book["bid"].insert(order)
            return

        if order.order_type == "ask":
            if order.price <= bid:
                order = self.order_book["bid"].fulfill(order, t_cost)
                self._record_execution(qty_before - order.qty)
            if order.qty > 0:
                self.order_book["ask"].insert(order)

    def market_order(self, order: Order) -> Order:
        qty_before = order.qty
        t_cost = self.transaction_cost
        if order.order_type == "bid":
            order = self.order_book["ask"].fulfill(order, t_cost)
        elif order.order_type == "ask":
            order = self.order_book["bid"].fulfill(order, t_cost)
        self._record_execution(qty_before - order.qty)
        return order


class SimulatorEventTimeUnified:
    """Event-time simulator that mirrors SimulatorUnified except for the clock."""

    def __init__(self, exchange, traders, events=None):
        self.exchange = exchange
        self.traders = traders
        self.events = [e.link(self) for e in events] if events else None
        self.info = SimulatorInfo(exchange, traders)

    def _payments(self):
        for trader in self.traders:
            trader.cash += trader.assets * self.exchange.dividend()
            trader.cash += trader.cash * self.exchange.risk_free

    @staticmethod
    def _update_sentiments(traders, info):
        for trader in traders:
            if isinstance(trader, Chartist) and type(trader).__name__ != "Universalist":
                trader.change_sentiment(info)

    @staticmethod
    def _call_traders(traders, speed_multiplier=1):
        fast = [t for t in traders if getattr(t, "speed", "slow") == "fast"]
        slow = [t for t in traders if getattr(t, "speed", "slow") != "fast"]

        for _ in range(speed_multiplier):
            random.shuffle(fast)
            for trader in fast:
                trader.call()

        random.shuffle(slow)
        for trader in slow:
            trader.call()

    def simulate_event_time(
        self,
        n_iter,
        volume_threshold,
        speed_multiplier=1,
        max_sub_iters=50,
        silent=False,
    ) -> Diagnostics:
        sub_iters_by_tick = []
        threshold_hits = []
        depleted_by_tick = []

        iterator = tqdm(range(n_iter), desc=f"event_time_V{volume_threshold}", disable=silent)
        for it in iterator:
            if self.events:
                for event in self.events:
                    event.call(it)

            self.exchange.record_state()
            self.info.capture()
            depleted_by_tick.append(self.exchange.is_book_depleted())
            self._update_sentiments(self.traders, self.info)

            self.exchange.reset_tick_counters()
            sub_iters = 0
            while (
                self.exchange.executed_volume_tick < volume_threshold
                and sub_iters < max_sub_iters
            ):
                self._call_traders(self.traders, speed_multiplier=speed_multiplier)
                sub_iters += 1

            threshold_hits.append(self.exchange.executed_volume_tick >= volume_threshold)
            sub_iters_by_tick.append(sub_iters)

            self._payments()
            self.exchange.generate_dividend()

        return Diagnostics(
            avg_sub_iters=float(np.mean(sub_iters_by_tick)) if sub_iters_by_tick else 0.0,
            max_sub_iters_observed=int(max(sub_iters_by_tick)) if sub_iters_by_tick else 0,
            threshold_hit_rate=float(np.mean(threshold_hits)) if threshold_hits else 0.0,
            executed_volume_total=self.exchange.executed_volume_total,
            book_depleted_rate=float(np.mean(depleted_by_tick)) if depleted_by_tick else 0.0,
        )


def build_exchange_and_traders(hft_frac, info_lag, softlimit):
    exchange = VolumeExchangeAgent(price=100, std=25, volume=1000, rf=5e-4)
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
    return exchange, traders


def compute_row_metrics(info, shock_it):
    return {
        "vol_ratio": vol_ratio(info, shock_it),
        "spread_ratio": spread_ratio(info, shock_it),
        "max_drawdown": max_drawdown(info, shock_it),
        "recovery_time": recovery_time(info, shock_it),
        "mm_panic_ratio": info.mm_panic_ratio(from_it=shock_it),
    }


def run_calendar_one(
    hft_frac,
    run,
    speed_multiplier,
    n_iter,
    shock_it,
    shock_dp,
    info_lag,
    softlimit,
) -> Dict[str, float]:
    seed = run * 10000 + int(hft_frac * 10) * 100 + speed_multiplier
    random.seed(seed)
    np.random.seed(seed)

    exchange, traders = build_exchange_and_traders(hft_frac, info_lag, softlimit)
    sim = SimulatorUnified(
        exchange=exchange,
        traders=traders,
        events=[MarketPriceShock(shock_it, shock_dp)],
    )
    sim.simulate(n_iter, silent=True, speed_multiplier=speed_multiplier)

    return {
        "mode": "calendar",
        "regime": "calendar",
        "volume_threshold": np.nan,
        "hft_frac": hft_frac,
        "run": run,
        "seed": seed,
        "n_iter": n_iter,
        "shock_it": shock_it,
        "shock_dp": shock_dp,
        "speed_multiplier": speed_multiplier,
        "info_lag": info_lag,
        "softlimit": softlimit,
        **compute_row_metrics(sim.info, shock_it),
        "avg_sub_iters": 1.0,
        "max_sub_iters_observed": 1,
        "threshold_hit_rate": 1.0,
        "executed_volume_total": exchange.executed_volume_total,
        "book_depleted_rate": 0.0,
    }


def run_event_time_one(
    hft_frac,
    run,
    volume_threshold,
    speed_multiplier,
    n_iter,
    shock_it,
    shock_dp,
    info_lag,
    softlimit,
    max_sub_iters,
) -> Dict[str, float]:
    seed = 1_000_000 + run * 10000 + int(hft_frac * 10) * 100 + int(volume_threshold)
    random.seed(seed)
    np.random.seed(seed)

    exchange, traders = build_exchange_and_traders(hft_frac, info_lag, softlimit)
    sim = SimulatorEventTimeUnified(
        exchange=exchange,
        traders=traders,
        events=[MarketPriceShock(shock_it, shock_dp)],
    )
    diagnostics = sim.simulate_event_time(
        n_iter=n_iter,
        volume_threshold=volume_threshold,
        speed_multiplier=speed_multiplier,
        max_sub_iters=max_sub_iters,
        silent=True,
    )

    return {
        "mode": "event_time",
        "regime": f"event_time_V{volume_threshold}",
        "volume_threshold": volume_threshold,
        "hft_frac": hft_frac,
        "run": run,
        "seed": seed,
        "n_iter": n_iter,
        "shock_it": shock_it,
        "shock_dp": shock_dp,
        "speed_multiplier": speed_multiplier,
        "info_lag": info_lag,
        "softlimit": softlimit,
        **compute_row_metrics(sim.info, shock_it),
        "avg_sub_iters": diagnostics.avg_sub_iters,
        "max_sub_iters_observed": diagnostics.max_sub_iters_observed,
        "threshold_hit_rate": diagnostics.threshold_hit_rate,
        "executed_volume_total": diagnostics.executed_volume_total,
        "book_depleted_rate": diagnostics.book_depleted_rate,
    }


def calibrated_vstars(calendar_rows, multipliers):
    baseline_rows = [row for row in calendar_rows if row["hft_frac"] == 0.0]
    if not baseline_rows:
        baseline_rows = calendar_rows

    vol_per_tick = np.mean([
        row["executed_volume_total"] / max(row["n_iter"], 1)
        for row in baseline_rows
    ])
    vstars = sorted({
        max(1, int(round(vol_per_tick * multiplier)))
        for multiplier in multipliers
    })
    return vstars, float(vol_per_tick)


def safe_values(values: Iterable[float]):
    return [float(v) for v in values if pd.notna(v) and np.isfinite(v)]


def bootstrap_ci(values, n_boot=1000, alpha=0.05, seed=123):
    vals = np.array(safe_values(values), dtype=float)
    if len(vals) == 0:
        return np.nan, np.nan
    if len(vals) == 1:
        return float(vals[0]), float(vals[0])
    rng = np.random.default_rng(seed)
    samples = rng.choice(vals, size=(n_boot, len(vals)), replace=True).mean(axis=1)
    return float(np.quantile(samples, alpha / 2)), float(np.quantile(samples, 1 - alpha / 2))


def aggregate_results(raw):
    metric_cols = [
        "vol_ratio",
        "spread_ratio",
        "max_drawdown",
        "recovery_time",
        "mm_panic_ratio",
        "avg_sub_iters",
        "threshold_hit_rate",
        "executed_volume_total",
        "book_depleted_rate",
        "calendar_volume_per_tick_target",
        "vstar_to_calendar_tick_ratio",
    ]
    rows = []
    group_cols = ["regime", "mode", "volume_threshold", "hft_frac"]
    for keys, sub in raw.groupby(group_cols, dropna=False):
        regime, mode, volume_threshold, hft_frac = keys
        row = {
            "regime": regime,
            "mode": mode,
            "volume_threshold": volume_threshold,
            "hft_frac": hft_frac,
            "n_runs": len(sub),
        }
        for col in metric_cols:
            row[f"{col}_mean"] = float(sub[col].mean())
            row[f"{col}_std"] = float(sub[col].std(ddof=1)) if len(sub) > 1 else 0.0
            lo, hi = bootstrap_ci(sub[col].tolist())
            row[f"{col}_ci_low"] = lo
            row[f"{col}_ci_high"] = hi
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["regime", "hft_frac"]).reset_index(drop=True)


def compute_tipping_points(agg, multiplier=1.3):
    rows = []
    for regime, sub in agg.groupby("regime"):
        sub = sub.sort_values("hft_frac")
        baseline_rows = sub[sub["hft_frac"] == 0.0]
        if baseline_rows.empty:
            continue
        baseline = float(baseline_rows["vol_ratio_mean"].iloc[0])
        threshold = baseline * multiplier
        phi_star = None
        for _, row in sub.iterrows():
            phi = float(row["hft_frac"])
            if phi == 0.0:
                continue
            if float(row["vol_ratio_mean"]) >= threshold:
                phi_star = phi
                break
        max_row = sub.loc[sub["vol_ratio_mean"].idxmax()]
        rows.append({
            "regime": regime,
            "mode": max_row["mode"],
            "volume_threshold": max_row["volume_threshold"],
            "baseline_vol_ratio": baseline,
            "threshold_1_3x": threshold,
            "phi_star": phi_star,
            "max_vol_ratio": float(max_row["vol_ratio_mean"]),
            "phi_at_max": float(max_row["hft_frac"]),
            "n_runs_per_phi_min": int(sub["n_runs"].min()),
            "n_runs_per_phi_max": int(sub["n_runs"].max()),
        })
    return pd.DataFrame(rows).sort_values("regime").reset_index(drop=True)


def mannwhitney_stats(raw):
    rows = []
    for regime, sub in raw.groupby("regime"):
        baseline = sub[sub["hft_frac"] == 0.0]["vol_ratio"].dropna()
        if baseline.empty:
            continue
        for phi in sorted(sub["hft_frac"].unique()):
            if phi == 0.0:
                continue
            treatment = sub[sub["hft_frac"] == phi]["vol_ratio"].dropna()
            if treatment.empty:
                continue
            try:
                stat, p_value = mannwhitneyu(treatment, baseline, alternative="greater")
            except ValueError:
                stat, p_value = np.nan, np.nan
            rows.append({
                "regime": regime,
                "hft_frac": phi,
                "baseline_mean": float(baseline.mean()),
                "treatment_mean": float(treatment.mean()),
                "u_stat": stat,
                "p_value": p_value,
                "significant_0_05": bool(p_value < 0.05) if np.isfinite(p_value) else False,
            })
    return pd.DataFrame(rows)


def plot_metrics(agg, output_path):
    sns.set_theme(style="whitegrid", context="talk")
    metrics = [
        ("vol_ratio", "Volatility ratio"),
        ("spread_ratio", "Spread ratio"),
        ("max_drawdown", "Max drawdown"),
        ("recovery_time", "Recovery time"),
        ("mm_panic_ratio", "MM panic ratio"),
        ("avg_sub_iters", "Avg sub-iterations"),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(20, 11))
    axes = axes.ravel()

    for ax, (metric, title) in zip(axes, metrics):
        for regime, sub in agg.groupby("regime"):
            sub = sub.sort_values("hft_frac")
            x = sub["hft_frac"].astype(float).to_numpy()
            y = sub[f"{metric}_mean"].astype(float).to_numpy()
            lo = sub[f"{metric}_ci_low"].astype(float).to_numpy()
            hi = sub[f"{metric}_ci_high"].astype(float).to_numpy()
            ax.plot(x, y, marker="o", linewidth=2, label=regime)
            ax.fill_between(x, lo, hi, alpha=0.14)
        ax.set_title(title)
        ax.set_xlabel("HFT share phi")
        ax.set_ylabel(metric)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=min(4, len(labels)), frameon=False)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def plot_heatmap(agg, output_path):
    sns.set_theme(style="white", context="talk")
    pivot = agg.pivot(index="regime", columns="hft_frac", values="vol_ratio_mean")
    fig, ax = plt.subplots(figsize=(15, max(4, 0.8 * len(pivot))))
    sns.heatmap(
        pivot,
        annot=True,
        fmt=".2f",
        cmap="rocket_r",
        linewidths=0.5,
        ax=ax,
        cbar_kws={"label": "Mean vol_ratio"},
    )
    ax.set_title("H2 on H1: Mean volatility ratio by regime and HFT share")
    ax.set_xlabel("HFT share phi")
    ax.set_ylabel("Regime")
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def plot_tipping(tipping, output_path):
    sns.set_theme(style="whitegrid", context="talk")
    plot_df = tipping.copy()
    plot_df["phi_star_plot"] = plot_df["phi_star"].fillna(-0.05)
    plot_df["label"] = plot_df["phi_star"].apply(lambda x: "None" if pd.isna(x) else f"{x:.1f}")

    fig, ax = plt.subplots(figsize=(13, 7))
    sns.barplot(data=plot_df, x="regime", y="phi_star_plot", ax=ax, color="#4C78A8")
    ax.axhline(0, color="black", linewidth=1)
    ax.set_title("H2 on H1: Tipping point phi* by timekeeping regime")
    ax.set_xlabel("Regime")
    ax.set_ylabel("phi* (None shown below zero)")
    ax.tick_params(axis="x", rotation=25)

    for idx, row in plot_df.reset_index(drop=True).iterrows():
        ax.text(idx, row["phi_star_plot"] + 0.03, row["label"], ha="center", va="bottom", fontsize=12)

    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def output_paths(prefix):
    return {
        "raw": f"{prefix}_raw.csv",
        "agg": f"{prefix}_agg.csv",
        "tipping": f"{prefix}_tipping.csv",
        "stats": f"{prefix}_stats.csv",
        "metrics_png": f"{prefix}_metrics.png",
        "heatmap_png": f"{prefix}_heatmap.png",
        "tipping_png": f"{prefix}_tipping.png",
    }


def run_experiment(args):
    paths = output_paths(args.output_prefix)

    if args.plot_from_raw:
        raw = pd.read_csv(paths["raw"])
        agg = aggregate_results(raw)
        tipping = compute_tipping_points(agg, multiplier=args.threshold_multiplier)
        stats = mannwhitney_stats(raw)

        agg.to_csv(paths["agg"], index=False)
        tipping.to_csv(paths["tipping"], index=False)
        stats.to_csv(paths["stats"], index=False)

        if not args.no_plots:
            plot_metrics(agg, paths["metrics_png"])
            plot_heatmap(agg, paths["heatmap_png"])
            plot_tipping(tipping, paths["tipping_png"])

        print("\nRebuilt from existing raw CSV:")
        for key in ["agg", "tipping", "stats"]:
            print(f"  {paths[key]}")
        if not args.no_plots:
            for key in ["metrics_png", "heatmap_png", "tipping_png"]:
                print(f"  {paths[key]}")
        print("\nTipping summary:")
        print(tipping.to_string(index=False))
        return

    rows = []
    calendar_total = len(args.hft_frac) * args.runs
    progress = tqdm(total=calendar_total, desc="H2 unified calendar")
    for phi in args.hft_frac:
        for run in range(args.runs):
            rows.append(run_calendar_one(
                hft_frac=phi,
                run=run,
                speed_multiplier=args.speed_multiplier,
                n_iter=args.n_iter,
                shock_it=args.shock_it,
                shock_dp=args.shock_dp,
                info_lag=args.info_lag,
                softlimit=args.softlimit,
            ))
            progress.update(1)
    progress.close()

    if args.calibrate_vstar:
        vstars, target = calibrated_vstars(rows, args.vstar_multipliers)
        print(f"\nCalibrated Vstar from unified calendar phi=0 volume: {target:.3f} volume/tick -> {vstars}")
    else:
        vstars = args.vstar
        target = np.nan

    if not args.calendar_only:
        event_total = len(vstars) * len(args.hft_frac) * args.runs
        progress = tqdm(total=event_total, desc="H2 unified event-time")
        for vstar in vstars:
            for phi in args.hft_frac:
                for run in range(args.runs):
                    rows.append(run_event_time_one(
                        hft_frac=phi,
                        run=run,
                        volume_threshold=vstar,
                        speed_multiplier=args.speed_multiplier,
                        n_iter=args.n_iter,
                        shock_it=args.shock_it,
                        shock_dp=args.shock_dp,
                        info_lag=args.info_lag,
                        softlimit=args.softlimit,
                        max_sub_iters=args.max_sub_iters,
                    ))
                    progress.update(1)
        progress.close()

    for row in rows:
        row["calendar_volume_per_tick_target"] = target
        vt = row.get("volume_threshold")
        if pd.notna(vt) and np.isfinite(target):
            row["vstar_to_calendar_tick_ratio"] = float(vt) / target
        else:
            row["vstar_to_calendar_tick_ratio"] = np.nan

    raw = pd.DataFrame(rows)
    agg = aggregate_results(raw)
    tipping = compute_tipping_points(agg, multiplier=args.threshold_multiplier)
    stats = mannwhitney_stats(raw)

    raw.to_csv(paths["raw"], index=False)
    agg.to_csv(paths["agg"], index=False)
    tipping.to_csv(paths["tipping"], index=False)
    stats.to_csv(paths["stats"], index=False)

    if not args.no_plots:
        plot_metrics(agg, paths["metrics_png"])
        plot_heatmap(agg, paths["heatmap_png"])
        plot_tipping(tipping, paths["tipping_png"])

    print("\nSaved:")
    for key in ["raw", "agg", "tipping", "stats"]:
        print(f"  {paths[key]}")
    if not args.no_plots:
        for key in ["metrics_png", "heatmap_png", "tipping_png"]:
            print(f"  {paths[key]}")

    print("\nTipping summary:")
    print(tipping.to_string(index=False))


def parse_args():
    parser = argparse.ArgumentParser(description="Run H2 event-time experiment on H1 unified environment.")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--n-iter", type=int, default=DEFAULT_N_ITER)
    parser.add_argument("--shock-it", type=int, default=DEFAULT_SHOCK_IT)
    parser.add_argument("--shock-dp", type=float, default=DEFAULT_SHOCK_DP)
    parser.add_argument("--speed-multiplier", type=int, default=DEFAULT_SPEED_MULTIPLIER)
    parser.add_argument("--info-lag", type=int, default=DEFAULT_INFO_LAG)
    parser.add_argument("--softlimit", type=int, default=DEFAULT_SOFTLIMIT)
    parser.add_argument("--hft-frac", type=float, nargs="+", default=DEFAULT_HFT_FRACS)
    parser.add_argument("--vstar", type=int, nargs="+", default=DEFAULT_VSTARS)
    parser.add_argument("--vstar-multipliers", type=float, nargs="+", default=DEFAULT_VSTAR_MULTIPLIERS)
    parser.add_argument("--max-sub-iters", type=int, default=DEFAULT_MAX_SUB_ITERS)
    parser.add_argument("--threshold-multiplier", type=float, default=1.3)
    parser.add_argument("--output-prefix", default=DEFAULT_OUTPUT_PREFIX)
    parser.add_argument("--calendar-only", action="store_true")
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument("--plot-from-raw", action="store_true")
    parser.add_argument("--calibrate-vstar", dest="calibrate_vstar", action="store_true", default=True)
    parser.add_argument("--no-calibrate-vstar", dest="calibrate_vstar", action="store_false")
    return parser.parse_args()


if __name__ == "__main__":
    run_experiment(parse_args())
