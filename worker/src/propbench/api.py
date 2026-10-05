"""The public operations of PropBench on JSON-compatible values (CLAUDE.md rule 2).

Each function here is one worker RPC method (``propbench.worker.server.METHODS``), reachable from the GUI through a
Tauri command and ``pb-engine``, and from ``pb-cli``. Inputs and outputs are plain dicts/lists in SI units; datasets
use the ``Dataset.to_dict`` schema and models the ``propbench.models.spec`` schema. NaN and infinities become null.
"""

from __future__ import annotations

import base64
import binascii
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

import numpy as np

from propbench.backends import assign_phases, get_backend
from propbench.core import Dataset, DatasetError
from propbench.fit import fit as run_fit
from propbench.fit import fit_data
from propbench.importers import ImportMapping, InMemoryFile, import_file, preview_file, read_thermoml
from propbench.importers.tabular import Source, source_suffix
from propbench.models.spec import KINDS, default_model, model_from_spec, model_to_spec, set_fixed
from propbench.validate import (
    SPLITS,
    Candidate,
    SelectionRule,
    cross_validate,
    information_criteria,
    physics_checks,
    select,
)

DEFAULT_BACKEND = "CoolProp::HEOS"


def jsonable(value: Any) -> Any:
    """Plain JSON values: numpy → Python, NaN/inf → None, tuples → lists."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [jsonable(v) for v in value.tolist()]
    if isinstance(value, np.bool_ | bool):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        v = float(value)
        return v if math.isfinite(v) else None
    return value


def _datasets(data: Sequence[Mapping[str, Any]]) -> list[Dataset]:
    if not isinstance(data, list) or not data:
        raise DatasetError("'datasets' must be a non-empty list of datasets")
    return [Dataset.from_dict(dict(d)) for d in data]


# --- fluids and properties ---


def fluids() -> dict[str, Any]:
    import CoolProp.CoolProp as CP  # noqa: N817

    names = sorted(CP.get_global_param_string("FluidsList").split(","), key=str.lower)
    return {"fluids": names}


def properties(
    fluid: str,
    pair: str,
    values1: Sequence[float],
    values2: Sequence[float],
    outputs: Sequence[str],
    backend: str = DEFAULT_BACKEND,
) -> dict[str, Any]:
    """Several properties at many states in one call (failed states are null, with a reason in ``errors``)."""
    result = get_backend(backend).properties(fluid, pair, values1, values2, list(outputs))
    return jsonable(
        {
            "outputs": result.outputs,
            "failed": result.failed,
            "errors": {str(k): v for k, v in result.errors.items()},
            "backend": result.backend,
            "backend_version": result.backend_version,
        }
    )


# --- datasets ---


def _source(path: str | None, content_base64: str | None, filename: str | None) -> Source:
    """A file path, or the file's content (base64) with its name, as sent by the UI's file picker."""
    if content_base64 is not None:
        if not filename:
            raise DatasetError("file content needs a filename (for its type)")
        try:
            data = base64.b64decode(content_base64, validate=True)
        except binascii.Error as exc:
            raise DatasetError(f"file content is not valid base64: {exc}") from exc
        return InMemoryFile(filename, data)
    if not path:
        raise DatasetError("give a path or the file content")
    return path


def dataset_preview(
    path: str | None = None,
    sheet: str | None = None,
    max_rows: int = 30,
    content_base64: str | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    source = _source(path, content_base64, filename)
    if source_suffix(source) == ".xml":
        return {"rows": [], "sheets": [], "sheet": None, "delimiter": None, "thermoml": True}
    p = preview_file(source, sheet, max_rows)
    return {
        "rows": [list(r) for r in p.rows],
        "sheets": list(p.sheets),
        "sheet": p.sheet,
        "delimiter": p.delimiter,
        "thermoml": False,
    }


def dataset_import(
    path: str | None = None,
    mapping: Mapping[str, Any] | None = None,
    fluid: str | None = None,
    name: str | None = None,
    content_base64: str | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    """CSV/Excel with a mapping and a fluid, or ThermoML (.xml) without either."""
    source = _source(path, content_base64, filename)
    if source_suffix(source) == ".xml":
        result = read_thermoml(source)
        return {"datasets": [d.to_dict() for d in result.datasets], "warnings": list(result.warnings)}
    if mapping is None or fluid is None:
        raise DatasetError("CSV and Excel imports need a mapping and a fluid")
    dataset = import_file(source, ImportMapping.from_dict(dict(mapping)), fluid=fluid, name=name)
    return {"datasets": [dataset.to_dict()], "warnings": []}


def dataset_check(datasets: Sequence[Mapping[str, Any]], backend: str = DEFAULT_BACKEND) -> dict[str, Any]:
    """EoS phase of each point, disagreements with the phases stated in the source, and a summary per dataset."""
    b = get_backend(backend)
    out = []
    for d in _datasets(datasets):
        entry: dict[str, Any] = {
            "name": d.name,
            "fluid": d.fluid,
            "quantity": d.quantity.value,
            "n": len(d),
            "t_range": [float(d.temperature.min()), float(d.temperature.max())],
            "p_range": None if d.pressure is None else [float(d.pressure.min()), float(d.pressure.max())],
            "has_uncertainty": d.expanded_uncertainty is not None,
        }
        if d.pressure is not None:
            check = assign_phases(d, b)
            entry["dataset"] = check.dataset.to_dict()
            entry["phase_mismatches"] = list(check.mismatches)
            entry["errors"] = {str(k): v for k, v in check.errors.items()}
            counts: dict[str, int] = {}
            for phase in check.dataset.phase or ():
                counts[phase.value] = counts.get(phase.value, 0) + 1
            entry["phases"] = counts
        else:
            entry["dataset"] = d.to_dict()
            entry["phase_mismatches"], entry["errors"], entry["phases"] = [], {}, {}
        out.append(entry)
    return jsonable({"datasets": out})


# --- models ---


def model_kinds() -> dict[str, Any]:
    return {"kinds": [{"kind": k, **v} for k, v in KINDS.items()]}


def model_default(kind: str, fluid: str, reference_fluid: str | None = None) -> dict[str, Any]:
    return jsonable({"model": model_to_spec(default_model(kind, fluid, reference_fluid))})


def model_predict(
    model: Mapping[str, Any],
    temperature: Sequence[float],
    molar_density: Sequence[float] | None = None,
    pressure: Sequence[float] | None = None,
    backend: str = DEFAULT_BACKEND,
) -> dict[str, Any]:
    """Model values at (T, ρ), or at (T, p) with ρ from the backend's equation of state."""
    m = model_from_spec(model)
    t = np.asarray(temperature, dtype=float)
    if molar_density is None:
        if pressure is None:
            raise DatasetError("give molar_density or pressure")
        batch = get_backend(backend).properties(m.fluid, "PT_INPUTS", pressure, t, ["Dmolar"])
        rho = batch["Dmolar"]
    else:
        rho = np.asarray(molar_density, dtype=float)
    from propbench.validate.physics import predict_each

    ok = np.isfinite(rho)
    values = np.full(len(t), np.nan)
    if ok.any():
        values[ok] = predict_each(m, t[ok], rho[ok])
    return jsonable({"values": values, "molar_density": rho})


