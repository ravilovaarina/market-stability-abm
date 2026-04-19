# 1D-ABM Baseline Simulator Documentation

## Purpose of This Document

This document describes the **original baseline simulator** that exists on the current branch.
At the moment of writing, the current Git branch is `main`, and this branch contains only the
base 1D-ABM implementation:

- no HFT speed split,
- no `speed_multiplier`,
- no delayed order-book information,
- no event-time / volume-clock loop,
- no H1/H2/H3 experiment scripts.

The goal of this document is to make the baseline architecture fully explicit before adding
new hypothesis-specific modifications. This is especially important for H2, because the event-time
experiment should be built from the clean original simulator rather than from the already modified
H1 branch.

---

## Project Context

The repository implements a one-dimensional agent-based model of a financial market.
The model has:

- a centralized limit order book,
- heterogeneous trading agents,
- stochastic dividends,
- exogenous intervention events,
- a fixed-iteration simulation loop,
- data recording and plotting utilities.

The intended research topic, according to `paper_full.pdf` / `paper_full.tex`, is:

> Financial Market Stability under Heterogeneous Information Speeds: An Agent-Based Modeling Approach.

The broad research question is:

> How do differences in information and execution speed among market participants affect market
> stability, market liquidity, and crisis dynamics?

The paper is organized around three hypotheses:

1. **H1: Latency heterogeneity and tipping point.**
2. **H2: Calendar time versus event time.**
3. **H3: Information delay, liquidity constraints, and volatility clustering.**

This branch is the clean baseline from which those experimental branches should be derived.

---

## Repository Structure on This Branch

```text
1D-ABM/
├── main.py
├── requirements.txt
├── documentation.md
└── AgentBasedModel/
    ├── __init__.py
    ├── agents/
    │   ├── __init__.py
    │   └── agents.py
    ├── simulator/
    │   ├── __init__.py
    │   └── simulator.py
    ├── events/
    │   ├── __init__.py
    │   └── events.py
    ├── states/
    │   ├── __init__.py
    │   └── states.py
    ├── utils/
    │   ├── __init__.py
    │   ├── math.py
    │   └── orders.py
    └── visualization/
        ├── __init__.py
        ├── market.py
        ├── trader.py
        └── other.py
```

### Main layers

The codebase has four conceptual layers:

1. **Market microstructure layer**
   - `Order`
   - `OrderList`
   - `ExchangeAgent`

2. **Agent layer**
   - `Trader`
   - `Random`
   - `Fundamentalist`
   - `Chartist`
   - `Universalist`
   - `MarketMaker`

3. **Simulation layer**
   - `Simulator`
   - `SimulatorInfo`
   - event classes
   - state classification functions

4. **Analysis / presentation layer**
   - visualization functions
   - `main.py` exploratory runner

---

## High-Level Simulation Flow

The baseline simulator is a discrete-time ABM. One simulation run follows this logic:

1. Create an `ExchangeAgent`.
2. The exchange initializes a limit order book and dividend book.
3. Create a population of agents linked to the same exchange.
4. Create optional exogenous events, for example `MarketPriceShock(200, -10)`.
5. Create a `Simulator(exchange, traders, events)`.
6. Run `simulator.simulate(n_iter)`.
7. During each iteration:
   - scheduled events are applied,
   - market and agent state is recorded,
   - chartist sentiment and universalist strategy are updated,
   - all traders are shuffled and called once,
   - dividend and interest payments are applied,
   - the dividend book advances by one step.

The baseline simulator uses **calendar time**: one iteration is one model time step.
It does not yet have event-time or volume-clock logic.

---

## Package Exports

The top-level `AgentBasedModel/__init__.py` re-exports the package submodules:

```python
from AgentBasedModel.agents import *
from AgentBasedModel.events import *
from AgentBasedModel.simulator import *
from AgentBasedModel.visualization import *
from AgentBasedModel.states import *
```

This allows examples such as:

```python
from AgentBasedModel import *

exchange = ExchangeAgent(volume=1000)
traders = [
    Random(exchange, 10**3),
    Fundamentalist(exchange, 10**3),
    Chartist(exchange, 10**3),
    MarketMaker(exchange, 10**3),
]
sim = Simulator(exchange, traders, events=[MarketPriceShock(200, -10)])
sim.simulate(500)
plot_price(sim.info)
```

Note: `LiquidityShock` exists in `events.py`, but it is not exported in
`AgentBasedModel/events/__init__.py` on this branch. If it is needed through
`from AgentBasedModel import *`, it should be added to the event exports.

---

# Core Market Architecture

## `Order`: Atomic Limit-Book Object

File: `AgentBasedModel/utils/orders.py`

An `Order` stores:

- `price`: order price,
- `qty`: remaining quantity,
- `order_type`: either `'bid'` or `'ask'`,
- `trader`: optional back-reference to the trader that placed the order,
- `order_id`: unique sequential ID,
- `left` and `right`: links for the doubly linked list.

### Comparison Logic

The order comparison operators are overloaded so that:

> `better offer < worse offer`

This means:

- for bids, higher price is better;
- for asks, lower price is better.

So for two bid orders:

```python
bid(price=101) < bid(price=100)  # True
```

For two ask orders:

```python
ask(price=99) < ask(price=100)  # True
```

This unusual comparison convention allows the same sorted-list logic to maintain both
bid and ask books in "best quote first" order.

---

## `OrderList`: Doubly Linked Order Book Side

File: `AgentBasedModel/utils/orders.py`

`OrderList` represents one side of the order book:

- one `OrderList('bid')` for buy orders,
- one `OrderList('ask')` for sell orders.

Each list stores:

