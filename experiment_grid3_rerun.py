"""
experiment_grid3_rerun.py
=========================

Targeted rerun of Unified Experiment Grid 3 only.

Purpose:
- recompute only the combined grid (speed + delay),
- save results into separate files,
- keep old unified results untouched,
- support resume / incremental saving / narrower sub-grids.

This script does NOT rerun Grid 1 or Grid 2.
"""

import os
import signal
import random
import argparse
from math import exp

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from tqdm import tqdm

from AgentBasedModel.agents import (
    ExchangeAgent, Fundamentalist, Chartist, MarketMaker, Random
)
from AgentBasedModel.simulator import SimulatorInfo
from AgentBasedModel.events import MarketPriceShock
from AgentBasedModel.utils.math import mean


# ============================================================================
# Agent classes
# ============================================================================

class TrendChartist(Chartist):
    def change_sentiment(self, info, a1=1, a2=1, v1=0.1):
        n_traders = len(info.traders)
        n_chartists = sum(v == 'Chartist' for v in info.types[-1].values())
        if n_chartists == 0:
            return

        n_optimistic = sum(v == 'Optimistic' for v in info.sentiments[-1].values())
        n_pessimists = sum(v == 'Pessimistic' for v in info.sentiments[-1].values())

        dp = info.prices[-1] - info.prices[-2] if len(info.prices) > 1 else 0
        try:
            p = self.market.price()
        except Exception:
            return

        x = (n_optimistic - n_pessimists) / max(n_chartists, 1)
        U = a1 * x + a2 / v1 * dp / p
        U = max(-50, min(50, U))

        if self.sentiment == 'Optimistic':
            prob = v1 * n_chartists / n_traders * exp(-U)
            if prob > random.random():
                self.sentiment = 'Pessimistic'
        elif self.sentiment == 'Pessimistic':
            prob = v1 * n_chartists / n_traders * exp(U)
            if prob > random.random():
                self.sentiment = 'Optimistic'


class SlowTrendChartist(TrendChartist):
    def __init__(self, market, cash, assets=0, lag=3, info_lag=0):
        super().__init__(market, cash, assets, info_lag=info_lag)
        self.lag = lag

    def change_sentiment(self, info, a1=1, a2=1, v1=0.1):
        n_traders = len(info.traders)
        n_chartists = sum(v == 'Chartist' for v in info.types[-1].values())
        if n_chartists == 0:
            return

        n_optimistic = sum(v == 'Optimistic' for v in info.sentiments[-1].values())
        n_pessimists = sum(v == 'Pessimistic' for v in info.sentiments[-1].values())

        if self.lag == 0 or len(info.prices) <= self.lag + 1:
            dp = info.prices[-1] - info.prices[-2] if len(info.prices) > 1 else 0
        else:
            dp = info.prices[-1 - self.lag] - info.prices[-2 - self.lag]

        try:
            p = self.market.price()
        except Exception:
            return

        x = (n_optimistic - n_pessimists) / max(n_chartists, 1)
        U = a1 * x + a2 / v1 * dp / p
        U = max(-50, min(50, U))

        if self.sentiment == 'Optimistic':
            prob = v1 * n_chartists / n_traders * exp(-U)
            if prob > random.random():
                self.sentiment = 'Pessimistic'
        elif self.sentiment == 'Pessimistic':
            prob = v1 * n_chartists / n_traders * exp(U)
            if prob > random.random():
                self.sentiment = 'Optimistic'


# ============================================================================
# Unified simulator
# ============================================================================