def _fit_options(options: Mapping[str, Any] | None) -> dict[str, Any]:
    o = dict(options or {})
    allowed = {"weighted", "scale_factors", "multistart", "seed"}
    unknown = set(o) - allowed - {"fixed"}
    if unknown:
        raise ValueError(f"unknown fit options: {sorted(unknown)} (known: {sorted(allowed | {'fixed'})})")
    return {k: o[k] for k in allowed if k in o}


def model_fit(
    model: Mapping[str, Any],
    datasets: Sequence[Mapping[str, Any]],
    options: Mapping[str, Any] | None = None,
    backend: str = DEFAULT_BACKEND,
) -> dict[str, Any]:
    """Fit the free parameters; ``options.fixed`` ({name: bool}) fixes or frees parameters first."""
    m = model_from_spec(model)
    if options and options.get("fixed"):
        m = set_fixed(m, options["fixed"])
    data = fit_data(_datasets(datasets), get_backend(backend))
    result = run_fit(m, data, **_fit_options(options))
    weighted_sse = 2.0 * result.cost
    n_free = len(result.values) + len(result.scale_factors)
    points = {
        "dataset": [data.dataset_names[j] for j in data.dataset_index],
        "point_id": data.point_ids,
        "temperature": data.temperature,
        "molar_density": data.molar_density,
        "value": data.values,
        "ard": result.ard,
    }
    return jsonable(
        {
            "model": model_to_spec(result.model),
            "summary": result.summary(),
            "criteria": information_criteria(len(data), n_free, weighted_sse),
            "n_parameters": n_free,
            "points": points,
        }
    )


