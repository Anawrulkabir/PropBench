"""Python plug-ins (README M4c): the template passes the check-value harness; plug-ins run in the project environment
with only their declared permissions."""

import hashlib
import json
from pathlib import Path

import pytest

from propbench import envs, plugins

TEMPLATE = Path(__file__).resolve().parents[2] / "plugins" / "templates" / "python-model"

TOOL = """
import os, socket, subprocess
def run(params, context):
    action, target = params["action"], params.get("path", "")
    if action == "read":
        with open(target, encoding="utf-8") as f:
            return f.read()
    if action == "write":
        with open(target, "w", encoding="utf-8") as f:
            f.write("written")
        return "ok"
    if action == "list":
        return sorted(os.listdir(target))
    if action == "net":
        socket.create_connection(("192.0.2.1", 80), timeout=1)
    if action == "proc":
        subprocess.run(["echo", "hi"])
    if action == "spin":
        while True:
            pass
    return context
"""


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv(envs.ENV_ROOT, str(tmp_path / "appdata" / "envs"))
    return tmp_path


def manifest(entry="plugin.py", kind="analysis", permissions=""):
    return (
        f'id = "demo"\nname = "Demo"\nversion = "1"\napi = 1\nkind = "{kind}"\nruntime = "python"\n'
        f'entry = "{entry}"\n[permissions]\ntime_s = 30\nmemory_mb = 2048\n{permissions}\n'
    )


def request(folder, project, permissions, method, params, entry="plugin.py"):
    """What the shell sends after verifying the package and its approval (pb-plugin python_request)."""
    source = (Path(folder) / entry).read_bytes()
    return {
        "dir": str(folder),
        "id": "demo",
        "entry": entry,
        "entry_sha256": hashlib.sha256(source).hexdigest(),
        "permissions": {"network": False, "gpu": False, "read": [], "write": [], "time_s": 30, "memory_mb": 2048}
        | permissions,
        "project_dir": str(project),
        "method": method,
        "params": params,
    }


def test_template_passes_the_check_value_harness():
    report = plugins.check(TEMPLATE)
    assert report["verified"], report["results"]
    assert {r["source"].split(", ")[-1] for r in report["results"]} == {"250 K", "300 K", "400 K"}


def test_template_runs_in_the_project_environment(root):
    req = request(TEMPLATE, root, {}, "predict", {"temperature": [273.15, 300.0], "molar_density": [0.0, 0.0]})
    out = plugins.run(req, project="plugin-test")
    assert out["result"]["values"][0] == pytest.approx(1.716e-5, rel=1e-12)
    checked = plugins.run({**req, "method": "check", "params": {}}, project="plugin-test")["result"]
    assert checked["verified"]
    assert len(checked["results"]) == 3
    fitted = plugins.run({**req, "params": {**req["params"], "parameters": {"S": 120.0}}}, project="plugin-test")[
        "result"
    ]["values"]
    assert fitted[1] != out["result"]["values"][1]


@pytest.fixture
def tool(root):
    folder = root / "plugin"
    folder.mkdir()
    (folder / "plugin.toml").write_text(manifest(), encoding="utf-8")
    (folder / "plugin.py").write_text(TOOL, encoding="utf-8")
    project = root / "project"
    (project / "data").mkdir(parents=True)
    (project / "data" / "in.txt").write_text("declared", encoding="utf-8")
    (project / "private.txt").write_text("project secret", encoding="utf-8")
    (root / "outside.txt").write_text("outside secret", encoding="utf-8")
    return folder, project


def run_tool(folder, project, permissions, **params):
    return plugins.run(request(folder, project, permissions, "run", params), project="plugin-test")["result"]


