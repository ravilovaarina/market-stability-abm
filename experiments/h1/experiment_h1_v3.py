"""
Experiment H1 v3: Tipping Point — новые метрики
================================================
Проблема v1/v2: general_states() классифицирует ~80% нормального поведения
модели как 'panic'/'disaster' даже без шока. Метрика нерабочая.

Решение: убираем general_states(), считаем метрики напрямую из info:
  1. vol_ratio     — средняя волатильность после шока / до шока
  2. spread_ratio  — средний спред после шока / до шока
  3. recovery_time — сколько итераций цена остаётся ниже уровня до шока
  4. mm_panic_ratio — доля итераций где MarketMaker в панике (после шока)

Tipping point = резкий скачок любой из этих метрик при росте fast_share.
"""

import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from AgentBasedModel import *
from AgentBasedModel.agents import ExchangeAgent, Fundamentalist, Chartist, MarketMaker
from AgentBasedModel.simulator import Simulator
from AgentBasedModel.events import MarketPriceShock
from AgentBasedModel.utils.math import mean, std


# ── Метрики ───────────────────────────────────────────────────────────────────

def vol_ratio(info, shock_it=200, window=10):
    """Волатильность после шока / до шока."""
    vols = info.price_volatility(window=window)
    # price_volatility(window) возвращает список длины n-window
    # индексы сдвинуты на window
    pre  = vols[:shock_it - window]
    post = vols[shock_it:]
    if not pre or not post:
        return 1.0
    return mean(post) / (mean(pre) + 1e-9)


def spread_ratio(info, shock_it=200):
    """Средний относительный спред после / до шока."""
    def rel(spreads, prices):
        vals = [(s['ask'] - s['bid']) / p for s, p in zip(spreads, prices) if s and p]
        return mean(vals) if vals else 1e-9
    pre  = rel(info.spreads[:shock_it], info.prices[:shock_it])
    post = rel(info.spreads[shock_it:], info.prices[shock_it:])
    return post / (pre + 1e-9)


def recovery_time(info, shock_it=200):
    """
    Количество итераций после шока пока цена остаётся ниже
    среднего уровня цены до шока. Чем дольше — тем тяжелее кризис.
    """
    pre_mean = mean(info.prices[:shock_it])
    post_prices = info.prices[shock_it:]
    count = 0
    for p in post_prices:
        if p < pre_mean:
            count += 1
        else:
            break  # как только цена вернулась — останавливаемся
    return count


def max_drawdown(info, shock_it=200):
    """Максимальное падение цены после шока относительно цены до шока."""
    pre_price = info.prices[shock_it - 1]
    post = info.prices[shock_it:]
    if not post:
        return 0.0
    min_post = min(post)
    return (pre_price - min_post) / pre_price


# ── Один прогон ───────────────────────────────────────────────────────────────

