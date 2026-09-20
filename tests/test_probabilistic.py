"""Ensemble / probabilistic verification tests.

Covers CRPS, the Brier family, reliability, ROC, rank histogram, PIT and
spread-skill. Expected values are derived from the closed-form definitions.
"""
import numpy as np
import pytest

import app


# --------------------------------------------------------------------------
# CRPS  (energy/"NRG" estimator:  mean|x_i - y| - 1/(2M^2) * sum_ij |x_i - x_j|)
# --------------------------------------------------------------------------
def test_crps_single_member_equals_absolute_error():
    """With M = 1 the spread term vanishes and CRPS reduces to |x - y|."""
    ens = np.array([[7.0, 2.0, 0.0]])          # (M=1, Npts=3)
    y = np.array([4.0, 2.0, 5.0])
    assert app.crps_points(ens, y) == pytest.approx(np.mean([3.0, 0.0, 5.0]))


def test_crps_two_member_hand_computed():
    """Members {0, 1}, obs 0.  t1 = 0.5, spread term = 0.25  ->  CRPS = 0.25."""
    ens = np.array([[0.0], [1.0]])
    y = np.array([0.0])
    assert app.crps_points(ens, y) == pytest.approx(0.25)


def test_crps_matches_double_sum_definition():
    """Sorted-formula implementation must equal the explicit double sum."""
    rng = np.random.default_rng(7)
    ens = rng.gamma(2.0, 2.0, (11, 40))
    y = rng.gamma(2.0, 2.0, 40)
    M = ens.shape[0]
    t1 = np.mean(np.abs(ens - y[None]), axis=0)
    spread = np.abs(ens[:, None, :] - ens[None, :, :]).sum(axis=(0, 1)) / (2 * M ** 2)
    assert app.crps_points(ens, y) == pytest.approx(float(np.mean(t1 - spread)))


def test_crps_zero_for_a_perfect_deterministic_ensemble():
    """All members identical and equal to the observation -> CRPS = 0."""
    ens = np.full((9, 25), 3.0)
    y = np.full(25, 3.0)
    assert app.crps_points(ens, y) == pytest.approx(0.0, abs=1e-12)


def test_crps_penalises_a_biased_ensemble_more():
    ens = np.tile(np.linspace(0.0, 2.0, 5)[:, None], (1, 30))
    y = np.full(30, 1.0)
    biased = app.crps_points(ens + 10.0, y)
    unbiased = app.crps_points(ens, y)
    assert biased > unbiased


def test_crps_grid_and_crps_ens_agree():
    rng = np.random.default_rng(3)
    ens = rng.gamma(2.0, 2.0, (8, 6, 7))
    obs = rng.gamma(2.0, 2.0, (6, 7))
    mask = np.ones((6, 7), dtype=bool)
    assert app.crps_ens(ens, obs, mask) == pytest.approx(float(np.mean(app.crps_grid(ens, obs))))


def test_crps_points_empty_is_nan():
    assert np.isnan(app.crps_points(np.empty((0, 0)), np.array([])))


# --------------------------------------------------------------------------
# Brier score / Brier skill score
# --------------------------------------------------------------------------
def test_brier_perfect_probability_forecast():
    O = np.array([[10.0, 0.0], [0.0, 10.0]])
    P = np.array([[1.0, 0.0], [0.0, 1.0]])
    mask = np.ones_like(O, dtype=bool)
    r = app.prob_scores(P, O, thr=1.0, mask=mask)
    assert r["Brier"] == pytest.approx(0.0)
    assert r["clim"] == pytest.approx(0.5)
    assert r["BSS"] == pytest.approx(1.0)


def test_brier_worst_possible_forecast():
    O = np.array([[10.0, 0.0]])
    P = np.array([[0.0, 1.0]])
    mask = np.ones_like(O, dtype=bool)
    assert app.prob_scores(P, O, 1.0, mask)["Brier"] == pytest.approx(1.0)


def test_bss_zero_for_a_climatological_forecast():
    """Forecasting the sample base rate everywhere gives BSS = 0 by construction."""
    O = np.array([10.0, 10.0, 0.0, 0.0, 0.0, 0.0, 10.0, 0.0])
    clim = 3 / 8
    P = np.full_like(O, clim)
    mask = np.ones_like(O, dtype=bool)
    r = app.prob_scores(P, O, 1.0, mask)
    assert r["clim"] == pytest.approx(clim)
    assert r["BSS"] == pytest.approx(0.0, abs=1e-12)


