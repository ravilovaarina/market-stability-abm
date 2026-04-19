# 1D-ABM H1 Experiment Documentation

## Project Overview

**Title:** Financial Market Stability under Heterogeneous Information Speeds: An Agent-Based Modeling Approach

**Author:** Ravilova Arina Kharisovna, Group БПАД246, 2nd year, HSE University (Faculty of Computer Science, Bachelor's Programme "Data Science and Business Analytics")

**Supervisor:** Lukyanchenko Petr Pavlovich, Head of Lab, Faculty of Computer Science, HSE University

**Original codebase:** https://github.com/bognik002/1D-ABM — a 1D agent-based model of a financial market with a centralized limit order book, developed by Bogdan Nikishin. The author's work extends this simulator to study how latency heterogeneity (differences in information/execution speed between traders) affects market stability.

**Research question:** How do differences in the speed of information acquisition by market participants affect the stability of financial markets? Specifically, does a critical proportion of high-frequency traders create a tipping point between normal liquidity and a "toxic" liquidity crisis?

---

## AI Orientation: Read This First

This section is intended for any future AI assistant entering the workspace.

### What this project is

This repository contains an **agent-based financial market simulator** with:
- a centralized limit order book,
- heterogeneous trader types,
- exogenous market shocks,
- experiment scripts studying how speed and information delay affect market stability.

This document is the H1-focused workspace documentation. Its research focus is whether heterogeneous information / execution speed creates a tipping point in post-shock instability.

### Three layers of the codebase

1. **Core engine** — `AgentBasedModel/`
   - order book, traders, events, simulator, metrics
2. **Experiment scripts** — top-level `experiment_*.py`
   - define populations, grids, metrics, plots, CSV output
3. **Outputs / presentation artifacts**
   - raw CSV files, plots, notebook for supervisor discussion

### Current source of truth in this workspace

If you need the **current H1 analysis**, start with:
- `experiment_unified.py`
- `unified_speed_raw.csv`
- `unified_delay_raw.csv`
- `unified_combined_raw.csv`
- `unified_all_raw.csv`
- `documentation.md`

The final rerun of Grid 3 is stored in:
- `unified_combined_raw.csv`
- `unified_all_raw.csv`

The files with `grid3_rerun` in their names belong to an earlier targeted rerun attempt. They are useful as a diagnostic / historical artifact, but they are **not** the final source of truth for Grid 3.

If you need the **best single pre-unified experiment**, use:
- `experiment_h1_v9.py`
- `h1_v9_raw.csv`

If you need the **post-unified follow-up analyses**, use:
- `experiment_threshold_validation.py`
- `experiment_grid3_rerun.py`
- `experiment_grid3_final_plots.py`
- `experiment_speed_delay_mannwhitney.py`
- `experiment_noisy_delay.py`
- `experiment_shock_magnitude.py`

If you need the **presentation / defense artifact**, use:
- `/Users/arinaravilova/Desktop/unified_experiment_talk.ipynb`

### Main parameters and meanings

- `phi` / `hft_frac`
  - share of fast HFT-type chartists among all chartists
  - this is not a share of all agents in the market
  - for example, with 10 chartists, `phi=0.4` means 4 fast chartists and 6 slow chartists
- `speed_multiplier`
  - how many times fast agents act per iteration
  - this models execution-speed advantage as both priority within the iteration and more trading opportunities per iteration
- `info_lag`
  - how many iterations old the visible price/spread information is for delayed agents
  - in the unified experiment, delayed slow chartists also use lagged price changes when updating sentiment
- `vol_ratio`
  - primary instability metric:
    - post-shock volatility divided by pre-shock volatility
- tipping point `phi*`
  - first `phi` where mean `vol_ratio` crosses the chosen threshold
- default threshold in this project
  - `1.3 × baseline`, where baseline = mean `vol_ratio` at `phi=0`

### Experimental logic

- **Grid 1 (speed)**:
  - fixed `info_lag=0`
  - asks whether execution-speed asymmetry destabilizes the market
- **Grid 2 (delay)**:
  - fixed `speed_multiplier=1`
  - asks whether stale information destabilizes the market
- **Grid 3 (combined)**:
  - varies both speed and delay
  - asks whether the speed effect survives when delay is also present
- **Threshold validation**:
  - checks whether `1.3× baseline` is a reasonable tipping-point rule
- **Additional Mann-Whitney analyses**:
  - test speed effect at fixed `phi`
  - test delay effect at fixed `phi`

### Most reliable conclusions currently supported

- strongest H1 support appears at **moderate speed advantage**, especially `speed×2`
- information delay raises baseline instability
- combined speed+delay effects exist, but are **regime-dependent**
- `speed×5` is a **non-monotonic / extreme regime**, not a stronger confirmation of H1
- the final Grid 3 rerun supports a conditional version of H1: latency heterogeneity can create tipping behavior, but not uniformly across all speed and delay regimes

### Important pitfalls

- Early files `experiment_h1_v1-v8.py` are historical and not the final modeling logic.
- The original `Chartist` in `agents.py` is **contrarian**.
- H1-confirming behavior uses `TrendChartist` / `SlowTrendChartist`, defined inside experiment files.
- `general_states()` is unreliable for H1 inference; use direct metrics such as `vol_ratio`.
- Some interpretation files were added later than the original experiments; always distinguish raw simulation output from later presentation artifacts.
- `grid3_rerun_*` files are from an earlier partial targeted rerun and should not be used as the final Grid 3 result.
- The final Grid 3 result is in `unified_combined_raw.csv` and is included in `unified_all_raw.csv`.
- Mann-Whitney tests are one-sided and uncorrected for multiple comparisons; they should be treated as supportive evidence, not as standalone proof.

---

## H1 Hypothesis

### H1: Latency Heterogeneity and the Tipping Point (IMPLEMENTED & TESTED)
An increase in the proportion of high-frequency traders with execution-speed advantage can lead to higher post-shock market volatility and reduced liquidity, exhibiting a non-linear transition beyond a critical threshold `phi*`.

**Status:** Supported, with important regime dependence.

The cleanest support comes from the speed-only unified grid, especially `speed_multiplier=2`, where the 1.3× tipping point appears at `phi*=0.2`. The final combined Grid 3 rerun confirms that speed effects can persist when information delay is also present, especially around `speed×3`, but the effect is not universal across all speed and delay regimes.

The correct interpretation is not "more speed always means more instability." Instead:
- moderate execution-speed advantage can create a tipping point,
- information delay raises baseline instability,
- combined speed+delay effects are regime-dependent,
- extreme `speed×5` produces non-monotonic dynamics and should not be treated as stronger confirmation of H1.

---

## Repository Structure

### Branches

| Branch | Purpose | Key Changes |
|--------|---------|-------------|
| `main` | Original baseline simulator from bognik002/1D-ABM with bug fixes | No HFT modifications. Contains the full ABM framework. |
| `h1-tipping-point` | H1 experiments v1-v6 (failed attempts with contrarian Chartist) | Speed attribute, fast/slow execution split, experiment files v1-v6, h1_description.md |
| `hft-intraiter` | H1 experiments v1-v9 (includes the fix + successful result) | TrendChartist, SlowTrendChartist, simulator_hft.py, experiment v7-v9, final results |

**Active development branch:** `hft-intraiter` (most complete, contains all work)

### Git History (Main Branch — Original Codebase)
```
8a0fb6e Initial commit
4f1b9d3 minor changes
01ae3e3 aggToShock
d0a7f1c states
e86b835 fix MM
83fdbc8 chartist chose price as Random, instead of Exchange.price() +- delta
c29b4ef change strategy bug fix
b54e525 baseline commit
```

### Git History (hft-intraiter — Author's Work)
```
b54e525 baseline commit (branching point)
009a6a5 v1-v6 h1 experiments
45201b0 interim commit
de5edfa H1 v9: TrendChartist + information latency — H1 confirmed for lag=0
d690fd3 Translate Russian plot text to English in experiment_h1 files
cb3937d translate plots
```

---

## File Tree (hft-intraiter branch — most complete)

```
1D-ABM/
├── CLAUDE.md                        # THIS FILE — project documentation
├── documentation.md                 # Human-readable project documentation (this file)
├── main.py                          # Original experiment runner (grid search over trader compositions)
├── baseline_check.py                # Diagnostic: validates baseline behavior without HFT
├── simulator_hft.py                 # Front-running HFT simulator (InterceptingExchange, used in v8 only)
│
├── experiment_h1.py                 # H1 v1: baseline speed experiment
├── experiment_h1_v2.py              # H1 v2: shock magnitude sweep + access asymmetry
├── experiment_h1_v3.py              # H1 v3: new direct metrics (vol_ratio, spread_ratio, etc.)
├── experiment_h1_v4.py              # H1 v4: increased to 30 runs
├── experiment_h1_v5.py              # H1 v5: pure speed effect (access=1 for all)
├── experiment_h1_v6.py              # H1 v6: 2D grid over fast_share x softlimit
├── experiment_h1_v7.py              # H1 v7: declared delayed_price_lag (BUGGY — not passed to simulator)
├── experiment_h1_v8.py              # H1 v8: front-running via InterceptingExchange
├── experiment_h1_v9.py              # H1 v9: TrendChartist fix — H1 CONFIRMED
│
├── experiment_unified.py            # Unified experiment: Grid 1 (speed), Grid 2 (delay), Grid 3 (combined)
├── experiment_threshold_validation.py  # Follow-up: justifies 1.3× baseline tipping threshold
├── experiment_grid3_rerun.py        # Follow-up: targeted Grid 3 rerun with resume support
├── experiment_grid3_final_plots.py  # Follow-up: final Grid 3 plots from unified_combined_raw.csv
├── experiment_speed_delay_mannwhitney.py  # Follow-up: Mann-Whitney tests for speed/delay effects at fixed phi
├── experiment_noisy_delay.py        # Follow-up: information delay only for noisy Random agents
├── experiment_shock_magnitude.py    # Follow-up: robustness of phi* across shock magnitudes
│
├── h1_description.md                # Detailed description of all H1 experiments (Russian)
├── h1_v9_raw.csv                    # Raw results: 1650 simulations
├── h1_v9_results.png                # Aggregated metrics plot (6 panels + heatmap + tipping table)
├── h1_v9_prices.png                 # Price trajectory examples
├── h1_v*_raw.csv                    # Raw results for earlier versions
├── h1_v*_results.png                # Plots for earlier versions
│
├── unified_speed_raw.csv            # Grid 1 raw results (1,320 rows)
├── unified_delay_raw.csv            # Grid 2 raw results (1,650 rows)
├── unified_combined_raw.csv         # Final Grid 3 raw results (2,160 rows)
├── unified_all_raw.csv              # All grids concatenated (5,130 rows; used by follow-up scripts)
├── unified_speed.png                # Grid 1 metrics + sensitivity table
├── unified_delay.png                # Grid 2 metrics + heatmap
├── unified_stats.png                # Mann-Whitney bar plots + sensitivity table
│
├── threshold_validation_summary.csv # Tipping points across thresholds 1.1×–1.5×
├── threshold_validation.png         # Threshold sensitivity line plot
├── threshold_validation_heatmap.png # Threshold sensitivity heatmap
├── threshold_validation_report.md   # Written interpretation of threshold validation
│
├── grid3_rerun_raw.csv              # Grid 3 rerun raw results
├── grid3_rerun_agg.csv              # Grid 3 rerun aggregated
├── grid3_rerun_skips.csv            # Skipped parameter combinations log
├── grid3_rerun.png                  # Grid 3 rerun plot
│
├── speed_effect_mannwhitney.csv     # Mann-Whitney: speed effect at fixed phi
├── delay_effect_mannwhitney.csv     # Mann-Whitney: delay effect at fixed phi
├── speed_effect_mannwhitney.png     # Speed effect plot
├── delay_effect_mannwhitney.png     # Delay effect plot
├── speed_delay_effect_mannwhitney_report.md  # Written interpretation
│
└── AgentBasedModel/                 # Core framework package
    ├── __init__.py                  # Exports all submodules
    ├── agents/
    │   ├── __init__.py
    │   └── agents.py               # ExchangeAgent, Trader, Random, Fundamentalist, Chartist,
    │                                # Universalist, MarketMaker
    ├── simulator/
    │   ├── __init__.py
    │   └── simulator.py            # Simulator, SimulatorInfo (MODIFIED: fast/slow split, mm_panic)
    ├── events/
    │   ├── __init__.py
    │   └── events.py               # MarketPriceShock, FundamentalPriceShock, LiquidityShock,
    │                                # InformationShock, MarketMakerIn/Out, TransactionCost
    ├── states/
    │   ├── __init__.py
    │   └── states.py               # aggToShock, trend, panic, disaster, mean_rev, general_states
    ├── utils/
    │   ├── __init__.py
    │   ├── orders.py               # Order, OrderList (doubly-linked list order book)
    │   └── math.py                 # mean, std, quantile, rolling, difference, aggregate
    └── visualization/
        ├── __init__.py
        ├── market.py               # plot_price, plot_volatility_price, plot_liquidity, etc.
        ├── trader.py               # plot_equity, plot_assets, plot_sentiments, etc.
        └── other.py                # plot_book, print_book (order book visualization)
```

---

## Core Architecture (Original Simulator)

### 1. Exchange Agent and Order Book

**Class: `ExchangeAgent`** (`agents/agents.py`)

The exchange implements a centralized limit order book as two sorted doubly-linked lists (`OrderList`), one for bids and one for asks. Each node is an `Order` object with price, quantity, order type, and a back-reference to the placing trader.

**Initialization:**
- `price=100`: initial stock price
- `std=25`: standard deviation for initial order distribution
- `volume=1000`: number of random orders to populate the book
- `rf=5e-4`: risk-free rate per iteration
- `transaction_cost=0`: fee per trade

**Order Book Population:** V=1000 orders are generated with prices drawn from N(p0-sigma, sigma) for bids and N(p0+sigma, sigma) for asks, quantities uniform [1,5].

**Key Methods:**
- `limit_order(order)`: inserts into book; if price crosses spread, fills against opposite side first
- `market_order(order)`: immediately fills against best available on opposite side
- `cancel_order(order)`: removes from book
- `spread()`: returns `{'bid': best_bid, 'ask': best_ask}`
- `price()`: returns midpoint `(bid + ask) / 2`
- `dividend(access=None)`: returns current dividend or list of n future dividends
- `generate_dividend()`: evolves next dividend via `d_new = d_old * exp(N(0, 5e-3))`

**Order Book Data Structure (`OrderList`):**
- Doubly-linked list maintaining best-offer-first ordering
- Custom `Order` comparison: "less than" = "better offer" regardless of side
- `insert(order)`: O(n) maintains sorted order
- `fulfill(order, t_cost)`: walks from best to worst, matching until filled
- `append/push/remove`: O(1) operations

### 2. Dividend Process

Stochastic multiplicative process:
```
d_{t+1} = max(d_t * exp(epsilon_t), 0),  epsilon ~ N(0, sigma_d^2)
```
where sigma_d = 5e-3. Initial dividend = rf * p0. The exchange maintains a rolling list of 100 pre-generated future dividends. Each iteration consumes one and generates a new one.

### 3. Trading Agents

All agents inherit from **`Trader`** base class:
- Attributes: `cash`, `assets`, `orders` (active orders list), `market` (link to ExchangeAgent)
- Primitives: `_buy_limit(qty, price)`, `_sell_limit(qty, price)`, `_buy_market(qty)`, `_sell_market(qty)`, `_cancel_order(order)`
- `equity()`: returns `cash + assets * market.price()`

#### Random Agent
Simulates background noise/liquidity.
- 15% chance: market order (buy/sell 50/50), qty uniform [1,5]
- 35% chance: limit order at price drawn from `draw_price()`:
  - 35% of time: uniform within spread
  - 65% of time: outside spread by Exp(lambda=1/std) offset
- 35% chance: cancel a random active order

#### Fundamentalist Agent
Trades based on dividend discount valuation.
- `access` parameter: number of future dividends visible (default 1)
- Fundamental price formula:
  ```
  pf = sum(d_i / (1+rf)^i, i=1..n-1) + (d_n / rf) / (1+rf)^(n-1)
  ```
- 55% chance: trade (buy if pf >= ask, sell if pf <= bid, mixed if between)
- 45% chance: cancel first active order
- Quantity: `min(|pf - p| / p / 0.005, 5)` (proportional to mispricing, capped at 5)

#### Chartist Agent
Trades based on sentiment (Optimistic/Pessimistic).
- Optimists buy, Pessimists sell (same market/limit/cancel probabilities as Random)
- **Sentiment switching** via `change_sentiment(info)`:
  ```
  x = (n_optimistic - n_pessimistic) / n_chartists  (sentiment imbalance)
  U = a1 * x + (a2 / v1) * dp / p                   (opinion index)
  ```
  - Optimist -> Pessimist: prob = v1 * (n_chartists/n_traders) * exp(U)
  - Pessimist -> Optimist: prob = v1 * (n_chartists/n_traders) * exp(-U)

**CRITICAL NOTE:** The original sign convention produces CONTRARIAN behavior (price falls -> become optimistic -> buy -> stabilize). This is intentional in the original code but was a problem for H1 testing. See "The Sentiment Bug" section below.

#### Universalist Agent
Multiple inheritance from both Fundamentalist and Chartist.
- Switches between strategies based on utility comparison of fundamental vs. chartist returns
- Executes whichever strategy is currently active

#### MarketMaker Agent
Provides two-sided liquidity within inventory band [-softlimit, +softlimit].
- Each call: cancels all previous orders, then places new bid/ask
- Bid volume: `max(0, ul - 1 - assets)`, Ask volume: `max(0, assets - ll - 1)`
- Inventory-dependent price skew: `delta = -(ask - bid) * assets / softlimit`
- Sets `panic=True` when either volume reaches zero
- **Note:** The rebalancing logic in the panic branch checks for `None` instead of zero, so the market-order rebalancing is never triggered. The panic flag is set but not operationally acted upon. This is a known quirk of the original code.

### 4. Simulation Loop

**Class: `Simulator`** (`simulator/simulator.py`)

Each iteration (of N=500 total):
1. **Events:** check and execute scheduled exogenous events
2. **Capture:** `SimulatorInfo.capture()` records market and agent state
3. **Behavioral update:** Universalists switch strategy, Chartists switch sentiment
4. **Trading:** shuffle all traders, call each agent's `call()` method
5. **Payments:** dividend income (`cash += assets * dividend`) and risk-free interest (`cash += cash * rf`)
6. **Dividend generation:** advance the dividend book

### 5. Events System

Seven event types, each activated at a pre-specified iteration:
- `MarketPriceShock(it, dp)`: shifts all order prices in book by dp
- `FundamentalPriceShock(it, dp)`: adjusts dividend book by dp * rf
- `LiquidityShock(it, dv)`: one-sided market order removing depth
- `InformationShock(it, access)`: changes Fundamentalist/Universalist access parameter
- `MarketMakerIn(it, cash, assets, softlimit)`: adds MarketMaker mid-simulation
- `MarketMakerOut(it)`: removes all MarketMakers
- `TransactionCost(it, cost)`: changes exchange transaction cost

### 6. SimulatorInfo (Data Recording)

**Per-iteration time series:**
- Market: `prices`, `spreads`, `dividends`, `orders` (book depth)
- Per-agent: `equities`, `cash`, `assets`, `types`, `sentiments`, `returns`

**Derived indicators:**
- `stock_returns(roll)`: (p[t+1]-p[t])/p[t] + div[t]/p[t]
- `abnormal_returns(roll)`: returns minus rf
- `return_volatility(window)`: rolling std dev of returns
- `price_volatility(window)`: rolling std dev of prices
- `liquidity(roll)`: (ask-bid)/price
- `fundamental_value(access)`: theoretical fundamental price

### 7. Market State Classification (`states.py`)

- `aggToShock(sim, window, funcs)`: aggregates stats relative to shock timing
- `general_states(info, size, window)`: classifies periods as 'stable', 'trend', 'panic', 'disaster', 'mean-rev'
  - **WARNING:** This function is unreliable — it classifies ~80% of normal operation as 'panic'/'disaster'. Direct metrics (vol_ratio, etc.) should be used instead.

### 8. Visualization (`visualization/`)

- `market.py`: plot_price, plot_price_fundamental, plot_arbitrage, plot_dividend, plot_orders, plot_volatility_price, plot_volatility_return, plot_liquidity
- `trader.py`: plot_equity, plot_cash, plot_assets, plot_strategies, plot_sentiments, plot_returns
- `other.py`: plot_book, print_book

---

## Author's Modifications

### Modification 1: Speed Attribute and Two-Phase Activation

**File:** `simulator/simulator.py` → `Simulator.simulate()`

Replaced the single `random.shuffle(self.traders)` + sequential call with a two-phase loop:

```python
fast = [t for t in self.traders if getattr(t, 'speed', 'slow') == 'fast']
slow = [t for t in self.traders if getattr(t, 'speed', 'slow') != 'fast']

random.shuffle(fast)
for t in fast:
    t.call()

# Optional extra call for fast agents (used in some versions):
if fast_extra_call:
    random.shuffle(fast)
    for t in fast:
        t.call()

random.shuffle(slow)
for t in slow:
    t.call()
```

Agents are tagged with `trader.speed = 'fast'` or `'slow'` when created in experiment files.

### Modification 2: MarketMaker Panic Tracking

**File:** `simulator/simulator.py` → `SimulatorInfo`

Added `self.mm_panic = []` to `__init__`. In `capture()`:
```python
self.mm_panic.append({
    t_id: getattr(t, 'panic', None)
    for t_id, t in self.traders.items()
    if type(t) == MarketMaker
})
```

New method:
```python
def mm_panic_ratio(self, from_it=0) -> float:
    subset = self.mm_panic[from_it:]
    if not subset:
        return 0.0
    return sum(1 for snap in subset if any(snap.values())) / len(subset)
```

### Modification 3: TrendChartist (Corrected Sentiment Logic)

**File:** `experiment_h1_v9.py` (defined inline in the experiment file)

The original `Chartist.change_sentiment()` has **inverted exp() signs** producing contrarian behavior. `TrendChartist` fixes this to produce trend-following behavior:

```python
class TrendChartist(Chartist):
    def change_sentiment(self, info, a1=1, a2=1, v1=0.1):
        # ... compute U = a1*x + a2/v1 * dp/p ...
        if self.sentiment == 'Optimistic':
            prob = v1 * n_chartists / n_traders * exp(-U)  # FIXED: exp(-U) not exp(U)
            # When price falls (dp<0): U<0, exp(-U) large -> flip to Pessimistic -> SELL
            if prob > random.random():
                self.sentiment = 'Pessimistic'
        elif self.sentiment == 'Pessimistic':
            prob = v1 * n_chartists / n_traders * exp(U)   # FIXED: exp(U) not exp(-U)
            # When price rises (dp>0): U>0, exp(U) large -> flip to Optimistic -> BUY
            if prob > random.random():
                self.sentiment = 'Optimistic'
```

**Why this matters:** With the original contrarian Chartist, fast agents STABILIZE the market after a shock (they buy the dip faster). H1 cannot be confirmed with contrarian agents — it's not that the hypothesis is wrong, it's that the agent behavior doesn't match real HFT (which is trend-following per Kirilenko 2017, Zhou 2022).

### Modification 4: SlowTrendChartist (Information Latency)

**File:** `experiment_h1_v9.py`

Same as TrendChartist but reads price change from `lag` iterations ago:

```python
class SlowTrendChartist(TrendChartist):
    def __init__(self, market, cash, assets=0, lag=3):
        super().__init__(market, cash, assets)
        self.lag = lag

    def change_sentiment(self, info, a1=1, a2=1, v1=0.1):
        if self.lag == 0 or len(info.prices) <= self.lag + 1:
            dp = info.prices[-1] - info.prices[-2]
        else:
            dp = info.prices[-1 - self.lag] - info.prices[-2 - self.lag]
        # ... same corrected sign convention as TrendChartist ...
```

This creates a two-wave crash mechanism: fast agents react immediately, slow agents react `lag` iterations later.

### Modification 5: Front-Running Simulator (simulator_hft.py)

**File:** `simulator_hft.py` (NEW file, used only in experiment_h1_v8.py)

Implements `InterceptingExchange` that wraps `ExchangeAgent`:
- When `intercepting=True`: slow traders' orders are buffered in `pending_orders` instead of executing
- Fast traders execute normally against the real book
- Then slow traders' pending orders are flushed (executing at shifted prices)

This simulates real front-running where HFTs see and act on slow traders' order flow before it reaches the book.

---

## The Sentiment Bug — Full Diagnosis

This was the central discovery of the research. Versions 1-8 all failed to confirm H1 because of a sign error in the original `Chartist.change_sentiment()`:

**Original behavior (contrarian):**
```
Price falls (dp < 0) → U < 0 → exp(-U) >> 1 → Pessimists flip to Optimistic → BUY → stabilize
Price rises (dp > 0) → U > 0 → exp(U) >> 1 → Optimists flip to Pessimistic → SELL → stabilize
```

**Consequence for H1:** Fast contrarian chartists REDUCE volatility after a shock — the exact opposite of what H1 predicts. More HFT = faster stabilization = lower vol_ratio. This is exactly what v1-v8 showed: decreasing vol_ratio with increasing phi.

**Fixed behavior (trend-following):**
```
Price falls (dp < 0) → U < 0 → exp(-U) >> 1 → Optimists flip to Pessimistic → SELL → amplify
Price rises (dp > 0) → U > 0 → exp(U) >> 1 → Pessimists flip to Optimistic → BUY → amplify
```

**Note:** This is NOT a bug in the original simulator per se — the original code may have been designed for contrarian chartists. But for modeling HFT behavior, trend-following is correct (per the literature).

---

## H1 Experimental Progression (9 Versions)

### v1: Baseline Speed Experiment
- **Setup:** 10 Fundamentalists + 10 Chartists + 1 MM, 500 iter, 20 runs
- **Speed:** Random agents tagged fast/slow, fast_share varies 0.0-1.0
- **Metric:** `crisis_share` from `general_states()`
- **Result:** No signal. `crisis_share` unreliable (80% baseline flagged as crisis).

### v2: Shock Magnitude Sweep + Information Asymmetry
- **Change:** Grid over shock magnitude dp ∈ {-1,-2,-3,-5,-7,-10} and fast_share. Fast Fundamentalists get access=5, slow get access=1.
- **Total:** 180 simulations
- **Result:** No signal. Speed and information effects confounded.

### v3: New Direct Metrics
- **Change:** Replaced broken `general_states()` with five direct metrics:
  - `vol_ratio` = mean post-shock volatility / mean pre-shock volatility (window=10)
  - `spread_ratio` = mean relative spread after / before
  - `max_drawdown` = (pre_price - min_post_price) / pre_price
  - `recovery_time` = iterations until price within 2% of pre-shock level
  - `mm_panic_ratio` = fraction of post-shock iterations with MM in panic
- **Result:** vol_ratio DECREASING with phi (inverse of H1). Later traced to contrarian sentiment.

### v4: Increased Statistical Power
- **Change:** n_runs 10 → 30 (330 total)
- **Result:** Same inverse trend, now confirmed as robust (not noise).

### v5: Pure Speed Effect Isolation
- **Change:** access=1 for ALL agents. Removes information asymmetry entirely.
- **Result:** Same inverse effect. Pure execution speed with contrarian agents = stabilization.

### v6: MarketMaker Softlimit Grid
- **Change:** 2D grid: fast_share × softlimit ∈ {5,10,20,50,100}, 20 runs
- **Total:** 1,100 simulations
- **Result:** mm_panic depends on softlimit only, not on fast_share. No H1 effect at any softlimit.

### v7: Delayed Price Observation (BUGGY)
- **Change:** Declared `delayed_price_lag` parameter but NEVER PASSED it to the simulator.
- **Result:** Functionally identical to v6. Bug discovered later.

### v8: Front-Running via InterceptingExchange
- **Change:** Uses `simulator_hft.py` with `front_running=True`. Slow orders intercepted.
- **Result:** Front-running intensifies the stabilizing effect — fast contrarian agents stabilize even more efficiently.

### v9: TrendChartist + Information Latency — H1 CONFIRMED
- **Changes:**
  - TrendChartist (corrected exp signs for trend-following)
  - SlowTrendChartist (lagged price observation)
  - Grid: phi ∈ {0.0, 0.1, ..., 1.0} × lag ∈ {0, 1, 3, 5, 10} × 30 runs = 1,650 simulations
  - Removed fast_extra_call (pure execution priority only)
- **Results:**
  - **lag=0:** vol_ratio rises from 1.795 (phi=0) to 2.498 (phi=1), +39%
  - **Tipping point at phi* = 0.4:** vol_ratio = 2.406, first crossing 1.3 × baseline (1.795 × 1.3 = 2.334)
  - Spread ratio +22%, recovery time +70% at phi=1 vs phi=0
  - **lag >= 3:** baseline volatility already elevated (2.33-2.52), HFT effect masked by information delay noise
  - Information delays are themselves an independent source of instability

---

## Stability Metrics — Definitions and Interpretation

### vol_ratio (PRIMARY METRIC)
```python
def vol_ratio(info, shock_it=200, window=10):
    vols = info.price_volatility(window=window)
    pre = vols[:shock_it - window]
    post = vols[shock_it:]
    return mean(post) / (mean(pre) + 1e-9)
```
- 1.0 = no change from shock
- 1.8 = volatility 80% higher after shock
- Used to determine tipping point

### spread_ratio
```python
def spread_ratio(info, shock_it=200):
    def rel(spreads, prices):
        vals = [(s['ask'] - s['bid']) / p for s, p in zip(spreads, prices) if s and p]
        return mean(vals) if vals else 1e-9
    pre = rel(info.spreads[:shock_it], info.prices[:shock_it])
    post = rel(info.spreads[shock_it:], info.prices[shock_it:])
    return post / (pre + 1e-9)
```
- 1.0 = liquidity unchanged
- 2.0 = spread doubled after shock

### max_drawdown
```python
def max_drawdown(info, shock_it=200):
    pre_price = info.prices[shock_it - 1]
    post = info.prices[shock_it:]
    return (pre_price - min(post)) / pre_price
```
- 0.10 = 10% max decline
- 0.20 = 20% max decline

### recovery_time
```python
def recovery_time(info, shock_it=200, threshold=0.02):
    pre_price = info.prices[shock_it - 1]
    for i, p in enumerate(info.prices[shock_it:]):
        if abs(p - pre_price) / pre_price < threshold:
            return i
    return len(info.prices) - shock_it
```
- Iterations until price within 2% of pre-shock level

### mm_panic_ratio
```python
def mm_panic_ratio(info_obj, shock_it=200):
    # from SimulatorInfo.mm_panic_ratio(from_it=shock_it)
```
- Fraction of post-shock iterations where any MM has panic=True

### Tipping Point Detection
```python
def find_tipping_point(agg, lag, col, multiplier=1.3):
    sub = agg[agg['lag'] == lag].sort_values('hft_frac')
    baseline = sub.loc[sub['hft_frac'] == 0.0, col].values[0]
    for _, row in sub.iterrows():
        if row['hft_frac'] == 0.0:
            continue
        if row[col] >= baseline * multiplier:
            return row['hft_frac']
    return None
```

---

## Key Results Table (v9, lag=0)

| phi | vol_ratio | spread_ratio | max_drawdown | recovery_time | mm_panic |
|:---:|:---------:|:------------:|:------------:|:-------------:|:--------:|
| 0.0 | 1.795     | 1.923        | 0.154        | 35.8          | 0.986    |
| 0.2 | 2.161     | 2.231        | 0.157        | 35.8          | 0.925    |
| **0.4** | **2.406** | **2.750** | **0.163**   | **46.8**      | **0.926** |
| 0.6 | 2.464     | 2.695        | 0.147        | 39.8          | 0.927    |
| 0.8 | 1.862     | 2.048        | 0.138        | 18.2          | 0.942    |
| 1.0 | 2.498     | 2.345        | 0.161        | 60.7          | 0.911    |

**Tipping point: phi* = 0.4** (vol_ratio crosses 1.3 × 1.795 = 2.334)

### Cross-Lag Comparison

| lag | baseline vol (phi=0) | vol at phi=1 | change | tipping point |
|:---:|:-------------------:|:------------:|:------:|:-------------:|
| 0   | 1.795               | 2.498        | +39%   | phi = 0.4     |
| 1   | 1.853               | 2.350        | +27%   | —             |
| 3   | 2.330               | 2.415        | +4%    | —             |
| 5   | 2.356               | 2.510        | +7%    | —             |
| 10  | 2.520               | 2.448        | -3%    | —             |

---

## Standard Experimental Configuration

All H1 experiments share these defaults:
- Initial price: p0 = 100
- Order book depth: V = 1000
- Risk-free rate: rf = 5e-4 per iteration
- Population: 10 Fundamentalists + 10 Chartists + 1 MarketMaker
- Horizon: N = 500 iterations
- Shock: `MarketPriceShock(it=200, dp=-10)`
- Runs per parameter combination: 30 (for statistical power)

Experiment-specific parameters:
- `hft_frac` (phi): share of chartists that are fast TrendChartists (0.0 to 1.0 in 0.1 steps)
- `lag`: information delay for SlowTrendChartists (0, 1, 3, 5, 10 iterations)
- `softlimit`: MarketMaker inventory limit (default 100, varied in v6)
- `fast_extra_call`: whether fast agents get an extra trading call per iteration (used in early versions, removed in v9)

---

## Implemented: Unified Experiment (`experiment_unified.py`)

### Modification 6: `speed_multiplier` parameter

**File:** `simulator/simulator.py` → `Simulator.simulate()`

Fast agents now trade `speed_multiplier` times per iteration instead of once:

```python
def simulate(self, n_iter, silent=False, fast_extra_call=False, speed_multiplier=1):
    ...
    for _ in range(speed_multiplier):
        random.shuffle(fast)
        for trader in fast:
            trader.call()
    ...
```

### Modification 7: Delayed order book information

**File:** `agents/agents.py`

`ExchangeAgent` now stores a sliding window of 20 historical spread/price snapshots:
- `record_state()`: called each iteration before trading, snapshots current spread and price
- `delayed_spread(lag)`: returns spread from `lag` iterations ago
- `delayed_price(lag)`: returns price from `lag` iterations ago

`Trader` base class now has `info_lag` parameter (default 0) and methods:
- `_get_spread()`: returns delayed spread if `info_lag > 0`, else real-time
- `_get_price()`: returns delayed price if `info_lag > 0`, else real-time

`Chartist.call()` and `Fundamentalist.call()` use `_get_spread()` / `_get_price()` instead of direct calls.

All agent constructors accept `info_lag=0` and pass it through to `Trader.__init__`. Backward compatible.

### Modification 8: Empty order book protection

At high `speed_multiplier` (≥2), fast agents can exhaust the order book entirely. Added `try/except` and `None` checks throughout the codebase. Also added `U = max(-50, min(50, U))` clamping in TrendChartist/SlowTrendChartist to prevent `OverflowError` from `exp()`.

### Three experimental grids

- **Grid 1 (Speed):**
  - `speed_multiplier ∈ {1, 2, 3, 5}`
  - `hft_frac ∈ {0.0, 0.1, ..., 1.0}`
  - `info_lag = 0`
  - `30 runs` per parameter combination
  - total: `4 × 11 × 30 = 1,320` simulations
- **Grid 2 (Delay):**
  - `info_lag ∈ {0, 1, 3, 5, 10}`
  - `hft_frac ∈ {0.0, 0.1, ..., 1.0}`
  - `speed_multiplier = 1`
  - `30 runs` per parameter combination
  - total: `5 × 11 × 30 = 1,650` simulations
- **Grid 3 (Combined, final rerun):**
  - `speed_multiplier ∈ {2, 3, 5}`
  - `info_lag ∈ {1, 3, 5, 10}`
  - `hft_frac ∈ {0.0, 0.2, 0.4, 0.6, 0.8, 1.0}`
  - `30 runs` per parameter combination
  - total: `3 × 4 × 6 × 30 = 2,160` simulations
- **Total unified raw simulations:** `1,320 + 1,650 + 2,160 = 5,130` rows in `unified_all_raw.csv`

Note: when grouping `unified_all_raw.csv`, always include the `grid` column. Some parameter combinations, especially `speed_multiplier=1, info_lag=0`, appear in both Grid 1 and Grid 2 and therefore have 60 rows if grouped without `grid`.

### Statistical methods

- **Mann-Whitney U test** (non-parametric): pairwise comparison of vol_ratio at φ=0 vs each φ, one-sided, p < 0.05
- **Bootstrap 95% CI** (1000 resamples): used on metric plots
- **Sensitivity analysis**: tipping point at thresholds 1.1×–1.5×

### Output files

| File | Contents |
|------|----------|
| `unified_speed_raw.csv` | Grid 1 raw results, 1,320 rows |
| `unified_delay_raw.csv` | Grid 2 raw results, 1,650 rows |
| `unified_combined_raw.csv` | Final Grid 3 raw results, 2,160 rows |
| `unified_all_raw.csv` | All unified grids concatenated, 5,130 rows |
| `unified_speed.png` | Grid 1 metrics + sensitivity table |
| `unified_delay.png` | Grid 2 metrics + heatmap |
| `unified_stats.png` | Mann-Whitney bar plots + sensitivity table |

---

## Unified Experiment Results

### Main result: strongest support at moderate speed advantage

| speed_mult | baseline vol (φ=0) | max vol | tipping (1.3×) | p-value at tipping |
|:---:|:---:|:---:|:---:|:---:|
| 1 | 2.123 | 3.264 (φ=0.6) | φ=0.6 | p=0.033 * |
| **2** | **1.746** | **3.392 (φ=0.4)** | **φ=0.2** | p=0.002 ** |
| 3 | 2.051 | 3.401 (φ=0.9) | φ=0.3 | p=0.034 * |
| 5 | 2.467 | 2.746 (φ=0.1) | — | n.s. |

**Interpretation:** the unified experiment does **not** support a monotone "more speed = more instability" claim. The strongest and cleanest H1 support appears at **moderate speed advantage**, especially `speed×2`. `speed×3` remains supportive but noisier. `speed×5` breaks the original tipping pattern.

### Mann-Whitney U results (speed×2)

| φ | baseline | treatment | U | p-value | sig |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 0.1 | 1.746 | 2.224 | 316 | 0.024 | * |
| 0.2 | 1.746 | 2.541 | 256 | 0.002 | ** |
| 0.4 | 1.746 | 3.392 | 162 | <0.0001 | *** |
| 0.5 | 1.746 | 3.142 | 223 | 0.0004 | *** |
| 0.6 | 1.746 | 2.970 | 275 | 0.005 | ** |
| 1.0 | 1.746 | 2.933 | 253 | 0.002 | ** |

### Sensitivity analysis (speed×2)

| Threshold | Tipping point φ* |
|:---:|:---:|
| 1.1× | 0.1 |
| 1.2× | 0.1 |
| 1.3× | 0.2 |
| 1.4× | 0.2 |
| 1.5× | 0.4 |

### Final Grid 3 rerun: combined speed + delay experiment

The combined experiment answers the supervisor's specific question: **is there a regime where information delay and speed multiplier are present simultaneously?** Yes — this is Grid 3.

The final Grid 3 rerun is stored in `unified_combined_raw.csv` and included in `unified_all_raw.csv`. This rerun replaced the earlier partial `grid3_rerun_*` attempt as the source of truth for the combined regime.

The final combined grid is complete:
- `speed_multiplier ∈ {2, 3, 5}`
- `info_lag ∈ {1, 3, 5, 10}`
- `hft_frac ∈ {0.0, 0.2, 0.4, 0.6, 0.8, 1.0}`
- `30 runs` per combination
- total: `2,160` successful simulations
- every parameter combination has exactly 30 runs

The earlier files:
- `grid3_rerun_raw.csv`
- `grid3_rerun_agg.csv`
- `grid3_rerun_skips.csv`
- `grid3_rerun.png`

belong to a previous targeted rerun attempt. That attempt was useful for debugging and partial verification, but it remained incomplete in the heaviest regimes. It should be treated as a historical diagnostic artifact, not as the final Grid 3 dataset.

#### Grid 3 results

| speed_mult | info_lag | baseline vol_ratio at phi=0 | 1.3× threshold | tipping point phi* | Interpretation |
|---:|---:|---:|---:|---:|---|
| 2 | 1 | 2.347 | 3.050 | 1.0 | effect appears only at full HFT share |
| 2 | 3 | 2.596 | 3.375 | 1.0 | delay raises baseline; tipping only at full HFT share |
| 2 | 5 | 2.340 | 3.042 | 0.4 | clear combined-regime tipping point |
| 2 | 10 | 2.366 | 3.076 | 0.8 | delayed but visible tipping |
| 3 | 1 | 2.178 | 2.831 | 0.2 | strongest combined-regime support |
| 3 | 3 | 2.141 | 2.783 | 0.4 | combined effect persists |
| 3 | 5 | 2.700 | 3.510 | — | high baseline masks the HFT tipping effect |
| 3 | 10 | 2.238 | 2.910 | 0.4 | combined effect reappears |
| 5 | 1 | 2.640 | 3.432 | — | extreme speed regime, non-monotonic |
| 5 | 3 | 2.777 | 3.610 | — | extreme speed regime, no 1.3× tipping |
| 5 | 5 | 2.526 | 3.284 | — | extreme speed regime, no 1.3× tipping |
| 5 | 10 | 2.466 | 3.206 | 0.4 | local crossing, but still non-monotonic overall |

#### Interpretation

The final Grid 3 rerun shows that the combined effect of execution speed and information delay is **real but regime-dependent**.

The strongest combined-regime support appears around `speed×3`:
- at `lag=1`, tipping occurs already at `phi*=0.2`
- at `lag=3`, tipping occurs at `phi*=0.4`
- at `lag=10`, tipping occurs at `phi*=0.4`

This means that the speed effect does survive in the presence of information delay, but only in part of the parameter space.

At the same time, Grid 3 does **not** support a simple monotone claim that more speed always produces more instability. In particular, `speed×5` behaves as an extreme regime. The volatility curve becomes non-monotonic, and the 1.3× tipping rule usually does not detect a stable tipping point. This should be interpreted as a different microstructure regime rather than as stronger confirmation of H1.

The most defensible conclusion is:

> Latency heterogeneity can generate post-shock instability and tipping behavior, especially under moderate execution-speed advantage. However, the combined speed-delay effect is conditional on the microstructure regime. Information delay raises baseline instability, and extreme speed advantage can produce non-monotonic dynamics rather than a clean tipping pattern.

Therefore, Grid 3 should be presented as a robustness / interaction experiment. It strengthens H1 by showing that speed effects can persist when information delay is also present, but it also narrows the hypothesis: the effect is not universal across all speed and delay combinations.

### Five conclusions

1. **Strongest H1 support at speed×2.** This is the cleanest tipping-point regime in the unified experiment.
2. **Tipping point at φ*=0.2 (speed×2, 1.3×).** Robust across thresholds (φ=0.1–0.4).
3. **Non-monotonic effect of speed.** At speed×5 the original tipping pattern collapses; the most plausible interpretation is aggressive liquidity depletion / partial order-book exhaustion rather than improved market health.
4. **Information delay is an independent instability source.** Baseline vol_ratio rises as lag increases, even at φ=0.
5. **Combined regimes are conditional, not universal.** Speed + delay can generate tipping points, but their location depends on the exact microstructure regime.

---

## Post-Unified Follow-Up Work (current workspace)

After `experiment_unified.py` was completed, several follow-up scripts and presentation materials were added to strengthen interpretation and defense.

### Follow-up 1: Threshold validation (`experiment_threshold_validation.py`)

Purpose:
- justify the use of the `1.3× baseline` rule as the main working tipping-point threshold,
- without rerunning the full simulation,
- by reusing `unified_all_raw.csv`.

Method:
- choose several representative regimes,
- recompute tipping point `φ*` under thresholds `1.1×, 1.2×, 1.3×, 1.4×, 1.5×`,
- compare how stable the estimated tipping region remains.

Representative regimes used:
- `speed_x2` — cleanest speed-only regime
- `combined_speed_x3_lag1` — strong combined regime
- `combined_speed_x3_lag5` — combined regime where 1.3× tipping disappears

Main result:

| Regime | 1.1× | 1.2× | 1.3× | 1.4× | 1.5× |
|---|---:|---:|---:|---:|---:|
| `speed_x2` | 0.1 | 0.1 | 0.2 | 0.2 | 0.4 |
| `combined_speed_x3_lag1` | 0.2 | 0.2 | 0.2 | 0.2 | 0.6 |
| `combined_speed_x3_lag5` | 0.6 | 0.6 | — | — | — |

Interpretation:
- `1.1×` and `1.2×` are too soft: crossings often happen very early
- `1.5×` is too strict: meaningful regimes can lose tipping points entirely
- `1.3×` is **not mathematically unique**, but is a reasonable **common working threshold**

Output files:
- `threshold_validation_summary.csv`
- `threshold_validation.png`
- `threshold_validation_heatmap.png`
- `threshold_validation_report.md`

### Follow-up 2: Final Grid 3 rerun and historical targeted rerun

The final Grid 3 rerun is now part of the unified experiment outputs:
- `unified_combined_raw.csv`
- `unified_all_raw.csv`

Purpose of the final rerun:
- recompute the full combined grid after stabilizing the simulation pipeline,
- include `speed_multiplier ∈ {2, 3, 5}`,
- include `info_lag ∈ {1, 3, 5, 10}`,
- keep `30 runs` per parameter combination,
- make Grid 3 directly comparable with Grid 1 and Grid 2 inside `unified_all_raw.csv`.

Final status:
- `unified_combined_raw.csv` contains `2,160` successful simulations,
- every Grid 3 parameter combination has exactly `30` runs,
- this is the final source of truth for the combined speed+delay experiment.

#### Historical note: earlier targeted Grid 3 rerun (`experiment_grid3_rerun.py`)

Before the final unified Grid 3 rerun, a separate targeted rerun script was created:
- `experiment_grid3_rerun.py`
- `grid3_rerun_raw.csv`
- `grid3_rerun_agg.csv`
- `grid3_rerun_skips.csv`
- `grid3_rerun.png`

Its purpose was to recompute only selected combined regimes with resume support and skip logging. This was useful while diagnosing long-running / timeout-prone combinations.

However, this earlier targeted rerun is **not** the final combined-grid result. It remained partial in the heaviest regimes, especially around `speed×3, lag=5`.

The final source of truth is now:
- `unified_combined_raw.csv`
- `unified_all_raw.csv`

The `grid3_rerun_*` files should be kept only as a historical diagnostic artifact.

### Follow-up 3: Additional Mann-Whitney analyses (`experiment_speed_delay_mannwhitney.py`)

Purpose:
- extend the original Mann-Whitney logic beyond "baseline φ=0 vs each φ"
- separately test:
  1. **effect of speed at fixed φ**
  2. **effect of delay at fixed φ**

This answers two additional questions:
- Does increasing `speed_multiplier` shift the `vol_ratio` distribution upward at a fixed HFT share?
- Does increasing `info_lag` shift the `vol_ratio` distribution upward at a fixed HFT share?

Outputs:
- `speed_effect_mannwhitney.csv`
- `delay_effect_mannwhitney.csv`
- `speed_effect_mannwhitney.png`
- `delay_effect_mannwhitney.png`
- `speed_delay_effect_mannwhitney_report.md`

### Follow-up 4: Noisy-agent information delay experiment (`experiment_noisy_delay.py`)

This experiment was proposed to isolate whether information delay among noisy / random traders is an independent source of instability.

In the unified experiment, `info_lag` is applied to slow informed / behavioral traders:
- slow chartists use lagged price changes in sentiment updating,
- slow chartists and fundamentalists use delayed spread/price information in order placement.

The noisy-delay experiment changes this design:
- `TrendChartist` agents work without information delay,
- `Fundamentalist` agents work without information delay,
- `MarketMaker` works without information delay,
- only noisy `Random` agents receive delayed spread information.

#### Important implementation detail

The base `Random.call()` method in `AgentBasedModel/agents/agents.py` uses `self.market.spread()` directly. Therefore, simply passing `info_lag` to `Random` would not actually delay its visible spread.

For this experiment, the script defines a local `DelayedRandom(Random)` subclass. It keeps the same random trading probabilities as the original `Random` agent, but replaces direct spread access with `_get_spread()`. This makes the delay operational only for noisy agents.

#### Scientific purpose

The goal is to separate two mechanisms:
- instability caused by delayed trend-following / informed behavioral agents,
- instability caused by stale noisy order placement.

If volatility rises when only noisy agents are delayed, then noisy-trader information delay is an independent instability channel. If the effect is weak or absent, then the stronger delay effects in the unified experiment are likely driven mainly by `SlowTrendChartist` and delayed `Fundamentalist` behavior.

#### Experimental design

- Population:
  - 10 chartists,
  - 10 fundamentalists,
  - 5 noisy random agents,
  - 1 market maker.
- `hft_frac` / `phi`:
  - share of chartists marked as fast HFT-type trend chartists,
  - `phi ∈ {0.0, 0.1, ..., 1.0}`.
- `info_lag`:
  - applied only to `DelayedRandom` agents,
  - `lag ∈ {0, 1, 3, 5, 10}`.
- Fast chartists:
  - use `TrendChartist`,
  - `speed='fast'`,
  - no information delay.
- Slow chartists:
  - also use `TrendChartist`,
  - `speed='slow'`,
  - no information delay.
- Fundamentalists:
  - `info_lag=0`,
  - no delayed information.
- Random agents:
  - use `DelayedRandom`,
  - `info_lag=lag`.
- Simulation setup:
  - `N=500` iterations,
  - shock at `it=200`,
  - `MarketPriceShock(200, -10)`,
  - `30 runs` per parameter combination.
- Total:
  - `11 phi values × 5 lag values × 30 runs = 1,650` simulations.

#### Metrics

The experiment uses the same H1 metrics as the unified experiment:
- `vol_ratio`,
- `spread_ratio`,
- `max_drawdown`,
- `recovery_time`,
- `mm_panic_ratio`.

#### Output files

Outputs:
- `noisy_delay_raw.csv` — raw simulation results,
- `noisy_delay_agg.csv` — aggregated results,
- `noisy_delay_tipping.csv` — tipping-point summary,
- `noisy_delay_metrics.png` — multi-metric line plots with bootstrap CI,
- `noisy_delay_heatmap.png` — heatmap of mean `vol_ratio`.

#### Results

The experiment completed successfully:
- total rows in `noisy_delay_raw.csv`: `1,650`,
- parameter combinations: `5 lag values × 11 phi values = 55`,
- every parameter combination has exactly `30` runs,
- `speed_mult=1` throughout, matching the v9 priority-only speed setup.

Tipping-point summary:

| noisy info_lag | baseline vol_ratio at phi=0 | 1.3× threshold | max vol_ratio | phi at max | phi_star |
|---:|---:|---:|---:|---:|---:|
| 0 | 1.931 | 2.510 | 2.197 | 1.0 | — |
| 1 | 2.188 | 2.845 | 2.440 | 0.7 | — |
| 3 | 2.454 | 3.190 | 2.454 | 0.0 | — |
| 5 | 2.202 | 2.862 | 2.437 | 0.7 | — |
| 10 | 2.535 | 3.296 | 2.552 | 0.3 | — |

Mean `vol_ratio` by noisy-agent lag and HFT fraction:

| info_lag | phi=0.0 | phi=0.1 | phi=0.2 | phi=0.3 | phi=0.4 | phi=0.5 | phi=0.6 | phi=0.7 | phi=0.8 | phi=0.9 | phi=1.0 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 1.931 | 2.116 | 2.148 | 2.029 | 2.082 | 1.843 | 1.936 | 1.884 | 2.055 | 1.940 | 2.197 |
| 1 | 2.188 | 2.358 | 1.963 | 2.182 | 1.728 | 2.005 | 2.279 | 2.440 | 2.051 | 2.001 | 2.031 |
| 3 | 2.454 | 2.102 | 2.257 | 2.216 | 2.055 | 2.111 | 2.115 | 1.989 | 1.919 | 2.060 | 2.424 |
| 5 | 2.202 | 2.223 | 2.188 | 2.030 | 1.984 | 2.360 | 2.130 | 2.437 | 2.430 | 2.079 | 2.012 |
| 10 | 2.535 | 2.114 | 2.149 | 2.552 | 2.219 | 2.516 | 2.453 | 1.964 | 2.336 | 2.135 | 1.842 |

#### Interpretation

This experiment should not be interpreted as a replacement for the unified delay grid. It is a mechanism-isolation experiment.

The main result is negative but informative: noisy-agent information delay does **not** generate a systematic HFT-share tipping point.

For every noisy lag value, `phi_star` is absent under the `1.3× baseline` rule. In other words, increasing the share of fast chartists does not push `vol_ratio` above the tipping threshold when the only delayed agents are noisy Random agents.

The experiment does show some local increases in volatility:
- `lag=1` reaches its maximum at `phi=0.7`,
- `lag=5` reaches its maximum at `phi=0.7`,
- `lag=10` reaches its maximum at `phi=0.3`.

However, these increases are not monotonic in `phi`, do not cross the 1.3× threshold, and do not form a robust tipping pattern. At `lag=3`, the maximum `vol_ratio` is already at `phi=0.0`, which indicates that the higher baseline instability is not caused by a growing HFT share.

The correct conclusion is:

> Stale information among noisy Random agents alone is not enough to produce the H1 tipping mechanism. It may change the noise/liquidity background and raise volatility in some local regimes, but the strong delay effects in the unified experiment are more likely driven by delayed trend-following chartists and delayed fundamentalist order placement.

#### Limitation

The delay in this experiment affects noisy agents' limit-order pricing through delayed spread information. Market orders still execute against the current order book, because market orders in this simulator do not choose a price from observed spread information. This is consistent with the intended mechanism-isolation design: the experiment tests stale noisy order placement, not delayed execution.

### Follow-up 5: Shock magnitude robustness experiment (`experiment_shock_magnitude.py`)

This experiment was proposed to test whether the estimated HFT tipping point is robust to the size of the exogenous market shock.

In the main unified experiment, the standard shock is:
- `MarketPriceShock(it=200, dp=-10)`.

The shock-magnitude experiment keeps the clean no-delay configuration and varies only the shock size:
- `info_lag = 0`,
- `shock_dp ∈ {-0.5, -1, -2, -5, -10}`,
- `hft_frac ∈ {0.0, 0.1, ..., 1.0}`.

#### Scientific purpose

The goal is to determine whether the tipping point is a property of the market microstructure or mostly an artifact of a specific shock magnitude.

Key question:

> Does `phi*` remain near the same HFT share when the shock becomes weaker or stronger?

If `phi*` is stable across shock magnitudes, then the tipping point can be interpreted as a robust market-structure threshold. If `phi*` moves substantially with `shock_dp`, then the result should be interpreted as shock-size-dependent.

#### Experimental design

- Population:
  - 10 chartists,
  - 10 fundamentalists,
  - 5 random agents,
  - 1 market maker.
- Chartists:
  - use `TrendChartist`,
  - fast chartists have `speed='fast'`,
  - slow chartists have `speed='slow'`,
  - no information delay.
- Fundamentalists:
  - `access=1`,
  - no information delay.
- Random agents:
  - no information delay.
- MarketMaker:
  - `softlimit=100`.
- Shock:
  - `MarketPriceShock(it=200, dp=shock_dp)`.
- Simulation:
  - `N=500` iterations,
  - `30 runs` per parameter combination.

Default script configuration:
- `speed_multiplier=2`, matching the cleanest unified speed-grid result where `phi*=0.2`.

For direct v9-style comparison, run the same script with:
- `--speed-multiplier 1`.

#### Grid size

Default grid:
- `5 shock magnitudes × 11 phi values × 30 runs = 1,650` simulations.

#### Metrics

The experiment uses the same H1 metrics:
- `vol_ratio`,
- `spread_ratio`,
- `max_drawdown`,
- `recovery_time`,
- `mm_panic_ratio`.

#### Output files

Outputs:
- `shock_magnitude_raw.csv` — raw simulation results,
- `shock_magnitude_agg.csv` — aggregated results,
- `shock_magnitude_tipping.csv` — tipping-point summary by shock magnitude,
- `shock_magnitude_metrics.png` — multi-metric line plots with bootstrap CI,
- `shock_magnitude_heatmap.png` — heatmap of mean `vol_ratio`.

#### Results

The experiment completed successfully:
- total rows in `shock_magnitude_raw.csv`: `1,650`,
- parameter combinations: `5 shock magnitudes × 11 phi values = 55`,
- every parameter combination has exactly `30` runs,
- `info_lag=0` throughout,
- `speed_mult=2` throughout.

The tested shock values are weaker versions of the original `dp=-10` benchmark plus the benchmark itself. The experiment does **not** test more extreme shocks such as `dp=-15` or `dp=-20`; those would be a separate catastrophic-shock regime.

Tipping-point summary:

| shock_dp | speed_mult | baseline vol_ratio at phi=0 | 1.3× threshold | phi_star | max vol_ratio | phi at max |
|---:|---:|---:|---:|---:|---:|---:|
| -0.5 | 2 | 1.726 | 2.244 | 0.4 | 3.186 | 1.0 |
| -1.0 | 2 | 1.726 | 2.244 | 0.4 | 3.173 | 0.9 |
| -2.0 | 2 | 1.761 | 2.289 | 0.3 | 3.136 | 1.0 |
| -5.0 | 2 | 1.991 | 2.588 | 0.7 | 3.260 | 0.8 |
| -10.0 | 2 | 2.312 | 3.006 | 0.5 | 3.722 | 0.9 |

Mean `vol_ratio` by shock magnitude and HFT fraction:

| shock_dp | phi=0.0 | phi=0.1 | phi=0.2 | phi=0.3 | phi=0.4 | phi=0.5 | phi=0.6 | phi=0.7 | phi=0.8 | phi=0.9 | phi=1.0 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| -10.0 | 2.312 | 2.493 | 1.991 | 2.239 | 2.576 | 3.039 | 2.699 | 3.245 | 2.577 | 3.722 | 3.353 |
| -5.0 | 1.991 | 1.971 | 2.485 | 2.548 | 2.242 | 2.329 | 2.436 | 2.765 | 3.260 | 3.007 | 2.579 |
| -2.0 | 1.761 | 1.988 | 1.797 | 2.380 | 2.081 | 2.578 | 2.813 | 2.737 | 2.429 | 2.957 | 3.136 |
| -1.0 | 1.726 | 1.868 | 1.893 | 1.843 | 2.777 | 2.114 | 2.482 | 2.601 | 3.120 | 3.173 | 3.067 |
| -0.5 | 1.726 | 1.746 | 1.962 | 2.190 | 2.374 | 2.630 | 2.284 | 2.914 | 2.827 | 2.632 | 3.186 |

#### Interpretation

This is a robustness experiment, not a new mechanism. The main interpretation is based on the movement of `phi*`:
- stable `phi*`: tipping point is relatively robust to shock size,
- lower `phi*` for stronger shocks: large shocks make the market more fragile,
- absent `phi*` for weak shocks: the HFT tipping mechanism may require a sufficiently large external disturbance,
- highly non-monotonic `phi*`: tipping behavior is sensitive to the interaction between shock size and endogenous liquidity.

The main result is that the tipping effect appears across all tested shock magnitudes, but the exact tipping point is not invariant.

Observed `phi_star` values:
- `dp=-0.5`: `phi*=0.4`,
- `dp=-1`: `phi*=0.4`,
- `dp=-2`: `phi*=0.3`,
- `dp=-5`: `phi*=0.7`,
- `dp=-10`: `phi*=0.5`.

This supports the robustness of the HFT-instability mechanism in a limited sense: it is not an artifact of a single chosen shock size. Even weak shocks such as `dp=-0.5` and `dp=-1` produce a tipping point under the 1.3× baseline rule.

However, the location of the tipping point shifts with shock magnitude. Therefore, `phi*` should not be presented as a universal constant. It is a regime-dependent estimate that depends on the size of the external shock and the baseline instability it creates.

The non-monotonic movement of `phi*` is expected under a relative threshold rule. Stronger shocks increase post-shock instability even when `phi=0`, which raises the baseline and therefore also raises the `1.3× baseline` threshold. For example:
- at `dp=-0.5`, baseline `vol_ratio=1.726` and threshold `=2.244`,
- at `dp=-10`, baseline `vol_ratio=2.312` and threshold `=3.006`.

Thus, a stronger shock does not necessarily produce a lower `phi*`, because the benchmark market without HFT is also more unstable.

The correct conclusion is:

> The HFT-related tipping effect is robust across the tested shock magnitudes, but the exact value of `phi*` is shock-size-dependent. The tipping point should be interpreted as a regime-dependent threshold rather than a fixed structural constant.

### Follow-up 6: Presentation notebook (`/Users/arinaravilova/Desktop/unified_experiment_talk.ipynb`)

Purpose:
- convert raw results into a supervisor-facing discussion notebook
- provide:
  - one section per grid
  - graphical interpretation
  - explanation of threshold choice
  - explanation of Mann-Whitney U test
  - a compact oral script for live discussion

This notebook is a presentation artifact, not part of the simulation pipeline.

### Technical fix: plotting bug in `experiment_unified.py`

During plotting, a `KeyError: 'drawdown'` was discovered.

Cause:
- aggregated columns used names like `drawdown_mean`
- raw CSV stores the underlying column as `max_drawdown`

Fix:
- plotting code now uses an explicit raw metric map:
  - `drawdown_mean -> max_drawdown`
  - `recovery_mean -> recovery_time`
  - `mm_panic_mean -> mm_panic_ratio`

Interpretation:
- the original unified experiment results were already computed correctly
- the error affected only the plotting stage, not the simulation results themselves

---

## Important Conventions and Pitfalls

1. **Agent classes defined in experiment files, not in agents.py.** TrendChartist and SlowTrendChartist are defined inline in `experiment_h1_v9.py`, not in the core `agents/agents.py`. This was a deliberate choice to avoid modifying the original codebase.

2. **`general_states()` is unreliable.** It classifies ~80% of baseline (no-shock) time as 'panic'/'disaster'. Always use direct metrics (vol_ratio, spread_ratio, etc.) instead.

3. **The original Chartist is CONTRARIAN.** This is by design in the original code (bognik002). For HFT modeling, use TrendChartist (corrected signs). Do not "fix" the original Chartist — it may be needed for other experiments.

4. **MarketMaker panic flag is diagnostic only.** The panic-triggered rebalancing logic in the original code never fires because it checks for `None` instead of zero.

5. **experiment_h1_v7.py has a bug** — the `delayed_price_lag` parameter is declared but never passed to the simulator. It's functionally identical to v6.

6. **simulator_hft.py is separate from simulator.py.** It has its own Simulator class with front-running logic. Only used in experiment_h1_v8.py.

7. **All experiment files are standalone scripts.** Each experiment_h1_v*.py file contains its own population setup, grid, run loop, metrics, and plotting. They import from AgentBasedModel but are self-contained.

8. **The speed attribute is ad-hoc.** It's set via `trader.speed = 'fast'` after construction, not as a constructor parameter. The simulator checks it with `getattr(t, 'speed', 'slow')`.

9. **CSV column names vary between versions.** v1-v2 use `fast_share`, v3+ use `hft_frac`. Some versions have `dp` (shock magnitude), `softlimit`, `lag` columns depending on the grid.

10. **Plots have been translated to English** in the latest commits on both experiment branches. Earlier commits have Russian plot labels.

---

## How to Run

```python
# Basic simulation (original baseline)
from AgentBasedModel import *
exchange = ExchangeAgent(volume=1000)
traders = [
    *[Random(exchange, 10**3) for _ in range(5)],
    *[Fundamentalist(exchange, 10**3) for _ in range(10)],
    *[Chartist(exchange, 10**3) for _ in range(10)],
    MarketMaker(exchange, 10**3, softlimit=100)
]
sim = Simulator(exchange=exchange, traders=traders, events=[MarketPriceShock(200, -10)])
sim.simulate(500)
plot_price(sim.info)

# H1 experiment v9 (latest)
python experiment_h1_v9.py  # Runs full grid, outputs h1_v9_raw.csv and plots
```

---

## References (from the paper)

[1] Easley, López de Prado, O'Hara (2011) — Flow Toxicity and Flash Crash
[2] Easley, López de Prado, O'Hara (2012) — Flow Toxicity in HF World
[4] Johnson et al. (2013) — Machine ecology beyond human response time
[5] Kirilenko et al. (2017) — Flash Crash: HFT in Electronic Markets
[6] Bookstaber & Paddrik (2015) — ABM for Crisis Liquidity Dynamics
[7] Wah & Wellman (2016) — Latency Arbitrage in Fragmented Markets
[8] Zhou, Zhong, Li (2022) — Stability driven by information delay and liquidity
[9] Brunnermeier & Pedersen (2005) — Predatory Trading
[10] Carlin, Lobo, Viswanathan (2007) — Episodic Liquidity Crises
[11] Budish, Cramton, Shim (2015) — Frequent Batch Auctions
[12] Biais, Foucault, Moinas (2015) — Equilibrium Fast Trading
[13] Menkveld & Zoican (2017) — Exchange Latency and Liquidity
[14] Kirman & Teyssière (2002) — Bubbles and Crashes ABM
[15] IOSCO (2011) — Market Integrity and Technological Changes
[16] CFTC & SEC (2010) — Findings on May 6, 2010 Market Events
