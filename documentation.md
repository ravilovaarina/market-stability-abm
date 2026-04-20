# H2 Event-Time / Volume-Clock Experiment Documentation

## Branch Purpose

This branch is intended for **Hypothesis H2**:

> Updating the market in event time, rather than ordinary calendar time, can change market resilience
> and shift the tipping point at which latency heterogeneity becomes destabilizing.

The branch starts from the clean baseline simulator. It should not inherit the H1 unified experiment files,
Grid 3 reruns, or other H1-specific artifacts. The H2 experiment is implemented as a standalone experiment
file so that the original simulator architecture remains easy to inspect.

---

## Why H2 Needs a Separate Experiment

The baseline simulator uses **calendar time**:

```python
for it in range(n_iter):
    events
    capture
    behavioural update
    trader calls
    payments
    dividend update
```

In that design, one model tick is just one fixed iteration. This means that information updates,
sentiment updates, dividend payments, and state recording happen after the same amount of clock time,
regardless of how much trading actually occurred.

H2 asks whether the result changes if the model uses **event time**:

```text
one model tick = enough trading has occurred
```

The operational version used here is a **volume clock**:

```text
one event-time tick ends when cumulative executed volume reaches Vstar
```

This follows the idea from the volume-clock literature: market stress may be better understood by
equal-volume intervals than by equal-calendar intervals.

---

## Research Question for This Experiment

The experiment asks:

> If we keep the same speed-heterogeneous market structure as in H1, does switching from calendar time
> to event time move the tipping point phi*?

More concretely:

```text
phi*_calendar vs phi*_event_time
```

If event time makes the market more resilient, we expect:

```text
phi*_event_time > phi*_calendar
```

That would mean the market can tolerate a larger share of fast traders before crossing the volatility
threshold.

---

## Key Terms

### `phi`

`phi` is the share of chartist agents that receive the fast execution advantage.

Example with 10 chartists:

```text
phi = 0.0 -> 0 fast chartists
phi = 0.2 -> 2 fast chartists
phi = 1.0 -> 10 fast chartists
```

### Calendar Time

Calendar time is the baseline mode:

```text
one tick = one fixed simulator iteration
```

Every tick has one behavioural update and one round of trading calls.

### Event Time

Event time is the H2 mode:

```text
one tick = trading continues until executed volume >= Vstar
```

The number of inner trading rounds can vary from tick to tick.

### `Vstar`

`Vstar` is the executed-volume threshold that defines one event-time tick.

Example:

```text
Vstar = 50
```

means:

```text
keep letting agents trade inside this tick until at least 50 units have been executed
```

### Volume Units

In this simulator, one volume unit is **one share / one asset unit executed in a matched trade**.

Agents submit orders with integer quantities, usually from 1 to 5. When an incoming order is matched
against the opposite side of the book, the executed volume is the matched quantity:

```text
executed_qty = quantity_before_matching - quantity_after_matching
```

Examples:

```text
market buy order qty=5 fully executed -> executed volume = 5
market sell order qty=3 partially executed for 2 -> executed volume = 2
limit order crossing the spread and executing qty=4 -> executed volume = 4
limit order posted but not executed -> executed volume = 0
```

So `Vstar = 13` means:

```text
end the event-time tick after approximately 13 shares/assets have actually traded
```

It is not the number of orders and not the number of agents. It is cumulative matched quantity.

### Tipping Point `phi*`

The tipping point is the first `phi` where volatility ratio crosses the chosen threshold:

```text
threshold = 1.3 * baseline_vol_ratio
baseline_vol_ratio = mean vol_ratio at phi = 0 in the same regime
```

Then:

```text
phi* = first phi where mean vol_ratio(phi) >= threshold
```

---

## Clean Experimental Architecture

The experiment is implemented in:

```text
experiment_h2_event_time.py
```

It is standalone and does not modify the core package files.

The file defines:

1. `VolumeExchangeAgent`
2. safe H2 trader classes
3. calendar-time simulation loop
4. event-time simulation loop
5. metrics
6. statistical tests
7. plots
8. CSV outputs

---

## Component 1: `VolumeExchangeAgent`

The baseline `ExchangeAgent` executes orders but does not record executed volume.
H2 requires volume accounting, so the experiment defines:

```python
class VolumeExchangeAgent(ExchangeAgent):
    ...
```

It adds counters:

```python
self.executed_volume_tick
self.executed_volume_total
self.executed_trades_tick
self.executed_trades_total
```

At the beginning of each event-time tick:

```python
exchange.reset_tick_counters()
```

Whenever an order is matched:

```python
executed_qty = quantity_before - quantity_after
exchange._record_execution(executed_qty)
```

This keeps the volume-clock mechanism local to the experiment file.

### H1 Infrastructure Fixes Reused in H2

After comparing this branch with the H1 `hft-intraiter` branch, several H1 changes were classified as
general infrastructure fixes rather than H1-only logic. H2 reuses them locally inside
`experiment_h2_event_time.py`:

1. **Safe empty-book price handling.**
   If one side of the book is empty, `VolumeExchangeAgent.price()` returns the last valid midpoint and
   records the situation through `book_depleted_rate`.

2. **`OrderList.insert()` empty-list fix.**
   The baseline linked-list insertion method missed a `return` after inserting into an empty list. H1 fixed
   this because stress regimes can deplete a book side and later rebuild it. H2 applies the same fix locally
   via `patch_order_list_insert()`.

