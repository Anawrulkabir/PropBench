"""Validation: splits, cross-validation (serial = parallel), physics checks, selection with a locked rule."""

from dataclasses import dataclass

import CoolProp.CoolProp as CP  # noqa: N817 - the name CoolProp itself documents
import numpy as np
import pytest

from propbench.core import Dataset, Quantity
from propbench.fit import fit, fit_data
from propbench.models import ECSViscosity
from propbench.validate import (
    Candidate,
    SelectionError,
    SelectionRule,
    SplitError,
    bootstrap,
    check_dilute_limit,
    check_extrapolation,
    check_monotonic_density,
    check_monotonic_temperature,
    cross_validate,
    information_criteria,
    kfold,
    loso,
    loto,
    physics_checks,
    select,
    state_grid,
)

SOURCES = [((260.0, 280.0, 300.0), (1e5, 5e6)), ((320.0, 340.0), (2e6, 1e7)), ((300.0, 360.0, 380.0), (1e5, 3e6))]


def make_model(psi):
    return ECSViscosity.create(
        "R236FA", "R134a", sigma=5.644e-10, epsilon_k=307.24, psi=psi, psi_rhomolar_reducing=3626
    )


TRUTH = make_model((1.10195, -0.0294253))


def datasets(noise=0.0, factors=(1.0, 1.0, 1.0)):
    rng = np.random.Generator(np.random.PCG64(1))
    out = []
    for j, (ts, ps) in enumerate(SOURCES):
        states = [(t, p) for t in ts for p in ps]
        t = np.array([s[0] for s in states])
        p = np.array([s[1] for s in states])
        rho = np.array([CP.PropsSI("Dmolar", "T", a, "P", b, "R236FA") for a, b in states])
        y = TRUTH.predict(t, rho) * factors[j] * (1 + noise * rng.standard_normal(len(t)))
        out.append(Dataset(f"src{j}", "R236FA", Quantity.VISCOSITY, t, y, pressure=p, expanded_uncertainty=0.01 * y))
    return out


@pytest.fixture(scope="module")
def data():
    return fit_data(datasets())


@pytest.fixture(scope="module")
def noisy():
    return fit_data(datasets(noise=0.003))


# --- splits ---


def test_loso_holds_out_each_dataset(data):
    folds = loso(data)
    assert [f.name for f in folds] == ["src0", "src1", "src2"]
    for j, f in enumerate(folds):
        assert set(data.dataset_index[f.test]) == {j}
        assert j not in set(data.dataset_index[f.train])
        assert len(f.train) + len(f.test) == len(data)


def test_loso_needs_two_datasets(data):
    with pytest.raises(SplitError, match="two datasets"):
        loso(data.select(data.dataset_index == 0))


def test_loto_groups_isotherms(data):
    folds = loto(data)
    assert len(folds) == len(np.unique(data.temperature))
    for f in folds:
        assert len(np.unique(data.temperature[f.test])) == 1
        assert not np.isin(data.temperature[f.train], data.temperature[f.test]).any()


def test_kfold_partitions_and_is_seeded(data):
    folds = kfold(data, k=4, seed=3)
    tests = np.concatenate([f.test for f in folds])
    assert sorted(tests.tolist()) == list(range(len(data)))
    again = kfold(data, k=4, seed=3)
    assert all(np.array_equal(a.test, b.test) for a, b in zip(folds, again, strict=True))
    other = kfold(data, k=4, seed=4)
    assert not all(np.array_equal(a.test, b.test) for a, b in zip(folds, other, strict=True))
    with pytest.raises(SplitError):
        kfold(data, k=1)


def test_bootstrap_test_set_is_out_of_bag(data):
    for f in bootstrap(data, n=5, seed=2):
        assert len(f.train) == len(data)
        assert not np.isin(f.test, f.train).any()
        assert sorted(set(f.train) | set(f.test)) == list(range(len(data)))


# --- cross-validation ---


def test_loso_of_exact_data_recovers_the_model(data):
    cv = cross_validate(make_model((1.0, 0.0)), data, loso(data), method="loso")
    assert cv.pooled.n == len(data)
    assert cv.pooled.aard < 1e-5
    params = cv.parameters()
    np.testing.assert_allclose(params["psi_0"], 1.10195, rtol=1e-6)
    summary = cv.summary()
    assert summary["method"] == "loso"
    assert len(summary["folds"]) == 3


def test_parallel_cross_validation_equals_serial(noisy):
    folds = kfold(noisy, k=3, seed=0)
    serial = cross_validate(make_model((1.0, 0.0)), noisy, folds, multistart=1, seed=5)
    parallel = cross_validate(make_model((1.0, 0.0)), noisy, folds, multistart=1, seed=5, workers=2)
    for a, b in zip(serial.folds, parallel.folds, strict=True):
        assert a.values == b.values
        np.testing.assert_array_equal(a.test_ard, b.test_ard)


