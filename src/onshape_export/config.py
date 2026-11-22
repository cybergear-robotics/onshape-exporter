from __future__ import annotations

import re
import tomllib
from pathlib import Path
from urllib.parse import urlparse

from .models import BomColumn, Config, DEFAULT_BOM_COLUMNS, DocumentRef, ExportSettings


_DOCUMENT_PATH = re.compile(
    r"/documents/(?P<did>[a-fA-F0-9]+)/(?P<wvm>[wvm])/(?P<wvmid>[a-fA-F0-9]+)/e/(?P<eid>[a-fA-F0-9]+)"
)


def parse_document_url(url: str, base_url: str | None = None) -> DocumentRef:
    match = _DOCUMENT_PATH.search(urlparse(url).path)
    if not match:
        raise ValueError(
            "document_url must point to an Onshape element: "
            "/documents/<did>/w/<wid>/e/<eid>"
        )
    parsed = urlparse(url)
    origin = (base_url or f"{parsed.scheme}://{parsed.netloc}").rstrip("/")
    values = match.groupdict()
    return DocumentRef(
        base_url=origin,
        document_id=values["did"],
        wvm=values["wvm"],
        wvm_id=values["wvmid"],
        element_id=values["eid"],
    )


def load_config(path: Path) -> Config:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    onshape = data.get("onshape", {})
    export = data.get("export", {})
    bom = data.get("bom", {})
    raw_columns = bom.get("columns")
    if raw_columns is None:
        bom_columns = DEFAULT_BOM_COLUMNS
    else:
        if not isinstance(raw_columns, list) or not raw_columns:
            raise ValueError("bom.columns must be a non-empty list")
        parsed_columns: list[BomColumn] = []
        for index, column in enumerate(raw_columns, start=1):
            if not isinstance(column, dict):
                raise ValueError(f"bom.columns entry {index} must be a table")
            property_name = str(column.get("property", "")).strip()
            title = str(column.get("title", "")).strip()
            if not property_name or not title:
                raise ValueError(
                    f"bom.columns entry {index} requires non-empty property and title values"
                )
            parsed_columns.append(BomColumn(property_name, title))
        bom_columns = tuple(parsed_columns)
    ref = parse_document_url(
        str(onshape.get("document_url", "")), str(onshape.get("base_url", "")) or None
    )
    if ref.wvm != "w":
        raise ValueError("The configured source must currently be a workspace URL (/w/).")
    return Config(
        ref=ref,
        api_version=str(onshape.get("api_version", "v12")),
        export=ExportSettings(
            product_column=str(export.get("product_column", "Produktzeile")),
            product_value=str(export.get("product_value", "3dprint")),
            units=str(export.get("units", "millimeter")),
            mesh_resolution=str(export.get("mesh_resolution", "fine")).lower(),
            translation_timeout_seconds=int(export.get("translation_timeout_seconds", 900)),
            poll_interval_seconds=float(export.get("poll_interval_seconds", 15)),
        ),
        bom_columns=bom_columns,
    )
