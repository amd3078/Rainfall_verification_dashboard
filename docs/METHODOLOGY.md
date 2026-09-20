# Verification methodology

Technical reference for the scores implemented in the Rainfall Verification
Dashboard: what each one measures, the exact formula used in the code, the published
source, and the assumptions and caveats that apply to this implementation.

All scores are computed in **millimetres**, over the grid cells inside the selected
box, for the selected valid dates, after the forecast has been interpolated onto the
observation grid.

---

## 1. The contingency table

Categorical verification reduces two continuous fields to a 2 × 2 table by applying a
rainfall threshold *t*. A grid point is an *event* when the value is **greater than or
equal to** *t*.

|  | Observed ≥ *t* | Observed < *t* |
|---|---|---|
| **Forecast ≥ *t*** | `a` hits | `b` false alarms |
| **Forecast < *t*** | `c` misses | `d` correct negatives |

`N = a + b + c + d`. Grid points where either field is `NaN` are excluded before the
table is formed, so `N` is the number of *valid pairs*, not the number of grid cells.

Two derived rates are used throughout:

```
H = a / (a + c)     hit rate           (= POD)
F = b / (b + d)     false-alarm rate   (not FAR)
```

`F` is the **false-alarm rate** (conditioned on non-events); `FAR = b/(a+b)` is the
**false-alarm ratio** (conditioned on forecast events). They are different quantities
and both are reported.

When a date range is selected, `a`, `b`, `c`, `d` are **summed over all dates first**
and the score is computed from the totals. This is not the same as averaging daily
scores, and it is the correct treatment for ratio scores.

---

## 2. Categorical scores

| Score | Formula | Range | Perfect | Measures |
|---|---|---|---|---|
| POD | `a/(a+c)` | 0 … 1 | 1 | Fraction of observed events that were forecast |
| FAR | `b/(a+b)` | 0 … 1 | 0 | Fraction of forecast events that did not occur |
| CSI | `a/(a+b+c)` | 0 … 1 | 1 | Overlap of forecast and observed event areas |
| BIAS | `(a+b)/(a+c)` | 0 … ∞ | 1 | Frequency bias: >1 over-forecast area, <1 under-forecast |
| ETS | `(a−aᵣ)/(a+b+c−aᵣ)`, `aᵣ=(a+b)(a+c)/N` | −⅓ … 1 | 1 | CSI adjusted for hits expected by chance |
| HSS | `2(ad−bc)/[(a+c)(c+d)+(a+b)(b+d)]` | −1 … 1 | 1 | Accuracy relative to random chance |
| PSS | `H − F` | −1 … 1 | 1 | Discrimination between events and non-events |
| ACC | `(a+d)/N` | 0 … 1 | 1 | Overall fraction correct |
| Yule's Q | `(ad−bc)/(ad+bc)` | −1 … 1 | 1 | Odds-ratio skill score |

**Choosing among them.** ACC is dominated by correct negatives and is close to 1 for
any rare event, so it is rarely informative for heavy rainfall. CSI and ETS are the
usual summary scores for moderate thresholds. PSS is nearly equal to POD for rare
events, because `F → 0`. BIAS should always be read alongside POD and FAR, since a
forecast can raise POD simply by over-forecasting area.

**Degenerate cases.** Every score returns `NaN` when its denominator is zero — for
example FAR when nothing was forecast, or POD when nothing was observed. It never
raises. When verifying rare events over short periods, check `N` and the raw counts
before interpreting a score.

**References**

- Wilks, D. S. (2011). *Statistical Methods in the Atmospheric Sciences*, 3rd ed.,
  Academic Press, ch. 8.
- Jolliffe, I. T. & Stephenson, D. B. (eds.) (2012). *Forecast Verification: A
  Practitioner's Guide in Atmospheric Science*, 2nd ed., Wiley.
- Schaefer, J. T. (1990). The critical success index as an indicator of warning skill.
  *Weather and Forecasting*, **5**, 570–575.

---

## 3. Extremal-dependence scores

