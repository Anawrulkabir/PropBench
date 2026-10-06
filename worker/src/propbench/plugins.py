"""Python plug-ins (README §2f): run in the project environment, in a separate process, with the approved permissions.

The shell (``pb-plugin``) verifies a plug-in's signed package and the user's approval of its permissions, then sends
``plugins.run`` with the plug-in folder, the SHA-256 of its entry point and the approved permissions. Here the
plug-in runs in the project environment with the time and memory limits it declared; before its code is loaded a
guard (``sys.addaudithook``) refuses every file access outside the declared project folders (and the Python
installation), any network access unless declared, and starting processes or loading native libraries. The guard
enforces what a plug-in declared; it is not a security boundary against hostile code, which is why third-party
plug-ins should be WASM (CLAUDE.md plug-in rules).

A model plug-in's entry module defines ``MODEL`` (an object implementing ``propbench.models.Model``) or
``create()`` returning one. A tool plug-in defines ``run(params, context) -> JSON``. ``check(folder)`` is the
check-value harness of the SDK: the plug-in's own ``check_values()`` and the ``[[check]]`` values of its manifest.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import tomllib
import types
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from propbench.plugin_child import RESULT_MARK

API_VERSION = 1
MANIFEST = "plugin.toml"


class PluginError(ValueError):
    """A plug-in or a request to run one is invalid, or the plug-in failed."""


def load_manifest(folder: str | os.PathLike[str]) -> dict[str, Any]:
    """Read and check ``plugin.toml`` (the shell checks it fully; these are the fields this side relies on)."""
    path = Path(folder) / MANIFEST
    try:
        manifest = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PluginError(f"{path}: {exc}") from exc
    for key in ("id", "name", "version", "api", "kind", "runtime", "entry"):
        if key not in manifest:
            raise PluginError(f"{MANIFEST} needs {key!r}")
    if not isinstance(manifest["api"], int) or not 1 <= manifest["api"] <= API_VERSION:
        raise PluginError(
            f"{manifest['id']} needs plug-in API {manifest['api']} (this PropBench provides {API_VERSION})"
        )
    entry = Path(manifest["entry"])
    if entry.is_absolute() or ".." in entry.parts or entry.suffix not in (".py", ".wasm", ".wat"):
        raise PluginError(f"invalid entry {manifest['entry']!r}")
    for check in manifest.get("check", []):
        if not str(check.get("source", "")).strip():
            raise PluginError("every check value needs its published source")
    return manifest


def load_module(folder: str | os.PathLike[str], entry: str, *, sha256: str | None = None) -> types.ModuleType:
    """Execute the plug-in's entry file as a fresh module. The source is read once, checked against ``sha256`` (the
    hash the shell verified) and compiled from memory, so no cached bytecode is used."""
    folder = Path(folder)
    path = folder / entry
    source = path.read_bytes()
    if sha256 is not None and hashlib.sha256(source).hexdigest() != sha256:
        raise PluginError(f"{entry} changed after the package was verified")
    name = f"propbench_plugin_{abs(hash(str(path)))}"
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))  # helper modules next to the entry point
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def model_of(module: types.ModuleType) -> Any:
    model = getattr(module, "MODEL", None)
    if model is None and callable(getattr(module, "create", None)):
        model = module.create()
    if model is None or not callable(getattr(model, "predict", None)):
        raise PluginError("a model plug-in must define MODEL or create() returning a Model")
    return model


def harness(model: Any, manifest_checks: Sequence[Mapping[str, Any]] = ()) -> list[dict[str, Any]]:
    """Evaluate the model at its check values; relative deviation (model − expected)/expected within the tolerance."""
    checks = [
        {
            "temperature": float(c["temperature"]),
            "molar_density": float(c.get("molar_density", 0.0)),
            "expected": float(c["expected"]),
            "rel_tol": float(c["rel_tol"]),
            "source": str(c["source"]),
        }
        for c in manifest_checks
    ]
    for cv in getattr(model, "check_values", lambda: [])():
        checks.append(
            {
                "temperature": cv.temperature,
                "molar_density": cv.molar_density,
                "expected": cv.expected,
                "rel_tol": cv.rel_tol,
                "source": cv.source,
            }
        )
    if not checks:
        return []
    values = np.asarray(
        model.predict([c["temperature"] for c in checks], [c["molar_density"] for c in checks]), dtype=float
    )
    out = []
    for c, v in zip(checks, values, strict=True):
        dev = (float(v) - c["expected"]) / c["expected"]
        out.append({**c, "value": float(v), "rel_dev": dev, "pass": math.isfinite(dev) and abs(dev) <= c["rel_tol"]})
    return out


def check(folder: str | os.PathLike[str]) -> dict[str, Any]:
    """The SDK's check-value harness, in this process (for a plug-in's own tests): ``verified`` when every published
    check value is reproduced (and there is at least one)."""
    manifest = load_manifest(folder)
    if manifest["runtime"] != "python" or manifest["kind"] != "model":
        raise PluginError(f"{manifest['id']} is not a Python model plug-in")
    model = model_of(load_module(folder, manifest["entry"]))
    results = harness(model, manifest.get("check", []))
    return {"id": manifest["id"], "results": results, "verified": bool(results) and all(r["pass"] for r in results)}


# --- running in the project environment ---


def run(request: Mapping[str, Any], *, project: str) -> dict[str, Any]:
    """Run an approved Python plug-in (``request`` as prepared by the shell) in the project environment ``project``,
    with the time and memory limits it declared."""
    from propbench import envs

    for key in ("dir", "entry", "permissions"):
        if key not in request:
            raise PluginError(f"plug-in request needs {key!r}")
    perms = request["permissions"]
    env = envs.create(project)
    result = envs.run(
        env,
        (Path(__file__).parent / "plugin_child.py").read_text(encoding="utf-8"),
        timeout=float(perms.get("time_s", 60)),
        memory_mb=int(perms.get("memory_mb", 512)),
        files={"request.json": json.dumps(dict(request))},
    )
    if result.timed_out:
        raise PluginError(f"plug-in stopped at the time limit of {perms.get('time_s')} s")
    if result.memory_exceeded:
        raise PluginError(f"plug-in stopped at the memory limit of {perms.get('memory_mb')} MB")
    for line in reversed(result.stdout.splitlines()):
        if line.startswith(RESULT_MARK):
            answer = json.loads(line[len(RESULT_MARK) :])
            if "error" in answer:
                raise PluginError(answer["error"])
            return {
                "result": answer["ok"],
                "stdout": result.stdout.replace(line, "").strip(),
                "seconds": result.seconds,
            }
    raise PluginError(f"plug-in failed (exit code {result.exit_code}): {result.stderr.strip()[-2000:]}")