def run_one(fast_share, n_iter=500, shock_it=200, shock_dp=-10,
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
            t.access = fast_access
    for t in all_traders:
        if type(t) == MarketMaker:
            t.speed = 'slow'

    sim = Simulator(exchange=exchange, traders=all_traders,
                    events=[MarketPriceShock(shock_it, shock_dp)])
    sim.simulate(n_iter, silent=True, fast_extra_call=fast_extra_call)
    info = sim.info

    return {
        'fast_share':     fast_share,
        'vol_ratio':      vol_ratio(info, shock_it),
        'spread_ratio':   spread_ratio(info, shock_it),
        'recovery_time':  recovery_time(info, shock_it),
        'max_drawdown':   max_drawdown(info, shock_it),
        'mm_panic_ratio': info.mm_panic_ratio(from_it=shock_it),
        'prices':         info.prices,
    }


# ── Полный грид ───────────────────────────────────────────────────────────────

def run_grid(fast_shares=None, n_runs=10, n_iter=500, shock_it=200, shock_dp=-10):
    if fast_shares is None:
        fast_shares = [round(x * 0.1, 1) for x in range(11)]
    records = []
    for fs in tqdm(fast_shares, desc=f'fast_share grid (dp={shock_dp})'):
        for run in range(n_runs):
            res = run_one(fs, n_iter, shock_it, shock_dp,
                          seed=run * 100 + int(fs * 10))
            records.append({
                'fast_share':     fs,
                'run':            run,
                'vol_ratio':      res['vol_ratio'],
                'spread_ratio':   res['spread_ratio'],
                'recovery_time':  res['recovery_time'],
                'max_drawdown':   res['max_drawdown'],
                'mm_panic_ratio': res['mm_panic_ratio'],
            })
    return pd.DataFrame(records)


def aggregate(df):
    return df.groupby('fast_share').agg(
        vol_ratio_mean    = ('vol_ratio',      'mean'),
        vol_ratio_std     = ('vol_ratio',      'std'),
        spread_ratio_mean = ('spread_ratio',   'mean'),
        spread_ratio_std  = ('spread_ratio',   'std'),
        recovery_mean     = ('recovery_time',  'mean'),
        recovery_std      = ('recovery_time',  'std'),
        drawdown_mean     = ('max_drawdown',   'mean'),
        drawdown_std      = ('max_drawdown',   'std'),
        mm_panic_mean     = ('mm_panic_ratio', 'mean'),
        mm_panic_std      = ('mm_panic_ratio', 'std'),
    ).reset_index()


def find_tipping_point(agg, col, baseline_multiplier=1.5):
    """
    Tipping point = первый fast_share где метрика превышает
    baseline (fast_share=0) более чем в baseline_multiplier раз.
    """
    baseline = agg.loc[agg['fast_share'] == 0.0, col].values
    if len(baseline) == 0:
        return None
    baseline = baseline[0]
    for _, row in agg.iterrows():
        if row['fast_share'] == 0.0:
            continue
        if row[col] >= baseline * baseline_multiplier:
            return row['fast_share']
    return None


# ── Графики ───────────────────────────────────────────────────────────────────

def plot_results(agg, df, shock_dp, save='h1_v3_results.png'):
    fig = plt.figure(figsize=(16, 12))
    gs = gridspec.GridSpec(2, 3, hspace=0.45, wspace=0.35)
    x = agg['fast_share']

    metrics = [
        ('vol_ratio_mean',    'vol_ratio_std',    'crimson',   'Volatility after/before shock',   1.0),
        ('spread_ratio_mean', 'spread_ratio_std', 'darkgreen', 'Spread after/before shock',            1.0),
        ('recovery_mean',     'recovery_std',     'navy',      'Recovery time (iterations)', None),
        ('drawdown_mean',     'drawdown_std',      'darkorange','Max. price drawdown (%)',        None),
        ('mm_panic_mean',     'mm_panic_std',      'purple',   'MarketMaker panic',              None),
    ]

    positions = [gs[0,0], gs[0,1], gs[0,2], gs[1,0], gs[1,1]]

    for pos, (col_m, col_s, color, title, baseline) in zip(positions, metrics):
        ax = fig.add_subplot(pos)
        ax.plot(x, agg[col_m], 'o-', color=color, lw=2)
        ax.fill_between(x, agg[col_m]-agg[col_s],
                           agg[col_m]+agg[col_s], alpha=0.2, color=color)
        if baseline is not None:
            ax.axhline(baseline, color='black', ls='--', lw=1, label=f'Baseline ({baseline})')

        tp = find_tipping_point(agg, col_m)
        if tp is not None:
            ax.axvline(tp, color='orange', ls=':', lw=2, label=f'Tipping point ({tp})')

        ax.set(title=title, xlabel='Fast agent share')
        ax.legend(fontsize=7); ax.grid(alpha=0.3)

    # Сводный график — все нормированные метрики на одном
    ax = fig.add_subplot(gs[1, 2])
    for col_m, _, color, label, _ in metrics:
        norm = agg[col_m] / agg[col_m].iloc[0]  # нормируем на значение при fast_share=0
        ax.plot(x, norm, 'o-', color=color, lw=1.5,
                label=label.split('(')[0].strip()[:20])
    ax.axhline(1.0, color='black', ls='--', lw=1, label='Baseline')
    ax.set(title='All metrics (norm. to fast_share=0)',
           xlabel='Fast agent share', ylabel='Relative change')
    ax.legend(fontsize=6); ax.grid(alpha=0.3)

    plt.suptitle(
        f'Hypothesis 1 v3: Direct instability metrics\n'
        f'shock dp={shock_dp} | fast_access=5, slow_access=1 | 10 runs',
        fontsize=12, fontweight='bold'
    )
    plt.savefig(save, dpi=150, bbox_inches='tight')
    print(f'Сохранено: {save}')


def plot_price_examples(shock_dp=-10, save='h1_v3_price_examples.png'):
    fig, axes = plt.subplots(2, 2, figsize=(14, 8))
    for ax, fs in zip(axes.flatten(), [0.0, 0.3, 0.6, 1.0]):
        res = run_one(fs, shock_dp=shock_dp, seed=42)
        ax.plot(res['prices'], color='black', lw=0.8)
        ax.axvline(200, color='red', ls='--', lw=1.5, label='Shock')
        ax.axhline(mean(res['prices'][:200]), color='blue', ls=':', lw=1, label='Pre-shock mean')
        ax.set(title=f'fast_share={fs} | drawdown={res["max_drawdown"]:.2f} | recovery={res["recovery_time"]}',
               xlabel='Iteration', ylabel='Price')
        ax.legend(fontsize=7); ax.grid(alpha=0.3)
    plt.suptitle(f'Sample price paths | shock dp={shock_dp}', fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(save, dpi=150, bbox_inches='tight')
    print(f'Сохранено: {save}')


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=' * 60)
    print('ГИПОТЕЗА 1 v3: прямые метрики нестабильности')
    print('Метрики: vol_ratio, spread_ratio, recovery_time,')
    print('         max_drawdown, mm_panic_ratio')
    print('=' * 60)

    SHOCK_DP = -10   # можно менять

    print(f'\n[1/3] Примеры ценовых путей (dp={SHOCK_DP})...')
    plot_price_examples(shock_dp=SHOCK_DP)

    print(f'\n[2/3] Полный грид (11 × 10 = 110 симуляций, dp={SHOCK_DP})...')
    df = run_grid(n_runs=10, n_iter=500, shock_it=200, shock_dp=SHOCK_DP)
    df.to_csv('h1_v3_raw.csv', index=False)

    agg = aggregate(df)
    print('\nАгрегированные результаты:')
    print(agg[['fast_share','vol_ratio_mean','spread_ratio_mean',
               'recovery_mean','drawdown_mean','mm_panic_mean']].to_string(index=False))

    # Tipping points по каждой метрике
    print('\nTipping points (превышение базового уровня в 1.5x):')
    for col, label in [('vol_ratio_mean','Волатильность'), ('spread_ratio_mean','Спред'),
                       ('recovery_mean','Время восстановления'), ('drawdown_mean','Просадка'),
                       ('mm_panic_mean','Паника MM')]:
        tp = find_tipping_point(agg, col)
        print(f'  {label}: {tp if tp else "не обнаружен"}')

    print('\n[3/3] Графики...')
    plot_results(agg, df, shock_dp=SHOCK_DP)
    print('\nГотово!')