def test_bss_nan_when_no_events_observed():
    """Base rate 0 -> reference Brier score 0 -> BSS undefined, must be NaN."""
    O = np.zeros((4, 4))
    P = np.full((4, 4), 0.2)
    r = app.prob_scores(P, O, 1.0, np.ones((4, 4), dtype=bool))
    assert r["clim"] == pytest.approx(0.0)
    assert np.isnan(r["BSS"])


def test_prob_scores_respects_mask():
    O = np.array([[10.0, 0.0], [0.0, 0.0]])
    P = np.array([[1.0, 1.0], [1.0, 1.0]])
    mask = np.array([[True, False], [False, False]])
    assert app.prob_scores(P, O, 1.0, mask)["Brier"] == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Reliability / ROC / relative economic value
# --------------------------------------------------------------------------
def test_reliability_of_a_perfectly_reliable_forecast():
    p = np.repeat([0.05, 0.45, 0.95], 400)
    rng = np.random.default_rng(0)
    obin = (rng.random(p.size) < p).astype(float)
    mp, of, n = app.reliability_curve(p, obin, nb=10)
    assert n.sum() == p.size
    assert np.allclose(mp, of, atol=0.05)


def test_reliability_skips_empty_bins():
    p = np.array([0.05, 0.05, 0.95])
    obin = np.array([0.0, 0.0, 1.0])
    mp, of, n = app.reliability_curve(p, obin, nb=10)
    assert len(mp) == 2                       # only two bins are populated
    assert n.tolist() == [2, 1]


def test_roc_auc_is_one_for_perfect_discrimination():
    p = np.r_[np.full(50, 0.9), np.full(50, 0.1)]
    obin = np.r_[np.ones(50), np.zeros(50)]
    _, _, auc = app.roc_curve(p, obin)
    assert auc == pytest.approx(1.0)


def test_roc_auc_is_half_for_no_discrimination():
    """Constant probability carries no information -> AUC = 0.5."""
    p = np.full(200, 0.4)
    obin = np.r_[np.ones(100), np.zeros(100)]
    _, _, auc = app.roc_curve(p, obin)
    assert auc == pytest.approx(0.5, abs=1e-9)


def test_rev_is_non_negative_for_a_perfect_forecast():
    p = np.r_[np.ones(40), np.zeros(60)]
    obin = np.r_[np.ones(40), np.zeros(60)]
    v = app.rev_curve(p, obin, np.linspace(0.05, 0.95, 19))
    assert np.all(v > 0.99)


# --------------------------------------------------------------------------
# Rank histogram / PIT / spread-skill
# --------------------------------------------------------------------------
def test_rank_histogram_length_and_total():
    rng = np.random.default_rng(5)
    ens = rng.normal(0, 1, (10, 500))
    obs = rng.normal(0, 1, 500)
    h = app.rank_hist(ens, obs)
    assert len(h) == 11                       # M + 1 bins
    assert h.sum() == 500


def test_rank_histogram_u_shaped_for_underdispersive_ensemble():
    """Spread far too small -> obs falls outside the ensemble -> extreme ranks."""
    rng = np.random.default_rng(6)
    ens = rng.normal(0.0, 0.01, (10, 2000))
    obs = rng.normal(0.0, 1.0, 2000)
    h = app.rank_hist(ens, obs)
    assert (h[0] + h[-1]) > 0.9 * h.sum()


def test_pit_values_within_unit_interval():
    rng = np.random.default_rng(8)
    ens = rng.normal(0, 1, (12, 300))
    obs = rng.normal(0, 1, 300)
    pit = app.pit_values(ens, obs)
    assert pit.min() >= 0.0 and pit.max() <= 1.0
    assert pit.shape == (300,)


def test_spread_skill_returns_finite_bins():
    rng = np.random.default_rng(9)
    spread = rng.uniform(0.5, 4.0, 800)
    ens = rng.normal(0.0, 1.0, (12, 800)) * spread
    obs = rng.normal(0.0, 1.0, 800) * spread
    xs, ys, msd, rmse = app.spread_skill(ens, obs, nbin=6)
    assert len(xs) == len(ys) > 0
    assert np.all(np.isfinite(xs)) and np.all(np.isfinite(ys))
    assert msd > 0 and rmse > 0
