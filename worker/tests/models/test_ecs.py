"""ECS viscosity (Huber et al. 2003) against CoolProp's independent implementation of the same published models."""

import CoolProp.CoolProp as CP  # noqa: N817 - the name CoolProp itself documents
import numpy as np
import pytest

from propbench.models import ECSViscosity, ModelError, conformal_state, free_bounds, free_names

# Fluids whose CoolProp viscosity is an ECS model with published parameters, covering three reference fluids.
ECS_FLUIDS = ["R236FA", "R236EA", "R116", "R143a", "R218", "Propylene", "R14"]

# (T / K, p / Pa): compressed liquid, saturated-region vapour, low-pressure gas, supercritical
STATES = [(250.0, 5.0e6), (300.0, 1.0e6), (300.0, 1.0e5), (350.0, 2.0e6), (400.0, 1.0e7)]


def coolprop_states(fluid):
    t, rho = [], []
    for ti, pi in STATES:
        try:
            rho.append(CP.PropsSI("Dmolar", "T", ti, "P", pi, fluid))
            t.append(ti)
        except ValueError:
            continue  # outside the EoS range of this fluid
    return np.array(t), np.array(rho)


@pytest.mark.parametrize("fluid", ECS_FLUIDS)
def test_reproduces_coolprop_ecs_viscosity(fluid):
    model = ECSViscosity.from_coolprop(fluid)
    t, rho = coolprop_states(fluid)
    assert len(t) >= 3
    expected = np.array([CP.PropsSI("V", "T", ti, "Dmolar", ri, fluid) for ti, ri in zip(t, rho, strict=True)])
    np.testing.assert_allclose(model.predict(t, rho), expected, rtol=1e-10)


def test_conformal_state_matches_alphar_and_z_to_better_than_1e7():
    # README §7: ECS conformal mapping residual < 1e-7 (the solver converges to 1e-9)
    target = CP.AbstractState("HEOS", "R13I1")  # CF3I
    reference = CP.AbstractState("HEOS", "R134a")
    for t, p in [(300.0, 5.0e6), (356.8, 2.0e5), (400.0, 1.0e7), (250.0, 1.0e5)]:
        target.update(CP.PT_INPUTS, p, t)
        state = conformal_state(target, reference)
        reference.update(CP.DmolarT_INPUTS, state.rhomolar0, state.t0)
        assert abs(reference.alphar() - target.alphar()) < 1e-7
        assert abs(reference.compressibility_factor() - target.compressibility_factor()) < 1e-7
        assert state.residual <= 1e-9
        assert state.iterations < 20


def cf3i_model(**kwargs):
    # Illustrative parameters only (not the fitted CF3I model, which waits for the measurement data)
    return ECSViscosity.create("CF3I", "R134a", sigma=0.47e-9, epsilon_k=300.0, psi=(1.1, -0.05), **kwargs)


def test_dilute_gas_limit_and_k_factor():
    model = cf3i_model()
    t = np.array([300.0, 400.0, 500.0])
    np.testing.assert_array_equal(model.predict(t, 0.0), model.dilute(t))
    doubled = model.with_params({"k": 1.2})
    np.testing.assert_allclose(doubled.dilute(t), 1.2 * model.dilute(t))
    # at low density the density-dependent term vanishes continuously
    low = model.predict(t, 1e-6)
    np.testing.assert_allclose(low, model.dilute(t), rtol=1e-8)


def test_psi_changes_only_the_dense_part():
    model = cf3i_model()
    t, rho = np.array([300.0]), np.array([CP.PropsSI("Dmolar", "T", 300.0, "P", 5e6, "R13I1")])
    stiffer = model.with_params({"psi_0": 1.2})
    assert stiffer.predict(t, rho)[0] > model.predict(t, rho)[0]  # larger ψ → denser reference state → higher η
    assert stiffer.dilute(t)[0] == model.dilute(t)[0]


def test_parameters_are_immutable_and_bounded():
    model = cf3i_model()
    assert free_names(model) == ["psi_0", "psi_1"]
    lower, upper = free_bounds(model)
    assert lower.tolist() == [-10.0, -10.0]
    assert upper.tolist() == [10.0, 10.0]
    changed = model.with_params({"psi_1": 0.1})
    assert model.params()["psi_1"].value == -0.05  # original unchanged
    assert changed.params()["psi_1"].value == 0.1
    assert "k" in free_names(cf3i_model(fit_k=True))
    with pytest.raises(ModelError, match="outside its bounds"):
        model.with_params({"psi_0": 50.0})
    with pytest.raises(ModelError, match="unknown parameters"):
        model.with_params({"beta": 1.0})


def test_model_metadata():
    model = ECSViscosity.from_coolprop("R236FA")
    assert model.reference_fluid == "R134a"
    assert "Huber-IECR-2003" in model.reference()
    validity = model.validity()
    assert validity.t_min < 250.0 < validity.t_max
    with pytest.raises(ModelError, match="not an ECS model"):
        ECSViscosity.from_coolprop("R134a")


def test_invalid_states():
    with pytest.raises(ModelError):
        cf3i_model().predict([-1.0], [1.0])


def test_fluid_without_coolprop_transport_gets_a_generic_ecs_start():
    from propbench.models.spec import default_model

    with pytest.raises(ModelError, match="not an ECS model"):
        ECSViscosity.from_coolprop("R13I1")  # CoolProp has no transport data for CF3I
    model = default_model("ecs_viscosity", "R13I1")
    assert model.reference_fluid == "R134a"
    assert model.params()["psi_0"].value == 1.0
