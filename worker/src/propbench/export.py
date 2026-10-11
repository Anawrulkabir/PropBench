"""Export fitted models to CoolProp (README §2, M4): a CoolProp fluid file whose transport block holds the model.

The fluid file is CoolProp's own JSON of the fluid (its equation of state is kept unchanged), renamed, with the
ECS viscosity model written in CoolProp's ECS format (``TRANSPORT.viscosity``: reference fluid, σ, ε/k and the
ψ polynomial; Huber et al. 2003, as CoolProp implements it). Load it with::

    import CoolProp.CoolProp as CP
    CP.add_fluids_as_JSON("HEOS", open("R13I1-PropBench.json").read())
    CP.PropsSI("V", "T", 300, "Dmolar", 8000, "R13I1-PropBench")

``verify`` loads the file into CoolProp and compares CoolProp's values with PropBench's at given states: the
export is accepted only when they agree (the M4 acceptance test). A model CoolProp cannot represent (an ECS model
with a dilute-gas factor k ≠ 1, or another model type) is refused with an explanation, never approximated.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

import CoolProp.CoolProp as CP  # noqa: N817
import numpy as np

from propbench.models.base import Model, ModelError
from propbench.models.ecs import ECSViscosity


class ExportError(ModelError):
    """The model cannot be written in a format CoolProp evaluates identically."""


def _viscosity_block(model: ECSViscosity) -> dict[str, Any]:
    p = model.params()
    k = p["k"].value
    if abs(k - 1.0) > 1e-12:
        raise ExportError(
            f"CoolProp's ECS viscosity has no dilute-gas factor; this model has k = {k:.6g}. "
            "Fix k = 1 and refit to export it."
        )
    n = len(model.psi_exponents)
    return {
        "type": "ECS",
        "BibTeX": "PropBench",
        "reference_fluid": model.reference_fluid,
        "sigma_eta": p["sigma"].value,
        "sigma_eta_units": "m",
        "epsilon_over_k": p["epsilon_k"].value,
        "epsilon_over_k_units": "K",
        "psi": {
            "a": [p[f"psi_{i}"].value for i in range(n)],
            "t": list(model.psi_exponents),
            "rhomolar_reducing": model.psi_rhomolar_reducing,
            "rhomolar_reducing_units": "mol/m^3",
        },
    }


def coolprop_fluid(model: Model, name: str | None = None) -> dict[str, Any]:
    """CoolProp fluid JSON (one fluid) carrying ``model`` as its viscosity model."""
    if not isinstance(model, ECSViscosity):
        raise ExportError(f"{type(model).__name__} has no CoolProp equivalent (export supports ECS viscosity)")
    fluid = json.loads(CP.get_fluid_param_string(model.fluid, "JSON"))[0]
    new_name = name or f"{model.fluid}-PropBench"
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", new_name):
        raise ExportError("the exported fluid name may only contain letters, digits, '-' and '_'")
    info = fluid["INFO"]
    info["NAME"] = new_name
    info["ALIASES"] = []
    info["REFPROP_NAME"] = "N/A"
    info["CAS"] = f"{info.get('CAS', 'N/A')}-propbench-{new_name}"  # CoolProp keys fluids by CAS too
    transport = dict(fluid.get("TRANSPORT", {}))
    transport["viscosity"] = _viscosity_block(model)
    fluid["TRANSPORT"] = transport
    return fluid


def to_json(model: Model, name: str | None = None) -> str:
    """The fluid file text (a JSON list with one fluid), ready for ``CoolProp.add_fluids_as_JSON``."""
    return json.dumps([coolprop_fluid(model, name)], indent=1)


def verify(model: Model, text: str, temperature: Sequence[float], molar_density: Sequence[float]) -> dict[str, Any]:
    """Load the exported fluid into CoolProp and compare its viscosity with the model's at the given states."""
    fluid = json.loads(text)[0]
    name = fluid["INFO"]["NAME"]
    try:
        CP.add_fluids_as_JSON("HEOS", text)
    except ValueError as exc:
        if "already" not in str(exc).lower():
            raise ExportError(f"CoolProp did not accept the exported fluid: {exc}") from exc
    t = np.asarray(temperature, dtype=float)
    rho = np.asarray(molar_density, dtype=float)
    ours = model.predict(t, rho)
    theirs = np.array([CP.PropsSI("V", "T", ti, "Dmolar", ri, name) for ti, ri in zip(t, rho, strict=True)])
    rel = np.abs(theirs / ours - 1.0)
    return {
        "fluid": name,
        "propbench": ours.tolist(),
        "coolprop": theirs.tolist(),
        "max_rel_diff": float(np.nanmax(rel)),
        "identical": bool(np.nanmax(rel) < 1e-9),
    }
