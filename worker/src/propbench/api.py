"""The public operations of PropBench on JSON-compatible values (CLAUDE.md rule 2).

Each function here is one worker RPC method (``propbench.worker.server.METHODS``), reachable from the GUI through a
Tauri command and ``pb-engine``, and from ``pb-cli``. Inputs and outputs are plain dicts/lists in SI units; datasets
use the ``Dataset.to_dict`` schema and models the ``propbench.models.spec`` schema. NaN and infinities become null.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

import numpy as np

from propbench.backends import assign_phases, get_backend
from propbench.consist import compare_models, consistency_report, isotherm_trends, phase_classes
from propbench.core import Dataset, DatasetError
from propbench.fit import fit as run_fit
from propbench.fit import fit_data
from propbench.importers import ImportMapping, InMemoryFile, import_file, preview_file, read_thermoml
from propbench.importers.tabular import Source, source_suffix
from propbench.models import Model
from propbench.models.reference import reference_models
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
    k = len(result.values)
    cov = result.covariance[:k, :k]
    with np.errstate(divide="ignore", invalid="ignore"):
        sd = np.sqrt(np.diag(cov))
        correlation = cov / np.outer(sd, sd)
    return jsonable(
        {
            "model": model_to_spec(result.model),
            "summary": result.summary(),
            "correlation": {"names": list(result.values), "matrix": correlation},
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
        out["cross_validation"][method] = cv.summary(data.dataset_names)
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


# --- consistency and comparison ---


def _named_models(
    models: Sequence[Mapping[str, Any]] | None, datasets: list[Dataset], include_references: bool
) -> dict[str, Model]:
    """User models ({name, model}) plus, optionally, the reference models available for the data's fluid."""
    out: dict[str, Model] = {}
    for entry in models or []:
        out[str(entry["name"])] = model_from_spec(entry["model"])
    if include_references and datasets:
        for label, model, _ in reference_models(datasets[0].fluid, datasets[0].quantity):
            out.setdefault(label, model)
    return out


def _same_isotherm(d: Dataset, temperature: float, phase: str, t_tol: float) -> np.ndarray:
    """Rows of ``d`` on the isotherm at ``temperature`` and in phase class ``phase``."""
    cls = phase_classes(d)
    ok = np.array([phase == "any" or c in ("any", phase) for c in cls], dtype=bool)
    return np.flatnonzero((np.abs(d.temperature - temperature) <= t_tol) & ok)


def _isotherm_plots(datasets: list[Dataset], comparisons: list[Any], t_tol: float) -> list[dict[str, Any]]:
    """For each isotherm where one dataset was compared with another: both sets of points with expanded
    uncertainties and the trend line of the reference dataset over the whole pressure range."""
    by_name = {d.name: d for d in datasets}
    plots = []
    seen: set[tuple[str, str, float, str]] = set()
    for ref_name, other_name in {(c.a, c.b) for c in comparisons}:
        ref, other = by_name[ref_name], by_name[other_name]
        for trend in isotherm_trends(ref, t_tol):
            key = (ref_name, other_name, round(trend.temperature, 6), trend.phase)
            if key in seen:
                continue

            near_ref = _same_isotherm(ref, trend.temperature, trend.phase, t_tol)
            near_other = _same_isotherm(other, trend.temperature, trend.phase, t_tol)
            if len(near_other) == 0 or ref.pressure is None or other.pressure is None:
                continue
            seen.add(key)
            p_all = np.concatenate([ref.pressure[near_ref], other.pressure[near_other]])
            line_p = np.linspace(p_all.min(), p_all.max(), 25)

            def series(d: Dataset, idx: np.ndarray) -> dict[str, Any]:
                return {
                    "dataset": d.name,
                    "pressure": None if d.pressure is None else d.pressure[idx],
                    "value": d.values[idx],
                    "expanded_uncertainty": None if d.expanded_uncertainty is None else d.expanded_uncertainty[idx],
                    "point_ids": d.point_ids[idx],
                }

            plots.append(
                {
                    "temperature": trend.temperature,
                    "phase": trend.phase,
                    "reference": ref_name,
                    "other": other_name,
                    "points": [series(ref, near_ref), series(other, near_other)],
                    "trend": {"pressure": line_p, "value": [trend.predict(float(x))[0] for x in line_p]},
                    "trend_range": list(trend.p_range),
                }
            )
    # the better-sampled reference first (its trend extrapolates least), then by temperature
    plots.sort(key=lambda pl: (-len(by_name[pl["reference"]]), pl["reference"], pl["other"], pl["temperature"]))
    return plots


