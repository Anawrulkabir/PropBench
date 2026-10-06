"""Project environments (README §2c, M1c): one Python environment per project, created and filled by uv.

Isolation (CLAUDE.md): environments live below ``PB_ENVS_DIR`` (the app data folder); uv's cache is kept there too,
uv never downloads Python (it uses the bundled one), never reads user or system configuration and never changes
PATH. The system Python, the user's site-packages and the PATH of the user's session are never touched: the
environment is activated only inside the processes PropBench starts.

An environment sees the core packages (propbench, numpy, CoolProp, ...) through a ``.pth`` file; packages
installed into the environment come first. ``lock`` records the exact installed versions (stored with the
project) and ``sync`` recreates them.

Scripts run in a separate process of the environment with a time limit and a memory limit: ``RLIMIT_AS`` on
Linux, a Job Object on Windows, and on macOS (where the kernel does not enforce address-space limits) the parent
polls the child's resident memory and stops it at the limit.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ENV_ROOT = "PB_ENVS_DIR"
MAX_OUTPUT = 1_000_000  # characters kept of stdout and of stderr


class EnvError(RuntimeError):
    """A project environment could not be created, changed or used."""


def envs_root() -> Path:
    root = os.environ.get(ENV_ROOT)
    if not root:
        raise EnvError("no environments folder configured (the app sets PB_ENVS_DIR)")
    return Path(root)


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not s:
        raise EnvError(f"invalid environment name {name!r}")
    return s[:64]


def uv_binary() -> str:
    try:
        from uv import find_uv_bin
    except ImportError as exc:  # pragma: no cover - uv is a core dependency
        raise EnvError("uv is not available in the core environment") from exc
    return find_uv_bin()


def _uv_env(root: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("UV_", "VIRTUAL_ENV", "CONDA", "PYTHON"))}
    env.update(
        {
            "UV_CACHE_DIR": str(root / ".uv-cache"),
            "UV_PYTHON_DOWNLOADS": "never",
            "UV_NO_CONFIG": "1",
            "UV_NO_MODIFY_PATH": "1",
            "UV_NO_PROGRESS": "1",
        }
    )
    return env


def _run_uv(root: Path, args: list[str], timeout: float = 600.0) -> str:
    try:
        done = subprocess.run(
            [uv_binary(), *args],
            capture_output=True,
            text=True,
            env=_uv_env(root),
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise EnvError(f"uv {args[0]} did not finish within {timeout:.0f} s") from exc
    if done.returncode != 0:
        raise EnvError(f"uv {' '.join(args[:2])} failed: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout


@dataclass(frozen=True)
class ProjectEnv:
    name: str
    path: Path

    @property
    def python(self) -> Path:
        if sys.platform == "win32":
            return self.path / "Scripts" / "python.exe"
        return self.path / "bin" / "python"

    @property
    def bin_dir(self) -> Path:
        return self.python.parent

    def exists(self) -> bool:
        return self.python.is_file()


def get(name: str, root: Path | None = None) -> ProjectEnv:
    root = root or envs_root()
    return ProjectEnv(slug(name), root / slug(name))


def create(name: str, root: Path | None = None) -> ProjectEnv:
    """Create (or reuse) the environment of project ``name``; it can import the core packages."""
    root = root or envs_root()
    env = get(name, root)
    if not env.exists():
        root.mkdir(parents=True, exist_ok=True)
        _run_uv(root, ["venv", "--quiet", "--python", sys.executable, str(env.path)])
    core = sorted({sysconfig.get_paths()["purelib"], sysconfig.get_paths()["platlib"]})
    site = _site_packages(env)
    # `import` lines of a .pth file run at start-up: addsitedir also processes the core's own .pth files
    lines = [f"import site; site.addsitedir({c!r})" for c in core]
    (site / "_propbench_core.pth").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env


def _site_packages(env: ProjectEnv) -> Path:
    if sys.platform == "win32":
        return env.path / "Lib" / "site-packages"
    found = sorted((env.path / "lib").glob("python3*/site-packages"))
    if not found:
        raise EnvError(f"{env.path}: no site-packages folder")
    return found[0]


def install(
    env: ProjectEnv,
    packages: list[str],
    *,
    find_links: list[str] | None = None,
    offline: bool = False,
    root: Path | None = None,
) -> str:
    """Install packages into the environment; returns the new lock. Never touches another environment."""
    if not env.exists():
        raise EnvError(f"environment {env.name} does not exist")
    bad = [p for p in packages if not re.fullmatch(r"[A-Za-z0-9_.\-\[\],<>=!~ ;:'\"*]+", p) or p.startswith("-")]
    if bad or not packages:
        raise EnvError(f"invalid package requirements: {bad or packages}")
    args = ["pip", "install", "--quiet", "--python", str(env.python)]
    for link in find_links or []:
        args += ["--find-links", link]
    if offline:
        args += ["--offline", "--no-index"]
    _run_uv(root or env.path.parent, [*args, *packages])
    return lock(env, root=root)


def lock(env: ProjectEnv, *, root: Path | None = None) -> str:
    """Exact versions installed in the environment (``name==version`` lines, sorted)."""
    out = _run_uv(root or env.path.parent, ["pip", "freeze", "--python", str(env.python)])
    lines = sorted({ln.strip() for ln in out.splitlines() if ln.strip() and not ln.startswith("#")}, key=str.lower)
    return "\n".join(lines) + ("\n" if lines else "")


def sync(
    env: ProjectEnv,
    lock_text: str,
    *,
    find_links: list[str] | None = None,
    offline: bool = False,
    root: Path | None = None,
) -> str:
    """Make the environment hold exactly the packages of ``lock_text`` (as stored with the project)."""
    root = root or env.path.parent
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        req = Path(tmp) / "requirements.lock"
        req.write_text(lock_text, encoding="utf-8")
        args = ["pip", "sync", "--quiet", "--python", str(env.python), str(req)]
        for link in find_links or []:
            args += ["--find-links", link]
        if offline:
            args += ["--offline", "--no-index"]
        _run_uv(root, args)
    create(env.name, root)  # pip sync removes unknown files' packages; the core .pth is kept or rewritten
    return lock(env, root=root)


def remove(env: ProjectEnv) -> None:
    shutil.rmtree(env.path, ignore_errors=True)


def activated(env: ProjectEnv, base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment variables of a process running inside ``env`` (only for that process)."""
    out = dict(base if base is not None else os.environ)
    for k in [k for k in out if k.upper() in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP")]:
        del out[k]
    path_key = next((k for k in out if k.upper() == "PATH"), "PATH")
    out[path_key] = os.pathsep.join([str(env.bin_dir), out.get(path_key, "")]).rstrip(os.pathsep)
    out["VIRTUAL_ENV"] = str(env.path)
    return out


# --- running scripts with limits ---

_BOOTSTRAP = r"""
import os, runpy, sys
limit = int(sys.argv[1])
if limit > 0 and sys.platform.startswith("linux"):
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
elif limit > 0 and sys.platform == "win32":
    import ctypes
    from ctypes import wintypes as w
    class IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]
    class BASIC(ctypes.Structure):
        _fields_ = [("a", ctypes.c_longlong), ("b", ctypes.c_longlong), ("LimitFlags", w.DWORD),
                    ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("e", w.DWORD), ("f", ctypes.c_size_t),
                    ("g", w.DWORD), ("h", w.DWORD)]
    class EXT(ctypes.Structure):
        _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("p", ctypes.c_size_t), ("q", ctypes.c_size_t)]
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = w.HANDLE
    k.GetCurrentProcess.restype = w.HANDLE
    job = k.CreateJobObjectW(None, None)
    info = EXT()
    info.Basic.LimitFlags = 0x100 | 0x2000  # JOB_OBJECT_LIMIT_PROCESS_MEMORY | KILL_ON_JOB_CLOSE
    info.ProcessMemoryLimit = limit
    k.SetInformationJobObject(w.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
    k.AssignProcessToJobObject(w.HANDLE(job), w.HANDLE(k.GetCurrentProcess()))
script = sys.argv[2]
sys.argv = [script, *sys.argv[3:]]
runpy.run_path(script, run_name="__main__")
"""


@dataclass(frozen=True)
class RunResult:
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    memory_exceeded: bool
    seconds: float

    def as_dict(self) -> dict[str, object]:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "memory_exceeded": self.memory_exceeded,
            "seconds": self.seconds,
        }