3. **Limit orders can rebuild a depleted book side.**
   In H1, if `spread()` is unavailable, a new limit order is inserted into its side of the book instead of
   being discarded. H2 now follows the same behavior. This matters because event-time stress can temporarily
   empty one side of the order book; the book should be allowed to recover endogenously.

4. **Fast/slow activation with `speed_multiplier`.**
   H2 uses the same fast-first trading mechanism as unified H1, so the calendar-time baseline is closer to
   the H1 speed grid.

The H2 experiment does **not** reuse H1's delayed-information machinery by default (`info_lag`,
`delayed_spread`, `delayed_price`) because H2 is meant to isolate the timekeeping mechanism. Those components
belong to H1 delay/combined grids, not to the clean event-time comparison.

---

## Component 2: Safe H2 Trader Classes

The baseline code can fail if one side of the book becomes empty. H2 may produce more intense trading,
especially inside event-time ticks, so the experiment uses safe subclasses:

- `SafeFundamentalist`
- `TrendChartist`
- `SafeMarketMaker`

These preserve the original economic logic but add checks such as:

```python
spread = self.market.spread()
if spread is None:
    return
```

### Why `TrendChartist` Is Used

The original baseline `Chartist` is contrarian:

- after price falls, pessimists tend to become optimists;
- this creates stabilizing buy pressure.

For the H1/H2 tipping-point mechanism, the relevant behavior is trend-following:

- after price falls, optimists should become pessimists;
- this amplifies the shock.

Therefore the H2 experiment uses `TrendChartist`, where the exponent signs are corrected.

---

## Component 3: Population Design

The population follows the unified H1 speed-grid configuration:

```text
10 Fundamentalists
10 TrendChartists
5 Random/noisy agents
1 MarketMaker
```

Among the 10 chartists:

```text
n_fast = round(phi * 10)
```

Fast chartists receive:

```python
trader.speed = "fast"
```

Slow chartists receive:

```python
trader.speed = "slow"
```

Fundamentalists and the market maker are slow by default.
Random agents are also slow by default and have no execution advantage.

### Important Correction After the First H2 Run

An early H2 run was performed with:

```text
10 Fundamentalists + 10 TrendChartists + 1 MarketMaker
```

that is, without the 5 Random/noisy agents used in the unified H1 speed experiment.
That run is useful as a preliminary debugging run, but it should **not** be interpreted as the final
H2 comparison against H1, because the calendar-time baseline was not the same population as in the
H1 speed grid.

The corrected H2 code now uses 5 Random agents by default:

```text
--n-random 5
```

For direct comparison with the strongest H1 unified speed result, run H2 with:

```bash
python3 experiment_h2_event_time.py --speed-multiplier 2
```

For comparison with the pure fast-first v9-style setting, run:

```bash
python3 experiment_h2_event_time.py --speed-multiplier 1
```

The H2 result should be reported only after the corrected population is rerun.

### Status of Existing Result Files After Population Correction

Any `h2_event_time_*.csv` / `h2_event_time_*.png` files produced before this correction should be
treated as **preliminary**. They are not invalid as debugging evidence, but they do not answer the
final H2 question because the calendar-time baseline used a different population from the H1 speed grid.

---

## Component 4: Calendar-Time Mode

Calendar mode is the comparison baseline.

For each tick:

1. apply scheduled events;
2. capture state;
3. update behaviour once;
4. call fast chartists before slow agents;
5. pay dividends and interest once;
6. generate the next dividend.

This mode keeps the same fixed time grid as the baseline simulator, but uses the H1 speed mechanism
so that tipping points can be compared across timekeeping regimes.

---

## Component 5: Event-Time Mode

Event-time mode uses the same external tick count, but each tick contains a variable number of
inner trading rounds.

For each event-time tick:

1. apply scheduled events once;
2. capture state once;
3. update behaviour once;
4. reset tick volume counters;
5. repeatedly call traders until:

```text
executed_volume_tick >= Vstar
```

6. if the threshold is not reached after `max_sub_iters`, stop the tick and record that threshold was missed;
7. pay dividends and interest once;
8. generate the next dividend once.

### Why Payments Happen Once Per Event Tick

This is important. If dividends and interest were paid inside every inner sub-iteration, then busy
high-volume periods would mechanically receive more economic income. That would mix the clock mechanism
with a change in dividend frequency.

The clean H2 design keeps:

```text
one payment per recorded tick
```

in both calendar and event-time modes.

---

## Component 6: Experimental Grid and Volume Matching

Default grid:

```text
mode in {calendar, event_time}
phi in {0.0, 0.1, ..., 1.0}
Vstar in calibrated values for event_time
n_runs = 30
n_ticks = 500
shock_tick = 200
shock_dp = -10
n_random = 5
```

Calendar mode is run once per `phi`.
Event-time mode is run separately for each `Vstar`.

### Why Volume Matching Is Necessary

The event-time clock must not be compared to calendar time with a much larger total executed volume.
An early H2 run used:

```text
Vstar in {25, 50, 100}
```

That made event-time runs much more active than calendar-time runs. For example, the preliminary run
produced approximately:

