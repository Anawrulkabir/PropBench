import numpy as np
import pytest

from propbench.backends import BackendError, CoolPropBackend, assign_phases, get_backend
from propbench.core import Dataset, Phase, Quantity


@pytest.fixture(scope="module")
def heos():
    return CoolPropBackend("HEOS")


def test_batch_matches_single_calls_and_contains_the_acceptance_value(heos):
    p = [1.0e6, 2.0e6, 0.5e6]
    t = [300.0, 280.0, 350.0]
    batch = heos.properties("R134a", "PT_INPUTS", p, t, ["Dmass", "Smolar_residual"])
    assert batch.backend == "CoolProp::HEOS"
    assert not batch.failed.any()
    for i in range(3):
        single = heos.property("R134a", "PT_INPUTS", (p[i], t[i]), "Dmass").value
        assert batch["Dmass"][i] == single  # identical code path, bit-identical result
    assert abs(batch["Dmass"][0] - 1201.53) < 0.005


def test_failed_states_are_nan_with_a_reason_and_do_not_stop_the_batch(heos):
    batch = heos.properties("R134a", "PT_INPUTS", [1.0e6, -5.0, float("nan")], [300.0, 300.0, 300.0], ["Dmass"])
    np.testing.assert_array_equal(batch.failed, [False, True, True])
    assert np.isnan(batch["Dmass"][1:]).all()
    assert set(batch.errors) == {1, 2}
    assert not batch["Dmass"].flags.writeable


def test_scalars_broadcast(heos):
    batch = heos.properties("R134a", "PT_INPUTS", 1.0e6, [290.0, 300.0], ["Dmass"])
    assert batch["Dmass"].shape == (2,)


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("R134a", "XY_INPUTS", [1e6], [300.0], ["Dmass"]), "unknown input pair"),
        (("R134a", "PT_INPUTS", [1e6], [300.0], ["Nonsense"]), "unknown output"),
        (("NotAFluid", "PT_INPUTS", [1e6], [300.0], ["Dmass"]), "unknown fluid"),
        (("R134a", "PT_INPUTS", [1e6], [300.0], []), "at least one output"),
        (("R134a", "PT_INPUTS", [1e6, 2e6], [300.0, 310.0, 320.0], ["Dmass"]), "broadcast"),
    ],
)
def test_bad_requests_raise(heos, args, message):
    with pytest.raises((BackendError, ValueError), match=message):
        heos.properties(*args)


def test_phases_from_the_equation_of_state(heos):
    # R134a: Tc = 374.21 K, pc = 4.059 MPa, psat(300 K) = 0.702 MPa. CoolProp's naming: supercritical gas is
    # T > Tc, p < pc; supercritical liquid is p > pc, T < Tc; supercritical is both above.
    result = heos.phases("R134a", [300.0, 300.0, 400.0, 400.0, 300.0], [1.0e6, 0.5e6, 1.0e6, 10.0e6, 10.0e6])
    assert result.phases == (
        Phase.LIQUID,
        Phase.VAPOR,
        Phase.SUPERCRITICAL_GAS,
        Phase.SUPERCRITICAL,
        Phase.SUPERCRITICAL_LIQUID,
    )


def test_pcsaft_library_names_are_resolved():
    # CoolProp's PC-SAFT library calls n-propane "PROPANE"; the adapter falls back to CAS and aliases
    batch = CoolPropBackend("PCSAFT").properties("n-Propane", "PT_INPUTS", [5.0e6], [300.0], ["Dmolar"])
    assert batch["Dmolar"][0] == pytest.approx(11379.1028, rel=1e-8)


def test_registry():
    assert get_backend().name == "CoolProp::HEOS"
    assert get_backend("CoolProp::PR").name == "CoolProp::PR"
    with pytest.raises(BackendError, match="unknown backend"):
        get_backend("REFPROP")


def dataset(stated):
    return Dataset(
        name="phases",
        fluid="R134a",
        quantity=Quantity.VISCOSITY,
        temperature=[300.0, 300.0, 400.0],
        pressure=[1.0e6, 0.5e6, 10.0e6],
        values=[1.9e-4, 1.2e-5, 1.0e-4],
        phase=stated,
        point_ids=[7, 8, 9],
    )


def test_assign_phases_flags_contradictions_by_point_id(heos):
    check = assign_phases(dataset([Phase.LIQUID, Phase.LIQUID, Phase.LIQUID]), heos)
    assert check.dataset.phase == (Phase.LIQUID, Phase.VAPOR, Phase.SUPERCRITICAL)
    assert check.stated == (Phase.LIQUID, Phase.LIQUID, Phase.LIQUID)
    assert check.mismatches == (8,)  # 0.5 MPa at 300 K is vapour; dense supercritical "liquid" is compatible


def test_assign_phases_without_stated_phases(heos):
    check = assign_phases(dataset(None), heos)
    assert check.mismatches == ()
    assert check.dataset.phase[1] is Phase.VAPOR
