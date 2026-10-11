"""Scripting API (README §2c): ``import propbench as pb`` in the project environment or any Python with PropBench.

    import propbench as pb
    data = pb.datasets()                       # the project's datasets when run from the app (masks applied)
    model = pb.model("ecs_viscosity", "R13I1", reference_fluid="R134a")
    result = pb.fit(model, data)
    print(result.values, result.deviations.aard)
    print(pb.validate(model, data, scheme="lostate", seed=2026)["pooled"])

Everything here is a thin layer over the same functions the GUI and the CLI use (CLAUDE.md rule 2).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from propbench.core import Dataset

ENV_DATASETS = "PB_DATASETS"
ENV_PROJECT = "PB_PROJECT_FILE"


def datasets(source: str | os.PathLike[str] | None = None) -> list[Dataset]:
    """Datasets of a project: from a ``.pbp`` file or a datasets JSON file, or (inside the app) the open project's."""
    path = Path(source) if source else None
    if path is None:
        env = os.environ.get(ENV_DATASETS) or os.environ.get(ENV_PROJECT)
        if not env:
            raise ValueError("no project: pass a .pbp file (run from the app to get the open project's datasets)")
        path = Path(env)
    if path.suffix == ".pbp":
        from propbench import project

        return project.datasets(project.load(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("datasets", []) if isinstance(data, dict) else data
    return [Dataset.from_dict(dict(d)) for d in items]


def open(path: str | os.PathLike[str]) -> dict[str, Any]:
    """The content of a project file (datasets, documents, snapshots, audit) as a dict."""
    from propbench import project

    return project.load(path)


def model(kind: str, fluid: str, reference_fluid: str | None = None, *, fixed: Mapping[str, bool] | None = None) -> Any:
    """A starting model of ``kind`` (see ``model_kinds``) for ``fluid``; ``fixed`` fixes or frees parameters."""
    from propbench.models.spec import default_model, set_fixed

    m = default_model(kind, fluid, reference_fluid)
    return set_fixed(m, fixed) if fixed else m


def model_kinds() -> list[str]:
    from propbench.models.spec import KINDS

    return list(KINDS)


def fit(model: Any, data: Sequence[Dataset], **options: Any) -> Any:
    """Weighted least-squares fit of the model's free parameters (``propbench.fit.fit`` options)."""
    from propbench.fit import fit as run_fit
    from propbench.fit import fit_data

    return run_fit(model, fit_data(list(data)), **options)


def validate(
    model: Any,
    data: Sequence[Dataset],
    scheme: str = "lostate",
    *,
    seed: int = 0,
    k: int = 5,
    n_bootstrap: int = 100,
    **options: Any,
) -> dict[str, Any]:
    """Cross-validation summary of ``model`` on ``data`` with one of the splits (lostate, loso, loto, kfold,
    bootstrap); deterministic for a given seed."""
    from propbench.fit import fit_data
    from propbench.validate import SPLITS, cross_validate

    fd = fit_data(list(data))
    if scheme not in SPLITS:
        raise ValueError(f"unknown scheme {scheme!r} (known: {', '.join(SPLITS)})")
    split = SPLITS[scheme]
    if scheme == "kfold":
        folds = split(fd, k=k, seed=seed)
    elif scheme == "bootstrap":
        folds = split(fd, n=n_bootstrap, seed=seed)
    else:
        folds = split(fd)
    cv = cross_validate(model, fd, folds, method=scheme, seed=seed, **options)
    return cv.summary(list(fd.dataset_names))
