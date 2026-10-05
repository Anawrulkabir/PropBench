import numpy as np
import pytest

from propbench.core import Quantity, UnitError, difference_to_si, from_si, normalize_unit, to_si


@pytest.mark.parametrize(
    ("value", "unit", "quantity", "expected"),
    [
        (1.0, "MPa", Quantity.PRESSURE, 1.0e6),
        (101.325, "kPa", Quantity.PRESSURE, 101325.0),
        (1.0, "bar", Quantity.PRESSURE, 1.0e5),
        (25.0, "°C", Quantity.TEMPERATURE, 298.15),
        (25.0, "degC", Quantity.TEMPERATURE, 298.15),
        (300.0, "K", Quantity.TEMPERATURE, 300.0),
        (168.5169, "μPa·s", Quantity.VISCOSITY, 168.5169e-6),  # Greek mu
        (168.5169, "µPa·s", Quantity.VISCOSITY, 168.5169e-6),  # micro sign
        (168.5169, "uPa*s", Quantity.VISCOSITY, 168.5169e-6),
        (1.0, "mPa s", Quantity.VISCOSITY, 1.0e-3),
        (1.0, "cP", Quantity.VISCOSITY, 1.0e-3),
        (8.724, "mol/L", Quantity.MOLAR_DENSITY, 8724.0),
        (8.724, "mol/dm³", Quantity.MOLAR_DENSITY, 8724.0),
        (1.2, "g/cm^3", Quantity.MASS_DENSITY, 1200.0),
        (1201.53, "kg/m³", Quantity.MASS_DENSITY, 1201.53),
        (80.0, "mW/(m·K)", Quantity.THERMAL_CONDUCTIVITY, 0.080),
    ],
)
def test_to_si(value, unit, quantity, expected):
    assert to_si(value, unit, quantity) == pytest.approx(expected, rel=1e-12)


def test_arrays_are_converted_elementwise():
    np.testing.assert_allclose(to_si([0.1, 1.0, 10.0], "MPa", Quantity.PRESSURE), [1e5, 1e6, 1e7])


def test_offset_units_are_absolute_for_values_but_not_for_differences():
    assert to_si(0.0, "°C", Quantity.TEMPERATURE) == pytest.approx(273.15)
    assert difference_to_si(0.5, "°C", Quantity.TEMPERATURE) == pytest.approx(0.5)
    assert difference_to_si(0.5, "MPa", Quantity.PRESSURE) == pytest.approx(5e5)


def test_round_trip_for_display():
    si = to_si([150.0, 200.0], "μPa·s", Quantity.VISCOSITY)
    np.testing.assert_allclose(from_si(si, "μPa·s", Quantity.VISCOSITY), [150.0, 200.0])


@pytest.mark.parametrize(("unit", "quantity"), [("MPa", Quantity.VISCOSITY), ("K", Quantity.PRESSURE)])
def test_wrong_dimension_is_rejected(unit, quantity):
    with pytest.raises(UnitError, match="is not a unit of"):
        to_si(1.0, unit, quantity)


@pytest.mark.parametrize("unit", ["furlongs", "", "kg/"])
def test_unknown_unit_is_rejected(unit):
    with pytest.raises(UnitError):
        to_si(1.0, unit, Quantity.MASS_DENSITY)


def test_normalize_unit():
    assert normalize_unit("μPa·s") == "μPa*s"
    assert normalize_unit("mol/dm³") == "mol/dm^3"
    assert normalize_unit(" mPa s ") == "mPa*s"
    assert normalize_unit("°C") == "degC"


def test_every_quantity_has_a_valid_si_unit():
    for quantity in Quantity:
        assert to_si(1.0, quantity.si_unit, quantity) == pytest.approx(1.0)
        assert quantity.symbol