def consistency_analyze(
    datasets: Sequence[Mapping[str, Any]],
    models: Sequence[Mapping[str, Any]] | None = None,
    include_references: bool = True,
    t_tol: float = 1.0,
    backend: str = DEFAULT_BACKEND,
) -> dict[str, Any]:
    """Overlaps, model-free comparisons at equal T, pressure-trend checks, offsets (against other datasets and
    against each model) and z-scores. ``models`` are {name, model} entries (model = spec)."""
    b = get_backend(backend)
    ds = [assign_phases(d, b).dataset if d.phase is None and d.pressure is not None else d for d in _datasets(datasets)]
    named = _named_models(models, ds, include_references)
    report = consistency_report(ds, named, b, t_tol)
    out = report.as_dict()
    out["models"] = list(named)
    out["plots"] = _isotherm_plots(ds, report.comparisons, t_tol)
    return jsonable(out)


def model_references(fluid: str, quantity: str = "viscosity") -> dict[str, Any]:
    """Reference models available for a fluid and property (published registry entries, CoolProp correlations)."""
    return jsonable(
        {
            "references": [
                {"label": label, "model": model_to_spec(model), "citation": citation}
                for label, model, citation in reference_models(fluid, quantity)
            ]
        }
    )


def model_compare(
    datasets: Sequence[Mapping[str, Any]],
    models: Sequence[Mapping[str, Any]] | None = None,
    include_references: bool = True,
    backend: str = DEFAULT_BACKEND,
) -> dict[str, Any]:
    """Deviation statistics of every model (user models and reference models) on every dataset."""
    ds = _datasets(datasets)
    named = _named_models(models, ds, include_references)
    rows = compare_models(named, ds, get_backend(backend))
    return jsonable({"models": list(named), "rows": [r.as_dict() for r in rows]})


# --- components (README §2b) ---

DEFAULT_REGISTRY = "https://propbench.github.io/components/registry.json"


def _registry_location(registry: str | None) -> str:
    import os

    return registry or os.environ.get("PB_REGISTRY_URL") or DEFAULT_REGISTRY


def components_list(registry: str | None = None) -> dict[str, Any]:
    """Installed components, the registry's components and available updates. A registry that cannot be read is
    reported in ``registry_error`` (offline use keeps working)."""
    from propbench import components

    installed = components.installed()
    try:
        available = components.load_registry(_registry_location(registry))
        error = None
    except components.ComponentError as exc:
        available, error = [], str(exc)
    return {
        "registry": _registry_location(registry),
        "registry_error": error,
        "installed": [c.to_dict() for c in installed.values()],
        "available": [c.to_dict() for c in available],
        "updates": [c.to_dict() for c in components.updates(available)],
    }


def components_install(id: str, registry: str | None = None) -> dict[str, Any]:
    """Download, verify (size, SHA-256) and install a component and what it requires."""
    from propbench import components

    done = components.install(id, components.load_registry(_registry_location(registry)))
    return {"installed": [c.to_dict() for c in done]}


def components_install_file(content_base64: str) -> dict[str, Any]:
    """Offline installation from a component archive."""
    from propbench import components

    c = components.install_file(components.decode_base64(content_base64))
    return {"installed": [c.to_dict()]}


