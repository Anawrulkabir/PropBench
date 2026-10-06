"""The public API / RPC v2 methods end to end: import → check → fit → validate → select, and model specs."""

import json
import math
import subprocess
import sys

import CoolProp.CoolProp as CP  # noqa: N817 - the name CoolProp itself documents
import numpy as np
import pytest

from propbench import api
from propbench.models import ECSViscosity, ModelError
from propbench.models.spec import default_model, model_from_spec, model_to_spec, set_fixed
from propbench.worker.server import METHODS, PROPBENCH_ERROR, Server

TRUTH = ECSViscosity.from_coolprop("R236FA")
STATES = [(t, p) for t in (260.0, 300.0, 340.0) for p in (1e5, 2e6, 1e7)]


def write_csv(path, factor=1.0):
    rows = ["T [K],p [MPa],eta [uPa s],U [%]"]
    for t, p in STATES:
        rho = CP.PropsSI("Dmolar", "T", t, "P", p, "R236FA")
        eta = float(TRUTH.predict([t], [rho])[0]) * factor
        rows.append(f"{t},{p / 1e6},{eta * 1e6!r},1.0")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


MAPPING = {
    "kind": "propbench.import-mapping",
    "version": 1,
    "quantity": "viscosity",
    "columns": [
        {"column": "T [K]", "role": "temperature", "unit": "K"},
        {"column": "p [MPa]", "role": "pressure", "unit": "MPa"},
        {"column": "eta [uPa s]", "role": "value", "unit": "uPa*s"},
        {"column": "U [%]", "role": "uncertainty", "uncertainty_kind": "relative_percent"},
    ],
}


@pytest.fixture
def imported(tmp_path):
    a = api.dataset_import(str(write_csv(tmp_path / "a.csv")), MAPPING, "R236FA")["datasets"]
    b = api.dataset_import(str(write_csv(tmp_path / "b.csv", 1.01)), MAPPING, "R236FA", name="b")["datasets"]
    return a + b


def test_every_method_is_exposed_by_the_server():
    server = Server()
    assert set(METHODS) <= set(server.methods)
    assert "property" in server.methods


@pytest.mark.parametrize("kind", ["ecs_viscosity", "chung_viscosity", "lj_dilute_viscosity"])
def test_spec_round_trip(kind):
    model = default_model(kind, "R236FA")
    spec = json.loads(json.dumps(model_to_spec(model)))  # through real JSON
    back = model_from_spec(spec)
    assert model_to_spec(back) == model_to_spec(model)
    t, rho = np.array([300.0]), np.array([CP.PropsSI("Dmolar", "T", 300.0, "P", 1e6, "R236FA")])
    np.testing.assert_array_equal(back.predict(t, rho), model.predict(t, rho))


def test_default_ecs_uses_coolprop_parameters_and_generic_start_otherwise():
    assert default_model("ecs_viscosity", "R236FA").params()["psi_0"].value == pytest.approx(1.10195)
    generic = default_model("ecs_viscosity", "R1234yf", reference_fluid="R134a")
    assert generic.params()["psi_0"].value == 1.0
    assert generic.params()["sigma"].value == pytest.approx(
        0.809 * (1e6 / CP.PropsSI("rhomolar_critical", "R1234yf")) ** (1 / 3) * 1e-10
    )
    with pytest.raises(ModelError, match="unknown model kind"):
        default_model("nope", "R134a")


def test_set_fixed():
    model = set_fixed(default_model("ecs_viscosity", "R236FA"), {"psi_2": True, "k": False})
    assert model.params()["psi_2"].fixed
    assert not model.params()["k"].fixed
    with pytest.raises(ModelError):
        set_fixed(model, {"nope": True})


def test_preview_csv(tmp_path):
    preview = api.dataset_preview(str(write_csv(tmp_path / "a.csv")), max_rows=3)
    assert preview["rows"][0] == ["T [K]", "p [MPa]", "eta [uPa s]", "U [%]"]
    assert len(preview["rows"]) == 3
    assert preview["delimiter"] == ","


