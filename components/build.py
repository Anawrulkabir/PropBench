"""Build the component archives and registry from the folders here (README §2b; nothing is published).

    uv run --project worker python components/build.py dist/components

Each folder with a ``component.json`` becomes ``<id>-<version>.zip``; ``registry.json`` lists them with size and
SHA-256. Archives are reproducible (fixed timestamps, sorted entries). Generated files (``datasets.json`` of data
components) are written into a staging copy, never into this folder.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import CoolProp.CoolProp as CP
from propbench import components

HERE = Path(__file__).resolve().parent
CF3I = HERE.parent / "worker" / "tests" / "data" / "cf3i"


def cf3i_datasets() -> dict:
    """The published CF3I tables as worker datasets (SI). Duan 1999 reports saturated-liquid values without
    pressure: saturation pressure and density come from CoolProp's reference EoS of R13I1 (noted per dataset)."""
    raw = json.loads((CF3I / "cf3i_viscosity.json").read_text(encoding="utf-8"))
    out = []
    for d in raw["datasets"]:
        t = [float(p["T"]) for p in d["points"]]
        eta = [float(p["eta"]) * 1e-6 for p in d["points"]]
        provenance = {
            "doi": d["doi"],
            "citation": d["source"],
            "method": d["method"],
            "notes": "",
        }
        ds = {
            "schema_version": 1,
            "name": d["id"],
            "fluid": "R13I1",
            "quantity": "viscosity",
            "temperature": t,
            "values": eta,
            "point_ids": list(range(len(t))),
            "coverage_factor": 2.0,
            "provenance": provenance,
        }
        if "U_rel" in d:
            ds["pressure"] = [float(p["p"]) * 1e6 for p in d["points"]]
            ds["expanded_uncertainty"] = [v * d["U_rel"] / 100.0 for v in eta]
        else:
            ds["pressure"] = [CP.PropsSI("P", "T", x, "Q", 0, "R13I1") for x in t]
            ds["molar_density"] = [
                CP.PropsSI("Dmolar", "T", x, "Q", 0, "R13I1") for x in t
            ]
            ds["expanded_uncertainty"] = [v * d["U_rel_max"] / 100.0 for v in eta]
            ds["phase"] = ["liquid"] * len(t)
            provenance["notes"] = (
                f"saturated liquid; p_sat and density from CoolProp {CP.get_global_param_string('version')}"
            )
        out.append(ds)
    return {"datasets": out}


GENERATED = {
    "cf3i-viscosity-data": {
        "datasets.json": cf3i_datasets,
        "SOURCE.md": lambda: (CF3I / "SOURCE.md").read_text(),
    }
}


def build(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    for meta in sorted(HERE.glob("*/component.json")):
        src = meta.parent
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / src.name
            shutil.copytree(src, stage)
            for name, make in GENERATED.get(src.name, {}).items():
                content = make()
                text = (
                    content
                    if isinstance(content, str)
                    else json.dumps(content, indent=1, sort_keys=True)
                )
                (stage / name).write_text(text, encoding="utf-8")
            info = json.loads(meta.read_text(encoding="utf-8"))
            entries.append(
                components.build_archive(
                    stage, out / f"{info['id']}-{info['version']}.zip"
                )
            )
    registry = {"schema": components.REGISTRY_SCHEMA, "components": entries}
    (out / "registry.json").write_text(json.dumps(registry, indent=1), encoding="utf-8")
    return registry


if __name__ == "__main__":
    target = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "dist" / "components"
    )
    reg = build(target)
    print(f"{len(reg['components'])} components → {target}")
