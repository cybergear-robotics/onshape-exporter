from pathlib import Path

import pytest

from onshape_export.config import parse_document_url


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