# --- validation and selection ---


def study_validate(
    model: Mapping[str, Any],
    datasets: Sequence[Mapping[str, Any]],
    methods: Sequence[str] = ("loso",),
    options: Mapping[str, Any] | None = None,
    k: int = 5,
    n_bootstrap: int = 50,
    seed: int = 0,
    workers: int = 1,
    physics: bool = True,
    backend: str = DEFAULT_BACKEND,
) -> dict[str, Any]:
    """Cross-validation by each of ``methods`` (loso, loto, kfold, bootstrap) and the physics checks of the model
    fitted to all data."""
    m = model_from_spec(model)
    if options and options.get("fixed"):
        m = set_fixed(m, options["fixed"])
    ds = _datasets(datasets)
    data = fit_data(ds, get_backend(backend))
    fit_options = _fit_options(options)
    fit_options.pop("seed", None)
    out: dict[str, Any] = {"seed": seed, "cross_validation": {}}
    for method in methods:
        if method not in SPLITS:
            raise ValueError(f"unknown validation method {method!r} (known: {', '.join(SPLITS)})")
        if method == "kfold":
            folds = SPLITS[method](data, k=k, seed=seed)
        elif method == "bootstrap":
            folds = SPLITS[method](data, n=n_bootstrap, seed=seed)
        else:
            folds = SPLITS[method](data)
        cv = cross_validate(m, data, folds, method=method, workers=workers, seed=seed, **fit_options)
        out["cross_validation"][method] = cv.summary()
    if physics:
        fitted = run_fit(m, data, seed=seed, **fit_options).model
        pressures = [d.pressure for d in ds if d.pressure is not None]
        p = np.concatenate(pressures) if pressures else None
        out["physics"] = [c.as_dict() for c in physics_checks(fitted, data.temperature, p, get_backend(backend))]
    return jsonable(out)


def selection_lock(rule: Mapping[str, Any]) -> dict[str, Any]:
    r = SelectionRule.from_dict(dict(rule))
    return {"rule": asdict(r), "sha256": r.sha256()}


def selection_select(rule: Mapping[str, Any], sha256: str, candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    r = SelectionRule.from_dict(dict(rule))
    cands = [
        Candidate(
            str(c["name"]),
            int(c["n_parameters"]),
            {k: (math.nan if v is None else float(v)) for k, v in dict(c["metrics"]).items()},
            bool(c.get("physics_passed", True)),
        )
        for c in candidates
    ]
    s = select(r, sha256, cands)
    return jsonable(
        {
            "chosen": s.chosen,
            "ranking": s.ranking,
            "excluded": s.excluded,
            "rule_sha256": s.rule_sha256,
            "reason": s.reason,
        }
    )


__all__ = [
    "dataset_check",
    "dataset_import",
    "dataset_preview",
    "fluids",
    "jsonable",
    "model_default",
    "model_fit",
    "model_kinds",
    "model_predict",
    "properties",
    "selection_lock",
    "selection_select",
    "study_validate",
]
