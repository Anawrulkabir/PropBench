"""Units at the public boundary (CLAUDE.md conventions: SI internally, convert only at import and display).

Everything inside PropBench is SI (K, Pa, Pa·s, kg/m³, mol/m³, W/(m·K), ...). Values arriving with other units are
converted here, with pint, exactly once.
"""

from __future__ import annotations

import re
from enum import StrEnum
from functools import cache

import numpy as np
import pint


class UnitError(ValueError):
    """A unit string could not be parsed or does not fit the quantity."""


class Quantity(StrEnum):
    """Physical quantities that datasets and models deal with, each with its internal SI unit."""

    TEMPERATURE = "temperature"
    PRESSURE = "pressure"
    MASS_DENSITY = "mass_density"
    MOLAR_DENSITY = "molar_density"
    VISCOSITY = "viscosity"
    THERMAL_CONDUCTIVITY = "thermal_conductivity"
    SPEED_OF_SOUND = "speed_of_sound"
    SURFACE_TENSION = "surface_tension"
    VAPOR_PRESSURE = "vapor_pressure"

    @property
    def si_unit(self) -> str:
        return _SI_UNITS[self]

    @property
    def symbol(self) -> str:
        return _SYMBOLS[self]


_SI_UNITS: dict[Quantity, str] = {
    Quantity.TEMPERATURE: "K",
    Quantity.PRESSURE: "Pa",
    Quantity.MASS_DENSITY: "kg/m^3",
    Quantity.MOLAR_DENSITY: "mol/m^3",
    Quantity.VISCOSITY: "Pa*s",
    Quantity.THERMAL_CONDUCTIVITY: "W/(m*K)",
    Quantity.SPEED_OF_SOUND: "m/s",
    Quantity.SURFACE_TENSION: "N/m",
    Quantity.VAPOR_PRESSURE: "Pa",
}

_SYMBOLS: dict[Quantity, str] = {
    Quantity.TEMPERATURE: "T",
    Quantity.PRESSURE: "p",
    Quantity.MASS_DENSITY: "ρ",
    Quantity.MOLAR_DENSITY: "ρn",
    Quantity.VISCOSITY: "η",
    Quantity.THERMAL_CONDUCTIVITY: "λ",
    Quantity.SPEED_OF_SOUND: "w",
    Quantity.SURFACE_TENSION: "σ",
    Quantity.VAPOR_PRESSURE: "psat",
}


@cache
def _registry() -> pint.UnitRegistry:
    # No on-disk cache: the worker writes nothing outside the app and project folders (CLAUDE.md, isolation).
    return pint.UnitRegistry(cache_folder=None)


_SUPERSCRIPTS = str.maketrans({"²": "^2", "³": "^3", "⁻": "^-", "¹": "1"})


def normalize_unit(unit: str) -> str:
    """Rewrite lab notations pint does not parse: ``μPa·s`` → ``μPa*s``, ``°C`` → ``degC``, ``m³`` → ``m^3``."""
    text = unit.strip().translate(_SUPERSCRIPTS)
    text = text.replace("·", "*").replace("⋅", "*").replace("°C", "degC").replace("°F", "degF").replace("°K", "K")
    text = re.sub(r"\s*\*\s*", "*", text)
    text = re.sub(r"(?<=[A-Za-z])\s+(?=[A-Za-z])", "*", text)  # "mPa s" → "mPa*s"
    return text


def parse_unit(unit: str, quantity: Quantity) -> pint.Unit:
    """Parse ``unit`` and check that it has the dimensions of ``quantity``."""
    registry = _registry()
    try:
        parsed = registry.Unit(normalize_unit(unit))
    except (pint.errors.UndefinedUnitError, pint.errors.DefinitionSyntaxError, AttributeError, ValueError) as exc:
        raise UnitError(f"unknown unit '{unit}'") from exc
    target = registry.Unit(quantity.si_unit)
    if parsed.dimensionality != target.dimensionality:
        raise UnitError(f"unit '{unit}' is not a unit of {quantity.value.replace('_', ' ')} (SI: {quantity.si_unit})")
    return parsed


def to_si(values: np.typing.ArrayLike, unit: str, quantity: Quantity) -> np.ndarray:
    """Convert ``values`` given in ``unit`` to the SI unit of ``quantity`` (absolute values, e.g. °C → K)."""
    parsed = parse_unit(unit, quantity)
    array = np.asarray(values, dtype=float)
    return np.asarray(_registry().Quantity(array, parsed).to(quantity.si_unit).magnitude, dtype=float)


def difference_to_si(values: np.typing.ArrayLike, unit: str, quantity: Quantity) -> np.ndarray:
    """Convert differences (e.g. absolute uncertainties) to SI: a difference of 1 °C is 1 K, not 274.15 K."""
    parsed = parse_unit(unit, quantity)
    registry = _registry()
    array = np.asarray(values, dtype=float)
    delta = registry.Quantity(array, parsed)
    if registry.Quantity(0.0, parsed).to(quantity.si_unit).magnitude != 0:
        # offset unit (degC, degF): a difference uses the matching delta unit
        delta = registry.Quantity(array, f"delta_{parsed}")
    return np.asarray(delta.to(quantity.si_unit).magnitude, dtype=float)


def from_si(values: np.typing.ArrayLike, unit: str, quantity: Quantity) -> np.ndarray:
    """Convert SI values of ``quantity`` to ``unit`` for display."""
    parsed = parse_unit(unit, quantity)
    array = np.asarray(values, dtype=float)
    return np.asarray(_registry().Quantity(array, quantity.si_unit).to(parsed).magnitude, dtype=float)
