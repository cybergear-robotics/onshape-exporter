from onshape_export.backup import _prepare_output


def test_prepare_output_preserves_project_files(tmp_path) -> None:
    project = tmp_path / "computer_module"
    project.mkdir()
    readme = project / "README.md"
    config = project / "onshape-export.toml"
    readme.write_text("# Computer Module\n", encoding="utf-8")
    config.write_text("[onshape]\n", encoding="utf-8")

    _prepare_output(project)
    assembly = project / "assembly"
    parts = project / "parts"
    assembly.mkdir()
    parts.mkdir()
    (assembly / "old.step").write_text("old", encoding="utf-8")
    (parts / "old.stl").write_text("old", encoding="utf-8")

    _prepare_output(project)

    assert readme.read_text(encoding="utf-8") == "# Computer Module\n"
    assert config.is_file()
    assert not assembly.exists()
    assert not parts.exists()
    assert (project / ".onshape-export-managed").is_file()


def test_prepare_output_refuses_unmanaged_generated_directories(tmp_path) -> None:
    project = tmp_path / "computer_module"
    (project / "assembly").mkdir(parents=True)

    try:
        _prepare_output(project)
    except ValueError as exc:
        assert "unmanaged output" in str(exc)
    else:
        raise AssertionError("Expected unmanaged output to be rejected")
