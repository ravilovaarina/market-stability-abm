"""
experiment_noisy_delay.py
=========================

Mechanism-isolation experiment for H1:
information delay is applied only to noisy Random agents.

Purpose:
- keep TrendChartist and Fundamentalist agents without information delay,
- apply `info_lag` only to noisy order placement,
- test whether stale noisy spread information is an independent source of
  post-shock instability.

Grid:
- hft_frac in {0.0, 0.1, ..., 1.0}
- info_lag in {0, 1, 3, 5, 10}
- 30 runs per parameter combination by default

Outputs:
- noisy_delay_raw.csv
- noisy_delay_agg.csv
- noisy_delay_tipping.csv
- noisy_delay_metrics.png
- noisy_delay_heatmap.png
"""

from __future__ import annotations

import argparse
import os
import random
from math import exp

os.environ.setdefault("MPLCONFIGDIR", "/tmp/1d-abm-mplconfig")
os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from tqdm import tqdm

from AgentBasedModel.agents import (
    ExchangeAgent,
    Fundamentalist,
    Chartist,
    MarketMaker,
    Random,
)
from AgentBasedModel.simulator import SimulatorInfo
from AgentBasedModel.events import MarketPriceShock
from AgentBasedModel.utils.math import mean


HFT_FRACS = [round(x * 0.1, 1) for x in range(11)]
INFO_LAGS = [0, 1, 3, 5, 10]
THRESHOLD_MULTIPLIER = 1.3


# ============================================================================
# Agent classes
# ============================================================================

class TrendChartist(Chartist):
    """
    Trend-following chartist with corrected sentiment-switching signs.

    This is the same H1 behavioral logic used in the unified experiment, but
    here both fast and slow chartists observe real-time information. The only
    delayed agents in this script are noisy Random agents.
    """

    def change_sentiment(self, info, a1=1, a2=1, v1=0.1):
        n_traders = len(info.traders)
        n_chartists = sum(v == "Chartist" for v in info.types[-1].values())
        if n_chartists == 0:
            return

        n_optimistic = sum(v == "Optimistic" for v in info.sentiments[-1].values())
        n_pessimists = sum(v == "Pessimistic" for v in info.sentiments[-1].values())

        dp = info.prices[-1] - info.prices[-2] if len(info.prices) > 1 else 0
        try:
            p = self.market.price()
        except Exception:
            return

        x = (n_optimistic - n_pessimists) / max(n_chartists, 1)
        U = a1 * x + a2 / v1 * dp / p
        U = max(-50, min(50, U))

        if self.sentiment == "Optimistic":
            prob = v1 * n_chartists / n_traders * exp(-U)
            if prob > random.random():
                self.sentiment = "Pessimistic"
        elif self.sentiment == "Pessimistic":
            prob = v1 * n_chartists / n_traders * exp(U)
            if prob > random.random():
                self.sentiment = "Optimistic"


class DelayedRandom(Random):
    """
    Random agent whose limit-order pricing uses delayed spread information.

    The base Random.call() reads self.market.spread() directly, so passing
    info_lag to Random is not enough. This subclass keeps the same action
    probabilities as Random, but obtains spread via Trader._get_spread().
    """

    def call(self):
        spread = self._get_spread()
        if spread is None:
            return

        random_state = random.random()
        order_type = "bid" if random_state > 0.5 else "ask"

        random_state = random.random()

        # Market order
        if random_state > 0.85:
            quantity = self.draw_quantity()
            if order_type == "bid":
                self._buy_market(quantity)
            elif order_type == "ask":
                self._sell_market(quantity)

        # Limit order, priced from delayed spread
        elif random_state > 0.5:
            price = self.draw_price(order_type, spread)
            quantity = self.draw_quantity()
            if order_type == "bid":
                self._buy_limit(quantity, price)
            elif order_type == "ask":
                self._sell_limit(quantity, price)

        # Cancellation order
        elif random_state < 0.35:
            if self.orders:
                order_n = random.randint(0, len(self.orders) - 1)
                self._cancel_order(self.orders[order_n])


