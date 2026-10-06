"""M4: reports (Markdown, Word, PDF, bundle) and CoolProp export — an exported model gives identical values
inside CoolProp (README M4 acceptance)."""

import base64
import io
import zipfile

import CoolProp.CoolProp as CP  # noqa: N817
import pytest

from propbench import export, report
from propbench.models import ChungViscosity, ECSViscosity


def test_exported_ecs_model_gives_identical_values_inside_coolprop():
    model = ECSViscosity.create(
        "R13I1", "R134a", sigma=0.4926e-9, epsilon_k=314.8, psi=(1.1332, -0.0543), psi_rhomolar_reducing=4430.6
    )
    text = export.to_json(model, "R13I1-test-export")
    temps = [260.0, 300.0, 340.0, 380.0, 420.0]
    rho = [CP.PropsSI("Dmolar", "T", t, "P", 3e6, "R13I1") for t in temps]
    result = export.verify(model, text, temps, rho)
    assert result["identical"], result
    assert result["max_rel_diff"] < 1e-12


def test_coolprops_own_ecs_model_round_trips():
    model = ECSViscosity.from_coolprop("R236FA")
    text = export.to_json(model, "R236FA-roundtrip")
    t = [250.0, 330.0]
    rho = [CP.PropsSI("Dmolar", "T", x, "P", 2e6, "R236FA") for x in t]
    assert export.verify(model, text, t, rho)["identical"]


def test_models_coolprop_cannot_represent_are_refused():
    k_model = ECSViscosity.create("R13I1", "R134a", sigma=0.4926e-9, epsilon_k=314.8, k=1.1)
    with pytest.raises(export.ExportError, match="dilute-gas factor"):
        export.to_json(k_model)
    chung = ChungViscosity.create("R134a", molar_mass=0.102, t_critical=374.2, rhomolar_critical=5017, acentric=0.327)
    with pytest.raises(export.ExportError, match="no CoolProp equivalent"):
        export.to_json(chung)
    ok = ECSViscosity.create("R13I1", "R134a", sigma=0.4926e-9, epsilon_k=314.8)
    with pytest.raises(export.ExportError, match="name"):
        export.to_json(ok, "bad name!")


SPEC = {
    "title": "CF3I viscosity",
    "authors": ["A. Researcher"],
    "template": "elsevier",
    "seed": 2026,
    "datasets": [
        {
            "name": "d1",
            "fluid": "R13I1",
            "quantity": "viscosity",
            "temperature": [300.0, 320.0],
            "values": [2e-4, 1.8e-4],
            "pressure": [3e6, 3e6],
            "expanded_uncertainty": [4e-6, 3.6e-6],
            "provenance": {"citation": "Tuhin et al. (2024)"},
        },
    ],
    "consistency": {"overlaps": [{"a": "d1", "b": "d2", "t_range": [333.0, 333.2]}], "warnings": ["d1 and d2 differ"]},
    "models": [
        {
            "label": "ECS (R134a)",
            "reference": "Huber 2003",
            "summary": {
                "values": {"psi_0": 1.133, "psi_1": -0.054},
                "standard_errors": {"psi_0": 0.004, "psi_1": 0.002},
                "deviations": {"aard": 0.54, "bias": 0.01, "max_ard": 1.3},
            },
            "study": {
                "cross_validation": {"lostate": {"folds": [{}] * 15, "pooled": {"aard": 0.55, "bias": 0.0}}},
                "physics": [{"name": "monotonic", "passed": True}],
            },
        }
    ],
    "comparison": {"rows": [{"model": "NISTIR 8209", "dataset": "d1", "n": 2, "aard": 5.48, "bias": -5.4}]},
    "selection": {
        "chosen": "ECS (R134a)",
        "reason": "lowest cv_aard",
        "sha256": "ab" * 32,
        "rule": {"metric": "cv_aard", "validation": "lostate"},
    },
    "references": [{"key": "Tuhin2024", "citation": "Tuhin et al. (2024) Int. J. Thermophys. 45:41"}],
    "figures": [
        {
            "caption": "Viscosity of CF3I.",
            "spec": {
                "preset": "elsevier1",
                "layers": [{"type": "points", "name": "d1", "x": [300, 320], "y": [200, 180]}],
            },
        }
    ],
}


def test_markdown_report_has_every_section_and_check_values():
    md = report.to_markdown(SPEC)
    for heading in (
        "## Data",
        "## Data consistency",
        "## Models",
        "## Comparison of models",
        "## Reference models: check values",
        "## Model selection",
        "## References",
        "## Reproducibility",
    ):
        assert heading in md
    assert "| d1 | 2 | 300.0–320.0 | 3–3 | 2 | Tuhin et al. (2024) |" in md
    assert "NISTIR 8209" in md
    assert "| yes |" in md  # check values reproduced
    assert "| NO |" not in md
    assert "Seed 2026" in md


@pytest.mark.parametrize("fmt", ["docx", "pdf", "md", "zip"])
def test_report_formats(fmt):
    out = report.render(SPEC, fmt, project={"meta": {"name": "x"}})
    data = base64.b64decode(out["content_base64"])
    if fmt == "pdf":
        assert data.startswith(b"%PDF")
    elif fmt in ("docx", "zip"):
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        if fmt == "zip":
            assert {
                "report.md",
                "report.pdf",
                "figure1.svg",
                "figure1.pdf",
                "versions.json",
                "inputs/project.json",
            } <= set(names)
        else:
            assert "word/document.xml" in names
    else:
        assert data.decode().startswith("# CF3I viscosity")


def test_text_is_escaped_for_typst():
    spec = {**SPEC, "title": "η = ν·ρ #1 [x] *bold* $5 @me <tag> back\\slash"}
    assert report.to_pdf(spec).startswith(b"%PDF")