def test_preview_xlsx(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "first"
    wb.active.append(["T", "eta"])
    wb.active.append([300.5, 1e-4])
    wb.create_sheet("second").append(["x"])
    wb.save(tmp_path / "w.xlsx")
    preview = api.dataset_preview(str(tmp_path / "w.xlsx"))
    assert preview["sheets"] == ["first", "second"]
    assert preview["rows"] == [["T", "eta"], ["300.5", "0.0001"]]
    assert api.dataset_preview(str(tmp_path / "w.xlsx"), sheet="second")["rows"] == [["x"]]


def test_import_and_check(imported):
    assert [d["name"] for d in imported] == ["a", "b"]
    check = api.dataset_check(imported)["datasets"]
    assert check[0]["n"] == len(STATES)
    assert check[0]["t_range"] == [260.0, 340.0]
    assert sum(check[0]["phases"].values()) == len(STATES)
    assert check[0]["dataset"]["phase"] is not None


def test_fit_validate_select(imported):
    start = model_to_spec(default_model("ecs_viscosity", "R236FA"))
    options = {"scale_factors": True, "fixed": {"psi_2": True}}
    result = api.model_fit(start, imported, options)
    assert result["summary"]["scale_factors"]["b"] == pytest.approx(1.01, rel=1e-3)
    assert result["summary"]["deviations"]["aard"] < 0.05
    assert len(result["points"]["ard"]) == 2 * len(STATES)
    assert result["n_parameters"] == 3
    json.dumps(result, allow_nan=False)

    study = api.study_validate(start, imported, methods=["loso", "kfold"], options=options, k=3, seed=4)
    assert set(study["cross_validation"]) == {"loso", "kfold"}
    assert study["cross_validation"]["loso"]["pooled"]["n"] == 2 * len(STATES)
    assert {c["name"] for c in study["physics"]} >= {"dilute-gas limit", "extrapolation"}
    json.dumps(study, allow_nan=False)

    rule = {"metric": "cv_aard", "validation": "loso", "tie_tolerance": 0.05, "require_physics": True, "notes": ""}
    locked = api.selection_lock(rule)
    candidates = [
        {"name": "ecs", "n_parameters": 3, "metrics": {"cv_aard": study["cross_validation"]["loso"]["pooled"]["aard"]}},
        {"name": "other", "n_parameters": 1, "metrics": {"cv_aard": None}},
    ]
    chosen = api.selection_select(locked["rule"], locked["sha256"], candidates)
    assert chosen["chosen"] == "ecs"
    assert chosen["excluded"] == ["other"]


def test_predict_at_t_and_p():
    spec = model_to_spec(TRUTH)
    out = api.model_predict(spec, [300.0, 300.0], pressure=[1e6, -1.0])
    expected = CP.PropsSI("V", "T", 300.0, "P", 1e6, "R236FA")
    assert out["values"][0] == pytest.approx(expected, rel=1e-10)
    assert out["values"][1] is None


def test_jsonable():
    assert api.jsonable({"a": np.array([1.0, math.nan]), "b": (np.int64(2), np.bool_(True))}) == {
        "a": [1.0, None],
        "b": [2, True],
    }


def test_rpc_errors_are_typed(tmp_path):
    server = Server()

    def call(method, params):
        return server.handle_line(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}))

    assert call("dataset.preview", {"path": str(tmp_path / "missing.csv")})["error"]["code"] == PROPBENCH_ERROR
    assert call("model.default", {"kind": "ecs_viscosity"})["error"]["code"] == -32602
    assert call("model.kinds", None)["result"]["kinds"]


def test_parallel_validation_inside_the_real_worker_process(imported):
    """Spawned validation processes must not start a second server (guarded __main__)."""
    start = model_to_spec(default_model("ecs_viscosity", "R236FA"))
    params = {
        "model": start,
        "datasets": imported,
        "methods": ["kfold"],
        "k": 2,
        "workers": 2,
        "physics": False,
        "options": {"fixed": {"psi_2": True}},
    }
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "study.validate", "params": params})
    proc = subprocess.run(
        [sys.executable, "-I", "-B", "-X", "utf8", "-m", "propbench.worker"],
        input=request + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [line.get("method") for line in lines] == ["ready", None]
    assert lines[1]["result"]["cross_validation"]["kfold"]["pooled"]["n"] == 2 * len(STATES)


def test_import_from_file_content(tmp_path):
    import base64

    data = base64.b64encode(write_csv(tmp_path / "x.csv").read_bytes()).decode()
    preview = api.dataset_preview(content_base64=data, filename="upload.csv", max_rows=2)
    assert preview["rows"][0][0] == "T [K]"
    out = api.dataset_import(mapping=MAPPING, fluid="R236FA", content_base64=data, filename="upload.csv")
    assert out["datasets"][0]["name"] == "upload"
    with pytest.raises(ValueError, match="base64"):
        api.dataset_preview(content_base64="%%%", filename="a.csv")
    with pytest.raises(ValueError, match="filename"):
        api.dataset_preview(content_base64=data)


def test_thermoml_from_file_content():
    import base64
    from pathlib import Path

    xml = Path(__file__).parent / "data" / "thermoml" / "r134a_sample.xml"
    data = base64.b64encode(xml.read_bytes()).decode()
    assert api.dataset_preview(content_base64=data, filename="r.xml")["thermoml"]
    out = api.dataset_import(content_base64=data, filename="r134a_sample.xml")
    assert out["datasets"]
