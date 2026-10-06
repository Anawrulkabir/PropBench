"""Child process of a Python plug-in run (``propbench.plugins.run``): executed as a script in the project
environment, standard library only until the plug-in is loaded, so a tool plug-in starts quickly.

Reads ``request.json``, installs the permission guard (``sys.addaudithook``, permanent for the process), loads the
plug-in's verified entry point and prints the JSON result after a marker line.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import types
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

RESULT_MARK = "@@propbench-plugin-result@@"

_PROCESS_EVENTS = (
    "subprocess.Popen",
    "os.system",
    "os.exec",
    "os.posix_spawn",
    "os.spawn",
    "os.fork",
    "os.forkpty",
    "os.startfile",
    "pty.spawn",
    "ctypes.dlopen",
    "ctypes.dlsym",
    "ctypes.cdata",
    "_winapi.CreateProcess",
)
_NETWORK_EVENTS = (
    "socket.connect",
    "socket.bind",
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "socket.gethostbyaddr",
    "socket.sendto",
    "socket.sendmsg",
    "urllib.Request",
    "http.client.connect",
)
# read by the Python runtime and numerical libraries themselves (random seeds, CPU detection, time zones)
_SYSTEM_READ = (
    os.devnull,
    "/dev/urandom",
    "/dev/random",
    "/proc/self",
    "/proc/cpuinfo",
    "/proc/meminfo",
    "/sys/devices/system/cpu",
    "/sys/fs/cgroup",
    "/etc/localtime",
    "/usr/share/zoneinfo",
)
_READ_EVENTS = {"os.listdir": 0, "os.scandir": 0, "glob.glob": 0}
_WRITE_EVENTS = {
    "os.remove": 0,
    "os.rmdir": 0,
    "os.mkdir": 0,
    "os.rename": (0, 1),
    "os.replace": (0, 1),
    "os.chmod": 0,
    "os.chown": 0,
    "os.truncate": 0,
    "os.symlink": (0, 1),
    "os.link": (0, 1),
    "os.utime": 0,
    "shutil.rmtree": 0,
    "shutil.copyfile": 1,
    "shutil.move": (0, 1),
}


def _inside(path: str, roots: Sequence[str]) -> bool:
    path = os.path.normcase(path)
    for root in roots:
        r = os.path.normcase(root).rstrip(os.sep)
        if path == r or path.startswith(r + os.sep):
            return True
    return False


def _folders(request: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    perms = request.get("permissions") or {}
    project = request.get("project_dir")
    folders = {"read": [], "write": []}
    for kind in folders:
        for f in perms.get(kind, []):
            p = Path(f)
            if p.is_absolute() or ".." in p.parts or not project:
                raise PermissionError(f"invalid {kind} folder {f!r}")
            path = Path(project) / p
            if kind == "write":
                path.mkdir(parents=True, exist_ok=True)
            folders[kind].append(os.path.realpath(path))
    return folders["read"], folders["write"]


def _guard(request: Mapping[str, Any]) -> None:
    """Install the permission guard for the rest of this process (it cannot be removed)."""
    import site
    import sysconfig

    read, write = _folders(request)
    network = bool((request.get("permissions") or {}).get("network", False))
    python_dirs = {
        sys.prefix,
        sys.base_prefix,
        sys.exec_prefix,
        *site.getsitepackages(),
        *sysconfig.get_paths().values(),
    }
    python_dirs |= {p for p in sys.path if p and Path(p).is_dir()}
    system = [p for p in _SYSTEM_READ if os.path.exists(p)]
    readable = sorted({os.path.realpath(p) for p in [*python_dirs, *system, str(request["dir"]), *read, *write]})
    readable = [p for p in readable if Path(p).parent != Path(p)]  # never a whole drive
    writable = list(write)
    pid = str(request.get("id", "plug-in"))

    def deny(what: str) -> None:
        raise PermissionError(f"plug-in {pid}: {what} is not declared in its plugin.toml")

    def check_path(path: Any, writing: bool) -> None:
        if isinstance(path, int) or path is None:
            return
        real = os.path.realpath(os.fsdecode(path))
        if not _inside(real, writable if writing else readable):
            deny(f"{'writing' if writing else 'reading'} {real}")

    def hook(event: str, args: tuple[Any, ...]) -> None:
        if event == "open":
            path, mode, flags = (*tuple(args), None, None, None)[:3]
            writing = bool(mode and any(c in str(mode) for c in "wax+")) or bool(
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC)
            )
            check_path(path, writing)
        elif event in _READ_EVENTS:
            check_path(args[0] if args else None, False)
        elif event in _WRITE_EVENTS:
            idx = _WRITE_EVENTS[event]
            for i in idx if isinstance(idx, tuple) else (idx,):
                if i < len(args):
                    check_path(args[i], True)
        elif event.startswith(_PROCESS_EVENTS):
            deny("starting processes or loading native libraries")
        elif not network and event.startswith(_NETWORK_EVENTS):
            deny("network access")

    sys.addaudithook(hook)


def _load(folder: Path, entry: str, sha256: str | None) -> types.ModuleType:
    """The entry file as a fresh module, compiled from the bytes checked against the verified hash."""
    path = folder / entry
    source = path.read_bytes()
    if sha256 is not None and hashlib.sha256(source).hexdigest() != sha256:
        raise ValueError(f"{entry} changed after the package was verified")
    module = types.ModuleType("propbench_plugin")
    module.__file__ = str(path)
    sys.modules[module.__name__] = module
    sys.path.insert(0, str(folder))
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def _serve(request: Mapping[str, Any]) -> Any:
    folder, entry = Path(request["dir"]), str(request["entry"])
    module = _load(folder, entry, request.get("entry_sha256"))
    method, params = request.get("method", "predict"), request.get("params") or {}
    if method == "run":
        run = getattr(module, "run", None)
        if not callable(run):
            raise ValueError("a tool plug-in must define run(params, context)")
        read, write = _folders(request)
        return run(params, {"project_dir": request.get("project_dir"), "read": read, "write": write})
    from propbench.plugins import harness, load_manifest, model_of  # model plug-ins use propbench anyway

    if method == "predict":
        model = model_of(module)
        if params.get("parameters"):
            model = model.with_params(params["parameters"])
        values = model.predict(params["temperature"], params["molar_density"])
        return {"values": [float(v) for v in values]}
    if method == "check":
        manifest = load_manifest(folder)
        results = harness(model_of(module), manifest.get("check", []))
        return {"results": results, "verified": bool(results) and all(r["pass"] for r in results)}
    if method == "info":
        model = model_of(module)
        return {
            "name": getattr(model, "name", ""),
            "fluid": getattr(model, "fluid", ""),
            "reference": model.reference() if callable(getattr(model, "reference", None)) else "",
            "params": {k: p.value for k, p in model.params().items()}
            if callable(getattr(model, "params", None))
            else {},
        }
    raise ValueError(f"unknown plug-in method {method!r}")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "tolist"):  # NumPy arrays and scalars
        return _jsonable(value.tolist())
    return value


def main() -> None:
    sys.dont_write_bytecode = True
    sys.pycache_prefix = os.path.join(os.getcwd(), "pycache")  # never the plug-in's own __pycache__ (not signed)
    with open("request.json", encoding="utf-8") as f:
        request = json.load(f)
    if request.get("method", "predict") != "run":
        # model plug-ins use the core packages: load them (and the native libraries their wheels load, e.g. with
        # ctypes on Windows) before the guard, which then applies to the plug-in's own code
        import numpy  # noqa: F401

        import propbench.models
        import propbench.plugins  # noqa: F401
    _guard(request)
    try:
        result: dict[str, Any] = {"ok": _serve(request)}
    except Exception as exc:  # reported to the caller
        result = {"error": f"{type(exc).__name__}: {exc}"}
    print(RESULT_MARK + json.dumps(_jsonable(result)))


if __name__ == "__main__":
    main()
