"""
Experiment H1 v2: перебираем разные величины шока + разница в access
"""
import random
import os
import sys
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/1d-abm-mplconfig")
os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "results" / "h1" / "raw"
TABLE_DIR = PROJECT_ROOT / "results" / "h1" / "tables"
FIGURE_DIR = PROJECT_ROOT / "results" / "h1" / "figures"
RAW_DIR.mkdir(parents=True, exist_ok=True)
TABLE_DIR.mkdir(parents=True, exist_ok=True)
FIGURE_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib
matplotlib.use("Agg")
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from tqdm import tqdm

from AgentBasedModel import *
from AgentBasedModel.agents import ExchangeAgent, Fundamentalist, Chartist, MarketMaker
from AgentBasedModel.simulator import Simulator, SimulatorInfo
from AgentBasedModel.events import MarketPriceShock
from AgentBasedModel.states import general_states
from AgentBasedModel.utils.math import mean


def get_crisis_share(info, shock_it=200, size=10):
    states = general_states(info, size=size, window=5)
    post = states[shock_it // size:]
    if not post:
        return 0.0
    return sum(1 for s in post if s in ('panic', 'disaster')) / len(post)


def get_spread_ratio(info, shock_it=200):
    def rel(spreads, prices):
        vals = [(s['ask'] - s['bid']) / p for s, p in zip(spreads, prices) if s and p]
        return mean(vals) if vals else 1e-9
    before = rel(info.spreads[:shock_it], info.prices[:shock_it])
    after  = rel(info.spreads[shock_it:], info.prices[shock_it:])
    return after / (before + 1e-9)


def run_one(fast_share, n_iter=500, shock_it=200, shock_dp=-3,
            fast_extra_call=True, fast_access=5, slow_access=1, seed=None):
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)

    exchange = ExchangeAgent(price=100, std=25, volume=1000, rf=5e-4)
    all_traders = (
        [Fundamentalist(exchange, 10**3, access=slow_access) for _ in range(10)] +
        [Chartist(exchange, 10**3) for _ in range(10)] +
        [MarketMaker(exchange, 10**3, softlimit=100)]
    )
    non_mm = [t for t in all_traders if type(t) != MarketMaker]
    n_fast = int(round(fast_share * len(non_mm)))
    for i, t in enumerate(non_mm):
        t.speed = 'fast' if i < n_fast else 'slow'
        if i < n_fast and type(t) == Fundamentalist:
            t.access = fast_access  # быстрые видят больше дивидендов
    for t in all_traders:
        if type(t) == MarketMaker:
            t.speed = 'slow'

    sim = Simulator(exchange=exchange, traders=all_traders,
                    events=[MarketPriceShock(shock_it, shock_dp)])
    sim.simulate(n_iter, silent=True, fast_extra_call=fast_extra_call)
    info = sim.info

    return {
        'fast_share':     fast_share,
        'crisis_share':   get_crisis_share(info, shock_it),
        'mm_panic_ratio': info.mm_panic_ratio(from_it=shock_it),
        'spread_ratio':   get_spread_ratio(info, shock_it),
        'prices':         info.prices,
    }


def run_shock_sweep(shock_dps=None, fast_shares=None, n_runs=5, n_iter=500, shock_it=200):
    """Перебираем разные dp чтобы найти оптимальный шок для видимости tipping point."""
    if shock_dps is None:
        shock_dps = [-1, -2, -3, -5, -7, -10]
    if fast_shares is None:
        fast_shares = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    records = []
    for dp in tqdm(shock_dps, desc='shock sweep'):
        for fs in fast_shares:
            for run in range(n_runs):
                res = run_one(fs, n_iter, shock_it, shock_dp=dp,
                              fast_access=5, slow_access=1,
                              seed=run * 100 + int(fs * 10) + abs(int(dp)) * 1000)
                records.append({'shock_dp': dp, 'fast_share': fs, 'run': run,
                                'crisis_share': res['crisis_share'],
                                'mm_panic_ratio': res['mm_panic_ratio']})
    return pd.DataFrame(records)


