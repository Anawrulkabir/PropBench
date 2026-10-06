"""Components: install/remove/update from a local registry (file URLs, no network), checksum and size checks,
unsafe archives, offline install, requirements, and use of installed parameters, data and reference models."""

import hashlib
import json
import zipfile

import pytest

from propbench import api, components
from propbench.components import ComponentError


def make_component(tmp_path, cid, version, kind="parameters", files=None, requires=()):
    src = tmp_path / "src" / f"{cid}-{version}"
    src.mkdir(parents=True)
    meta = {
        "id": cid,
        "name": cid.title(),
        "version": version,
        "kind": kind,
        "license": "CC-BY-4.0",
        "source": "test",
        "requires": list(requires),
    }
    (src / "component.json").write_text(json.dumps(meta))
    for name, content in (files or {}).items():
        (src / name).parent.mkdir(parents=True, exist_ok=True)
        (src / name).write_text(content)
    return components.build_archive(src, tmp_path / "registry" / f"{cid}-{version}.zip")


def write_registry(tmp_path, entries):
    path = tmp_path / "registry" / "registry.json"
    path.write_text(json.dumps({"schema": 1, "components": entries}))
    return str(path)


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "appdata" / "components"
    monkeypatch.setenv(components.ENV_ROOT, str(r))
    return r


PCSAFT = json.dumps({"TestFluid": {"m": 2.0, "sigma": 3.6, "epsilon_k": 208.0, "molar_mass": 44.1, "reference": "x"}})


def test_install_verify_remove(tmp_path, root):
    entry = make_component(tmp_path, "pcsaft-extra", "1.0.0", files={"pcsaft.json": PCSAFT})
    registry = components.load_registry(write_registry(tmp_path, [entry]))
    (done,) = components.install("pcsaft-extra", registry)
    assert done.version == "1.0.0"
    assert (root / "pcsaft-extra" / "1.0.0" / "pcsaft.json").is_file()
    assert set(components.installed()) == {"pcsaft-extra"}
    assert components.install("pcsaft-extra", registry) == []  # already installed: nothing to do
    components.remove("pcsaft-extra")
    assert components.installed() == {}
    assert not (root / "pcsaft-extra").exists()
    with pytest.raises(ComponentError, match="not installed"):
        components.remove("pcsaft-extra")


def test_checksum_and_size_mismatch_are_refused_before_unpacking(tmp_path, root):
    entry = make_component(tmp_path, "data-x", "1.0", kind="data", files={"datasets.json": '{"datasets": []}'})
    bad = {**entry, "sha256": hashlib.sha256(b"something else").hexdigest()}
    with pytest.raises(ComponentError, match="checksum mismatch"):
        components.install("data-x", components.load_registry(write_registry(tmp_path, [bad])))
    wrong_size = {**entry, "size": entry["size"] + 1}
    with pytest.raises(ComponentError, match="bytes"):
        components.install("data-x", components.load_registry(write_registry(tmp_path, [wrong_size])))
    assert components.installed() == {}
    assert not any(root.glob("data-x*")) if root.exists() else True


def test_update_replaces_the_old_version(tmp_path, root):
    old = make_component(tmp_path, "pcsaft-extra", "1.2.9", files={"pcsaft.json": PCSAFT})
    new = make_component(tmp_path, "pcsaft-extra", "1.2.10", files={"pcsaft.json": PCSAFT})
    components.install("pcsaft-extra", components.load_registry(write_registry(tmp_path, [old])))
    registry = components.load_registry(write_registry(tmp_path, [old, new]))
    assert [c.version for c in components.updates(registry)] == ["1.2.10"]
    components.install("pcsaft-extra", registry)
    assert components.installed()["pcsaft-extra"].version == "1.2.10"
    assert not (root / "pcsaft-extra" / "1.2.9").exists()
    assert components.updates(registry) == []


def test_requirements_are_installed_first_and_protect_removal(tmp_path, root):
    base = make_component(tmp_path, "base", "1.0", files={"pcsaft.json": PCSAFT})
    top = make_component(
        tmp_path, "top", "1.0", kind="data", files={"datasets.json": '{"datasets": []}'}, requires=["base"]
    )
    done = components.install("top", components.load_registry(write_registry(tmp_path, [top, base])))
    assert [c.id for c in done] == ["base", "top"]
    with pytest.raises(ComponentError, match="required by top"):
        components.remove("base")
    with pytest.raises(ComponentError, match="not in the registry"):
        components.install("missing", components.load_registry(write_registry(tmp_path, [top])))