As a threshold rises, the base rate falls and ETS, CSI and HSS tend to zero for *any*
forecast, whatever its real skill — the "degeneracy" problem. The extremal-dependence
family is constructed to converge to a non-trivial limit as the base rate approaches
zero, making it the appropriate choice for heavy and extreme rainfall thresholds.

| Score | Formula | Notes |
|---|---|---|
| EDI | `[ln F − ln H] / [ln F + ln H]` | Base-rate independent asymptotically; not "hedgeable" by over-forecasting |
| SEDI | `[ln F − ln H − ln(1−F) + ln(1−H)] / [ln F + ln H + ln(1−F) + ln(1−H)]` | Symmetric version; the usual recommendation for rare events |
| EDS | `2 ln[(a+c)/N] / ln(a/N) − 1` | Depends on base rate; can be improved by over-forecasting, so read with BIAS |
| SEDS | `{ln[(a+b)/N] + ln[(a+c)/N]} / ln(a/N) − 1` | Symmetric extremal dependence score |

**Undefined cases.** EDI and SEDI require `0 < H < 1` and `0 < F < 1`; the code
returns `NaN` otherwise. EDS and SEDS require at least one hit (`a > 0`) and
`ln(a/N) ≠ 0`.

**Interpretation.** EDI and SEDI are 0 for a random forecast and 1 for a perfect one.
Because they are ratios of logarithms, they are sensitive to very small counts: with
only a handful of hits, the value carries wide uncertainty. Always report the
bootstrap interval alongside them.

**References**

- Stephenson, D. B., Casati, B., Ferro, C. A. T. & Wilson, C. A. (2008). The extreme
  dependency score: a non-vanishing measure for forecasts of rare events.
  *Meteorological Applications*, **15**, 41–50.
- Hogan, R. J., O'Connor, E. J. & Illingworth, A. J. (2009). Verification of
  cloud-fraction forecasts. *Quarterly Journal of the Royal Meteorological Society*,
  **135**, 1494–1511.
- Ferro, C. A. T. & Stephenson, D. B. (2011). Extremal dependence indices: improved
  verification measures for deterministic forecasts of rare binary events.
  *Weather and Forecasting*, **26**, 699–713.

---

## 4. Continuous scores

Computed on the regridded forecast field `F` against the observation field `O`. For
ensembles they are computed on the **ensemble mean**.

| Score | Formula | Perfect |
|---|---|---|
| ME (mean error) | `mean(F − O)` | 0 |
| MAE | `mean(|F − O|)` | 0 |
| RMSE | `sqrt(mean((F − O)²))` | 0 |
| CORR | Pearson correlation of `F` and `O` | 1 |

**Sign convention:** ME is forecast minus observation, so a positive ME means a
**wet bias**.

Over a date range these are accumulated from running sums (`ΣF`, `ΣO`, `ΣF²`, `ΣO²`,
`ΣFO`, `Σ|e|`, `Σe²`, `n`) rather than by averaging daily values, so the pooled result
equals the score of the pooled sample.

CORR is `NaN` when either field has zero variance — a constant field, which happens
in a small box on a dry day.

**Caveat for rainfall.** Precipitation is strongly non-Gaussian and CORR is dominated
by the wettest points. RMSE on raw rainfall is likewise dominated by a few extreme
cells. Threshold-based and spatial scores are usually more informative.

---

## 5. Probabilistic and ensemble scores

For an *M*-member ensemble, the forecast probability of exceeding threshold *t* is the
fraction of members exceeding it; the observation is binary.

### Brier score

```
BS = mean( (P − obin)² )
```

Mean squared error of the probability forecast. 0 is perfect, 1 is worst.

### Brier skill score

```
BSS = 1 − BS / BS_ref ,     BS_ref = c̄ (1 − c̄)
```

`c̄` is the **base rate of the sample itself** — the observed event frequency over the
selected box and dates.

> **Caveat.** This is skill relative to *sample* climatology, not an independent
> long-term climatology. It is the standard convention, but it makes BSS values
> dependent on the period and region selected, and it is optimistic relative to a
> forecast scored against an external climatology. `BSS` is `NaN` when `c̄` is 0 or 1.

