"""Reference models for comparison (README §2: literature and reference models side by side with fitted ones).

- ``CoolPropTransport``: the transport correlation CoolProp stores for a fluid (for most refrigerants the same NIST
  correlations as REFPROP, cited by CoolProp's BibTeX keys). It has no parameters; it is only compared, never fitted.
- A registry of published models (``reference_models.json`` next to this file): each entry is a model spec with its
  citation and the check values printed in the source, verified by ``tests/models/test_reference.py``. Entries are
  added only from the original publications (CLAUDE.md rule 4); coefficients are never guessed.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from importlib import resources
from typing import Any, Self

import CoolProp.CoolProp as CP  # noqa: N817 - the name CoolProp itself documents
import numpy as np

from propbench.core import Quantity, identify_fluid
from propbench.models.base import CheckValue, Model, ModelError, Parameter, Validity, as_states

_OUTPUT = {Quantity.VISCOSITY: "viscosity", Quantity.THERMAL_CONDUCTIVITY: "conductivity"}
_BIBTEX = {Quantity.VISCOSITY: "BibTeX-VISCOSITY", Quantity.THERMAL_CONDUCTIVITY: "BibTeX-CONDUCTIVITY"}


@dataclass(frozen=True)
class CoolPropTransport:
    """CoolProp's stored transport correlation for ``fluid`` (no parameters)."""

    fluid: str
    quantity: Quantity = Quantity.VISCOSITY
    name: str = "CoolProp reference correlation"

    @classmethod
    def create(cls, fluid: str, quantity: Quantity | str = Quantity.VISCOSITY) -> Self:
        q = Quantity(quantity)
        if q not in _OUTPUT:
            raise ModelError(f"CoolProp transport correlations cover viscosity and thermal conductivity, not {q.value}")
        model = cls(identify_fluid(fluid), q)
        if not model.available():
            raise ModelError(f"CoolProp has no {q.value} correlation for {model.fluid}")
        return model

    def available(self) -> bool:
        state = CP.AbstractState("HEOS", self.fluid)
        try:
            state.update(CP.PT_INPUTS, 1e5, state.T_critical() * 1.2)
            getattr(state, _OUTPUT[self.quantity])()
        except ValueError:
            return False
        return True

    def predict(self, temperature: np.typing.ArrayLike, molar_density: np.typing.ArrayLike) -> np.ndarray:
        t, rho = as_states(temperature, molar_density)
        state = CP.AbstractState("HEOS", self.fluid)
        out = np.empty_like(t)
        method = _OUTPUT[self.quantity]
        for i, (ti, ri) in enumerate(zip(t, rho, strict=True)):
            try:
                state.update(CP.DmolarT_INPUTS, max(ri, 1e-12), ti)
                out[i] = getattr(state, method)()
            except ValueError as exc:
                raise ModelError(f"CoolProp {method} failed at T={ti} K, rho={ri} mol/m3: {exc}") from exc
        return out

    def params(self) -> Mapping[str, Parameter]:
        return {}

    def with_params(self, values: Mapping[str, float]) -> Self:
        if values:
            raise ModelError(f"{self.name} has no parameters")
        return self

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return np.array([]), np.array([])

    def check_values(self) -> Sequence[CheckValue]:
        return ()

    def validity(self) -> Validity:
        return Validity(CP.PropsSI("Ttriple", self.fluid), CP.PropsSI("Tmax", self.fluid), notes="CoolProp EoS range")

    @cached_property
    def _citation(self) -> str:
        try:
            key = CP.get_fluid_param_string(self.fluid, _BIBTEX[self.quantity])
        except ValueError:
            key = ""
        version = CP.get_global_param_string("version")
        return f"CoolProp {version} {self.quantity.value} correlation ({key or 'see CoolProp'})"

    def reference(self) -> str:
        return self._citation


@dataclass(frozen=True)
class ReferenceEntry:
    """A published model with the check values printed in its source."""

    id: str
    label: str
    fluid: str
    quantity: Quantity
    spec: Mapping[str, Any]
    citation: str
    check_values: tuple[CheckValue, ...]

    def model(self) -> Model:
        from propbench.models.spec import model_from_spec

        return model_from_spec(self.spec)


def load_registry(text: str | None = None) -> list[ReferenceEntry]:
    """Entries of the reference-model registry (the bundled file, or ``text`` in the same JSON format)."""
    if text is None:
        text = resources.files("propbench.models").joinpath("reference_models.json").read_text(encoding="utf-8")
    data = json.loads(text)
    if data.get("kind") != "propbench.reference-models" or data.get("version") != 1:
        raise ModelError("not a version-1 PropBench reference-model registry")
    entries = []
    for e in data.get("models", []):
        try:
            checks = tuple(
                CheckValue(
                    float(c["temperature"]),
                    float(c["molar_density"]),
                    float(c["value"]),
                    float(c["rel_tol"]),
                    str(c["source"]),
                )
                for c in e["check_values"]
            )
            if not checks:
                raise ModelError(f"reference model {e['id']} has no check values")
            entries.append(
                ReferenceEntry(
                    str(e["id"]),
                    str(e["label"]),
                    identify_fluid(e["fluid"]),
                    Quantity(e["quantity"]),
                    e["spec"],
                    str(e["citation"]),
                    checks,
                )
            )
        except KeyError as exc:
            raise ModelError(f"reference model entry is missing {exc}") from None
    return entries


def reference_models(fluid: str, quantity: Quantity | str) -> list[tuple[str, Model, str]]:
    """(label, model, citation) of every reference model available for ``fluid`` and ``quantity``."""
    name = identify_fluid(fluid)
    q = Quantity(quantity)
    out: list[tuple[str, Model, str]] = []
    for entry in load_registry():
        if entry.fluid == name and entry.quantity is q:
            out.append((entry.label, entry.model(), entry.citation))
    if q in _OUTPUT:
        try:
            model = CoolPropTransport.create(name, q)
            out.append((f"CoolProp {q.value} correlation", model, model.reference()))
        except ModelError:
            pass
    return out
