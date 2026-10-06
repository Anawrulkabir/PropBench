"""PropBench project files (``.pbp``) from Python: the same SQLite format the app and ``propbench project`` write
(``crates/pb-store``, README §4).

A project is a plain dict::

    {"meta": {"name", "created", "modified", "app_version", "schema_version"},
     "datasets": [{"name", "data"}], "documents": {key: value},
     "snapshots": [{"id", "label", "created", "datasets", "documents"}],
     "audit": [{"time", "action", "detail"}]}

``data`` of a dataset is the worker's dataset JSON (SI units), so ``datasets(project)`` gives ``Dataset`` objects.
Saves are atomic (temporary file next to the target, then ``os.replace``).
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

FORMAT = "propbench-project"
APPLICATION_ID = 0x5042504A
SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE datasets (
    position INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    fluid TEXT NOT NULL,
    quantity TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE documents (key TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE snapshots (id INTEGER PRIMARY KEY, label TEXT NOT NULL, created INTEGER NOT NULL, data TEXT NOT NULL);
CREATE TABLE audit (id INTEGER PRIMARY KEY, time INTEGER NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
"""


class ProjectError(ValueError):
    """A file is not a PropBench project, is too new for this version, or the content is invalid."""


def new(name: str = "Untitled project") -> dict[str, Any]:
    now = int(time.time())
    meta = {"name": name, "created": now, "modified": now, "app_version": "", "schema_version": SCHEMA_VERSION}
    return {"meta": meta, "datasets": [], "documents": {}, "snapshots": [], "audit": []}


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _dataset_row(position: int, record: Mapping[str, Any]) -> tuple[int, str, str, str, str]:
    data = record["data"]
    return position, record["name"], str(data.get("fluid", "")), str(data.get("quantity", "")), _dumps(data)


def save(path: str | os.PathLike[str], project: Mapping[str, Any]) -> None:
    """Write ``project`` to ``path`` atomically."""
    target = Path(path)
    names = [d["name"] for d in project.get("datasets", [])]
    if any(not str(n).strip() for n in names) or len(set(names)) != len(names):
        raise ProjectError("dataset names must be unique and non-empty")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)
    meta = project["meta"]
    try:
        with closing(sqlite3.connect(tmp)) as conn:
            conn.executescript(_SCHEMA_V1)
            conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            rows = [
                ("format", FORMAT),
                ("name", str(meta.get("name", ""))),
                ("created", str(int(meta.get("created", 0)))),
                ("modified", str(int(meta.get("modified", 0)))),
                ("app_version", str(meta.get("app_version", ""))),
            ]
            conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", rows)
            conn.executemany(
                "INSERT INTO datasets (position, name, fluid, quantity, data) VALUES (?, ?, ?, ?, ?)",
                [_dataset_row(i, d) for i, d in enumerate(project.get("datasets", []))],
            )
            conn.executemany(
                "INSERT INTO documents (key, data) VALUES (?, ?)",
                [(k, _dumps(v)) for k, v in project.get("documents", {}).items()],
            )
            conn.executemany(
                "INSERT INTO snapshots (id, label, created, data) VALUES (?, ?, ?, ?)",
                [
                    (s["id"], s["label"], s["created"], _dumps({k: s[k] for k in ("datasets", "documents")}))
                    for s in project.get("snapshots", [])
                ],
            )
            conn.executemany(
                "INSERT INTO audit (time, action, detail) VALUES (?, ?, ?)",
                [(a["time"], a["action"], a["detail"]) for a in project.get("audit", [])],
            )
            conn.commit()
        with open(tmp, "rb") as f:
            os.fsync(f.fileno())
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def load(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read a project file (schema 1). Foreign files and files of a newer PropBench are refused."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    try:
        conn = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ProjectError(f"{source}: not a PropBench project file") from exc
    with closing(conn):
        try:
            app_id = conn.execute("PRAGMA application_id").fetchone()[0]
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            raise ProjectError(f"{source}: not a PropBench project file") from exc
        if app_id != APPLICATION_ID or version < 1:
            raise ProjectError(f"{source}: not a PropBench project file")
        if version > SCHEMA_VERSION:
            raise ProjectError(f"{source}: made by a newer PropBench (format {version}, this reads {SCHEMA_VERSION})")
        meta_rows = dict(conn.execute("SELECT key, value FROM meta"))
        if meta_rows.get("format") != FORMAT:
            raise ProjectError(f"{source}: not a PropBench project file")
        meta = {
            "name": meta_rows.get("name", ""),
            "created": int(meta_rows["created"]),
            "modified": int(meta_rows["modified"]),
            "app_version": meta_rows.get("app_version", ""),
            "schema_version": version,
        }
        datasets = [
            {"name": n, "data": json.loads(d)}
            for n, d in conn.execute("SELECT name, data FROM datasets ORDER BY position")
        ]
        documents = {k: json.loads(v) for k, v in conn.execute("SELECT key, data FROM documents")}
        snapshots = []
        for sid, label, created, data in conn.execute("SELECT id, label, created, data FROM snapshots ORDER BY id"):
            content = json.loads(data)
            snapshots.append({"id": sid, "label": label, "created": created, **content})
        audit = [
            {"time": t, "action": a, "detail": d}
            for t, a, d in conn.execute("SELECT time, action, detail FROM audit ORDER BY id")
        ]
    return {"meta": meta, "datasets": datasets, "documents": documents, "snapshots": snapshots, "audit": audit}


def datasets(project: Mapping[str, Any]) -> list[Any]:
    """The project's datasets as ``propbench.core.Dataset`` objects."""
    from propbench.core import Dataset

    return [Dataset.from_dict(dict(d["data"])) for d in project.get("datasets", [])]