### CRPS

The continuous ranked probability score generalises MAE to a probabilistic forecast.
The implementation uses the standard ensemble ("NRG") estimator:

```
CRPS = (1/M) Σᵢ |xᵢ − y|  −  (1 / 2M²) Σᵢ Σⱼ |xᵢ − xⱼ|
```

evaluated through the sorted-member identity

```
Σᵢ Σⱼ |xᵢ − xⱼ| = 2 Σᵢ (2i − M − 1) x₍ᵢ₎
```

which is `O(M log M)` rather than `O(M²)`. CRPS has the units of the variable (mm)
and reduces to `|x − y|` for a single-member ensemble, so it is directly comparable
with the MAE of a deterministic forecast.

> **Caveat.** This estimator is **biased** — it systematically rewards
> under-dispersive ensembles, with the bias decreasing as `1/M`. The "fair" or
> unbiased estimator replaces `1/(2M²)` with `1/(2M(M−1))`. This application does not
> implement the fair version, so **CRPS values must not be compared between ensembles
> of different sizes**.

**References**

- Brier, G. W. (1950). Verification of forecasts expressed in terms of probability.
  *Monthly Weather Review*, **78**, 1–3.
- Hersbach, H. (2000). Decomposition of the continuous ranked probability score for
  ensemble prediction systems. *Weather and Forecasting*, **15**, 559–570.
- Gneiting, T. & Raftery, A. E. (2007). Strictly proper scoring rules, prediction,
  and estimation. *Journal of the American Statistical Association*, **102**, 359–378.
- Ferro, C. A. T., Richardson, D. S. & Weigel, A. P. (2008). On the effect of ensemble
  size on the discrete and continuous ranked probability scores.
  *Meteorological Applications*, **15**, 19–24.

---

## 6. Ensemble diagnostics

### Reliability diagram

Forecast probabilities are binned into 10 equal-width bins in `[0, 1]`; for each
populated bin the mean forecast probability is plotted against the observed
frequency. Points on the 1:1 line indicate reliability (calibration). Empty bins are
omitted, and the sample count per bin is returned so that sparsely populated bins can
be identified.

### ROC curve and AUC

Hit rate against false-alarm rate as the probability decision threshold is swept over
all distinct forecast probabilities. The area under the curve is obtained by
trapezoidal integration; 1 is perfect discrimination, 0.5 is none. ROC measures
*discrimination* only and is insensitive to calibration bias — a systematically
over-confident forecast can still have a high AUC.

### Relative economic value

Richardson (2000). For a user with cost/loss ratio *r*, the value of the forecast
relative to a perfect forecast and to always acting on climatology:

```
V(r) = [ min(r, s) − E_forecast ] / [ min(r, s) − s·r ]
E_forecast = r·(H·s + F·(1−s)) + (1−H)·s
```

with `s` the base rate. The plotted curve is the **envelope**: the maximum over
probability decision thresholds for each *r*.

### Rank histogram (Talagrand diagram)

The verification rank of the observation among the *M* sorted members, giving `M+1`
bins. Ties are broken randomly. A flat histogram indicates a well-calibrated
ensemble; U-shaped indicates under-dispersion (spread too small); dome-shaped
indicates over-dispersion; a sloped histogram indicates bias.

> **Caveat.** Tie-breaking uses NumPy's *global* random state, so the rank histogram
> is not bit-reproducible between runs. The PIT histogram, by contrast, uses a fixed
> seed. This inconsistency is a known open item.

### PIT histogram

The randomised probability integral transform — the forecast CDF evaluated at the
observation, in `[0, 1]`. A uniform histogram indicates calibration. It is the
continuous analogue of the rank histogram.

### Spread–skill

Points are binned by ensemble standard deviation; each bin contributes its mean
spread and the RMSE of the ensemble mean. A perfectly calibrated ensemble lies on the
1:1 line. Bins with two or fewer points are dropped.

### Taylor diagram

Correlation, standard deviation and centred RMS difference for each model on a single
polar plot (Taylor 2001).

