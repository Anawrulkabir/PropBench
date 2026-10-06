"""Project files from Python: round trip, atomic save, refusal of foreign and newer files, datasets as objects."""

import sqlite3
from contextlib import closing

import numpy as np
import pytest

from propbench import project
from propbench.core import Dataset, Quantity


def sample():
    p = project.new("CF3I")
    ds = Dataset(
        "d1",
        "R13I1",
        Quantity.VISCOSITY,
        np.array([300.0, 310.0]),
        np.array([2e-4, 1.9e-4]),
        pressure=np.array([3e6, 3e6]),
    )
    p["datasets"].append({"name": "d1", "data": ds.to_dict()})
    p["documents"]["settings"] = {"seed": 2026, "methods": ["lostate"]}
    p["snapshots"].append({"id": 1, "label": "imported", "created": 1, "datasets": [], "documents": {}})
    p["audit"].append({"time": 1, "action": "import", "detail": "d1"})
    return p


def test_round_trip_and_datasets(tmp_path):
    path = tmp_path / "p.pbp"
    p = sample()
    project.save(path, p)
    back = project.load(path)
    assert back == p
    (ds,) = project.datasets(back)
    assert ds.name == "d1"
    np.testing.assert_array_equal(ds.values, [2e-4, 1.9e-4])
    assert not list(tmp_path.glob(".*.tmp"))


def test_invalid_content_leaves_existing_file(tmp_path):
    path = tmp_path / "p.pbp"
    project.save(path, sample())
    bad = sample()
    bad["datasets"].append(bad["datasets"][0])
    with pytest.raises(project.ProjectError, match="unique"):
        project.save(path, bad)
    assert len(project.load(path)["datasets"]) == 1


def test_foreign_and_newer_files_are_refused(tmp_path):
    text = tmp_path / "x.pbp"
    text.write_bytes(b"not a database at all, just some text")
    with pytest.raises(project.ProjectError, match="not a PropBench project"):
        project.load(text)
    newer = tmp_path / "n.pbp"
    project.save(newer, sample())
    with closing(sqlite3.connect(newer)) as conn:
        conn.execute(f"PRAGMA user_version = {project.SCHEMA_VERSION + 1}")
        conn.commit()
    with pytest.raises(project.ProjectError, match="newer PropBench"):
        project.load(newer)
    with pytest.raises(FileNotFoundError):
        project.load(tmp_path / "missing.pbp")
