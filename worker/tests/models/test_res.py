"""Residual entropy scaling (M1.4b): FeOs's published check value, an independent Chapman-Enskog cross-check, the
PC-SAFT fit to the reference EoS, spec round-trip and recovery of known coefficients."""

import os

import CoolProp.CoolProp as CP  # noqa: N817
import numpy as np
import pytest

from propbench.backends import PCSAFT_PARAMETERS, PcSaftParameters
from propbench.fit import fit
from propbench.fit.data import FitData
from propbench.models import ResidualEntropyViscosity, chapman_enskog_viscosity, fit_pcsaft_to_eos
from propbench.models.base import CheckValue
from propbench.models.res import R, pcsaft_density
from propbench.models.spec import default_model, model_from_spec, model_to_spec

if os.environ.get("PB_REQUIRE_FEOS"):
    import feos  # noqa: F401  # CI installs the component: a missing FeOs must fail, not skip
else:
    pytest.importorskip("feos", reason="FeOs component not installed (uv sync --group feos)")

pytestmark = pytest.mark.feos

# Propane: PC-SAFT (Gross & Sadowski 2001) and viscosity coefficients (Lötgering-Lin & Gross 2015) as used in FeOs's
# own test `pcsaft::eos::tests::viscosity` (feos v0.10.1), whose check value is η = 0.00797 mPa·s at 300 K, 1 bar.
PROPANE = PcSaftParameters(2.001829, 3.618353, 208.1101, 44.0962, "Gross & Sadowski 2001 (FeOs test set)")
PROPANE_VISCOSITY = (-0.8013, -1.9972, -0.2907, -0.0467)


def propane_model() -> ResidualEntropyViscosity:
    rho = pcsaft_density(PROPANE, 300.0, 1e5)
    check = CheckValue(300.0, rho, 0.00797e-3, 1e-3, "FeOs v0.10.1 test viscosity (0.00797 mPa·s, 3 digits)")
    return ResidualEntropyViscosity.create("n-Propane", PROPANE, PROPANE_VISCOSITY, checks=[check])


def test_reproduces_feos_published_check_value():
    model = propane_model()
    (check,) = model.check_values()
    value = model.predict(check.temperature, check.molar_density)[0]
    assert value == pytest.approx(check.expected, rel=check.rel_tol)


def test_reference_viscosity_matches_independent_chapman_enskog():
    """η_CE from FeOs equals PropBench's own Chapman-Enskog/Neufeld implementation for the PC-SAFT segment."""
    model = propane_model().with_params(dict.fromkeys("ABCD", 0.0))
    t = np.array([250.0, 300.0, 400.0])
    rho = np.array([1.0, 1.0, 1.0])  # near the dilute limit s_res → 0, so η = η_CE · e^0
    eta_ce = chapman_enskog_viscosity(t, PROPANE.molar_mass / 1000.0, PROPANE.sigma * 1e-10, PROPANE.epsilon_k)
    np.testing.assert_allclose(model.predict(t, rho), eta_ce, rtol=2e-3)


def test_pcsaft_fit_to_eos_recovers_published_parameters():
    fitted = fit_pcsaft_to_eos("n-Propane")
    published = PCSAFT_PARAMETERS["n-Propane"]
    assert fitted.m == pytest.approx(published.m, rel=0.01)
    assert fitted.sigma == pytest.approx(published.sigma, rel=0.005)
    assert fitted.epsilon_k == pytest.approx(published.epsilon_k, rel=0.005)


def test_new_fluid_gets_fitted_pcsaft_and_round_trips():
    model = default_model("res_viscosity", "R13I1")
    assert isinstance(model, ResidualEntropyViscosity)
    assert "fitted to the R13I1 reference EoS" in model.reference()
    again = model_from_spec(model_to_spec(model))
    t, rho = np.array([300.0]), np.array([CP.PropsSI("Dmolar", "T", 300.0, "Q", 0, "R13I1")])
    np.testing.assert_array_equal(again.predict(t, rho), model.predict(t, rho))


def test_fit_recovers_known_coefficients():
    truth = ResidualEntropyViscosity.create("n-Propane", PROPANE, PROPANE_VISCOSITY)
    temps = np.repeat([200.0, 240.0, 280.0, 320.0], 3)
    pressures = np.tile([1e6, 5e6, 2e7], 4)
    rho = np.array([CP.PropsSI("Dmolar", "T", t, "P", p, "n-Propane") for t, p in zip(temps, pressures, strict=True)])
    values = truth.predict(temps, rho)
    data = FitData(
        temps, rho, values, None, np.zeros(len(temps), int), np.arange(len(temps)), ("synthetic",), "n-Propane"
    )
    start = truth.with_params({"A": -0.5, "B": -1.0, "C": 0.0, "D": 0.0})
    result = fit(start, data, weighted=False)
    for name, expected in zip("ABCD", PROPANE_VISCOSITY, strict=True):
        assert result.values[name] == pytest.approx(expected, abs=1e-6)


def test_reduced_entropy_is_residual_entropy_per_segment():
    model = propane_model()
    (check,) = model.check_values()
    eta_ce, s = model._scaling(np.array([check.temperature]), np.array([check.molar_density]))
    # FeOs's own reduced viscosity at this state is ln(η/η_CE) = A + B s + C s² + D s³
    a, b, c, d = PROPANE_VISCOSITY
    assert np.log(model.predict(check.temperature, check.molar_density)[0] / eta_ce[0]) == pytest.approx(
        a + b * s[0] + c * s[0] ** 2 + d * s[0] ** 3
    )
    assert s[0] < 0  # a dilute vapour has a small negative residual entropy
    assert abs(s[0] * R * PROPANE.m) < 1.0