```text
calendar:        9.9 executed volume per tick
event_time_V25: 30.5 executed volume per tick
event_time_V50: 54.8 executed volume per tick
event_time_V100: 98.1 executed volume per tick
```

This is not a clean H2 comparison, because the result mixes two changes:

1. the clock changes from calendar time to event time;
2. the total trading activity also becomes much larger.

The corrected design therefore calibrates `Vstar` from the calendar-time baseline.

### Corrected Calibration Rule

The experiment first runs the calendar-time block. Then it computes:

```text
calendar_volume_per_tick =
    mean(executed_volume_total / n_ticks at phi=0 in calendar mode)
```

Then event-time `Vstar` values are chosen as:

```text
Vstar = round(calendar_volume_per_tick * multiplier)
```

Default multipliers:

```text
{0.5, 1.0, 1.5}
```

So if calendar baseline volume is approximately 10 per tick, event-time regimes become:

```text
event_time_V5
event_time_V10
event_time_V15
```

This keeps event-time ticks close to comparable market-activity intervals and makes the H2 inference
much more legitimate.

### Recommended Final H2 Run

For the final H2 comparison against the strongest unified H1 speed regime:

```bash
python3 experiment_h2_event_time.py --speed-multiplier 2 --calibrate-vstar
```

For a v9-style pure fast-first comparison:

```bash
python3 experiment_h2_event_time.py --speed-multiplier 1 --calibrate-vstar
```

The old `{25, 50, 100}` run should be treated as a high-activity sensitivity run, not as the final
clean H2 result.

Each regime receives its own baseline at `phi=0` and its own tipping-point calculation.

### Status of Existing Result Files After Volume Calibration

Any results produced with:

```text
Vstar in {25, 50, 100}
```

should be treated as **high-activity sensitivity results**, not as the final H2 test. In those runs,
event-time had substantially higher realized executed volume per tick than calendar time, so the comparison
mixed two mechanisms: timekeeping and total market activity.

The final H2 candidate run must use:

```bash
python3 experiment_h2_event_time.py --speed-multiplier 2 --calibrate-vstar
```

This writes calibrated `Vstar` values into the raw and aggregate CSV files through:

- `calendar_volume_per_tick_target`
- `vstar_to_calendar_tick_ratio`

Those columns should be checked before interpreting the results.

---

## Metrics

The experiment computes the same stability metrics as H1:

### `vol_ratio`

Primary metric:

```text
mean post-shock rolling price volatility / mean pre-shock rolling price volatility
```

### `spread_ratio`

Liquidity metric:

```text
mean post-shock relative spread / mean pre-shock relative spread
```

### `max_drawdown`

Largest post-shock price decline relative to the pre-shock price:

```text
(p_{shock-1} - min(post_shock_price)) / p_{shock-1}
```

### `recovery_time`

Number of ticks until price returns within 2% of the pre-shock price.

### `mm_stress_ratio`

Fraction of post-shock ticks where a market maker's absolute inventory is at or above `softlimit`.

### Event-Time Diagnostics

For event-time mode, the experiment also records:

- `avg_sub_iters`: average number of inner trading rounds per event tick;
- `max_sub_iters_observed`;
- `threshold_hit_rate`: share of event ticks where `Vstar` was reached before `max_sub_iters`;
- `executed_volume_total`;
- `book_depleted_rate`: share of recorded ticks where at least one side of the order book was empty.
- `calendar_volume_per_tick_target`: calibrated calendar baseline activity level.
- `vstar_to_calendar_tick_ratio`: how large each `Vstar` is relative to the calibrated calendar activity.

These diagnostics are necessary to understand whether the volume clock is actually active.

### Empty Order Book Handling

In stressful event-time regimes, one side of the order book can be fully depleted. The baseline
`ExchangeAgent.price()` raises an exception in this case, because the midpoint cannot be computed
without both bid and ask quotes.

For H2 this is not treated as a coding failure. It is an important market failure state. Therefore
`VolumeExchangeAgent.price()` keeps the last valid midpoint when the book is depleted and the experiment
records the condition through:

```text
book_depleted_rate
```

The experiment does **not** artificially refill the book. If depletion is frequent, the interpretation is
that the corresponding timekeeping regime generated severe liquidity exhaustion.

---

## Statistical Testing

For each regime, the experiment compares:

```text
vol_ratio(phi=0) vs vol_ratio(phi>0)
```

using a one-sided Mann-Whitney U test:

```text
H_A: vol_ratio(phi) > vol_ratio(0)
```

This is the same logic as the H1 statistical validation.

---

## Output Files

The experiment writes:

```text
h2_event_time_raw.csv
h2_event_time_agg.csv
h2_event_time_tipping.csv
h2_event_time_stats.csv
h2_event_time_metrics.png
h2_event_time_heatmap.png
h2_event_time_tipping.png
```

### `h2_event_time_raw.csv`

One row per simulation run.

### `h2_event_time_agg.csv`

Aggregated means, standard deviations, and confidence intervals by regime and `phi`.

### `h2_event_time_tipping.csv`

Tipping point summary for each regime.

### `h2_event_time_stats.csv`

Mann-Whitney U results.

### Figures

The plots are designed in the same spirit as H1/unified plots:

1. metric curves by `phi`;
2. heatmap of mean `vol_ratio`;
3. tipping-point comparison across regimes.

---

## Interpretation Guide

### H2 supported

If:

```text
phi*_event_time > phi*_calendar
```

and event-time regimes show lower post-shock volatility or smoother liquidity stress, then H2 is supported.

Interpretation:

> Volume-clock updating makes the market more resilient by preventing the crisis boundary from being
> crossed at low fast-trader shares.

### H2 not supported

If:

```text
phi*_event_time <= phi*_calendar
```

or event-time produces higher volatility, then H2 is not supported under this model specification.

Interpretation:

> In this ABM, event-time trading does not buffer speed-driven instability; it may even intensify it
> if volume thresholds create concentrated trading bursts.

### Ambiguous result

If results differ strongly by `Vstar`, the conclusion should be conditional:

> Event time changes the instability boundary, but the direction depends on the chosen volume threshold.

In that case, the paper should report H2 as regime-dependent rather than universally confirmed.

---

## How to Run Later

Do not run automatically while writing code. When ready, run manually:

```bash
python3 experiment_h2_event_time.py --speed-multiplier 2 --calibrate-vstar
```

For a smaller smoke test:

```bash
python3 experiment_h2_event_time.py --runs 2 --n-ticks 120 --shock-tick 50 --speed-multiplier 2 --calibrate-vstar --no-plots
```

For a v9-style fast-first comparison without additional speed multiplication:

```bash
python3 experiment_h2_event_time.py --speed-multiplier 1 --calibrate-vstar
```

For a high-activity sensitivity run only:

```bash
python3 experiment_h2_event_time.py --speed-multiplier 2 --vstar 25 50 100
```

---

## Notes for `paper_full`

The H2 section should eventually include:

1. why calendar time is the baseline;
2. why volume-clock event time is theoretically relevant;
3. how executed volume is measured;
4. how one event-time tick is defined;
5. why dividends and interest are paid once per tick;
6. comparison of `phi*_calendar` and `phi*_event_time`;
7. interpretation of `Vstar` sensitivity.

The core comparison table should be:

| regime | baseline vol_ratio | threshold 1.3x | phi* | max vol_ratio | phi at max |
|---|---:|---:|---:|---:|---:|
| calendar | ... | ... | ... | ... | ... |
| event_time_V_calibrated_low | ... | ... | ... | ... | ... |
| event_time_V_calibrated_mid | ... | ... | ... | ... | ... |
| event_time_V_calibrated_high | ... | ... | ... | ... | ... |

The key sentence for the paper will be:

```text
Compared with calendar time, event-time updating shifted / did not shift the critical HFT share phi*.
```

---

## H2 Experiment Version Log

### Version 0: Initial standalone H2 code

Changes:

- standalone `experiment_h2_event_time.py`;
- calendar mode and event-time mode;
- `VolumeExchangeAgent`;
- first volume-clock diagnostics;
- plots and CSV outputs.

Problem:

- the population missed the 5 Random/noisy agents used in the unified H1 speed grid;
- event-time `Vstar` values `{25, 50, 100}` created much higher realized trading volume than calendar time.

Status:

- debugging / preliminary only.

### Version 1: Population aligned with unified H1

Changes:

- default population changed to:

```text
10 Fundamentalists + 10 TrendChartists + 5 Random + 1 MarketMaker
```

- added CLI parameter:

```text
--n-random
```

Reason:

- H2 calendar-time baseline must be comparable to the H1 speed-grid population.

Status:

- required for final H2.

### Version 2: Volume-matched event-time design

Changes:

- added:

```text
--calibrate-vstar
--vstar-multipliers
```

- calendar block runs first;
- `Vstar` is computed from calendar `phi=0` executed volume per tick;
- output rows now include:

```text
calendar_volume_per_tick_target
vstar_to_calendar_tick_ratio
```

Reason:

- event-time must not be compared to calendar time with a much larger total executed volume.

Status:

- required for final H2.

### Version 3: H1 infrastructure fixes reused locally

Changes:

- added local `patch_order_list_insert()` matching the H1 `OrderList.insert()` empty-list fix;
- `VolumeExchangeAgent.limit_order()` can now insert limit orders even when `spread()` is unavailable;
- safe last-valid-price handling is kept through `VolumeExchangeAgent.price()`;
- `book_depleted_rate` remains the diagnostic for empty-book episodes.

Reason:

- H1 had general robustness fixes that are not specific to the delay hypothesis;
- event-time can temporarily deplete one book side, and the book should be able to rebuild endogenously.

Status:

- current H2 implementation.

### Version 4: Decision to Port H2 into H1 Unified Environment

Observation:

- after aligning the population and adding H1-style infrastructure fixes, the standalone H2 calendar-time
  baseline still does not reproduce the main H1 unified speed result;
- in unified H1 speed×2, the main tipping point was approximately:

```text
phi* = 0.2
```

- in the standalone H2 calendar speed×2 run, the calendar-time tipping point is:

```text
phi* = 0.7
```

Interpretation:

- the standalone H2 experiment is useful for developing and debugging the volume-clock mechanism;
- however, it is not yet a clean continuation of H1, because the calendar-time baseline differs too much
  from the H1 unified speed grid;
- therefore the final H2 experiment should be ported into the H1 `hft-intraiter` / `experiment_unified.py`
  environment, so that the calendar-time baseline is literally the same as H1.

Status:

- current standalone H2 results should be treated as exploratory / design evidence;
- final H2 inference should be based on the ported unified-H1 version.

### Current Final-Candidate Command

Use this command for the main H2 result:

```bash
python3 experiment_h2_event_time.py --speed-multiplier 2 --calibrate-vstar
```

After running, interpret only the newly generated `h2_event_time_*.csv` / `.png` files.
Older files from Version 0-2 should be labeled as preliminary or sensitivity runs.

---

## Plan: Port H2 into the H1 Unified Environment

The next step is to move the validated H2 idea into the H1 branch instead of continuing with a standalone
baseline-branch implementation.

### Why Porting Is Necessary

The scientific problem is comparability:

```text
H1 unified speed×2 phi* != standalone H2 calendar speed×2 phi*
```

Since H2 asks whether changing the clock shifts the H1 tipping point, the calendar-time part of H2 should
reuse the same H1 implementation that produced the original speed-grid result.

The clean target is:

```text
same H1 unified population
same H1 unified TrendChartist / SlowTrendChartist classes
same H1 unified SimulatorInfo / metrics
same H1 unified speed_multiplier logic
same H1 unified calendar simulation
only change: calendar-time loop vs event-time loop
```

### Target Branch

Use the H1 branch:

```bash
git switch hft-intraiter
```

Then create a new branch from it:

```bash
git switch -c h2-on-h1-volume-clock
```

This new branch should inherit all H1 unified infrastructure and add only the H2 event-time experiment.

### Files to Bring Over

From this standalone H2 branch, the useful pieces are:

1. Volume counters from `VolumeExchangeAgent`.
2. Event-time simulation loop.
3. `Vstar` calibration logic.
4. Event-time diagnostics:

```text
avg_sub_iters
threshold_hit_rate
executed_volume_total
book_depleted_rate
calendar_volume_per_tick_target
vstar_to_calendar_tick_ratio
```

5. Plot/output structure:

```text
raw CSV
aggregate CSV
tipping CSV
Mann-Whitney CSV
metrics plot
heatmap
tipping plot
```

### What Not to Bring Over

Do not bring the standalone H2 population and agent definitions if the H1 branch already has equivalent
unified versions.

In particular, avoid duplicating:

- H1 `TrendChartist` if it already exists in `experiment_unified.py`;
- H1 population construction if `create_population()` already exists;
- H1 calendar simulator if `SimulatorUnified` already exists.

The ported H2 should reuse those H1 pieces.

### Implementation Steps

1. Switch to H1 branch:

```bash
git switch hft-intraiter
```

2. Create a new H2-on-H1 branch:

```bash
git switch -c h2-on-h1-volume-clock
```

3. Copy or recreate a new experiment file:

```text
experiment_h2_event_time_unified.py
```

4. Import / reuse from `experiment_unified.py` where possible:

```text
TrendChartist
SlowTrendChartist
SimulatorUnified
create_population
vol_ratio
spread_ratio
max_drawdown
recovery_time
```

5. Add executed-volume tracking to the exchange used by the H2 experiment.

   Preferred minimal approach:

   - subclass the H1 `ExchangeAgent`;
   - override `limit_order()` and `market_order()` to count matched quantity;
   - keep H1 delayed-info and safe-book behavior.

6. Add an event-time simulator class or function:

```text
SimulatorEventTimeUnified
```

It should reuse the same H1 behaviour update and fast/slow activation logic, but replace the calendar tick
with:

```text
repeat trading rounds until executed_volume_tick >= Vstar
```

7. Keep the calendar baseline literally H1-style:

```text
calendar mode = SimulatorUnified.simulate(..., speed_multiplier=2)
```

8. Run a sanity check:

```text
calendar mode speed×2 should approximately reproduce H1 unified speed×2 tipping point
```

Expected target:

```text
phi* close to 0.2
```

If this fails, do not interpret H2 yet.

9. Only after the sanity check passes, run event-time modes:

```text
--calibrate-vstar
```

10. Save outputs under names that do not overwrite older standalone H2 files:

```text
h2_unified_calibrated_raw.csv
h2_unified_calibrated_agg.csv
h2_unified_calibrated_tipping.csv
h2_unified_calibrated_stats.csv
h2_unified_calibrated_metrics.png
h2_unified_calibrated_heatmap.png
h2_unified_calibrated_tipping.png
```

### Acceptance Criteria for Final H2

The ported H2 experiment becomes legitimate if:

1. H2 calendar baseline approximately reproduces H1 unified speed×2.
2. Event-time modes differ only by the timekeeping mechanism.
3. `Vstar` is calibrated from calendar executed volume.
4. Diagnostics show:

```text
threshold_hit_rate reasonably high
book_depleted_rate not dominating the result
```

5. The interpretation is based on:

```text
phi*_calendar vs phi*_event_time
```

inside the same H1-unified environment.

---

## Final H2-Clean Experiment: Volume-Matched Calendar vs Event Time

### Branch Hygiene Note

This experiment belongs to the H2 branch:

```text
h2-event-time-volume-clock
```

It was originally created by mistake while working on the H3 branch. The H3 branch was cleaned:

- H2 volume-matched code and output files were removed from H3;
- the H2 documentation block was removed from H3 documentation;
- H3 section numbering was restored there.

The corrected H2-clean experiment is now placed on the H2 branch as:

```text
experiment_h2_volume_matched.py
```