class SimulatorUnified:
    def __init__(self, exchange, traders, events=None):
        self.exchange = exchange
        self.traders = traders
        self.events = [e.link(self) for e in events] if events else None
        self.info = SimulatorInfo(exchange, traders)

    def _payments(self):
        for t in self.traders:
            t.cash += t.assets * self.exchange.dividend()
            t.cash += t.cash * self.exchange.risk_free

    def simulate(self, n_iter, silent=False, speed_multiplier=1):
        for it in tqdm(range(n_iter), desc="Simulation", disable=silent):
            if self.events:
                for e in self.events:
                    e.call(it)

            self.exchange.record_state()
            self.info.capture()

            for t in self.traders:
                if isinstance(t, Chartist) and type(t).__name__ != 'Universalist':
                    t.change_sentiment(self.info)

            fast = [t for t in self.traders if getattr(t, 'speed', 'slow') == 'fast']
            slow = [t for t in self.traders if getattr(t, 'speed', 'slow') != 'fast']

            for _ in range(speed_multiplier):
                random.shuffle(fast)
                for t in fast:
                    t.call()

            random.shuffle(slow)
            for t in slow:
                t.call()

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
        vals = [(s['ask'] - s['bid']) / p for s, p in zip(spreads, prices) if s and p]
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
    for i, p in enumerate(info.prices[shock_it:]):
        if abs(p - pre_price) / pre_price < threshold:
            return i
    return len(info.prices) - shock_it


# ============================================================================
# Population + run
# ============================================================================

def create_population(exchange, hft_frac=0.3, info_lag=0, softlimit=100,
                      n_chartists=10, n_fundamentalists=10, n_random=5, n_mm=1):
    traders = []

    n_fast = round(hft_frac * n_chartists)
    n_slow = n_chartists - n_fast

    for _ in range(n_fast):
        t = TrendChartist(exchange, cash=10**3, info_lag=0)
        t.speed = 'fast'
        traders.append(t)

    for _ in range(n_slow):
        t = SlowTrendChartist(exchange, cash=10**3, lag=info_lag, info_lag=info_lag)
        t.speed = 'slow'
        traders.append(t)

    for _ in range(n_fundamentalists):
        t = Fundamentalist(exchange, cash=10**3, access=1, info_lag=info_lag)
        t.speed = 'slow'
        traders.append(t)

    for _ in range(n_random):
        t = Random(exchange, cash=10**3, info_lag=0)
        t.speed = 'slow'
        traders.append(t)

    for _ in range(n_mm):
        mm = MarketMaker(exchange, cash=10**3, softlimit=softlimit)
        mm.speed = 'slow'
        traders.append(mm)

    return traders


def run_one(hft_frac, info_lag=0, speed_multiplier=1,
            n_iter=500, shock_it=200, shock_dp=-10,
            softlimit=100, seed=None):
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)

    exchange = ExchangeAgent(price=100, std=25, volume=1000, rf=5e-4)
    traders = create_population(
        exchange,
        hft_frac=hft_frac,
        info_lag=info_lag,
        softlimit=softlimit,
    )

    sim = SimulatorUnified(
        exchange=exchange,
        traders=traders,
        events=[MarketPriceShock(shock_it, shock_dp)]
    )
    sim.simulate(n_iter, silent=True, speed_multiplier=speed_multiplier)
    info = sim.info

    return {
        'hft_frac': hft_frac,
        'info_lag': info_lag,
        'speed_mult': speed_multiplier,
        'vol_ratio': vol_ratio(info, shock_it),
        'spread_ratio': spread_ratio(info, shock_it),
        'max_drawdown': max_drawdown(info, shock_it),
        'recovery_time': recovery_time(info, shock_it),
        'mm_panic_ratio': info.mm_panic_ratio(from_it=shock_it),
    }


# ============================================================================
# Grid 3 rerun only
# ============================================================================

def _timeout_handler(signum, frame):
    raise TimeoutError("Simulation took too long")