def _rss_bytes(pid: int) -> int:
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, check=False)
        return int(out.stdout.strip() or 0) * 1024
    except (OSError, ValueError):
        return 0


def run(
    env: ProjectEnv,
    code: str,
    *,
    cwd: Path | None = None,
    timeout: float = 600.0,
    memory_mb: int = 4096,
    args: list[str] | None = None,
    files: dict[str, str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> RunResult:
    """Run Python ``code`` as a script in ``env``, in a separate process, with time and memory limits.

    ``files`` are written next to the script (the working directory unless ``cwd`` is given); ``extra_env`` adds
    variables (``{dir}`` in a value is replaced by that folder)."""
    if not env.exists():
        raise EnvError(f"environment {env.name} does not exist")
    limit = max(0, int(memory_mb)) * 1024 * 1024
    with tempfile.TemporaryDirectory(dir=env.path) as tmp:
        script = Path(tmp) / "script.py"
        script.write_text(code, encoding="utf-8")
        boot = Path(tmp) / "_propbench_boot.py"
        boot.write_text(_BOOTSTRAP, encoding="utf-8")
        for name, text in (files or {}).items():
            if Path(name).name != name:
                raise EnvError(f"invalid file name {name!r}")
            (Path(tmp) / name).write_text(text, encoding="utf-8")
        out_path, err_path = Path(tmp) / ".out.txt", Path(tmp) / ".err.txt"
        process_env = activated(env)
        process_env.update({k: v.replace("{dir}", tmp) for k, v in (extra_env or {}).items()})
        start = time.monotonic()
        with open(out_path, "w", encoding="utf-8") as out, open(err_path, "w", encoding="utf-8") as err:
            proc = subprocess.Popen(
                [str(env.python), "-I", "-X", "utf8", str(boot), str(limit), str(script), *(args or [])],
                cwd=str(cwd or tmp),
                env=process_env,
                stdout=out,
                stderr=err,
                stdin=subprocess.DEVNULL,
                start_new_session=sys.platform != "win32",
            )
            timed_out = memory_exceeded = False
            while proc.poll() is None:
                if time.monotonic() - start > timeout:
                    timed_out = True
                    _kill(proc)
                    break
                if limit and sys.platform == "darwin" and _rss_bytes(proc.pid) > limit:
                    memory_exceeded = True
                    _kill(proc)
                    break
                time.sleep(0.05)
            code_ = proc.wait()
        seconds = time.monotonic() - start
        stdout = out_path.read_text(encoding="utf-8", errors="replace")[:MAX_OUTPUT]
        stderr = err_path.read_text(encoding="utf-8", errors="replace")[:MAX_OUTPUT]
    memory_exceeded = memory_exceeded or (code_ != 0 and "MemoryError" in stderr)
    return RunResult(stdout, stderr, None if timed_out else code_, timed_out, memory_exceeded, seconds)


def _kill(proc: subprocess.Popen[bytes]) -> None:
    try:
        if sys.platform != "win32":
            os.killpg(proc.pid, 9)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()