def components_remove(id: str) -> dict[str, Any]:
    from propbench import components

    components.remove(id)
    return {"removed": id}


def components_datasets() -> dict[str, Any]:
    """Published datasets of installed ``data`` components (each with its DOI and citation)."""
    import json as _json

    from propbench import components

    out = []
    for path in components.files("data", "datasets.json"):
        for d in _json.loads(path.read_text(encoding="utf-8")).get("datasets", []):
            out.append(Dataset.from_dict(dict(d)).to_dict())
    return jsonable({"datasets": out})


# --- worksheets, curve fitting, uncertainty, references (M3a) ---


def worksheet_compute(
    dataset: Mapping[str, Any],
    formulas: Sequence[Mapping[str, str]] = (),
    filter: str | None = None,
    masked: Sequence[int] = (),
) -> dict[str, Any]:
    """Formula columns, the row filter and column statistics of one dataset (README §2e.1)."""
    from propbench import worksheet

    ds = Dataset.from_dict(dict(dataset))
    return jsonable(worksheet.compute(ds, formulas, filter, masked))


def _series(spec: Mapping[str, Any]) -> Any:
    from propbench import curvefit, worksheet

    ds = Dataset.from_dict(dict(spec["dataset"]))
    cols = worksheet.dataset_columns(ds)
    cols.update(worksheet.compute(ds, spec.get("formulas", ()))["columns"])
    keep = ~np.isin(np.asarray(ds.point_ids), np.asarray(list(spec.get("masked", ())), dtype=int))
    cols = {k: np.asarray(v)[keep] for k, v in cols.items()}
    return curvefit.series_from_columns(
        ds.name, cols, list(spec.get("x", ["T"])), spec.get("y", "y"), spec.get("sigma")
    )


def curvefit_fit(
    equation: str,
    series: Sequence[Mapping[str, Any]],
    parameters: Mapping[str, Mapping[str, Any]],
    local: Sequence[str] = (),
    scale_factors: bool = False,
    weighted: bool = True,
    multistart: int = 0,
    seed: int = 0,
) -> dict[str, Any]:
    """General curve fit of a user equation to one or more datasets (shared and per-dataset parameters)."""
    from propbench import curvefit

    def number(v: Any, default: float) -> float:
        return default if v is None else float(v)

    specs = {
        name: curvefit.ParameterSpec(
            float(p["value"]), number(p.get("lower"), -math.inf), number(p.get("upper"), math.inf), bool(p.get("fixed"))
        )
        for name, p in parameters.items()
    }
    result = curvefit.fit(
        equation,
        [_series(s) for s in series],
        specs,
        local=list(local),
        scale_factors=scale_factors,
        weighted=weighted,
        multistart=int(multistart),
        seed=int(seed),
    )
    return jsonable(result.as_dict())


def curvefit_ftest(simple: Mapping[str, Any], full: Mapping[str, Any]) -> dict[str, Any]:
    """F-test of two nested curve fits (results of curvefit.fit on the same data)."""
    from propbench import curvefit

    def as_fit(d: Mapping[str, Any]) -> Any:
        return curvefit.CurveFit(**{k: d[k] for k in curvefit.CurveFit.__dataclass_fields__ if k in d})

    return curvefit.f_test(as_fit(simple), as_fit(full))


def _gum_inputs(inputs: Sequence[Mapping[str, Any]]) -> list[Any]:
    from propbench import gum

    return [
        gum.Input(
            str(i["name"]),
            float(i["value"]),
            float(i["u"]),
            math.inf if i.get("dof") in (None, "", "inf") else float(i["dof"]),
            str(i.get("distribution", "normal")),
        )
        for i in inputs
    ]


def _correlations(items: Sequence[Mapping[str, Any]] | None) -> dict[tuple[str, str], float]:
    return {(str(c["a"]), str(c["b"])): float(c["r"]) for c in items or ()}


