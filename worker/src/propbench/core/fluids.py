"""Fluid identification: map a name, alias or CAS number to CoolProp's canonical fluid name."""

from __future__ import annotations

import re
from functools import cache

import CoolProp.CoolProp as CP  # noqa: N817 - the name CoolProp itself documents


class UnknownFluidError(ValueError):
    """No fluid in the library matches the given name or CAS number."""


_CAS = re.compile(r"^\d{2,7}-\d{2}-\d$")


@cache
def _cas_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for name in CP.get_global_param_string("FluidsList").split(","):
        index[CP.get_fluid_param_string(name, "CAS").strip()] = name
    return index


def identify_fluid(identifier: str) -> str:
    """Return the canonical fluid name for a name, alias (e.g. ``CF3I``, ``R13I1``) or CAS number (``2314-97-8``)."""
    text = identifier.strip()
    if not text:
        raise UnknownFluidError("empty fluid identifier")
    if _CAS.match(text):
        try:
            return _cas_index()[text]
        except KeyError:
            raise UnknownFluidError(f"no fluid with CAS number {text}") from None
    try:
        return CP.get_fluid_param_string(text, "name")
    except ValueError:
        pass
    try:
        return _alias_index()[text.casefold()]
    except KeyError:
        raise UnknownFluidError(f"unknown fluid '{text}'") from None


@cache
def _alias_index() -> dict[str, str]:
    """Case-insensitive index of names and aliases (CoolProp's own lookup is case-sensitive for some names)."""
    index: dict[str, str] = {}
    for name in CP.get_global_param_string("FluidsList").split(","):
        aliases = CP.get_fluid_param_string(name, "aliases").split(",")
        for alias in [name, *aliases]:
            if alias.strip():
                index.setdefault(alias.strip().casefold(), name)
    return index
