"""Input handling, regridding, unit conversion and a demo-data smoke test."""
import numpy as np
import pytest

import app


# --------------------------------------------------------------------------
# Regridding
# --------------------------------------------------------------------------
def test_regrid_is_the_identity_when_grids_match():
    lon = np.linspace(70.0, 80.0, 11)
    lat = np.linspace(10.0, 20.0, 9)
    rng = np.random.default_rng(0)
    field = rng.gamma(2.0, 2.0, (len(lat), len(lon)))     # readers emit (lat, lon)
    out = app.regrid(lon, lat, field, lon, lat)
    assert out.shape == field.shape
    assert np.allclose(out, field)


def test_regrid_reproduces_a_linear_field_exactly():
    """Bilinear interpolation is exact for a field linear in lon/lat."""
    flon = np.linspace(70.0, 80.0, 6)
    flat = np.linspace(10.0, 20.0, 5)
    LAT, LON = np.meshgrid(flat, flon, indexing="ij")
    field = 2.0 * LON + 3.0 * LAT

    olon = np.linspace(71.0, 79.0, 17)
    olat = np.linspace(11.0, 19.0, 13)
    out = app.regrid(flon, flat, field, olon, olat)

    OLAT, OLON = np.meshgrid(olat, olon, indexing="ij")
    assert np.allclose(out, 2.0 * OLON + 3.0 * OLAT)


def test_regrid_output_has_observation_grid_shape():
    flon = np.linspace(70.0, 90.0, 33)
    flat = np.linspace(8.0, 30.0, 35)
    olon = np.linspace(70.0, 90.0, 41)
    olat = np.linspace(8.0, 30.0, 45)
    out = app.regrid(flon, flat, np.ones((35, 33)), olon, olat)
    assert out.shape == (45, 41)


def test_regrid_handles_a_square_grid_without_transposing():
    """Regression guard: when nlon == nlat the (lat, lon) layout must win."""
    lon = np.linspace(70.0, 80.0, 9)
    lat = np.linspace(10.0, 20.0, 9)
    LAT, LON = np.meshgrid(lat, lon, indexing="ij")
    field = LON * 10.0 + LAT                       # asymmetric, so a transpose shows up
    out = app.regrid(lon, lat, field, lon, lat)
    assert np.allclose(out, field)


def test_regrid_fills_points_outside_the_source_grid_with_nan():
    flon = np.linspace(75.0, 80.0, 6)
    flat = np.linspace(12.0, 18.0, 7)
    out = app.regrid(flon, flat, np.ones((7, 6)),
                     np.array([60.0, 77.0]), np.array([15.0]))
    assert np.isnan(out[0, 0])
    assert out[0, 1] == pytest.approx(1.0)


def test_regrid_propagates_missing_values():
    lon = np.linspace(70.0, 80.0, 6)
    lat = np.linspace(10.0, 20.0, 5)
    field = np.ones((5, 6))
    field[2, 3] = np.nan
    out = app.regrid(lon, lat, field, lon, lat)
    assert np.isnan(out[2, 3])


# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------
@pytest.mark.parametrize("unit,factor", [
    ("mm", 1.0), ("kg m-2", 1.0), ("kg/m2", 1.0),
    ("cm", 10.0), ("m", 1000.0),
])
def test_unit_factor_converts_to_millimetres(unit, factor):
    assert app._unit_factor(unit) == pytest.approx(factor)


def test_unit_factor_is_none_for_an_unknown_unit():
    """Unknown units must not be silently assumed to be mm."""
    assert app._unit_factor("furlongs") is None
    assert app._unit_factor("") is None


# --------------------------------------------------------------------------
# Filename parsing
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name,lead", [
    ("day01fcst_demo.nc", 1),
    ("ModelA-day3_20200615.nc", 3),
    ("NCUM_day5.nc", 5),
])
def test_lead_is_parsed_from_the_filename(name, lead):
    assert app.lead_of(name) == lead


@pytest.mark.parametrize("name,model", [
    ("NCUM_day1.nc", "NCUM"),
    ("ModelA-day3_20200615.nc", "ModelA"),
    ("GFS-day2_20200601.nc", "GFS"),
])
def test_model_name_is_parsed_from_the_filename(name, model):
    assert app._model_name(name) == model


def test_grib_extensions_are_recognised():
    assert app._is_grib("fc.grib2") and app._is_grib("fc.GRB2")
    assert not app._is_grib("fc.nc")


