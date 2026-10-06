"""Published CF3I viscosity data (tests/data/cf3i, see SOURCE.md) as Datasets."""

import json
from pathlib import Path

import CoolProp.CoolProp as CP  # noqa: N817 - the name CoolProp itself documents
import numpy as np
import pytest

from propbench.core import Dataset, Phase, Provenance, Quantity

DATA = Path(__file__).parent.parent / "data" / "cf3i" / "cf3i_viscosity.json"


def load_cf3i() -> dict[str, Dataset]:
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    out = {}
    for d in raw["datasets"]:
        t = np.array([p["T"] for p in d["points"]], dtype=float)
        eta = np.array([p["eta"] for p in d["points"]], dtype=float) * 1e-6  # µPa·s → Pa·s
        provenance = Provenance(doi=d["doi"], citation=d["source"], method=d["method"])
        if "U_rel" in d:
            p = np.array([pt["p"] for pt in d["points"]], dtype=float) * 1e6  # MPa → Pa
            u = eta * d["U_rel"] / 100.0
            out[d["id"]] = Dataset(
                d["id"], "R13I1", Quantity.VISCOSITY, t, eta, pressure=p, expanded_uncertainty=u, provenance=provenance
            )
        else:
            # saturated liquid, pressure not reported: saturation state from the reference EoS of CF3I
            p = np.array([CP.PropsSI("P", "T", x, "Q", 0, "R13I1") for x in t])
            rho = np.array([CP.PropsSI("Dmolar", "T", x, "Q", 0, "R13I1") for x in t])
            out[d["id"]] = Dataset(
                d["id"],
                "R13I1",
                Quantity.VISCOSITY,
                t,
                eta,
                pressure=p,
                molar_density=rho,
                expanded_uncertainty=eta * d["U_rel_max"] / 100.0,
                phase=tuple([Phase.LIQUID] * len(t)),
                provenance=provenance,
            )
    return out


@pytest.fixture(scope="session")
def cf3i() -> dict[str, Dataset]:
    return load_cf3i()
