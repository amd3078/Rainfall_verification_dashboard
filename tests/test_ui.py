"""User-interface tests driven through Streamlit's headless AppTest harness.

These run the real `app.py` script, set real sidebar widgets and click the real
run button, so they cover `run_app()` and `_run_multimodel()` — the bulk of the
file, which the numerical tests do not reach. No browser is involved.

They assert that each mode completes without raising and produces a score
table, and that the numbers the UI renders match the separately tested
scientific functions.
"""
import glob
from pathlib import Path

import numpy as np
import pytest

import app

APP = str(Path(__file__).resolve().parents[1] / "app.py")
ENSEMBLE_FOLDER = "· (files in this folder)"

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def fresh():
    at = AppTest.from_file(APP, default_timeout=600)
    at.run()
    return at


def set_radio(at, label, value):
    for r in at.sidebar.radio:
        if r.label == label:
            r.set_value(value)
            return
    raise AssertionError(f"sidebar radio {label!r} not found")


def set_select(at, label, value):
    for s in at.sidebar.selectbox:
        if s.label == label:
            assert value in s.options, f"{value!r} not offered by {label!r}"
            s.set_value(value)
            return
    raise AssertionError(f"sidebar selectbox {label!r} not found")


def set_check(at, label_prefix, value):
    for c in at.sidebar.checkbox:
        if c.label.startswith(label_prefix):
            c.set_value(value)
            return
    raise AssertionError(f"sidebar checkbox {label_prefix!r} not found")


def run(at):
    for b in at.button:
        if "Run verification" in b.label:
            b.click().run()
            return at
    raise AssertionError("the run button was not found")


def assert_clean(at):
    assert not at.exception, f"app raised: {[str(e.value)[:300] for e in at.exception]}"
    assert not at.error, f"app reported an error: {[m.value[:300] for m in at.error]}"


# --------------------------------------------------------------------------
# the app loads
# --------------------------------------------------------------------------
def test_app_starts_on_the_bundled_demo_without_configuration():
    at = fresh()
    assert_clean(at)
    paths = [t.value for t in at.sidebar.text_input]
    assert any("demo_data" in p for p in paths), "a fresh start must default to the demo data"


def test_app_warns_that_the_demo_data_carries_no_units():
    """The demo files have no `units` attribute; that must be surfaced, not assumed."""
    at = fresh()
    warnings = " ".join(m.value for m in at.warning).lower()
    assert "units" in warnings


def test_sidebar_offers_the_documented_modes():
    at = fresh()
    labels = {r.label: r.options for r in at.sidebar.radio}
    assert "Ensemble" in labels["Forecast type"] and "Deterministic" in labels["Forecast type"]
    assert "Single" in labels["Models"] and "Multiple" in labels["Models"]
    assert "Daily" in labels["Verification period"] and "Seasonal" in labels["Verification period"]


def test_demo_model_folders_are_offered_in_the_model_picker():
    at = fresh()
    opts = [s.options for s in at.sidebar.selectbox if s.label == "Model"][0]
    assert "ModelA" in opts and "ModelB" in opts


# --------------------------------------------------------------------------
# every mode runs end to end
# --------------------------------------------------------------------------
def _ensemble(at):
    set_select(at, "Model", ENSEMBLE_FOLDER)


MODES = [
    ("ensemble-single-mean-seasonal", lambda at: _ensemble(at)),
    ("ensemble-single-probabilistic", lambda at: (_ensemble(at),
                                                  set_radio(at, "Ensemble verification", "Probabilistic"))),
    ("ensemble-single-mean-daily", lambda at: (_ensemble(at),
                                               set_radio(at, "Verification period", "Daily"))),
    ("ensemble-multiple", lambda at: set_radio(at, "Models", "Multiple")),
    ("deterministic-single", lambda at: set_radio(at, "Forecast type", "Deterministic")),
    ("deterministic-multiple", lambda at: (set_radio(at, "Forecast type", "Deterministic"),
                                           set_radio(at, "Models", "Multiple"))),
    ("deterministic-multiple-daily", lambda at: (set_radio(at, "Forecast type", "Deterministic"),
                                                 set_radio(at, "Models", "Multiple"),
                                                 set_radio(at, "Verification period", "Daily"))),
]