# --------------------------------------------------------------------------
# Demo-data smoke test (the bundled synthetic dataset must verify end to end)
# --------------------------------------------------------------------------
def test_demo_data_produces_sensible_verification_scores():
    import glob

    ocat = app.catalog(app._DEMO_OBS)
    files = sorted(glob.glob(f"{app._DEMO_DIR}/day*fcst*.nc"))
    assert files, "bundled demo forecast files are missing"

    fcat = app.catalog(files[0])
    common = np.intersect1d(fcat["times"], ocat["times"])
    assert len(common) >= 10
    date = common[len(common) // 2]

    O = app.read_slice(app._DEMO_OBS, date)
    F = app.regrid(fcat["lon"], fcat["lat"],
                   app.read_slice(files[0], date), ocat["lon"], ocat["lat"])

    assert O.shape == F.shape
    assert np.isfinite(O).all()

    s = app.scores(F, O, thr=5.0)
    assert s["N"] > 0
    assert 0.0 <= s["POD"] <= 1.0
    assert 0.0 <= s["CSI"] <= 1.0
    assert s["POD"] > 0.5, "demo forecast should show real skill at 5 mm"


def test_demo_ensemble_has_members_and_yields_finite_crps():
    import glob

    files = sorted(glob.glob(f"{app._DEMO_DIR}/day*fcst*.nc"))
    ocat = app.catalog(app._DEMO_OBS)
    fcat = app.catalog(files[0])

    members = fcat["members"]
    assert len(members) >= 10, "demo ensemble should carry multiple members"
    date = np.intersect1d(fcat["times"], ocat["times"])[0]

    O = app.read_slice(app._DEMO_OBS, date)
    ens = np.stack([
        app.regrid(fcat["lon"], fcat["lat"],
                   app.read_slice(files[0], date, member=m), ocat["lon"], ocat["lat"])
        for m in members[:5]
    ])
    crps = app.crps_ens(ens, O, np.isfinite(O))
    assert np.isfinite(crps) and crps >= 0.0


def test_demo_model_folders_are_discovered():
    models = app.discover_models(app._DEMO_DIR)
    assert "ModelA" in models and "ModelB" in models


# --------------------------------------------------------------------------
# selftest()
# --------------------------------------------------------------------------
def test_selftest_runs_and_exercises_real_scores(capsys):
    """It must complete, and the scores it prints must not be degenerate."""
    app.selftest()
    out = capsys.readouterr().out
    assert "selftest OK" in out

    leads = [ln for ln in out.splitlines() if ln.startswith("lead ")]
    assert len(leads) >= 5, "every demo lead should be reported"
    for line in leads:
        assert "nan" not in line.lower(), f"degenerate score in: {line}"
        pod = float(line.split("POD")[1].split()[0])
        csi = float(line.split("CSI")[1].split()[0])
        assert 0.0 < pod <= 1.0, f"POD carries no information in: {line}"
        assert 0.0 < csi <= 1.0, f"CSI carries no information in: {line}"


def test_selftest_threshold_leaves_events_on_both_sides(capsys):
    """The derived threshold must not be above (or at) the observed maximum."""
    app.selftest()
    out = capsys.readouterr().out
    thr = float(out.split("threshold")[1].split("mm")[0])

    ocat = app.catalog(app._DEMO_OBS)
    date = out.split("date ")[1].split()[0]
    O = app.read_slice(app._DEMO_OBS, np.datetime64(date))
    olat, olon = ocat["lat"], ocat["lon"]
    (la0, la1) = np.quantile(olat, [.25, .75])
    (lo0, lo1) = np.quantile(olon, [.25, .75])
    Ob = O[np.ix_((olat >= la0) & (olat <= la1), (olon >= lo0) & (olon <= lo1))]

    assert 0.0 < thr < float(Ob.max()), "threshold must sit inside the observed range"
    assert (Ob >= thr).any() and (Ob < thr).any(), "both events and non-events must exist"


def test_selftest_fails_loudly_when_forecasts_are_missing(tmp_path, monkeypatch):
    """A missing dataset must exit non-zero, not print OK."""
    monkeypatch.setattr(app, "DEFAULT_DIR", str(tmp_path))
    with pytest.raises(SystemExit) as e:
        app.selftest()
    assert e.value.code == 1


def test_selftest_fails_when_the_box_is_dry(monkeypatch):
    """A dry field gives a degenerate table; that must fail rather than pass."""
    real = app.read_slice
    monkeypatch.setattr(
        app, "read_slice",
        lambda p, d, member=None: (np.zeros((45, 41)) if p == app.DEFAULT_OBS
                                   else real(p, d, member)),
    )
    with pytest.raises(SystemExit) as e:
        app.selftest()
    assert e.value.code == 1
