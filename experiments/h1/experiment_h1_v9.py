"""
Experiment H1 v9: TrendChartist + информационная задержка
=========================================================

ДИАГНОЗ ПРЕДЫДУЩИХ ВЕРСИЙ
--------------------------
v1–v6: generic fast_share (execution priority) → нет сигнала
        fast_extra_call=True даёт двойной вызов → больше торговли = лучше price discovery = НИЖЕ волатильность

v7:    delayed_price_lag объявлен как параметр, но НЕ передаётся в симулятор — баг,
        v7 идентичен v6 по механике

v8:    front-running + fast_extra_call → быстрые торгуют вдвое больше →
        vol_ratio СНИЖАЕТСЯ при росте hft_frac (обратный эффект)

КОРЕНЬ ПРОБЛЕМЫ
---------------
В AgentBasedModel/agents/agents.py формула change_sentiment:
    O→P: prob ∝ exp( U)   — когда U>0 (цена растёт) оптимисты уходят в пессимизм → КОНТРАРНО
    P→O: prob ∝ exp(-U)   — когда U<0 (цена падает) пессимисты уходят в оптимизм → КОНТРАРНО

Результат: после шока (dp=-10) чартисты ПОКУПАЮТ (контрарно), стабилизируя рынок.
Значит, более быстрые контрарные чартисты = быстрее гасят шок = НИЖЕ волатильность.
H1 не может быть подтверждена с контрарными чартистами.

РЕШЕНИЕ v9
----------
TrendChartist: меняем знаки в формуле:
    O→P: prob ∝ exp(-U)   — когда U<0 (цена падает) оптимисты уходят в пессимизм → ТРЕНДОВО
    P→O: prob ∝ exp( U)   — когда U>0 (цена растёт) пессимисты уходят в оптимизм → ТРЕНДОВО

Теперь после шока (dp=-10): чартисты немедленно становятся пессимистами → ПРОДАЮТ → усиливают падение.

SlowTrendChartist: TrendChartist + задержанный ценовой сигнал (lag итераций)
    После шока t=200:
    - Fast TrendChartist (lag=0): видит dp=-10 → Pessimistic → продаёт → первая волна
    - Slow TrendChartist (lag=5): видит dp[t-5]≈0 → не реагирует → нейтрален
    - При t=205: Slow видит dp=-10 → Pessimistic → продаёт → вторая волна
    - Fundamentalists: видят низкую цену → покупают (стабилизация), но идут после чартистов

ОЖИДАЕМЫЙ РЕЗУЛЬТАТ
-------------------
hft_frac↑ → сильнее первая волна после шока → vol_ratio↑, spread_ratio↑
lag↑      → больший разрыв между быстрыми и медленными → эффект сильнее

Grid:
    hft_frac ∈ {0.0, 0.1, ..., 1.0}  — доля Fast TrendChartists среди всех чартистов
    lag      ∈ {0, 1, 3, 5, 10}       — задержка (итераций) для Slow TrendChartists
    n_runs   = 30
"""

import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import random
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from math import exp
from tqdm import tqdm

from AgentBasedModel.agents import ExchangeAgent, Fundamentalist, Chartist, MarketMaker
from AgentBasedModel.simulator import SimulatorInfo
from AgentBasedModel.events import MarketPriceShock
from AgentBasedModel.utils.math import mean, std
from experiments.paths import result_path


# ══════════════════════════════════════════════════════════════════════════════
# Классы агентов
# ══════════════════════════════════════════════════════════════════════════════

class TrendChartist(Chartist):
    """
    Трендовый чартист — исправленная версия Chartist из agents.py.

    В оригинальном Chartist знаки в exp перепутаны: агент контрарный
    (после падения цены становится оптимистом и покупает).

    TrendChartist меняет знаки → позитивная обратная связь:
    - После падения цены → становится Pessimistic → продаёт → усиливает падение
    - После роста цены  → становится Optimistic  → покупает → усиливает рост

    Именно такое поведение нужно для H1 (HFT-дестабилизация).
    """

    def change_sentiment(self, info, a1=1, a2=1, v1=0.1):
        n_traders   = len(info.traders)
        n_chartists = sum(v == 'Chartist' for v in info.types[-1].values())
        if n_chartists == 0:
            return

        n_optimistic = sum(v == 'Optimistic' for v in info.sentiments[-1].values())
        n_pessimists = sum(v == 'Pessimistic' for v in info.sentiments[-1].values())

        dp = info.prices[-1] - info.prices[-2] if len(info.prices) > 1 else 0
        p  = self.market.price()
        x  = (n_optimistic - n_pessimists) / max(n_chartists, 1)

        U = a1 * x + a2 / v1 * dp / p

        # TREND-FOLLOWING: знаки поменяны относительно оригинала
        if self.sentiment == 'Optimistic':
            prob = v1 * n_chartists / n_traders * exp(-U)   # большое при U<0 (цена падает)
            if prob > random.random():
                self.sentiment = 'Pessimistic'
        elif self.sentiment == 'Pessimistic':
            prob = v1 * n_chartists / n_traders * exp(U)    # большое при U>0 (цена растёт)
            if prob > random.random():
                self.sentiment = 'Optimistic'