### Why This Additional H2 Experiment Was Needed

The earlier H2 experiment compared calendar time and event time, but one concern remained: if the two clocks produce different total trading volume, then any difference in volatility may come from a different amount of market activity rather than from the clock itself.

The H2-clean experiment therefore asks a narrower and cleaner question:

```text
If calendar-time and event-time runs are matched by total executed volume,
does the event-time clock still change post-shock instability?
```

This is a cleaner H2 test because it controls the main confound: different exposure to trading activity.

### Experimental Architecture

The experiment uses paired simulations. For each `(run, hft_frac)` pair:

1. Run the calendar-time simulation first.
2. Measure its realized total executed volume.
3. Run the event-time simulation with the same seed and same agent composition.
4. Stop the event-time simulation when it reaches approximately the same total executed volume as the calendar run.
5. Compare event-time minus calendar-time metrics within the same pair.

The paired design is important because it reduces noise: each event-time result is compared to its own calendar-time counterpart rather than to an unrelated simulation.

### Implementation Details

The script is self-contained on the H2 branch and reuses local H2-safe components from `experiment_h2_event_time.py`:

- `VolumeExchangeAgent`
- `TrendChartist`
- `SafeFundamentalist`
- `SafeMarketMaker`
- safe order-book patching via `patch_order_list_insert()`
- H2-compatible metrics such as `price_vol_ratio`, `spread_ratio`, `max_drawdown`, `recovery_time`, and `mm_stress_ratio`

The exchange used in the new script is:

```text
LoggingExchange(VolumeExchangeAgent)
```

It records executed volume per tick and cumulative executed volume.

Calendar mode:

```text
one simulation tick = one ordinary calendar iteration
```

Event-time mode:

```text
one simulation tick = trading continues until the volume threshold is reached
```

But unlike the previous Vstar-grid H2 experiment, this version does not compare several fixed `Vstar` values. Instead, it matches the event-time run to the realized calendar total volume.

### Grid

The final run used:

| Parameter | Values |
|---|---|
| `hft_frac` | `{0.0, 0.2, 0.4, 0.6}` |
| modes | `calendar`, `event_time` |
| runs per cell | 50 |
| total raw rows | 400 |
| paired comparisons | 200 |
| shock | `MarketPriceShock(t=200, dp=-10)` |
| horizon | 500 calendar ticks for calendar mode |

The row counts are:

| File | Rows |
|---|---:|
| `h2_volume_matched_raw.csv` | 400 |
| `h2_volume_matched_agg.csv` | 8 |
| `h2_volume_matched_paired_diffs.csv` | 200 |
| `h2_volume_matched_diff_summary.csv` | 4 |

### Output Files

```text
h2_volume_matched_raw.csv
h2_volume_matched_agg.csv
h2_volume_matched_paired_diffs.csv
h2_volume_matched_diff_summary.csv
h2_volume_matched_metrics.png
h2_volume_matched_diffs.png
```

### Volume-Matching Diagnostics

All shocks were triggered:

| Mode | Shock-triggered share |
|---|---:|
| calendar | 1.0 |
| event_time | 1.0 |

The calendar run has zero matching error by construction. The event-time run cannot always stop at exactly the same cumulative volume because trades are discrete, but the mismatch is small relative to total volume:

| Mode | Mean volume match error | Min | Max |
|---|---:|---:|---:|
| calendar | 0.00 | 0.0 | 0.0 |
| event_time | 8.26 | 0.0 | 38.0 |

Calendar total executed volume ranges from roughly 6,448 to 8,481 units depending on `hft_frac`, so the average event-time mismatch is small.

### Aggregated Results

| Mode | `hft_frac` | `vol_ratio` | realized vol / volume | max drawdown | recovery time | total volume | volume/tick | ticks |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| calendar | 0.0 | 2.343 | 0.000344 | 0.150 | 30.12 | 6448.18 | 12.90 | 500.00 |
| calendar | 0.2 | 2.349 | 0.000419 | 0.179 | 39.16 | 7114.10 | 14.23 | 500.00 |
| calendar | 0.4 | 2.795 | 0.000449 | 0.212 | 47.68 | 7797.80 | 15.60 | 500.00 |
| calendar | 0.6 | 2.886 | 0.000460 | 0.226 | 46.60 | 8481.16 | 16.96 | 500.00 |
| event_time | 0.0 | 2.296 | 0.000338 | 0.145 | 20.84 | 6455.96 | 12.88 | 501.42 |
| event_time | 0.2 | 2.499 | 0.000427 | 0.177 | 33.76 | 7121.46 | 14.39 | 496.22 |
| event_time | 0.4 | 2.740 | 0.000424 | 0.183 | 32.88 | 7805.96 | 15.71 | 497.48 |
| event_time | 0.6 | 2.799 | 0.000460 | 0.219 | 45.10 | 8490.90 | 17.06 | 499.08 |

### Paired Event-Time Minus Calendar-Time Differences

Positive values mean event time produced a higher metric than calendar time. Negative values mean event time produced a lower metric.

