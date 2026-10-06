"""Components (README §2b): optional parts of PropBench installed on demand into the app data folder.

A registry is a JSON index (``registry.json``) of components; each entry names a zip archive by URL (absolute, or
relative to the registry), its size and SHA-256. Installing downloads the archive (``https``, ``http`` or
``file``), checks size and checksum before anything is unpacked, refuses unsafe paths in the archive, unpacks it
into a temporary folder and renames that into place, so a component is either completely installed or not at all.
Offline installation takes the same archive from a file: it carries its own ``component.json``.

Kinds:
* ``parameters``: published model parameters (``pcsaft.json``: fluid → {m, sigma, epsilon_k, molar_mass, reference})
* ``reference-models``: published reference models with check values (``reference_models.json``)
* ``data``: published experimental datasets (``datasets.json``: worker dataset JSON with DOI and citation)
* ``python``: pure-Python packages (``site/`` is added to the worker's import path); never the core environment

Everything is written below ``root`` (the components folder in the app data folder); nothing else is touched.
Only standard-library code is used (urllib, hashlib, zipfile).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

REGISTRY_SCHEMA = 1
KINDS = ("parameters", "reference-models", "data", "python")
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
ENV_ROOT = "PB_COMPONENTS_DIR"


class ComponentError(ValueError):
    """A registry, archive or installation request is invalid, or a download failed its checks."""


@dataclass(frozen=True)
class Component:
    id: str
    name: str
    version: str
    kind: str
    description: str = ""
    license: str = ""
    source: str = ""
    url: str = ""
    size: int = 0
    sha256: str = ""
    requires: tuple[str, ...] = ()
    category: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Component:
        try:
            cid, kind = str(d["id"]), str(d["kind"])
            version = str(d["version"])
        except KeyError as exc:
            raise ComponentError(f"component entry is missing {exc}") from None
        if not cid or "/" in cid or "\\" in cid or cid.startswith("."):
            raise ComponentError(f"invalid component id {cid!r}")
        if kind not in KINDS:
            raise ComponentError(f"component {cid}: unknown kind {kind!r} (known: {', '.join(KINDS)})")
        known = {f for f in cls.__dataclass_fields__ if f != "extra"}
        return cls(
            id=cid,
            name=str(d.get("name", cid)),
            version=version,
            kind=kind,
            description=str(d.get("description", "")),
            license=str(d.get("license", "")),
            source=str(d.get("source", "")),
            url=str(d.get("url", "")),
            size=int(d.get("size", 0)),
            sha256=str(d.get("sha256", "")).lower(),
            requires=tuple(str(r) for r in d.get("requires", ())),
            category=str(d.get("category", "")),
            extra={k: v for k, v in d.items() if k not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["requires"] = list(self.requires)
        extra = d.pop("extra")
        return {**extra, **d}


def version_key(version: str) -> tuple[Any, ...]:
    """Order versions like 1.2.10 > 1.2.9; non-numeric parts compare as text after numbers."""
    parts: list[tuple[int, Any]] = []
    for p in version.replace("-", ".").split("."):
        parts.append((0, int(p)) if p.isdigit() else (1, p))
    return tuple(parts)


def default_root() -> Path:
    """The components folder given by the shell (``PB_COMPONENTS_DIR``)."""
    root = os.environ.get(ENV_ROOT)
    if not root:
        raise ComponentError("no components folder configured (the app sets PB_COMPONENTS_DIR)")
    return Path(root)


# --- registry ---


def _fetch(url: str, max_bytes: int = MAX_ARCHIVE_BYTES, timeout: float = 60.0) -> bytes:
    scheme = urllib.parse.urlparse(url).scheme
    if scheme not in ("https", "http", "file"):
        raise ComponentError(f"unsupported URL {url!r} (https, http or file)")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
    except OSError as exc:
        raise ComponentError(f"download of {url} failed: {exc}") from exc
    if len(data) > max_bytes:
        raise ComponentError(f"{url} is larger than {max_bytes} bytes")
    return data


def _as_url(location: str) -> str:
    """A registry location as URL: plain paths become file URLs."""
    scheme = urllib.parse.urlparse(location).scheme
    if len(scheme) > 1:  # a URL (one letter is a Windows drive, e.g. C:\\registry.json)
        return location
    return Path(location).resolve().as_uri()


def load_registry(location: str) -> list[Component]:
    """Components listed by the registry at ``location`` (URL or path); archive URLs are made absolute."""
    url = _as_url(location)
    try:
        index = json.loads(_fetch(url, max_bytes=16 * 1024 * 1024).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ComponentError(f"{location}: not a component registry ({exc})") from exc
    if not isinstance(index, dict) or index.get("schema") != REGISTRY_SCHEMA:
        raise ComponentError(f"{location}: unsupported registry (expected schema {REGISTRY_SCHEMA})")
    out = []
    for entry in index.get("components", []):
        c = Component.from_dict(entry)
        if not c.url or len(c.sha256) != 64:
            raise ComponentError(f"registry entry {c.id}: needs a url and a SHA-256")
        out.append(Component(**{**asdict(c), "url": urllib.parse.urljoin(url, c.url), "requires": c.requires}))
    return out


# --- installed components ---


def _manifest_path(root: Path) -> Path:
    return root / "installed.json"


def installed(root: Path | None = None) -> dict[str, Component]:
    root = root or default_root()
    path = _manifest_path(root)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {cid: Component.from_dict(d) for cid, d in data.get("components", {}).items()}


def _write_manifest(root: Path, components: Mapping[str, Component]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"schema": 1, "components": {k: v.to_dict() for k, v in sorted(components.items())}}, indent=1)
    tmp = root / f".installed.{os.getpid()}.tmp"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, _manifest_path(root))


def component_dir(root: Path, component: Component) -> Path:
    return root / component.id / component.version


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    total = 0
    for m in members:
        p = PurePosixPath(m.filename)
        if p.is_absolute() or ".." in p.parts or "\\" in m.filename or (p.parts and ":" in p.parts[0]):
            raise ComponentError(f"unsafe path in archive: {m.filename!r}")
        total += m.file_size
    if total > 4 * MAX_ARCHIVE_BYTES:
        raise ComponentError("archive expands to more than the allowed size")
    return members


def _unpack(data: bytes, expected: Component | None, root: Path) -> Component:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ComponentError(f"not a component archive: {exc}") from exc
    with archive:
        members = _safe_members(archive)
        try:
            meta = json.loads(archive.read("component.json").decode("utf-8"))
        except KeyError:
            raise ComponentError("archive has no component.json") from None
        component = Component.from_dict(meta)
        if expected is not None and (component.id, component.version) != (expected.id, expected.version):
            raise ComponentError(
                f"archive holds {component.id} {component.version}, registry says {expected.id} {expected.version}"
            )
        target = component_dir(root, component)
        root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{component.id}-", dir=root))
        try:
            for m in members:
                archive.extract(m, staging)
            if target.exists():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, target)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    info = expected or component
    return Component(**{**asdict(component), "url": info.url, "sha256": info.sha256, "size": len(data)})


def install(component_id: str, registry: list[Component], root: Path | None = None) -> list[Component]:
    """Install a component and the components it requires (newest registry versions). Returns what was installed
    (already installed components with the same version are skipped)."""
    root = root or default_root()
    by_id: dict[str, Component] = {}
    for c in registry:
        if c.id not in by_id or version_key(c.version) > version_key(by_id[c.id].version):
            by_id[c.id] = c
    order: list[Component] = []

    def visit(cid: str, chain: tuple[str, ...]) -> None:
        if cid in chain:
            raise ComponentError(f"circular requirement: {' → '.join((*chain, cid))}")
        if cid not in by_id:
            raise ComponentError(f"component {cid!r} is not in the registry")
        c = by_id[cid]
        for req in c.requires:
            visit(req, (*chain, cid))
        if c not in order:
            order.append(c)

    visit(component_id, ())
    current = installed(root)
    done = []
    for c in order:
        have = current.get(c.id)
        if have is not None and have.version == c.version:
            continue
        data = _fetch(c.url)
        if c.size and len(data) != c.size:
            raise ComponentError(f"{c.id}: downloaded {len(data)} bytes, registry says {c.size}")
        digest = hashlib.sha256(data).hexdigest()
        if digest != c.sha256:
            raise ComponentError(f"{c.id}: checksum mismatch (got {digest[:12]}…, expected {c.sha256[:12]}…)")
        new = _unpack(data, c, root)
        if have is not None and have.version != new.version:
            shutil.rmtree(component_dir(root, have), ignore_errors=True)
        current[new.id] = new
        _write_manifest(root, current)
        done.append(new)
    return done


def install_file(path_or_bytes: str | os.PathLike[str] | bytes, root: Path | None = None) -> Component:
    """Offline installation from a component archive (its ``component.json`` describes it)."""
    root = root or default_root()
    data = path_or_bytes if isinstance(path_or_bytes, bytes) else Path(path_or_bytes).read_bytes()
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ComponentError("archive is too large")
    current = installed(root)
    new = _unpack(data, None, root)
    new = Component(**{**asdict(new), "sha256": hashlib.sha256(data).hexdigest(), "url": "file"})
    old = current.get(new.id)
    if old is not None and old.version != new.version:
        shutil.rmtree(component_dir(root, old), ignore_errors=True)
    current[new.id] = new
    _write_manifest(root, current)
    return new


def remove(component_id: str, root: Path | None = None) -> None:
    """Remove an installed component. Components that require it must be removed first."""
    root = root or default_root()
    current = installed(root)
    if component_id not in current:
        raise ComponentError(f"component {component_id!r} is not installed")
    users = sorted(c.id for c in current.values() if component_id in c.requires)
    if users:
        raise ComponentError(f"{component_id} is required by {', '.join(users)}; remove those first")
    c = current.pop(component_id)
    _write_manifest(root, current)
    shutil.rmtree(root / c.id, ignore_errors=True)


def updates(registry: list[Component], root: Path | None = None) -> list[Component]:
    """Registry components newer than the installed versions."""
    current = installed(root)
    newest: dict[str, Component] = {}
    for c in registry:
        newer = c.id in current and version_key(c.version) > version_key(current[c.id].version)
        if newer and (c.id not in newest or version_key(c.version) > version_key(newest[c.id].version)):
            newest[c.id] = c
    return sorted(newest.values(), key=lambda c: c.id)


# --- using installed components ---


def files(kind: str, name: str, root: Path | None = None) -> list[Path]:
    """Files called ``name`` in every installed component of ``kind``."""
    try:
        root = root or default_root()
    except ComponentError:
        return []
    return [p for c in installed(root).values() if c.kind == kind and (p := component_dir(root, c) / name).is_file()]


def activate_python(root: Path | None = None) -> list[str]:
    """Add the ``site`` folders of installed python components to ``sys.path`` (the worker calls this at start)."""
    added = []
    for c in installed(root).values() if (root or os.environ.get(ENV_ROOT)) else []:
        if c.kind == "python":
            site = component_dir(root or default_root(), c) / "site"
            if site.is_dir() and str(site) not in sys.path:
                sys.path.append(str(site))
                added.append(str(site))
    return added


def build_archive(directory: str | os.PathLike[str], out: str | os.PathLike[str]) -> dict[str, Any]:
    """Zip a component folder (with its ``component.json``) and return its registry entry (size, SHA-256)."""
    src = Path(directory)
    meta = Component.from_dict(json.loads((src / "component.json").read_text(encoding="utf-8")))
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                info = zipfile.ZipInfo(p.relative_to(src).as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, p.read_bytes())  # fixed timestamps: the same folder gives the same archive
    data = target.read_bytes()
    return {**meta.to_dict(), "url": target.name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def decode_base64(content: str) -> bytes:
    try:
        return base64.b64decode(content, validate=True)
    except ValueError as exc:
        raise ComponentError(f"content is not base64: {exc}") from exc
