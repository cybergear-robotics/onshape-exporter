from __future__ import annotations

import base64
import binascii
import logging
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


LOG = logging.getLogger(__name__)

_MESH_FORMATS = {"3MF", "GLB", "GLTF", "OBJ", "STL"}


def _translation_body(
    format_name: str,
    *,
    part_id: str | None,
    configuration: str | None,
    units: str,
    resolution: str,
) -> dict[str, Any]:
    normalized_format = format_name.upper()
    body: dict[str, Any] = {
        "formatName": normalized_format,
        "storeInDocument": False,
        "translate": True,
        "allowFaultyParts": False,
    }
    if normalized_format in _MESH_FORMATS:
        normalized_resolution = resolution.lower()
        if normalized_resolution not in {"fine", "medium", "coarse"}:
            raise ValueError(
                f"Unsupported mesh resolution {resolution!r}; use fine, medium, or coarse"
            )
        body.update(
            {
                "grouping": True,
                "resolution": normalized_resolution,
                "specifyUnits": True,
                "unit": units.lower(),
            }
        )
    if part_id:
        body["partIds"] = part_id
    if configuration and configuration != "default":
        body["configuration"] = configuration
    return body


class OnshapeError(RuntimeError):
    pass


class OnshapeClient:
    def __init__(
        self,
        base_url: str,
        access_key: str,
        secret_key: str,
        api_version: str = "v12",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version.strip("/")
        self.session = requests.Session()
        self.session.auth = (access_key, secret_key)
        self.session.headers.update({"Accept": "application/json;charset=UTF-8; qs=0.09"})
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            # Translation POSTs are not guaranteed to be idempotent.
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/api/{self.api_version}/{path.lstrip('/')}"

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        response = self.session.request(method, self._url(path), timeout=120, **kwargs)
        if not response.ok:
            detail = response.text[:1000]
            raise OnshapeError(f"Onshape API returned {response.status_code}: {detail}")
        return response

    def get_json(self, path: str, **kwargs: Any) -> dict[str, Any]:
        value = self.request("GET", path, **kwargs).json()
        if not isinstance(value, dict):
            raise OnshapeError(f"Expected an object from {path}, got {type(value).__name__}")
        return value

    def get_assembly(self, did: str, wvm: str, wvmid: str, eid: str) -> dict[str, Any]:
        return self.get_json(
            f"assemblies/d/{did}/{wvm}/{wvmid}/e/{eid}",
            params={
                "includeMateFeatures": "false",
                "includeNonSolids": "false",
                "includeMateConnectors": "false",
                "excludeSuppressed": "true",
            },
        )

    def get_bom(self, did: str, wvm: str, wvmid: str, eid: str) -> dict[str, Any]:
        return self.get_json(
            f"assemblies/d/{did}/{wvm}/{wvmid}/e/{eid}/bom",
            params={"indented": "false", "multiLevel": "true", "generateIfAbsent": "true"},
        )

    def get_exploded_views(
        self, did: str, wvm: str, wvmid: str, eid: str
    ) -> list[dict[str, Any]]:
        value = self.request(
            "GET", f"assemblies/d/{did}/{wvm}/{wvmid}/e/{eid}/explodedviews"
        ).json()
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise OnshapeError("Expected a list from the exploded views endpoint")
        return value

    def create_translation(
        self,
        resource: str,
        did: str,
        wvm: str,
        wvmid: str,
        eid: str,
        format_name: str,
        *,
        part_id: str | None = None,
        configuration: str | None = None,
        units: str = "millimeter",
        resolution: str = "fine",
    ) -> dict[str, Any]:
        body = _translation_body(
            format_name,
            part_id=part_id,
            configuration=configuration,
            units=units,
            resolution=resolution,
        )
        response = self.request(
            "POST",
            f"{resource}/d/{did}/{wvm}/{wvmid}/e/{eid}/translations",
            headers={"Content-Type": "application/json;charset=UTF-8; qs=0.09"},
            json=body,
        )
        value = response.json()
        if not isinstance(value, dict) or not value.get("id"):
            raise OnshapeError(f"Translation did not return an id: {value!r}")
        return value

    def wait_for_translation(
        self, translation: dict[str, Any], timeout_seconds: int, poll_interval: float
    ) -> dict[str, Any]:
        translation_id = str(translation["id"])
        deadline = time.monotonic() + timeout_seconds
        current = translation
        interval = max(1.0, poll_interval)
        while str(current.get("requestState", "")).upper() not in {"DONE", "FAILED"}:
            if time.monotonic() >= deadline:
                raise OnshapeError(f"Translation {translation_id} timed out after {timeout_seconds}s")
            time.sleep(interval)
            current = self.get_json(f"translations/{translation_id}")
            interval = min(interval * 1.4, 15.0)
        if str(current.get("requestState")).upper() == "FAILED":
            raise OnshapeError(
                f"Translation {translation_id} failed: {current.get('failureReason', 'unknown reason')}"
            )
        return current

    def download_translation(self, did: str, translation: dict[str, Any], target: Path) -> Path:
        ids = translation.get("resultExternalDataIds") or []
        if not ids:
            raise OnshapeError("Completed translation contains no external data id")
        if len(ids) != 1:
            raise OnshapeError(
                f"Translation returned {len(ids)} files; a single non-ZIP export was expected"
            )
        response = self.request("GET", f"documents/d/{did}/externaldata/{ids[0]}")
        # 3MF is itself a ZIP-based file format; other requested formats must
        # not silently turn into an archive.
        if target.suffix.lower() != ".3mf" and response.content.startswith(b"PK\x03\x04"):
            raise OnshapeError("Onshape returned a ZIP archive instead of a single export file")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return target

    def export(
        self,
        resource: str,
        did: str,
        wvm: str,
        wvmid: str,
        eid: str,
        format_name: str,
        target: Path,
        *,
        timeout_seconds: int,
        poll_interval: float,
        part_id: str | None = None,
        configuration: str | None = None,
        units: str = "millimeter",
        resolution: str = "fine",
    ) -> Path:
        LOG.info("Exporting %s as %s", target.stem, format_name)
        started = self.create_translation(
            resource,
            did,
            wvm,
            wvmid,
            eid,
            format_name,
            part_id=part_id,
            configuration=configuration,
            units=units,
            resolution=resolution,
        )
        done = self.wait_for_translation(started, timeout_seconds, poll_interval)
        return self.download_translation(did, done, target)

    def download_thumbnail(self, did: str, wvm: str, wvmid: str, eid: str, target: Path) -> Path:
        # This unversioned endpoint returns the image directly, not thumbnail metadata.
        response = self.request(
            "GET",
            f"{self.base_url}/api/thumbnails/d/{did}/{wvm}/{wvmid}/e/{eid}/s/300x300",
            headers={"Accept": "image/png,image/jpeg,*/*"},
        )
        content_type = response.headers.get("Content-Type", "").casefold()
        if not content_type.startswith("image/"):
            raise OnshapeError(f"Thumbnail endpoint returned {content_type or 'unknown content type'}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return target

    def download_exploded_view(
        self,
        did: str,
        wvm: str,
        wvmid: str,
        eid: str,
        exploded_view_id: str,
        target: Path,
    ) -> Path:
        response = self.get_json(
            f"assemblies/d/{did}/{wvm}/{wvmid}/e/{eid}/shadedviews",
            params={
                "explodedViewId": exploded_view_id,
                "viewMatrix": "0.612,0.612,0,0,-0.354,0.354,0.707,0,0.707,-0.707,0.707,0",
                "outputHeight": 800,
                "outputWidth": 1200,
                "pixelSize": 0,
                "edges": "show",
                "showAllParts": "true",
                "includeSurfaces": "true",
                "useAntiAliasing": "true",
            },
        )
        encoded = _first_image(response.get("images"))
        try:
            image = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise OnshapeError("Exploded view endpoint returned invalid image data") from exc
        if not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise OnshapeError("Exploded view endpoint did not return a PNG image")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(image)
        return target


def _first_image(value: Any) -> str:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, list):
        for item in value:
            try:
                return _first_image(item)
            except OnshapeError:
                continue
    raise OnshapeError("Exploded view endpoint returned no image")
