"""Release gate (README §4e): the CF₃I tutorial workflow, headless, with the Python inside an installed PropBench.

    <installed python> -I -m propbench.gate --out gate-result --component cf3i-viscosity-data-1.0.0.zip

Steps (each timed; any failure fails the gate): install the published CF₃I data component offline (unless already
installed, as in the offline installer) → data check → fit the ECS model (reference R134a) → leave-one-dataset-out
validation → export the deviation figure (PNG and SVG) → write the report (Markdown and PDF). ``gate.json`` records
every step, the versions and the result. Everything is written to ``--out`` and the app data folders given by the
environment (``PB_COMPONENTS_DIR``); nothing else is touched.
"""

from __future__ import annotations

import argparse
import base64
import json
import platform
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

DATA_COMPONENT = "cf3i-viscosity-data"
# Smoke bound for an installed copy, not a quality target: the default ECS fit to the published data gives about
# 4.3 % AARD. The exact values are checked by the regression tests (worker/tests/regression/test_cf3i.py).
MAX_FIT_AARD = 10.0


class GateError(RuntimeError):
    """A step of the release gate failed."""


def _datasets(component: str | None) -> list[dict[str, Any]]:
    from propbench import components

    if component:
        components.install_file(component)
    paths = [p for p in components.files("data", "datasets.json") if p.parent.parent.name == DATA_COMPONENT]
    if not paths:
        raise GateError(f"the {DATA_COMPONENT} component is not installed (pass --component <archive>)")
    return json.loads(paths[0].read_text(encoding="utf-8"))["datasets"]


def run(out: Path, component: str | None = None, *, pdf: bool = True) -> dict[str, Any]:
    """Run the gate; returns the record also written to ``out/gate.json``."""
    from propbench import api

    out.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {"steps": [], "passed": False, "python": sys.version.split()[0], "os": platform.platform()}
    state: dict[str, Any] = {}

    def step(name: str, fn: Callable[[], Any]) -> None:
        start = time.perf_counter()
        try:
            detail = fn()
        except Exception as exc:
            record["steps"].append({"step": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
            raise GateError(f"{name}: {exc}") from exc
        record["steps"].append({"step": name, "ok": True, "seconds": round(time.perf_counter() - start, 3), **detail})

    def load() -> dict[str, Any]:
        state["datasets"] = _datasets(component)
        return {"datasets": len(state["datasets"]), "points": sum(len(d["values"]) for d in state["datasets"])}

    def check() -> dict[str, Any]:
        res = api.dataset_check(state["datasets"])
        return {"checked": len(res["datasets"])}

    def fit() -> dict[str, Any]:
        model = api.model_default("ecs_viscosity", "R13I1", "R134a")["model"]
        state["fit"] = api.model_fit(model, state["datasets"])
        summary = state["fit"]["summary"]
        if not summary.get("success", True):
            raise GateError("the fit did not converge")
        aard = summary["deviations"]["aard"]
        if not aard < MAX_FIT_AARD:
            raise GateError(f"fit AARD {aard:.3f} % exceeds {MAX_FIT_AARD} %")
        return {"aard_percent": aard}

    def validate() -> dict[str, Any]:
        state["study"] = api.study_validate(state["fit"]["model"], state["datasets"], methods=["loso"], physics=False)
        pooled = state["study"]["cross_validation"]["loso"]["pooled"]
        return {"loso_aard_percent": pooled["aard"]}

    def figure() -> dict[str, Any]:
        pts = state["fit"]["points"]
        layers = []
        for name in dict.fromkeys(pts["dataset"]):
            idx = [i for i, d in enumerate(pts["dataset"]) if d == name]
            x = [pts["temperature"][i] for i in idx]
            y = [pts["ard"][i] for i in idx]
            layers.append({"type": "points", "name": name, "x": x, "y": y})
        layers.append({"type": "hline", "y": 0.0})
        spec = {
            "preset": "elsevier1",
            "x": {"label": "T / K"},
            "y": {"label": "100·(η_exp − η_model)/η_model"},
            "layers": layers,
        }
        state["figure"] = spec
        sizes = {}
        for fmt in ("png", "svg"):
            data = base64.b64decode(api.figure_render(spec, fmt, 300)["content_base64"])
            (out / f"deviations.{fmt}").write_bytes(data)
            sizes[fmt] = len(data)
        return {"bytes": sizes}

    def report() -> dict[str, Any]:
        model = {"label": "ECS (R134a)", "summary": state["fit"]["summary"], "study": state["study"]}
        spec = {
            "title": "CF3I viscosity (release gate)",
            "datasets": state["datasets"],
            "models": [model],
            "figures": [{"caption": "Deviations of the data from the ECS model.", "spec": state["figure"]}],
        }
        sizes = {}
        for fmt in ("md", "pdf") if pdf else ("md",):
            data = base64.b64decode(api.report_render(spec, fmt)["content_base64"])
            (out / f"report.{fmt}").write_bytes(data)
            sizes[fmt] = len(data)
        return {"bytes": sizes}

    try:
        for name, fn in [
            ("load published data", load),
            ("data check", check),
            ("fit ECS model", fit),
            ("validate (leave one dataset out)", validate),
            ("export figure", figure),
            ("write report", report),
        ]:
            step(name, fn)
        record["passed"] = True
    finally:
        (out / "gate.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m propbench.gate", description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--component", help="archive of the cf3i-viscosity-data component (offline install)")
    parser.add_argument("--no-pdf", action="store_true")
    args = parser.parse_args(argv)
    try:
        record = run(args.out, args.component, pdf=not args.no_pdf)
    except GateError as exc:
        print(f"release gate FAILED: {exc}", file=sys.stderr)
        return 1
    for s in record["steps"]:
        print(f"  ok  {s['step']} ({s['seconds']} s)")
    print("release gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
