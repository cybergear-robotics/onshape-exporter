import pytest

from onshape_export.bom import match_parts, normalize_bom, render_bom, select_rows
from onshape_export.models import BomColumn


def test_normalize_and_filter_bom() -> None:
    raw = {
        "headers": [
            {"id": "name", "name": "Name"},
            {"id": "line", "name": "Produktzeile"},
        ],
        "rows": [
            {"cells": {"name": "Bracket", "line": "3DPrint"}},
            {"cells": {"name": "Screw", "line": "Purchased"}},
        ],
    }
    table = normalize_bom(raw)
    selected = select_rows(table, "Produktzeile", "3dprint")
    assert len(selected) == 1
    assert selected[0]["Name"] == "Bracket"


def test_missing_filter_column_is_an_error() -> None:
    table = normalize_bom({"headers": [{"id": "name", "name": "Name"}], "rows": []})
    with pytest.raises(ValueError, match="Produktzeile"):
        select_rows(table, "Produktzeile", "3dprint")


def test_current_onshape_header_id_schema_and_product_alias() -> None:
    table = normalize_bom(
        {
            "headers": [
                {"id": "pn", "name": "Part number", "propertyName": "partNumber", "visible": True},
                {"id": "pl", "name": "Product line", "propertyName": "productLine", "visible": False},
            ],
            "rows": [
                {
                    "headerIdToValue": {"pn": "P-1", "pl": "3dprint"},
                    "itemSource": {
                        "documentId": "did",
                        "elementId": "eid",
                        "partId": "pid",
                    },
                }
            ],
        }
    )
    assert table.columns == ["Part number"]
    assert select_rows(table, "Produktzeile", "3dprint")[0]["Part number"] == "P-1"


def test_part_reference_comes_directly_from_bom_source() -> None:
    rows = [
        {
            "Part number": "P-1",
            "Name": "Bracket",
            "__source": {
                "documentId": "did",
                "elementId": "eid",
                "partId": "pid",
                "wvmType": "v",
                "wvmId": "vid",
                "fullConfiguration": "size=large",
            },
        }
    ]
    part = match_parts(rows, [])[0]
    assert (part.wvm, part.wvm_id, part.part_id) == ("v", "vid", "pid")
    assert part.configuration == "size=large"


def test_markdown_uses_requested_columns_and_title_mapping() -> None:
    table = normalize_bom(
        {
            "headers": [
                {"id": "item", "name": "Item", "propertyName": "item"},
                {"id": "title1", "name": "Title 1", "propertyName": "title1"},
                {"id": "title2", "name": "Title 2", "propertyName": "title2"},
                {"id": "description", "name": "Description", "propertyName": "description"},
                {"id": "quantity", "name": "Quantity", "propertyName": "quantity"},
                {"id": "material", "name": "Material", "propertyName": "material"},
                {"id": "mass", "name": "Mass", "propertyName": "customMassId"},
            ],
            "rows": [
                {
                    "headerIdToValue": {
                        "item": "1",
                        "title1": "Screw",
                        "title2": "Fasteners",
                        "description": "M3 screw",
                        "quantity": 4.0,
                        "material": {"displayName": "Steel"},
                        "mass": {"value": 12.5, "units": "gram"},
                    }
                }
            ],
        }
    )
    markdown = render_bom(table)
    assert "| Item | Component | Description | Quantity | Material | Mass |" in markdown
    assert "| 1 | Screw | M3 screw | 4 | Steel | 12.5 gram |" in markdown
    assert "Category" not in markdown
    assert "Automatically generated" not in markdown
    assert "Title 1" not in markdown
    assert "Title 2" not in markdown


def test_markdown_columns_can_be_selected_renamed_and_reordered() -> None:
    table = normalize_bom(
        {
            "headers": [
                {"id": "name", "name": "Title 1", "propertyName": "title1"},
                {"id": "quantity", "name": "Quantity", "propertyName": "quantity"},
            ],
            "rows": [{"headerIdToValue": {"name": "Bracket", "quantity": 2.0}}],
        }
    )

    markdown = render_bom(
        table,
        (BomColumn("quantity", "Anzahl"), BomColumn("title1", "Bauteil")),
    )

    assert "| Anzahl | Bauteil |" in markdown
    assert "| 2 | Bracket |" in markdown