# ============================================================================
# Simulator
# ============================================================================

class SimulatorNoisyDelay:
    """
    Simulator with H1 fast/slow activation and exchange.record_state().

    Fast chartists act first. Each fast chartist acts once per iteration by
    default, matching the v9-style priority-only speed advantage.
    """

    def __init__(self, exchange, traders, events=None):
        self.exchange = exchange
        self.traders = traders
        self.events = [event.link(self) for event in events] if events else None
        self.info = SimulatorInfo(exchange, traders)

    def _payments(self):
        for trader in self.traders:
            trader.cash += trader.assets * self.exchange.dividend()
            trader.cash += trader.cash * self.exchange.risk_free

    def simulate(self, n_iter, silent=False, speed_multiplier=1):
        for it in tqdm(range(n_iter), desc="Simulation", disable=silent):
            if self.events:
                for event in self.events:
                    event.call(it)

            self.exchange.record_state()
            self.info.capture()

            for trader in self.traders:
                if isinstance(trader, Chartist) and type(trader).__name__ != "Universalist":
                    trader.change_sentiment(self.info)

            fast = [t for t in self.traders if getattr(t, "speed", "slow") == "fast"]
            slow = [t for t in self.traders if getattr(t, "speed", "slow") != "fast"]

            for _ in range(speed_multiplier):
                random.shuffle(fast)
                for trader in fast:
                    trader.call()

            random.shuffle(slow)
            for trader in slow:
                trader.call()

            self._payments()
            self.exchange.generate_dividend()

        return self


# ============================================================================
# Metrics
# ============================================================================

def vol_ratio(info, shock_it=200, window=10):
    vols = info.price_volatility(window=window)
    pre = vols[:shock_it - window]
    post = vols[shock_it:]
    if not pre or not post:
        return 1.0
    return mean(post) / (mean(pre) + 1e-9)


def spread_ratio(info, shock_it=200):
    def rel_spread(spreads, prices):
        vals = [(s["ask"] - s["bid"]) / p for s, p in zip(spreads, prices) if s and p]
        return mean(vals) if vals else 1e-9

    pre = rel_spread(info.spreads[:shock_it], info.prices[:shock_it])
    post = rel_spread(info.spreads[shock_it:], info.prices[shock_it:])
    return post / (pre + 1e-9)


def max_drawdown(info, shock_it=200):
    pre_price = info.prices[shock_it - 1]
    post = info.prices[shock_it:]
    if not post:
        return 0.0
    return (pre_price - min(post)) / pre_price


def recovery_time(info, shock_it=200, threshold=0.02):
    pre_price = info.prices[shock_it - 1]
    for i, price in enumerate(info.prices[shock_it:]):
        if abs(price - pre_price) / pre_price < threshold:
            return i
    return len(info.prices) - shock_it


# ============================================================================
# Population and run loop
# ============================================================================

def create_population(
    exchange,
    hft_frac=0.3,
    noisy_lag=0,
    n_chartists=10,
    n_fundamentalists=10,
    n_random=5,
    n_mm=1,
    softlimit=100,
):
    traders = []

    n_fast = round(hft_frac * n_chartists)
    n_slow = n_chartists - n_fast

    for _ in range(n_fast):
        trader = TrendChartist(exchange, cash=10**3, info_lag=0)
        trader.speed = "fast"
        traders.append(trader)

    for _ in range(n_slow):
        trader = TrendChartist(exchange, cash=10**3, info_lag=0)
        trader.speed = "slow"
        traders.append(trader)

    for _ in range(n_fundamentalists):
        trader = Fundamentalist(exchange, cash=10**3, access=1, info_lag=0)
        trader.speed = "slow"
        traders.append(trader)

    for _ in range(n_random):
        trader = DelayedRandom(exchange, cash=10**3, info_lag=noisy_lag)
        trader.speed = "slow"
        traders.append(trader)

    for _ in range(n_mm):
        trader = MarketMaker(exchange, cash=10**3, softlimit=softlimit)
        trader.speed = "slow"
        traders.append(trader)

    return traders


