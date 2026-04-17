# Threshold Validation Report

This report validates whether the 30% rule (`1.3x baseline`) is a reasonable
working definition of a tipping point across several representative regimes.

Selected regimes:
- `speed_x2`: grid=`speed`, speed_mult=`2`, info_lag=`0`. Key clean speed regime.
- `combined_speed_x3_lag1`: grid=`combined`, speed_mult=`3`, info_lag=`1`. Strong combined regime with stable tipping.
- `combined_speed_x3_lag5`: grid=`combined`, speed_mult=`3`, info_lag=`5`. Combined regime where 1.3x tipping disappears.

## Summary table

| Regime | Baseline vol_ratio | 1.1x | 1.2x | 1.3x | 1.4x | 1.5x |
|---|---:|---:|---:|---:|---:|---:|
| speed_x2 | 1.75 | 0.1 | 0.1 | 0.2 | 0.2 | 0.4 |
| combined_speed_x3_lag1 | 2.18 | 0.2 | 0.2 | 0.2 | 0.2 | 0.6 |
| combined_speed_x3_lag5 | 2.70 | 0.6 | 0.6 | — | — | — |

## Interpretation

- `1.3x` should not be presented as a mathematically unique threshold.
- It can be presented as the main working threshold because it is stricter than `1.1x` and `1.2x`,
  which often trigger very early crossings, but less restrictive than `1.5x`, which can remove
  tipping points even in meaningful regimes.
- The strongest empirical justification comes from `speed_x2`.
- The combined regimes show that the same threshold remains interpretable outside the clean speed-only setup,
  but not every regime produces a tipping point at `1.3x`.
