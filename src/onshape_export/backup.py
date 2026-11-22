from __future__ import annotations

import hashlib
import logging
import re
import shutil
from pathlib import Path

from .bom import match_parts, normalize_bom, parts_from_assembly, render_bom, select_rows
from .client import OnshapeClient
from .models import BackupResult, Config, PartRef


LOG = logging.getLogger(__name__)

_MANAGED_DIRECTORIES = ("assembly", "parts")
_MARKER_NAME = ".onshape-export-managed"


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


def create_backup(client: OnshapeClient, config: Config, output: Path) -> BackupResult:
    _prepare_output(output)
    ref = config.ref
    settings = config.export
    result = BackupResult(output)

    assembly = client.get_assembly(
        ref.document_id, ref.wvm, ref.wvm_id, ref.element_id
    )

    raw_bom = client.get_bom(ref.document_id, ref.wvm, ref.wvm_id, ref.element_id)
    table = normalize_bom(raw_bom)
    result.bom_markdown = render_bom(table)

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
    assembly_stl = client.export(
        "assemblies",
        ref.document_id,
        ref.wvm,
        ref.wvm_id,
        ref.element_id,
        "STL",
        assembly_dir / "complete-assembly.stl",
        timeout_seconds=settings.translation_timeout_seconds,
        poll_interval=settings.poll_interval_seconds,
        units=settings.units,
        resolution=settings.mesh_resolution,
    )
    result.files.append(assembly_stl)
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
        for format_name, extension in (("STL", "stl"), ("STEP", "step"), ("3MF", "3mf")):
            target = client.export(
                "partstudios",
                part.document_id,
                part.wvm,
                part.wvm_id,
                part.element_id,
                format_name,
                directory / f"{part_basename}.{extension}",
                timeout_seconds=settings.translation_timeout_seconds,
                poll_interval=settings.poll_interval_seconds,
                part_id=part.part_id,
                configuration=part.configuration,
                units=settings.units,
                resolution=settings.mesh_resolution,
            )
            result.files.append(target)
    return result
