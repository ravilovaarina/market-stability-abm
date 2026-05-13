# H2 Paired Statistical Tests

Input: `h2_postshock_volume_paired_diffs.csv`.

All differences are `event time - calendar time`. For instability metrics, negative values mean event time is lower / more stable.

Tests:
- bootstrap 95% CI for the mean paired difference;
- one-sided Wilcoxon signed-rank test with alternative `event time < calendar time`;
- exact sign test for whether negative differences are more frequent than positive ones.

## Results

| phi | metric | mean diff | 95% CI | negative share | effect size | Wilcoxon p (<0) | Holm p | BH p | conclusion |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---|
| 0.0 | RV per volume | -1.615e-05 | [-3.459e-05, 2.166e-06] | 0.66 | 0.3788 | 0.0095 | 0.2955 | 0.0572 | not significant / mixed |
| 0.0 | RV per trade | -5.873e-05 | [-1.204e-04, 2.165e-06] | 0.66 | 0.3945 | 0.0072 | 0.2317 | 0.0521 | not significant / mixed |
| 0.0 | Vol / sqrt(volume) | -8.388e-06 | [-8.432e-05, 7.105e-05] | 0.56 | 0.0933 | 0.2860 | 1.0000 | 0.4119 | not significant / mixed |
| 0.0 | Equal-volume vol ratio | -2.4175 | [-4.0585, -0.8358] | 0.70 | 0.5200 | 5.322e-04 | 0.0186 | 0.0096 | event time lower |
| 0.0 | Calendar-style vol ratio | -0.7100 | [-1.0430, -0.3623] | 0.72 | 0.6031 | 5.952e-05 | 0.0021 | 0.0021 | event time lower |
| 0.0 | Spread ratio | -0.5606 | [-1.0164, -0.1049] | 0.70 | 0.4463 | 0.0027 | 0.0919 | 0.0324 | event time lower |
| 0.2 | RV per volume | 2.297e-06 | [-1.774e-05, 2.386e-05] | 0.54 | 0.0494 | 0.3834 | 1.0000 | 0.4929 | not significant / mixed |
| 0.2 | RV per trade | 1.056e-05 | [-5.623e-05, 8.357e-05] | 0.54 | 0.0494 | 0.3834 | 1.0000 | 0.4929 | not significant / mixed |
| 0.2 | Vol / sqrt(volume) | 9.011e-05 | [1.059e-05, 1.746e-04] | 0.50 | -0.2580 | 0.9441 | 1.0000 | 0.9441 | event time higher |
| 0.2 | Equal-volume vol ratio | -0.4021 | [-3.1841, 2.3986] | 0.60 | 0.2282 | 0.0815 | 1.0000 | 0.1833 | not significant / mixed |
| 0.2 | Calendar-style vol ratio | -0.2575 | [-0.9166, 0.4281] | 0.62 | 0.1969 | 0.1149 | 1.0000 | 0.2433 | not significant / mixed |
| 0.2 | Spread ratio | -0.1969 | [-1.0252, 0.6489] | 0.58 | 0.1686 | 0.1522 | 1.0000 | 0.2823 | not significant / mixed |
| 0.4 | RV per volume | -6.415e-06 | [-3.551e-05, 2.384e-05] | 0.58 | 0.1012 | 0.2699 | 1.0000 | 0.4097 | not significant / mixed |
| 0.4 | RV per trade | -2.166e-05 | [-1.183e-04, 7.633e-05] | 0.58 | 0.0996 | 0.2731 | 1.0000 | 0.4097 | not significant / mixed |
| 0.4 | Vol / sqrt(volume) | 6.234e-05 | [-3.245e-05, 1.636e-04] | 0.40 | -0.1765 | 0.8610 | 1.0000 | 0.9311 | not significant / mixed |
| 0.4 | Equal-volume vol ratio | -1.8137 | [-6.2410, 2.2478] | 0.58 | 0.1655 | 0.1568 | 1.0000 | 0.2823 | not significant / mixed |
| 0.4 | Calendar-style vol ratio | -0.0861 | [-0.7135, 0.5323] | 0.54 | 0.0541 | 0.3724 | 1.0000 | 0.4929 | not significant / mixed |
| 0.4 | Spread ratio | 0.1766 | [-0.6073, 0.9888] | 0.48 | -0.0337 | 0.5834 | 1.0000 | 0.6861 | not significant / mixed |
| 0.6 | RV per volume | -2.986e-05 | [-6.213e-05, 1.214e-06] | 0.64 | 0.2894 | 0.0378 | 0.9067 | 0.1046 | not significant / mixed |
| 0.6 | RV per trade | -1.026e-04 | [-2.118e-04, 3.191e-06] | 0.62 | 0.2941 | 0.0354 | 0.8853 | 0.1046 | not significant / mixed |
| 0.6 | Vol / sqrt(volume) | 2.687e-05 | [-7.014e-05, 1.268e-04] | 0.44 | -0.0588 | 0.6420 | 1.0000 | 0.7222 | not significant / mixed |
| 0.6 | Equal-volume vol ratio | -1.6553 | [-5.3090, 2.4477] | 0.62 | 0.3051 | 0.0304 | 0.7891 | 0.0993 | not significant / mixed |
| 0.6 | Calendar-style vol ratio | -0.4702 | [-1.1086, 0.1359] | 0.60 | 0.1875 | 0.1265 | 1.0000 | 0.2531 | not significant / mixed |
| 0.6 | Spread ratio | -0.4375 | [-1.1942, 0.3365] | 0.64 | 0.2675 | 0.0506 | 1.0000 | 0.1213 | not significant / mixed |
| 0.8 | RV per volume | -2.025e-05 | [-5.556e-05, 1.355e-05] | 0.58 | 0.1231 | 0.2274 | 1.0000 | 0.3721 | not significant / mixed |
| 0.8 | RV per trade | -7.268e-05 | [-1.945e-04, 4.036e-05] | 0.58 | 0.1263 | 0.2216 | 1.0000 | 0.3721 | not significant / mixed |
| 0.8 | Vol / sqrt(volume) | 6.736e-05 | [-3.350e-05, 1.666e-04] | 0.48 | -0.1906 | 0.8794 | 1.0000 | 0.9311 | not significant / mixed |
| 0.8 | Equal-volume vol ratio | -6.7002 | [-14.0759, 0.1878] | 0.72 | 0.4118 | 0.0053 | 0.1743 | 0.0475 | event time lower |
| 0.8 | Calendar-style vol ratio | -0.7970 | [-1.6444, 0.0344] | 0.66 | 0.3114 | 0.0277 | 0.7488 | 0.0993 | not significant / mixed |
| 0.8 | Spread ratio | -1.1436 | [-2.4635, 0.1558] | 0.56 | 0.3239 | 0.0231 | 0.6454 | 0.0922 | not significant / mixed |
| 1.0 | RV per volume | 1.093e-05 | [-5.039e-05, 7.183e-05] | 0.48 | -0.0369 | 0.5908 | 1.0000 | 0.6861 | not significant / mixed |
| 1.0 | RV per trade | 2.676e-05 | [-1.873e-04, 2.342e-04] | 0.48 | -0.0290 | 0.5721 | 1.0000 | 0.6861 | not significant / mixed |
| 1.0 | Vol / sqrt(volume) | 1.282e-04 | [-1.751e-05, 2.803e-04] | 0.40 | -0.2298 | 0.9214 | 1.0000 | 0.9441 | not significant / mixed |
| 1.0 | Equal-volume vol ratio | -7.1723 | [-12.4305, -2.4491] | 0.58 | 0.3271 | 0.0220 | 0.6376 | 0.0922 | event time lower |
| 1.0 | Calendar-style vol ratio | -0.7817 | [-1.5252, -0.0140] | 0.62 | 0.3537 | 0.0145 | 0.4348 | 0.0745 | event time lower |
| 1.0 | Spread ratio | -0.6599 | [-1.5513, 0.2682] | 0.62 | 0.2675 | 0.0506 | 1.0000 | 0.1213 | not significant / mixed |

## Interpretation

Across the primary H2 metrics, 13 out of 36 phi-metric cells show uncorrected statistical evidence that event time is lower than calendar time by either bootstrap CI or one-sided Wilcoxon at the 5% level.
After Benjamini-Hochberg correction across all H2 paired tests, 4 Wilcoxon cells remain significant; after Holm correction, 2 remain significant.
1 cells show bootstrap evidence that event time is higher.

The result is therefore not a universal stabilization result. It is a regime-dependent clock effect: event-time measurement can reduce some post-shock volatility/spread measures, but the evidence is uneven across HFT shares and metrics.