- `first`: best order,
- `last`: worst order,
- `order_type`: side of the book.

### Main Methods

#### `append(order)`

Adds an order to the end of the list.

Complexity: `O(1)`.

#### `push(order)`

Adds an order to the beginning of the list.

Complexity: `O(1)`.

#### `insert(order)`

Inserts an order while preserving best-to-worst ordering.

Complexity: `O(n)`.

#### `remove(order)`

Removes a known order node from the list.

Complexity: `O(1)` when the order object is already known.

#### `fulfill(order, t_cost)`

Matches an incoming order against this book side.

Example:

- incoming bid order matches against the ask book,
- incoming ask order matches against the bid book.

The method walks from the best available quote to worse quotes and stops when:

- the incoming order is fully filled,
- or the next available order is no longer compatible with the incoming price.

During each partial fill, it updates:

- buyer cash,
- buyer assets,
- seller cash,
- seller assets,
- remaining quantity of both orders.

Transaction costs are applied inside `fulfill`:

- buyer pays `price * quantity * (1 + transaction_cost)`,
- seller receives `price * quantity * (1 - transaction_cost)`.

### Important Implementation Risk

In the baseline code, `OrderList.insert()` has a fragile empty-list branch:

```python
if self.first is None:
    self.append(order)

if order <= self.first:
    ...
```

After appending into an empty list, the method does **not** immediately return.
That can lead to incorrect pointer manipulation if `insert()` is called on an empty list.
In normal baseline runs the initial order book is large, so this often stays hidden, but
it matters for stress experiments where one side of the order book can be depleted.

For future experiments, especially H1/H2 with heavy market orders, this should be fixed
by adding `return` after `self.append(order)`.

---

## `ExchangeAgent`: Centralized Exchange and Order Book

File: `AgentBasedModel/agents/agents.py`

`ExchangeAgent` is the market venue. It owns:

- the bid order book,
- the ask order book,
- the dividend book,
- the risk-free rate,
- the transaction cost.

### Constructor

```python
ExchangeAgent(
    price=100,
    std=25,
    volume=1000,
    rf=5e-4,
    transaction_cost=0
)
```

Parameters:

- `price`: initial reference price, default `100`;
- `std`: standard deviation used to generate initial order prices, default `25`;
- `volume`: number of initial orders in the book, default `1000`;
- `rf`: risk-free rate per iteration, default `5e-4`;
- `transaction_cost`: proportional transaction cost, default `0`.

### Order Book Initialization

The exchange creates two lists:

```python
self.order_book = {
    'bid': OrderList('bid'),
    'ask': OrderList('ask')
}
```

Then `_fill_book(price, std, volume, rf * price)` generates initial orders:

- half of prices are sampled around `price - std`,
- half are sampled around `price + std`,
- quantities are sampled uniformly from integers `[1, 5]`,
- prices above the initial price become asks,
- prices at or below the initial price become bids.

This creates a populated initial limit order book around the initial reference price.

### Mid-Price

The market price is the midpoint between best bid and best ask:

```python
price = round((best_bid + best_ask) / 2, 1)
```

If either side of the order book is empty, `price()` raises:

```text
Price cannot be determined, since no orders either bid or ask
```

This is important: baseline code is not robust to full depletion of either side of the book.

### Spread

`spread()` returns:

```python
{'bid': best_bid_price, 'ask': best_ask_price}
```

or `None` if one side of the book is empty.

`spread_volume()` returns:

```python
{'bid': best_bid_quantity, 'ask': best_ask_quantity}
```

or `None` if one side is empty.

### Limit Orders

`limit_order(order)` checks whether the order crosses the spread:

- incoming bid crosses if `order.price >= best_ask`,
- incoming ask crosses if `order.price <= best_bid`.

If the order crosses, it is matched against the opposite side through `fulfill`.
Any remaining quantity is inserted into the appropriate book side.

### Market Orders

`market_order(order)` immediately matches against the opposite book side:

- bid market order consumes asks,
- ask market order consumes bids.

The baseline implementation does not track executed volume, trade count, or transaction history.
This will matter for H2 because event-time requires volume accounting.

### Cancellation

`cancel_order(order)` removes the order from the corresponding book side.

### Dividend Book

The exchange stores 100 future dividends in `dividend_book`.

`dividend(access=None)` works in two modes:

- if `access is None`, it returns the current dividend payment;
- if `access` is an integer, it returns the first `access` future dividends.

This is used by fundamentalist agents, whose information level is controlled by `access`.

---

## Dividend Process

The dividend process is stochastic and multiplicative.

In code:

```python
d_next = d_current * exp(normal(0, 5e-3))
```

Mathematically:

```text
d_{t+1} = max(d_t * exp(epsilon_t), 0)
epsilon_t ~ N(0, sigma_d^2)
sigma_d = 5e-3
```

Initial dividend:

```text
d_0 = rf * p_0
```

With default values:

```text
d_0 = 5e-4 * 100 = 0.05
```

At the end of every simulation iteration:

1. the current dividend is paid to traders according to their holdings;
2. `exchange.generate_dividend()` appends a new future dividend and removes the oldest one.

---

# Trader Architecture

## `Trader`: Base Class

File: `AgentBasedModel/agents/agents.py`

All trading agents inherit from `Trader`.

State variables:

- `id`: unique numerical ID,
- `name`: string name,
- `type`: current trader type,
- `market`: reference to the shared `ExchangeAgent`,
- `orders`: list of active orders placed by this trader,
- `cash`: current cash,
- `assets`: current stock holdings.

### Equity

```python
equity = cash + assets * market.price()
```

Important limitation: if the market price cannot be computed because the book is empty,
`equity()` will also fail.

