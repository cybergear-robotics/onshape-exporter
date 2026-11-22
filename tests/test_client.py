import pytest

from onshape_export.client import OnshapeError, _first_image, _translation_body


def test_3mf_translation_uses_valid_mesh_parameters() -> None:
    body = _translation_body(
        "3MF",
        part_id="JHD",
        configuration="default",
        units="millimeter",
        resolution="FINE",
    )

    assert body["resolution"] == "fine"
    assert body["unit"] == "millimeter"
    assert body["specifyUnits"] is True
    assert body["grouping"] is True
    assert body["partIds"] == "JHD"
    assert "units" not in body


def test_step_translation_has_no_mesh_parameters() -> None:
    body = _translation_body(
        "STEP",
        part_id=None,
        configuration=None,
        units="millimeter",
        resolution="fine",
    )

    assert "resolution" not in body
    assert "unit" not in body
    assert "specifyUnits" not in body
    assert "grouping" not in body


def test_invalid_mesh_resolution_is_rejected_before_api_call() -> None:
    with pytest.raises(ValueError, match="fine, medium, or coarse"):
        _translation_body(
            "3MF",
            part_id=None,
            configuration=None,
            units="millimeter",
            resolution="ultra",
        )


def test_first_exploded_view_image_accepts_nested_api_response() -> None:
    assert _first_image([["encoded-png"]]) == "encoded-png"


def test_missing_exploded_view_image_is_an_error() -> None:
    with pytest.raises(OnshapeError, match="no image"):
        _first_image([])
