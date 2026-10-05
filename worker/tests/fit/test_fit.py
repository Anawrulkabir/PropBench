"""Fitting engine: parameter recovery on synthetic ECS data, weights, scale factors, seeds, Bayesian linear fit."""

from dataclasses import replace

import CoolProp.CoolProp as CP  # noqa: N817 - the name CoolProp itself documents
import numpy as np
import pytest

from propbench.core import Dataset, DatasetError, Quantity
from propbench.fit import FitError, ard, bayesian_linear_fit, deviations, fit, fit_data
from propbench.models import ECSViscosity

# Published ECS parameters of R236fa relative to R134a (Huber et al. 2003, as stored in CoolProp), linear ψ.
TRUE_PSI = (1.10195, -0.0294253)
SIGMA, EPSILON_K, RHO_RED = 5.644e-10, 307.24, 3626.0

STATES = [(t, p) for t in (260.0, 300.0, 340.0, 380.0) for p in (1.0e5, 2.0e6, 1.0e7)]


def make_model(psi):
    return ECSViscosity.create(
        "R236FA", "R134a", sigma=SIGMA, epsilon_k=EPSILON_K, psi=psi, psi_rhomolar_reducing=RHO_RED
    )


def synthetic(model, states, name="synthetic", factor=1.0, noise=0.0, seed=0, u=0.01):
    t = np.array([s[0] for s in states])
    p = np.array([s[1] for s in states])
    rho = np.array([CP.PropsSI("Dmolar", "T", ti, "P", pi, "R236FA") for ti, pi in states])
    eta = model.predict(t, rho) * factor
    if noise:
        eta = eta * (1 + noise * np.random.Generator(np.random.PCG64(seed)).standard_normal(len(eta)))
    return Dataset(
        name, "R236FA", Quantity.VISCOSITY, t, eta, pressure=p, expanded_uncertainty=2 * u * eta, coverage_factor=2.0
    )


@pytest.fixture(scope="module")
def truth():
    return make_model(TRUE_PSI)


def test_ard_sign_convention():
    # positive when the model is below the data
    assert ard(1.1, 1.0) == pytest.approx(10.0)
    assert ard(0.9, 1.0) == pytest.approx(-10.0)
    d = deviations([1.1, 0.9], [1.0, 1.0])
    assert d.n == 2
    assert d.aard == pytest.approx(10.0)
    assert d.bias == pytest.approx(0.0)
    assert d.max_abs == pytest.approx(10.0)


def test_fit_data_converts_pressure_to_density_and_combines(truth):
    a = synthetic(truth, STATES[:5], "a")
    b = synthetic(truth, STATES[5:], "b")
    data = fit_data([a, b])
    assert len(data) == len(STATES)
    assert data.dataset_names == ("a", "b")
    np.testing.assert_array_equal(data.dataset_index, [0] * 5 + [1] * (len(STATES) - 5))
    expected = CP.PropsSI("Dmolar", "T", STATES[0][0], "P", STATES[0][1], "R236FA")
    assert data.molar_density[0] == pytest.approx(expected, rel=1e-12)
    np.testing.assert_allclose(data.relative_uncertainty, 0.01)
    sub = data.select(data.dataset_index == 1)
    assert len(sub) == len(STATES) - 5


def test_fit_data_rejects_mixed_fluids(truth):
    a = synthetic(truth, STATES[:3], "a")
    other = Dataset("b", "R134a", Quantity.VISCOSITY, [300.0], [1e-4], pressure=[1e6])
    with pytest.raises(DatasetError):
        fit_data([a, other])


def test_prepared_ecs_matches_predict(truth):
    data = fit_data([synthetic(truth, STATES)])
    prepared = truth.prepare(data.temperature, data.molar_density)
    values = {"psi_0": 1.05, "psi_1": -0.01}
    expected = truth.with_params(values).predict(data.temperature, data.molar_density)
    np.testing.assert_allclose(prepared.evaluate(values), expected, rtol=1e-14)


def test_recovers_parameters_from_noise_free_data(truth):
    data = fit_data([synthetic(truth, STATES)])
    result = fit(make_model((1.0, 0.0)), data)
    assert result.success
    assert result.values["psi_0"] == pytest.approx(TRUE_PSI[0], rel=1e-6)
    assert result.values["psi_1"] == pytest.approx(TRUE_PSI[1], rel=1e-4)
    assert result.deviations.aard < 1e-5
    assert result.weighted


