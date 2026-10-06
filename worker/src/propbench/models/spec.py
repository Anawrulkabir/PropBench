"""Models as JSON-compatible specs (``kind`` + constructor fields + parameters), for the RPC and for project files.

The spec stores every parameter with its value, bounds and fixed flag, so a fitted model round-trips exactly.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, replace
from typing import Any

import CoolProp.CoolProp as CP  # noqa: N817 - the name CoolProp itself documents

from propbench.backends.feos import PcSaftParameters
from propbench.core import Quantity, identify_fluid
from propbench.models.base import Model, ModelError, Parameter
from propbench.models.critical import CriticalEnhancement
from propbench.models.dilute import ChungViscosity, LennardJonesDiluteGas
from propbench.models.ecs import ECSViscosity
from propbench.models.ecs_conductivity import ECSConductivity
from propbench.models.reference import CoolPropTransport
from propbench.models.res import ResidualEntropyViscosity, pcsaft_parameters

KINDS: dict[str, dict[str, str]] = {
    "ecs_viscosity": {
        "label": "Extended corresponding states (viscosity)",
        "reference": "Huber, Laesecke, Perkins, Ind. Eng. Chem. Res. 42 (2003) 3163",
    },
    "chung_viscosity": {
        "label": "Chung et al. (viscosity)",
        "reference": "Chung, Ajlan, Lee, Starling, Ind. Eng. Chem. Res. 27 (1988) 671",
    },
    "lj_dilute_viscosity": {
        "label": "Chapman-Enskog dilute gas (viscosity)",
        "reference": "Neufeld, Janzen, Aziz, J. Chem. Phys. 57 (1972) 1100",
    },
    "ecs_conductivity": {
        "label": "Extended corresponding states (thermal conductivity)",
        "reference": "McLinden, Klein, Perkins, Int. J. Refrig. 23 (2000) 43",
    },
    "res_viscosity": {
        "label": "Residual entropy scaling with PC-SAFT (viscosity)",
        "reference": "Lötgering-Lin & Gross, Ind. Eng. Chem. Res. 54 (2015) 7942 (via FeOs)",
    },
    "coolprop_transport": {
        "label": "CoolProp reference correlation (comparison only)",
        "reference": "the transport correlation stored in CoolProp for the fluid",
    },
}

_CLASSES: dict[type, str] = {ECSViscosity: "ecs_viscosity", ChungViscosity: "chung_viscosity"}
_CLASSES[LennardJonesDiluteGas] = "lj_dilute_viscosity"
_CLASSES[CoolPropTransport] = "coolprop_transport"
_CLASSES[ECSConductivity] = "ecs_conductivity"
_CLASSES[ResidualEntropyViscosity] = "res_viscosity"


def _number(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _parameter_to_dict(p: Parameter) -> dict[str, Any]:
    return {
        "value": p.value,
        "lower": _number(p.lower),
        "upper": _number(p.upper),
        "fixed": p.fixed,
        "unit": p.unit,
        "description": p.description,
    }


def _parameters_from_dict(data: Mapping[str, Any]) -> dict[str, Parameter]:
    out = {}
    for name, d in data.items():
        lower = -math.inf if d.get("lower") is None else float(d["lower"])
        upper = math.inf if d.get("upper") is None else float(d["upper"])
        out[name] = Parameter(
            name,
            float(d["value"]),
            lower,
            upper,
            bool(d.get("fixed", False)),
            d.get("unit", "1"),
            d.get("description", ""),
        )
    return out


def model_to_spec(model: Model) -> dict[str, Any]:
    kind = _CLASSES.get(type(model))
    if kind is None:
        raise ModelError(f"no spec for model type {type(model).__name__}")
    spec: dict[str, Any] = {
        "kind": kind,
        "name": model.name,
        "fluid": model.fluid,
        "quantity": model.quantity.value,
        "reference": model.reference(),
        "parameters": {n: _parameter_to_dict(p) for n, p in model.params().items()},
    }
    if isinstance(model, CoolPropTransport):
        pass
    elif isinstance(model, ResidualEntropyViscosity):
        spec["pcsaft"] = asdict(model.pcsaft)
    elif isinstance(model, ECSConductivity):
        spec["viscosity"] = model_to_spec(model.viscosity)
        spec["chi_exponents"] = list(model.chi_exponents)
        spec["chi_rhomolar_reducing"] = model.chi_rhomolar_reducing
        spec["critical"] = None if model.critical is None else asdict(model.critical)
    elif isinstance(model, ECSViscosity):
        spec["reference_fluid"] = model.reference_fluid
        spec["psi_exponents"] = list(model.psi_exponents)
        spec["psi_rhomolar_reducing"] = model.psi_rhomolar_reducing
    else:
        spec["molar_mass"] = model.molar_mass  # type: ignore[attr-defined]
    return spec


def model_from_spec(spec: Mapping[str, Any]) -> Model:
    kind = spec.get("kind")
    try:
        params = _parameters_from_dict(spec["parameters"])
        fluid = identify_fluid(spec["fluid"])
        if kind == "ecs_viscosity":
            model: Model = ECSViscosity(
                fluid,
                identify_fluid(spec["reference_fluid"]),
                tuple(float(e) for e in spec["psi_exponents"]),
                float(spec["psi_rhomolar_reducing"]),
                params,
            )
            if spec.get("reference"):
                model = replace(model, source=str(spec["reference"]))  # type: ignore[type-var]
        elif kind == "chung_viscosity":
            model = ChungViscosity(fluid, float(spec["molar_mass"]), params)
        elif kind == "lj_dilute_viscosity":
            model = LennardJonesDiluteGas(fluid, float(spec["molar_mass"]), params)
        elif kind == "ecs_conductivity":
            viscosity = model_from_spec(spec["viscosity"])
            if not isinstance(viscosity, ECSViscosity):
                raise ModelError("an ECS conductivity model needs an ECS viscosity model")
            critical = spec.get("critical")
            model = ECSConductivity(
                viscosity,
                tuple(float(e) for e in spec["chi_exponents"]),
                float(spec["chi_rhomolar_reducing"]),
                None if critical is None else CriticalEnhancement(**{k: float(v) for k, v in critical.items()}),
                params,
            )
            if spec.get("reference"):
                model = replace(model, source=str(spec["reference"]))  # type: ignore[type-var]
        elif kind == "res_viscosity":
            p = spec.get("pcsaft")
            pcsaft = (
                None
                if p is None
                else PcSaftParameters(
                    float(p["m"]), float(p["sigma"]), float(p["epsilon_k"]), float(p["molar_mass"]), str(p["reference"])
                )
            )
            model = ResidualEntropyViscosity(fluid, pcsaft or pcsaft_parameters(fluid), params)
        elif kind == "coolprop_transport":
            model = CoolPropTransport.create(fluid, spec.get("quantity", "viscosity"))
        else:
            raise ModelError(f"unknown model kind {kind!r} (known: {', '.join(KINDS)})")
    except KeyError as exc:
        raise ModelError(f"model spec is missing {exc}") from None
    return model


def default_model(kind: str, fluid: str, reference_fluid: str | None = None) -> Model:
    """A starting model for ``fluid``: CoolProp's published ECS parameters when it has them, otherwise generic starts
    (Lennard-Jones σ and ε/k from the critical point, Chung et al. 1988 Eq. 4-5; linear ψ = 1)."""
    name = identify_fluid(fluid)
    m = CP.PropsSI("molar_mass", name)
    tc = CP.PropsSI("Tcrit", name)
    rhoc = CP.PropsSI("rhomolar_critical", name)
    sigma = 0.809 * (1.0 / rhoc * 1e6) ** (1 / 3) * 1e-10  # Vc in cm³/mol → σ in m
    epsilon_k = tc / 1.2593
    if kind == "ecs_viscosity":
        if reference_fluid is None:
            try:
                return ECSViscosity.from_coolprop(name)
            except ModelError:
                reference_fluid = "R134a"
        return ECSViscosity.create(name, reference_fluid, sigma=sigma, epsilon_k=epsilon_k, psi=(1.0, 0.0))
    if kind == "chung_viscosity":
        return ChungViscosity.create(
            name, molar_mass=m, t_critical=tc, rhomolar_critical=rhoc, acentric=CP.PropsSI("acentric", name)
        )
    if kind == "lj_dilute_viscosity":
        return LennardJonesDiluteGas.create(name, m, sigma, epsilon_k)
    if kind == "res_viscosity":
        return ResidualEntropyViscosity.create(name)
    if kind == "coolprop_transport":
        return CoolPropTransport.create(name, Quantity.VISCOSITY)
    raise ModelError(f"unknown model kind {kind!r} (known: {', '.join(KINDS)})")


def set_fixed(model: Model, fixed: Mapping[str, bool]) -> Model:
    """Copy of ``model`` with some parameters fixed or freed."""
    params = dict(model.params())
    unknown = set(fixed) - set(params)
    if unknown:
        raise ModelError(f"unknown parameters: {sorted(unknown)}")
    spec = model_to_spec(model)
    for name, flag in fixed.items():
        spec["parameters"][name]["fixed"] = bool(flag)
    return model_from_spec(spec)
