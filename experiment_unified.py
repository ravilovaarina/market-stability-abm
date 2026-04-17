"""
experiment_unified.py — Единый эксперимент для H1
===================================================

Три грида:
  1. Speed advantage:   speed_multiplier × hft_frac  (info_lag=0)
  2. Information delay:  info_lag × hft_frac          (speed_multiplier=1)
  3. Combined:           speed_multiplier × info_lag × hft_frac

Статистика:
  - Mann-Whitney U test: попарное сравнение φ=0 vs каждого φ
  - Bootstrap 95% CI на графиках
  - Sensitivity analysis: tipping point при порогах 1.1–1.5

Использует модифицированные agents.py и simulator.py с:
  - speed_multiplier в simulate()
  - delayed_spread() / delayed_price() / record_state() в ExchangeAgent
  - info_lag в Trader / Fundamentalist / Chartist
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import random
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from math import exp
from tqdm import tqdm
from scipy.stats import mannwhitneyu
import signal

from AgentBasedModel.agents import (
    ExchangeAgent, Fundamentalist, Chartist, MarketMaker, Random
)
from AgentBasedModel.simulator import Simulator, SimulatorInfo
from AgentBasedModel.events import MarketPriceShock
from AgentBasedModel.utils.math import mean, std


# ══════════════════════════════════════════════════════════════════════════════
# Классы агентов (из v9, без изменений)
# ══════════════════════════════════════════════════════════════════════════════

class TrendChartist(Chartist):
    """
    Трендовый чартист — исправленные знаки в exp() для trend-following.
    """
    def change_sentiment(self, info, a1=1, a2=1, v1=0.1):
        n_traders   = len(info.traders)
        n_chartists = sum(v == 'Chartist' for v in info.types[-1].values())
        if n_chartists == 0:
            return

        n_optimistic = sum(v == 'Optimistic' for v in info.sentiments[-1].values())
        n_pessimists = sum(v == 'Pessimistic' for v in info.sentiments[-1].values())

        dp = info.prices[-1] - info.prices[-2] if len(info.prices) > 1 else 0
        try:
            p  = self.market.price()
        except Exception:
            return
        x  = (n_optimistic - n_pessimists) / max(n_chartists, 1)

        U = a1 * x + a2 / v1 * dp / p
        U = max(-50, min(50, U))  # clamp to prevent overflow

        if self.sentiment == 'Optimistic':
            prob = v1 * n_chartists / n_traders * exp(-U)
            if prob > random.random():
                self.sentiment = 'Pessimistic'
        elif self.sentiment == 'Pessimistic':
            prob = v1 * n_chartists / n_traders * exp(U)
            if prob > random.random():
                self.sentiment = 'Optimistic'


class SlowTrendChartist(TrendChartist):
    """
    Трендовый чартист с задержкой ценового сигнала.
    """
    def __init__(self, market, cash, assets=0, lag=3, info_lag=0):
        super().__init__(market, cash, assets, info_lag=info_lag)
        self.lag = lag

    def change_sentiment(self, info, a1=1, a2=1, v1=0.1):
        n_traders   = len(info.traders)
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
        U = max(-50, min(50, U))  # clamp to prevent overflow

        if self.sentiment == 'Optimistic':
            prob = v1 * n_chartists / n_traders * exp(-U)
            if prob > random.random():
                self.sentiment = 'Pessimistic'
        elif self.sentiment == 'Pessimistic':
            prob = v1 * n_chartists / n_traders * exp(U)
            if prob > random.random():
                self.sentiment = 'Optimistic'


# ══════════════════════════════════════════════════════════════════════════════
# Симулятор (на базе SimulatorV9 + speed_multiplier + record_state)
# ══════════════════════════════════════════════════════════════════════════════

class SimulatorUnified:
    """
    Unified simulator with:
    - isinstance(t, Chartist) for TrendChartist/SlowTrendChartist dispatch
    - speed_multiplier: fast agents trade N times per iteration
    - exchange.record_state() for delayed information
    """

    def __init__(self, exchange, traders, events=None):
        self.exchange = exchange
        self.traders  = traders
        self.events   = [e.link(self) for e in events] if events else None
        self.info     = SimulatorInfo(exchange, traders)

    def _payments(self):
        for t in self.traders:
            t.cash += t.assets * self.exchange.dividend()
            t.cash += t.cash   * self.exchange.risk_free

    def simulate(self, n_iter, silent=False, speed_multiplier=1):
        for it in tqdm(range(n_iter), desc='Simulation', disable=silent):

            # 1. Events
            if self.events:
                for e in self.events:
                    e.call(it)

            # 2. Record order book state for delayed info
            self.exchange.record_state()

            # 3. Capture state
            self.info.capture()

            # 4. Update sentiments (Python dispatch → correct change_sentiment)
            for t in self.traders:
                if isinstance(t, Chartist) and type(t).__name__ != 'Universalist':
                    t.change_sentiment(self.info)

            # 5. Trading: fast first, speed_multiplier times
            fast = [t for t in self.traders if getattr(t, 'speed', 'slow') == 'fast']
            slow = [t for t in self.traders if getattr(t, 'speed', 'slow') != 'fast']

            for _ in range(speed_multiplier):
                random.shuffle(fast)
                for t in fast:
                    t.call()

            random.shuffle(slow)
            for t in slow:
                t.call()

            # 6. Payments and dividends
            self._payments()
            self.exchange.generate_dividend()

        return self


# ══════════════════════════════════════════════════════════════════════════════
# Метрики (из v9)
# ══════════════════════════════════════════════════════════════════════════════

def vol_ratio(info, shock_it=200, window=10):
    vols = info.price_volatility(window=window)
    pre  = vols[:shock_it - window]
    post = vols[shock_it:]
    if not pre or not post:
        return 1.0
    return mean(post) / (mean(pre) + 1e-9)


def spread_ratio(info, shock_it=200):
    def rel_spread(spreads, prices):
        vals = [(s['ask'] - s['bid']) / p
                for s, p in zip(spreads, prices) if s and p]
        return mean(vals) if vals else 1e-9
    pre  = rel_spread(info.spreads[:shock_it], info.prices[:shock_it])
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


# ══════════════════════════════════════════════════════════════════════════════
# Создание популяции
# ══════════════════════════════════════════════════════════════════════════════

def create_population(exchange, n_chartists=10, n_fundamentalists=10,
                      n_random=5, n_mm=1, hft_frac=0.3, info_lag=0,
                      softlimit=100):
    """
    Create agent population.

    :param hft_frac: share of chartists that are fast TrendChartists
    :param info_lag: information delay for slow agents (iterations)
    """
    traders = []

    n_fast = round(hft_frac * n_chartists)
    n_slow = n_chartists - n_fast

    # Fast chartists: TrendChartist, no info delay, speed='fast'
    for _ in range(n_fast):
        t = TrendChartist(exchange, cash=10**3, info_lag=0)
        t.speed = 'fast'
        traders.append(t)

    # Slow chartists: SlowTrendChartist, with sentiment lag AND info_lag
    for _ in range(n_slow):
        t = SlowTrendChartist(exchange, cash=10**3, lag=info_lag, info_lag=info_lag)
        t.speed = 'slow'
        traders.append(t)

    # Fundamentalists: slow, with info_lag
    for _ in range(n_fundamentalists):
        t = Fundamentalist(exchange, cash=10**3, access=1, info_lag=info_lag)
        t.speed = 'slow'
        traders.append(t)

    # Random agents: no info delay (background noise)
    for _ in range(n_random):
        t = Random(exchange, cash=10**3, info_lag=0)
        t.speed = 'slow'
        traders.append(t)

    # MarketMaker: no info delay
    for _ in range(n_mm):
        mm = MarketMaker(exchange, cash=10**3, softlimit=softlimit)
        mm.speed = 'slow'
        traders.append(mm)

    return traders


# ══════════════════════════════════════════════════════════════════════════════
# Один прогон
# ══════════════════════════════════════════════════════════════════════════════

def run_one(hft_frac, info_lag=0, speed_multiplier=1,
            n_iter=500, shock_it=200, shock_dp=-10,
            softlimit=100, seed=None):
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)

    exchange = ExchangeAgent(price=100, std=25, volume=1000, rf=5e-4)

    traders = create_population(
        exchange,
        n_chartists=10, n_fundamentalists=10,
        n_random=5, n_mm=1,
        hft_frac=hft_frac, info_lag=info_lag,
        softlimit=softlimit
    )

    sim = SimulatorUnified(
        exchange=exchange,
        traders=traders,
        events=[MarketPriceShock(shock_it, shock_dp)]
    )
    sim.simulate(n_iter, silent=True, speed_multiplier=speed_multiplier)
    info = sim.info

    return {
        'hft_frac':       hft_frac,
        'info_lag':       info_lag,
        'speed_mult':     speed_multiplier,
        'vol_ratio':      vol_ratio(info, shock_it),
        'spread_ratio':   spread_ratio(info, shock_it),
        'max_drawdown':   max_drawdown(info, shock_it),
        'recovery_time':  recovery_time(info, shock_it),
        'mm_panic_ratio': info.mm_panic_ratio(from_it=shock_it),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Три грида
# ══════════════════════════════════════════════════════════════════════════════

def run_grid_speed(n_runs=30, n_iter=500, shock_it=200, shock_dp=-10, softlimit=100):
    """Grid 1: speed_multiplier × hft_frac (info_lag=0)."""
    records = []
    speed_mults = [1, 2, 3, 5]
    hft_fracs = [round(x * 0.1, 1) for x in range(11)]

    total = len(speed_mults) * len(hft_fracs) * n_runs
    print(f'Grid 1 (speed): {len(speed_mults)} × {len(hft_fracs)} × {n_runs} = {total} runs')

    for sm in speed_mults:
        for fs in tqdm(hft_fracs, desc=f'speed_mult={sm}'):
            for run in range(n_runs):
                seed = run * 10000 + int(fs * 10) * 100 + sm
                r = run_one(fs, info_lag=0, speed_multiplier=sm,
                            n_iter=n_iter, shock_it=shock_it,
                            shock_dp=shock_dp, softlimit=softlimit, seed=seed)
                r['run'] = run
                r['grid'] = 'speed'
                records.append(r)
    return pd.DataFrame(records)


def run_grid_delay(n_runs=30, n_iter=500, shock_it=200, shock_dp=-10, softlimit=100):
    """Grid 2: info_lag × hft_frac (speed_multiplier=1)."""
    records = []
    info_lags = [0, 1, 3, 5, 10]
    hft_fracs = [round(x * 0.1, 1) for x in range(11)]

    total = len(info_lags) * len(hft_fracs) * n_runs
    print(f'Grid 2 (delay): {len(info_lags)} × {len(hft_fracs)} × {n_runs} = {total} runs')

    for lag in info_lags:
        for fs in tqdm(hft_fracs, desc=f'info_lag={lag}'):
            for run in range(n_runs):
                seed = run * 10000 + int(fs * 10) * 100 + lag + 50
                r = run_one(fs, info_lag=lag, speed_multiplier=1,
                            n_iter=n_iter, shock_it=shock_it,
                            shock_dp=shock_dp, softlimit=softlimit, seed=seed)
                r['run'] = run
                r['grid'] = 'delay'
                records.append(r)
    return pd.DataFrame(records)


def _timeout_handler(signum, frame):
    raise TimeoutError("Simulation took too long")


def run_grid_combined(n_runs=30, n_iter=500, shock_it=200, shock_dp=-10, softlimit=100):
    """Grid 3: speed_multiplier × info_lag × hft_frac (reduced to avoid OrderList hanging)."""
    records = []
    speed_mults = [2, 3]
    info_lags = [1, 3, 5]
    hft_fracs = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    TIMEOUT_SEC = 30  # max seconds per single simulation

    total = len(speed_mults) * len(info_lags) * len(hft_fracs) * n_runs
    print(f'Grid 3 (combined): {len(speed_mults)} × {len(info_lags)} × {len(hft_fracs)} × {n_runs} = {total} runs')

    for sm in speed_mults:
        for lag in info_lags:
            for fs in tqdm(hft_fracs, desc=f'sm={sm},lag={lag}'):
                for run in range(n_runs):
                    seed = run * 10000 + int(fs * 10) * 100 + lag * 10 + sm
                    try:
                        # Set timeout to catch infinite loops in OrderList
                        signal.signal(signal.SIGALRM, _timeout_handler)
                        signal.alarm(TIMEOUT_SEC)
                        r = run_one(fs, info_lag=lag, speed_multiplier=sm,
                                    n_iter=n_iter, shock_it=shock_it,
                                    shock_dp=shock_dp, softlimit=softlimit, seed=seed)
                        signal.alarm(0)  # cancel alarm
                    except (Exception, TimeoutError) as e:
                        signal.alarm(0)
                        print(f'\n  SKIP sm={sm} lag={lag} fs={fs} run={run}: {e}')
                        continue
                    r['run'] = run
                    r['grid'] = 'combined'
                    records.append(r)
    return pd.DataFrame(records)


# ══════════════════════════════════════════════════════════════════════════════
# Агрегация
# ══════════════════════════════════════════════════════════════════════════════

def aggregate(df, group_cols=None):
    if group_cols is None:
        group_cols = ['grid', 'speed_mult', 'info_lag', 'hft_frac']
    return df.groupby(group_cols).agg(
        vol_ratio_mean    = ('vol_ratio',      'mean'),
        vol_ratio_std     = ('vol_ratio',      'std'),
        spread_ratio_mean = ('spread_ratio',   'mean'),
        spread_ratio_std  = ('spread_ratio',   'std'),
        drawdown_mean     = ('max_drawdown',   'mean'),
        drawdown_std      = ('max_drawdown',   'std'),
        recovery_mean     = ('recovery_time',  'mean'),
        recovery_std      = ('recovery_time',  'std'),
        mm_panic_mean     = ('mm_panic_ratio', 'mean'),
        mm_panic_std      = ('mm_panic_ratio', 'std'),
        n_runs            = ('vol_ratio',      'count'),
    ).reset_index()


def find_tipping_point(agg, condition_col, condition_val, metric_col, multiplier=1.3):
    """
    Find first hft_frac where metric exceeds baseline * multiplier.

    :param condition_col: column to filter by (e.g. 'speed_mult' or 'info_lag')
    :param condition_val: value to filter for
    """
    sub = agg[agg[condition_col] == condition_val].sort_values('hft_frac')
    baseline = sub.loc[sub['hft_frac'] == 0.0, metric_col].values
    if len(baseline) == 0:
        return None
    baseline = baseline[0]
    for _, row in sub.iterrows():
        if row['hft_frac'] == 0.0:
            continue
        if row[metric_col] >= baseline * multiplier:
            return row['hft_frac']
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Статистические тесты
# ══════════════════════════════════════════════════════════════════════════════

def mann_whitney_tests(df, condition_col, condition_val, metric='vol_ratio'):
    """
    Run Mann-Whitney U test comparing baseline (hft_frac=0) vs each other hft_frac.

    Returns DataFrame with columns: hft_frac, baseline_mean, treatment_mean, U_stat, p_value, significant
    """
    sub = df[df[condition_col] == condition_val]
    baseline = sub[sub['hft_frac'] == 0.0][metric].values
    hft_fracs = sorted(sub['hft_frac'].unique())

    results = []
    for fs in hft_fracs:
        if fs == 0.0:
            continue
        treatment = sub[sub['hft_frac'] == fs][metric].values
        if len(baseline) < 3 or len(treatment) < 3:
            continue
        stat, p = mannwhitneyu(baseline, treatment, alternative='less')
        results.append({
            'hft_frac':       fs,
            'baseline_mean':  np.mean(baseline),
            'treatment_mean': np.mean(treatment),
            'U_stat':         stat,
            'p_value':        p,
            'significant':    p < 0.05,
        })
    return pd.DataFrame(results)


def bootstrap_ci(data, n_bootstrap=1000, ci=0.95, seed=42):
    """Compute bootstrap confidence interval for the mean."""
    rng = np.random.RandomState(seed)
    means = []
    for _ in range(n_bootstrap):
        sample = rng.choice(data, size=len(data), replace=True)
        means.append(np.mean(sample))
    alpha = (1 - ci) / 2
    return np.percentile(means, [alpha * 100, (1 - alpha) * 100])


def sensitivity_analysis(agg, condition_col, condition_val, metric_col='vol_ratio_mean',
                          multipliers=None):
    """
    Compute tipping point at different threshold multipliers.
    Returns dict {multiplier: tipping_point_or_None}.
    """
    if multipliers is None:
        multipliers = [1.1, 1.2, 1.3, 1.4, 1.5]

    sub = agg[agg[condition_col] == condition_val].sort_values('hft_frac')
    baseline = sub.loc[sub['hft_frac'] == 0.0, metric_col].values
    if len(baseline) == 0:
        return {m: None for m in multipliers}
    baseline = baseline[0]

    results = {}
    for mult in multipliers:
        threshold = baseline * mult
        tp = None
        for _, row in sub.iterrows():
            if row['hft_frac'] == 0.0:
                continue
            if row[metric_col] >= threshold:
                tp = row['hft_frac']
                break
        results[mult] = tp
    return results


# ══════════════════════════════════════════════════════════════════════════════
# Графики
# ══════════════════════════════════════════════════════════════════════════════

def plot_grid_speed(df_raw, agg, save='unified_speed.png'):
    """Plot Grid 1: speed_multiplier effect."""
    speed_mults = sorted(agg[agg['grid'] == 'speed']['speed_mult'].unique())
    colors = plt.cm.viridis(np.linspace(0.15, 0.85, len(speed_mults)))

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    metrics = [
        ('vol_ratio_mean',    'Volatility ratio (after/before)'),
        ('spread_ratio_mean', 'Spread ratio (after/before)'),
        ('drawdown_mean',     'Max drawdown'),
        ('recovery_mean',     'Recovery time (iterations)'),
        ('mm_panic_mean',     'MarketMaker panic ratio'),
    ]
    raw_metric_map = {
        'vol_ratio_mean': 'vol_ratio',
        'spread_ratio_mean': 'spread_ratio',
        'drawdown_mean': 'max_drawdown',
        'recovery_mean': 'recovery_time',
        'mm_panic_mean': 'mm_panic_ratio',
    }

    sub_agg = agg[agg['grid'] == 'speed']

    for idx, (col, title) in enumerate(metrics):
        ax = axes[idx // 3, idx % 3]
        for sm, color in zip(speed_mults, colors):
            data = sub_agg[(sub_agg['speed_mult'] == sm) & (sub_agg['info_lag'] == 0)]
            n = data['n_runs'].iloc[0] if len(data) > 0 else 30

            # Bootstrap CI
            ci_lo, ci_hi = [], []
            for fs in data['hft_frac']:
                raw_vals = df_raw[
                    (df_raw['grid'] == 'speed') &
                    (df_raw['speed_mult'] == sm) &
                    (df_raw['hft_frac'] == fs)
                ][raw_metric_map[col]].values
                if len(raw_vals) > 1:
                    lo, hi = bootstrap_ci(raw_vals)
                    ci_lo.append(lo)
                    ci_hi.append(hi)
                else:
                    ci_lo.append(data.loc[data['hft_frac'] == fs, col].values[0])
                    ci_hi.append(data.loc[data['hft_frac'] == fs, col].values[0])

            label = f'speed×{sm}' + (' (baseline)' if sm == 1 else '')
            ax.plot(data['hft_frac'], data[col], 'o-', color=color, lw=2, label=label)
            ax.fill_between(data['hft_frac'], ci_lo, ci_hi, alpha=0.15, color=color)

        ax.set(title=title, xlabel='HFT fraction (φ)', ylabel=col.replace('_mean', ''))
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)

    # Sensitivity analysis in last panel
    ax = axes[1, 2]
    ax.axis('off')
    sens_data = []
    for sm in speed_mults:
        sub = sub_agg[(sub_agg['speed_mult'] == sm) & (sub_agg['info_lag'] == 0)]
        sens = sensitivity_analysis(sub, 'speed_mult', sm)
        row = [f'speed×{sm}']
        for mult in [1.1, 1.2, 1.3, 1.4, 1.5]:
            tp = sens.get(mult)
            row.append(f'{tp:.1f}' if tp is not None else '—')
        sens_data.append(row)

    t = ax.table(
        cellText=sens_data,
        colLabels=['Condition', '1.1×', '1.2×', '1.3×', '1.4×', '1.5×'],
        cellLoc='center', loc='center'
    )
    t.auto_set_font_size(True)
    ax.set_title('Sensitivity: tipping point at different thresholds', fontsize=9)

    plt.suptitle(
        'Grid 1: Speed Advantage Effect\n'
        'info_lag=0 | 10 Fund + 10 TrendChartists + 5 Random + 1 MM | 30 runs\n'
        'Shading = 95% bootstrap CI',
        fontsize=12, fontweight='bold'
    )
    plt.tight_layout()
    plt.savefig(save, dpi=150, bbox_inches='tight')
    print(f'Saved: {save}')
    plt.close()


def plot_grid_delay(df_raw, agg, save='unified_delay.png'):
    """Plot Grid 2: info_lag effect."""
    info_lags = sorted(agg[agg['grid'] == 'delay']['info_lag'].unique())
    colors = plt.cm.plasma(np.linspace(0.15, 0.85, len(info_lags)))

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    metrics = [
        ('vol_ratio_mean',    'Volatility ratio (after/before)'),
        ('spread_ratio_mean', 'Spread ratio (after/before)'),
        ('drawdown_mean',     'Max drawdown'),
        ('recovery_mean',     'Recovery time (iterations)'),
        ('mm_panic_mean',     'MarketMaker panic ratio'),
    ]
    raw_metric_map = {
        'vol_ratio_mean': 'vol_ratio',
        'spread_ratio_mean': 'spread_ratio',
        'drawdown_mean': 'max_drawdown',
        'recovery_mean': 'recovery_time',
        'mm_panic_mean': 'mm_panic_ratio',
    }

    sub_agg = agg[agg['grid'] == 'delay']

    for idx, (col, title) in enumerate(metrics):
        ax = axes[idx // 3, idx % 3]
        for lag, color in zip(info_lags, colors):
            data = sub_agg[(sub_agg['info_lag'] == lag) & (sub_agg['speed_mult'] == 1)]

            ci_lo, ci_hi = [], []
            for fs in data['hft_frac']:
                raw_vals = df_raw[
                    (df_raw['grid'] == 'delay') &
                    (df_raw['info_lag'] == lag) &
                    (df_raw['hft_frac'] == fs)
                ][raw_metric_map[col]].values
                if len(raw_vals) > 1:
                    lo, hi = bootstrap_ci(raw_vals)
                    ci_lo.append(lo)
                    ci_hi.append(hi)
                else:
                    ci_lo.append(data.loc[data['hft_frac'] == fs, col].values[0])
                    ci_hi.append(data.loc[data['hft_frac'] == fs, col].values[0])

            label = f'lag={lag}' + (' (no delay)' if lag == 0 else '')
            ax.plot(data['hft_frac'], data[col], 'o-', color=color, lw=2, label=label)
            ax.fill_between(data['hft_frac'], ci_lo, ci_hi, alpha=0.15, color=color)

        ax.set(title=title, xlabel='HFT fraction (φ)', ylabel=col.replace('_mean', ''))
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)

    # Heatmap
    ax = axes[1, 2]
    pivot = sub_agg.pivot(index='info_lag', columns='hft_frac', values='vol_ratio_mean')
    im = ax.imshow(pivot.values, aspect='auto', origin='lower',
                   cmap='RdYlGn_r',
                   extent=[-0.05, 1.05, pivot.index.min() - 0.5, pivot.index.max() + 0.5])
    ax.set_yticks(pivot.index)
    ax.set(title='Heatmap: vol_ratio\n(darker = higher)',
           xlabel='hft_frac', ylabel='info_lag')
    plt.colorbar(im, ax=ax, fraction=0.04)

    plt.suptitle(
        'Grid 2: Information Delay Effect\n'
        'speed_mult=1 | 10 Fund + 10 TrendChartists + 5 Random + 1 MM | 30 runs\n'
        'Shading = 95% bootstrap CI',
        fontsize=12, fontweight='bold'
    )
    plt.tight_layout()
    plt.savefig(save, dpi=150, bbox_inches='tight')
    print(f'Saved: {save}')
    plt.close()


def plot_stat_tests(df_raw, save='unified_stats.png'):
    """Plot Mann-Whitney results and sensitivity analysis."""
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    # Panel 1: Mann-Whitney p-values for Grid 1 (speed), speed_mult=1, lag=0
    ax = axes[0]
    sub = df_raw[(df_raw['grid'] == 'speed') & (df_raw['speed_mult'] == 1) & (df_raw['info_lag'] == 0)]
    if len(sub) > 0:
        mw = mann_whitney_tests(sub, 'speed_mult', 1)
        if len(mw) > 0:
            bars = ax.bar(mw['hft_frac'], -np.log10(mw['p_value']),
                          color=['green' if s else 'gray' for s in mw['significant']],
                          width=0.08)
            ax.axhline(-np.log10(0.05), color='red', ls='--', lw=1, label='p=0.05')
            ax.set(title='Mann-Whitney U test\n(speed baseline, speed_mult=1)',
                   xlabel='HFT fraction (φ)',
                   ylabel='-log10(p-value)')
            ax.legend()
    ax.grid(alpha=0.3)

    # Panel 2: Mann-Whitney for different speed_multipliers
    ax = axes[1]
    for sm in [1, 2, 3, 5]:
        sub = df_raw[(df_raw['grid'] == 'speed') & (df_raw['speed_mult'] == sm)]
        if len(sub) == 0:
            continue
        mw = mann_whitney_tests(sub, 'speed_mult', sm)
        if len(mw) > 0:
            ax.plot(mw['hft_frac'], mw['p_value'], 'o-', label=f'speed×{sm}')
    ax.axhline(0.05, color='red', ls='--', lw=1, label='p=0.05')
    ax.set(title='Mann-Whitney p-values\n(all speed multipliers)',
           xlabel='HFT fraction (φ)', ylabel='p-value')
    ax.set_yscale('log')
    ax.legend(fontsize=7)
    ax.grid(alpha=0.3)

    # Panel 3: Sensitivity analysis table
    ax = axes[2]
    ax.axis('off')
    agg = aggregate(df_raw[df_raw['grid'] == 'speed'],
                    group_cols=['grid', 'speed_mult', 'info_lag', 'hft_frac'])
    sens_data = []
    for sm in [1, 2, 3, 5]:
        sub = agg[(agg['speed_mult'] == sm) & (agg['info_lag'] == 0)]
        sens = sensitivity_analysis(sub, 'speed_mult', sm)
        row = [f'speed×{sm}']
        for mult in [1.1, 1.2, 1.3, 1.4, 1.5]:
            tp = sens.get(mult)
            row.append(f'{tp:.1f}' if tp is not None else '—')
        sens_data.append(row)

    t = ax.table(
        cellText=sens_data,
        colLabels=['Condition', '1.1×', '1.2×', '1.3×', '1.4×', '1.5×'],
        cellLoc='center', loc='center'
    )
    t.auto_set_font_size(True)
    ax.set_title('Tipping point sensitivity', fontsize=10)

    plt.suptitle('Statistical Validation', fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(save, dpi=150, bbox_inches='tight')
    print(f'Saved: {save}')
    plt.close()


# ══════════════════════════════════════════════════════════════════════════════
# Сводка
# ══════════════════════════════════════════════════════════════════════════════

def print_summary(df_raw, agg):
    """Print summary to stdout."""
    print('\n' + '=' * 70)
    print('UNIFIED EXPERIMENT RESULTS')
    print('=' * 70)

    # Grid 1: Speed
    print('\n── Grid 1: Speed Advantage (info_lag=0) ──')
    sub = agg[agg['grid'] == 'speed']
    for sm in sorted(sub['speed_mult'].unique()):
        ss = sub[sub['speed_mult'] == sm]
        baseline = ss.loc[ss['hft_frac'] == 0.0, 'vol_ratio_mean'].values
        if len(baseline) == 0:
            continue
        baseline = baseline[0]
        max_val = ss['vol_ratio_mean'].max()
        sens = sensitivity_analysis(ss, 'speed_mult', sm)
        tp13 = sens.get(1.3)
        print(f'  speed×{sm}: baseline={baseline:.3f}  max={max_val:.3f}  '
              f'tipping(1.3×)={tp13 if tp13 else "—"}')

    # Grid 2: Delay
    print('\n── Grid 2: Information Delay (speed_mult=1) ──')
    sub = agg[agg['grid'] == 'delay']
    for lag in sorted(sub['info_lag'].unique()):
        ss = sub[sub['info_lag'] == lag]
        baseline = ss.loc[ss['hft_frac'] == 0.0, 'vol_ratio_mean'].values
        if len(baseline) == 0:
            continue
        baseline = baseline[0]
        max_val = ss['vol_ratio_mean'].max()
        print(f'  lag={lag:2d}: baseline={baseline:.3f}  max={max_val:.3f}')

    # Mann-Whitney for key comparison
    print('\n── Mann-Whitney U tests (speed grid, speed_mult=1, lag=0) ──')
    sub_raw = df_raw[(df_raw['grid'] == 'speed') & (df_raw['speed_mult'] == 1)]
    if len(sub_raw) > 0:
        mw = mann_whitney_tests(sub_raw, 'speed_mult', 1)
        if len(mw) > 0:
            for _, row in mw.iterrows():
                sig = '***' if row['p_value'] < 0.001 else '**' if row['p_value'] < 0.01 else '*' if row['p_value'] < 0.05 else 'n.s.'
                print(f"  φ=0 vs φ={row['hft_frac']:.1f}: "
                      f"mean {row['baseline_mean']:.3f} vs {row['treatment_mean']:.3f}  "
                      f"U={row['U_stat']:.0f}  p={row['p_value']:.4f} {sig}")


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    SHOCK_DP  = -10
    N_RUNS    = 30
    N_ITER    = 500
    SHOCK_IT  = 200
    SOFTLIMIT = 100

    print('=' * 70)
    print('UNIFIED EXPERIMENT: Speed + Delay + Combined')
    print('=' * 70)

    # Grid 1: Load existing results
    if os.path.exists('unified_speed_raw.csv'):
        print('\n[1/4] Grid 1: Loading from unified_speed_raw.csv...')
        df_speed = pd.read_csv('unified_speed_raw.csv')
        print(f'  Loaded {len(df_speed)} rows')
    else:
        print('\n[1/4] Grid 1: Speed advantage...')
        df_speed = run_grid_speed(N_RUNS, N_ITER, SHOCK_IT, SHOCK_DP, SOFTLIMIT)
        df_speed.to_csv('unified_speed_raw.csv', index=False)
        print('Saved: unified_speed_raw.csv')

    # Grid 2: Load existing results
    if os.path.exists('unified_delay_raw.csv'):
        print('\n[2/4] Grid 2: Loading from unified_delay_raw.csv...')
        df_delay = pd.read_csv('unified_delay_raw.csv')
        print(f'  Loaded {len(df_delay)} rows')
    else:
        print('\n[2/4] Grid 2: Information delay...')
        df_delay = run_grid_delay(N_RUNS, N_ITER, SHOCK_IT, SHOCK_DP, SOFTLIMIT)
        df_delay.to_csv('unified_delay_raw.csv', index=False)
        print('Saved: unified_delay_raw.csv')

    # Grid 3: Run (or load if exists)
    if os.path.exists('unified_combined_raw.csv'):
        print('\n[3/4] Grid 3: Loading from unified_combined_raw.csv...')
        df_combined = pd.read_csv('unified_combined_raw.csv')
        print(f'  Loaded {len(df_combined)} rows')
    else:
        print('\n[3/4] Grid 3: Combined...')
        df_combined = run_grid_combined(N_RUNS, N_ITER, SHOCK_IT, SHOCK_DP, SOFTLIMIT)
        df_combined.to_csv('unified_combined_raw.csv', index=False)
        print('Saved: unified_combined_raw.csv')

    # Merge and analyze
    df_all = pd.concat([df_speed, df_delay, df_combined], ignore_index=True)
    df_all.to_csv('unified_all_raw.csv', index=False)
    print('Saved: unified_all_raw.csv')

    agg = aggregate(df_all)
    print_summary(df_all, agg)

    # Plots
    print('\n[4/4] Generating plots...')
    plot_grid_speed(df_all, agg)
    plot_grid_delay(df_all, agg)
    plot_stat_tests(df_all)

    print('\nDone!')