def test_scale_factors_with_held_out_reference():
    data = fit_data(datasets(factors=(1.0, 1.02, 0.97)))
    cv = cross_validate(make_model((1.0, 0.0)), data, loso(data), scale_factors=True)
    # leaving out src0 makes src1 the reference: src2 is fitted relative to it
    without_src0 = cv.folds[0]
    assert without_src0.success
    result = fit(make_model((1.0, 0.0)), data, scale_factors=True)
    assert result.scale_factors["src1"] == pytest.approx(1.02, rel=1e-6)
    assert result.scale_factors["src2"] == pytest.approx(0.97, rel=1e-6)


# --- physics checks ---


@dataclass(frozen=True)
class Toy:
    """A viscosity-like toy model: dilute term a·√T plus b·ρ²/T (b < 0 breaks density monotonicity)."""

    a: float = 5e-7
    b: float = 1e-11
    fluid: str = "R236FA"
    name: str = "toy"
    quantity: Quantity = Quantity.VISCOSITY

    def predict(self, temperature, molar_density):
        t, rho = np.asarray(temperature, float), np.asarray(molar_density, float)
        return self.a * np.sqrt(t) + self.b * rho**2 / t


@pytest.fixture(scope="module")
def grid():
    return state_grid("R236FA", [250.0, 300.0, 350.0, 420.0], [1e5, 1e6, 5e6, 2e7])


def test_state_grid_is_single_phase(grid):
    assert len(grid.temperature) == 16
    assert grid.t_critical == pytest.approx(CP.PropsSI("Tcrit", "R236FA"))
    assert np.all(grid.molar_density > 0)


def test_physics_checks_pass_for_a_good_model(grid):
    model = Toy()
    assert check_monotonic_density(model, grid).passed
    assert check_monotonic_temperature(model, grid).passed
    assert check_extrapolation(model, grid).passed
    assert check_dilute_limit(model, [250.0, 300.0]).passed


def test_physics_checks_catch_violations(grid):
    bad = Toy(b=-1e-13)
    density = check_monotonic_density(bad, grid)
    assert not density.passed
    assert density.violations
    negative = Toy(a=-1e-6, b=0.0)
    assert not check_extrapolation(negative, grid).passed
    assert not check_dilute_limit(negative, [300.0]).passed


def test_physics_checks_of_fitted_ecs(noisy):
    result = fit(make_model((1.0, 0.0)), noisy)
    checks = physics_checks(result.model, noisy.temperature)
    assert checks[0].name == "dilute-gas limit"
    assert all(c.passed for c in checks), [c.as_dict() for c in checks if not c.passed]


# --- selection ---


def test_rule_hash_is_stable_and_detects_changes():
    rule = SelectionRule(metric="cv_aard", validation="loso", tie_tolerance=0.05)
    assert rule.sha256() == SelectionRule.from_dict(dict(rule.__dict__)).sha256()
    assert rule.sha256() != SelectionRule(metric="bic").sha256()
    candidates = [Candidate("a", 2, {"cv_aard": 1.0})]
    with pytest.raises(SelectionError, match="differs"):
        select(SelectionRule(metric="fit_aard"), rule.sha256(), candidates)


def test_selection_prefers_fewer_parameters_within_tolerance():
    rule = SelectionRule(tie_tolerance=0.05)
    candidates = [
        Candidate("big", 5, {"cv_aard": 1.00}),
        Candidate("small", 2, {"cv_aard": 1.04}),
        Candidate("worse", 1, {"cv_aard": 2.0}),
        Candidate("unphysical", 1, {"cv_aard": 0.5}, physics_passed=False),
    ]
    chosen = select(rule, rule.sha256(), candidates)
    assert chosen.chosen == "small"
    assert chosen.excluded == ("unphysical",)
    assert chosen.ranking == ("big", "small", "worse")
    strict = SelectionRule(tie_tolerance=0.0)
    assert select(strict, strict.sha256(), candidates).chosen == "big"


def test_selection_rejects_unknown_metric_and_empty_field():
    with pytest.raises(SelectionError, match="unknown metric"):
        SelectionRule(metric="r2")
    rule = SelectionRule()
    with pytest.raises(SelectionError, match="no candidate"):
        select(rule, rule.sha256(), [Candidate("x", 1, {"bic": 1.0})])


def test_information_criteria():
    ic = information_criteria(10, 2, 5.0)
    assert ic["aic"] == pytest.approx(10 * np.log(0.5) + 4)
    assert ic["bic"] == pytest.approx(10 * np.log(0.5) + 2 * np.log(10))


def test_dilute_limit_reports_unevaluable_states_without_failing():
    class Partial(Toy):
        def predict(self, temperature, molar_density):
            rho = np.asarray(molar_density, float)
            if np.any((rho > 0) & (np.asarray(temperature, float) < 250)):
                from propbench.models import ModelError

                raise ModelError("no conformal state")
            return super().predict(temperature, molar_density)

    check = check_dilute_limit(Partial(), [200.0, 300.0])
    assert check.passed
    assert check.not_evaluated == 1
    assert "not evaluated" in check.message


def test_cross_validation_of_a_model_without_free_parameters(data):
    frozen = TRUTH.with_params({})
    from dataclasses import replace

    frozen = replace(frozen, parameters={k: replace(v, fixed=True) for k, v in frozen.parameters.items()})
    cv = cross_validate(frozen, data, loso(data))
    assert all(f.success for f in cv.folds)
    assert cv.pooled.aard < 1e-10
