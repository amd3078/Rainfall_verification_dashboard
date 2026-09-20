# Rainfall Verification Dashboard

An interactive [Streamlit](https://streamlit.io) application for verifying gridded
**deterministic and ensemble precipitation forecasts** against gridded observations.

Draw a region on the map, choose a rainfall threshold and a date range, and the app
computes categorical, continuous, probabilistic and spatial verification scores, with
diagnostic plots, per-grid-cell score maps and bootstrap confidence intervals.

The repository ships a small **synthetic** demonstration dataset, so the application
runs immediately after installation with no external data required.

---

## Contents

- [Installation](#installation)
- [Running the demo](#running-the-demo)
- [Capabilities](#capabilities)
- [Supported input](#supported-input)
- [Variables, units and accumulation](#variables-units-and-accumulation)
- [Grid handling](#grid-handling)
- [Thresholds](#thresholds)
- [Verification scores](#verification-scores)
- [Spatial verification](#spatial-verification)
- [Confidence intervals](#confidence-intervals)
- [Outputs](#outputs)
- [Using your own data](#using-your-own-data)
- [Optional features](#optional-features)
- [Tests](#tests)
- [Documentation](#documentation)
- [Author](#author)
- [Citation](#citation)
- [License](#license)

---

## Installation

Requires **Python 3.10 or newer**.

```bash
git clone https://github.com/amd3078/Rainfall_verification_dashboard.git
cd Rainfall_verification_dashboard

python -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

Then start the application:

```bash
streamlit run app.py
```

It opens at <http://localhost:8501>.

### Conda (recommended if you need GRIB2 or Cartopy)

`cfgrib`/`eccodes` (GRIB2 input) and `cartopy` (Natural Earth coastlines) depend on
compiled geospatial libraries that install far more reliably through conda-forge:

```bash
conda env create -f environment.yml
conda activate rainfall-verif
streamlit run app.py
```

### Docker

```bash
docker build -t rainfall-verif .
docker run -p 8501:8501 -v /path/to/your/data:/data rainfall-verif
```

All compiled geospatial libraries (PROJ, GEOS, ecCodes) are baked into the image.

### Double-click launchers

For users who would rather not use a terminal, the repository includes launchers that
create the conda environment on first run, start the server and open the browser:

| Platform | File |
|---|---|
| macOS / Linux | `run.command` |
| Windows | `run.bat` |

They require [Miniconda or Miniforge](https://conda-forge.org/download/) to be
installed. On first run each also creates a desktop shortcut, so subsequent launches
are a single double-click.

---

## Running the demo

No configuration is needed. After installation:

```bash
streamlit run app.py
```

The sidebar already points at the bundled `demo_data/` directory. Press
**▶ Run verification** to compute scores. Nothing is recomputed while you edit the
sidebar — the run button is the only trigger.

A non-interactive check is also available:

```bash
python app.py --selftest
```

> **Note:** `--selftest` currently evaluates a sub-box (20–26°N, 80–88°E) in which the
> synthetic rainfall field stays below the 5 mm threshold it uses, so it reports
> `POD 0.000 / FAR nan` while still printing `selftest OK`. It verifies that lazy
> NetCDF slicing works, not that the scores are meaningful. Use `pytest` (below) for
> the numerical checks.

The bundled demo data is fully described in [`docs/DEMO_DATA.md`](docs/DEMO_DATA.md)
and can be regenerated with `python make_demo_data.py`.

---

## Capabilities

| Area | What the application provides |
|---|---|
| Forecast types | Deterministic (single model or multi-model comparison) and ensemble (ensemble mean or probabilistic) |
| Input formats | NetCDF (`.nc`, `.nc4`) always; GRIB2 (`.grib`, `.grib2`, `.grb`, `.grb2`) when `cfgrib` is installed |
| File layouts | One file per lead holding all dates ("together"), or one file per date per lead ("split"); models as sub-folders or as filename prefixes in a flat folder |
| Periods | A single day, or a date range pooled over a season |
| Maps | Side-by-side observation and forecast panels, draw-a-box region selection, synchronised zoom/pan, optional coastline and national-boundary overlay |
| Score maps | Per-grid-cell maps for any categorical or continuous score, plus CRPS, Brier score and BSS maps for ensembles |
| Diagnostics | Reliability diagram, ROC curve with AUC, relative economic value, rank histogram, PIT histogram, spread–skill, Taylor diagram, Q–Q plot, score-vs-valid-date time series |
| Uncertainty | Non-parametric bootstrap confidence intervals on all scores |
| Export | Score tables to CSV; any figure to PNG, JPEG, SVG or PDF at a chosen size and DPI |

---

## Supported input

### Observations

One gridded NetCDF (or GRIB2) file with a `time` axis covering the dates you want to
verify.

- **Rainfall variable** — the first match among
  `rf`, `APCP_24`, `APCP_surface`, `precip`, `precipitation`, `tp`;
  otherwise the first variable with two or more dimensions.
- **Coordinates** — longitude named `lon` or `longitude`, latitude named `lat` or
  `latitude`, time named `time`.
- **Expected dimension order** — `(time, lat, lon)`.

### Forecasts

One file per forecast lead, per model.

- **Lead time** is parsed from the *filename*: any `day1` … `dayN` token
  (`day 1`, `lead1` and `f03` are also recognised).
- **Valid date(s)** are read from the file's `time` coordinate, not the filename.
- **Deterministic** files hold a single rainfall variable, dimensions `(time, lat, lon)`.
- **Ensemble** files hold members as separate variables named
  `APCP_surface_1` … `APCP_surface_N`, each with dimensions `(time, lat, lon)`.
  There is no `member` dimension — members are variables.
- **Model name**, in a flat folder, is the filename text before `dayN`
  (`NCUM_day1.nc` → `NCUM`); date and initialisation tokens are stripped. In a
  nested layout, each sub-folder is one model.

Both time layouts work and may be mixed:

```
together/   day01fcst.nc  day02fcst.nc  …            (each file: time × members)
split/      day01_2025-06-19.nc  day01_2025-06-20.nc  …  day02_2025-06-19.nc  …
```

For deterministic multi-model comparison:

```
BASE/ NCUM/  ncum-…-day1.nc  ncum-…-day2.nc  …
      GFS/   GFS-day1_….nc   GFS-day2_….nc   …

merged/  NCUM_day1.nc … NCUM_day5.nc   GFS_day1.nc … GFS_day5.nc
```

Point the sidebar at `BASE/` or `merged/` and the models are listed automatically.

> **Tidy folders matter.** With a clean folder, leave the *Forecast glob* blank and
> every `dayN` file is read. With a mixed folder, set a glob
> (e.g. `day*fcstjjas2025*.nc`) to select only the files you want.

Small files can also be uploaded directly in the browser (Upload mode); the server
upload limit is 2000 MB, set in `.streamlit/config.toml`.

---

## Variables, units and accumulation

**Units.** The application reads each rainfall variable's `units` attribute and
converts to millimetres:

| `units` attribute | Factor applied |
|---|---|
| `mm`, `kg m-2`, `kg/m2`, `kg m^-2` | 1 |
| `cm` | 10 |
| `m`, `metre`, `meter` | 1000 |
| `inch`, `in` | 25.4 |
| absent or unrecognised | **none** — a warning is shown and you select the units manually |

A display-units selector (mm / cm / m / inch) controls presentation only; all scores
are computed in millimetres.

**Accumulation.** The application performs **no temporal accumulation or
disaggregation**. Each forecast field is compared with the observation field on the
same valid date, exactly as stored. It is your responsibility to supply forecast and
observation files over the **same accumulation window** — typically 24-hour totals,
which is what the `APCP_24` / `rf` conventions imply. Comparing a 24-hour forecast
accumulation against, say, a 3-hour observation accumulation will produce scores that
are numerically valid but meteorologically meaningless.

**Missing data and negatives.** Values with magnitude greater than `1e6` are treated
as fill/sentinel values and set to `NaN`. Negative values — which occur in
bias-corrected and otherwise post-processed fields — are clipped to zero rather than
discarded. Grid points where either the forecast or the observation is `NaN` are
excluded from every score.

---

## Grid handling

Forecast and observation grids **do not need to match**.

- Each forecast field is **bilinearly interpolated onto the observation grid** using
  `scipy.interpolate.RegularGridInterpolator`. The observation grid is always the
  verification grid.
- Forecast points that fall outside the observation grid become `NaN` and are excluded.
- Latitude may be stored ascending or descending; the reader honours the file's own
  `(lat, lon)` orientation. This matters for square grids (`nlon == nlat`), where a
  transposition would otherwise go undetected — a bug fixed in v5.0 and covered by a
  regression test.
- Longitudes are used as stored. **0–360 and −180–180 conventions are not converted
  automatically**: if your forecast uses one and your observations the other, convert
  before running, or every point will fall outside the target grid.
- Regridding is bilinear and therefore smooths extremes slightly. For threshold-based
  verification of rare events, consider pre-regridding with a conservative scheme.

---

## Thresholds

Categorical verification uses a single user-specified rainfall threshold, editable in
the sidebar and defaulting to **0.1 mm**.

The threshold is applied as **greater than or equal to** on both fields:

```
forecast event  ⇔  F ≥ threshold
observed event  ⇔  O ≥ threshold
```

A value exactly equal to the threshold counts as an event. The same threshold defines
the binary fields used for FSS, and the event whose probability is scored by the
Brier score and BSS.

---

## Verification scores

With `a` = hits, `b` = false alarms, `c` = misses, `d` = correct negatives and
`N = a+b+c+d`:

### Categorical

| Score | Formula | Range (perfect) |
|---|---|---|
| POD (hit rate, *H*) | `a / (a+c)` | 0 → 1 (1) |
| FAR | `b / (a+b)` | 0 → 1 (0) |
| CSI (threat score) | `a / (a+b+c)` | 0 → 1 (1) |
| BIAS (frequency bias) | `(a+b) / (a+c)` | 0 → ∞ (1) |
| ETS (Gilbert skill score) | `(a−aᵣ) / (a+b+c−aᵣ)`, `aᵣ = (a+b)(a+c)/N` | −⅓ → 1 (1) |
| HSS (Heidke) | `2(ad−bc) / [(a+c)(c+d) + (a+b)(b+d)]` | −1 → 1 (1) |
| PSS (Peirce / Hanssen–Kuipers) | `H − F`, `F = b/(b+d)` | −1 → 1 (1) |
| ACC (proportion correct) | `(a+d) / N` | 0 → 1 (1) |
| Yule's Q (odds-ratio skill) | `(ad−bc) / (ad+bc)` | −1 → 1 (1) |

Any score with a zero denominator returns `NaN` rather than raising an error.

### Extremal dependence (rare events)

These remain informative as the base rate approaches zero, where ETS and CSI
degenerate. With `H = a/(a+c)` and `F = b/(b+d)`:

| Score | Formula | Reference |
|---|---|---|
| EDI | `[ln F − ln H] / [ln F + ln H]` | Ferro & Stephenson (2011) |
| SEDI | `[ln F − ln H − ln(1−F) + ln(1−H)] / [ln F + ln H + ln(1−F) + ln(1−H)]` | Ferro & Stephenson (2011) |
| EDS | `2 ln[(a+c)/N] / ln(a/N) − 1` | Stephenson et al. (2008) |
| SEDS | `{ln[(a+b)/N] + ln[(a+c)/N]} / ln(a/N) − 1` | Hogan et al. (2009) |

EDI and SEDI are undefined (`NaN`) when `H` or `F` equals 0 or 1; EDS and SEDS are
undefined when there are no hits.

### Continuous

Computed on the regridded forecast against the observation, over the selected box
and dates. For ensembles these are computed on the **ensemble mean**.

| Score | Definition |
|---|---|
| ME (mean error / bias) | `mean(F − O)` — positive means the forecast is too wet |
| MAE | `mean(|F − O|)` |
| RMSE | `sqrt(mean((F − O)²))` |
| CORR | Pearson correlation between `F` and `O` |

### Probabilistic (ensemble)

Forecast probability `P` is the fraction of members exceeding the threshold;
`obin` is the binary observation.

| Score | Definition | Notes |
|---|---|---|
| Brier score | `mean((P − obin)²)` | 0 is perfect |
| BSS | `1 − BS / [c̄(1−c̄)]` | `c̄` is the **sample** base rate over the selected box and dates, so BSS is measured against sample climatology, not an independent climatology. `NaN` when `c̄` is 0 or 1 |
| CRPS | `mean|xᵢ − y| − (1/2M²) ΣᵢΣⱼ|xᵢ − xⱼ|` | The standard ("NRG") ensemble estimator, evaluated via the sorted-member identity. This estimator carries a known negative bias that shrinks as *M* grows; the fair/unbiased `1/(2M(M−1))` variant is **not** used |

### Diagnostic plots

- **Reliability diagram** — forecast probability binned into 10 equal-width bins;
  empty bins are omitted. Points on the diagonal indicate a reliable forecast.
- **ROC curve and AUC** — hit rate against false-alarm rate over all distinct
  probability thresholds; AUC by trapezoidal integration. 0.5 means no skill.
- **Relative economic value** — Richardson (2000); the envelope (maximum over
  probability thresholds) against cost/loss ratio.
- **Rank histogram** — verification rank of the observation among *M* members,
  giving `M+1` bins; ties are randomised. Flat indicates good calibration, U-shaped
  under-dispersion, dome-shaped over-dispersion.
- **PIT histogram** — randomised probability integral transform in `[0, 1]`.
- **Spread–skill** — points binned by ensemble standard deviation; mean spread
  against ensemble-mean RMSE per bin. A well-calibrated ensemble lies near 1:1.
- **Taylor diagram** — correlation, standard deviation and centred RMS difference
  for every model on one plot.
- **Q–Q plot** — forecast against observed quantiles.
- **Score maps** — every categorical and continuous score per grid cell, plus CRPS,
  Brier score and BSS for ensembles. Cells with fewer than 3 valid samples are masked.

---

## Spatial verification

Both are opt-in, because they are the most expensive computations in the application.

### FSS — Fractions Skill Score

Roberts & Lean (2008). Forecast and observation are converted to binary fields at
the chosen threshold, each is convolved with a square neighbourhood of side *n*
using `scipy.ndimage.uniform_filter` to give fractional coverages `PF` and `PO`, and

```
FSS(n) = 1 − Σ(PF − PO)² / Σ(PF² + PO²)
```

Numerator and denominator are accumulated across dates before the ratio is taken, so
the seasonal FSS is properly pooled rather than an average of daily values.

- **Neighbourhood sizes** (grid boxes): 1, 3, 5, 9, 15, 21, 31.
- FSS rises from the grid-scale value towards 1 as the neighbourhood grows; the scale
  at which it exceeds `0.5 + f₀/2` is the usual "skilful scale".
- **Boundary treatment:** `uniform_filter` is used with `mode="constant"` (zero
  padding), so fractional coverage is biased low within *n*/2 grid boxes of the domain
  edge. Keep the verification box well inside your data domain.

### CRA — contiguous rain area decomposition

After Ebert & McBride (2000). The forecast field is shifted over
`±8` grid boxes in each direction; the shift minimising the mean squared error is
taken as the displacement error, and the total MSE is decomposed as

```
MSE_total = displacement + volume + pattern
    displacement = MSE_original − MSE_shifted
    volume       = (mean F − mean O)²
    pattern      = MSE_shifted − volume
```

The reported table also gives RMSE, correlation before and after the shift, maximum
and mean rainfall in each field, the optimal displacement `(dx, dy)`, the rain-area
fractions, and each component as a percentage of the total.

> **Two deviations from the published CRA method, stated explicitly:**
>
> 1. **The shift is applied to the whole verification box, not to an identified
>    contiguous rain object.** Ebert & McBride isolate a rain entity above a threshold
>    and shift that object. Here the threshold is used only to report rain-area
>    fractions. Read the output as a whole-field displacement/MSE decomposition.
> 2. **The shift uses `numpy.roll`, which wraps around the domain edges.** Rainfall
>    shifted off one edge reappears on the opposite edge. For a regional domain with
>    rainfall near the boundary this can bias the optimal displacement. Keep the
>    verification box padded away from active rainfall at the edges.
>
> Both are open items, tracked for a future release. See
> [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

---

## Confidence intervals

Confidence intervals are produced by a **non-parametric bootstrap that resamples
whole dates with replacement** — a temporal block bootstrap in which each block is
one valid date.

- Per-date sufficient statistics (contingency counts and running sums) are stored
  once, then resampled and re-summed; the score is recomputed from each resampled
  total. Resampling totals rather than averaging daily scores is what makes ratio
  scores such as ETS and CSI come out correctly.
- Because a whole date is resampled as a unit, **spatial correlation within a date is
  preserved**; the intervals do not assume independent grid points. They do assume
  **independence between dates**, which is optimistic for consecutive days in a
  persistent monsoon spell.
- **Number of resamples** is user-defined in the sidebar.
- **Confidence level** is 95% by default, obtained by the **percentile method**
  (the 2.5th and 97.5th percentiles of the bootstrap distribution). No bias
  correction or acceleration (BCa) is applied.
- The random seed is fixed, so a given dataset and resample count reproduce the same
  interval.
- Resamples that yield an undefined score (a zero denominator) are dropped before the
  percentiles are taken. With very rare events this can make the interval slightly
  optimistic.
- Brier score, BSS and CRPS use the same date-resampling scheme on their per-date
  values.
- At least two dates are required; otherwise `NaN` is returned.

---

## Outputs

- **Score tables** — every score, for every model and lead, downloadable as CSV.
- **Figures** — any plot or map exported as PNG, JPEG, SVG or PDF, with configurable
  width, height and scale (requires `kaleido`, included in `requirements.txt`).
- **Score maps** — per-grid-cell fields for any score, exportable as images.
- **Audit log** — every run appends one JSON line to `logs/audit.jsonl` recording
  timestamp, session id, source mode, input files, period, threshold, box and the
  resulting scores. `python read_audit.py` summarises it; `--csv` exports it. The
  log directory is git-ignored.

---

## Using your own data

Set the paths in the sidebar, or through environment variables:

```bash
export VERIF_DATA_DIR=/path/to/forecasts       # directory of forecast files
export VERIF_OBS=/path/to/observations.nc      # gridded observation file
streamlit run app.py
```

If either variable is unset, or points at a path that does not exist, the application
falls back to the bundled demo data, so a fresh clone always opens successfully.

All available settings are listed in [`.env.example`](.env.example). Copy it to
`.env` and fill it in — `.env` is git-ignored and must never be committed.

Useful preprocessing with [CDO](https://code.mpimet.mpg.de/projects/cdo):

```bash
cdo splitdate day01fcst.nc split/day01_       # per-lead file -> per-date files
cdo mergetime NCUM/*-day1.nc NCUM_day1.nc     # per-date files -> per-lead file
```

---

## Optional features

| Feature | Requirement | Behaviour when absent |
|---|---|---|
| GRIB2 input | `cfgrib` + ECMWF ecCodes (`conda install -c conda-forge cfgrib eccodes`, or the apt packages in [`packages.txt`](packages.txt)) | GRIB files are not listed; NetCDF is unaffected |
| Natural Earth coastlines | `cartopy` | The coastline overlay is empty unless `VERIF_BOUNDARY` is set |
| Official boundary overlay | A GeoJSON or shapefile at `VERIF_BOUNDARY`, or dropped into `./boundary/` | Falls back to Natural Earth, which may not match official national boundaries |
| Shapefile boundaries without cartopy | `geopandas` | GeoJSON still works with no extra dependency |
| Central audit log | `firebase-admin` and a Firestore service-account key at `VERIF_FIREBASE_CRED` | The local JSONL audit log is written regardless |

**No boundary file is distributed with this repository.** Official national boundary
datasets generally carry their own redistribution terms; supply your own and point
`VERIF_BOUNDARY` at it.

---

## Tests

```bash
pip install pytest
pytest -q
```

The suite covers the scientific functions rather than the user interface: contingency
counts, all categorical and extremal-dependence scores, continuous scores, CRPS, the
Brier family, reliability, ROC, rank histogram, PIT, spread–skill, FSS, the CRA
decomposition, bootstrap behaviour, regridding and unit conversion — including
perfect-forecast, complete-miss, all-false-alarm, no-event, missing-value,
zero-denominator and constant-field edge cases.

---

## Documentation

- [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) — verification theory, full formulas,
  references and known methodological caveats.
- [`docs/DEMO_DATA.md`](docs/DEMO_DATA.md) — what the bundled demo dataset contains
  and how it is generated.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — development setup and the rules for adding
  or changing a verification metric.
- [`CHANGELOG.md`](CHANGELOG.md) — release history and what changed in each version.

---

## Author

**Anumeha Dube**

- ORCID: [0000-0002-0341-6955](https://orcid.org/0000-0002-0341-6955)
- Google Scholar: [publication list](https://scholar.google.com/citations?hl=en&user=05uV0jQAAAAJ)

---

## Citation

If this software contributes to published work, please cite it using the metadata in
[`CITATION.cff`](CITATION.cff). GitHub renders that file as a "Cite this repository"
button, which produces BibTeX and APA entries directly.

To mint a DOI, archive a tagged release through [Zenodo](https://zenodo.org) and add
the resulting identifier to `CITATION.cff`.

---

## License

Released under the [MIT License](LICENSE).

The bundled demo dataset is synthetic, generated by `make_demo_data.py`, and is
covered by the same license. No observational or operational forecast data is
distributed with this repository.
