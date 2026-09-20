# Contributing

Thanks for your interest in improving the Rainfall Verification Dashboard.

This is scientific verification software. The most important rule is that **a
verification score must compute what the published literature says it computes**, and
must keep doing so after every change.

---

## Development setup

```bash
git clone https://github.com/amd3078/Rainfall_verification_dashboard.git
cd Rainfall_verification_dashboard

python -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows

pip install -r requirements.txt
pip install pytest
```

Run the application:

```bash
streamlit run app.py
```

Run the tests:

```bash
pytest -q
```

If you need GRIB2 input or Cartopy coastlines, use the conda environment instead —
those depend on compiled libraries that pip cannot install reliably:

```bash
conda env create -f environment.yml
conda activate rainfall-verif
```

---

## Making a change

1. **Open an issue first** for anything beyond a small fix, so the approach can be
   agreed before you write code.
2. **Branch** from `main`:
   ```bash
   git checkout -b fix/short-description
   ```
3. **Keep the change small and focused.** One logical change per pull request.
   Unrelated refactoring makes a scientific change much harder to review.
4. **Run the tests** before pushing:
   ```bash
   pytest -q
   ```
5. **Open a pull request** describing what changed, why, and how you verified it.

---

## Adding or changing a verification metric

This is the part that needs the most care. A pull request that adds or modifies a
score **must** include all three of the following:

### 1. A reference

Cite the paper or textbook that defines the score — author, year, title, journal,
volume, pages. "This is the standard formula" is not a reference. If you are
implementing a variant (a fair estimator, a different reference climatology, a
different normalisation), say which variant and cite it specifically.

### 2. A methodology description

State in the pull request, and in `docs/METHODOLOGY.md`:

- the exact formula, in the same notation as the rest of that document
  (`a` hits, `b` false alarms, `c` misses, `d` correct negatives);
- its range, and the value for a perfect forecast;
- what it measures, and when it is the right choice;
- its degenerate cases — which denominators can be zero, and what the code returns
  then (it must be `NaN`, never an exception);
- any assumption or deviation from the published method. Deviations are acceptable
  when they are documented; silent ones are not.

Also add a row to the "Summary of known caveats" table if the change introduces one.

### 3. Tests

Add tests to `tests/` using small arrays whose expected value you can compute by hand
or from an independent implementation. Cover, where they apply:

- perfect forecast
- complete miss
- all false alarms
- no observed events, and no forecast events
- zero denominators (must return `NaN`, must not raise)
- missing values (`NaN`) in either field
- constant fields (zero variance)
- small arrays, and a single grid point
- pooling: the score over two dates must equal the score of the combined sample
- for ensembles: a single member, identical members, an extreme outlier member

Write the expected value as an explicit number or as an independent recomputation in
the test — not by calling the function under test.

### Rules that are not negotiable

- **Do not change an algorithm to make a test pass.** If a test exposes behaviour you
  believe is wrong, open an issue describing what you found and what the correct
  behaviour should be, with a reference. Changing the science to satisfy a test is
  how silent errors enter verification software.
- **Do not change a formula while reorganising code.** Refactoring and scientific
  changes belong in separate pull requests.
- **Undefined means `NaN`.** Never return 0, never raise, never substitute a default.
- **Accumulate sufficient statistics, then compute the score.** Never average daily
  scores to get a seasonal score — that is wrong for every ratio score.
- **Preserve the existing sign and denominator conventions.** ME is forecast minus
  observation; FAR is `b/(a+b)`; the false-alarm *rate* `F` is `b/(b+d)`. These are
  distinct and both are used.

---

## Code style

Match the surrounding code. The existing style is compact and NumPy-vectorised, with
a short docstring on each function.

- Vectorise with NumPy; avoid per-grid-point Python loops.
- Guard every division that can have a zero denominator
  (`np.errstate(divide="ignore", invalid="ignore")` and an explicit `NaN`).
- Use `pathlib` or `os.path` joins for file paths. **Never hard-code an absolute
  path**, and never commit one.
- Keep the scientific functions free of Streamlit calls where you reasonably can —
  functions that take arrays and return numbers are the ones that can be tested.

---

## Data

- **Never commit** real observations, operational forecasts, downloaded NetCDF or
  GRIB files, boundary shapefiles, credentials, `.env` files, logs or generated
  output. The `.gitignore` is set up to block these; do not add exceptions to it.
- The only data in the repository is the synthetic demo set in `demo_data/`,
  regenerable with `python make_demo_data.py` and documented in
  [`docs/DEMO_DATA.md`](docs/DEMO_DATA.md).
- If you extend the demo data, keep it synthetic, keep it small, and update that
  document.

---

## Reporting a bug

Open an issue with:

- what you did, what you expected, and what happened;
- the exact error message, if any;
- your OS, Python version and how you installed the dependencies;
- whether it reproduces with the bundled demo data — and if not, the *structure* of
  your data (dimensions, variable names, coordinate names, units), **not the data
  itself**.

For a suspected error in a score, include the input arrays if they are small, the
value you got, the value you expected, and the reference the expected value comes
from.

---

## License

By contributing you agree that your contribution is licensed under the
[MIT License](LICENSE), like the rest of the project.