| `hft_frac` | Δ `vol_ratio` | 95% CI | Δ realized vol / volume | 95% CI | Δ max drawdown | 95% CI | Δ ticks | 95% CI |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.0 | -0.048 | [-0.449, 0.327] | -0.000006 | [-0.000058, 0.000043] | -0.005 | [-0.018, 0.008] | 1.42 | [-5.60, 8.54] |
| 0.2 | 0.150 | [-0.271, 0.570] | 0.000008 | [-0.000068, 0.000084] | -0.002 | [-0.021, 0.014] | -3.78 | [-12.58, 4.78] |
| 0.4 | -0.055 | [-0.542, 0.413] | -0.000025 | [-0.000101, 0.000058] | -0.029 | [-0.051, -0.003] | -2.52 | [-10.84, 5.54] |
| 0.6 | -0.087 | [-0.495, 0.335] | -0.000001 | [-0.000067, 0.000064] | -0.007 | [-0.034, 0.022] | -0.92 | [-9.46, 7.90] |

### Interpretation

The volume-matched H2 experiment does not support a strong claim that event time mechanically stabilizes the market.

The main evidence:

- `vol_ratio` differences are small and all 95% confidence intervals include zero;
- realized volatility per unit of executed volume is almost unchanged;
- max drawdown is slightly lower under event time, especially at `hft_frac=0.4`, where the confidence interval is below zero;
- event-time and calendar-time runs use almost the same total executed volume, so this comparison is cleaner than the earlier fixed-`Vstar` comparison.

The strongest safe conclusion is:

```text
After matching total executed volume, event time does not materially change
the post-shock volatility ratio relative to calendar time in this configuration.
There is weak evidence that event time can reduce drawdown in the mid-HFT-share
regime, but not enough to claim broad market stabilization.
```

### Final H2 Conclusion

H2 is not confirmed in the strong form.

The evidence supports a weaker interpretation:

```text
Calendar-time and event-time measurement choices affect the representation
of trading activity, but once total executed volume is controlled, the H1
instability pattern is not primarily an artifact of the calendar clock.
```

This is still useful for the paper because it strengthens H1: the tipping behavior is not simply caused by counting time in calendar iterations.

---

## H2 Improved: Post-Shock Volume-Window Comparison

### Motivation

The previous H2-clean experiment matched calendar-time and event-time runs by **total executed volume**. This was already cleaner than comparing raw calendar ticks, but an additional concern remained:

```text
The shock changes trading intensity, so total-volume matching may still mix
pre-shock and post-shock activity in a way that blurs the actual H2 question.
```

The improved H2 experiment follows the external review suggestion and compares **equal executed-volume windows after the shock**.

### Scientific Question

The improved H2 question is:

```text
After matching the amount of post-shock trading activity,
does event time produce lower realized volatility than calendar time?
```

This is stricter than the previous H2-clean test because it controls the exact post-shock exposure that is most relevant for market instability.

### Architecture

The experiment is implemented as:

```text
experiment_h2_postshock_volume_windows.py
```

For each `(run, hft_frac)` pair:

1. Run the calendar-time simulation with fixed `n_ticks=500`.
2. Trigger the shock at `shock_tick=200`.
3. Measure calendar post-shock executed volume:

```text
calendar_post_volume = executed volume from tick 200 to the end
```

4. Calibrate the event-time volume threshold from the calendar post-shock trading rate:

```text
Vstar = round(calendar_post_volume / number_of_post_shock_ticks)
```

This means `Vstar` is matched to the **post-shock** calendar trading rate, not the pre-shock average.

5. Rerun the same seed in event time with this `Vstar`.
6. Compare calendar and event-time metrics on the same target post-shock executed-volume window.

### Metrics

Primary metrics:

- `post_rv_per_volume`
  - sum of squared returns in the post-shock volume window divided by executed volume;
- `post_rv_per_trade`
  - sum of squared returns divided by the number of executed trades;
- `post_vol_per_sqrt_volume`
  - standard deviation of returns divided by square root of executed volume.

Context metrics:

- `equal_volume_vol_ratio`
  - post/pre realized variance per volume ratio using volume-matched windows;
- `post_window_volume`
- `post_window_trades`
- `threshold_hit_rate`
- `avg_sub_iters`
- `book_depleted_rate`

### Interpretation Rule

H2 receives support if event time systematically lowers post-shock realized volatility after controlling for post-shock executed volume:

```text
event_time - calendar_time < 0
```

especially for:

```text
post_rv_per_volume
post_rv_per_trade
post_vol_per_sqrt_volume
```

If the paired differences are close to zero or confidence intervals include zero, the correct conclusion remains:

```text
Event time changes how activity is represented, but does not materially
stabilize the market once post-shock trading exposure is controlled.
```

### Completed H2 Improved Run

The improved post-shock volume-window experiment was run with:

```bash
python3 experiment_h2_postshock_volume_windows.py
```

Run completeness:

```text
raw rows = 400
aggregated rows = 8
paired-difference rows = 200
difference-summary rows = 4
runs per mode x hft_frac cell = 50
```

Output files:

```text
h2_postshock_volume_raw.csv
h2_postshock_volume_agg.csv
h2_postshock_volume_paired_diffs.csv
h2_postshock_volume_diff_summary.csv
h2_postshock_volume_metrics.png
h2_postshock_volume_diffs.png
```

### Diagnostics

The event-time threshold was calibrated from post-shock calendar volume per tick:

| `hft_frac` | mean `Vstar` |
|---:|---:|
| 0.0 | 12.70 |
| 0.2 | 13.84 |
| 0.4 | 15.28 |
| 0.6 | 17.02 |