class SlowTrendChartist(TrendChartist):
    """
    Трендовый чартист с задержкой ценового сигнала.

    Видит изменение цены `lag` итераций назад — симулирует медленного трейдера,
    который реагирует на движения рынка с опозданием (информационная задержка).
    """

    def __init__(self, market, cash, assets=0, lag=3):
        super().__init__(market, cash, assets)
        self.lag = lag

    def change_sentiment(self, info, a1=1, a2=1, v1=0.1):
        n_traders   = len(info.traders)
        n_chartists = sum(v == 'Chartist' for v in info.types[-1].values())
        if n_chartists == 0:
            return

        n_optimistic = sum(v == 'Optimistic' for v in info.sentiments[-1].values())
        n_pessimists = sum(v == 'Pessimistic' for v in info.sentiments[-1].values())

        # Задержанный ценовой сигнал
        if self.lag == 0 or len(info.prices) <= self.lag + 1:
            dp = info.prices[-1] - info.prices[-2] if len(info.prices) > 1 else 0
        else:
            dp = info.prices[-1 - self.lag] - info.prices[-2 - self.lag]

        p = self.market.price()
        x = (n_optimistic - n_pessimists) / max(n_chartists, 1)

        U = a1 * x + a2 / v1 * dp / p

        # TREND-FOLLOWING с задержанным сигналом
        if self.sentiment == 'Optimistic':
            prob = v1 * n_chartists / n_traders * exp(-U)
            if prob > random.random():
                self.sentiment = 'Pessimistic'
        elif self.sentiment == 'Pessimistic':
            prob = v1 * n_chartists / n_traders * exp(U)
            if prob > random.random():
                self.sentiment = 'Optimistic'


# ══════════════════════════════════════════════════════════════════════════════
# Симулятор
# ══════════════════════════════════════════════════════════════════════════════

