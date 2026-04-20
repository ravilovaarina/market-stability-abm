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
