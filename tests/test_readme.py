from onshape_export.readme import END, START, update_readme


def test_update_readme_is_idempotent(tmp_path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(f"# Project\n\n{START}\nold\n{END}\n", encoding="utf-8")
    bom = "# Bill of Materials\n\n| Item | Component |\n| --- | --- |\n| 1 | Screw |\n"
    update_readme(
        readme,
        "preview.png",
        bom,
        "https://cad.onshape.com/documents/did/w/wid/e/eid",
        "assembly.step",
        "assembly.stl",
        "parts/",
        [("Exploded 1", "exploded/1.png")],
    )
    first = readme.read_text(encoding="utf-8")
    update_readme(
        readme,
        "preview.png",
        bom,
        "https://cad.onshape.com/documents/did/w/wid/e/eid",
        "assembly.step",
        "assembly.stl",
        "parts/",
        [("Exploded 1", "exploded/1.png")],
    )
    assert readme.read_text(encoding="utf-8") == first
    assert "![Onshape assembly](preview.png)" in first
    assert "![Exploded 1](exploded/1.png)" in first
    assert "[Complete assembly as STEP](assembly.step)" in first
    assert "[Interactive 3D view as STL](assembly.stl)" in first
    assert "## Bill of Materials" in first
    assert "https://cad.onshape.com/documents/did/w/wid/e/eid" in first
    assert "| 1 | Screw |" in first
    assert "GitHub Release" not in first
