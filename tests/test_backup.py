from onshape_export.backup import (
    _config_signature,
    _load_cached_result,
    _prepare_output,
    _resolve_source,
    _write_cache,
)
from onshape_export.models import BackupResult, Config, DocumentRef, ExportSettings


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


def test_cache_reuses_complete_export_for_same_microversion(tmp_path) -> None:
    output = tmp_path / "backup"
    _prepare_output(output)
    step = output / "assembly" / "complete-assembly.step"
    step.parent.mkdir()
    step.write_bytes(b"step")
    result = BackupResult(output, files=[step], bom_markdown="# Bill of Materials\n")
    config = Config(
        DocumentRef("https://cad.onshape.com", "did", "w", "wid", "eid"),
        "v12",
        ExportSettings(),
    )
    signature = _config_signature(config)
    ref = config.ref

    _write_cache(output, result, "microversion:mid", signature)
    cached = _load_cached_result(output, "microversion:mid", signature, ref)

    assert cached is not None
    assert cached.cached is True
    assert cached.files == [step]
    assert _load_cached_result(output, "microversion:new-mid", signature, ref) is None


def test_cache_is_invalid_when_an_exported_file_is_missing(tmp_path) -> None:
    output = tmp_path / "backup"
    _prepare_output(output)
    missing = output / "assembly" / "missing.step"
    result = BackupResult(output, files=[missing], bom_markdown="BOM")
    config = Config(
        DocumentRef("https://cad.onshape.com", "did", "w", "wid", "eid"),
        "v12",
        ExportSettings(),
    )
    signature = _config_signature(config)

    _write_cache(output, result, "microversion:mid", signature)

    assert _load_cached_result(output, "microversion:mid", signature, config.ref) is None


def test_polling_settings_do_not_invalidate_export_cache() -> None:
    ref = DocumentRef("https://cad.onshape.com", "did", "w", "wid", "eid")
    fast_polling = Config(ref, "v12", ExportSettings(poll_interval_seconds=3))
    slow_polling = Config(ref, "v12", ExportSettings(poll_interval_seconds=30))

    assert _config_signature(fast_polling) == _config_signature(slow_polling)


def test_version_mode_uses_latest_named_version_as_source() -> None:
    class Client:
        def get_latest_version(self, did):
            assert did == "did"
            return {"id": "vid", "name": "Release 1"}

        def get_current_microversion(self, did, wid):
            raise AssertionError("Microversion must not be requested in version mode")

    ref = DocumentRef("https://cad.onshape.com", "did", "w", "wid", "eid")
    config = Config(ref, "v12", ExportSettings(update_mode="version"))

    revision, source = _resolve_source(Client(), config)

    assert revision == "version:vid"
    assert (source.wvm, source.wvm_id) == ("v", "vid")
