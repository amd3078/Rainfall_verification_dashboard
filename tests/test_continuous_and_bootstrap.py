"""Continuous scores, per-cell score maps and bootstrap confidence intervals.

`boot_metric` / `boot_ci` operate on a per-date statistics array of shape
(Ndates, 12) with the column order
    A, B, C, D, n, sumF, sumO, sumF2, sumO2, sumFO, sum|err|, sum err^2
so that resampling whole dates and summing the columns reproduces any score.
"""
import numpy as np
import pytest

import app


def _perdate_row(F, O, thr):
    """Build one date's 12-column statistics row from a forecast/obs pair."""
    F = np.asarray(F, float).ravel()
    O = np.asarray(O, float).ravel()
    a, b, c, d = app.counts(F, O, thr)
    e = F - O
    return [a, b, c, d, F.size, F.sum(), O.sum(),
            (F ** 2).sum(), (O ** 2).sum(), (F * O).sum(),
            np.abs(e).sum(), (e ** 2).sum()]


# --------------------------------------------------------------------------
# Continuous scores via boot_metric
# --------------------------------------------------------------------------
def test_continuous_scores_match_hand_computation():
    F = np.array([1.0, 2.0, 3.0, 4.0])
    O = np.array([1.5, 1.5, 4.0, 3.0])
    S = np.array([_perdate_row(F, O, 0.1)])

    assert app.boot_metric(S, "ME")[0] == pytest.approx(np.mean(F - O))
    assert app.boot_metric(S, "MAE")[0] == pytest.approx(np.mean(np.abs(F - O)))
    assert app.boot_metric(S, "RMSE")[0] == pytest.approx(np.sqrt(np.mean((F - O) ** 2)))
    assert app.boot_metric(S, "CORR")[0] == pytest.approx(np.corrcoef(F, O)[0, 1])


def test_me_is_zero_and_rmse_is_zero_for_a_perfect_forecast():
    O = np.array([0.0, 3.0, 12.0, 7.5])
    S = np.array([_perdate_row(O, O, 0.1)])
    assert app.boot_metric(S, "ME")[0] == pytest.approx(0.0)
    assert app.boot_metric(S, "MAE")[0] == pytest.approx(0.0)
    assert app.boot_metric(S, "RMSE")[0] == pytest.approx(0.0)


def test_me_sign_convention_is_forecast_minus_observation():
    """A wet-biased forecast must give a positive mean error."""
    O = np.full(10, 2.0)
    S = np.array([_perdate_row(O + 3.0, O, 0.1)])
    assert app.boot_metric(S, "ME")[0] == pytest.approx(3.0)


def test_corr_is_nan_for_a_constant_field():
    """Zero variance -> correlation undefined, must be NaN rather than an error."""
    F = np.full(6, 4.0)
    O = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    S = np.array([_perdate_row(F, O, 0.1)])
    assert np.isnan(app.boot_metric(S, "CORR")[0])


def test_boot_metric_pools_dates_by_summing_columns():
    """Two dates summed must equal one date holding the concatenated sample."""
    F1, O1 = np.array([1.0, 2.0]), np.array([1.0, 3.0])
    F2, O2 = np.array([5.0, 9.0]), np.array([4.0, 9.0])
    split = np.array([_perdate_row(F1, O1, 0.1), _perdate_row(F2, O2, 0.1)])
    joint = np.array([_perdate_row(np.r_[F1, F2], np.r_[O1, O2], 0.1)])
    pooled = app.boot_metric(split.sum(0, keepdims=True), "MAE")[0]
    assert pooled == pytest.approx(app.boot_metric(joint, "MAE")[0])


def test_boot_metric_categorical_matches_scores_from_counts():
    S = np.array([[20, 10, 5, 65, 100, 0, 0, 0, 0, 0, 0, 0]], dtype=float)
    direct = app.scores_from_counts(20, 10, 5, 65)
    for name in ("POD", "FAR", "CSI", "BIAS", "ETS", "HSS", "PSS", "ACC", "YuleQ"):
        assert app.boot_metric(S, name)[0] == pytest.approx(direct[name]), name


