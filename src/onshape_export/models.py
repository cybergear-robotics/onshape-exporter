from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DocumentRef:
    base_url: str
    document_id: str
    wvm: str
    wvm_id: str
    element_id: str


@dataclass(frozen=True)
class ExportSettings:
    product_column: str = "Produktzeile"
    product_value: str = "3dprint"
    units: str = "millimeter"
    mesh_resolution: str = "fine"
    translation_timeout_seconds: int = 900
    poll_interval_seconds: float = 15.0


@dataclass(frozen=True)
class BomColumn:
    property: str
    title: str


DEFAULT_BOM_COLUMNS = (
    BomColumn("item", "Item"),
    BomColumn("title1", "Component"),
    BomColumn("description", "Description"),
    BomColumn("quantity", "Quantity"),
    BomColumn("material", "Material"),
    BomColumn("mass", "Mass"),
)


@dataclass(frozen=True)
class Config:
    ref: DocumentRef
    api_version: str
    export: ExportSettings
    bom_columns: tuple[BomColumn, ...] = DEFAULT_BOM_COLUMNS


@dataclass
class BomTable:
    columns: list[str]
    rows: list[dict[str, Any]]
    raw: dict[str, Any]


@dataclass(frozen=True)
class PartRef:
    document_id: str
    wvm: str
    wvm_id: str
    element_id: str
    part_id: str
    name: str
    part_number: str = ""
    configuration: str = "default"

    @property
    def identity(self) -> tuple[str, ...]:
        return (
            self.document_id,
            self.wvm,
            self.wvm_id,
            self.element_id,
            self.part_id,
            self.configuration,
        )


@dataclass
class BackupResult:
    output_dir: Path
    files: list[Path] = field(default_factory=list)
    exploded_views: list[tuple[str, Path]] = field(default_factory=list)
    bom_markdown: str = ""
    warnings: list[str] = field(default_factory=list)
    cached: bool = False
