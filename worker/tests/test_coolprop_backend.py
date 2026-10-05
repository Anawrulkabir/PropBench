import math

import pytest

import propbench
from propbench.backends import BackendError
from propbench.backends.coolprop import CoolPropBackend

# M0 acceptance value: R134a at 300 K and 1 MPa, CoolProp HEOS (reference EoS of Tillner-Roth and Baehr,
# J. Phys. Chem. Ref. Data 23 (1994) 657). Given to 2 decimals, so the tolerance is half a unit in the last place.
R134A_DENSITY_300K_1MPA = 1201.53
TOLERANCE = 0.005


def test_acceptance_r134a_density():
    result = CoolPropBackend().property("R134a", "PT_INPUTS", (1.0e6, 300.0), "Dmass")
    assert abs(result.value - R134A_DENSITY_300K_1MPA) < TOLERANCE
    assert result.output == "Dmass"
    assert result.backend == "CoolProp::HEOS"


def test_package_level_property_uses_coolprop_heos():
    result = propbench.property("R134a", "PT_INPUTS", (1.0e6, 300.0), "Dmass")
    assert abs(result.value - R134A_DENSITY_300K_1MPA) < TOLERANCE


def test_input_pair_order_matters():
    # DmassT_INPUTS takes density first, then temperature: the inverse of the acceptance state.
    result = CoolPropBackend().property("R134a", "DmassT_INPUTS", (1201.5290150541637, 300.0), "P")
    assert math.isclose(result.value, 1.0e6, rel_tol=1e-8)


def test_unknown_fluid():
    with pytest.raises(BackendError, match="unknown fluid"):
        CoolPropBackend().property("NotAFluid", "PT_INPUTS", (1.0e6, 300.0), "Dmass")


@pytest.mark.parametrize("pair", ["PT", "PT_INPUT", "FOO_INPUTS", "INPUT_PAIR_INVALID", "__version__"])
def test_unknown_input_pair(pair):
    with pytest.raises(BackendError, match="unknown input pair"):
        CoolPropBackend().property("R134a", pair, (1.0e6, 300.0), "Dmass")


def test_unknown_output():
    with pytest.raises(BackendError, match="unknown output"):
        CoolPropBackend().property("R134a", "PT_INPUTS", (1.0e6, 300.0), "NotAProperty")


@pytest.mark.parametrize("values", [(math.nan, 300.0), (1.0e6, math.inf)])
def test_non_finite_inputs(values):
    with pytest.raises(BackendError, match="finite"):
        CoolPropBackend().property("R134a", "PT_INPUTS", values, "Dmass")


def test_wrong_number_of_values():
    with pytest.raises(BackendError, match="two values"):
        CoolPropBackend().property("R134a", "PT_INPUTS", (1.0e6,), "Dmass")  # type: ignore[arg-type]


def test_invalid_state_is_a_backend_error():
    with pytest.raises(BackendError):
        CoolPropBackend().property("R134a", "PT_INPUTS", (-1.0, 300.0), "Dmass")