def test_noisy_fit_is_consistent_with_standard_errors(truth):
    data = fit_data([synthetic(truth, STATES, noise=0.005, seed=3, u=0.005)])
    result = fit(make_model((1.0, 0.0)), data)
    for name, true in zip(("psi_0", "psi_1"), TRUE_PSI, strict=True):
        assert abs(result.values[name] - true) < 4 * result.standard_errors[name]
    assert 0.1 < result.deviations.aard < 1.0


def test_unweighted_fit_ignores_uncertainties(truth):
    data = fit_data([synthetic(truth, STATES)])
    result = fit(make_model((1.0, 0.0)), data, weighted=False)
    assert not result.weighted
    assert result.values["psi_0"] == pytest.approx(TRUE_PSI[0], rel=1e-6)


def test_scale_factor_recovers_dataset_offset(truth):
    a = synthetic(truth, STATES, "reference")
    b = synthetic(truth, STATES[::2], "offset", factor=1.03)
    result = fit(make_model((1.0, 0.0)), fit_data([a, b]), scale_factors=True)
    assert result.scale_factors["offset"] == pytest.approx(1.03, rel=1e-6)
    assert result.values["psi_0"] == pytest.approx(TRUE_PSI[0], rel=1e-6)
    assert result.deviations.aard < 1e-5


def test_multistart_is_deterministic_for_a_seed(truth):
    data = fit_data([synthetic(truth, STATES, noise=0.005, seed=1)])
    r1 = fit(make_model((1.0, 0.0)), data, multistart=2, seed=11)
    r2 = fit(make_model((1.0, 0.0)), data, multistart=2, seed=11)
    assert r1.starts == 3
    assert r1.seed == 11
    assert r1.values == r2.values
    assert r1.nfev == r2.nfev


def test_fit_without_free_parameters_raises(truth):
    data = fit_data([synthetic(truth, STATES[:3])])
    frozen = replace(truth, parameters={k: replace(v, fixed=True) for k, v in truth.parameters.items()})
    with pytest.raises(FitError):
        fit(frozen, data)


def test_bayesian_flat_prior_equals_weighted_least_squares():
    rng = np.random.Generator(np.random.PCG64(5))
    x = np.column_stack([np.ones(20), np.linspace(0, 1, 20)])
    sigma = np.full(20, 0.1)
    y = x @ np.array([2.0, -1.0]) + sigma * rng.standard_normal(20)
    result = bayesian_linear_fit(x, y, sigma)
    expected, *_ = np.linalg.lstsq(x / sigma[:, None], y / sigma, rcond=None)
    np.testing.assert_allclose(result.mean, expected, rtol=1e-12)
    np.testing.assert_allclose(result.covariance, np.linalg.inv((x / sigma[:, None]).T @ (x / sigma[:, None])))
    assert np.isnan(result.log_evidence)


def test_bayesian_conjugate_posterior_of_a_mean():
    # one parameter, y_i ~ N(b, σ²), prior b ~ N(m0, s0²): posterior precision 1/s0² + n/σ²
    y = np.array([1.0, 2.0, 3.0])
    sigma, m0, s0 = 1.0, 0.0, 2.0
    result = bayesian_linear_fit(np.ones((3, 1)), y, sigma, prior_mean=[m0], prior_covariance=[[s0**2]])
    precision = 1 / s0**2 + 3 / sigma**2
    assert result.covariance[0, 0] == pytest.approx(1 / precision)
    assert result.mean[0] == pytest.approx((m0 / s0**2 + y.sum() / sigma**2) / precision)
    # evidence: y ~ N(0, σ² I + s0² 11ᵀ)
    cov = sigma**2 * np.eye(3) + s0**2 * np.ones((3, 3))
    expected = -0.5 * (y @ np.linalg.solve(cov, y) + np.linalg.slogdet(cov)[1] + 3 * np.log(2 * np.pi))
    assert result.log_evidence == pytest.approx(expected)
    mean, sd = result.predict(np.array([[1.0]]))
    assert mean[0] == pytest.approx(result.mean[0])
    assert sd[0] == pytest.approx(np.sqrt(1 / precision))


def test_bayesian_rejects_bad_input():
    with pytest.raises(ValueError, match="same number of rows"):
        bayesian_linear_fit(np.ones((3, 1)), [1.0, 2.0], 1.0)
    with pytest.raises(ValueError, match="positive"):
        bayesian_linear_fit(np.ones((2, 1)), [1.0, 2.0], 0.0)