def run_one(
    hft_frac,
    noisy_lag=0,
    n_iter=500,
    shock_it=200,
    shock_dp=-10,
    softlimit=100,
    speed_multiplier=1,
    seed=None,
):
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)

    exchange = ExchangeAgent(price=100, std=25, volume=1000, rf=5e-4)
    traders = create_population(
        exchange,
        hft_frac=hft_frac,
        noisy_lag=noisy_lag,
        softlimit=softlimit,
    )

    sim = SimulatorNoisyDelay(
        exchange=exchange,
        traders=traders,
        events=[MarketPriceShock(shock_it, shock_dp)],
    )
    sim.simulate(n_iter, silent=True, speed_multiplier=speed_multiplier)
    info = sim.info

    return {
        "hft_frac": hft_frac,
        "info_lag": noisy_lag,
        "speed_mult": speed_multiplier,
        "vol_ratio": vol_ratio(info, shock_it),
        "spread_ratio": spread_ratio(info, shock_it),
        "max_drawdown": max_drawdown(info, shock_it),
        "recovery_time": recovery_time(info, shock_it),
        "mm_panic_ratio": info.mm_panic_ratio(from_it=shock_it),
    }


def run_grid(
    n_runs=30,
    n_iter=500,
    shock_it=200,
    shock_dp=-10,
    softlimit=100,
    speed_multiplier=1,
    raw_out_path=None,
    resume=True,
):
    records = []
    completed = set()

    if resume and raw_out_path and os.path.exists(raw_out_path):
        previous = pd.read_csv(raw_out_path)
        if not previous.empty:
            records.extend(previous.to_dict("records"))
            completed.update(
                (
                    float(row["hft_frac"]),
                    int(row["info_lag"]),
                    int(row["run"]),
                )
                for _, row in previous.iterrows()
            )

    total = len(INFO_LAGS) * len(HFT_FRACS) * n_runs
    print(
        f"Noisy-delay grid: {len(INFO_LAGS)} lags × {len(HFT_FRACS)} phi values × {n_runs} runs = {total} runs"
    )
    if completed:
        print(f"Resume enabled: {len(completed)} runs already recorded and will be skipped.")

    for lag in INFO_LAGS:
        for phi in tqdm(HFT_FRACS, desc=f"noisy_lag={lag}"):
            for run in range(n_runs):
                key = (float(phi), int(lag), int(run))
                if key in completed:
                    continue

                seed = run * 10000 + int(phi * 10) * 100 + lag + 700
                row = run_one(
                    phi,
                    noisy_lag=lag,
                    n_iter=n_iter,
                    shock_it=shock_it,
                    shock_dp=shock_dp,
                    softlimit=softlimit,
                    speed_multiplier=speed_multiplier,
                    seed=seed,
                )
                row["run"] = run
                row["grid"] = "noisy_delay"
                records.append(row)
                completed.add(key)

                if raw_out_path:
                    pd.DataFrame(records).to_csv(raw_out_path, index=False)

    return pd.DataFrame(records)


# ============================================================================
# Aggregation and tipping points
# ============================================================================

def aggregate(df):
    return (
        df.groupby(["grid", "speed_mult", "info_lag", "hft_frac"])
        .agg(
            vol_ratio_mean=("vol_ratio", "mean"),
            vol_ratio_std=("vol_ratio", "std"),
            spread_ratio_mean=("spread_ratio", "mean"),
            spread_ratio_std=("spread_ratio", "std"),
            drawdown_mean=("max_drawdown", "mean"),
            drawdown_std=("max_drawdown", "std"),
            recovery_mean=("recovery_time", "mean"),
            recovery_std=("recovery_time", "std"),
            mm_panic_mean=("mm_panic_ratio", "mean"),
            mm_panic_std=("mm_panic_ratio", "std"),
            n_runs=("vol_ratio", "count"),
        )
        .reset_index()
    )