### Primitive Actions

The base class exposes:

- `_buy_limit(quantity, price)`,
- `_sell_limit(quantity, price)`,
- `_buy_market(quantity)`,
- `_sell_market(quantity)`,
- `_cancel_order(order)`.

All higher-level trader behavior is built from these primitives.

### Market Order Price Detail

The baseline `_buy_market` and `_sell_market` create a marketable order using the
`last.price` of the opposite book side:

```python
Order(self.market.order_book['ask'].last.price, quantity, 'bid', self)
Order(self.market.order_book['bid'].last.price, quantity, 'ask', self)
```

Because the order book is sorted from best to worst, `last.price` is the worst quote,
not the best quote. This makes the incoming order marketable across the whole available
side up to that worst price. In practice this means market orders are very aggressive:
they are allowed to walk through the entire opposite book if quantity is large enough.

This is useful to know when designing shock and liquidity experiments.

---

## `Random`: Noise Trader

`Random` agents approximate background noisy liquidity.

### Behavior

On each `call()`:

1. If the spread is unavailable, the agent does nothing.
2. The agent randomly chooses order side:
   - bid with probability 50%,
   - ask with probability 50%.
3. The agent randomly chooses action:
   - if random state `> 0.85`: market order,
   - if random state `> 0.5`: limit order,
   - if random state `< 0.35`: cancellation.

So approximate action probabilities are:

- 15% market order,
- 35% limit order,
- 35% cancellation attempt,
- 15% no action.

### Limit Order Price

`Random.draw_price(order_type, spread)`:

- with probability 35%, price is drawn uniformly inside the spread;
- with probability 65%, price is outside the spread by an exponentially distributed offset.

For bids:

```text
price = best_bid - delta
```

For asks:

```text
price = best_ask + delta
```

where:

```text
delta ~ Exponential(lambda = 1 / 2.5)
```

### Quantity

Quantity is an integer from 1 to 5.

---

## `Fundamentalist`: Dividend-Value Trader

Fundamentalists trade based on the estimated fundamental value of the asset.

Constructor:

```python
Fundamentalist(market, cash, assets=0, access=1)
```

The key parameter is:

- `access`: number of future dividends visible to the trader.

### Fundamental Price

Given visible future dividends:

```text
d_1, d_2, ..., d_n
```

and risk-free rate `r`, the fundamental value is:

```text
p_f = sum_{i=1}^{n-1} d_i / (1+r)^i
      + (d_n / r) / (1+r)^(n-1)
```

Interpretation:

- known near-term dividends are discounted directly;
- the last visible dividend is used as a perpetuity anchor.

### Quantity Rule

The order quantity is proportional to relative mispricing:

```python
q = round(abs(pf - p) / p / gamma)
q = min(q, 5)
```

Default:

```text
gamma = 0.005
```

If the mispricing is too small and `q == 0`, the agent does nothing.

### Trading Logic

On each call:

1. Compute `pf`.
2. Read current market price and spread.
3. With probability 55%, submit an order.
4. With probability 45%, cancel the first active order if one exists.

If trading:

- if `pf >= ask`, the asset is undervalued relative to ask, so the agent buys or places a high sell limit around fundamental value depending on random draw;
- if `pf <= bid`, the asset is overvalued relative to bid, so the agent sells or places a low buy limit;
- if `bid < pf < ask`, the agent places a limit order around `pf`.

The implementation uses transaction-cost-adjusted bid and ask prices:

```python
ask_t = spread['ask'] * (1 + transaction_cost)
bid_t = spread['bid'] * (1 - transaction_cost)
```

---

## `Chartist`: Sentiment Trader

Chartists trade according to a binary sentiment:

- `Optimistic`: buy-oriented,
- `Pessimistic`: sell-oriented.

The initial sentiment is random.

### Trading Logic

If optimistic:

- 15% chance: buy market order,
- 35% chance: buy limit order,
- 35% chance: cancel last active order,
- 15% chance: no action.

If pessimistic:

- 15% chance: sell market order,
- 35% chance: sell limit order,
- 35% chance: cancel last active order,
- 15% chance: no action.

### Sentiment Update

Sentiment is updated before trading during each simulation iteration.

The opinion index is:

```text
U = a1 * x + (a2 / v1) * dp / p
```

where:

- `x = (n_optimistic - n_pessimistic) / n_chartists`,
- `dp` is the latest price change,
- `p` is current market price,
- `a1` controls social/sentiment influence,
- `a2` controls price-trend influence,
- `v1` controls sentiment update frequency.

Baseline probabilities:

```python
Optimistic -> Pessimistic:
prob = v1 * n_chartists / n_traders * exp(U)

Pessimistic -> Optimistic:
prob = v1 * n_chartists / n_traders * exp(-U)
```

### Critical Interpretation

This baseline formula produces **contrarian** behavior:

- if price falls, `dp < 0`, `U < 0`, so `exp(-U)` becomes large;
- pessimists are more likely to become optimists;
- agents buy after a fall;
- this stabilizes the market.

For the H1 high-frequency-trading hypothesis, this is not the intended mechanism.
The H1 experiments therefore need a `TrendChartist` subclass with reversed exponent signs.

Important: this does not necessarily mean the baseline code is "wrong" in general.
It means that the original chartist behavior is contrarian and therefore unsuitable
for testing a trend-following HFT crash-amplification mechanism without modification.

---

## `Universalist`: Strategy-Switching Agent

`Universalist` inherits from both `Fundamentalist` and `Chartist`.

It can switch between:

- `type = 'Fundamentalist'`,
- `type = 'Chartist'`.

On each `call()`:

