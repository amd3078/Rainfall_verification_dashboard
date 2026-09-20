"""Contingency-table and categorical score tests.

Convention used throughout `app.py`:
    a = hits, b = false alarms, c = misses, d = correct negatives.
Expected values below are computed by hand from the standard definitions
(Wilks 2011, ch. 8; Jolliffe & Stephenson 2012).
"""
import numpy as np
import pytest

import app


# --------------------------------------------------------------------------
# counts()
# --------------------------------------------------------------------------
def test_counts_perfect_forecast():
    O = np.array([[0.0, 10.0], [10.0, 0.0]])
    a, b, c, d = app.counts(O.copy(), O, thr=1.0)
    assert (a, b, c, d) == (2, 0, 0, 2)


def test_counts_complete_miss():
    O = np.array([[10.0, 10.0], [10.0, 10.0]])
    F = np.zeros_like(O)
    a, b, c, d = app.counts(F, O, thr=1.0)
    assert (a, b, c, d) == (0, 0, 4, 0)


def test_counts_all_false_alarms():
    O = np.zeros((2, 2))
    F = np.full((2, 2), 10.0)
    a, b, c, d = app.counts(F, O, thr=1.0)
    assert (a, b, c, d) == (0, 4, 0, 0)


def test_counts_threshold_is_inclusive():
    """A value exactly equal to the threshold counts as an event (>=)."""
    a, b, c, d = app.counts(np.array([1.0]), np.array([1.0]), thr=1.0)
    assert (a, b, c, d) == (1, 0, 0, 0)


def test_counts_ignores_nan_in_either_field():
    F = np.array([10.0, np.nan, 10.0, 0.0])
    O = np.array([10.0, 10.0, np.nan, 0.0])
    a, b, c, d = app.counts(F, O, thr=1.0)
    assert a + b + c + d == 2          # two NaN-containing pairs dropped
    assert (a, b, c, d) == (1, 0, 0, 1)


def test_counts_negative_values_below_threshold():
    """Post-processed negatives must not be treated as events."""
    a, b, c, d = app.counts(np.array([-5.0]), np.array([-5.0]), thr=0.1)
    assert (a, b, c, d) == (0, 0, 0, 1)


# --------------------------------------------------------------------------
# scores_from_counts()
# --------------------------------------------------------------------------
def test_scores_perfect_forecast():
    s = app.scores_from_counts(a=10, b=0, c=0, d=10)
    assert s["POD"] == pytest.approx(1.0)
    assert s["FAR"] == pytest.approx(0.0)
    assert s["CSI"] == pytest.approx(1.0)
    assert s["BIAS"] == pytest.approx(1.0)
    assert s["ETS"] == pytest.approx(1.0)
    assert s["HSS"] == pytest.approx(1.0)
    assert s["PSS"] == pytest.approx(1.0)
    assert s["ACC"] == pytest.approx(1.0)
    assert s["YuleQ"] == pytest.approx(1.0)
    assert s["N"] == 20


def test_scores_known_contingency_table():
    """a=20 b=10 c=5 d=65, N=100 — values derived by hand."""
    s = app.scores_from_counts(20, 10, 5, 65)
    assert s["POD"] == pytest.approx(20 / 25)
    assert s["FAR"] == pytest.approx(10 / 30)
    assert s["CSI"] == pytest.approx(20 / 35)
    assert s["BIAS"] == pytest.approx(30 / 25)
    assert s["ACC"] == pytest.approx(85 / 100)
    assert s["PSS"] == pytest.approx(20 / 25 - 10 / 75)

    a_ref = 30 * 25 / 100                                   # random hits = 7.5
    assert s["ETS"] == pytest.approx((20 - a_ref) / (35 - a_ref))

    num = 2 * (20 * 65 - 10 * 5)
    den = 25 * 70 + 30 * 75
    assert s["HSS"] == pytest.approx(num / den)
    assert s["YuleQ"] == pytest.approx((20 * 65 - 10 * 5) / (20 * 65 + 10 * 5))


