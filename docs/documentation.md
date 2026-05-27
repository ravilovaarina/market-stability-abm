# 1D-ABM H3 Branch Documentation

## Project Overview

**Title:** Financial Market Stability under Heterogeneous Information Speeds: An Agent-Based Modeling Approach

**Author:** Ravilova Arina Kharisovna, Group BPAD246, 2nd year, HSE University, Faculty of Computer Science, Bachelor's Programme "Data Science and Business Analytics"

**Supervisor:** Lukyanchenko Petr Pavlovich, Head of Lab, Faculty of Computer Science, HSE University

**Original codebase:** https://github.com/bognik002/1D-ABM

This branch contains the H3 analysis built on top of the H1 unified simulator. The core model is an agent-based financial market with a central limit order book, heterogeneous traders, exogenous market shocks, and post-shock stability metrics.

## Branch Purpose

The `h3-volatility-clustering` branch studies whether delayed information and weak liquidity jointly worsen market stability after a negative price shock.

The H3 work has two stages:

1. **Original H3 framing:** information delay combined with liquidity constraints should increase post-shock volatility clustering.
2. **Revised H3 framing:** information delay combined with a thin order book should weaken shock absorption, measured through deeper drawdown, slower recovery, and worse stabilisation after the shock.

The final interpretation is partial support. The volatility-clustering interaction is not robust as a systematic positive effect. The shock-absorption framing is better supported, mainly through maximum drawdown in the worst-case regime.

## Repository Structure

```text
1D-ABM/
├── AgentBasedModel/                 # Core simulator package
├── experiments/
│   ├── h1/                          # H1 baseline and support experiments
│   ├── h3/                          # H3 experiment and analysis scripts
│   ├── robustness/                  # H1 follow-up and robustness scripts
│   └── paths.py                     # Shared project paths
├── results/
│   ├── h1/                          # H1 baseline outputs used as context
│   └── h3/                          # H3 raw data, tables, and figures
├── docs/
│   └── documentation.md             # Current branch documentation
├── archives/                        # Historical zipped snapshots
├── requirements.txt
└── .gitignore
```

## H3 Scripts

### Exploratory Softlimit Experiment

Script:

```bash
python experiments/h3/experiment_h3_volatility_clustering.py
```

Rebuild tables and figures from existing raw data:

```bash
python experiments/h3/experiment_h3_volatility_clustering.py --plot-from-raw
```

Purpose:

- varies `info_lag`, `hft_frac`, and MarketMaker `softlimit`;
- uses `softlimit` as the first liquidity proxy;
- measures post-shock volatility clustering and standard H1 stability metrics.

Outputs:

- raw data: `results/h3/clustering/raw/h3_clustering_raw.csv`
- tables: `results/h3/clustering/tables/`
- figures: `results/h3/clustering/figures/`

### Softlimit Interaction Bootstrap

Script:

```bash
python experiments/h3/experiment_h3_interaction_bootstrap.py
```

Purpose:

- reuses `h3_clustering_raw.csv`;
- estimates uncertainty around the factorial interaction:

```text
combined - delay_only - liquidity_only + baseline
```

Output:

- `results/h3/clustering/tables/h3_clustering_interactions_bootstrap.csv`

### Clean Order-Book Depth Experiment

Script:

```bash
python experiments/h3/experiment_h3_liquidity_depth.py
```

Rebuild tables and figures from existing raw data:

```bash
python experiments/h3/experiment_h3_liquidity_depth.py --plot-from-raw
```

Purpose:

- replaces `softlimit` with initial `ExchangeAgent.volume`;
- keeps MarketMaker `softlimit=100`;
- treats book depth as the cleaner liquidity proxy.

Outputs:

- raw data: `results/h3/depth/raw/h3_depth_raw.csv`
- tables: `results/h3/depth/tables/`
- figures: `results/h3/depth/figures/`

### Depth Interaction Bootstrap

Script:

```bash
python experiments/h3/experiment_h3_depth_bootstrap.py
```

Output:

- `results/h3/depth/tables/h3_depth_interactions_bootstrap.csv`

### Confirmatory 2x2 Experiment

Script:

```bash
python experiments/h3/experiment_h3_confirmatory_2x2.py
```

Rebuild outputs from existing raw data:

```bash
python experiments/h3/experiment_h3_confirmatory_2x2.py --plot-from-raw
```

Purpose:

- focused test of the revised H3;
- varies `info_lag` in `{0, 1}`;
- varies `book_volume` in `{300, 1500}`;
- uses `hft_frac` in `{0.2, 0.4}`;
- runs 200 paired repetitions by default.

Outputs:

- raw data: `results/h3/confirmatory/raw/h3_confirmatory_raw.csv`
- tables: `results/h3/confirmatory/tables/`
- figures: `results/h3/confirmatory/figures/`

### Shock-Absorption Reanalysis

Script:

```bash
python experiments/h3/experiment_h3_shock_absorption.py
```

Purpose:

- reuses the confirmatory raw data;
- tests whether the worst-case regime is worse than the baseline regime;
- reports OLS HC3 interaction tests, Mann-Whitney worst-vs-best comparisons, and cell means.

Outputs:

- tables: `results/h3/shock_absorption/tables/`
- figure: `results/h3/shock_absorption/figures/h3_shock_absorption.png`

### Final H3 Summary

Script:

```bash
python experiments/h3/experiment_h3_final_summary.py
```

Purpose:

- combines completed H3 outputs;
- applies Holm and Benjamini-Hochberg multiple-testing corrections;
- summarises support for original and revised H3.

Outputs:

- tables: `results/h3/summary/tables/`
- figure: `results/h3/summary/figures/h3_final_summary.png`

## Main Metrics

Standard market-stability metrics:

- `vol_ratio`: post-shock volatility divided by pre-shock volatility;
- `spread_ratio`: post-shock relative spread divided by pre-shock relative spread;
- `max_drawdown`: maximum post-shock price drop relative to the pre-shock price;
- `recovery_time`: iterations until price recovers close to the pre-shock level;
- `mm_panic_ratio`: share of post-shock iterations with MarketMaker stress.

Volatility-clustering metrics:

- `acf_abs_ret_1`: autocorrelation of absolute returns at lag 1;
- `acf_abs_ret_5`: autocorrelation of absolute returns at lag 5;
- `vol_persistence`: persistence of rolling volatility;
- `high_vol_cluster_share`: share of post-shock windows above the pre-shock high-volatility threshold.

Shock-absorption metrics:

- `stabilization_price`;
- `stabilization_price_ratio`;
- `stabilization_gap`;
- `max_drawdown`;
- `recovery_time`.

## Statistical Tests

Bootstrap confidence intervals:

- used for uncertainty around means and factorial interaction terms;
- appropriate because simulation metrics are non-normal and can be skewed.

OLS with HC3 standard errors:

- used in the confirmatory and shock-absorption tests;
- model includes delay, thin-book indicator, their interaction, and run fixed effects;
- HC3 is used because simulation residuals can be heteroskedastic.

Mann-Whitney U tests:

- used for direct distributional comparison of best-case and worst-case regimes;
- one-sided alternative tests whether the worst-case regime produces larger instability metrics.

Multiple-testing correction:

- Holm correction controls family-wise error rate;
- Benjamini-Hochberg correction controls false discovery rate.

## Key Results

Original H3, softlimit liquidity proxy:

- information delay is associated with higher short-run volatility clustering in several regimes;
- the delay x softlimit interaction is mixed and not robust;
- the original superadditive interaction claim is not supported as a general mechanism.

Clean H3, order-book depth proxy:

- order-book depth is a cleaner liquidity proxy than `softlimit`;
- delay remains associated with higher ACF-based clustering;
- the delay x thin-book interaction remains weak and sparse after bootstrap inference.

Confirmatory 2x2 and shock absorption:

- the focused 2x2 design does not robustly confirm the original volatility-clustering interaction;
- the revised shock-absorption interpretation has partial support;
- the clearest supporting result is larger `max_drawdown` in the delayed thin-book regime.

## Current Source of Truth

Use these files as the main H3 source of truth:

- `results/h3/confirmatory/raw/h3_confirmatory_raw.csv`
- `results/h3/confirmatory/tables/h3_confirmatory_ols_hc3.csv`
- `results/h3/shock_absorption/tables/h3_shock_absorption_ols.csv`
- `results/h3/shock_absorption/tables/h3_shock_absorption_mw.csv`
- `results/h3/summary/tables/h3_final_summary_clustering_interactions.csv`
- `results/h3/summary/tables/h3_final_summary_shock_absorption.csv`
- `results/h3/summary/figures/h3_final_summary.png`

The exploratory clustering and depth grids are useful background, but the confirmatory and shock-absorption outputs carry the final interpretation.

## H1 Support Files

The H3 scripts reuse H1 infrastructure from:

- `experiments/h1/experiment_unified.py`
- `AgentBasedModel/`

H1 outputs kept for context are stored under:

- `results/h1/raw/`
- `results/h1/figures/`
- `results/h1/robustness/`

These files are not the main H3 evidence, but they document the baseline environment that H3 builds on.

## Running From the Project Root

Recommended commands:

```bash
python -m compileall AgentBasedModel experiments
python experiments/h3/experiment_h3_volatility_clustering.py --plot-from-raw
python experiments/h3/experiment_h3_liquidity_depth.py --plot-from-raw
python experiments/h3/experiment_h3_confirmatory_2x2.py --plot-from-raw
python experiments/h3/experiment_h3_shock_absorption.py
python experiments/h3/experiment_h3_final_summary.py
```

New outputs are written into `results/`, not into the repository root.

## Notes

- The core simulator remains in `AgentBasedModel/`.
- Historical zipped snapshots are kept in `archives/`.
- Generated Python caches and local virtual environments are ignored by Git.
- The branch is structured so that the root directory contains project-level files only.