- if current type is `Chartist`, it uses `Chartist.call(self)`;
- if current type is `Fundamentalist`, it uses `Fundamentalist.call(self)`.

### Strategy Switching

The method `change_strategy(info)` compares:

- fundamental expected return,
- recent price change,
- average return of agents in the economy,
- mispricing between fundamental and market price,
- current sentiment composition.

It computes two utility-like indices:

```text
U1 = a3 * ((r + 1/v2 * dp) / p - R_bar - s * |(pf - p) / p|)
U2 = a3 * (R_bar - (r + 1/v2 * dp) / p - s * |(pf - p) / p|)
```

where:

- `pf`: fundamental value,
- `r = pf * risk_free`,
- `R_bar`: average realized return across agents,
- `s`: sensitivity to mispricing,
- `v2`: strategy switching frequency.

Both `U1` and `U2` are clamped to `[-100, 100]` to avoid exponential overflow.

If the agent is currently a chartist, it may switch to fundamentalist.
If currently fundamentalist, it may switch to chartist with either optimistic or pessimistic sentiment.

---

## `MarketMaker`: Inventory-Constrained Liquidity Provider

The market maker provides two-sided limit orders and manages inventory inside a soft band.

Constructor:

```python
MarketMaker(market, cash, assets=0, softlimit=100)
```

State:

- `softlimit`: inventory band size,
- `ul = softlimit`: upper inventory limit,
- `ll = -softlimit`: lower inventory limit,
- `panic`: diagnostic flag.

### Behavior

On each call:

1. Cancel all previously placed orders.
2. Read current spread.
3. Compute bid and ask volumes:

```text
bid_volume = max(0, ul - 1 - assets)
ask_volume = max(0, assets - ll - 1)
```

4. If either volume is zero, set `panic = True`.
5. Otherwise, set `panic = False` and place both bid and ask limit orders.

### Inventory-Dependent Quote Skew

The market maker adjusts quotes according to inventory:

```text
base_offset = -((ask - bid) * assets / softlimit)
```

Then:

```python
buy at:  bid - base_offset - 0.1
sell at: ask + base_offset + 0.1
```

This makes the market maker quote differently depending on whether it holds too many or too few shares.

### Important Baseline Quirk

When bid or ask volume is zero, the code enters the panic branch:

```python
if not bid_volume or not ask_volume:
    self.panic = True
    self._buy_market(...) if ask_volume is None else None
    self._sell_market(...) if bid_volume is None else None
```

But `bid_volume` and `ask_volume` are numbers created by `max(0, ...)`.
They become `0`, not `None`.

Therefore the rebalancing market orders are never triggered.
The `panic` flag is set, but panic is diagnostic only.

For experiments, this means:

- `panic` can be used as a stress indicator,
- but it does not actively rebalance the market maker.

---

# Simulator Architecture

## `Simulator`

File: `AgentBasedModel/simulator/simulator.py`

Constructor:

```python
Simulator(exchange=None, traders=None, events=None)
```

It stores:

- `exchange`,
- `traders`,
- `events`,
- `info = SimulatorInfo(exchange, traders)`.

If events are passed, each event is linked to the simulator:

```python
self.events = [event.link(self) for event in events]
```

This gives each event access to:

- the exchange,
- the trader list,
- the current simulation environment.

---

## Baseline Calendar-Time Loop

The baseline `simulate(n_iter, silent=False)` loop is:

```python
for it in range(n_iter):
    if self.events:
        for event in self.events:
            event.call(it)

    self.info.capture()

    for trader in self.traders:
        if type(trader) == Universalist:
            trader.change_strategy(self.info)
        elif type(trader) == Chartist:
            trader.change_sentiment(self.info)

    random.shuffle(self.traders)
    for trader in self.traders:
        trader.call()

    self._payments()
    self.exchange.generate_dividend()
```

### Interpretation of Ordering

The order matters:

1. **Events happen first.**
   If a shock is scheduled at `it=200`, it changes the order book before state capture.

2. **State is captured before agents trade.**
   The recorded price at iteration `t` is the price after events but before that iteration's trading.

3. **Behavioral updates use captured state.**
   Chartists and Universalists react to the time series recorded so far.

4. **Trader order is random.**
   There is no systematic priority or speed advantage in the baseline.

5. **Payments happen after trading.**
   Traders receive dividends and interest at the end of the iteration.

6. **Dividends advance after payments.**
   The dividend book shifts forward once per calendar iteration.

---

## `_payments()`

At the end of each iteration, for every trader:

```python
trader.cash += trader.assets * exchange.dividend()
trader.cash += trader.cash * exchange.risk_free
```

The code allows:

- negative cash,
- negative assets,
- interest on negative cash,
- dividend payments on negative asset positions.

This keeps the model simple but means there are no hard budget constraints.

---

## `SimulatorInfo`: Data Recorder

`SimulatorInfo` captures market and agent state during simulation.

It stores:

### Market series

- `prices`: market midpoint at each capture,
- `spreads`: best bid and ask at each capture,
- `dividends`: current dividend at each capture,
- `orders`: order-book summary.

The current `orders` summary records only:

```python
{
    'quantity': {
        'bid': number_of_bid_orders,
        'ask': number_of_ask_orders
    }
}
```

There are commented-out placeholders for:

- mean order price,
- standard deviation of order price,
- volume sum,
- volume mean,
- volume standard deviation.

These are not active in the baseline.

### Agent series

- `equities`: each agent's equity,
- `cash`: each agent's cash,
- `assets`: each agent's stock holdings,
- `types`: each agent's current type,
- `sentiments`: chartist sentiments,
- `returns`: relative equity returns.

### Derived Indicators

#### `fundamental_value(access=1)`

