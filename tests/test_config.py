from pathlib import Path

import pytest

from onshape_export.config import load_config, parse_document_url


def test_parse_document_url() -> None:
    ref = parse_document_url(
        "https://cad.onshape.com/documents/abc123/w/def456/e/789abc"
    )
    assert ref.document_id == "abc123"
    assert ref.wvm == "w"
    assert ref.wvm_id == "def456"
    assert ref.element_id == "789abc"


def test_reject_invalid_document_url() -> None:
    with pytest.raises(ValueError):
        parse_document_url("https://cad.onshape.com/documents/not-enough")


def test_loads_custom_bom_columns(tmp_path: Path) -> None:
    path = tmp_path / "onshape-export.toml"
    path.write_text(
        """
[onshape]
document_url = "https://cad.onshape.com/documents/abc123/w/def456/e/789abc"

[bom]
columns = [
  { property = "quantity", title = "Anzahl" },
  { property = "title1", title = "Bauteil" },
]
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert [(column.property, column.title) for column in config.bom_columns] == [
        ("quantity", "Anzahl"),
        ("title1", "Bauteil"),
    ]
    assert config.export.poll_interval_seconds == 15