**References**

- Talagrand, O., Vautard, R. & Strauss, B. (1997). Evaluation of probabilistic
  prediction systems. *ECMWF Workshop on Predictability*, 1–25.
- Hamill, T. M. (2001). Interpretation of rank histograms for verifying ensemble
  forecasts. *Monthly Weather Review*, **129**, 550–560.
- Richardson, D. S. (2000). Skill and relative economic value of the ECMWF ensemble
  prediction system. *Quarterly Journal of the Royal Meteorological Society*,
  **126**, 649–667.
- Taylor, K. E. (2001). Summarizing multiple aspects of model performance in a single
  diagram. *Journal of Geophysical Research*, **106**, 7183–7192.

---

## 7. Spatial verification

Grid-point scores penalise a forecast twice for a small displacement — once for a
miss and once for a false alarm ("double penalty"). Spatial methods address this
directly.

### Fractions Skill Score

Roberts & Lean (2008), a neighbourhood method. Both fields are made binary at the
threshold, each is convolved with a square neighbourhood of side *n* to give
fractional coverages `PF` and `PO`, and

```
FSS(n) = 1 − Σ(PF − PO)² / Σ(PF² + PO²)
```

Neighbourhood sizes are 1, 3, 5, 9, 15, 21 and 31 grid boxes. Numerator and
denominator are accumulated across all dates before the ratio is formed.

FSS is 0 for no overlap and 1 for a perfect match, and increases monotonically with
*n*. The **skilful scale** is conventionally the smallest *n* at which
`FSS > 0.5 + f₀/2`, where `f₀` is the observed event frequency.

> **Caveat.** `scipy.ndimage.uniform_filter` is used with `mode="constant"` (zero
> padding), so fractional coverage is biased low within *n*/2 grid boxes of the box
> edge. At *n* = 31 that is 15 grid boxes on each side. Keep the verification box
> comfortably inside the data domain, and treat large-*n* FSS from a small box with
> caution.

### CRA decomposition

After Ebert & McBride (2000). The forecast is shifted over `±8` grid boxes in both
directions; the shift minimising the MSE defines the displacement error, and

```
MSE_total    = displacement + volume + pattern
displacement = MSE_original − MSE_shifted
volume       = (mean F − mean O)²
pattern      = MSE_shifted − volume
```

A large displacement component means the forecast had roughly the right rainfall in
the wrong place; a large volume component means a systematic amplitude error; a large
pattern component means the structure itself is wrong. The output also reports RMSE,
correlation before and after the shift, maximum and mean rainfall in both fields, the
optimal `(dx, dy)`, and the rain-area fractions.

> **Two deviations from the published method.**
>
> 1. **Whole-field rather than object-based.** Ebert & McBride identify a *contiguous
>    rain area* above a threshold and shift that object. Here the entire verification
>    box is shifted as one, and the threshold only feeds the reported area fractions.
>    With several rain systems moving differently, a single whole-field shift is a
>    compromise between them. Read the result as a whole-field displacement/MSE
>    decomposition.
> 2. **Circular shift.** The shift uses `numpy.roll`, so rainfall leaving one edge of
>    the box reappears on the opposite edge. For a regional domain with rainfall near
>    the boundary this can select a spurious optimal displacement. Pad the
>    verification box away from active rainfall at the edges.
>
> Both are open items for a future release. A shift with truncation and masking, and
> optional object identification, would bring the implementation in line with the
> published method.

**References**

- Ebert, E. E. & McBride, J. L. (2000). Verification of precipitation in weather
  systems: determination of systematic errors. *Journal of Hydrology*, **239**,
  179–202.
- Roberts, N. M. & Lean, H. W. (2008). Scale-selective verification of rainfall
  accumulations from high-resolution forecasts of convective events.
  *Monthly Weather Review*, **136**, 78–97.
- Gilleland, E., Ahijevych, D., Brown, B. G., Casati, B. & Ebert, E. E. (2009).
  Intercomparison of spatial forecast verification methods.
  *Weather and Forecasting*, **24**, 1416–1430.