def run_grid(fast_shares=None, n_runs=10, n_iter=500, shock_it=200, shock_dp=-3):
    if fast_shares is None:
        fast_shares = [round(x * 0.1, 1) for x in range(11)]
    records = []
    for fs in tqdm(fast_shares, desc=f'fast_share grid (dp={shock_dp})'):
        for run in range(n_runs):
            res = run_one(fs, n_iter, shock_it, shock_dp=shock_dp,
                          fast_access=5, slow_access=1,
                          seed=run * 100 + int(fs * 10))
            records.append({'fast_share': fs, 'run': run,
                            'crisis_share': res['crisis_share'],
                            'mm_panic_ratio': res['mm_panic_ratio'],
                            'spread_ratio': res['spread_ratio']})
    return pd.DataFrame(records)


def aggregate(df):
    return df.groupby('fast_share').agg(
        crisis_mean=('crisis_share', 'mean'), crisis_std=('crisis_share', 'std'),
        mm_panic_mean=('mm_panic_ratio', 'mean'), mm_panic_std=('mm_panic_ratio', 'std'),
        spread_mean=('spread_ratio', 'mean'), spread_std=('spread_ratio', 'std'),
    ).reset_index()


def find_tipping_point(agg, col='crisis_mean', threshold=0.3):
    for _, row in agg.iterrows():
        if row[col] >= threshold:
            return row['fast_share']
    return None


def plot_shock_sweep(df_sweep, save=None):
    if save is None:
        save = FIGURE_DIR / "h1_shock_sweep.png"
    """Heatmap: ось X = fast_share, ось Y = shock_dp, цвет = crisis_share."""
    pivot = df_sweep.groupby(['shock_dp', 'fast_share'])['crisis_share'].mean().unstack()
    fig, axes = plt.subplots(1, 2, figsize=(16, 5))

    # Heatmap crisis_share
    im = axes[0].imshow(pivot.values, aspect='auto', cmap='RdYlGn_r',
                        vmin=0, vmax=1, origin='lower')
    axes[0].set_xticks(range(len(pivot.columns)))
    axes[0].set_xticklabels([str(c) for c in pivot.columns])
    axes[0].set_yticks(range(len(pivot.index)))
    axes[0].set_yticklabels([str(i) for i in pivot.index])
    axes[0].set_xlabel('fast_share')
    axes[0].set_ylabel('shock_dp')
    axes[0].set_title('Crisis Share (red = crisis)')
    plt.colorbar(im, ax=axes[0])

    # Линии по dp
    for dp in df_sweep['shock_dp'].unique():
        sub = df_sweep[df_sweep['shock_dp'] == dp].groupby('fast_share')['crisis_share'].mean()
        axes[1].plot(sub.index, sub.values, 'o-', label=f'dp={dp}', linewidth=1.5)
    axes[1].axhline(0.3, color='black', ls='--', lw=1, label='Threshold 0.3')
    axes[1].set(title='Crisis Share by fast_share for different shocks',
                xlabel='fast_share', ylabel='crisis_share', ylim=(0, 1))
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.3)

    plt.suptitle('Search for optimal shock to detect Tipping Point', fontsize=12, fontweight='bold')
    plt.tight_layout()
    plt.savefig(save, dpi=150, bbox_inches='tight')
    print(f'Сохранено: {save}')