def find_tipping_point(means, multiplier=THRESHOLD_MULTIPLIER):
    if 0.0 not in means.index:
        return None, np.nan, np.nan

    baseline = float(means.loc[0.0])
    threshold = baseline * multiplier

    for phi, value in means.sort_index().items():
        if phi == 0.0:
            continue
        if value >= threshold:
            return float(phi), baseline, threshold

    return None, baseline, threshold


def build_tipping_table(df):
    rows = []
    for lag, sub in df.groupby("info_lag"):
        means = sub.groupby("hft_frac")["vol_ratio"].mean().sort_index()
        phi_star, baseline, threshold = find_tipping_point(means)
        rows.append(
            {
                "info_lag": int(lag),
                "baseline_vol_ratio": baseline,
                "threshold_1_3x": threshold,
                "phi_star": phi_star,
                "max_vol_ratio": float(means.max()),
                "phi_at_max": float(means.idxmax()),
                "n_runs_per_phi_min": int(sub.groupby("hft_frac").size().min()),
                "n_runs_per_phi_max": int(sub.groupby("hft_frac").size().max()),
            }
        )
    return pd.DataFrame(rows).sort_values("info_lag")


def bootstrap_ci(data, n_bootstrap=1000, ci=0.95, seed=42):
    rng = np.random.RandomState(seed)
    data = np.asarray(data)
    if len(data) <= 1:
        value = float(np.mean(data)) if len(data) else np.nan
        return value, value

    means = []
    for _ in range(n_bootstrap):
        sample = rng.choice(data, size=len(data), replace=True)
        means.append(np.mean(sample))

    alpha = (1 - ci) / 2
    return np.percentile(means, [alpha * 100, (1 - alpha) * 100])


# ============================================================================
# Plots
# ============================================================================

