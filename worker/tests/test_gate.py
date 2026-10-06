"""Release gate (README §4e): the CF3I tutorial workflow runs headless from the published data component."""

import importlib.util
import json
from pathlib import Path

from propbench import gate

BUILD = Path(__file__).resolve().parents[2] / "components" / "build.py"


def _build_components(out: Path) -> Path:
    spec = importlib.util.spec_from_file_location("components_build", BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build(out)
    return next(out.glob(f"{gate.DATA_COMPONENT}-*.zip"))


def test_gate_runs_the_tutorial_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("PB_COMPONENTS_DIR", str(tmp_path / "components"))
    archive = _build_components(tmp_path / "dist")
    out = tmp_path / "gate"
    assert gate.main(["--out", str(out), "--component", str(archive), "--no-pdf"]) == 0
    record = json.loads((out / "gate.json").read_text(encoding="utf-8"))
    assert record["passed"]
    assert [s["step"] for s in record["steps"]][-1] == "write report"
    fit = next(s for s in record["steps"] if s["step"] == "fit ECS model")
    assert fit["aard_percent"] < gate.MAX_FIT_AARD
    assert (out / "deviations.png").read_bytes().startswith(b"\x89PNG")
    assert (out / "report.md").stat().st_size > 0


def test_gate_fails_without_the_data(tmp_path, monkeypatch):
    monkeypatch.setenv("PB_COMPONENTS_DIR", str(tmp_path / "empty"))
    out = tmp_path / "gate"
    assert gate.main(["--out", str(out)]) == 1
    record = json.loads((out / "gate.json").read_text(encoding="utf-8"))
    assert not record["passed"]
    assert not record["steps"][0]["ok"]