def plot_main(agg, df, shock_dp, save=None):
    if save is None:
        save = FIGURE_DIR / "h1_results_v2.png"
    fig = plt.figure(figsize=(16, 10))
    gs = gridspec.GridSpec(2, 2, hspace=0.4, wspace=0.35)
    tp = find_tipping_point(agg)
    x = agg['fast_share']

    def vline(ax):
        if tp is not None:
            ax.axvline(tp, color='orange', ls=':', lw=2, label=f'Tipping point ({tp})')

    ax = fig.add_subplot(gs[0, 0])
    ax.plot(x, agg['crisis_mean'], 'o-', color='crimson', lw=2)
    ax.fill_between(x, agg['crisis_mean']-agg['crisis_std'],
                       agg['crisis_mean']+agg['crisis_std'], alpha=0.2, color='crimson')
    ax.axhline(0.3, color='black', ls='--', lw=1, label='Crisis threshold (0.3)')
    vline(ax); ax.legend(fontsize=8); ax.grid(alpha=0.3)
    ax.set(title='Crisis state share (post-shock)',
           xlabel='Fast agent share', ylabel='Fraction of panic/disaster windows', ylim=(0, 1))

    ax = fig.add_subplot(gs[0, 1])
    ax.plot(x, agg['mm_panic_mean'], 's-', color='navy', lw=2)
    ax.fill_between(x, agg['mm_panic_mean']-agg['mm_panic_std'],
                       agg['mm_panic_mean']+agg['mm_panic_std'], alpha=0.2, color='navy')
    vline(ax); ax.legend(fontsize=8); ax.grid(alpha=0.3)
    ax.set(title='MarketMaker panic (post-shock)',
           xlabel='Fast agent share', ylabel='Fraction of panic iterations', ylim=(0, 1))

    ax = fig.add_subplot(gs[1, 0])
    ax.plot(x, agg['spread_mean'], '^-', color='darkgreen', lw=2)
    ax.fill_between(x, agg['spread_mean']-agg['spread_std'],
                       agg['spread_mean']+agg['spread_std'], alpha=0.2, color='darkgreen')
    ax.axhline(1.0, color='black', ls='--', lw=1, label='Baseline')
    vline(ax); ax.legend(fontsize=8); ax.grid(alpha=0.3)
    ax.set(title='Spread after / before shock',
           xlabel='Fast agent share', ylabel='Spread ratio')

    ax = fig.add_subplot(gs[1, 1])
    groups = [df[df['fast_share']==fs]['crisis_share'].values
              for fs in sorted(df['fast_share'].unique())]
    labels = [str(fs) for fs in sorted(df['fast_share'].unique())]
    ax.boxplot(groups, labels=labels, patch_artist=True,
               boxprops=dict(facecolor='lightyellow', color='black'),
               medianprops=dict(color='crimson', lw=2))
    ax.axhline(0.3, color='black', ls='--', lw=1, label='Crisis threshold')
    ax.legend(fontsize=8); ax.grid(alpha=0.3, axis='y')
    ax.set(title='Variance across runs (crisis_share)',
           xlabel='Fast agent share', ylabel='Crisis share')

    plt.suptitle(f'Hypothesis 1: Tipping Point | shock dp={shock_dp} | fast_access=5, slow_access=1',
                 fontsize=12, fontweight='bold')
    plt.savefig(save, dpi=150, bbox_inches='tight')
    print(f'Saved: {save}')


if __name__ == '__main__':
    print('=' * 60)
    print('ГИПОТЕЗА 1 v2: поиск tipping point с разными шоками')
    print('=' * 60)

    # Шаг 1: sweep по shock_dp — 6 значений × 6 fast_share × 5 прогонов = 180 симуляций
    print('\n[1/2] Sweep по величине шока (найдём оптимальный dp)...')
    df_sweep = run_shock_sweep(
        shock_dps=[-1, -2, -3, -5, -7, -10],
        fast_shares=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        n_runs=5, n_iter=500, shock_it=200
    )
    df_sweep.to_csv(TABLE_DIR / "h1_sweep.csv", index=False)
    plot_shock_sweep(df_sweep)

    # Выбираем лучший dp — тот где максимальный разброс crisis_share по fast_share
    best_dp = df_sweep.groupby('shock_dp').apply(
        lambda x: x.groupby('fast_share')['crisis_share'].mean().std()
    ).idxmax()
    print(f'\nОптимальный dp для видимости tipping point: {best_dp}')

    # Шаг 2: полный грид с лучшим dp
    print(f'\n[2/2] Полный грид с dp={best_dp} (11 × 10 = 110 симуляций)...')
    df = run_grid(n_runs=10, n_iter=500, shock_it=200, shock_dp=best_dp)
    df.to_csv(RAW_DIR / f'h1_raw_dp{best_dp}.csv', index=False)
    agg = aggregate(df)
    print(agg.to_string(index=False))

    tp = find_tipping_point(agg)
    if tp is not None:
        print(f'\n✓ Tipping point: fast_share = {tp}')
    else:
        print('\n✗ Tipping point не обнаружен')

    plot_main(agg, df, shock_dp=best_dp)
    print('\nГотово!')
