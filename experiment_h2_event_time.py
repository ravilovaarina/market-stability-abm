"""
H2 experiment: Calendar time versus event time (volume clock).

This script is intentionally standalone. It does not modify the baseline
AgentBasedModel package. The experiment compares two timekeeping regimes:

1. calendar:
   one recorded tick = one fixed simulator iteration.

2. event_time:
   one recorded tick = enough trading has occurred, measured by cumulative
   executed volume reaching Vstar.

Outputs:
    h2_event_time_raw.csv
    h2_event_time_agg.csv
    h2_event_time_tipping.csv
    h2_event_time_stats.csv
    h2_event_time_metrics.png
    h2_event_time_heatmap.png
    h2_event_time_tipping.png
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.stats import mannwhitneyu
from tqdm import tqdm

from AgentBasedModel.agents import (
    Chartist,
    ExchangeAgent,
    Fundamentalist,
    MarketMaker,
    Random,
    Trader,
    Universalist,
)
from AgentBasedModel.events import MarketPriceShock
from AgentBasedModel.simulator import Simulator, SimulatorInfo
from AgentBasedModel.utils import Order, OrderList
from AgentBasedModel.utils.math import exp


DEFAULT_HFT_FRACS = [round(x, 1) for x in np.linspace(0.0, 1.0, 11)]
DEFAULT_VSTARS = [5, 10, 15]
DEFAULT_VSTAR_MULTIPLIERS = [0.5, 1.0, 1.5]
DEFAULT_N_TICKS = 500
DEFAULT_SHOCK_TICK = 200
DEFAULT_SHOCK_DP = -10
DEFAULT_N_RUNS = 30
DEFAULT_SPEED_MULTIPLIER = 1
DEFAULT_MAX_SUB_ITERS = 50
DEFAULT_VOL_WINDOW = 10
DEFAULT_SOFTLIMIT = 100
DEFAULT_N_RANDOM = 5

RAW_OUT = "h2_event_time_raw.csv"
AGG_OUT = "h2_event_time_agg.csv"
TIPPING_OUT = "h2_event_time_tipping.csv"
STATS_OUT = "h2_event_time_stats.csv"
METRICS_PNG = "h2_event_time_metrics.png"
HEATMAP_PNG = "h2_event_time_heatmap.png"
TIPPING_PNG = "h2_event_time_tipping.png"


def patch_order_list_insert():
    """Apply the H1 OrderList.insert safety fix locally for this experiment.

    Baseline OrderList.insert misses a return after inserting into an empty
    list. In stress regimes this can corrupt pointers when a depleted side of
    the book starts receiving new limit orders again.
    """

    def fixed_insert(self, order: Order):
        if order.order_type != self.order_type:
            raise ValueError(
                f"Wrong order type! OrderList: {self.order_type}, Order: {order.order_type}"
            )

        if self.first is None:
            self.append(order)
            return

        if order <= self.first:
            order.right = self.first
            self.first.left = order
            self.first = order
            return

        for val in self:
            if order <= val:
                order.left = val.left
                order.right = val
                order.left.right = order
                order.right.left = order
                return

        self.append(order)

    OrderList.insert = fixed_insert


@dataclass
class SimDiagnostics:
    avg_sub_iters: float = 1.0
    max_sub_iters_observed: int = 1
    threshold_hit_rate: float = 1.0
    executed_volume_total: int = 0
    book_depleted_rate: float = 0.0


class VolumeExchangeAgent(ExchangeAgent):
    """ExchangeAgent with executed-volume counters for the H2 volume clock."""

    def __init__(self, *args, **kwargs):
        initial_price = kwargs.get("price", 100)
        super().__init__(*args, **kwargs)
        self.executed_volume_tick = 0
        self.executed_volume_total = 0
        self.executed_trades_tick = 0
        self.executed_trades_total = 0
        self.last_valid_price = float(initial_price)

    def reset_tick_counters(self):
        self.executed_volume_tick = 0
        self.executed_trades_tick = 0

    def _record_execution(self, qty: int):
        qty = int(max(qty, 0))
        if qty <= 0:
            return
        self.executed_volume_tick += qty
        self.executed_volume_total += qty
        self.executed_trades_tick += 1
        self.executed_trades_total += 1

    def price(self) -> float:
        """Return midpoint when available, otherwise keep last valid price.

        In event-time stress regimes, one side of the book can be depleted.
        That is an economically meaningful failure state, so the run should
        record it instead of crashing inside SimulatorInfo.capture().
        """
        spread = self.spread()
        if spread:
            self.last_valid_price = round((spread["bid"] + spread["ask"]) / 2, 1)
        return self.last_valid_price

    def is_book_depleted(self) -> bool:
        return self.spread() is None

    def limit_order(self, order: Order):
        """Baseline limit order logic plus volume accounting and empty-book checks."""
        spread = self.spread()
        if spread is None:
            if order.order_type == "bid":
                self.order_book["bid"].insert(order)
            elif order.order_type == "ask":
                self.order_book["ask"].insert(order)
            return

        bid, ask = spread.values()
        t_cost = self.transaction_cost
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
        """Baseline market order logic plus volume accounting."""
        qty_before = order.qty
        t_cost = self.transaction_cost

        if order.order_type == "bid":
            order = self.order_book["ask"].fulfill(order, t_cost)
        elif order.order_type == "ask":
            order = self.order_book["bid"].fulfill(order, t_cost)

        self._record_execution(qty_before - order.qty)
        return order


class SafeFundamentalist(Fundamentalist):
    """Fundamentalist with empty-book protection."""

    def call(self):
        spread = self.market.spread()
        if spread is None:
            return

        try:
            p = self.market.price()
        except Exception:
            return

        pf = round(self.evaluate(self.market.dividend(self.access), self.market.risk_free), 1)
        t_cost = self.market.transaction_cost

        random_state = random.random()
        qty = Fundamentalist.draw_quantity(pf, p)
        if not qty:
            return

        if random_state > 0.45:
            random_state = random.random()
            ask_t = round(spread["ask"] * (1 + t_cost), 1)
            bid_t = round(spread["bid"] * (1 - t_cost), 1)

            if pf >= ask_t:
                if random_state > 0.5:
                    self._buy_market(qty)
                else:
                    self._sell_limit(qty, (pf + Random.draw_delta()) * (1 + t_cost))

            elif pf <= bid_t:
                if random_state > 0.5:
                    self._sell_market(qty)
                else:
                    self._buy_limit(qty, (pf - Random.draw_delta()) * (1 - t_cost))

            elif ask_t > pf > bid_t:
                if random_state > 0.5:
                    self._buy_limit(qty, (pf - Random.draw_delta()) * (1 - t_cost))
                else:
                    self._sell_limit(qty, (pf + Random.draw_delta()) * (1 + t_cost))

        elif self.orders:
            self._cancel_order(self.orders[0])


class TrendChartist(Chartist):
    """
    Trend-following Chartist.

    The baseline Chartist is contrarian. For the latency/tipping-point mechanism,
    we use corrected signs: price falls make Optimists more likely to become
    Pessimistic; price rises make Pessimists more likely to become Optimistic.
    """

    def call(self):
        spread = self.market.spread()
        if spread is None:
            return

        random_state = random.random()
        t_cost = self.market.transaction_cost

        if self.sentiment == "Optimistic":
            if random_state > 0.85:
                self._buy_market(Random.draw_quantity())
            elif random_state > 0.5:
                price = Random.draw_price("bid", spread) * (1 - t_cost)
                self._buy_limit(Random.draw_quantity(), price)
            elif random_state < 0.35 and self.orders:
                self._cancel_order(self.orders[-1])

        elif self.sentiment == "Pessimistic":
            if random_state > 0.85:
                self._sell_market(Random.draw_quantity())
            elif random_state > 0.5:
                price = Random.draw_price("ask", spread) * (1 + t_cost)
                self._sell_limit(Random.draw_quantity(), price)
            elif random_state < 0.35 and self.orders:
                self._cancel_order(self.orders[-1])

    def change_sentiment(self, info: SimulatorInfo, a1=1, a2=1, v1=0.1):
        n_traders = len(info.traders)
        n_chartists = sum(tr_type == "Chartist" for tr_type in info.types[-1].values())
        if n_chartists == 0:
            return

        n_optimistic = sum(s == "Optimistic" for s in info.sentiments[-1].values())
        n_pessimists = sum(s == "Pessimistic" for s in info.sentiments[-1].values())

        dp = info.prices[-1] - info.prices[-2] if len(info.prices) > 1 else 0
        try:
            p = self.market.price()
        except Exception:
            return
        if not p:
            return

        x = (n_optimistic - n_pessimists) / n_chartists
        u = a1 * x + a2 / v1 * dp / p
        u = max(-50, min(50, u))

        if self.sentiment == "Optimistic":
            prob = v1 * n_chartists / n_traders * exp(-u)
            if prob > random.random():
                self.sentiment = "Pessimistic"

        elif self.sentiment == "Pessimistic":
            prob = v1 * n_chartists / n_traders * exp(u)
            if prob > random.random():
                self.sentiment = "Optimistic"


class SafeMarketMaker(MarketMaker):
    """MarketMaker with empty-book protection."""

    def call(self):
        spread = self.market.spread()
        if spread is None:
            return

        for order in self.orders.copy():
            self._cancel_order(order)

        bid_volume = max(0.0, self.ul - 1 - self.assets)
        ask_volume = max(0.0, self.assets - self.ll - 1)

        if not bid_volume or not ask_volume:
            self.panic = True
            return

        self.panic = False
        base_offset = -((spread["ask"] - spread["bid"]) * (self.assets / self.softlimit))
        self._buy_limit(bid_volume, spread["bid"] - base_offset - 0.1)
        self._sell_limit(ask_volume, spread["ask"] + base_offset + 0.1)


def reset_class_ids():
    ExchangeAgent.id = 0
    Trader.id = 0
    Order.order_id = 0


def build_simulation(
    hft_frac: float,
    shock_tick: int,
    shock_dp: float,
    seed: int,
    softlimit: int = DEFAULT_SOFTLIMIT,
    n_random: int = DEFAULT_N_RANDOM,
) -> Simulator:
    patch_order_list_insert()
    random.seed(seed)
    np.random.seed(seed)
    reset_class_ids()

    exchange = VolumeExchangeAgent(volume=1000)

    n_fundamentalists = 10
    n_chartists = 10
    n_fast = int(round(hft_frac * n_chartists))

    fundamentalists = [SafeFundamentalist(exchange, 10**3) for _ in range(n_fundamentalists)]
    chartists = [TrendChartist(exchange, 10**3) for _ in range(n_chartists)]
    random_traders = [Random(exchange, 10**3) for _ in range(n_random)]

    for i, trader in enumerate(chartists):
        trader.speed = "fast" if i < n_fast else "slow"

    for trader in fundamentalists:
        trader.speed = "slow"

    for trader in random_traders:
        trader.speed = "slow"

    maker = SafeMarketMaker(exchange, 10**3, softlimit=softlimit)
    maker.speed = "slow"

    traders = [*fundamentalists, *chartists, *random_traders, maker]
    events = [MarketPriceShock(shock_tick, shock_dp)]
    return Simulator(exchange=exchange, traders=traders, events=events)


def update_behaviour(sim: Simulator):
    for trader in sim.traders:
        if isinstance(trader, Universalist):
            trader.change_strategy(sim.info)
        elif isinstance(trader, Chartist):
            trader.change_sentiment(sim.info)


def call_traders_fast_first(traders: List[Trader], speed_multiplier: int = 1):
    fast = [t for t in traders if getattr(t, "speed", "slow") == "fast"]
    slow = [t for t in traders if getattr(t, "speed", "slow") != "fast"]

    for _ in range(speed_multiplier):
        random.shuffle(fast)
        for trader in fast:
            trader.call()

    random.shuffle(slow)
    for trader in slow:
        trader.call()


def apply_payments(sim: Simulator):
    dividend = sim.exchange.dividend()
    risk_free = sim.exchange.risk_free
    for trader in sim.traders:
        trader.cash += trader.assets * dividend
        trader.cash += trader.cash * risk_free


def simulate_calendar(
    sim: Simulator,
    n_ticks: int,
    speed_multiplier: int,
    silent: bool = True,
) -> SimDiagnostics:
    depleted_by_tick = []
    iterator = tqdm(range(n_ticks), desc="calendar", disable=silent)
    for tick in iterator:
        if sim.events:
            for event in sim.events:
                event.call(tick)

        sim.info.capture()
        depleted_by_tick.append(sim.exchange.is_book_depleted())
        update_behaviour(sim)
        call_traders_fast_first(sim.traders, speed_multiplier=speed_multiplier)
        apply_payments(sim)
        sim.exchange.generate_dividend()

    return SimDiagnostics(
        avg_sub_iters=1.0,
        max_sub_iters_observed=1,
        threshold_hit_rate=1.0,
        executed_volume_total=sim.exchange.executed_volume_total,
        book_depleted_rate=float(np.mean(depleted_by_tick)) if depleted_by_tick else 0.0,
    )


def simulate_event_time(
    sim: Simulator,
    n_ticks: int,
    volume_threshold: int,
    speed_multiplier: int,
    max_sub_iters: int,
    silent: bool = True,
) -> SimDiagnostics:
    sub_iters_by_tick = []
    threshold_hits = []
    depleted_by_tick = []

    iterator = tqdm(range(n_ticks), desc=f"event_time_V{volume_threshold}", disable=silent)
    for tick in iterator:
        if sim.events:
            for event in sim.events:
                event.call(tick)

        sim.info.capture()
        depleted_by_tick.append(sim.exchange.is_book_depleted())
        update_behaviour(sim)
        sim.exchange.reset_tick_counters()

        sub_iters = 0
        while sim.exchange.executed_volume_tick < volume_threshold and sub_iters < max_sub_iters:
            call_traders_fast_first(sim.traders, speed_multiplier=speed_multiplier)
            sub_iters += 1

        threshold_hits.append(sim.exchange.executed_volume_tick >= volume_threshold)
        sub_iters_by_tick.append(sub_iters)

        apply_payments(sim)
        sim.exchange.generate_dividend()

    return SimDiagnostics(
        avg_sub_iters=float(np.mean(sub_iters_by_tick)) if sub_iters_by_tick else 0.0,
        max_sub_iters_observed=int(max(sub_iters_by_tick)) if sub_iters_by_tick else 0,
        threshold_hit_rate=float(np.mean(threshold_hits)) if threshold_hits else 0.0,
        executed_volume_total=sim.exchange.executed_volume_total,
        book_depleted_rate=float(np.mean(depleted_by_tick)) if depleted_by_tick else 0.0,
    )


def safe_mean(values: Iterable[float], default: float = np.nan) -> float:
    vals = [v for v in values if v is not None and np.isfinite(v)]
    return float(np.mean(vals)) if vals else default


def price_vol_ratio(info: SimulatorInfo, shock_tick: int, window: int) -> float:
    vols = info.price_volatility(window=window)
    pre = vols[: max(shock_tick - window, 0)]
    post = vols[shock_tick:]
    return safe_mean(post) / (safe_mean(pre, default=1e-9) + 1e-9)


def spread_ratio(info: SimulatorInfo, shock_tick: int) -> float:
    def rel_spreads(spreads, prices):
        vals = []
        for spread, price in zip(spreads, prices):
            if spread is None or not price:
                continue
            vals.append((spread["ask"] - spread["bid"]) / price)
        return vals

    pre = rel_spreads(info.spreads[:shock_tick], info.prices[:shock_tick])
    post = rel_spreads(info.spreads[shock_tick:], info.prices[shock_tick:])
    return safe_mean(post) / (safe_mean(pre, default=1e-9) + 1e-9)


def max_drawdown(info: SimulatorInfo, shock_tick: int) -> float:
    if len(info.prices) <= shock_tick:
        return np.nan
    pre_price = info.prices[shock_tick - 1]
    post_prices = info.prices[shock_tick:]
    if not pre_price or not post_prices:
        return np.nan
    return (pre_price - min(post_prices)) / pre_price


def recovery_time(info: SimulatorInfo, shock_tick: int, threshold: float = 0.02) -> int:
    if len(info.prices) <= shock_tick:
        return 0
    pre_price = info.prices[shock_tick - 1]
    if not pre_price:
        return len(info.prices) - shock_tick
    for i, price in enumerate(info.prices[shock_tick:]):
        if abs(price - pre_price) / pre_price < threshold:
            return i
    return len(info.prices) - shock_tick


def mm_stress_ratio(info: SimulatorInfo, shock_tick: int, softlimit: int) -> float:
    stress = []
    for types_snapshot, assets_snapshot in zip(info.types[shock_tick:], info.assets[shock_tick:]):
        stressed_now = False
        for trader_id, trader_type in types_snapshot.items():
            if trader_type == "Market Maker" and abs(assets_snapshot.get(trader_id, 0)) >= softlimit:
                stressed_now = True
                break
        stress.append(stressed_now)
    return float(np.mean(stress)) if stress else 0.0


def compute_metrics(
    info: SimulatorInfo,
    shock_tick: int,
    vol_window: int,
    softlimit: int,
) -> Dict[str, float]:
    return {
        "vol_ratio": price_vol_ratio(info, shock_tick=shock_tick, window=vol_window),
        "spread_ratio": spread_ratio(info, shock_tick=shock_tick),
        "max_drawdown": max_drawdown(info, shock_tick=shock_tick),
        "recovery_time": recovery_time(info, shock_tick=shock_tick),
        "mm_stress_ratio": mm_stress_ratio(info, shock_tick=shock_tick, softlimit=softlimit),
    }


def run_one(
    mode: str,
    hft_frac: float,
    run_id: int,
    seed: int,
    n_ticks: int,
    shock_tick: int,
    shock_dp: float,
    volume_threshold: Optional[int],
    speed_multiplier: int,
    max_sub_iters: int,
    vol_window: int,
    softlimit: int,
    n_random: int,
    silent: bool,
) -> Dict[str, float]:
    sim = build_simulation(
        hft_frac=hft_frac,
        shock_tick=shock_tick,
        shock_dp=shock_dp,
        seed=seed,
        softlimit=softlimit,
        n_random=n_random,
    )

    if mode == "calendar":
        diagnostics = simulate_calendar(
            sim,
            n_ticks=n_ticks,
            speed_multiplier=speed_multiplier,
            silent=silent,
        )
        regime = "calendar"
        vstar_value = np.nan

    elif mode == "event_time":
        if volume_threshold is None:
            raise ValueError("event_time mode requires volume_threshold")
        diagnostics = simulate_event_time(
            sim,
            n_ticks=n_ticks,
            volume_threshold=volume_threshold,
            speed_multiplier=speed_multiplier,
            max_sub_iters=max_sub_iters,
            silent=silent,
        )
        regime = f"event_time_V{volume_threshold}"
        vstar_value = volume_threshold

    else:
        raise ValueError(f"Unknown mode: {mode}")

    metrics = compute_metrics(
        sim.info,
        shock_tick=shock_tick,
        vol_window=vol_window,
        softlimit=softlimit,
    )

    return {
        "mode": mode,
        "regime": regime,
        "volume_threshold": vstar_value,
        "hft_frac": hft_frac,
        "run": run_id,
        "seed": seed,
        "n_ticks": n_ticks,
        "shock_tick": shock_tick,
        "shock_dp": shock_dp,
        "speed_multiplier": speed_multiplier,
        "softlimit": softlimit,
        "n_random": n_random,
        **metrics,
        "avg_sub_iters": diagnostics.avg_sub_iters,
        "max_sub_iters_observed": diagnostics.max_sub_iters_observed,
        "threshold_hit_rate": diagnostics.threshold_hit_rate,
        "executed_volume_total": diagnostics.executed_volume_total,
        "book_depleted_rate": diagnostics.book_depleted_rate,
    }


def bootstrap_ci(values: Sequence[float], n_boot: int = 1000, alpha: float = 0.05, seed: int = 123):
    vals = np.array([v for v in values if np.isfinite(v)], dtype=float)
    if len(vals) == 0:
        return np.nan, np.nan
    if len(vals) == 1:
        return float(vals[0]), float(vals[0])

    rng = np.random.default_rng(seed)
    samples = rng.choice(vals, size=(n_boot, len(vals)), replace=True).mean(axis=1)
    return (
        float(np.quantile(samples, alpha / 2)),
        float(np.quantile(samples, 1 - alpha / 2)),
    )


def aggregate_results(raw: pd.DataFrame) -> pd.DataFrame:
    metric_cols = [
        "vol_ratio",
        "spread_ratio",
        "max_drawdown",
        "recovery_time",
        "mm_stress_ratio",
        "avg_sub_iters",
        "threshold_hit_rate",
        "executed_volume_total",
        "book_depleted_rate",
        "calendar_volume_per_tick_target",
        "vstar_to_calendar_tick_ratio",
    ]

    grouped = raw.groupby(["regime", "mode", "volume_threshold", "hft_frac"], dropna=False)
    rows = []
    for keys, sub in grouped:
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
            ci_low, ci_high = bootstrap_ci(sub[col].tolist())
            row[f"{col}_ci_low"] = ci_low
            row[f"{col}_ci_high"] = ci_high
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["regime", "hft_frac"]).reset_index(drop=True)


def compute_tipping_points(agg: pd.DataFrame, multiplier: float = 1.3) -> pd.DataFrame:
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
        rows.append(
            {
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
            }
        )

    return pd.DataFrame(rows).sort_values("regime").reset_index(drop=True)


def mannwhitney_stats(raw: pd.DataFrame) -> pd.DataFrame:
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
                stat, p_value = mannwhitneyu(
                    treatment,
                    baseline,
                    alternative="greater",
                )
            except ValueError:
                stat, p_value = np.nan, np.nan

            rows.append(
                {
                    "regime": regime,
                    "hft_frac": phi,
                    "baseline_mean": float(baseline.mean()),
                    "treatment_mean": float(treatment.mean()),
                    "u_stat": stat,
                    "p_value": p_value,
                    "significant_0_05": bool(p_value < 0.05) if np.isfinite(p_value) else False,
                }
            )

    return pd.DataFrame(rows)


def plot_metrics(agg: pd.DataFrame, output_path: str = METRICS_PNG):
    sns.set_theme(style="whitegrid", context="talk")
    metrics = [
        ("vol_ratio", "Volatility ratio"),
        ("spread_ratio", "Spread ratio"),
        ("max_drawdown", "Max drawdown"),
        ("recovery_time", "Recovery time"),
        ("mm_stress_ratio", "MM stress ratio"),
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


def plot_heatmap(agg: pd.DataFrame, output_path: str = HEATMAP_PNG):
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
    ax.set_title("H2: Mean volatility ratio by regime and HFT share")
    ax.set_xlabel("HFT share phi")
    ax.set_ylabel("Regime")
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def plot_tipping(tipping: pd.DataFrame, output_path: str = TIPPING_PNG):
    sns.set_theme(style="whitegrid", context="talk")
    plot_df = tipping.copy()
    plot_df["phi_star_plot"] = plot_df["phi_star"].fillna(-0.05)
    plot_df["label"] = plot_df["phi_star"].apply(lambda x: "None" if pd.isna(x) else f"{x:.1f}")

    fig, ax = plt.subplots(figsize=(13, 7))
    sns.barplot(data=plot_df, x="regime", y="phi_star_plot", ax=ax, color="#4C78A8")
    ax.axhline(0, color="black", linewidth=1)
    ax.set_title("H2: Tipping point phi* by timekeeping regime")
    ax.set_xlabel("Regime")
    ax.set_ylabel("phi* (None shown below zero)")
    ax.tick_params(axis="x", rotation=25)

    for idx, row in plot_df.reset_index(drop=True).iterrows():
        ax.text(
            idx,
            row["phi_star_plot"] + 0.03,
            row["label"],
            ha="center",
            va="bottom",
            fontsize=12,
        )

    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def calibrated_vstars_from_calendar(calendar_rows: List[Dict[str, float]], multipliers: Sequence[float]):
    """Calibrate Vstar to calendar-time executed volume per recorded tick.

    The calibration uses the phi=0 calendar baseline. This keeps event-time
    ticks close to equal-activity intervals while preserving the same number
    of recorded ticks and the same shock tick.
    """
    baseline_rows = [row for row in calendar_rows if row["hft_frac"] == 0.0]
    if not baseline_rows:
        baseline_rows = calendar_rows

    vol_per_tick = np.mean([
        row["executed_volume_total"] / max(row["n_ticks"], 1)
        for row in baseline_rows
    ])
    vstars = sorted({
        max(1, int(round(vol_per_tick * multiplier)))
        for multiplier in multipliers
    })
    return vstars, float(vol_per_tick)


def run_experiment(args: argparse.Namespace):
    rows = []
    total_calendar_runs = len(args.hft_frac) * args.runs
    progress = tqdm(total=total_calendar_runs, desc="H2 calendar")

    for phi in args.hft_frac:
        for run_id in range(args.runs):
            seed = args.seed + 10_000 * run_id + int(phi * 100)
            rows.append(
                run_one(
                    mode="calendar",
                    hft_frac=phi,
                    run_id=run_id,
                    seed=seed,
                    n_ticks=args.n_ticks,
                    shock_tick=args.shock_tick,
                    shock_dp=args.shock_dp,
                    volume_threshold=None,
                    speed_multiplier=args.speed_multiplier,
                    max_sub_iters=args.max_sub_iters,
                    vol_window=args.vol_window,
                    softlimit=args.softlimit,
                    n_random=args.n_random,
                    silent=True,
                )
            )
            progress.update(1)

    progress.close()

    if args.calibrate_vstar:
        vstars, calendar_volume_per_tick_target = calibrated_vstars_from_calendar(
            rows,
            multipliers=args.vstar_multipliers,
        )
        print(
            "\nCalibrated Vstar from calendar phi=0 volume: "
            f"{calendar_volume_per_tick_target:.3f} volume/tick -> {vstars}"
        )
    else:
        vstars = args.vstar
        calendar_volume_per_tick_target = np.nan

    total_event_runs = len(vstars) * len(args.hft_frac) * args.runs
    progress = tqdm(total=total_event_runs, desc="H2 event-time")

    for vstar in vstars:
        for phi in args.hft_frac:
            for run_id in range(args.runs):
                seed = args.seed + 1_000_000 + 10_000 * run_id + 100 * vstar + int(phi * 100)
                rows.append(
                    run_one(
                        mode="event_time",
                        hft_frac=phi,
                        run_id=run_id,
                        seed=seed,
                        n_ticks=args.n_ticks,
                        shock_tick=args.shock_tick,
                        shock_dp=args.shock_dp,
                        volume_threshold=vstar,
                        speed_multiplier=args.speed_multiplier,
                        max_sub_iters=args.max_sub_iters,
                        vol_window=args.vol_window,
                        softlimit=args.softlimit,
                        n_random=args.n_random,
                        silent=True,
                    )
                )
                progress.update(1)

    progress.close()

    for row in rows:
        row["calendar_volume_per_tick_target"] = calendar_volume_per_tick_target
        if np.isfinite(calendar_volume_per_tick_target) and row.get("volume_threshold") == row.get("volume_threshold"):
            row["vstar_to_calendar_tick_ratio"] = row["volume_threshold"] / calendar_volume_per_tick_target
        else:
            row["vstar_to_calendar_tick_ratio"] = np.nan

    raw = pd.DataFrame(rows)
    agg = aggregate_results(raw)
    tipping = compute_tipping_points(agg, multiplier=args.threshold_multiplier)
    stats = mannwhitney_stats(raw)

    raw.to_csv(args.raw_out, index=False)
    agg.to_csv(args.agg_out, index=False)
    tipping.to_csv(args.tipping_out, index=False)
    stats.to_csv(args.stats_out, index=False)

    if not args.no_plots:
        plot_metrics(agg, output_path=args.metrics_png)
        plot_heatmap(agg, output_path=args.heatmap_png)
        plot_tipping(tipping, output_path=args.tipping_png)

    print("\nSaved:")
    print(f"  {args.raw_out}")
    print(f"  {args.agg_out}")
    print(f"  {args.tipping_out}")
    print(f"  {args.stats_out}")
    if not args.no_plots:
        print(f"  {args.metrics_png}")
        print(f"  {args.heatmap_png}")
        print(f"  {args.tipping_png}")

    print("\nTipping summary:")
    print(tipping.to_string(index=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run H2 calendar-time versus event-time volume-clock experiment."
    )
    parser.add_argument("--runs", type=int, default=DEFAULT_N_RUNS)
    parser.add_argument("--n-ticks", type=int, default=DEFAULT_N_TICKS)
    parser.add_argument("--shock-tick", type=int, default=DEFAULT_SHOCK_TICK)
    parser.add_argument("--shock-dp", type=float, default=DEFAULT_SHOCK_DP)
    parser.add_argument("--vstar", type=int, nargs="+", default=DEFAULT_VSTARS)
    parser.add_argument("--calibrate-vstar", action="store_true")
    parser.add_argument("--vstar-multipliers", type=float, nargs="+", default=DEFAULT_VSTAR_MULTIPLIERS)
    parser.add_argument("--hft-frac", type=float, nargs="+", default=DEFAULT_HFT_FRACS)
    parser.add_argument("--speed-multiplier", type=int, default=DEFAULT_SPEED_MULTIPLIER)
    parser.add_argument("--max-sub-iters", type=int, default=DEFAULT_MAX_SUB_ITERS)
    parser.add_argument("--vol-window", type=int, default=DEFAULT_VOL_WINDOW)
    parser.add_argument("--softlimit", type=int, default=DEFAULT_SOFTLIMIT)
    parser.add_argument("--n-random", type=int, default=DEFAULT_N_RANDOM)
    parser.add_argument("--threshold-multiplier", type=float, default=1.3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-plots", action="store_true")

    parser.add_argument("--raw-out", default=RAW_OUT)
    parser.add_argument("--agg-out", default=AGG_OUT)
    parser.add_argument("--tipping-out", default=TIPPING_OUT)
    parser.add_argument("--stats-out", default=STATS_OUT)
    parser.add_argument("--metrics-png", default=METRICS_PNG)
    parser.add_argument("--heatmap-png", default=HEATMAP_PNG)
    parser.add_argument("--tipping-png", default=TIPPING_PNG)

    return parser.parse_args()


if __name__ == "__main__":
    run_experiment(parse_args())