class SimulatorV9:
    """
    Симулятор для v9.

    Ключевые отличия от базового:
    1. isinstance(t, Chartist) вместо type(t) == Chartist → работает с TrendChartist/SlowTrendChartist
    2. Python dispatch автоматически вызывает правильную change_sentiment для каждого типа
    3. Fast-first execution, БЕЗ extra call (extra call стабилизировал в v8)
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

    def simulate(self, n_iter, silent=False):
        for it in tqdm(range(n_iter), desc='Simulation', disable=silent):

            # 1. События
            if self.events:
                for e in self.events:
                    e.call(it)

            # 2. Захват состояния
            self.info.capture()

            # 3. Обновление настроений (Python dispatch → верная change_sentiment)
            for t in self.traders:
                if isinstance(t, Chartist) and type(t).__name__ != 'Universalist':
                    t.change_sentiment(self.info)

            # 4. Торговля: fast первыми
            fast = [t for t in self.traders if getattr(t, 'speed', 'slow') == 'fast']
            slow = [t for t in self.traders if getattr(t, 'speed', 'slow') != 'fast']

            random.shuffle(fast)
            for t in fast:
                t.call()

            random.shuffle(slow)
            for t in slow:
                t.call()

            # 5. Выплаты и дивиденды
            self._payments()
            self.exchange.generate_dividend()

        return self


# ══════════════════════════════════════════════════════════════════════════════
# Метрики
# ══════════════════════════════════════════════════════════════════════════════

def vol_ratio(info, shock_it=200, window=10):
    """Соотношение волатильности цены после/до шока."""
    vols = info.price_volatility(window=window)
    pre  = vols[:shock_it - window]
    post = vols[shock_it:]
    if not pre or not post:
        return 1.0
    return mean(post) / (mean(pre) + 1e-9)


def spread_ratio(info, shock_it=200):
    """Соотношение нормированного спреда после/до шока."""
    def rel_spread(spreads, prices):
        vals = [(s['ask'] - s['bid']) / p
                for s, p in zip(spreads, prices) if s and p]
        return mean(vals) if vals else 1e-9

    pre  = rel_spread(info.spreads[:shock_it], info.prices[:shock_it])
    post = rel_spread(info.spreads[shock_it:], info.prices[shock_it:])
    return post / (pre + 1e-9)


def max_drawdown(info, shock_it=200):
    """Максимальная просадка цены от уровня до шока."""
    pre_price = info.prices[shock_it - 1]
    post = info.prices[shock_it:]
    if not post:
        return 0.0
    return (pre_price - min(post)) / pre_price


def recovery_time(info, shock_it=200, threshold=0.02):
    """Итераций до возврата цены в диапазон ±threshold от уровня до шока."""
    pre_price = info.prices[shock_it - 1]
    for i, p in enumerate(info.prices[shock_it:]):
        if abs(p - pre_price) / pre_price < threshold:
            return i
    return len(info.prices) - shock_it  # не восстановилась


# ══════════════════════════════════════════════════════════════════════════════
# Один прогон
# ══════════════════════════════════════════════════════════════════════════════

def run_one(hft_frac, lag=3, n_iter=500, shock_it=200,
            shock_dp=-10, softlimit=100, seed=None):
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)

    exchange = ExchangeAgent(price=100, std=25, volume=1000, rf=5e-4)

    n_chartists_total = 10
    n_fast = round(hft_frac * n_chartists_total)
    n_slow = n_chartists_total - n_fast

    # Быстрые: TrendChartist, видят текущую цену, торгуют первыми
    fast_chartists = [TrendChartist(exchange, 10**3) for _ in range(n_fast)]
    for t in fast_chartists:
        t.speed = 'fast'

    # Медленные: SlowTrendChartist, видят цену с задержкой lag
    slow_chartists = [SlowTrendChartist(exchange, 10**3, lag=lag) for _ in range(n_slow)]
    for t in slow_chartists:
        t.speed = 'slow'

    fundamentalists = [Fundamentalist(exchange, 10**3, access=1) for _ in range(10)]
    for t in fundamentalists:
        t.speed = 'slow'

    mm = MarketMaker(exchange, 10**3, softlimit=softlimit)
    mm.speed = 'slow'

    all_traders = fast_chartists + slow_chartists + fundamentalists + [mm]

    sim = SimulatorV9(
        exchange=exchange,
        traders=all_traders,
        events=[MarketPriceShock(shock_it, shock_dp)]
    )
    sim.simulate(n_iter, silent=True)
    info = sim.info

    return {
        'hft_frac':       hft_frac,
        'lag':            lag,
        'vol_ratio':      vol_ratio(info, shock_it),
        'spread_ratio':   spread_ratio(info, shock_it),
        'max_drawdown':   max_drawdown(info, shock_it),
        'recovery_time':  recovery_time(info, shock_it),
        'mm_panic_ratio': info.mm_panic_ratio(from_it=shock_it),
        'prices':         info.prices,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Полный грид
# ══════════════════════════════════════════════════════════════════════════════

def run_grid(hft_fracs=None, lags=None, n_runs=30, n_iter=500,
             shock_it=200, shock_dp=-10, softlimit=100):
    if hft_fracs is None:
        hft_fracs = [round(x * 0.1, 1) for x in range(11)]
    if lags is None:
        lags = [0, 1, 3, 5, 10]

    records = []
    for lag in lags:
        for fs in tqdm(hft_fracs, desc=f'lag={lag}'):
            for run in range(n_runs):
                seed = run * 1000 + int(fs * 10) * 10 + lag
                r = run_one(fs, lag, n_iter, shock_it, shock_dp, softlimit, seed=seed)
                records.append({
                    'hft_frac':       r['hft_frac'],
                    'lag':            r['lag'],
                    'run':            run,
                    'vol_ratio':      r['vol_ratio'],
                    'spread_ratio':   r['spread_ratio'],
                    'max_drawdown':   r['max_drawdown'],
                    'recovery_time':  r['recovery_time'],
                    'mm_panic_ratio': r['mm_panic_ratio'],
                })
    return pd.DataFrame(records)


def aggregate(df):
    return df.groupby(['lag', 'hft_frac']).agg(
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
    ).reset_index()


def find_tipping_point(agg, lag, col, multiplier=1.3):
    """Первый hft_frac при котором метрика превышает baseline * multiplier."""
    sub = agg[agg['lag'] == lag].sort_values('hft_frac')
    baseline = sub.loc[sub['hft_frac'] == 0.0, col].values
    if len(baseline) == 0:
        return None
    baseline = baseline[0]
    for _, row in sub.iterrows():
        if row['hft_frac'] == 0.0:
            continue
        if row[col] >= baseline * multiplier:
            return row['hft_frac']
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Графики
# ══════════════════════════════════════════════════════════════════════════════

def plot_results(agg, shock_dp, save='h1_v9_results.png'):
    lags   = sorted(agg['lag'].unique())
    colors = plt.cm.plasma(np.linspace(0.15, 0.85, len(lags)))

    fig = plt.figure(figsize=(20, 14))
    gs  = gridspec.GridSpec(3, 3, figure=fig, hspace=0.48, wspace=0.35)

    metrics = [
        ('vol_ratio_mean',    'vol_ratio_std',    'Volatility: after/before shock',    1.0),
        ('spread_ratio_mean', 'spread_ratio_std', 'Spread: after/before shock (liquidity)', 1.0),
        ('drawdown_mean',     'drawdown_std',      'Max. price drawdown',            None),
        ('recovery_mean',     'recovery_std',      'Recovery time (iterations)',  None),
        ('mm_panic_mean',     'mm_panic_std',      'MarketMaker panic',             None),
    ]

    for idx, (col_m, col_s, title, baseline_val) in enumerate(metrics):
        ax = fig.add_subplot(gs[idx // 3, idx % 3])
        for lag, color in zip(lags, colors):
            sub = agg[agg['lag'] == lag]
            label = f'lag={lag}' + (' (no delay)' if lag == 0 else '')
            ax.plot(sub['hft_frac'], sub[col_m], 'o-', color=color, lw=2, label=label)
            ax.fill_between(sub['hft_frac'],
                            sub[col_m] - sub[col_s],
                            sub[col_m] + sub[col_s],
                            alpha=0.12, color=color)

        if baseline_val is not None:
            ax.axhline(baseline_val, color='black', ls='--', lw=1, alpha=0.5, label='Baseline')

        # Tipping point для lag=5
        if 5 in lags:
            tp = find_tipping_point(agg, 5, col_m)
            if tp is not None:
                ax.axvline(tp, color='orange', ls=':', lw=2, label=f'Tipping (lag=5): {tp}')

        ax.set(title=title,
               xlabel='Fast chartist share (hft_frac)',
               ylabel=col_m.replace('_mean', ''))
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)

    # Heatmap волатильности
    ax_h = fig.add_subplot(gs[1, 2])
    pivot = agg.pivot(index='lag', columns='hft_frac', values='vol_ratio_mean')
    im = ax_h.imshow(pivot.values, aspect='auto', origin='lower',
                     cmap='RdYlGn_r',
                     extent=[-0.05, 1.05,
                             pivot.index.min() - 0.5,
                             pivot.index.max() + 0.5])
    ax_h.set_yticks(pivot.index)
    ax_h.set(title='Heatmap: volatility\n(darker = higher)',
             xlabel='hft_frac', ylabel='lag')
    plt.colorbar(im, ax=ax_h, fraction=0.04)

    # Сводная таблица tipping points
    ax_t = fig.add_subplot(gs[2, 2])
    ax_t.axis('off')
    tp_data = []
    for lag in lags:
        tp_v = find_tipping_point(agg, lag, 'vol_ratio_mean')
        tp_s = find_tipping_point(agg, lag, 'spread_ratio_mean')
        tp_data.append([
            f'lag={lag}',
            f'{tp_v:.1f}' if tp_v is not None else '—',
            f'{tp_s:.1f}' if tp_s is not None else '—',
        ])
    t = ax_t.table(
        cellText=tp_data,
        colLabels=['Condition', 'Tipping Vol', 'Tipping Spread'],
        cellLoc='center', loc='center'
    )
    t.auto_set_font_size(True)
    ax_t.set_title('Tipping points (threshold ×1.3)', fontsize=9)

    plt.suptitle(
        f'Hypothesis H1 v9: TrendChartist + information delay\n'
        f'10 Fundamentalists (slow) + 10 TrendChartists (fast/slow) + 1 MM\n'
        f'Shock dp={shock_dp} at t=200 | {30} runs | fast-first, no extra call',
        fontsize=12, fontweight='bold'
    )
    plt.savefig(save, dpi=150, bbox_inches='tight')
    print(f'Сохранено: {save}')
    plt.close()


def plot_price_examples(lag=5, hft_fracs_to_show=None, shock_it=200,
                        shock_dp=-10, n_iter=500, n_examples=5,
                        save='h1_v9_prices.png'):
    """Примеры ценовых траекторий для разных hft_frac при заданном lag."""
    if hft_fracs_to_show is None:
        hft_fracs_to_show = [0.0, 0.3, 0.7, 1.0]

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    for ax, fs in zip(axes.flatten(), hft_fracs_to_show):
        for seed in range(n_examples):
            r = run_one(fs, lag=lag, n_iter=n_iter,
                        shock_it=shock_it, shock_dp=shock_dp, seed=seed)
            color = plt.cm.Blues(0.4 + seed * 0.12)
            ax.plot(r['prices'], color=color, lw=0.9, alpha=0.85)
        ax.axvline(shock_it, color='red', ls='--', lw=1.5, label='Shock')
        ax.set(title=f'hft_frac={fs} (lag={lag})',
               xlabel='Iterations', ylabel='Price')
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)

    plt.suptitle(f'Sample prices at lag={lag} | TrendChartist v9',
                 fontsize=12, fontweight='bold')
    plt.tight_layout()
    plt.savefig(save, dpi=150, bbox_inches='tight')
    print(f'Сохранено: {save}')
    plt.close()


def print_summary(agg):
    """Краткое резюме результатов в stdout."""
    print('\n' + '=' * 65)
    print('РЕЗУЛЬТАТЫ H1 v9')
    print('=' * 65)

    lags = sorted(agg['lag'].unique())

    # vol_ratio при каждом lag
    for lag in lags:
        sub = agg[agg['lag'] == lag][['hft_frac', 'vol_ratio_mean', 'vol_ratio_std']]
        baseline = sub.loc[sub['hft_frac'] == 0.0, 'vol_ratio_mean'].values[0]
        max_val  = sub['vol_ratio_mean'].max()
        max_fs   = sub.loc[sub['vol_ratio_mean'].idxmax(), 'hft_frac']
        tp       = find_tipping_point(agg, lag, 'vol_ratio_mean')
        trend    = 'РАСТЁТ ✓' if sub.loc[sub['hft_frac'] == 1.0, 'vol_ratio_mean'].values[0] > baseline else 'НЕ РАСТЁТ ✗'
        print(f'\nlag={lag:2d}:  baseline={baseline:.3f}  max={max_val:.3f}@{max_fs}  '
              f'tipping={tp if tp else "—"}  → {trend}')

    print('\nVol ratio при lag=5:')
    sub5 = agg[agg['lag'] == 5][['hft_frac', 'vol_ratio_mean', 'vol_ratio_std']].round(3)
    print(sub5.to_string(index=False))

    print('\nTipping points (порог 1.3× от baseline):')
    for lag in lags:
        tp_v = find_tipping_point(agg, lag, 'vol_ratio_mean')
        tp_s = find_tipping_point(agg, lag, 'spread_ratio_mean')
        tp_r = find_tipping_point(agg, lag, 'recovery_mean')
        print(f'  lag={lag:2d}: vol={str(tp_v) if tp_v else "—":>4s}  '
              f'spread={str(tp_s) if tp_s else "—":>4s}  '
              f'recovery={str(tp_r) if tp_r else "—":>4s}')


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print('=' * 65)
    print('ГИПОТЕЗА H1 v9: TrendChartist + информационная задержка')
    print('Механизм: fast_chartists видят текущий dp,')
    print('          slow_chartists видят dp с задержкой lag итераций')
    print('Ожидание: hft_frac↑ → vol↑, spread↑, recovery_time↑')
    print('=' * 65)

    SHOCK_DP  = -10
    N_RUNS    = 30
    N_ITER    = 500
    SHOCK_IT  = 200
    LAGS      = [0, 1, 3, 5, 10]
    HFT_FRACS = [round(x * 0.1, 1) for x in range(11)]
    SOFTLIMIT = 100

    total = len(LAGS) * len(HFT_FRACS) * N_RUNS
    print(f'\n[1/3] Грид ({len(LAGS)} лагов × {len(HFT_FRACS)} значений × {N_RUNS} прогонов = {total} симуляций)...')

    df = run_grid(HFT_FRACS, LAGS, N_RUNS, N_ITER, SHOCK_IT, SHOCK_DP, SOFTLIMIT)
    raw_path = result_path("h1", "raw", "h1_v9_raw.csv")
    df.to_csv(raw_path, index=False)
    print(f'Сохранено: {raw_path}')

    agg = aggregate(df)
    print_summary(agg)

    print('\n[2/3] Основные графики...')
    plot_results(
        agg,
        shock_dp=SHOCK_DP,
        save=result_path("h1", "figures", "h1_v9_results.png"),
    )

    print('\n[3/3] Примеры ценовых траекторий (lag=5)...')
    plot_price_examples(
        lag=5,
        save=result_path("h1", "figures", "h1_v9_prices.png"),
    )

    print('\nГотово!')
