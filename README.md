# Financial Market Stability ABM

Agent-based market simulator for studying how heterogeneous trader behavior, information access, liquidity, and market shocks can affect price stability in a limit order book.

This repository is part of my course research project on financial market stability under heterogeneous information speeds. The `main` branch contains the clean baseline simulator: a compact, inspectable 1D market model that can be extended into hypothesis-specific experiments.

## Project Snapshot

- **Domain:** market microstructure, agent-based modeling, computational finance
- **Core model:** centralized limit order book with bid/ask matching
- **Agents:** random traders, fundamentalists, chartists, universalists, and a market maker
- **Events:** price shocks, fundamental shocks, information shocks, market-maker entry/exit, transaction-cost changes
- **Outputs:** simulated prices, spreads, dividends, trader equity/cash/assets, strategies, sentiments, and liquidity metrics
- **Stack:** Python, NumPy, pandas, SciPy, statsmodels, matplotlib, seaborn

## Paper

The full course paper is available here:

[Financial Market Stability under Heterogeneous Information Speeds: An Agent-Based Modeling Approach](docs/Coursework-Ravilova.pdf)

## Why This Project Exists

Financial markets can become unstable not only because of external shocks, but also because market participants react with different speeds, information sets, and strategies. This project provides a simulation environment for exploring those mechanisms in a controlled setting.

The baseline model is intentionally small enough to audit, but rich enough to support research questions such as:

- How do different trader populations change market stability?
- How does a shock propagate through a limit order book?
- What happens when fundamentalist, chartist, and market-making behavior interact?
- Which market conditions make recovery after a shock slower or less complete?

## Model Overview

The simulator runs in discrete calendar-time iterations. During each iteration:

1. Scheduled market events are applied.
2. Current market and trader state is recorded.
3. Chartists update sentiment and universalists may switch strategy.
4. Traders are shuffled and activated once.
5. Dividends and risk-free interest are paid.
6. The future dividend process advances.

The market price is derived from the best bid and ask in the order book. Traders submit market orders, limit orders, and cancellations depending on their behavioral rule.

## Repository Structure

```text
1D-ABM/
├── AgentBasedModel/
│   ├── agents/          # Exchange, trader classes, and market maker
│   ├── events/          # Exogenous shocks and market interventions
│   ├── simulator/       # Simulation loop and recorded market state
│   ├── states/          # Market-state classification helpers
│   ├── utils/           # Order and order-book primitives
│   └── visualization/   # Plotting utilities for market and trader metrics
├── docs/
│   └── Coursework-Ravilova.pdf
├── main.py              # Exploratory runner
├── documentation.md     # Detailed baseline architecture notes
└── requirements.txt
```

## Quick Start

Create an environment and install the project dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Run the exploratory script. It performs a broader parameter sweep, so it may take some time:

```bash
python main.py
```

For a quick smoke test, start with a smaller custom simulation:

```python
from AgentBasedModel import *

exchange = ExchangeAgent(volume=1000)
traders = [
    Random(exchange, 10**3),
    Fundamentalist(exchange, 10**3),
    Chartist(exchange, 10**3),
    Universalist(exchange, 10**3),
    MarketMaker(exchange, 10**3),
]

simulator = Simulator(
    exchange=exchange,
    traders=traders,
    events=[MarketPriceShock(200, -10)],
)

simulator.simulate(500, silent=True)
plot_price(simulator.info)
```

## Research Branches

The `main` branch is the baseline model. Hypothesis-specific work is developed in separate branches, including:

- `h1-tipping-point` - latency heterogeneity and tipping-point behavior
- `h2-event-time-volume-clock` - calendar time versus event-time / volume-clock simulations
- `h3-volatility-clustering` - information delay, liquidity constraints, and post-shock stability
- `results` - consolidated experiment outputs and deliverables

## Portfolio Notes

This project demonstrates:

- translating a financial-market research question into an executable simulation model;
- working with object-oriented Python in a multi-agent system;
- designing experiments around market shocks, liquidity, and heterogeneous strategies;
- collecting simulation outputs for statistical analysis and visualization;
- maintaining a clean baseline branch while developing experimental extensions separately.

## Current Status

The baseline simulator is functional and documented. The main branch is best used as a readable entry point into the model architecture, while the research branches contain the expanded experiments and final empirical outputs.
