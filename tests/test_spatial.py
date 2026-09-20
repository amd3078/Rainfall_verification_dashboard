"""Spatial verification tests: FSS (Roberts & Lean 2008) and the CRA-style
MSE decomposition (after Ebert & McBride 2000).

`app.fss_accum` returns, per neighbourhood size n, the pair
    (numerator, denominator) = (sum (PF-PO)^2, sum (PF^2 + PO^2))
so that   FSS(n) = 1 - numerator / denominator.
"""
import numpy as np
import pytest

import app


def _fss(num, den):
    return 1.0 - num / den if den else np.nan


# --------------------------------------------------------------------------
# FSS
# --------------------------------------------------------------------------
def test_fss_is_one_for_identical_binary_fields():
    rng = np.random.default_rng(0)
    BO = (rng.random((20, 20)) > 0.7)
    acc = app.fss_accum(BO.copy(), BO, [1, 3, 5])
    for n in (1, 3, 5):
        num, den = acc[n]
        assert _fss(num, den) == pytest.approx(1.0)


def test_fss_is_zero_for_disjoint_events_at_gridscale():
    """No overlap at n = 1 -> numerator equals denominator -> FSS = 0."""
    BF = np.zeros((10, 10), dtype=bool)
    BO = np.zeros((10, 10), dtype=bool)
    BF[2, 2] = BF[2, 3] = True
    BO[7, 7] = BO[7, 8] = True
    num, den = app.fss_accum(BF, BO, [1])[1]
    assert _fss(num, den) == pytest.approx(0.0)


def test_fss_improves_with_a_larger_neighbourhood():
    """A small displacement is forgiven once the neighbourhood spans it."""
    BF = np.zeros((31, 31), dtype=bool)
    BO = np.zeros((31, 31), dtype=bool)
    BO[15, 15] = True
    BF[15, 18] = True                      # 3 grid boxes to the east
    acc = app.fss_accum(BF, BO, [1, 3, 9, 15])
    vals = [_fss(*acc[n]) for n in (1, 3, 9, 15)]
    assert vals[0] == pytest.approx(0.0)   # no overlap at grid scale
    assert vals[-1] > vals[0]              # large neighbourhood scores better
    assert all(b >= a - 1e-12 for a, b in zip(vals, vals[1:]))


def test_fss_accum_returns_every_requested_neighbourhood():
    BF = np.zeros((12, 12), dtype=bool)
    BO = np.zeros((12, 12), dtype=bool)
    BF[5, 5] = BO[5, 5] = True
    acc = app.fss_accum(BF, BO, app.FSS_NS)
    assert sorted(acc) == sorted(app.FSS_NS)
    assert all(isinstance(v, tuple) and len(v) == 2 for v in acc.values())


def test_fss_denominator_zero_when_no_events_anywhere():
    """Empty fields give a 0/0 FSS; the accumulator must report den = 0, not crash."""
    z = np.zeros((8, 8), dtype=bool)
    num, den = app.fss_accum(z, z, [3])[3]
    assert num == 0.0 and den == 0.0


# --------------------------------------------------------------------------
# CRA-style decomposition
# --------------------------------------------------------------------------
def _blob(ny, nx, cy, cx, amp=20.0, sig=3.0):
    y, x = np.mgrid[0:ny, 0:nx]
    return amp * np.exp(-(((y - cy) ** 2 + (x - cx) ** 2) / (2 * sig ** 2)))


def test_cra_all_components_zero_for_a_perfect_forecast():
    O = _blob(41, 41, 20, 20)
    r = app.cra_decomp(O.copy(), O)
    assert r["total"] == pytest.approx(0.0, abs=1e-12)
    assert r["displacement"] == pytest.approx(0.0, abs=1e-12)
    assert r["volume"] == pytest.approx(0.0, abs=1e-12)
    assert r["pattern"] == pytest.approx(0.0, abs=1e-12)
    assert r["CORR"] == pytest.approx(1.0)


def test_cra_components_sum_to_total_mse():
    """The decomposition must be additive: total = displacement + volume + pattern."""
    O = _blob(41, 41, 20, 20)
    F = _blob(41, 41, 20, 24, amp=26.0)
    r = app.cra_decomp(F, O, maxs=8)
    total = r["displacement"] + r["volume"] + r["pattern"]
    assert total == pytest.approx(r["total"], rel=1e-9)


def test_cra_recovers_a_pure_translation():
    """A blob displaced 4 columns east is corrected by a shift of -4."""
    O = _blob(41, 41, 20, 20)
    F = _blob(41, 41, 20, 24)
    r = app.cra_decomp(F, O, maxs=8)
    assert r["dx"] == pytest.approx(-4.0)
    assert r["dy"] == pytest.approx(0.0)
    assert r["displacement"] == pytest.approx(r["total"], rel=1e-6)
    assert r["pattern"] == pytest.approx(0.0, abs=1e-9)
    assert r["CORR_shift"] > r["CORR"]


def test_cra_isolates_a_pure_amplitude_error():
    """Same position, uniformly larger amplitude -> error is volume, not displacement."""
    O = _blob(41, 41, 20, 20)
    F = O + 5.0
    r = app.cra_decomp(F, O, maxs=4)
    assert r["dx"] == pytest.approx(0.0)
    assert r["dy"] == pytest.approx(0.0)
    assert r["volume"] == pytest.approx(25.0, rel=1e-9)
    assert r["displacement"] == pytest.approx(0.0, abs=1e-9)


def test_cra_rmse_matches_total():
    O = _blob(31, 31, 15, 15)
    F = _blob(31, 31, 15, 18, amp=24.0)
    r = app.cra_decomp(F, O, maxs=6)
    assert r["RMSE"] == pytest.approx(np.sqrt(r["total"]))


def test_cra_treats_nan_as_zero_rainfall():
    """NaNs are filled with 0 before the shift search, so they must not propagate."""
    O = _blob(21, 21, 10, 10)
    F = O.copy()
    F[0, 0] = np.nan
    r = app.cra_decomp(F, O, maxs=3)
    assert np.isfinite(r["total"])
    assert np.isfinite(r["RMSE"])


def test_cra_reports_event_area_fractions():
    O = np.zeros((10, 10))
    O[:5, :] = 10.0                       # half the domain is raining
    F = np.zeros((10, 10))
    F[:2, :] = 10.0
    r = app.cra_decomp(F, O, maxs=2, thr=0.1)
    assert r["areaO"] == pytest.approx(0.5)
    assert r["areaF"] == pytest.approx(0.2)
