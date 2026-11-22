from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .bom import match_parts, normalize_bom, parts_from_assembly, render_bom, select_rows
from .client import OnshapeClient
from .models import BackupResult, Config, DocumentRef, PartRef


LOG = logging.getLogger(__name__)

_MANAGED_DIRECTORIES = ("assembly", "parts")
_MARKER_NAME = ".onshape-export-managed"
_CACHE_NAME = ".onshape-export-cache.json"
_CACHE_VERSION = 2


def _safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    return value or "unnamed-part"


def _part_dir(part: PartRef) -> str:
    prefix = f"{part.part_number}-" if part.part_number else ""
    suffix = hashlib.sha256("|".join(part.identity).encode()).hexdigest()[:8]
    return _safe_name(f"{prefix}{part.name}-{suffix}")


def _prepare_output(output: Path) -> None:
    marker = output / _MARKER_NAME
    authorized = marker.is_file()

    if output.exists() and not output.is_dir():
        raise ValueError(f"Output path {output} is not a directory")
    output.mkdir(parents=True, exist_ok=True)

    existing_managed = [output / name for name in _MANAGED_DIRECTORIES if (output / name).exists()]
    if existing_managed and not authorized:
        names = ", ".join(path.name for path in existing_managed)
        raise ValueError(
            f"Refusing to replace unmanaged output in {output}: {names}. "
            f"Remove it once or add {_MARKER_NAME}."
        )
    for path in existing_managed:
        if not path.is_dir():
            raise ValueError(f"Managed output path {path} is not a directory")
        shutil.rmtree(path)

    marker.write_text("managed by onshape-export\n", encoding="utf-8")


