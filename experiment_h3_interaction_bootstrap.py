#!/usr/bin/env python3
"""
Bootstrap inference for H3 interaction terms.

This script does not rerun simulations. It reuses h3_clustering_raw.csv and
estimates uncertainty around the 2x2 factorial interaction:

    combined - delay_only - liquidity_only + baseline

The bootstrap resamples runs within each of the four cells independently.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd


DEFAULT_RAW = "h3_clustering_raw.csv"
DEFAULT_OUT = "h3_clustering_interactions_bootstrap.csv"
DEFAULT_N_BOOT = 1000
DEFAULT_SEED = 20260420
BASELINE_LAG = 0
BASELINE_SOFTLIMIT = 100

METRICS = [
    "acf_abs_ret_1",
    "acf_abs_ret_5",
    "vol_persistence",
    "high_vol_cluster_share",
    "vol_ratio",
]


def cell_values(
    raw: pd.DataFrame,
    *,
    hft_frac: float,
    info_lag: int,
    softlimit: int,
    metric: str,
) -> np.ndarray:
    sub = raw[
        (raw["hft_frac"].round(10) == round(float(hft_frac), 10))
        & (raw["info_lag"].astype(int) == int(info_lag))
        & (raw["softlimit"].astype(int) == int(softlimit))
    ]
    values = sub[metric].to_numpy(dtype=float)
    if len(values) == 0:
        raise ValueError(
            f"Missing cell for phi={hft_frac}, lag={info_lag}, "
            f"softlimit={softlimit}, metric={metric}"
        )
    return values


def bootstrap_interaction(
    base: np.ndarray,
    delay: np.ndarray,
    liquidity: np.ndarray,
    combined: np.ndarray,
    *,
    n_boot: int,
    rng: np.random.Generator,
) -> Tuple[float, float, float, float, float]:
    point = float(combined.mean() - delay.mean() - liquidity.mean() + base.mean())

    samples = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        b = rng.choice(base, size=len(base), replace=True).mean()
        d = rng.choice(delay, size=len(delay), replace=True).mean()
        l = rng.choice(liquidity, size=len(liquidity), replace=True).mean()
        c = rng.choice(combined, size=len(combined), replace=True).mean()
        samples[i] = c - d - l + b

    ci_low, ci_high = np.percentile(samples, [2.5, 97.5])
    # Two-sided bootstrap sign p-value around zero.
    p_lower = float(np.mean(samples <= 0))
    p_upper = float(np.mean(samples >= 0))
    p_two_sided = min(1.0, 2.0 * min(p_lower, p_upper))
    return point, float(ci_low), float(ci_high), p_two_sided, float(samples.mean())


def compute_bootstrap(
    raw: pd.DataFrame,
    *,
    metrics: Iterable[str],
    n_boot: int,
    seed: int,
    baseline_lag: int = BASELINE_LAG,
    baseline_softlimit: int = BASELINE_SOFTLIMIT,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows: List[Dict[str, float]] = []

    hft_fracs = sorted(float(x) for x in raw["hft_frac"].unique())
    lags = [int(x) for x in sorted(raw["info_lag"].unique()) if int(x) != baseline_lag]
    softlimits = [
        int(x)
        for x in sorted(raw["softlimit"].unique())
        if int(x) != baseline_softlimit
    ]

    for phi in hft_fracs:
        for lag in lags:
            for softlimit in softlimits:
                for metric in metrics:
                    base = cell_values(
                        raw,
                        hft_frac=phi,
                        info_lag=baseline_lag,
                        softlimit=baseline_softlimit,
                        metric=metric,
                    )
                    delay = cell_values(
                        raw,
                        hft_frac=phi,
                        info_lag=lag,
                        softlimit=baseline_softlimit,
                        metric=metric,
                    )
                    liquidity = cell_values(
                        raw,
                        hft_frac=phi,
                        info_lag=baseline_lag,
                        softlimit=softlimit,
                        metric=metric,
                    )
                    combined = cell_values(
                        raw,
                        hft_frac=phi,
                        info_lag=lag,
                        softlimit=softlimit,
                        metric=metric,
                    )
                    point, ci_low, ci_high, p_value, boot_mean = bootstrap_interaction(
                        base,
                        delay,
                        liquidity,
                        combined,
                        n_boot=n_boot,
                        rng=rng,
                    )
                    rows.append(
                        {
                            "hft_frac": phi,
                            "info_lag": lag,
                            "softlimit": softlimit,
                            "metric": metric,
                            "n_boot": n_boot,
                            "n_base": len(base),
                            "n_delay": len(delay),
                            "n_liquidity": len(liquidity),
                            "n_combined": len(combined),
                            "interaction_point": point,
                            "interaction_boot_mean": boot_mean,
                            "ci_low": ci_low,
                            "ci_high": ci_high,
                            "p_two_sided": p_value,
                            "ci_excludes_zero": bool(ci_low > 0 or ci_high < 0),
                            "positive_point": bool(point > 0),
                        }
                    )

    return pd.DataFrame(rows)


def summarize(result: pd.DataFrame) -> None:
    print("Bootstrap H3 interaction summary")
    print(f"rows: {len(result)}")
    for metric, sub in result.groupby("metric", sort=False):
        positive_share = float((sub["interaction_point"] > 0).mean())
        ci_excludes = int(sub["ci_excludes_zero"].sum())
        positive_sig = int(
            ((sub["ci_low"] > 0) & (sub["ci_high"] > 0)).sum()
        )
        negative_sig = int(
            ((sub["ci_low"] < 0) & (sub["ci_high"] < 0)).sum()
        )
        print(
            f"{metric}: positive_share={positive_share:.3f}, "
            f"mean_point={sub['interaction_point'].mean():.4f}, "
            f"ci_excludes_zero={ci_excludes}/{len(sub)}, "
            f"positive_ci={positive_sig}, negative_ci={negative_sig}"
        )

    headline = result[result["metric"].isin(["acf_abs_ret_1", "acf_abs_ret_5"])]
    print("\nTop positive ACF interactions by point estimate:")
    cols = [
        "metric",
        "info_lag",
        "softlimit",
        "hft_frac",
        "interaction_point",
        "ci_low",
        "ci_high",
        "p_two_sided",
        "ci_excludes_zero",
    ]
    print(
        headline.sort_values("interaction_point", ascending=False)[cols]
        .head(10)
        .to_string(index=False)
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap H3 interaction terms from raw simulation output."
    )
    parser.add_argument("--raw", default=DEFAULT_RAW)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--n-boot", type=int, default=DEFAULT_N_BOOT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw_path = Path(args.raw)
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw file not found: {raw_path}")

    raw = pd.read_csv(raw_path)
    result = compute_bootstrap(
        raw,
        metrics=METRICS,
        n_boot=args.n_boot,
        seed=args.seed,
    )
    result.to_csv(args.out, index=False)
    print(f"Saved: {args.out}")
    summarize(result)


if __name__ == "__main__":
    main()
