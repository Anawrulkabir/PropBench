"""Column mappings: which column holds which quantity, in which unit (README §2c: mappings are saved as templates)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from enum import StrEnum
from pathlib import Path
from typing import Any

from propbench.core import Quantity, parse_unit

TEMPLATE_KIND = "propbench.import-mapping"
TEMPLATE_VERSION = 1


class MappingError(ValueError):
    """A column mapping is incomplete or inconsistent."""


class Role(StrEnum):
    """What a column contains."""

    TEMPERATURE = "temperature"
    PRESSURE = "pressure"
    MOLAR_DENSITY = "molar_density"
    VALUE = "value"
    UNCERTAINTY = "uncertainty"
    PHASE = "phase"


class UncertaintyKind(StrEnum):
    """How an uncertainty column is expressed."""

    ABSOLUTE = "absolute"  # same dimension as the value; unit required (defaults to the value's unit)
    RELATIVE_PERCENT = "relative_percent"  # in % of the value
    RELATIVE_FRACTION = "relative_fraction"  # fraction of the value


_STATE_QUANTITY = {
    Role.TEMPERATURE: Quantity.TEMPERATURE,
    Role.PRESSURE: Quantity.PRESSURE,
    Role.MOLAR_DENSITY: Quantity.MOLAR_DENSITY,
}


@dataclass(frozen=True)
class ColumnSpec:
    column: str
    role: Role
    unit: str | None = None
    uncertainty_kind: UncertaintyKind | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", Role(self.role))
        if self.uncertainty_kind is not None:
            object.__setattr__(self, "uncertainty_kind", UncertaintyKind(self.uncertainty_kind))
        if not self.column.strip():
            raise MappingError("a column spec needs a column name")


@dataclass(frozen=True)
class ImportMapping:
    """How to read one table into a dataset of ``quantity``.

    ``header_row`` and ``first_data_row`` are 1-based file rows (as shown in a spreadsheet). A units row between the
    header and the data (Origin style) is skipped by setting ``first_data_row``.
    """

    quantity: Quantity
    columns: tuple[ColumnSpec, ...]
    coverage_factor: float = 2.0
    header_row: int = 1
    first_data_row: int | None = None
    sheet: str | None = None
    decimal_comma: bool = False
    delimiter: str | None = None
    notes: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", Quantity(self.quantity))
        object.__setattr__(self, "columns", tuple(_spec(c) for c in self.columns))
        if self.header_row < 1:
            raise MappingError("header_row is 1-based and must be at least 1")
        if self.first_data_row is not None and self.first_data_row <= self.header_row:
            raise MappingError("first_data_row must come after header_row")
        if not self.coverage_factor > 0:
            raise MappingError("the coverage factor must be positive")
        names = [c.column for c in self.columns]
        if len(set(names)) != len(names):
            raise MappingError("each column may be mapped only once")
        roles = [c.role for c in self.columns]
        for role in Role:
            if roles.count(role) > 1:
                raise MappingError(f"more than one column has the role '{role.value}'")
        for required in (Role.TEMPERATURE, Role.VALUE):
            if required not in roles:
                raise MappingError(f"no column has the role '{required.value}'")
        if (
            Role.PRESSURE not in roles
            and Role.MOLAR_DENSITY not in roles
            and self.quantity is not Quantity.VAPOR_PRESSURE
        ):
            raise MappingError("map a pressure or molar-density column to define the state of each point")
        for spec in self.columns:
            self._check_spec(spec)

    def _check_spec(self, spec: ColumnSpec) -> None:
        if spec.role in _STATE_QUANTITY or spec.role is Role.VALUE:
            if not spec.unit:
                raise MappingError(f"column '{spec.column}' needs a unit")
            parse_unit(spec.unit, _STATE_QUANTITY.get(spec.role, self.quantity))
        elif spec.role is Role.UNCERTAINTY:
            if spec.uncertainty_kind is None:
                raise MappingError(f"uncertainty column '{spec.column}' needs an uncertainty_kind")
            if spec.uncertainty_kind is UncertaintyKind.ABSOLUTE and spec.unit:
                parse_unit(spec.unit, self.quantity)

    @property
    def data_start_row(self) -> int:
        return self.first_data_row if self.first_data_row is not None else self.header_row + 1

    def column(self, role: Role) -> ColumnSpec | None:
        return next((c for c in self.columns if c.role is role), None)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": TEMPLATE_KIND, "version": TEMPLATE_VERSION}
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name == "columns":
                value = [
                    {k: (str(v) if isinstance(v, StrEnum) else v) for k, v in vars(c).items() if v is not None}
                    for c in value
                ]
            elif isinstance(value, StrEnum):
                value = value.value
            out[f.name] = value
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImportMapping:
        if data.get("kind") != TEMPLATE_KIND or data.get("version") != TEMPLATE_VERSION:
            raise MappingError(f"not a version-{TEMPLATE_VERSION} PropBench import mapping")
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known - {"kind", "version"}
        if unknown:
            raise MappingError(f"unknown mapping fields: {sorted(unknown)}")
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs["columns"] = tuple(ColumnSpec(**c) for c in kwargs.get("columns", ()))
        return cls(**kwargs)

    def save(self, path: str | Path) -> None:
        """Save as a reusable template (JSON)."""
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> ImportMapping:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _spec(value: ColumnSpec | dict[str, Any]) -> ColumnSpec:
    return value if isinstance(value, ColumnSpec) else ColumnSpec(**value)