def run_grid3_rerun(
    n_runs=30,
    n_iter=500,
    shock_it=200,
    shock_dp=-10,
    softlimit=100,
    speed_mults=None,
    info_lags=None,
    hft_fracs=None,
    timeout_sec=45,
    raw_out_path=None,
    skip_out_path=None,
    resume=True,
):
    if speed_mults is None:
        speed_mults = [2, 3]
    if info_lags is None:
        info_lags = [1, 3, 5]
    if hft_fracs is None:
        hft_fracs = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]

    records = []
    skipped = []
    completed = set()

    if resume and raw_out_path and os.path.exists(raw_out_path):
        prev_raw = pd.read_csv(raw_out_path)
        if not prev_raw.empty:
            records.extend(prev_raw.to_dict("records"))
            completed.update(
                (
                    int(row["speed_mult"]),
                    int(row["info_lag"]),
                    float(row["hft_frac"]),
                    int(row["run"]),
                )
                for _, row in prev_raw.iterrows()
            )

    if resume and skip_out_path and os.path.exists(skip_out_path):
        prev_skips = pd.read_csv(skip_out_path)
        if not prev_skips.empty:
            skipped.extend(prev_skips.to_dict("records"))
            completed.update(
                (
                    int(row["speed_mult"]),
                    int(row["info_lag"]),
                    float(row["hft_frac"]),
                    int(row["run"]),
                )
                for _, row in prev_skips.iterrows()
            )

    total = len(speed_mults) * len(info_lags) * len(hft_fracs) * n_runs
    print(
        f"Grid 3 rerun: {len(speed_mults)} × {len(info_lags)} × {len(hft_fracs)} × {n_runs} = {total} runs"
    )
    print(f"Timeout per run: {timeout_sec} sec")
    if completed:
        print(f"Resume enabled: {len(completed)} runs already recorded and will be skipped.")

    for sm in speed_mults:
        for lag in info_lags:
            for fs in tqdm(hft_fracs, desc=f"sm={sm},lag={lag}"):
                for run in range(n_runs):
                    key = (int(sm), int(lag), float(fs), int(run))
                    if key in completed:
                        continue
                    seed = run * 10000 + int(fs * 10) * 100 + lag * 10 + sm
                    try:
                        signal.signal(signal.SIGALRM, _timeout_handler)
                        signal.alarm(timeout_sec)
                        r = run_one(
                            fs,
                            info_lag=lag,
                            speed_multiplier=sm,
                            n_iter=n_iter,
                            shock_it=shock_it,
                            shock_dp=shock_dp,
                            softlimit=softlimit,
                            seed=seed,
                        )
                        signal.alarm(0)
                        r['run'] = run
                        r['grid'] = 'combined_rerun'
                        records.append(r)
                        completed.add(key)
                        if raw_out_path:
                            pd.DataFrame(records).to_csv(raw_out_path, index=False)
                        if skip_out_path:
                            pd.DataFrame(skipped).to_csv(skip_out_path, index=False)
                    except (Exception, TimeoutError) as e:
                        signal.alarm(0)
                        skip_row = {
                            'speed_mult': sm,
                            'info_lag': lag,
                            'hft_frac': fs,
                            'run': run,
                            'seed': seed,
                            'error': str(e),
                        }
                        skipped.append(skip_row)
                        completed.add(key)
                        if raw_out_path:
                            pd.DataFrame(records).to_csv(raw_out_path, index=False)
                        if skip_out_path:
                            pd.DataFrame(skipped).to_csv(skip_out_path, index=False)
                        print(f"\nSKIP sm={sm} lag={lag} phi={fs} run={run}: {e}")

    return pd.DataFrame(records), pd.DataFrame(skipped)


def aggregate(df):
    return df.groupby(['grid', 'speed_mult', 'info_lag', 'hft_frac']).agg(
        vol_ratio_mean=('vol_ratio', 'mean'),
        vol_ratio_std=('vol_ratio', 'std'),
        spread_ratio_mean=('spread_ratio', 'mean'),
        drawdown_mean=('max_drawdown', 'mean'),
        recovery_mean=('recovery_time', 'mean'),
        mm_panic_mean=('mm_panic_ratio', 'mean'),
        n_runs=('vol_ratio', 'count'),
    ).reset_index()


