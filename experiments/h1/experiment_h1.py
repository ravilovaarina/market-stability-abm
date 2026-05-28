"""
Experiment H1: Tipping Point in Latency Heterogeneity
"""
import random
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_DIR = PROJECT_ROOT / "results" / "h1" / "legacy"
LEGACY_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(LEGACY_DIR)

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


def run_one(fast_share, n_iter=500, shock_it=200, fast_extra_call=True, seed=None):
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)

    exchange = ExchangeAgent(price=100, std=25, volume=1000, rf=5e-4)
    all_traders = (
        [Fundamentalist(exchange, 10**3, access=1) for _ in range(10)] +
        [Chartist(exchange, 10**3) for _ in range(10)] +
        [MarketMaker(exchange, 10**3, softlimit=100)]
    )
    non_mm = [t for t in all_traders if type(t) != MarketMaker]
    n_fast = int(round(fast_share * len(non_mm)))
    for i, t in enumerate(non_mm):
        t.speed = 'fast' if i < n_fast else 'slow'
    for t in all_traders:
        if type(t) == MarketMaker:
            t.speed = 'slow'

    sim = Simulator(exchange=exchange, traders=all_traders,
                    events=[MarketPriceShock(shock_it, -10)])
    sim.simulate(n_iter, silent=True, fast_extra_call=fast_extra_call)
    info = sim.info

    return {
        'fast_share':     fast_share,
        'crisis_share':   get_crisis_share(info, shock_it),
        'mm_panic_ratio': info.mm_panic_ratio(from_it=shock_it),
        'spread_ratio':   get_spread_ratio(info, shock_it),
        'prices':         info.prices,
    }


def run_grid(fast_shares=None, n_runs=10, n_iter=500, shock_it=200):
    if fast_shares is None:
        fast_shares = [round(x * 0.1, 1) for x in range(11)]
    records = []
    for fs in tqdm(fast_shares, desc='fast_share grid'):
        for run in range(n_runs):
            res = run_one(fs, n_iter, shock_it, seed=run * 100 + int(fs * 10))
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


def plot_main(agg, df, save='h1_results.png'):
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
    ax.axhline(0.3, color='black', ls='--', lw=1, label='Порог кризиса (0.3)')
    vline(ax); ax.legend(fontsize=8); ax.grid(alpha=0.3)
    ax.set(title='Доля кризисных состояний (после шока)',
           xlabel='Доля быстрых агентов', ylabel='Доля panic/disaster окон', ylim=(0,1))

    ax = fig.add_subplot(gs[0, 1])
    ax.plot(x, agg['mm_panic_mean'], 's-', color='navy', lw=2)
    ax.fill_between(x, agg['mm_panic_mean']-agg['mm_panic_std'],
                       agg['mm_panic_mean']+agg['mm_panic_std'], alpha=0.2, color='navy')
    vline(ax); ax.legend(fontsize=8); ax.grid(alpha=0.3)
    ax.set(title='Паника MarketMaker (после шока)',
           xlabel='Доля быстрых агентов', ylabel='Доля итераций в панике', ylim=(0,1))

    ax = fig.add_subplot(gs[1, 0])
    ax.plot(x, agg['spread_mean'], '^-', color='darkgreen', lw=2)
    ax.fill_between(x, agg['spread_mean']-agg['spread_std'],
                       agg['spread_mean']+agg['spread_std'], alpha=0.2, color='darkgreen')
    ax.axhline(1.0, color='black', ls='--', lw=1, label='Базовый уровень')
    vline(ax); ax.legend(fontsize=8); ax.grid(alpha=0.3)
    ax.set(title='Спред после / до шока',
           xlabel='Доля быстрых агентов', ylabel='Отношение спредов')

    ax = fig.add_subplot(gs[1, 1])
    groups = [df[df['fast_share']==fs]['crisis_share'].values
              for fs in sorted(df['fast_share'].unique())]
    labels = [str(fs) for fs in sorted(df['fast_share'].unique())]
    ax.boxplot(groups, labels=labels, patch_artist=True,
               boxprops=dict(facecolor='lightyellow', color='black'),
               medianprops=dict(color='crimson', lw=2))
    ax.axhline(0.3, color='black', ls='--', lw=1, label='Порог кризиса')
    ax.legend(fontsize=8); ax.grid(alpha=0.3, axis='y')
    ax.set(title='Разброс по прогонам (crisis_share)',
           xlabel='Доля быстрых агентов', ylabel='Crisis share')

    plt.suptitle('Гипотеза 1: Tipping Point при гетерогенности задержек\n'
                 '10 Fundamentalists + 10 Chartists + 1 MarketMaker | шок it=200, dp=−10',
                 fontsize=12, fontweight='bold')
    plt.savefig(save, dpi=150, bbox_inches='tight')
    print(f'Сохранено: {save}')
    plt.show()


def plot_price_examples(save='h1_prices.png'):
    fig, axes = plt.subplots(2, 2, figsize=(14, 8))
    for ax, fs in zip(axes.flatten(), [0.0, 0.3, 0.6, 1.0]):
        res = run_one(fs, seed=42)
        ax.plot(res['prices'], color='black', lw=0.8)
        ax.axvline(200, color='red', ls='--', lw=1.5, label='Шок (it=200)')
        ax.set(title=f'fast_share={fs} | crisis={res["crisis_share"]:.2f}',
               xlabel='Итерация', ylabel='Цена')
        ax.legend(fontsize=8); ax.grid(alpha=0.3)
    plt.suptitle('Примеры ценовых путей при разных fast_share', fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(save, dpi=150, bbox_inches='tight')
    print(f'Сохранено: {save}')
    plt.show()


if __name__ == '__main__':
    print('=' * 60)
    print('ГИПОТЕЗА 1: Tipping Point при гетерогенности задержек')
    print('=' * 60)

    print('\n[1/3] Примеры ценовых путей...')
    plot_price_examples()

    print('\n[2/3] Запуск грида (11 × 10 = 110 симуляций)...')
    df = run_grid(n_runs=10, n_iter=500, shock_it=200)
    df.to_csv('h1_raw.csv', index=False)
    agg = aggregate(df)
    print(agg.to_string(index=False))

    tp = find_tipping_point(agg)
    if tp is not None:
        print(f'\n✓ Tipping point: fast_share = {tp} ({int(tp*20)}/20 агентов быстрые)')
    else:
        print('\n✗ Tipping point не обнаружен')

    print('\n[3/3] Графики...')
    plot_main(agg, df)
    print('Готово!')
