"""Reference models: CoolProp's stored correlations, the published-model registry and its check-value harness."""

import json

import CoolProp.CoolProp as CP  # noqa: N817 - the name CoolProp itself documents
import numpy as np
import pytest

from propbench.consist import compare_models
from propbench.core import Dataset, Quantity
from propbench.models import ECSViscosity, ModelError
from propbench.models.reference import CoolPropTransport, load_registry, reference_models
from propbench.models.spec import default_model, model_from_spec, model_to_spec


def check_registry_entry(entry):
    """Every check value printed in the source is reproduced within its stated tolerance."""
    model = entry.model()
    for c in entry.check_values:
        value = float(model.predict([c.temperature], [c.molar_density])[0])
        assert value == pytest.approx(c.expected, rel=c.rel_tol), f"{entry.id}: {c.source}"


def test_bundled_registry_reproduces_all_check_values():
    for entry in load_registry():  # entries are added only with their published check values
        check_registry_entry(entry)


def test_harness_on_a_registry_entry():
    model = ECSViscosity.from_coolprop("R236FA")
    t, rho = 300.0, CP.PropsSI("Dmolar", "T", 300.0, "P", 2e6, "R236FA")
    registry = {
        "kind": "propbench.reference-models",
        "version": 1,
        "models": [
            {
                "id": "r236fa-ecs",
                "label": "R236fa ECS",
                "fluid": "R236fa",
                "quantity": "viscosity",
                "spec": model_to_spec(model),
                "citation": "Huber et al. 2003",
                "check_values": [
                    {
                        "temperature": t,
                        "molar_density": rho,
                        "value": CP.PropsSI("V", "T", t, "Dmolar", rho, "R236FA"),
                        "rel_tol": 1e-8,
                        "source": "CoolProp (independent implementation)",
                    }
                ],
            }
        ],
    }
    [entry] = load_registry(json.dumps(registry))
    assert entry.fluid == "R236FA"
    check_registry_entry(entry)
    bad = json.loads(json.dumps(registry))
    bad["models"][0]["check_values"][0]["value"] *= 1.01
    with pytest.raises(AssertionError):
        check_registry_entry(load_registry(json.dumps(bad))[0])
    empty = json.loads(json.dumps(registry))
    empty["models"][0]["check_values"] = []
    with pytest.raises(ModelError, match="no check values"):
        load_registry(json.dumps(empty))
    with pytest.raises(ModelError, match="registry"):
        load_registry(json.dumps({"kind": "x", "version": 1}))


@pytest.mark.parametrize("fluid", ["R134a", "Nitrogen", "Propane"])
def test_coolprop_transport_equals_coolprop(fluid):
    model = CoolPropTransport.create(fluid)
    t = np.array([300.0, 350.0])
    rho = np.array([CP.PropsSI("Dmolar", "T", x, "P", 1e5, fluid) for x in t])
    expected = [CP.PropsSI("V", "T", a, "Dmolar", b, fluid) for a, b in zip(t, rho, strict=True)]
    np.testing.assert_allclose(model.predict(t, rho), expected, rtol=1e-12)
    assert model.params() == {}
    assert "CoolProp" in model.reference()
    k = CoolPropTransport.create(fluid, "thermal_conductivity")
    assert k.predict([300.0], [rho[0]])[0] == pytest.approx(CP.PropsSI("L", "T", 300.0, "Dmolar", rho[0], fluid))


def test_ecs_conductivity_spec_round_trip_and_parts():
    entry = next(e for e in load_registry() if e.id == "nistir8209-r13i1-conductivity")
    model = entry.model()
    back = model_from_spec(json.loads(json.dumps(model_to_spec(model))))
    assert model_to_spec(back) == model_to_spec(model)
    t, rho = 356.8, 8724.0
    np.testing.assert_array_equal(back.predict([t], [rho]), model.predict([t], [rho]))
    # zero density: only the dilute-gas part (modified Eucken), positive and smaller than the dense value
    assert 0 < model.predict([t], [0.0])[0] < model.predict([t], [rho])[0]
    assert model.predict([t], [0.0])[0] == pytest.approx(model.dilute([t])[0])


def test_critical_enhancement_matches_coolprop():
    """Simplified Olchowy-Sengers term against CoolProp's independent implementation (R134a, Perkins et al.)."""
    from propbench.models.critical import CriticalEnhancement

    ce = CriticalEnhancement(q_d=1892020000.0, xi0=1.94e-10, gamma0=0.0496, r0=1.03)
    state = CP.AbstractState("HEOS", "R134a")
    for t, p in [(380.0, 4.2e6), (376.0, 4.1e6), (400.0, 5e6), (300.0, 1e6)]:
        state.update(CP.PT_INPUTS, p, t)
        expected = state.conductivity_contributions()["critical"]
        assert ce.value(state, state.viscosity()) == pytest.approx(expected, rel=1e-5)


def test_coolprop_transport_absent_or_unsupported():
    with pytest.raises(ModelError, match="no viscosity correlation"):
        CoolPropTransport.create("R13I1")  # CoolProp has no transport model for CF3I
    with pytest.raises(ModelError, match="cover viscosity"):
        CoolPropTransport.create("R134a", Quantity.SPEED_OF_SOUND)


def test_reference_models_listing_and_spec_round_trip():
    refs = reference_models("R134a", "viscosity")
    assert [label for label, _, _ in refs] == ["CoolProp viscosity correlation"]
    cf3i = reference_models("R13I1", "viscosity")  # no CoolProp correlation: the NISTIR 8209 entry only
    assert [label for label, _, _ in cf3i] == ["NISTIR 8209 (REFPROP 10) viscosity"]
    assert "NIST.IR.8209" in cf3i[0][2]
    assert [label for label, _, _ in reference_models("R13I1", "thermal_conductivity")] == [
        "NISTIR 8209 (REFPROP 10) thermal conductivity"
    ]
    model = default_model("coolprop_transport", "R134a")
    back = model_from_spec(json.loads(json.dumps(model_to_spec(model))))
    assert back == model


def test_compare_models_side_by_side():
    truth = CoolPropTransport.create("R236FA")
    states = [(300.0, 2e6), (320.0, 5e6), (340.0, 1e5)]
    t = np.array([s[0] for s in states])
    p = np.array([s[1] for s in states])
    rho = np.array([CP.PropsSI("Dmolar", "T", a, "P", b, "R236FA") for a, b in states])
    eta = truth.predict(t, rho)
    a = Dataset("a", "R236FA", Quantity.VISCOSITY, t, eta, pressure=p)
    b = Dataset("b", "R236FA", Quantity.VISCOSITY, t, eta * 1.02, pressure=p)
    rows = compare_models({"CoolProp": truth, "scaled": truth}, [a, b])
    table = {(r.model, r.dataset): r for r in rows}
    assert set(table) == {(m, d) for m in ("CoolProp", "scaled") for d in ("a", "b", "all")}
    assert table[("CoolProp", "a")].deviations.aard < 1e-10
    assert table[("CoolProp", "b")].deviations.bias == pytest.approx(2.0, rel=1e-9)
    assert table[("CoolProp", "all")].deviations.n == 6
    assert table[("CoolProp", "all")].not_evaluated == 0