---

## 8. Bootstrap uncertainty

A verification score computed from a finite sample is an estimate. The application
quantifies its sampling uncertainty with a **non-parametric bootstrap that resamples
whole valid dates with replacement** — a block bootstrap whose block is one date.

**Procedure**

1. For each date, the sufficient statistics are stored once: the contingency counts
   `a, b, c, d` and the running sums `n, ΣF, ΣO, ΣF², ΣO², ΣFO, Σ|e|, Σe²`.
2. `B` dates are drawn with replacement from the `B` available dates.
3. The statistics of the drawn dates are **summed**, and the score is recomputed from
   those totals.
4. Steps 2–3 repeat for the user-specified number of resamples.
5. The interval is the **percentile interval**: at 95%, the 2.5th and 97.5th
   percentiles of the bootstrap distribution.

**Why resample sufficient statistics.** Recomputing the score from resampled totals —
rather than averaging resampled daily scores — is what makes ratio scores such as ETS,
CSI and BIAS come out correctly, and it costs almost nothing per resample.

**Assumptions and limitations**

- **Spatial correlation within a date is preserved**, because a whole date is
  resampled as a unit. The interval does not assume independent grid points.
- **Dates are assumed independent.** They are not, during a persistent monsoon spell
  or a long dry break, so the interval is somewhat too narrow in those conditions. A
  multi-day moving-block bootstrap would be the standard remedy.
- **Percentile method only.** No bias correction or acceleration (BCa) is applied.
  For strongly skewed bootstrap distributions — common for rare-event scores — the
  percentile interval can be mis-centred.
- **Undefined resamples are dropped.** Resamples yielding a zero denominator are
  removed before the percentiles are taken. With rare events, where many resamples
  may contain no hits, this makes the reported interval optimistic.
- **A fixed seed** makes the interval reproducible for a given dataset and resample
  count.
- **At least two dates** are required; otherwise `NaN` is returned.
- Brier score, BSS and CRPS use the same date-resampling scheme applied to their
  per-date values.

**References**

- Efron, B. & Tibshirani, R. J. (1993). *An Introduction to the Bootstrap*,
  Chapman & Hall.
- Gilleland, E. (2020). Bootstrap methods for statistical inference. Part I:
  comparative forecast verification for continuous variables.
  *Journal of Atmospheric and Oceanic Technology*, **37**, 2117–2134.

---

## 9. Summary of known caveats

| # | Item | Where | Impact |
|---|---|---|---|
| 1 | CRA shifts the whole field, not an identified rain object | `cra_decomp` | Displacement is a compromise across multiple systems |
| 2 | CRA shift wraps around the domain (`numpy.roll`) | `cra_decomp` | Possible spurious displacement when rain sits near the box edge |
| 3 | FSS neighbourhood uses zero padding | `fss_accum` | Coverage biased low within *n*/2 grid boxes of the edge |
| 4 | CRPS uses the biased `1/(2M²)` estimator | `crps_points`, `crps_ens`, `crps_grid` | Not comparable across different ensemble sizes |
| 5 | BSS reference is sample climatology | `prob_scores` | Skill is period- and region-dependent |
| 6 | Rank-histogram ties use the global RNG | `rank_hist` | Not bit-reproducible between runs |
| 7 | Bootstrap assumes independent dates, percentile method only | `boot_ci`, `prob_boot_ci` | Intervals slightly narrow for autocorrelated periods |
| 8 | Undefined bootstrap resamples are dropped | `boot_ci` | Optimistic intervals for rare events |
| 9 | Regridding is bilinear | `regrid` | Smooths extremes; affects high thresholds |
| 10 | Longitude conventions are not converted (0–360 vs −180–180) | `regrid` | Mismatched conventions yield an all-`NaN` field |
| 11 | `--selftest` box contains no events above its 5 mm threshold | `selftest` | Prints `OK` on degenerate scores; use `pytest` instead |

None of these is a formula error — the implemented equations match their published
definitions, as verified by the test suite. They are documented assumptions and
implementation choices that affect interpretation.