def test_unsafe_archives_are_refused(tmp_path, root):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("component.json", json.dumps({"id": "evil", "version": "1", "kind": "data"}))
        z.writestr("../../outside.txt", "x")
    with pytest.raises(ComponentError, match="unsafe path"):
        components.install_file(evil)
    assert not (tmp_path / "outside.txt").exists()
    with pytest.raises(ComponentError, match="not a component archive"):
        components.install_file(b"not a zip")
    no_meta = tmp_path / "nometa.zip"
    with zipfile.ZipFile(no_meta, "w") as z:
        z.writestr("x.txt", "x")
    with pytest.raises(ComponentError, match=r"no component\.json"):
        components.install_file(no_meta)


def test_offline_install_and_archives_are_reproducible(tmp_path, root):
    entry = make_component(tmp_path, "pcsaft-extra", "2.0", files={"pcsaft.json": PCSAFT})
    archive = tmp_path / "registry" / "pcsaft-extra-2.0.zip"
    c = components.install_file(archive)
    assert c.sha256 == entry["sha256"]
    again = components.build_archive(tmp_path / "src" / "pcsaft-extra-2.0", tmp_path / "copy.zip")
    assert again["sha256"] == entry["sha256"], "the same folder always gives the same archive"


def test_registry_must_be_valid(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"schema": 99}))
    with pytest.raises(ComponentError, match="unsupported registry"):
        components.load_registry(str(path))
    path.write_text(json.dumps({"schema": 1, "components": [{"id": "x", "version": "1", "kind": "nope"}]}))
    with pytest.raises(ComponentError, match="unknown kind"):
        components.load_registry(str(path))
    with pytest.raises(ComponentError, match="unsupported URL"):
        components.load_registry("ftp://example.org/registry.json")


def test_installed_components_are_used(tmp_path, root):
    from propbench.backends.feos import available_parameters
    from propbench.models.reference import all_entries, load_registry

    dataset = {
        "schema_version": 1,
        "name": "pub",
        "fluid": "R134a",
        "quantity": "viscosity",
        "temperature": [300.0],
        "values": [1e-4],
        "pressure": [1e6],
        "provenance": {"doi": "10.0/x", "citation": "Someone 2020"},
    }
    bundled = json.loads(
        __import__("importlib.resources")
        .resources.files("propbench.models")
        .joinpath("reference_models.json")
        .read_text(encoding="utf-8")
    )
    good = bundled["models"][0]
    wrong = {**good, "id": "wrong-check", "check_values": [{**good["check_values"][0], "value": 1.0}]}
    renamed = {**good, "id": "copy-ok", "label": "Copy"}
    entries = [
        make_component(tmp_path, "params", "1", files={"pcsaft.json": PCSAFT}),
        make_component(
            tmp_path, "pubdata", "1", kind="data", files={"datasets.json": json.dumps({"datasets": [dataset]})}
        ),
        make_component(
            tmp_path,
            "refs",
            "1",
            kind="reference-models",
            files={"reference_models.json": json.dumps({**bundled, "models": [wrong, renamed]})},
        ),
    ]
    registry = write_registry(tmp_path, entries)
    for e in entries:
        api.components_install(e["id"], registry)
    assert "TestFluid" in available_parameters()
    (d,) = api.components_datasets()["datasets"]
    assert d["provenance"]["doi"] == "10.0/x"
    ids = {e.id for e in all_entries()}
    assert "copy-ok" in ids, "an entry that reproduces its check values is offered"
    assert "wrong-check" not in ids, "an entry that fails its check values is never offered"
    assert len(all_entries()) == len(load_registry()) + 1
    listing = api.components_list(registry)
    assert listing["registry_error"] is None
    assert {c["id"] for c in listing["installed"]} == {"params", "pubdata", "refs"}


def test_list_works_offline(root, tmp_path):
    listing = api.components_list(str(tmp_path / "missing" / "registry.json"))
    assert listing["available"] == []
    assert "failed" in listing["registry_error"]


def test_shipped_components_build_and_install(tmp_path, root):
    """The components in /components build into a registry whose archives install and load (no network)."""
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "components" / "build.py"
    spec = importlib.util.spec_from_file_location("component_build", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    reg = module.build(tmp_path / "dist")
    assert {c["id"] for c in reg["components"]} >= {"cf3i-viscosity-data"}
    api.components_install("cf3i-viscosity-data", str(tmp_path / "dist" / "registry.json"))
    datasets = api.components_datasets()["datasets"]
    assert sorted(len(d["values"]) for d in datasets) == [18, 21, 24]
    assert all(d["provenance"]["doi"] for d in datasets)
    again = module.build(tmp_path / "dist2")
    assert [c["sha256"] for c in again["components"]] == [c["sha256"] for c in reg["components"]], "reproducible"