def gum_linear(
    model: str,
    inputs: Sequence[Mapping[str, Any]],
    correlations: Sequence[Mapping[str, Any]] | None = None,
    p: float = 0.9545,
) -> dict[str, Any]:
    """GUM uncertainty budget (JCGM 100): sensitivities, contributions, ν_eff, k and U."""
    from propbench import gum

    return jsonable(gum.linear(model, _gum_inputs(inputs), _correlations(correlations), p))


def gum_montecarlo(
    model: str,
    inputs: Sequence[Mapping[str, Any]],
    correlations: Sequence[Mapping[str, Any]] | None = None,
    p: float = 0.9545,
    draws: int = 200_000,
    seed: int = 0,
) -> dict[str, Any]:
    """Monte Carlo propagation (JCGM 101) with a seeded generator."""
    from propbench import gum

    draws = max(1_000, min(int(draws), 5_000_000))
    return jsonable(gum.monte_carlo(model, _gum_inputs(inputs), _correlations(correlations), p, draws, int(seed)))


def refs_parse(bibtex: str) -> dict[str, Any]:
    from propbench import refs

    entries = refs.parse_bibtex(bibtex)
    return {"references": [{**e, "citation": refs.citation(e)} for e in entries]}


def refs_format(references: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    from propbench import refs

    return {"bibtex": refs.to_bibtex(list(references)), "citations": [refs.citation(r) for r in references]}


def refs_doi(doi: str) -> dict[str, Any]:
    """Look a DOI up at Crossref (network)."""
    from propbench import refs

    ref = refs.lookup_doi(doi)
    return {"reference": {**ref, "citation": refs.citation(ref)}}


# --- publication figures (M3b) ---


def figure_render(spec: Mapping[str, Any], format: str = "svg", dpi: int = 600) -> dict[str, Any]:
    """A publication figure (matplotlib) from a figure spec: SVG/PDF/EPS, or PNG/TIFF up to 2500 dpi."""
    from propbench import figures

    return figures.render_base64(spec, format, int(dpi))


def figure_presets() -> dict[str, Any]:
    from propbench import figures

    return {"presets": [{"id": k, **v} for k, v in figures.PRESETS.items()], "formats": list(figures.FORMATS)}


# --- reports and CoolProp export (M4) ---


def report_render(
    spec: Mapping[str, Any], format: str = "pdf", project: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The report as Markdown, Word, PDF, or a reproducibility bundle (zip)."""
    from propbench import report

    return report.render(spec, format, project)


def model_export_coolprop(
    model: Mapping[str, Any],
    name: str | None = None,
    datasets: Sequence[Mapping[str, Any]] | None = None,
    backend: str = DEFAULT_BACKEND,
) -> dict[str, Any]:
    """CoolProp fluid file holding the model, verified inside CoolProp at the datasets' states (or a default grid)."""
    from propbench import export

    m = model_from_spec(model)
    text = export.to_json(m, name)
    if datasets:
        data = fit_data(_datasets(datasets), get_backend(backend))
        t, rho = data.temperature, data.molar_density
    else:
        import CoolProp.CoolProp as CP  # noqa: N817

        tc = CP.PropsSI("Tcrit", m.fluid)
        t = np.linspace(0.6 * tc, 1.2 * tc, 7)
        rho = np.array([CP.PropsSI("Dmolar", "T", x, "P", 2e6, m.fluid) for x in t])
    return {"json": text, "verification": jsonable(export.verify(m, text, t.tolist(), rho.tolist()))}


# --- integrations: AI assistant and GitHub (M4b); credentials come from the shell (OS keychain) per request ---


def assistant_providers() -> dict[str, Any]:
    from propbench import assistant

    return {"providers": [{"id": k, **v} for k, v in assistant.PROVIDERS.items()]}


def assistant_ask(
    provider: str,
    model: str,
    messages: Sequence[Mapping[str, str]],
    api_key: str | None = None,
    base_url: str | None = None,
    context: str = "",
) -> dict[str, Any]:
    """A reply and the changes it proposes (data only: the app applies a proposal after the user confirms)."""
    from propbench import assistant

    return assistant.ask(provider, model, messages, api_key, base_url, context)


def github_device_start(client_id: str) -> dict[str, Any]:
    from propbench import github

    return github.device_start(client_id)


def github_device_poll(client_id: str, device_code: str) -> dict[str, Any]:
    from propbench import github

    return github.device_poll(client_id, device_code)


def github_push(
    token: str, owner: str, repo: str, branch: str, files: Mapping[str, str], message: str
) -> dict[str, Any]:
    """Push the project mirror (path → UTF-8 text) as one commit on ``branch``."""
    from propbench import github

    encoded = github.encode_files({k: v.encode("utf-8") for k, v in files.items()})
    return github.push(token, owner, repo, branch, encoded, message)


# --- plug-ins (M4c) ---


def plugins_run(request: Mapping[str, Any], project: str) -> dict[str, Any]:
    """Run an approved Python plug-in in the project's environment. Only the shell sends this, after ``pb-plugin``
    verified the package and the user's approval; ``request`` carries the approved permissions."""
    from propbench import plugins

    return plugins.run(request, project=project)


# --- project environments (M1c) ---


def env_status(project: str) -> dict[str, Any]:
    """Whether the project's environment exists, where, and its lock."""
    from propbench import envs

    env = envs.get(project)
    return {
        "name": env.name,
        "path": str(env.path),
        "exists": env.exists(),
        "python": str(env.python),
        "lock": envs.lock(env) if env.exists() else "",
    }


def env_create(project: str) -> dict[str, Any]:
    from propbench import envs

    envs.create(project)
    return env_status(project)


def env_install(project: str, packages: Sequence[str]) -> dict[str, Any]:
    """Install packages into the project's environment (created when missing); returns the new lock."""
    from propbench import envs

    env = envs.create(project)
    return {"lock": envs.install(env, list(packages))}


def env_sync(project: str, lock: str) -> dict[str, Any]:
    """Recreate the project's environment from a lock stored with the project."""
    from propbench import envs

    env = envs.create(project)
    return {"lock": envs.sync(env, lock)}


def env_run(
    project: str,
    code: str,
    timeout: float = 600.0,
    memory_mb: int = 4096,
    datasets: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run a script in the project's environment (separate process, time and memory limits). ``datasets`` (the
    open project's) are given to the script: ``propbench.datasets()`` returns them."""
    from propbench import envs
    from propbench.script import ENV_DATASETS

    env = envs.create(project)
    files, extra = {}, {}
    if datasets:
        files["project_datasets.json"] = json.dumps({"datasets": list(datasets)})
        extra[ENV_DATASETS] = "{dir}/project_datasets.json"  # "/" works on every OS
    result = envs.run(env, code, timeout=float(timeout), memory_mb=int(memory_mb), files=files, extra_env=extra)
    return result.as_dict()


__all__ = [
    "assistant_ask",
    "assistant_providers",
    "components_datasets",
    "components_install",
    "components_install_file",
    "components_list",
    "components_remove",
    "consistency_analyze",
    "curvefit_fit",
    "curvefit_ftest",
    "dataset_check",
    "dataset_import",
    "dataset_preview",
    "env_create",
    "env_install",
    "env_run",
    "env_status",
    "env_sync",
    "figure_presets",
    "figure_render",
    "fluids",
    "github_device_poll",
    "github_device_start",
    "github_push",
    "gum_linear",
    "gum_montecarlo",
    "jsonable",
    "model_compare",
    "model_default",
    "model_export_coolprop",
    "model_fit",
    "model_kinds",
    "model_predict",
    "model_references",
    "plugins_run",
    "properties",
    "refs_doi",
    "refs_format",
    "refs_parse",
    "report_render",
    "selection_lock",
    "selection_select",
    "study_validate",
    "worksheet_compute",
]