Computes model-implied fundamental value series using recorded dividends and the current future dividend book.

#### `stock_returns(roll=None)`

Computes:

```text
r_t = (p_{t+1} - p_t) / p_t + dividend_t / p_t
```

If `roll` is provided, returns rolling mean.
If no `roll` is provided, returns the mean return over the whole simulation.

#### `abnormal_returns(roll=None)`

Returns stock returns minus the risk-free rate.

Important implementation note:

```python
r = [r - rf for r in self.stock_returns()]
```

Since `stock_returns()` without `roll` returns a scalar mean, this method is fragile in the baseline.
For experiment scripts, it is safer to compute returns directly from `info.prices` or call
`stock_returns(1)` when a series is needed.

#### `return_volatility(window=None)`

If `window` is provided, computes rolling standard deviation of one-step stock returns.

#### `price_volatility(window=None)`

If `window` is provided, computes rolling standard deviation of prices.

This became the main volatility input in H1-style experiments.

#### `liquidity(roll=None)`

Computes relative spread:

```text
(ask - bid) / price
```

This is a proxy for market illiquidity: higher values mean wider spreads and lower liquidity.

---

# Event System

File: `AgentBasedModel/events/events.py`

All events inherit from `Event`.

Each event has:

- `it`: activation iteration,
- `simulator`: link to simulator, assigned by `event.link(self)`.

The base `call(it)` method checks:

- whether the event has a simulator link,
- whether the current iteration equals the event activation iteration.

If `it != self.it`, the event does nothing.

---

## `MarketPriceShock`

```python
MarketPriceShock(it, price_change)
```

At activation, shifts all order prices in the book:

```python
order.price += round(self.dp, 1)
```

Important detail:

```python
self.dp = round(price_change)
```

This means fractional shocks are rounded at construction.
For example, in Python:

```python
round(-0.5) == 0
```

So a requested `MarketPriceShock(..., -0.5)` would become `dp=0` in this baseline.
If future experiments need fractional shock magnitudes, this event class should be adjusted.

---

## `FundamentalPriceShock`

```python
FundamentalPriceShock(it, price_change)
```

At activation, modifies the whole dividend book:

```python
dividend += dp * risk_free
```

This shifts the fundamental value rather than directly shifting the order book.

---

## `LiquidityShock`

```python
LiquidityShock(it, volume_change)
```

Creates a pseudo-trader and sends a one-sided market order.

If `dv < 0`, the pseudo-trader buys from the ask side.
If `dv >= 0`, the pseudo-trader sells into the bid side.

This directly removes depth from the book.

Important export note: `LiquidityShock` is defined in `events.py`, but is not currently exported
from `AgentBasedModel/events/__init__.py`.

---

## `InformationShock`

```python
InformationShock(it, access)
```

At activation, changes `access` for all agents whose type is exactly:

- `Universalist`,
- `Fundamentalist`.

This controls how many future dividends those agents can observe.

---

## `MarketMakerIn`

```python
MarketMakerIn(it, cash=10**3, assets=0, softlimit=100)
```

At activation, creates a new `MarketMaker` and appends it to `simulator.traders`.

Important limitation: `SimulatorInfo.traders` is created once in `SimulatorInfo.__init__`.
If traders are added after simulation starts, the recorder's internal trader dictionary may not include
the new market maker unless the recorder is updated.

---

## `MarketMakerOut`

```python
MarketMakerOut(it)
```

At activation, removes all traders whose exact type is `MarketMaker`.

As with `MarketMakerIn`, changing the trader list dynamically can create mismatch with
`SimulatorInfo.traders`, because the recorder stores a fixed dictionary from initial traders.

---

## `TransactionCost`

```python
TransactionCost(it, cost)
```

At activation, updates:

```python
exchange.transaction_cost = cost
```

---

# State Classification

File: `AgentBasedModel/states/states.py`

The `states` module provides post-simulation helpers.

## `aggToShock(sim, window, funcs)`

Aggregates selected time series relative to each event.

For each event and each function, it returns:

- `start`,
- `before`,
- `right before`,
- `after`,
- `right after`,
- `end`.

The baseline `main.py` uses this to compare prices around the market price shock.

## Trend Tests

The module includes:

- `test_trend_kendall(values)`,
- `test_trend_ols(values)`.

`test_trend_ols` regresses a time series on time and returns:

- slope value,
- t-statistic,
- p-value.

## Regime Classifiers

The module defines:

- `trend(info, size=None, window=5, conf=.95, th=.01)`,
- `panic(info, size=None, window=5, th=.5)`,
- `disaster(info, size=None, window=5, conf=.95, th=.02)`,
- `mean_rev(info, size=None, window=5, conf=.95, th=-.02)`,
- `general_states(info, size=10, window=5)`.

`general_states` labels rolling windows as:

- `mean-rev`,
- `disaster`,
- `panic`,
- `trend`,
- `stable`.

### Important Research Note

For H1-style inference, `general_states()` should be treated carefully.
Earlier H1 work found that crisis-state classifications can be too sensitive and can label
large fractions of normal baseline simulation as `panic` or `disaster`.

For hypothesis testing, direct metrics such as volatility ratio, spread ratio, drawdown,
recovery time, and volatility clustering measures are more reliable.

---

# Utility Math

File: `AgentBasedModel/utils/math.py`

The utility module defines:

- `mean(x)`,
- `quantile(x, q=.5)`,
- `std(x)`,
- `rolling(x, n)`,
- `difference(x)`,
- `aggregate(types_arr, target_arr, labels)`.

Important limitations:

- `mean([])` is undefined and will fail;
- `rolling` has an incomplete `else` branch: when `None in x`, it builds `res` but does not return it;
- `quantile` uses `round(len(x) * q) - 1`, which may behave unexpectedly for very small lists.

These functions are simple and useful for plots, but experiment scripts should protect against empty
lists and missing values explicitly.

---

# Visualization Layer

## Market Plots

File: `AgentBasedModel/visualization/market.py`

Functions:

- `plot_price(info, spread=False, rolling=1)`,
- `plot_price_fundamental(info, spread=False, access=1, rolling=1)`,
- `plot_arbitrage(info, access=1, rolling=1)`,
- `plot_dividend(info, rolling=1)`,
- `plot_orders(info, stat='quantity', rolling=1)`,
- `plot_volatility_price(info, window=5)`,
- `plot_volatility_return(info, window=5)`,
- `plot_liquidity(info, rolling=1)`.

These functions use `matplotlib` and the simple rolling helpers from `utils.math`.

## Trader Plots

File: `AgentBasedModel/visualization/trader.py`

Functions:

- `plot_equity(info, rolling=1)`,
- `plot_cash(info, rolling=1)`,
- `plot_assets(info, rolling=1)`,
- `plot_strategies(info, rolling=1)`,
- `plot_strategies2(info, rolling=1)`,
- `plot_sentiments(info, rolling=1)`,
- `plot_sentiments2(info, rolling=1)`,
- `plot_returns(info, rolling=1)`.

These aggregate agent data by type.

Important limitation: labels are hard-coded mostly for:

- `Random`,
- `Fundamentalist`,
- `Chartist`.

MarketMaker and Universalist are not always included in aggregate plots.

## Order Book Plots

File: `AgentBasedModel/visualization/other.py`

Functions:

- `print_book(info, n=5)`,
- `plot_book(info, bins=50)`.

`print_book` prints top bid/ask levels.
`plot_book` creates histograms of bid and ask price distributions.

---

# `main.py`: Baseline Exploratory Runner

The current `main.py` is an exploratory script, not a final hypothesis experiment.

It runs a grid over population composition:

```python
RANGE = range(0, 6)

for n_rand, n_fund, n_chart, n_univ in product(RANGE, repeat=4):
    for is_mm in range(2):
        ...
```

For each configuration, it creates:

- `n_rand` random agents,
- `n_fund` fundamentalists,
- `n_chart` chartists,
- `n_univ` universalists,
- optionally one market maker.

Every run uses:

```python
MarketPriceShock(200, -10)
simulator.simulate(500)
```

Then it extracts prices around the shock with:

```python
aggToShock(simulator, 1, FUNCS)
```

At the end, it plots the last simulation's:

- price,
- equity,
- assets,
- cash.

Important: `main.py` does not save results to CSV and does not compute final H1/H2/H3 metrics.
It is best interpreted as a basic model exploration script.

---

# Baseline Limitations Important for Future Experiments

## 1. No Speed Heterogeneity

All traders are shuffled together:

```python
random.shuffle(self.traders)
for trader in self.traders:
    trader.call()
```

There is no systematic fast/slow ordering in the baseline.

## 2. No Information Delay

Agents observe the current spread and current price directly through:

- `market.spread()`,
- `market.price()`.

There is no historical spread buffer and no `info_lag`.

## 3. No Event-Time Clock

The simulator advances by calendar iteration only.

There is no:

- executed-volume counter,
- trade count,
- per-tick volume threshold,
- event-time capture mode.

This must be added for H2.

## 4. No Trade History

`OrderList.fulfill` updates cash and assets but does not record:

- executed quantity,
- execution price history,
- trade count,
- buyer/seller identity,
- cumulative volume.

H2 requires at least executed-volume tracking.

## 5. Empty Book Is Not Safely Handled Everywhere

Some methods check for missing spread, but others assume price and spread exist.

Risky places:

- `ExchangeAgent.limit_order()` calls `self.spread().values()` before checking whether spread is `None`;
- `SimulatorInfo.capture()` calls `exchange.price()` directly;
- `Trader.equity()` calls `market.price()`;
- `Chartist.call()` uses `Random.draw_price(..., spread)` without checking whether `spread` is `None`.

Stress experiments can therefore crash if one side of the book is depleted.

## 6. MarketMaker Panic Is Diagnostic Only

The `panic` flag can become `True`, but the intended one-sided rebalancing orders do not fire
because the code checks `is None` instead of checking zero volume.

## 7. `MarketPriceShock` Rounds Shock Magnitude

`MarketPriceShock.__init__` uses:

```python
self.dp = round(price_change)
```

Therefore fractional shock magnitudes are not preserved.
This matters if shock-magnitude robustness experiments use values like `-0.5`.

## 8. Chartist Sentiment Is Contrarian

The baseline chartist switching formula stabilizes price moves rather than amplifying them.

This matters for H1: HFT crash amplification requires a trend-following version of chartist behavior.

## 9. Dynamic Trader Entry/Exit Can Desynchronize Recorder

`SimulatorInfo.traders` is created once at simulator initialization.
If `MarketMakerIn` or `MarketMakerOut` changes `simulator.traders`, the recorder may not match
the live trader list unless it is updated.

---

# Research Hypotheses and Experimental Plan

This section aligns the codebase with the plan in `paper_full.pdf` / `paper_full.tex`.

## H1: Latency Heterogeneity and the Tipping Point

### Research Claim

An increase in the proportion of high-frequency traders with execution-speed advantage leads to
higher post-shock volatility and reduced liquidity. The relationship is expected to be nonlinear:
beyond a critical share of fast agents, the market enters a toxic-liquidity regime.

### Main Quantity

The key parameter is:

```text
phi = hft_frac = share of chartist agents that are fast
```

### Required Code Modifications

H1 cannot be tested on the baseline as-is because all traders are randomly shuffled.

Needed changes:

1. Add fast/slow labels to traders:

```python
trader.speed = 'fast'
trader.speed = 'slow'
```

2. Replace one random activation list with two phases:

```python
fast = [t for t in self.traders if getattr(t, 'speed', 'slow') == 'fast']
slow = [t for t in self.traders if getattr(t, 'speed', 'slow') != 'fast']

random.shuffle(fast)
for trader in fast:
    trader.call()

random.shuffle(slow)
for trader in slow:
    trader.call()
```

3. Add optional `speed_multiplier` if testing stronger execution advantage.

4. Introduce `TrendChartist`, because the baseline `Chartist` is contrarian.

5. Optionally introduce `SlowTrendChartist` or delayed market information for slow agents.

### Metrics

Use direct post-shock stability metrics:

- volatility ratio,
- spread ratio,
- maximum drawdown,
- recovery time,
- market-maker stress / panic ratio.

### Tipping Point

Define:

```text
baseline = mean volatility ratio at phi = 0
threshold = 1.3 * baseline
phi* = first phi where mean volatility ratio >= threshold
```

### Expected Paper Role

H1 is the first empirical core of the paper. It demonstrates whether speed heterogeneity alone can
generate a critical transition from ordinary volatility to unstable post-shock dynamics.

---

## H2: Calendar Time versus Event Time

### Research Claim

Updating market information in event time, rather than fixed calendar time, can alter market resilience
and shift the crisis boundary. A market operating on an event-time or volume-clock basis may tolerate
a higher share of fast traders before reaching the tipping point.

### Baseline Situation

The current simulator is purely calendar-time:

```python
for it in range(n_iter):
    ...
```

Every iteration has:

- one event check,
- one capture,
- one behavioral update,
- one call opportunity per trader,
- one payment,
- one dividend-book shift.

### Clean H2 Architecture

H2 should compare two modes under otherwise identical market settings:

1. **Calendar-time mode**
   - original fixed iteration loop;
   - one tick = one iteration.

2. **Event-time / volume-clock mode**
   - one tick ends only after cumulative executed volume reaches `Vstar`;
   - the number of inner sub-iterations is variable;
   - state is captured once per event-time tick.

### Required Code Modifications

H2 requires trade-volume tracking.

The cleanest design is:

1. Add executed-volume counters to `ExchangeAgent`:

```python
self.executed_volume_tick = 0
self.executed_volume_total = 0
self.executed_trades_tick = 0
self.executed_trades_total = 0
```

2. During each match in `OrderList.fulfill`, report executed quantity back to the exchange.

The current `OrderList` does not know the exchange. Possible implementation options:

- pass an optional callback into `fulfill`;
- or let `ExchangeAgent.market_order` / `limit_order` compute before-after book quantities;
- or refactor `fulfill` to accept `exchange` and increment counters directly.

The callback design is cleanest because it keeps order matching generic.

3. Add a calendar-time simulation method:

```python
simulate_calendar(...)
```

or preserve existing `simulate(...)`.

4. Add an event-time simulation method:

```python
simulate_event_time(n_ticks, volume_threshold)
```

Pseudo-logic:

```python
for tick in range(n_ticks):
    exchange.reset_tick_volume()

    while exchange.executed_volume_tick < Vstar:
        maybe_call_events()
        call_traders_without_payment()

    info.capture()
    update_behaviour()
    payments_once_per_tick()
    exchange.generate_dividend()
```

### Critical Design Choice: Payments

Payments and dividend generation must not happen inside every inner sub-iteration.

If they did, active high-volume periods would mechanically receive more dividends and interest,
which would distort the economics.

For event time, the cleaner rule is:

- many trading sub-iterations may occur inside one event tick;
- but dividends, interest, behavioral update, and state capture happen once per event tick.

### H2 Experimental Grid

A clean first H2 grid:

```text
mode in {calendar, event_time}
phi in {0.0, 0.1, ..., 1.0}
Vstar in calibrated set, for example {10, 25, 50}
n_runs = 30
shock = same MarketPriceShock at comparable tick
```

The first version can use one calibrated `Vstar` after measuring typical executed volume in baseline.

### Main H2 Outcome

Compare:

```text
phi*_calendar
phi*_event
Delta phi* = phi*_event - phi*_calendar
```

H2 is supported if:

- `phi*_event > phi*_calendar`,
- event-time mode has lower post-shock volatility or shorter crisis duration,
- liquidity does not deteriorate more severely under event time.

### Expected Paper Role

H2 should answer whether the timekeeping rule changes the crisis boundary.
This connects directly to the literature on volume clocks and frequent batch auctions.

---

## H3: Information Delay, Liquidity Constraints, and Volatility Clustering

### Research Claim

Information delays combined with liquidity constraints generate volatility clustering, and this
clustering becomes stronger during crisis regimes.

The key idea is not just "delay increases volatility", but:

> delay plus limited liquidity creates persistent bursts of volatility.

### Baseline Situation

The current baseline has:

- no reaction delay parameter,
- no delayed information buffer,
- a market maker with `softlimit`,
- liquidity shocks,
- market-maker entry/exit events.

So H3 can reuse the existing liquidity mechanisms but needs new delay logic.

### Required Code Modifications

Introduce:

```python
trader.reaction_delay = d
```

Then apply it in:

1. behavioral updates,
2. trading calls.

Example:

```python
for trader in self.traders:
    delay = getattr(trader, 'reaction_delay', 1)
    if it % delay != 0:
        continue
    trader.call()
```