def test_boot_metric_unknown_name_returns_nan():
    S = np.zeros((3, 12))
    out = app.boot_metric(S, "NOT_A_SCORE")
    assert out.shape == (3,) and np.all(np.isnan(out))


# --------------------------------------------------------------------------
# Bootstrap confidence intervals (resampling whole dates, percentile method)
# --------------------------------------------------------------------------
def _synthetic_perdate(ndates=40, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(ndates):
        O = rng.gamma(2.0, 3.0, 200)
        F = O * 1.1 + rng.normal(0, 1.0, 200)
        rows.append(_perdate_row(F, O, 1.0))
    return np.array(rows)


def test_bootstrap_ci_brackets_the_point_estimate():
    pd = _synthetic_perdate()
    point = app.boot_metric(pd.sum(0, keepdims=True), "CSI")[0]
    lo, hi = app.boot_ci(pd, "CSI", nboot=400, seed=0)
    assert lo <= point <= hi


def test_bootstrap_ci_is_reproducible_for_a_fixed_seed():
    pd = _synthetic_perdate()
    assert app.boot_ci(pd, "POD", 300, seed=42) == app.boot_ci(pd, "POD", 300, seed=42)


def test_bootstrap_ci_differs_between_seeds():
    pd = _synthetic_perdate()
    assert app.boot_ci(pd, "POD", 300, seed=1) != app.boot_ci(pd, "POD", 300, seed=2)


def test_bootstrap_ci_narrows_as_the_sample_grows():
    wide = app.boot_ci(_synthetic_perdate(8, seed=3), "CSI", 500, seed=0)
    narrow = app.boot_ci(_synthetic_perdate(200, seed=3), "CSI", 500, seed=0)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_bootstrap_ci_level_is_respected():
    """A 50% interval must sit inside the 95% interval."""
    pd = _synthetic_perdate()
    lo95, hi95 = app.boot_ci(pd, "CSI", 800, ci=95, seed=0)
    lo50, hi50 = app.boot_ci(pd, "CSI", 800, ci=50, seed=0)
    assert lo95 <= lo50 <= hi50 <= hi95


def test_bootstrap_ci_needs_at_least_two_dates():
    assert all(np.isnan(v) for v in app.boot_ci(_synthetic_perdate(1), "CSI", 100))
    assert all(np.isnan(v) for v in app.boot_ci(np.zeros((0, 12)), "CSI", 100))


def test_prob_bootstrap_ci_brackets_the_mean_brier_score():
    rng = np.random.default_rng(11)
    pdB = rng.uniform(0.05, 0.35, 50)
    pr = {"pdB": pdB, "pdC": rng.uniform(1.0, 3.0, 50), "pdCl": rng.uniform(0.2, 0.4, 50)}
    lo, hi = app.prob_boot_ci(pr, "Brier", nboot=400, seed=0)
    assert lo <= pdB.mean() <= hi


def test_prob_bootstrap_ci_unknown_score_is_nan():
    pr = {"pdB": np.zeros(5), "pdC": np.zeros(5), "pdCl": np.full(5, 0.3)}
    assert all(np.isnan(v) for v in app.prob_boot_ci(pr, "NOPE", 100))


# --------------------------------------------------------------------------
# Per-cell score maps
# --------------------------------------------------------------------------
def test_cell_maps_mask_cells_with_too_few_samples():
    shape = (3, 3)
    cn = np.full(shape, 5.0)
    cn[0, 0] = 1.0                                  # below minn
    ones = np.ones(shape)
    acc = (cn, ones, ones, ones, ones, ones,
           ones, ones, ones, ones, ones, ones)
    m = app.cell_maps(acc, minn=3)
    assert np.isnan(m["POD"][0, 0])
    assert not np.isnan(m["ACC"][1, 1])


def test_cellwise_categorical_matches_the_scalar_implementation():
    a = np.array([[20.0]]); b = np.array([[10.0]])
    c = np.array([[5.0]]);  d = np.array([[65.0]])
    grid = app.cellwise_cat(a, b, c, d)
    scalar = app.scores_from_counts(20, 10, 5, 65)
    for k in ("POD", "FAR", "CSI", "BIAS", "ETS", "HSS", "PSS", "ACC", "YuleQ"):
        assert grid[k][0, 0] == pytest.approx(scalar[k]), k
