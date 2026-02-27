"""
Experiment H1 v7: настоящий HFT-эффект через задержку цены
===========================================================
Используется simulator_hft.py — медленные агенты видят цену
с задержкой delayed_price_lag итераций назад.

Это реализует настоящую latency heterogeneity:
- Быстрые: видят актуальную цену, действуют первыми
- Медленные: видят устаревшую цену, действуют после

Grid: fast_share × delayed_price_lag
fast_share ∈ {0.0, ..., 1.0}
lag ∈ {1, 2, 3, 5, 10}
n_runs = 20
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Подменяем симулятор на HFT-версию
import simulator_hft
import AgentBasedModel.simulator
AgentBasedModel.simulator.Simulator = simulator_hft.Simulator
AgentBasedModel.simulator.SimulatorInfo = simulator_hft.SimulatorInfo

import random
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from tqdm import tqdm

from AgentBasedModel import *
from AgentBasedModel.agents import ExchangeAgent, Fundamentalist, Chartist, MarketMaker
from simulator_hft import Simulator
from AgentBasedModel.events import MarketPriceShock
from AgentBasedModel.utils.math import mean


# ── Метрики ───────────────────────────────────────────────────────────────────

def vol_ratio(info, shock_it=200, window=10):
    vols = info.price_volatility(window=window)
    pre  = vols[:shock_it - window]
    post = vols[shock_it:]
    if not pre or not post:
        return 1.0
    return mean(post) / (mean(pre) + 1e-9)


def spread_ratio(info, shock_it=200):
    def rel(spreads, prices):
        vals = [(s['ask'] - s['bid']) / p for s, p in zip(spreads, prices) if s and p]
        return mean(vals) if vals else 1e-9
    pre  = rel(info.spreads[:shock_it], info.prices[:shock_it])
    post = rel(info.spreads[shock_it:], info.prices[shock_it:])
    return post / (pre + 1e-9)


def max_drawdown(info, shock_it=200):
    pre_price = info.prices[shock_it - 1]
    post = info.prices[shock_it:]
    if not post:
        return 0.0
    return (pre_price - min(post)) / pre_price


# ── Один прогон ───────────────────────────────────────────────────────────────

def run_one(fast_share, lag=1, n_iter=500, shock_it=200,
            shock_dp=-10, softlimit=100, seed=None):
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)

    exchange = ExchangeAgent(price=100, std=25, volume=1000, rf=5e-4)
    all_traders = (
        [Fundamentalist(exchange, 10**3, access=1) for _ in range(10)] +
        [Chartist(exchange, 10**3) for _ in range(10)] +
        [MarketMaker(exchange, 10**3, softlimit=softlimit)]
    )

    non_mm = [t for t in all_traders if type(t) != MarketMaker]
    n_fast = int(round(fast_share * len(non_mm)))
    for i, t in enumerate(non_mm):
        t.speed = 'fast' if i < n_fast else 'slow'
    for t in all_traders:
        if type(t) == MarketMaker:
            t.speed = 'slow'

    sim = Simulator(exchange=exchange, traders=all_traders,
                    events=[MarketPriceShock(shock_it, shock_dp)])
    sim.simulate(n_iter, silent=True,
                 fast_extra_call=True,
                 delayed_price_lag=lag)
    info = sim.info

    return {
        'fast_share':     fast_share,
        'lag':            lag,
        'vol_ratio':      vol_ratio(info, shock_it),
        'spread_ratio':   spread_ratio(info, shock_it),
        'max_drawdown':   max_drawdown(info, shock_it),
        'mm_panic_ratio': info.mm_panic_ratio(from_it=shock_it),
        'prices':         info.prices,
    }


# ── Полный грид ───────────────────────────────────────────────────────────────

def run_grid(fast_shares=None, lags=None, n_runs=20,
             n_iter=500, shock_it=200, shock_dp=-10, softlimit=100):
    if fast_shares is None:
        fast_shares = [round(x * 0.1, 1) for x in range(11)]
    if lags is None:
        lags = [1, 2, 3, 5, 10]

    total = len(lags) * len(fast_shares) * n_runs
    print(f'Всего симуляций: {total}')

    records = []
    for lag in tqdm(lags, desc='lag grid'):
        for fs in fast_shares:
            for run in range(n_runs):
                res = run_one(fs, lag, n_iter, shock_it, shock_dp, softlimit,
                              seed=run * 100 + int(fs * 10) + lag * 1000)
                records.append({
                    'fast_share':     fs,
                    'lag':            lag,
                    'run':            run,
                    'vol_ratio':      res['vol_ratio'],
                    'spread_ratio':   res['spread_ratio'],
                    'max_drawdown':   res['max_drawdown'],
                    'mm_panic_ratio': res['mm_panic_ratio'],
                })
    return pd.DataFrame(records)


def aggregate(df):
    return df.groupby(['lag', 'fast_share']).agg(
        vol_ratio_mean    = ('vol_ratio',      'mean'),
        vol_ratio_std     = ('vol_ratio',      'std'),
        spread_ratio_mean = ('spread_ratio',   'mean'),
        spread_ratio_std  = ('spread_ratio',   'std'),
        drawdown_mean     = ('max_drawdown',   'mean'),
        drawdown_std      = ('max_drawdown',   'std'),
        mm_panic_mean     = ('mm_panic_ratio', 'mean'),
        mm_panic_std      = ('mm_panic_ratio', 'std'),
    ).reset_index()


def find_tipping_point(agg, lag, col, baseline_multiplier=1.3):
    sub = agg[agg['lag'] == lag].copy()
    baseline = sub.loc[sub['fast_share'] == 0.0, col].values
    if len(baseline) == 0:
        return None
    baseline = baseline[0]
    for _, row in sub.iterrows():
        if row['fast_share'] == 0.0:
            continue
        if row[col] >= baseline * baseline_multiplier:
            return row['fast_share']
    return None


# ── Графики ───────────────────────────────────────────────────────────────────

def plot_results(agg, shock_dp, save='h1_v7_results.png'):
    lags = sorted(agg['lag'].unique())
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']

    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    metrics = [
        ('vol_ratio_mean',    'Volatility after/before shock',    1.0),
        ('spread_ratio_mean', 'Spread after/before shock',             1.0),
        ('drawdown_mean',     'Max. price drawdown',             None),
        ('mm_panic_mean',     'MarketMaker panic (post-shock)', None),
    ]

    for ax, (col, title, baseline) in zip(axes.flatten(), metrics):
        for lag, color in zip(lags, colors):
            sub = agg[agg['lag'] == lag]
            ax.plot(sub['fast_share'], sub[col], 'o-',
                    color=color, lw=2, label=f'lag={lag}')
        if baseline is not None:
            ax.axhline(baseline, color='black', ls='--', lw=1,
                       label='Baseline')
        ax.set(title=title, xlabel='Fast agent share')
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)

    plt.suptitle(
        f'Hypothesis 1 v7: price delay for slow agents\n'
        f'10 Fund + 10 Chart + 1 MM | shock dp={shock_dp} | 20 runs',
        fontsize=12, fontweight='bold'
    )
    plt.tight_layout()
    plt.savefig(save, dpi=150, bbox_inches='tight')
    print(f'Сохранено: {save}')


def plot_heatmap(agg, col, title, save='h1_v7_heatmap.png'):
    pivot = agg.pivot(index='lag', columns='fast_share', values=col)
    fig, ax = plt.subplots(figsize=(13, 5))
    im = ax.imshow(pivot.values, aspect='auto', cmap='RdYlGn_r', origin='lower')
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([str(c) for c in pivot.columns])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([str(i) for i in pivot.index])
    ax.set_xlabel('fast_share')
    ax.set_ylabel('lag (iterations)')
    ax.set_title(title)
    plt.colorbar(im, ax=ax)
    plt.tight_layout()
    plt.savefig(save, dpi=150, bbox_inches='tight')
    print(f'Сохранено: {save}')


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=' * 60)
    print('ГИПОТЕЗА 1 v7: задержка цены для медленных агентов')
    print('lag ∈ {1, 2, 3, 5, 10} итераций')
    print('fast_share ∈ {0.0, ..., 1.0}, n_runs=20')
    print('=' * 60)

    SHOCK_DP = -10

    print(f'\n[1/2] Запуск грида...')
    df = run_grid(
        lags=[1, 2, 3, 5, 10],
        n_runs=20, n_iter=500, shock_it=200,
        shock_dp=SHOCK_DP, softlimit=100
    )
    df.to_csv('h1_v7_raw.csv', index=False)

    agg = aggregate(df)

    print('\nТipping points по lag (vol_ratio, порог 1.3x):')
    for lag in sorted(df['lag'].unique()):
        tp = find_tipping_point(agg, lag, 'vol_ratio_mean')
        print(f'  lag={lag}: {tp if tp is not None else "не обнаружен"}')

    print('\nvol_ratio_mean по lag × fast_share:')
    pivot = agg.pivot(index='lag', columns='fast_share',
                      values='vol_ratio_mean').round(3)
    print(pivot.to_string())

    print('\n[2/2] Графики...')
    plot_results(agg, shock_dp=SHOCK_DP)
    plot_heatmap(agg, 'vol_ratio_mean',
                 'Volatility after/before shock: fast_share × lag',
                 save='h1_v7_heatmap_vol.png')
    plot_heatmap(agg, 'mm_panic_mean',
                 'MM panic: fast_share × lag',
                 save='h1_v7_heatmap_panic.png')
    print('\nГотово!')
