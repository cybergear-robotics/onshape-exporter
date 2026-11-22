from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .backup import create_backup
from .client import OnshapeClient, OnshapeError
from .config import load_config
from .readme import update_readme


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Back up an Onshape assembly")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup", help="Export assembly, BOM, and printable parts")
    backup.add_argument("--config", type=Path, default=Path("onshape-export.toml"))
    backup.add_argument("--output", type=Path, default=Path("dist/onshape-backup"))
    backup.add_argument("--update-readme", action="store_true")
    backup.add_argument("--readme", type=Path, default=Path("README.md"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    try:
        access = os.environ.get("ONSHAPE_ACCESS_KEY")
        secret = os.environ.get("ONSHAPE_SECRET_KEY")
        if not access or not secret:
            raise ValueError("ONSHAPE_ACCESS_KEY and ONSHAPE_SECRET_KEY must be set")
        config = load_config(args.config)
        client = OnshapeClient(
            config.ref.base_url, access, secret, api_version=config.api_version
        )
        result = create_backup(client, config, args.output)
        if args.update_readme:
            readme_parent = args.readme.resolve().parent

            def relative_to_readme(path: Path) -> str:
                return Path(os.path.relpath(path.resolve(), readme_parent)).as_posix()

            exploded_views = [
                (display_name, relative_to_readme(source))
                for display_name, source in result.exploded_views
            ]
            update_readme(
                args.readme,
                relative_to_readme(args.output / "assembly" / "preview.png"),
                result.bom_markdown,
                (
                    f"{config.ref.base_url}/documents/{config.ref.document_id}/"
                    f"{config.ref.wvm}/{config.ref.wvm_id}/e/{config.ref.element_id}"
                ),
                relative_to_readme(args.output / "assembly" / "complete-assembly.step"),
                relative_to_readme(args.output / "parts"),
                exploded_views,
            )
            if not args.readme.is_file():
                raise OSError(f"README was not created at {args.readme.resolve()}")
            logging.info("README updated at %s", args.readme.resolve())
        if result.cached:
            logging.info("Backup is already current at %s", result.output_dir)
        else:
            logging.info("Backup created at %s (%d files)", result.output_dir, len(result.files))
        return 0
    except (ValueError, OSError, OnshapeError) as exc:
        logging.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
