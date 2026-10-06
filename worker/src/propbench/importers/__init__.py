"""Importers: CSV, Excel and ThermoML files → datasets, with reusable column mappings (README §2c)."""

from propbench.importers.mapping import ColumnSpec, ImportMapping, MappingError, Role, UncertaintyKind
from propbench.importers.tabular import (
    ImportFileError,
    InMemoryFile,
    Preview,
    Table,
    import_file,
    preview_file,
    read_table,
    table_to_dataset,
)
from propbench.importers.thermoml import read_thermoml

__all__ = [
    "ColumnSpec",
    "ImportFileError",
    "ImportMapping",
    "InMemoryFile",
    "MappingError",
    "Preview",
    "Role",
    "Table",
    "UncertaintyKind",
    "import_file",
    "preview_file",
    "read_table",
    "read_thermoml",
    "table_to_dataset",
]
