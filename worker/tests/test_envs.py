"""Project environments (M1c acceptance): a script that installs packages leaves the system Python and PATH
untouched; locks recreate environments; scripts run with time and memory limits. No network: packages come from
a wheel built here."""

import base64
import hashlib
import os
import site
import subprocess
import sys
import zipfile

import pytest

from propbench import envs


def make_wheel(folder, name="demo_pkg", version="1.0"):
    """A minimal pure-Python wheel (PEP 427) defining ``name.VALUE``."""
    dist = f"{name}-{version}"
    files = {
        f"{name}/__init__.py": f"VALUE = {version!r}\n",
        f"{dist}.dist-info/METADATA": f"Metadata-Version: 2.1\nName: {name.replace('_', '-')}\nVersion: {version}\n",
        f"{dist}.dist-info/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = []
    for path, text in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(text.encode()).digest()).rstrip(b"=").decode()
        record.append(f"{path},sha256={digest},{len(text.encode())}")
    record.append(f"{dist}.dist-info/RECORD,,")
    files[f"{dist}.dist-info/RECORD"] = "\n".join(record) + "\n"
    path = folder / f"{dist}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as z:
        for p, text in files.items():
            z.writestr(p, text)
    return path


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "appdata" / "envs"
    monkeypatch.setenv(envs.ENV_ROOT, str(r))
    return r


@pytest.fixture
def wheels(tmp_path):
    d = tmp_path / "wheels"
    d.mkdir()
    make_wheel(d, version="1.0")
    make_wheel(d, version="2.0")
    return str(d)


def importable_by_system_python(module):
    code = f"import importlib.util, sys; sys.exit(0 if importlib.util.find_spec({module!r}) else 1)"
    return subprocess.run([sys.executable, "-I", "-c", code], check=False).returncode == 0


def test_installing_packages_leaves_system_python_and_path_untouched(root, wheels):
    path_before = os.environ.get("PATH")
    user_site = site.getusersitepackages()
    user_site_before = sorted(os.listdir(user_site)) if os.path.isdir(user_site) else None
    env = envs.create("CF3I viscosity")
    assert env.path.parent == root, "environments live in the app data folder only"
    script = (
        "import subprocess, sys\n"
        "from uv import find_uv_bin\n"  # the core's uv, as a user's script would call it
        f"subprocess.run([find_uv_bin(), 'pip', 'install', '--offline', '--no-index', '--find-links', {wheels!r},"
        " '--python', sys.executable, 'demo-pkg==2.0'], check=True)\n"
        "import demo_pkg; print(demo_pkg.VALUE)\n"
    )
    result = envs.run(env, script, timeout=300)
    assert result.exit_code == 0, result.stderr
    assert result.stdout.strip() == "2.0"
    assert not importable_by_system_python("demo_pkg"), "the system (core) Python is untouched"
    assert os.environ.get("PATH") == path_before, "PATH of the session is untouched"
    if user_site_before is not None:
        assert sorted(os.listdir(user_site)) == user_site_before, "user site-packages untouched"
    assert "demo-pkg==2.0" in envs.lock(env)


def test_lock_recreates_the_environment(root, wheels):
    env = envs.create("a")
    lock = envs.install(env, ["demo-pkg==1.0"], find_links=[wheels], offline=True)
    assert "demo-pkg==1.0" in lock
    other = envs.create("b")
    assert "demo-pkg" not in envs.lock(other)
    envs.sync(other, lock, find_links=[wheels], offline=True)
    assert envs.lock(other) == lock
    result = envs.run(other, "import demo_pkg, propbench; print(demo_pkg.VALUE)")
    assert result.stdout.strip() == "1.0", "packages of the lock and the core are both importable"


def test_scripts_run_with_time_and_memory_limits(root):
    env = envs.create("limits")
    slow = envs.run(env, "import time; time.sleep(60)", timeout=1.0)
    assert slow.timed_out
    assert slow.seconds < 30
    big = envs.run(env, "x = bytearray(3 * 1024**3); print('allocated')", memory_mb=256, timeout=120)
    assert big.exit_code != 0
    assert "allocated" not in big.stdout
    assert big.memory_exceeded
    ok = envs.run(env, "import sys; print(sys.argv[1:]); raise SystemExit(3)", args=["x"])
    assert ok.stdout.strip() == "['x']"
    assert ok.exit_code == 3


def test_invalid_requests_are_refused(root):
    env = envs.create("x")
    with pytest.raises(envs.EnvError, match="invalid package"):
        envs.install(env, ["--index-url=https://evil.example"])
    with pytest.raises(envs.EnvError, match="invalid environment name"):
        envs.get("///")
    with pytest.raises(envs.EnvError, match="does not exist"):
        envs.run(envs.get("never-created"), "print(1)")


def test_scripts_get_the_open_projects_datasets_and_the_scripting_api(root):
    from propbench import api

    ds = {
        "schema_version": 1,
        "name": "d",
        "fluid": "R134a",
        "quantity": "viscosity",
        "temperature": [300.0, 320.0],
        "values": [2.0e-4, 1.8e-4],
        "pressure": [2e6, 2e6],
    }
    code = (
        "import propbench as pb\n"
        "data = pb.datasets()\n"
        "m = pb.model('lj_dilute_viscosity', 'R134a')\n"
        "print(len(data), data[0].name, 'lj_dilute_viscosity' in pb.model_kinds())\n"
    )
    out = api.env_run("scripting", code, timeout=120, datasets=[ds])
    assert out["exit_code"] == 0, out["stderr"]
    assert out["stdout"].split() == ["1", "d", "True"]
