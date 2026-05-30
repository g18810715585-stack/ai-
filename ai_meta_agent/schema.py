from __future__ import annotations

from pathlib import Path

from .io_utils import read_json
from .models import SchemaBundle, TableSchema


def load_schema(path: Path) -> SchemaBundle:
    return SchemaBundle.model_validate(read_json(path))


def table_schema(bundle: SchemaBundle, table_name: str) -> TableSchema:
    try:
        return bundle.tables[table_name]
    except KeyError as exc:
        raise KeyError(f"Unknown target table: {table_name}") from exc


def alias_map(bundle: SchemaBundle) -> dict[str, tuple[str, str]]:
    aliases: dict[str, tuple[str, str]] = {}
    for table_name, table in bundle.tables.items():
        for alias, field in table.field_aliases.items():
            aliases[alias] = (table_name, field)
        for field in table.fields:
            aliases[field] = (table_name, field)
    return aliases