Threshold diagnostics:

| Mode | `hft_frac` | threshold hit rate | avg sub-iterations | book depleted rate |
|---|---:|---:|---:|---:|
| calendar | 0.0 | 1.0 | 1.000 | 0.0 |
| calendar | 0.2 | 1.0 | 1.000 | 0.0 |
| calendar | 0.4 | 1.0 | 1.000 | 0.0 |
| calendar | 0.6 | 1.0 | 1.000 | 0.0 |
| event_time | 0.0 | 1.0 | 1.676 | 0.0 |
| event_time | 0.2 | 1.0 | 1.623 | 0.0 |
| event_time | 0.4 | 1.0 | 1.614 | 0.0 |
| event_time | 0.6 | 1.0 | 1.609 | 0.0 |

Interpretation:

- event-time ticks reliably reach the calibrated post-shock volume threshold;
- there is no order-book depletion in this run;
- event-time uses about 1.6 trading rounds per tick on average, which means the clock transformation is operational rather than only cosmetic.

### Aggregated Primary Metrics

| Mode | `hft_frac` | post RV / volume | post RV / trade | post vol / sqrt(volume) | equal-volume vol ratio | post-window volume | target post volume |
|---|---:|---:|---:|---:|---:|---:|---:|
| calendar | 0.0 | 0.000049 | 0.000157 | 0.000373 | 4.250 | 3793.50 | 3805.38 |
| calendar | 0.2 | 0.000044 | 0.000141 | 0.000346 | 4.284 | 4124.46 | 4138.38 |
| calendar | 0.4 | 0.000074 | 0.000247 | 0.000434 | 7.010 | 4565.90 | 4580.88 |
| calendar | 0.6 | 0.000081 | 0.000269 | 0.000471 | 7.233 | 5075.24 | 5093.38 |
| event_time | 0.0 | 0.000034 | 0.000106 | 0.000377 | 4.006 | 3815.58 | 3805.38 |
| event_time | 0.2 | 0.000056 | 0.000183 | 0.000477 | 5.596 | 4150.14 | 4138.38 |
| event_time | 0.4 | 0.000060 | 0.000194 | 0.000480 | 5.184 | 4590.34 | 4580.88 |
| event_time | 0.6 | 0.000070 | 0.000230 | 0.000549 | 5.120 | 5103.90 | 5093.38 |

Post-window volume matching is close:

| `hft_frac` | calendar mean error | event-time mean error |
|---:|---:|---:|
| 0.0 | -11.88 | 10.20 |
| 0.2 | -13.92 | 11.76 |
| 0.4 | -14.98 | 9.46 |
| 0.6 | -18.14 | 10.52 |

The small errors come from discrete trade sizes: the script cannot stop inside a partially executed trade.

### Paired Event-Time Minus Calendar-Time Differences

Negative values mean event time produced lower post-shock volatility than calendar time.

| `hft_frac` | Δ post RV / volume | 95% CI | Δ post RV / trade | 95% CI | Δ post vol / sqrt(volume) | 95% CI |
|---:|---:|---:|---:|---:|---:|---:|
| 0.0 | -0.000016 | [-0.000033, 0.000001] | -0.000051 | [-0.000108, 0.000004] | 0.000004 | [-0.000071, 0.000078] |
| 0.2 | 0.000012 | [-0.000011, 0.000040] | 0.000041 | [-0.000037, 0.000135] | 0.000130 | [0.000041, 0.000235] |
| 0.4 | -0.000014 | [-0.000045, 0.000017] | -0.000052 | [-0.000162, 0.000056] | 0.000045 | [-0.000056, 0.000147] |
| 0.6 | -0.000011 | [-0.000038, 0.000016] | -0.000039 | [-0.000130, 0.000051] | 0.000077 | [-0.000008, 0.000164] |

Equal-volume volatility ratio differences:

| `hft_frac` | Δ equal-volume vol ratio | 95% CI |
|---:|---:|---:|
| 0.0 | -0.244 | [-1.764, 1.346] |
| 0.2 | 1.312 | [-1.222, 3.880] |
| 0.4 | -1.825 | [-6.291, 1.894] |
| 0.6 | -2.112 | [-6.466, 0.888] |

### Improved H2 Interpretation

This improved experiment again does **not** support a strong stabilizing effect of event time.

Main points:

- `post_rv_per_volume` has confidence intervals crossing zero for all `hft_frac`;
- `post_rv_per_trade` also has confidence intervals crossing zero for all `hft_frac`;
- `post_vol_per_sqrt_volume` is positive at `hft_frac=0.2`, which goes against a universal stabilization claim;
- equal-volume volatility-ratio differences are noisy and all confidence intervals include zero;
- diagnostics are clean: threshold hit rate is 1.0 and book depletion is 0.0.

Final H2-improved conclusion:

```text
Even after calibrating Vstar from post-shock calendar volume and comparing
equal post-shock executed-volume windows, event time does not materially reduce
post-shock realized volatility in this ABM configuration.
```

This strengthens the final H2 interpretation:

```text
H2 is not confirmed as "event time stabilizes markets".
The supported claim is weaker: H1 results are not merely an artifact of using
calendar-time ticks, because the instability pattern persists under stricter
volume-aware comparisons.
```
