"""Measured data: one dataset = one property of one fluid from one source (README §2, Data)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, replace
from enum import StrEnum
from typing import Any

import numpy as np

from propbench.core.units import Quantity

SCHEMA_VERSION = 1


class DatasetError(ValueError):
    """A dataset is inconsistent (lengths, non-finite or non-physical values)."""


class Phase(StrEnum):
    """Phase of a state point, from the source file or assigned from an equation of state."""

    LIQUID = "liquid"
    VAPOR = "vapor"
    SUPERCRITICAL = "supercritical"
    SUPERCRITICAL_LIQUID = "supercritical_liquid"
    SUPERCRITICAL_GAS = "supercritical_gas"
    TWO_PHASE = "two_phase"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Provenance:
    """Where the data come from (README §2: DOI, method, purity)."""

    doi: str | None = None
    citation: str | None = None
    method: str | None = None
    purity: str | None = None
    notes: str | None = None


@dataclass(frozen=True, eq=False)
class Dataset:
    """Values of one property of one fluid at a set of states. All arrays are SI and read-only.

    The state of each point is given by its temperature and its pressure and/or molar density. Saturation properties
    (e.g. vapour pressure) need temperature only. ``expanded_uncertainty`` is absolute, in the unit of ``values``, at
    coverage factor ``coverage_factor``.
    """

    name: str
    fluid: str
    quantity: Quantity
    temperature: np.ndarray
    values: np.ndarray
    pressure: np.ndarray | None = None
    molar_density: np.ndarray | None = None
    expanded_uncertainty: np.ndarray | None = None
    coverage_factor: float = 2.0
    phase: tuple[Phase, ...] | None = None
    point_ids: np.ndarray = field(default=None)  # type: ignore[assignment]  # filled in __post_init__
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        n = _length(self.temperature)
        arrays = {
            "temperature": self.temperature,
            "values": self.values,
            "pressure": self.pressure,
            "molar_density": self.molar_density,
            "expanded_uncertainty": self.expanded_uncertainty,
        }
        for key, array in arrays.items():
            if array is None:
                continue
            frozen = _frozen_float_array(array, key)
            if len(frozen) != n:
                raise DatasetError(f"{key} has {len(frozen)} values, temperature has {n}")
            object.__setattr__(self, key, frozen)
        if not self.name.strip():
            raise DatasetError("a dataset needs a name")
        if n == 0:
            raise DatasetError("a dataset needs at least one point")
        if np.any(self.temperature <= 0):
            raise DatasetError("temperatures must be positive (K)")
        if self.pressure is not None and np.any(self.pressure <= 0):
            raise DatasetError("pressures must be positive (Pa)")
        if self.molar_density is not None and np.any(self.molar_density <= 0):
            raise DatasetError("molar densities must be positive (mol/m³)")
        if self.expanded_uncertainty is not None and np.any(self.expanded_uncertainty < 0):
            raise DatasetError("uncertainties must not be negative")
        if self.pressure is None and self.molar_density is None and self.quantity is not Quantity.VAPOR_PRESSURE:
            raise DatasetError(f"{self.quantity.value} data need pressure or molar density to define the state")
        if not (self.coverage_factor > 0 and np.isfinite(self.coverage_factor)):
            raise DatasetError("the coverage factor must be a positive number")
        if self.phase is not None:
            phases = tuple(Phase(p) for p in self.phase)
            if len(phases) != n:
                raise DatasetError(f"phase has {len(phases)} entries, temperature has {n}")
            object.__setattr__(self, "phase", phases)
        ids = np.arange(n) if self.point_ids is None else np.asarray(self.point_ids)
        if ids.shape != (n,) or not np.issubdtype(ids.dtype, np.integer) or len(np.unique(ids)) != n:
            raise DatasetError("point_ids must be n unique integers")
        ids = ids.astype(np.int64)
        ids.flags.writeable = False
        object.__setattr__(self, "point_ids", ids)

    def __len__(self) -> int:
        return len(self.temperature)

    @property
    def relative_uncertainty(self) -> np.ndarray | None:
        """Expanded uncertainty divided by the value (same coverage factor)."""
        if self.expanded_uncertainty is None:
            return None
        return self.expanded_uncertainty / np.abs(self.values)

    @property
    def standard_uncertainty(self) -> np.ndarray | None:
        """Absolute standard uncertainty u = U / k."""
        if self.expanded_uncertainty is None:
            return None
        return self.expanded_uncertainty / self.coverage_factor

    def select(self, mask: np.typing.ArrayLike) -> Dataset:
        """A new dataset with the points where ``mask`` is true (or with the given indices). Point ids are kept."""
        index = np.asarray(mask)
        if index.dtype == bool and index.shape != (len(self),):
            raise DatasetError(f"mask has shape {index.shape}, dataset has {len(self)} points")
        return replace(
            self,
            temperature=self.temperature[index],
            values=self.values[index],
            pressure=None if self.pressure is None else self.pressure[index],
            molar_density=None if self.molar_density is None else self.molar_density[index],
            expanded_uncertainty=None if self.expanded_uncertainty is None else self.expanded_uncertainty[index],
            phase=None if self.phase is None else tuple(np.asarray(self.phase, dtype=object)[index]),
            point_ids=self.point_ids[index],
        )

    def with_phase(self, phase: tuple[Phase, ...] | list[Phase]) -> Dataset:
        return replace(self, phase=tuple(phase))

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible representation (schema version 1)."""
        out: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, np.ndarray):
                value = value.tolist()
            elif isinstance(value, Provenance):
                value = {k.name: getattr(value, k.name) for k in fields(Provenance)}
            elif isinstance(value, tuple):
                value = [str(p) for p in value]
            elif isinstance(value, Quantity):
                value = value.value
            out[f.name] = value
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Dataset:
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise DatasetError(f"unsupported dataset schema version {version!r} (expected {SCHEMA_VERSION})")
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known - {"schema_version"}
        if unknown:
            raise DatasetError(f"unknown dataset fields: {sorted(unknown)}")
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs["quantity"] = Quantity(kwargs["quantity"])
        kwargs["provenance"] = Provenance(**(kwargs.get("provenance") or {}))
        if kwargs.get("phase") is not None:
            kwargs["phase"] = tuple(Phase(p) for p in kwargs["phase"])
        if kwargs.get("point_ids") is not None:
            kwargs["point_ids"] = np.asarray(kwargs["point_ids"], dtype=np.int64)
        return cls(**kwargs)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False, indent=1)

    @classmethod
    def from_json(cls, text: str) -> Dataset:
        return cls.from_dict(json.loads(text))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Dataset):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    __hash__ = None  # type: ignore[assignment]  # mutable-looking content: not hashable


def _length(array: Any) -> int:
    return len(np.atleast_1d(np.asarray(array)))


def _frozen_float_array(values: Any, name: str) -> np.ndarray:
    try:
        array = np.array(values, dtype=float).reshape(-1)
    except (TypeError, ValueError) as exc:
        raise DatasetError(f"{name} must contain numbers") from exc
    if not np.all(np.isfinite(array)):
        raise DatasetError(f"{name} contains non-finite values (NaN or inf)")
    array.flags.writeable = False
    return array
