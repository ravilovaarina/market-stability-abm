"""
Experiment H1 v6: варьируем softlimit MarketMaker
==================================================
Идея: при softlimit=100 MM поглощает почти любой шок без паники.
При меньшем softlimit MM быстрее уходит в панику — и эффект
fast_share должен стать виднее.

Эксперимент: grid по fast_share × softlimit
softlimit ∈ {5, 10, 20, 50, 100}
fast_share ∈ {0.0, 0.1, ..., 1.0}
n_runs = 20, остальное как в v5 (access=1 у всех)
"""

import random
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from tqdm import tqdm

from AgentBasedModel import *
from AgentBasedModel.agents import ExchangeAgent, Fundamentalist, Chartist, MarketMaker
from AgentBasedModel.simulator import Simulator
from AgentBasedModel.events import MarketPriceShock
from AgentBasedModel.utils.math import mean, std


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

def run_one(fast_share, softlimit=100, n_iter=500, shock_it=200,
            shock_dp=-10, seed=None):
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
    sim.simulate(n_iter, silent=True, fast_extra_call=True)
    info = sim.info

    return {
        'fast_share':     fast_share,
        'softlimit':      softlimit,
        'vol_ratio':      vol_ratio(info, shock_it),
        'spread_ratio':   spread_ratio(info, shock_it),
        'max_drawdown':   max_drawdown(info, shock_it),
        'mm_panic_ratio': info.mm_panic_ratio(from_it=shock_it),
        'prices':         info.prices,
    }


# ── Полный грид ───────────────────────────────────────────────────────────────

def run_grid(fast_shares=None, softlimits=None, n_runs=20,
             n_iter=500, shock_it=200, shock_dp=-10):
    if fast_shares is None:
        fast_shares = [round(x * 0.1, 1) for x in range(11)]
    if softlimits is None:
        softlimits = [5, 10, 20, 50, 100]

    records = []
    total = len(softlimits) * len(fast_shares) * n_runs
    print(f'Всего симуляций: {total}')

    for sl in tqdm(softlimits, desc='softlimit'):
        for fs in fast_shares:
            for run in range(n_runs):
                res = run_one(fs, sl, n_iter, shock_it, shock_dp,
                              seed=run * 100 + int(fs * 10) + sl * 1000)
                records.append({
                    'fast_share':     fs,
                    'softlimit':      sl,
                    'run':            run,
                    'vol_ratio':      res['vol_ratio'],
                    'spread_ratio':   res['spread_ratio'],
                    'max_drawdown':   res['max_drawdown'],
                    'mm_panic_ratio': res['mm_panic_ratio'],
                })
    return pd.DataFrame(records)


def aggregate(df):
    return df.groupby(['softlimit', 'fast_share']).agg(
        vol_ratio_mean    = ('vol_ratio',      'mean'),
        vol_ratio_std     = ('vol_ratio',      'std'),
        spread_ratio_mean = ('spread_ratio',   'mean'),
        spread_ratio_std  = ('spread_ratio',   'std'),
        drawdown_mean     = ('max_drawdown',   'mean'),
        drawdown_std      = ('max_drawdown',   'std'),
        mm_panic_mean     = ('mm_panic_ratio', 'mean'),
        mm_panic_std      = ('mm_panic_ratio', 'std'),
    ).reset_index()


# ── Графики ───────────────────────────────────────────────────────────────────

def plot_results(agg, shock_dp, save='h1_v6_results.png'):
    softlimits = sorted(agg['softlimit'].unique())
    colors = ['#d62728', '#ff7f0e', '#2ca02c', '#1f77b4', '#9467bd']

    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    metrics = [
        ('vol_ratio_mean',    'Волатильность после/до шока',  1.0),
        ('spread_ratio_mean', 'Спред после/до шока',           1.0),
        ('drawdown_mean',     'Макс. просадка цены',           None),
        ('mm_panic_mean',     'Паника MarketMaker (после шока)', None),
    ]

    for ax, (col, title, baseline) in zip(axes.flatten(), metrics):
        for sl, color in zip(softlimits, colors):
            sub = agg[agg['softlimit'] == sl]
            ax.plot(sub['fast_share'], sub[col], 'o-',
                    color=color, lw=2, label=f'softlimit={sl}')
        if baseline is not None:
            ax.axhline(baseline, color='black', ls='--', lw=1, label='Базовый уровень')
        ax.set(title=title, xlabel='Доля быстрых агентов')
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)

    plt.suptitle(
        f'Гипотеза 1 v6: варьируем softlimit MarketMaker\n'
        f'10 Fund + 10 Chart + 1 MM | шок dp={shock_dp} | access=1 | 20 прогонов',
        fontsize=12, fontweight='bold'
    )
    plt.tight_layout()
    plt.savefig(save, dpi=150, bbox_inches='tight')
    print(f'Сохранено: {save}')


def plot_heatmap(agg, col, title, save='h1_v6_heatmap.png'):
    """Heatmap: ось X = fast_share, ось Y = softlimit, цвет = метрика."""
    pivot = agg.pivot(index='softlimit', columns='fast_share', values=col)

    fig, ax = plt.subplots(figsize=(12, 5))
    im = ax.imshow(pivot.values, aspect='auto', cmap='RdYlGn_r', origin='lower')
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([str(c) for c in pivot.columns])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([str(i) for i in pivot.index])
    ax.set_xlabel('fast_share')
    ax.set_ylabel('softlimit')
    ax.set_title(title)
    plt.colorbar(im, ax=ax)
    plt.tight_layout()
    plt.savefig(save, dpi=150, bbox_inches='tight')
    print(f'Сохранено: {save}')


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=' * 60)
    print('ГИПОТЕЗА 1 v6: варьируем softlimit MarketMaker')
    print('softlimit ∈ {5, 10, 20, 50, 100}')
    print('fast_share ∈ {0.0, ..., 1.0}, n_runs=20')
    print('=' * 60)

    SHOCK_DP = -10

    print(f'\n[1/2] Запуск грида...')
    df = run_grid(
        softlimits=[5, 10, 20, 50, 100],
        n_runs=20, n_iter=500, shock_it=200, shock_dp=SHOCK_DP
    )
    df.to_csv('h1_v6_raw.csv', index=False)

    agg = aggregate(df)

    # Вывод по каждому softlimit
    print('\nАгрегированные результаты (mm_panic_mean):')
    pivot_panic = agg.pivot(index='softlimit', columns='fast_share',
                            values='mm_panic_mean').round(3)
    print(pivot_panic.to_string())

    print('\nАгрегированные результаты (vol_ratio_mean):')
    pivot_vol = agg.pivot(index='softlimit', columns='fast_share',
                          values='vol_ratio_mean').round(3)
    print(pivot_vol.to_string())

    print('\n[2/2] Графики...')
    plot_results(agg, shock_dp=SHOCK_DP)
    plot_heatmap(agg, 'mm_panic_mean',
                 'Паника MarketMaker: fast_share × softlimit',
                 save='h1_v6_heatmap_panic.png')
    plot_heatmap(agg, 'vol_ratio_mean',
                 'Волатильность после/до шока: fast_share × softlimit',
                 save='h1_v6_heatmap_vol.png')
    print('\nГотово!')