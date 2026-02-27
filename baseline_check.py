"""
Диагностика базового сценария.
Запускаем симуляцию БЕЗ шока и смотрим:
1. Какие состояния general_states() выдаёт в норме?
2. Какой crisis_share без всякого воздействия?
3. Как выглядит цена и волатильность?

Если crisis_share высокий даже без шока — проблема в метрике или в составе агентов.
"""

import random
import numpy as np
import matplotlib.pyplot as plt
from AgentBasedModel import *
from AgentBasedModel.agents import ExchangeAgent, Fundamentalist, Chartist, MarketMaker
from AgentBasedModel.simulator import Simulator
from AgentBasedModel.states import general_states
from AgentBasedModel.utils.math import mean


def run_baseline(seed=42, n_iter=500, with_shock=False):
    random.seed(seed)
    np.random.seed(seed)

    exchange = ExchangeAgent(price=100, std=25, volume=1000, rf=5e-4)
    traders = (
        [Fundamentalist(exchange, 10**3, access=1) for _ in range(10)] +
        [Chartist(exchange, 10**3) for _ in range(10)] +
        [MarketMaker(exchange, 10**3, softlimit=100)]
    )
    events = [MarketPriceShock(200, -10)] if with_shock else []
    sim = Simulator(exchange=exchange, traders=traders, events=events if events else None)
    sim.simulate(n_iter, silent=True)
    return sim


print('=' * 55)
print('ДИАГНОСТИКА БАЗОВОГО СЦЕНАРИЯ')
print('=' * 55)

# --- 1. Без шока ---
print('\n[1] Без шока...')
sim_no = run_baseline(with_shock=False)
states_no = general_states(sim_no.info, size=10, window=5)
counts_no = {s: states_no.count(s) for s in set(states_no)}
crisis_no = sum(1 for s in states_no if s in ('panic','disaster')) / len(states_no)
print(f'  Распределение состояний: {counts_no}')
print(f'  Crisis share (panic+disaster): {crisis_no:.3f}')
print(f'  Средняя цена: {mean(sim_no.info.prices):.2f}')
print(f'  Волатильность цены: {sim_no.info.price_volatility():.4f}')

# --- 2. С шоком dp=-10 ---
print('\n[2] С шоком dp=-10...')
sim_sh = run_baseline(with_shock=True)
states_sh = general_states(sim_sh.info, size=10, window=5)
counts_sh = {s: states_sh.count(s) for s in set(states_sh)}
crisis_sh = sum(1 for s in states_sh if s in ('panic','disaster')) / len(states_sh)
print(f'  Распределение состояний: {counts_sh}')
print(f'  Crisis share (panic+disaster): {crisis_sh:.3f}')

# --- Графики ---
fig, axes = plt.subplots(2, 2, figsize=(14, 8))

# --- Plots ---
fig, axes = plt.subplots(2, 2, figsize=(14, 8))

# Prices
axes[0,0].plot(sim_no.info.prices, color='black', lw=0.8)
axes[0,0].set(title='Price — WITHOUT shock', xlabel='Iteration', ylabel='Price')
axes[0,0].grid(alpha=0.3)

axes[0,1].plot(sim_sh.info.prices, color='black', lw=0.8)
axes[0,1].axvline(200, color='red', ls='--', lw=1.5, label='Shock dp=-10')
axes[0,1].set(title='Price — WITH shock dp=-10', xlabel='Iteration', ylabel='Price')
axes[0,1].legend(); axes[0,1].grid(alpha=0.3)

# Volatility
vol_no = sim_no.info.price_volatility(window=10)
vol_sh = sim_sh.info.price_volatility(window=10)
axes[1,0].plot(vol_no, color='steelblue', lw=1)
axes[1,0].set(title='Volatility — WITHOUT shock', xlabel='Iteration', ylabel='Price std (window=10)')
axes[1,0].grid(alpha=0.3)

axes[1,1].plot(vol_sh, color='steelblue', lw=1)
axes[1,1].axvline(200, color='red', ls='--', lw=1.5, label='Shock dp=-10')
axes[1,1].set(title='Volatility — WITH shock dp=-10', xlabel='Iteration', ylabel='Price std (window=10)')
axes[1,1].legend(); axes[1,1].grid(alpha=0.3)

plt.suptitle(f'Diagnostics: crisis_share without shock = {crisis_no:.2f}, with shock = {crisis_sh:.2f}',
             fontsize=12, fontweight='bold')
plt.tight_layout()
plt.savefig('h1_baseline_check_prices_volatility.png', dpi=150, bbox_inches='tight')
print('\nСохранено: h1_baseline_check_prices_volatility.png')

# --- Вывод ---
print('\n' + '=' * 55)
print('ВЫВОД:')
if crisis_no > 0.5:
    print(f'  ⚠ crisis_share БЕЗ шока = {crisis_no:.2f} — модель хронически')
    print('    в кризисе. general_states() слишком чувствительна.')
    print('    Нужно менять метрику или состав агентов.')
else:
    print(f'  ✓ crisis_share БЕЗ шока = {crisis_no:.2f} — базовый сценарий стабилен.')
    print(f'    Шок поднимает до {crisis_sh:.2f}. Метрика рабочая.')
print('=' * 55)