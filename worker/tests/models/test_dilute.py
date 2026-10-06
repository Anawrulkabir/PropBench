import json

import CoolProp.CoolProp as CP  # noqa: N817 - the name CoolProp itself documents
import numpy as np
import pytest

from propbench.models import ChungViscosity, LennardJonesDiluteGas, chapman_enskog_viscosity, omega22_neufeld


def chung_from_coolprop(fluid):
    d = json.loads(CP.get_fluid_param_string(fluid, "JSON"))[0]["TRANSPORT"]["viscosity"]
    assert d["type"] == "Chung"
    return ChungViscosity.create(
        fluid,
        molar_mass=d["molar_mass"],
        t_critical=d["T_critical"],
        rhomolar_critical=d["rhomolar_critical"],
        acentric=d["acentric"],
        dipole_moment=d["dipole_moment_D"],
    )


@pytest.mark.parametrize("fluid", ["Isopentane", "Cyclopentane"])  # CoolProp uses Chung for these (isopentane: polar)
def test_chung_reproduces_coolprop(fluid):
    model = chung_from_coolprop(fluid)
    t = np.array([250.0, 300.0, 400.0, 500.0, 600.0])
    rho = np.array([CP.PropsSI("Dmolar", "T", ti, "P", 5.0e6, fluid) for ti in t])
    expected = np.array([CP.PropsSI("V", "T", ti, "Dmolar", ri, fluid) for ti, ri in zip(t, rho, strict=True)])
    np.testing.assert_allclose(model.predict(t, rho), expected, rtol=1e-12)


def test_chung_dense_formula_reduces_to_its_dilute_gas_limit():
    # README §7: ratio 1.0000
    model = chung_from_coolprop("Isopentane")
    t = np.array([250.0, 400.0, 800.0])
    ratio = model.predict(t, np.array([1e-9, 1e-9, 0.0])) / model.dilute(t)
    np.testing.assert_allclose(ratio, 1.0, rtol=1e-9)
    assert np.round(ratio, 4).tolist() == [1.0, 1.0, 1.0]


def test_neufeld_without_sine_term_matches_coolprop_dilute_gas():
    # CoolProp's kinetic-theory dilute term for R236fa (σ, ε/k from Huber et al. 2003): ρ → 0 viscosity
    sigma, eps = 5.644e-10, 307.24
    m = CP.PropsSI("molar_mass", "R236FA")
    for t in (250.0, 300.0, 400.0):
        assert chapman_enskog_viscosity(t, m, sigma, eps) == pytest.approx(
            CP.PropsSI("V", "T", t, "Dmolar", 1e-9, "R236FA"), rel=1e-10
        )


def test_neufeld_formula_terms():
    t = np.array([0.3, 1.0, 10.0, 100.0])
    base = omega22_neufeld(t)
    full = omega22_neufeld(t, sine_term=True)
    assert np.all(np.abs(full / base - 1) < 2e-3)  # the sine correction is small
    assert np.all(np.diff(base) < 0)  # Ω(2,2)* decreases with T*


def test_lennard_jones_model():
    model = LennardJonesDiluteGas.create("R236FA", CP.PropsSI("molar_mass", "R236FA"), 5.644e-10, 307.24)
    t = np.array([300.0])
    expected = chapman_enskog_viscosity(300.0, model.molar_mass, 5.644e-10, 307.24)
    assert model.predict(t, [0.0])[0] == pytest.approx(expected)
    assert model.with_params({"k": 1.1}).predict(t, [0.0])[0] == pytest.approx(1.1 * model.predict(t, [0.0])[0])
    assert model.validity().rhomolar_max == 0.0