def plot_grid3_rerun(df_raw, agg, save_path):
    fig, axes = plt.subplots(2, 3, figsize=(16, 9), sharey=True)

    speed_mults = sorted(agg['speed_mult'].unique())
    info_lags = sorted(agg['info_lag'].unique())

    for i, sm in enumerate(speed_mults):
        for j, lag in enumerate(info_lags):
            ax = axes[i, j]
            sub = agg[(agg['speed_mult'] == sm) & (agg['info_lag'] == lag)].sort_values('hft_frac')
            if sub.empty:
                ax.set_axis_off()
                continue

            ax.plot(sub['hft_frac'], sub['vol_ratio_mean'], 'o-', lw=2)

            baseline = sub.loc[sub['hft_frac'] == 0.0, 'vol_ratio_mean']
            if not baseline.empty:
                baseline = float(baseline.iloc[0])
                ax.axhline(baseline, color='gray', ls='--', lw=1)
                ax.axhline(baseline * 1.3, color='red', ls=':', lw=1.5)
                title_suffix = f"baseline={baseline:.2f}"
            else:
                title_suffix = "no baseline"

            ax.set_title(f"speed×{sm}, lag={lag}\n{title_suffix}", fontsize=10)
            ax.set_xlabel("HFT fraction (phi)")
            ax.grid(alpha=0.25)

    axes[0, 0].set_ylabel("Mean vol_ratio")
    axes[1, 0].set_ylabel("Mean vol_ratio")
    fig.suptitle("Grid 3 rerun: combined effect (speed + delay)", fontsize=14, fontweight='bold')
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close(fig)


def parse_list(value, cast=float):
    if value is None:
        return None
    return [cast(x.strip()) for x in value.split(",") if x.strip()]


def main():
    parser = argparse.ArgumentParser(description="Targeted Grid 3 rerun with resume support.")
    parser.add_argument("--n-runs", type=int, default=30)
    parser.add_argument("--n-iter", type=int, default=500)
    parser.add_argument("--shock-it", type=int, default=200)
    parser.add_argument("--shock-dp", type=float, default=-10)
    parser.add_argument("--softlimit", type=int, default=100)
    parser.add_argument("--timeout-sec", type=int, default=45)
    parser.add_argument("--speed-mults", type=str, default=None,
                        help="Comma-separated list, e.g. 2,3")
    parser.add_argument("--info-lags", type=str, default=None,
                        help="Comma-separated list, e.g. 1,3,5")
    parser.add_argument("--hft-fracs", type=str, default=None,
                        help="Comma-separated list, e.g. 0.0,0.2,0.4")
    parser.add_argument("--no-resume", action="store_true",
                        help="Disable resume from existing rerun files.")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))

    raw_out = os.path.join(base_dir, "grid3_rerun_raw.csv")
    skip_out = os.path.join(base_dir, "grid3_rerun_skips.csv")
    agg_out = os.path.join(base_dir, "grid3_rerun_agg.csv")
    plot_out = os.path.join(base_dir, "grid3_rerun.png")

    df_raw, df_skips = run_grid3_rerun(
        n_runs=args.n_runs,
        n_iter=args.n_iter,
        shock_it=args.shock_it,
        shock_dp=args.shock_dp,
        softlimit=args.softlimit,
        speed_mults=parse_list(args.speed_mults, int),
        info_lags=parse_list(args.info_lags, int),
        hft_fracs=parse_list(args.hft_fracs, float),
        timeout_sec=args.timeout_sec,
        raw_out_path=raw_out,
        skip_out_path=skip_out,
        resume=not args.no_resume,
    )

    if not df_raw.empty:
        agg = aggregate(df_raw)
        agg.to_csv(agg_out, index=False)
        plot_grid3_rerun(df_raw, agg, plot_out)
    else:
        print("No successful runs, so aggregation and plotting were skipped.")

    print("\nSaved:")
    print(f"  {raw_out}")
    print(f"  {skip_out}")
    if not df_raw.empty:
        print(f"  {agg_out}")
        print(f"  {plot_out}")


if __name__ == "__main__":
    main()
