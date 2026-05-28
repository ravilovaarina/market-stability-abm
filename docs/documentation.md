# H1 Tipping-Point Branch Documentation

## Branch Purpose

This branch contains the early H1 experiments for the course paper.

Hypothesis H1:

> A higher share of fast high-frequency traders can increase post-shock volatility and reduce liquidity, producing a nonlinear tipping point.

This branch covers the first H1 design stage: baseline diagnostics and experiments v1-v6. Later H1 work with TrendChartist, information delay, and the unified H1 grids belongs to the `hft-intraiter` branch, not this branch.

## Repository Structure

```text
1D-ABM/
├── AgentBasedModel/                 # Baseline ABM simulator package
├── docs/
│   └── documentation.md             # This branch documentation
├── experiments/
│   ├── baseline/
│   │   └── main.py                  # Original baseline runner
│   └── h1/
│       ├── baseline_check.py        # Baseline diagnostics
│       ├── experiment_h1.py         # H1 v1
│       ├── experiment_h1_v2.py      # Shock sweep and access asymmetry
│       ├── experiment_h1_v3.py      # Direct stability metrics
│       ├── experiment_h1_v4.py      # Same design with more runs
│       ├── experiment_h1_v5.py      # Pure execution-speed isolation
│       └── experiment_h1_v6.py      # fast_share x MarketMaker softlimit grid
├── results/
│   └── h1/
│       ├── raw/                     # Raw simulation outputs
│       ├── tables/                  # Summary tables
│       └── figures/                 # Plots
└── requirements.txt
```

## Source Files

### `experiments/h1/baseline_check.py`

Purpose:
- checks baseline behavior without HFT-specific mechanisms;
- compares no-shock and shock runs;
- verifies that `general_states()` is not reliable enough for H1 inference.

Output:
- `results/h1/figures/h1_baseline_check_prices_volatility.png`

### `experiments/h1/experiment_h1.py`

Purpose:
- first speed-heterogeneity experiment;
- varies `fast_share`;
- uses `general_states()` and direct spread metrics.

Outputs:
- `results/h1/raw/h1_raw.csv`
- `results/h1/figures/h1_results.png`
- `results/h1/figures/h1_prices.png`

### `experiments/h1/experiment_h1_v2.py`

Purpose:
- adds shock-magnitude sweep;
- combines execution-speed asymmetry with different fundamental-information access.

Outputs:
- `results/h1/tables/h1_sweep.csv`
- `results/h1/raw/h1_raw_dp*.csv` for new runs
- `results/h1/figures/h1_shock_sweep.png`
- `results/h1/figures/h1_results_v2.png`

### `experiments/h1/experiment_h1_v3.py`

Purpose:
- replaces `general_states()` with direct metrics:
  - `vol_ratio`
  - `spread_ratio`
  - `max_drawdown`
  - `recovery_time`
  - `mm_panic_ratio`

Outputs:
- `results/h1/raw/h1_v3_raw.csv`
- `results/h1/figures/h1_v3_results.png`
- `results/h1/figures/h1_v3_price_examples.png`

### `experiments/h1/experiment_h1_v4.py`

Purpose:
- reruns the v3 design with more simulations;
- checks whether the weak / inverse H1 signal was noise.

Outputs:
- `results/h1/raw/h1_v4_raw.csv`
- `results/h1/figures/h1_v4_results.png`

### `experiments/h1/experiment_h1_v5.py`

Purpose:
- isolates pure execution-speed priority;
- keeps information access equal across all agents.

Outputs:
- `results/h1/raw/h1_v5_raw.csv`
- `results/h1/figures/h1_v5_results.png`

### `experiments/h1/experiment_h1_v6.py`

Purpose:
- adds MarketMaker inventory-limit sensitivity;
- tests whether a weaker MarketMaker makes the fast-share effect visible.

Outputs:
- `results/h1/raw/h1_v6_raw.csv`
- `results/h1/figures/h1_v6_results.png`
- `results/h1/figures/h1_v6_heatmap_panic.png`
- `results/h1/figures/h1_v6_heatmap_vol.png`

## Result Files Currently Stored

Raw results:
- `results/h1/raw/h1_raw.csv`
- `results/h1/raw/h1_v3_raw.csv`
- `results/h1/raw/h1_v4_raw.csv`
- `results/h1/raw/h1_v5_raw.csv`
- `results/h1/raw/h1_v6_raw.csv`

Tables:
- `results/h1/tables/h1_sweep.csv`

Figures:
- `results/h1/figures/h1_baseline_check_prices_volatility.png`
- `results/h1/figures/h1_prices.png`
- `results/h1/figures/h1_results.png`
- `results/h1/figures/h1_results_v2.png`
- `results/h1/figures/h1_shock_sweep.png`
- `results/h1/figures/h1_v3_price_examples.png`
- `results/h1/figures/h1_v3_results.png`
- `results/h1/figures/h1_v4_results.png`
- `results/h1/figures/h1_v5_results.png`
- `results/h1/figures/h1_v6_heatmap_panic.png`
- `results/h1/figures/h1_v6_heatmap_vol.png`
- `results/h1/figures/h1_v6_results.png`

## Main Experimental Findings

The early H1 designs do not provide strong support for the hypothesis.

Key findings:
- random assignment of fast execution priority does not create a stable monotonic HFT effect;
- `general_states()` is too noisy for H1 inference and should not be used as the main metric;
- direct metrics are more informative, especially `vol_ratio` and `spread_ratio`;
- adding more runs in v4 does not recover the expected H1 pattern;
- isolating pure speed in v5 still does not produce the predicted destabilization;
- MarketMaker softlimit affects liquidity and panic diagnostics, but not in a way that depends clearly on `fast_share`.

The main conclusion of this branch is diagnostic: the early H1 implementation was not sufficient to confirm H1. This motivated later H1 work on a different branch with a more realistic trend-following mechanism.

## Important Caveats

- This branch should be treated as the early H1 experiment history.
- It does not contain the final H1 result.
- It does not contain H1 v7-v9.
- It does not contain the unified H1 speed/delay/combined grids.
- The final H1 interpretation should use the later H1 branch.

## How to Run

Run scripts from the repository root:

```bash
python3 experiments/h1/baseline_check.py
python3 experiments/h1/experiment_h1.py
python3 experiments/h1/experiment_h1_v2.py
python3 experiments/h1/experiment_h1_v3.py
python3 experiments/h1/experiment_h1_v4.py
python3 experiments/h1/experiment_h1_v5.py
python3 experiments/h1/experiment_h1_v6.py
```

Outputs are written under `results/h1/`.