def test_scores_zero_denominator_is_nan_not_exception():
    """No events forecast and none observed -> FAR/POD undefined, not a crash."""
    s = app.scores_from_counts(0, 0, 0, 50)
    assert np.isnan(s["POD"])
    assert np.isnan(s["FAR"])
    assert np.isnan(s["CSI"])
    assert s["ACC"] == pytest.approx(1.0)
    assert s["N"] == 50


def test_scores_no_observed_events():
    s = app.scores_from_counts(0, 7, 0, 93)
    assert np.isnan(s["POD"])
    assert s["FAR"] == pytest.approx(1.0)
    assert s["ACC"] == pytest.approx(0.93)


def test_random_forecast_has_zero_skill():
    """Independent forecast/obs -> ETS, HSS and PSS all 0."""
    a, b, c, d = 6, 14, 24, 56          # perfectly independent 2x2 table
    s = app.scores_from_counts(a, b, c, d)
    assert s["ETS"] == pytest.approx(0.0, abs=1e-12)
    assert s["HSS"] == pytest.approx(0.0, abs=1e-12)
    assert s["PSS"] == pytest.approx(0.0, abs=1e-12)
    assert s["YuleQ"] == pytest.approx(0.0, abs=1e-12)


# --------------------------------------------------------------------------
# Extremal-dependence family
# --------------------------------------------------------------------------
def test_edi_sedi_match_reference_formulas():
    """EDI: Ferro & Stephenson (2011). SEDI: same paper, eq. 5."""
    a, b, c, d = 20, 10, 5, 65
    s = app.scores_from_counts(a, b, c, d)
    H = a / (a + c)
    F = b / (b + d)
    edi = (np.log(F) - np.log(H)) / (np.log(F) + np.log(H))
    sedi = ((np.log(F) - np.log(H) - np.log(1 - F) + np.log(1 - H))
            / (np.log(F) + np.log(H) + np.log(1 - F) + np.log(1 - H)))
    assert s["EDI"] == pytest.approx(edi)
    assert s["SEDI"] == pytest.approx(sedi)


def test_eds_seds_match_reference_formulas():
    """EDS: Stephenson et al. (2008). SEDS: Hogan et al. (2009)."""
    a, b, c, d = 20, 10, 5, 65
    N = a + b + c + d
    s = app.scores_from_counts(a, b, c, d)
    eds = 2 * np.log((a + c) / N) / np.log(a / N) - 1
    seds = (np.log((a + b) / N) + np.log((a + c) / N)) / np.log(a / N) - 1
    assert s["EDS"] == pytest.approx(eds)
    assert s["SEDS"] == pytest.approx(seds)


def test_extremal_scores_nan_when_undefined():
    """H or F equal to 0 or 1 -> EDI/SEDI undefined, must return NaN."""
    s = app.scores_from_counts(10, 0, 0, 90)          # F = 0, H = 1
    assert np.isnan(s["EDI"])
    assert np.isnan(s["SEDI"])


def test_edi_approaches_one_for_a_good_rare_event_forecast():
    """Rare event, high hit rate, tiny false-alarm rate -> EDI close to 1."""
    s = app.scores_from_counts(a=9, b=1, c=1, d=9989)
    assert 0.9 < s["EDI"] <= 1.0
    assert 0.9 < s["SEDI"] <= 1.0


# --------------------------------------------------------------------------
# scores() end-to-end on fields
# --------------------------------------------------------------------------
def test_scores_on_fields_matches_counts_path():
    rng = np.random.default_rng(1)
    F = rng.gamma(2.0, 3.0, (20, 20))
    O = rng.gamma(2.0, 3.0, (20, 20))
    direct = app.scores(F, O, 5.0)
    manual = app.scores_from_counts(*app.counts(F, O, 5.0))
    assert direct["CSI"] == pytest.approx(manual["CSI"])
    assert direct["N"] == manual["N"] == 400
