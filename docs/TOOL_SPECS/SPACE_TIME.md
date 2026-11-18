# Space Time Pattern Mining - Create Space Time Cube + Emerging Hot Spot Analysis

Status: **FUNCTIONAL_UNVALIDATED**. Tested with synthetic data that has known answers. No ArcGIS Pro reference run exists yet.
To validate, run both tools in ArcGIS Pro on the same PACP points with the same bin size, time step and
neighbourhood. Compare CATEGORY per location and the overall trend, then file the report in `../VALIDATION_REPORTS/`.

## Purpose
Finds where and how event clusters change over time. Example: PACP pipe inspections by `INSPECT_DT`.
Patterns include new, intensifying, persistent, diminishing, sporadic, oscillating and historical hot and cold spots.

## Inputs
* **Create Space Time Cube** takes points in a **projected** CRS and a date or text-date field.
  * Unknown dates are excluded and counted. Examples: blank, `0000/00/00`, unparseable values.
  * Optional: a numeric summary field (SUM / MEAN / MIN / MAX).
  * It needs at least 60 points and at least 10 time steps, as ArcGIS does.
* **Emerging Hot Spot Analysis** takes a complete cube layer: one bin per location × time step.

## Method
1. **Time bins.** End-time alignment, the default, puts the last event in the last bin.
   * End time: each bin is `(start, end]`. Start time: each bin is `[start, end)`.
   * Reference time: one bin ends at the reference.
   * Month and year steps are offsets from the anchor date, so month ends don't drift.
2. **Grid.** The upper-left bin is centred on the upper-left corner of the input extent, as in ArcGIS.
   * Hexagons are flat-topped. Height = distance interval. Width = 2·h/√3.
   * Only locations with at least one point are kept.
3. **Mann-Kendall.** S is the sum of sign(xⱼ−xᵢ). The variance is corrected for ties.
   z = (S∓1)/√var. p is two-sided.
   * Bins: ±3 = p ≤ 0.01, ±2 = p ≤ 0.05, ±1 = p ≤ 0.10.
   * It runs per location (COUNT_TREND_*) and on the step totals (overall trend, in messages and counts).
4. **Gi\*.** Binary weights over the space-time neighbourhood.
   * The neighbourhood is locations whose centroid is within the distance (self included).
   * It covers the current step and the `neighborhood_time_step` preceding steps.
   * Mean and standard deviation are global over the entire cube.
5. **FDR.** Benjamini-Hochberg at 90 / 95 / 99 % gives EMERGING_*_HS_BIN (−3…3).
6. **Categories.** A significant hot (cold) bin is HS_BIN > 0 (< 0). Let *share* = significant steps / all steps.
   * **New:** final step hot, never hot before.
   * **Consecutive:** final run of ≥ 2 hot steps, never hot before the run, share < 0.9.
   * **Intensifying / Diminishing / Persistent:** share ≥ 0.9 with final hot. Which one depends on the
     Mann-Kendall test of the Gi\* z-scores (bin > 0, < 0, or 0 at 90 %).
   * **Oscillating:** final hot, share < 0.9, cold in some earlier step.
   * **Sporadic:** final hot, share < 0.9, never cold.
   * **Historical:** final step not hot, share ≥ 0.9.
   * Cold spots mirror these rules.

## Decisions not stated by ArcGIS (assumptions)
* The confidence level that makes a bin "statistically significant" in the category rules is taken as 90 % (after FDR).
* The 90 % rule is applied as share ≥ 0.9, with no rounding.
* **Default neighbourhood distance.** It is the kernel-density default search radius,
  0.9·min(SD, √(1/ln2)·Dm)·n^−0.2, computed on location centroids weighted by the analysis variable.
  It is never less than √2 × bin size, so every interior bin reaches its queen neighbours.
  ArcGIS says only that its default is "adapted from" this formula.
* **Default bin size.** Longest extent side / 100. ArcGIS uses the larger of this and a
  spatial-distribution estimate, so ArcGIS defaults can be larger.

## Outputs (new Gold layers)
* **Space Time Cube**: LOCATION_ID, TIME_STEP (0-based), START_TIME, END_TIME, COUNT, [SUM_x …].
* **Cube Trends** (one row per location): COUNT_TOTAL, STEPS_WITH_DATA, COUNT_TREND_ZSCORE / PVALUE / BIN.
* **Emerging Hot Spots** (one row per location): CATEGORY (−8…8), PATTERN, totals, NUM_HOT / NUM_COLD,
  FINAL_HS_BIN, EMERGING_{V}_TREND_* and {V}_TREND_*.
* **Hot Spot Bins**: the cube rows plus EMERGING_{V}_HS_ZSCORE / PVALUE / BIN.
* **Run counts**: `series` (per-step totals, hot and cold bins per step) for the dashboard chart.

## Not implemented
K nearest neighbours, contiguity, the number-of-neighbours minimum, polygon analysis mask, and the
neighbourhood / individual-time-step global windows. Also missing: defined locations, template cubes,
non-zero empty-bin fills, netCDF output and Local Outlier Analysis.

## Changelog
* 2026-11-15, 0.1.0: first implementation.