def plot_metrics(df_raw, save_path):
    metrics = [
        ("vol_ratio", "Volatility ratio (after/before)"),
        ("spread_ratio", "Spread ratio (after/before)"),
        ("max_drawdown", "Max drawdown"),
        ("recovery_time", "Recovery time (iterations)"),
        ("mm_panic_ratio", "MarketMaker panic ratio"),
    ]
    colors = plt.cm.plasma(np.linspace(0.15, 0.85, len(INFO_LAGS)))

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))

    for idx, (metric, title) in enumerate(metrics):
        ax = axes[idx // 3, idx % 3]

        for lag, color in zip(INFO_LAGS, colors):
            sub = df_raw[df_raw["info_lag"] == lag]
            grouped = sub.groupby("hft_frac")[metric]
            means = grouped.mean().sort_index()

            ci_lo = []
            ci_hi = []
            for phi in means.index:
                lo, hi = bootstrap_ci(grouped.get_group(phi).values)
                ci_lo.append(lo)
                ci_hi.append(hi)

            label = f"noisy lag={lag}" + (" (baseline)" if lag == 0 else "")
            ax.plot(means.index, means.values, "o-", color=color, lw=2, label=label)
            ax.fill_between(means.index, ci_lo, ci_hi, alpha=0.15, color=color)

            if metric == "vol_ratio":
                phi_star, baseline, threshold = find_tipping_point(means)
                ax.axhline(baseline, color=color, lw=0.8, ls="--", alpha=0.35)
                ax.axhline(threshold, color=color, lw=0.9, ls=":", alpha=0.45)
                if phi_star is not None:
                    ax.axvline(phi_star, color=color, lw=0.9, ls=":", alpha=0.35)

        ax.set(title=title, xlabel="HFT fraction (phi)", ylabel=metric)
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)

    ax = axes[1, 2]
    ax.axis("off")
    tipping = build_tipping_table(df_raw)
    table_rows = []
    for _, row in tipping.iterrows():
        phi_star = row["phi_star"]
        table_rows.append(
            [
                f"lag={int(row['info_lag'])}",
                f"{row['baseline_vol_ratio']:.2f}",
                f"{row['threshold_1_3x']:.2f}",
                f"{phi_star:.1f}" if pd.notna(phi_star) else "—",
                f"{row['max_vol_ratio']:.2f}",
            ]
        )

    table = ax.table(
        cellText=table_rows,
        colLabels=["Condition", "Baseline", "1.3x", "phi*", "Max"],
        cellLoc="center",
        loc="center",
    )
    table.auto_set_font_size(True)
    ax.set_title("Tipping summary for vol_ratio", fontsize=9)

    fig.suptitle(
        "Noisy-agent delay experiment\n"
        "Only Random agents receive delayed spread information | 30 runs | Shading = 95% bootstrap CI",
        fontsize=12,
        fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_heatmap(df_raw, tipping, save_path):
    pivot = (
        df_raw.groupby(["info_lag", "hft_frac"])["vol_ratio"]
        .mean()
        .unstack("hft_frac")
        .sort_index()
    )

    fig, ax = plt.subplots(figsize=(11, 5))
    im = ax.imshow(pivot.values, aspect="auto", origin="lower", cmap="RdYlGn_r")

    ax.set_title(
        "Noisy-agent delay heatmap: mean vol_ratio\n"
        "Black square = first phi crossing 1.3x baseline",
        fontsize=12,
        fontweight="bold",
    )
    ax.set_xlabel("HFT fraction (phi)")
    ax.set_ylabel("Noisy-agent info_lag")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([f"{x:.1f}" for x in pivot.columns])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([str(int(x)) for x in pivot.index])

    for y, lag in enumerate(pivot.index):
        for x, phi in enumerate(pivot.columns):
            value = pivot.loc[lag, phi]
            ax.text(x, y, f"{value:.2f}", ha="center", va="center", fontsize=8)

        row = tipping[tipping["info_lag"] == lag]
        if not row.empty and pd.notna(row.iloc[0]["phi_star"]):
            phi_star = row.iloc[0]["phi_star"]
            if phi_star in list(pivot.columns):
                x_star = list(pivot.columns).index(phi_star)
                ax.scatter(
                    [x_star],
                    [y],
                    marker="s",
                    s=160,
                    facecolors="none",
                    edgecolors="black",
                    linewidths=1.5,
                )

    cbar = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.03)
    cbar.set_label("Mean vol_ratio")
    fig.tight_layout()
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Run noisy-agent delay experiment.")
    parser.add_argument("--n-runs", type=int, default=30)
    parser.add_argument("--n-iter", type=int, default=500)
    parser.add_argument("--shock-it", type=int, default=200)
    parser.add_argument("--shock-dp", type=float, default=-10)
    parser.add_argument("--softlimit", type=int, default=100)
    parser.add_argument(
        "--speed-multiplier",
        type=int,
        default=1,
        help="Fast chartist calls per iteration. Default 1 matches v9 priority-only speed.",
    )
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    raw_out = os.path.join(base_dir, "noisy_delay_raw.csv")
    agg_out = os.path.join(base_dir, "noisy_delay_agg.csv")
    tipping_out = os.path.join(base_dir, "noisy_delay_tipping.csv")
    metrics_png = os.path.join(base_dir, "noisy_delay_metrics.png")
    heatmap_png = os.path.join(base_dir, "noisy_delay_heatmap.png")

    df_raw = run_grid(
        n_runs=args.n_runs,
        n_iter=args.n_iter,
        shock_it=args.shock_it,
        shock_dp=args.shock_dp,
        softlimit=args.softlimit,
        speed_multiplier=args.speed_multiplier,
        raw_out_path=raw_out,
        resume=not args.no_resume,
    )

    agg = aggregate(df_raw)
    tipping = build_tipping_table(df_raw)

    agg.to_csv(agg_out, index=False)
    tipping.to_csv(tipping_out, index=False)
    plot_metrics(df_raw, metrics_png)
    plot_heatmap(df_raw, tipping, heatmap_png)

    print("\nSaved:")
    print(f"  {raw_out}")
    print(f"  {agg_out}")
    print(f"  {tipping_out}")
    print(f"  {metrics_png}")
    print(f"  {heatmap_png}")
    print()
    print(tipping.to_string(index=False))


if __name__ == "__main__":
    main()
