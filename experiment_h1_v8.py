"""
Experiment H1 v8: front-running механизм
=========================================
Медленные агенты размещают заявки в pending_orders.
Быстрые агенты видят pending и front-run их.
Потом pending медленных исполняются по сдвинутым ценам.

Grid: fast_share × front_running (вкл/выкл для сравнения)
n_runs = 30
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


def slow_trader_loss(info, shock_it=200):
    """
    Средняя потеря equity медленных трейдеров после шока
    относительно быстрых — ключевая метрика front-running.
    """
    if len(info.equities) < shock_it + 10:
        return 0.0

    post_equities = info.equities[shock_it:]
    slow_losses = []
    fast_gains = []

    for snap in post_equities:
        for t_id, t in info.traders.items():
            eq_start = info.equities[shock_it].get(t_id, 0)
            eq_end = snap.get(t_id, 0)
            if eq_start == 0:
                continue
            ret = (eq_end - eq_start) / eq_start
            if getattr(t, 'speed', 'slow') == 'fast':
                fast_gains.append(ret)
            elif type(t) != MarketMaker:
                slow_losses.append(ret)

    if not fast_gains or not slow_losses:
        return 0.0
    return mean(fast_gains) - mean(slow_losses)  # разрыв в доходности


# ── Один прогон ───────────────────────────────────────────────────────────────

def run_one(fast_share, front_running=True, n_iter=500,
            shock_it=200, shock_dp=-10, softlimit=100, seed=None):
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
                 front_running=front_running)
    info = sim.info

    return {
        'fast_share':     fast_share,
        'front_running':  front_running,
        'vol_ratio':      vol_ratio(info, shock_it),
        'spread_ratio':   spread_ratio(info, shock_it),
        'max_drawdown':   max_drawdown(info, shock_it),
        'mm_panic_ratio': info.mm_panic_ratio(from_it=shock_it),
        'equity_gap':     slow_trader_loss(info, shock_it),
        'prices':         info.prices,
    }


# ── Полный грид ───────────────────────────────────────────────────────────────

def run_grid(fast_shares=None, n_runs=30, n_iter=500,
             shock_it=200, shock_dp=-10, softlimit=100):
    if fast_shares is None:
        fast_shares = [round(x * 0.1, 1) for x in range(11)]

    records = []
    for fr in [True, False]:
        label = 'front_run' if fr else 'baseline'
        for fs in tqdm(fast_shares, desc=f'{label}'):
            for run in range(n_runs):
                res = run_one(fs, fr, n_iter, shock_it, shock_dp, softlimit,
                              seed=run * 100 + int(fs * 10) + (1000 if fr else 2000))
                records.append({
                    'fast_share':     fs,
                    'front_running':  fr,
                    'run':            run,
                    'vol_ratio':      res['vol_ratio'],
                    'spread_ratio':   res['spread_ratio'],
                    'max_drawdown':   res['max_drawdown'],
                    'mm_panic_ratio': res['mm_panic_ratio'],
                    'equity_gap':     res['equity_gap'],
                })
    return pd.DataFrame(records)


def aggregate(df):
    return df.groupby(['front_running', 'fast_share']).agg(
        vol_ratio_mean    = ('vol_ratio',      'mean'),
        vol_ratio_std     = ('vol_ratio',      'std'),
        spread_ratio_mean = ('spread_ratio',   'mean'),
        spread_ratio_std  = ('spread_ratio',   'std'),
        drawdown_mean     = ('max_drawdown',   'mean'),
        drawdown_std      = ('max_drawdown',   'std'),
        mm_panic_mean     = ('mm_panic_ratio', 'mean'),
        mm_panic_std      = ('mm_panic_ratio', 'std'),
        equity_gap_mean   = ('equity_gap',     'mean'),
        equity_gap_std    = ('equity_gap',     'std'),
    ).reset_index()


def find_tipping_point(agg, front_running, col, baseline_multiplier=1.3):
    sub = agg[agg['front_running'] == front_running]
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

def plot_results(agg, shock_dp, save='h1_v8_results.png'):
    fig, axes = plt.subplots(2, 3, figsize=(18, 11))

    metrics = [
        ('vol_ratio_mean',    'vol_ratio_std',    'Volatility after/before shock',    1.0),
        ('spread_ratio_mean', 'spread_ratio_std', 'Spread after/before shock',             1.0),
        ('drawdown_mean',     'drawdown_std',      'Max. price drawdown',            None),
        ('mm_panic_mean',     'mm_panic_std',      'MarketMaker panic',             None),
        ('equity_gap_mean',   'equity_gap_std',    'Return gap (fast-slow)',  0.0),
    ]

    for ax, (col_m, col_s, title, baseline) in zip(axes.flatten(), metrics):
        for fr, color, label in [(True, 'crimson', 'With front-running'),
                                  (False, 'steelblue', 'Without front-running')]:
            sub = agg[agg['front_running'] == fr]
            x = sub['fast_share']
            ax.plot(x, sub[col_m], 'o-', color=color, lw=2, label=label)
            ax.fill_between(x, sub[col_m] - sub[col_s],
                               sub[col_m] + sub[col_s],
                               alpha=0.15, color=color)

        if baseline is not None:
            ax.axhline(baseline, color='black', ls='--', lw=1,
                       label='Baseline')

        tp = find_tipping_point(agg, True, col_m)
        if tp is not None:
            ax.axvline(tp, color='orange', ls=':', lw=2,
                       label=f'Tipping point ({tp})')

        ax.set(title=title, xlabel='Fast agent share')
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)

    # Последний subplot — сводный нормированный
    ax = axes[1, 2]
    for col_m, _, label, _ in metrics:
        sub_fr = agg[agg['front_running'] == True]
        sub_bl = agg[agg['front_running'] == False]
        # Разница между front-running и baseline
        diff = sub_fr[col_m].values - sub_bl[col_m].values
        ax.plot(sub_fr['fast_share'], diff, 'o-', lw=1.5,
                label=label[:20])
    ax.axhline(0, color='black', ls='--', lw=1)
    ax.set(title='Front-running effect\n(with FR minus without FR)',
           xlabel='Fast agent share')
    ax.legend(fontsize=6)
    ax.grid(alpha=0.3)

    plt.suptitle(
        f'Hypothesis 1 v8: front-running mechanism\n'
        f'10 Fund + 10 Chart + 1 MM | shock dp={shock_dp} | 30 runs',
        fontsize=12, fontweight='bold'
    )
    plt.tight_layout()
    plt.savefig(save, dpi=150, bbox_inches='tight')
    print(f'Сохранено: {save}')


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=' * 60)
    print('ГИПОТЕЗА 1 v8: front-running механизм')
    print('Медленные → pending → быстрые front-run → pending исполняются')
    print('Сравниваем: с front-running vs без')
    print('=' * 60)

    SHOCK_DP = -10

    print(f'\n[1/2] Грид (2 × 11 × 30 = 660 симуляций)...')
    print('      Ожидаемое время: ~40-50 минут')
    df = run_grid(n_runs=30, n_iter=500, shock_it=200,
                  shock_dp=SHOCK_DP, softlimit=100)
    df.to_csv('h1_v8_raw.csv', index=False)

    agg = aggregate(df)

    print('\nTipping points (front_running=True, порог 1.3x):')
    for col, label in [
        ('vol_ratio_mean',    'Волатильность'),
        ('spread_ratio_mean', 'Спред'),
        ('mm_panic_mean',     'Паника MM'),
        ('equity_gap_mean',   'Разрыв доходности'),
    ]:
        tp = find_tipping_point(agg, True, col)
        print(f'  {label:25s}: {tp if tp is not None else "не обнаружен"}')

    print('\nEquity gap (fast-slow) при front_running=True:')
    sub = agg[agg['front_running'] == True][['fast_share', 'equity_gap_mean']].round(4)
    print(sub.to_string(index=False))

    print('\n[2/2] Графики...')
    plot_results(agg, shock_dp=SHOCK_DP)
    print('\nГотово!')