def test_python_plugin_reads_only_its_declared_folders(tool, root):
    folder, project = tool
    perms = {"read": ["data"]}
    assert run_tool(folder, project, perms, action="read", path=str(project / "data" / "in.txt")) == "declared"
    assert run_tool(folder, project, perms, action="list", path=str(project / "data")) == ["in.txt"]
    for target in [project / "private.txt", root / "outside.txt", project / "data" / ".." / "private.txt"]:
        with pytest.raises(plugins.PluginError, match="not declared"):
            run_tool(folder, project, perms, action="read", path=str(target))
    with pytest.raises(plugins.PluginError, match="not declared"):
        run_tool(folder, project, perms, action="list", path=str(project))
    with pytest.raises(plugins.PluginError, match="not declared"):
        run_tool(folder, project, perms, action="write", path=str(project / "data" / "new.txt"))
    assert not (project / "data" / "new.txt").exists()
    with pytest.raises(plugins.PluginError, match="not declared"):
        run_tool(folder, project, {}, action="read", path=str(project / "data" / "in.txt"))


def test_declared_writes_network_and_processes(tool):
    folder, project = tool
    assert run_tool(folder, project, {"write": ["out"]}, action="write", path=str(project / "out" / "r.txt")) == "ok"
    assert (project / "out" / "r.txt").read_text(encoding="utf-8") == "written"
    with pytest.raises(plugins.PluginError, match="network access is not declared"):
        run_tool(folder, project, {}, action="net")
    with pytest.raises(plugins.PluginError, match="starting processes"):
        run_tool(folder, project, {}, action="proc")
    ctx = run_tool(folder, project, {"write": ["out"]}, action="context")
    assert ctx["write"] == [str((project / "out").resolve())]


def test_changed_entry_point_and_time_limit(tool):
    folder, project = tool
    req = request(folder, project, {}, "run", {"action": "context"})
    (folder / "plugin.py").write_text(TOOL + "\nEVIL = 1\n", encoding="utf-8")
    with pytest.raises(plugins.PluginError, match="changed after the package was verified"):
        plugins.run(req, project="plugin-test")
    req = request(folder, project, {"time_s": 1}, "run", {"action": "spin"})
    with pytest.raises(plugins.PluginError, match="time limit"):
        plugins.run(req, project="plugin-test")


def test_manifest_checks(tmp_path):
    (tmp_path / "plugin.toml").write_text(manifest().replace("api = 1", "api = 9"), encoding="utf-8")
    with pytest.raises(plugins.PluginError, match="needs plug-in API 9"):
        plugins.load_manifest(tmp_path)
    (tmp_path / "plugin.toml").write_text(manifest(entry="../x.py"), encoding="utf-8")
    with pytest.raises(plugins.PluginError, match="invalid entry"):
        plugins.load_manifest(tmp_path)
    text = manifest() + '[[check]]\ntemperature = 300.0\nexpected = 1.0\nrel_tol = 0.1\nsource = ""\n'
    (tmp_path / "plugin.toml").write_text(text, encoding="utf-8")
    with pytest.raises(plugins.PluginError, match="published source"):
        plugins.load_manifest(tmp_path)


def test_plugins_are_distributed_as_components(tmp_path):
    from propbench import components

    src = tmp_path / "src"
    (src / "plugin").mkdir(parents=True)
    meta = {"id": "sutherland-air-py", "name": "Sutherland", "version": "1.0.0", "kind": "plugin"}
    (src / "component.json").write_text(json.dumps(meta), encoding="utf-8")
    for name in ("plugin.toml", "plugin.py"):
        (src / "plugin" / name).write_bytes((TEMPLATE / name).read_bytes())
    entry = components.build_archive(src, tmp_path / "out" / "plugin.zip")
    root = tmp_path / "components"
    c = components.install_file(tmp_path / "out" / "plugin.zip", root)
    assert c.kind == "plugin"
    assert entry["sha256"] == c.sha256
    installed = components.component_dir(root, c) / "plugin"
    assert plugins.load_manifest(installed)["id"] == "sutherland-air-py"
    # an archive without the package is refused
    (src / "plugin" / "plugin.toml").unlink()
    components.build_archive(src, tmp_path / "out" / "bad.zip")
    with pytest.raises(components.ComponentError, match=r"no plugin/plugin\.toml"):
        components.install_file(tmp_path / "out" / "bad.zip", root)