This represents agents who react only every `d` iterations.

### Liquidity Constraint Variables

Use:

- `MarketMaker.softlimit`,
- optional `LiquidityShock`,
- optional `MarketMakerOut`.

Recommended first grid:

```text
reaction_delay in {1, 2, 3, 5, 10}
softlimit in {5, 10, 20, 50, 100}
n_runs = 30
```

### Metrics

Volatility clustering should be measured directly, not only through average volatility.

Recommended metrics:

1. Autocorrelation of absolute returns:

```text
corr(|r_t|, |r_{t-k}|)
```

for lags `k = 1, 2, 5, 10`.

2. Mean length of high-volatility episodes.

3. Share of time spent above high-volatility threshold.

4. Interaction effect:

```text
effect(delay + low_liquidity)
  - effect(delay only)
  - effect(low_liquidity only)
```

### Confirmation Criterion

H3 is supported if:

- absolute-return autocorrelation is positive and statistically meaningful,
- clustering is stronger in high-delay + low-liquidity regimes,
- the interaction is stronger than either factor alone.

### Expected Paper Role

H3 extends the paper from tipping-point instability to stylized facts of financial crises:
volatility is not only higher, but clustered in persistent bursts.

---

# Suggested Branch Strategy

Because the current branch is clean baseline `main`, future experimental work should branch from here:

```bash
git switch main
git switch -c h2-event-time-volume-clock
```

Recommended branch names:

- `h1-tipping-point` or `hft-intraiter` for H1;
- `h2-event-time-volume-clock` for H2;
- `h3-delay-liquidity-clustering` for H3.

If a branch accidentally starts from an H1-modified branch, it will inherit many unrelated files and
code changes. For H2, that is not ideal: H2 should start from `main` and introduce only volume-clock
changes.

---

# Plan for Updating `paper_full`

## Current Paper Structure

The existing `paper_full` already contains:

1. research motivation,
2. literature review,
3. baseline simulator description,
4. experimental design for H1-H3,
5. H1 results.

The next work should keep the paper organized around the three hypotheses.

---

## Paper Plan: Baseline Model Section

The baseline model section should describe:

- centralized limit order book,
- order matching,
- dividend process,
- trader types,
- event system,
- simulator loop,
- recorded indicators.

This documentation can serve as the source for that section.

Important details to mention in the paper:

- price is midpoint of best bid and best ask;
- order book is initialized from random bid/ask distributions;
- fundamentalists use dividend discount valuation;
- baseline chartists are contrarian;
- market maker supplies two-sided liquidity with inventory-dependent quote skew;
- simulation is calendar-time by default.

---

## Paper Plan: H1 Section

H1 section should contain:

1. Why baseline cannot test latency heterogeneity.
2. Fast/slow activation-loop modification.
3. TrendChartist correction.
4. Experimental grid over `phi`, speed, and lag.
5. Stability metrics.
6. Tipping-point definition.
7. Main results and interpretation.

The paper already has a strong H1 section. It should eventually be updated with the latest unified
and follow-up results if those are intended for the final version.

---

## Paper Plan: H2 Section

H2 section should be written after implementing and running the clean branch experiment.

It should contain:

1. Motivation from volume-clock literature.
2. Difference between calendar time and event time.
3. Implementation of executed-volume counter.
4. Definition of event-time tick:

```text
one tick = cumulative executed volume >= Vstar
```

5. Calibration of `Vstar`.
6. Experiment grid:

```text
mode x phi x Vstar
```

7. Same stability metrics as H1 for comparability.
8. Main comparison:

```text
phi*_calendar vs phi*_event
```

9. Interpretation:
   - if event time shifts `phi*` upward, it supports H2;
   - if not, explain whether event time is neutral or destabilizing in this model.

---

## Paper Plan: H3 Section

H3 section should be written after H2 or in parallel if time allows.

It should contain:

1. Motivation from delayed reaction and limited liquidity literature.
2. Definition of reaction delay.
3. Definition of liquidity constraint through `softlimit`.
4. Factorial experiment:

```text
reaction_delay x softlimit
```

5. Volatility clustering metrics:
   - autocorrelation of absolute returns,
   - high-volatility episode length,
   - crisis-state duration if `general_states` is made reliable enough.
6. Interaction-effect interpretation.

---

## Final Paper Logic

The final paper can tell one coherent story:

1. **Baseline model** creates a realistic microstructure environment with heterogeneous agents.
2. **H1** asks whether speed inequality creates a tipping point.
3. **H2** asks whether changing the market clock changes that tipping point.
4. **H3** asks whether delayed reaction plus limited liquidity creates clustered volatility.

In other words:

```text
H1: Who is faster?
H2: What clock does the market use?
H3: What happens when reaction is delayed and liquidity is limited?
```

Together, these hypotheses connect microstructure speed, information timing, and liquidity supply
to market stability.

---

# Immediate Next Steps

## For This Branch

This branch should remain clean and baseline-oriented.

Recommended next steps:

1. Commit this baseline documentation.
2. Create `h2-event-time-volume-clock` from `main`.
3. Implement only H2-specific changes there:
   - executed-volume tracking,
   - event-time simulator loop,
   - H2 experiment script,
   - H2 plots and CSV outputs.

## For H2 Implementation

Before writing the full H2 experiment, implement and test in small steps:

1. Add executed-volume tracking.
2. Verify that market orders increment volume.
3. Verify that limit orders crossing the spread increment volume.
4. Add a tiny event-time simulation with `Vstar`.
5. Compare number of sub-iterations per event tick.
6. Only then run the full grid.

This keeps H2 clean and prevents mixing event-time logic with H1-specific speed/delay code.
