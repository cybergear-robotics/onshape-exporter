from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from .models import BomColumn, BomTable, DEFAULT_BOM_COLUMNS, PartRef


def _display(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if "displayValue" in value:
        return _display(value["displayValue"])
    unit = value.get("unit") or value.get("units")
    if "value" in value and unit:
        return f"{_display(value['value'])} {unit}"
    for key in ("displayName", "value", "name", "text"):
        if key in value:
            return _display(value[key])
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def normalize_bom(raw: dict[str, Any]) -> BomTable:
    headers = raw.get("headers") or raw.get("columns") or []
    rows = raw.get("rows") or raw.get("items") or []
    if not isinstance(headers, list) or not isinstance(rows, list):
        raise ValueError("Unsupported Onshape BOM response: headers/rows are not lists")

    id_to_name: dict[str, str] = {}
    id_to_property: dict[str, str] = {}
    visible_columns: list[str] = []
    for index, header in enumerate(headers):
        if isinstance(header, str):
            id_to_name[str(index)] = header
            id_to_name[header] = header
            visible_columns.append(header)
            continue
        if not isinstance(header, dict):
            continue
        name = str(
            header.get("name")
            or header.get("displayName")
            or header.get("propertyName")
            or header.get("id")
            or f"Column {index + 1}"
        )
        for key in ("id", "propertyId", "key"):
            if header.get(key) is not None:
                id_to_name[str(header[key])] = name
                if header.get("propertyName"):
                    id_to_property[str(header[key])] = str(header["propertyName"])
        id_to_name[str(index)] = name
        if header.get("visible", True):
            visible_columns.append(name)

    normalized: list[dict[str, Any]] = []
    for raw_row in rows:
        if not isinstance(raw_row, dict):
            continue
        cells = raw_row.get(
            "headerIdToValue", raw_row.get("cells", raw_row.get("values", {}))
        )
        row: dict[str, Any] = {}
        if isinstance(cells, list):
            for index, cell in enumerate(cells):
                if isinstance(cell, dict):
                    key = str(cell.get("headerId") or cell.get("columnId") or index)
                    row[id_to_name.get(key, key)] = _display(cell)
                else:
                    row[id_to_name.get(str(index), str(index))] = _display(cell)
        elif isinstance(cells, dict):
            for key, value in cells.items():
                row[id_to_name.get(str(key), str(key))] = _display(value)
                if str(key) in id_to_property:
                    row[f"__property:{id_to_property[str(key)]}"] = _display(value)

        # Keep source identity fields available for mapping but out of normal columns if hidden.
        source = raw_row.get("itemSource") or raw_row.get("source") or {}
        if isinstance(source, dict):
            row["__source"] = source
        for key in ("documentId", "elementId", "partId", "partNumber", "name", "configuration"):
            if key in raw_row and key not in row:
                row[f"__{key}"] = raw_row[key]
        normalized.append(row)

    columns = list(dict.fromkeys(visible_columns))
    known_header_names = set(id_to_name.values())
    for row in normalized:
        for key in row:
            if not key.startswith("__") and key not in known_header_names and key not in columns:
                columns.append(key)
    return BomTable(columns=columns, rows=normalized, raw=raw)


def select_rows(table: BomTable, column: str, expected: str) -> list[dict[str, Any]]:
    row_keys = list(dict.fromkeys(key for row in table.rows for key in row))
    actual = next((name for name in row_keys if name.casefold() == column.casefold()), None)
    if actual is None and column.casefold().replace(" ", "") in {"produktzeile", "productline"}:
        actual = next(
            (name for name in row_keys if name.casefold() == "__property:productline"), None
        )
    if actual is None:
        available = [name for name in row_keys if not name.startswith("__")]
        raise ValueError(
            f"BOM column {column!r} was not found. Available columns: {', '.join(available)}"
        )
    wanted = expected.strip().casefold()
    return [row for row in table.rows if str(row.get(actual, "")).strip().casefold() == wanted]


def _lookup(row: dict[str, Any], *names: str) -> str:
    folded = {key.casefold(): value for key, value in row.items()}
    for name in names:
        value = folded.get(name.casefold())
        if value not in (None, ""):
            return str(value)
    return ""


def parts_from_assembly(assembly: dict[str, Any]) -> list[PartRef]:
    sections: list[dict[str, Any]] = []
    root = assembly.get("rootAssembly")
    if isinstance(root, dict):
        sections.append(root)
    sections.extend(section for section in assembly.get("subAssemblies", []) if isinstance(section, dict))
    parts: list[PartRef] = []
    seen: set[tuple[str, ...]] = set()
    for section in sections:
        for instance in section.get("instances", []):
            if not isinstance(instance, dict) or str(instance.get("type", "")).casefold() != "part":
                continue
            if instance.get("suppressed"):
                continue
            did = str(instance.get("documentId") or section.get("documentId") or "")
            eid = str(instance.get("elementId") or "")
            pid = str(instance.get("partId") or "")
            mid = str(instance.get("documentMicroversion") or section.get("documentMicroversion") or "")
            vid = str(instance.get("documentVersion") or instance.get("versionId") or "")
            if not all((did, eid, pid)) or not (mid or vid):
                continue
            part = PartRef(
                document_id=did,
                wvm="v" if vid else "m",
                wvm_id=vid or mid,
                element_id=eid,
                part_id=pid,
                name=str(instance.get("name") or pid).rsplit(" <", 1)[0],
                part_number=str(instance.get("partNumber") or ""),
                configuration=str(instance.get("fullConfiguration") or instance.get("configuration") or "default"),
            )
            if part.identity not in seen:
                seen.add(part.identity)
                parts.append(part)
    return parts


def match_parts(rows: Iterable[dict[str, Any]], parts: list[PartRef]) -> list[PartRef]:
    selected: list[PartRef] = []
    selected_ids: set[tuple[str, ...]] = set()
    failures: list[str] = []
    for row in rows:
        source = row.get("__source") if isinstance(row.get("__source"), dict) else {}
        part_id = str(source.get("partId") or row.get("__partId") or _lookup(row, "Part ID"))
        element_id = str(source.get("elementId") or row.get("__elementId") or "")
        document_id = str(source.get("documentId") or row.get("__documentId") or "")
        number = _lookup(row, "Part number", "Part Number", "Teilenummer", "__partNumber")
        name = _lookup(row, "Name", "Item", "Benennung", "Description", "__name")

        # BOM itemSource is the most authoritative location, especially for linked
        # documents and configurations. Prefer it over reconstructing references.
        source_wvm = str(source.get("wvmType") or "").casefold()
        source_wvm_id = str(source.get("wvmId") or "")
        if all((document_id, element_id, part_id, source_wvm_id)) and source_wvm in {"w", "v", "m"}:
            direct = PartRef(
                document_id=document_id,
                wvm=source_wvm,
                wvm_id=source_wvm_id,
                element_id=element_id,
                part_id=part_id,
                name=name or number or part_id,
                part_number=number,
                configuration=str(
                    source.get("fullConfiguration") or source.get("configuration") or "default"
                ),
            )
            if direct.identity not in selected_ids:
                selected_ids.add(direct.identity)
                selected.append(direct)
            continue

        candidates = parts
        if part_id:
            candidates = [part for part in candidates if part.part_id == part_id]
        if element_id:
            candidates = [part for part in candidates if part.element_id == element_id]
        if document_id:
            candidates = [part for part in candidates if part.document_id == document_id]
        if not candidates and number:
            candidates = [part for part in parts if part.part_number.casefold() == number.casefold()]
        if not candidates and name:
            candidates = [part for part in parts if part.name.casefold() == name.casefold()]
        if not candidates:
            failures.append(number or name or part_id or "unnamed BOM row")
            continue
        for part in candidates:
            if part.identity not in selected_ids:
                selected_ids.add(part.identity)
                selected.append(part)
    if failures:
        raise ValueError("Could not map printable BOM rows to assembly parts: " + ", ".join(failures))
    return selected


def _output_value(row: dict[str, Any], column: BomColumn) -> Any:
    direct = next(
        (value for key, value in row.items() if key.casefold() == column.property.casefold()),
        None,
    )
    if direct is not None:
        return direct
    property_key = f"__property:{column.property}".casefold()
    property_value = next(
        (value for key, value in row.items() if key.casefold() == property_key), None
    )
    if property_value is not None:
        return property_value
    return next(
        (value for key, value in row.items() if key.casefold() == column.title.casefold()), ""
    )


def _format_output_value(property_name: str, value: Any) -> Any:
    if property_name.casefold() != "quantity" or value in (None, ""):
        return value
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return value
    if quantity == quantity.to_integral_value():
        return str(int(quantity))
    return value


def render_bom(
    table: BomTable, columns: tuple[BomColumn, ...] = DEFAULT_BOM_COLUMNS
) -> str:
    titles = [column.title for column in columns]
    lines = ["# Bill of Materials", "", "| " + " | ".join(titles) + " |"]
    lines.append("| " + " | ".join("---" for _ in titles) + " |")
    for row in table.rows:
        values = [
            _format_output_value(column.property, _output_value(row, column))
            for column in columns
        ]
        lines.append("| " + " | ".join(_md(value) for value in values) + " |")
    lines.append("")
    return "\n".join(lines)


def _md(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", "<br>")