def _config_signature(config: Config) -> str:
    payload = {
        "cache_version": _CACHE_VERSION,
        "source": asdict(config.ref),
        "api_version": config.api_version,
        "export": {
            "product_column": config.export.product_column,
            "product_value": config.export.product_value,
            "units": config.export.units,
            "mesh_resolution": config.export.mesh_resolution,
            "update_mode": config.export.update_mode,
        },
        "bom_columns": [asdict(column) for column in config.bom_columns],
        "formats": {"assembly": ["STEP"], "parts": ["3MF"]},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_cached_result(
    output: Path, revision: str, signature: str, source_ref: DocumentRef
) -> BackupResult | None:
    def cached_path(value: str) -> Path | None:
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            return None
        return output / relative

    cache_path = output / _CACHE_NAME
    if not cache_path.is_file() or not (output / _MARKER_NAME).is_file():
        return None
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            return None
        if (
            cache.get("version") != _CACHE_VERSION
            or cache.get("revision") != revision
            or cache.get("signature") != signature
        ):
            return None
        relative_files = cache.get("files")
        if not isinstance(relative_files, list) or not all(
            isinstance(path, str) for path in relative_files
        ):
            return None
        resolved_files = [cached_path(path) for path in relative_files]
        if not resolved_files or any(path is None for path in resolved_files):
            return None
        files = [path for path in resolved_files if path is not None]
        if not all(path.is_file() for path in files):
            return None
        raw_views = cache.get("exploded_views", [])
        if not isinstance(raw_views, list):
            return None
        exploded_views: list[tuple[str, Path]] = []
        for view in raw_views:
            if (
                not isinstance(view, dict)
                or not isinstance(view.get("name"), str)
                or not isinstance(view.get("path"), str)
            ):
                return None
            path = cached_path(view["path"])
            if path is None:
                return None
            exploded_views.append((view["name"], path))
        bom_markdown = cache.get("bom_markdown")
        if not isinstance(bom_markdown, str):
            return None
    except (OSError, json.JSONDecodeError):
        return None
    return BackupResult(
        output,
        files=files,
        exploded_views=exploded_views,
        bom_markdown=bom_markdown,
        cached=True,
        source_ref=source_ref,
    )


def _write_cache(
    output: Path, result: BackupResult, revision: str, signature: str
) -> None:
    def relative(path: Path) -> str:
        return path.relative_to(output).as_posix()

    cache: dict[str, Any] = {
        "version": _CACHE_VERSION,
        "revision": revision,
        "signature": signature,
        "files": [relative(path) for path in result.files],
        "exploded_views": [
            {"name": name, "path": relative(path)} for name, path in result.exploded_views
        ],
        "bom_markdown": result.bom_markdown,
    }
    cache_path = output / _CACHE_NAME
    temporary = output / f"{_CACHE_NAME}.tmp"
    temporary.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(cache_path)


def _resolve_source(client: OnshapeClient, config: Config) -> tuple[str, DocumentRef]:
    ref = config.ref
    if config.export.update_mode == "version":
        version = client.get_latest_version(ref.document_id)
        version_id = str(version["id"])
        return (
            f"version:{version_id}",
            DocumentRef(ref.base_url, ref.document_id, "v", version_id, ref.element_id),
        )
    microversion = client.get_current_microversion(ref.document_id, ref.wvm_id)
    return f"microversion:{microversion}", ref


def create_backup(client: OnshapeClient, config: Config, output: Path) -> BackupResult:
    revision, ref = _resolve_source(client, config)
    signature = _config_signature(config)
    cached = _load_cached_result(output, revision, signature, ref)
    if cached is not None:
        LOG.info("Onshape source revision is unchanged; using cached export")
        return cached

    _prepare_output(output)
    settings = config.export
    result = BackupResult(output, source_ref=ref)

    assembly = client.get_assembly(
        ref.document_id, ref.wvm, ref.wvm_id, ref.element_id
    )

    raw_bom = client.get_bom(ref.document_id, ref.wvm, ref.wvm_id, ref.element_id)
    table = normalize_bom(raw_bom)
    result.bom_markdown = render_bom(table, config.bom_columns)

    assembly_dir = output / "assembly"
    step = client.export(
        "assemblies",
        ref.document_id,
        ref.wvm,
        ref.wvm_id,
        ref.element_id,
        "STEP",
        assembly_dir / "complete-assembly.step",
        timeout_seconds=settings.translation_timeout_seconds,
        poll_interval=settings.poll_interval_seconds,
        units=settings.units,
        resolution=settings.mesh_resolution,
    )
    result.files.append(step)
    preview = client.download_thumbnail(
        ref.document_id,
        ref.wvm,
        ref.wvm_id,
        ref.element_id,
        assembly_dir / "preview.png",
    )
    result.files.append(preview)

    exploded_views = client.get_exploded_views(
        ref.document_id, ref.wvm, ref.wvm_id, ref.element_id
    )
    if not exploded_views:
        LOG.warning("The assembly contains no saved exploded views")
    for index, view in enumerate(exploded_views, start=1):
        view_id = str(view.get("id") or "")
        if not view_id:
            raise ValueError("Onshape returned an exploded view without an id")
        view_name = str(view.get("name") or f"Exploded view {index}")
        exploded_image = client.download_exploded_view(
            ref.document_id,
            ref.wvm,
            ref.wvm_id,
            ref.element_id,
            view_id,
            assembly_dir / "exploded" / f"{index:02d}-{_safe_name(view_name)}.png",
        )
        result.files.append(exploded_image)
        result.exploded_views.append((view_name, exploded_image))

    printable_rows = select_rows(table, settings.product_column, settings.product_value)
    all_parts = parts_from_assembly(assembly)
    printable_parts = match_parts(printable_rows, all_parts)
    LOG.info("Found %d unique printable parts", len(printable_parts))
    for part in printable_parts:
        part_basename = _part_dir(part)
        directory = output / "parts" / part_basename
        target = client.export(
            "partstudios",
            part.document_id,
            part.wvm,
            part.wvm_id,
            part.element_id,
            "3MF",
            directory / f"{part_basename}.3mf",
            timeout_seconds=settings.translation_timeout_seconds,
            poll_interval=settings.poll_interval_seconds,
            part_id=part.part_id,
            configuration=part.configuration,
            units=settings.units,
            resolution=settings.mesh_resolution,
        )
        result.files.append(target)
    _write_cache(output, result, revision, signature)
    return result