@pytest.mark.parametrize("name,setup", MODES, ids=[m[0] for m in MODES])
def test_mode_runs_and_produces_a_score_table(name, setup):
    at = fresh()
    setup(at)
    run(at)
    assert_clean(at)
    assert at.dataframe, f"{name} produced no score table"
    df = at.dataframe[0].value
    assert len(df) > 0, f"{name} produced an empty score table"
    assert "lead" in df.columns


def test_spatial_diagnostics_add_a_second_table():
    at = fresh()
    _ensemble(at)
    set_check(at, "Spatial diagnostics", True)
    run(at)
    assert_clean(at)
    assert len(at.dataframe) >= 2, "FSS/CRA should add their own table"


def test_bootstrap_confidence_intervals_run():
    at = fresh()
    _ensemble(at)
    set_check(at, "Bootstrap confidence intervals", True)
    run(at)
    assert_clean(at)
    assert at.dataframe


def test_everything_enabled_at_once():
    at = fresh()
    set_radio(at, "Forecast type", "Deterministic")
    set_radio(at, "Models", "Multiple")
    set_check(at, "Spatial diagnostics", True)
    set_check(at, "Bootstrap confidence intervals", True)
    run(at)
    assert_clean(at)
    assert len(at.dataframe) >= 2


# --------------------------------------------------------------------------
# the overlay must never take the app down
# --------------------------------------------------------------------------
def test_a_failing_coastline_overlay_does_not_break_the_run(monkeypatch):
    """Regression: `coastlines()` imported shapely outside its try block, so on a
    pip install without shapely -- and the overlay checkbox defaults to on --
    *every* verification run died with ModuleNotFoundError."""
    def explode(*a, **k):
        raise ModuleNotFoundError("No module named 'shapely'")

    monkeypatch.setattr(app, "_polylines", explode)
    app._COAST.clear()
    xs, ys = app.coastlines(70, 90, 8, 30)
    assert xs == [] and ys == [], "a failing overlay must degrade to no coastlines"


def test_run_completes_with_the_coastline_overlay_enabled():
    at = fresh()
    _ensemble(at)
    set_check(at, "Show coastlines", True)
    run(at)
    assert_clean(at)
    assert at.dataframe


# --------------------------------------------------------------------------
# the UI must agree with the tested science
# --------------------------------------------------------------------------
def test_ui_probabilistic_scores_match_the_science_functions():
    """Guards against the UI wiring the right function to the wrong data."""
    at = fresh()
    _ensemble(at)
    set_radio(at, "Ensemble verification", "Probabilistic")
    run(at)
    assert_clean(at)

    df = at.dataframe[0].value
    row = df[df["lead"] == 1].iloc[0]
    thr = [n.value for n in at.sidebar.number_input if n.label.startswith("Rain threshold")][0]

    oc = app.catalog(app._DEMO_OBS)
    f = sorted(glob.glob(f"{app._DEMO_DIR}/day01fcst*.nc"))[0]
    fc = app.catalog(f)
    bs, cl = [], []
    for d in np.intersect1d(fc["times"], oc["times"]):
        O = app.read_slice(app._DEMO_OBS, d)
        ens = np.stack([app.regrid(fc["lon"], fc["lat"], app.read_slice(f, d, member=m),
                                   oc["lon"], oc["lat"]) for m in fc["members"]])
        mask = np.isfinite(O) & np.isfinite(ens).all(0)
        r = app.prob_scores((ens >= thr).mean(0), O, thr, mask)
        bs.append(r["Brier"]); cl.append(r["clim"])

    brier = float(np.mean(bs)); clim = float(np.mean(cl))
    assert row["Brier"] == pytest.approx(brier, rel=1e-6)
    assert row["BSS"] == pytest.approx(1 - brier / (clim * (1 - clim)), rel=1e-6)
