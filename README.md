# Onshape Backup Exporter

[![Unit tests](https://github.com/cybergear-robotics/onshape-exporter/actions/workflows/tests.yml/badge.svg)](https://github.com/cybergear-robotics/onshape-exporter/actions/workflows/tests.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Exports an Onshape assembly as STEP, its bill of materials as Markdown, and all
parts marked with `Produktzeile = 3dprint` as 3MF.

## Local usage

Requirements: Python 3.11 or newer and an Onshape API key with read access to
the document.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
export ONSHAPE_ACCESS_KEY='...'
export ONSHAPE_SECRET_KEY='...'
onshape-export backup --config onshape-export.toml --output dist/onshape-backup --update-readme
```

Set the document URL and export options in `onshape-export.toml`. Credentials
must only be stored in environment variables or GitHub Secrets.

## GitHub Actions

Add `ONSHAPE_ACCESS_KEY` and `ONSHAPE_SECRET_KEY` under **Settings → Secrets and
variables → Actions**. The **Onshape backup** workflow can then be started
manually through `Actions → Run workflow`. It commits the bill of materials to
this README along with all preview images and exported files.

### Setup in another repository

1. Create one directory for each CAD project.
2. Add an `onshape-export.toml` and a `README.md` to each project directory.
3. Set `document_url` to the URL of that project's top-level Onshape assembly.
4. Create the following GitHub Actions repository secrets:
   - `ONSHAPE_ACCESS_KEY`
   - `ONSHAPE_SECRET_KEY`
5. Create `.github/workflows/onshape-backup.yml` in the backup repository.
6. Open the **Actions** tab, select **Onshape backup**, and click
   **Run workflow**.

Each project directory is updated in place:

```text
project_name/
├── onshape-export.toml
├── README.md
├── assembly/
└── parts/
```

Example `onshape-export.toml`:

```toml
[onshape]
base_url = "https://cad.onshape.com"
document_url = "https://cad.onshape.com/documents/DOCUMENT_ID/w/WORKSPACE_ID/e/ELEMENT_ID"
api_version = "v12"

[export]
product_column = "Produktzeile"
product_value = "3dprint"
units = "millimeter"
mesh_resolution = "fine"
translation_timeout_seconds = 900
poll_interval_seconds = 15
# "microversion" exports workspace changes; "version" exports only new named versions.
update_mode = "microversion"

[bom]
columns = [
  { property = "item", title = "Item" },
  { property = "title1", title = "Component" },
  { property = "description", title = "Description" },
  { property = "quantity", title = "Quantity" },
  { property = "material", title = "Material" },
  { property = "mass", title = "Mass" },
]
```

The column order in `bom.columns` is also used in the generated Markdown. The
exporter stores the last exported source revision in `.onshape-export-cache.json`.
An unchanged run uses one API request to check the revision and does not recreate
translations or download files. Set `update_mode = "version"` to export the
latest named Onshape version only when a new version has been created. The
default `microversion` mode tracks every workspace change.

### Complete workflow

This workflow discovers and exports every `onshape-export.toml` in the
repository:

```yaml
name: Onshape backup

on:
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: onshape-backup
  cancel-in-progress: false

jobs:
  export:
    runs-on: ubuntu-latest
    timeout-minutes: 60

    steps:
      - name: Check out repository
        uses: actions/checkout@v6
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.12"
          cache: pip

      - name: Install exporter
        run: >-
          pip install
          "git+https://github.com/cybergear-robotics/onshape-exporter.git@master"

      - name: Export all Onshape projects
        env:
          ONSHAPE_ACCESS_KEY: ${{ secrets.ONSHAPE_ACCESS_KEY }}
          ONSHAPE_SECRET_KEY: ${{ secrets.ONSHAPE_SECRET_KEY }}
        run: |
          mapfile -d '' configs < <(
            find . -type f -name onshape-export.toml -not -path './.git/*' -print0 | sort -z
          )
          if (( ${#configs[@]} == 0 )); then
            echo "No onshape-export.toml files found" >&2
            exit 1
          fi

          for config in "${configs[@]}"; do
            project_dir="$(dirname "$config")"
            echo "::group::Export ${project_dir#./}"
            onshape-export backup \
              --config "$config" \
              --output "$project_dir" \
              --update-readme \
              --readme "$project_dir/README.md"
            echo "::endgroup::"
          done

      - name: Commit generated backups
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -A
          if ! git diff --cached --quiet; then
            git commit -m "docs: update Onshape backup"
            git push
          fi
```

The workflow commits the following generated content:

- `<project>/README.md` with model links, images, and the bill of materials
- `<project>/assembly/` with STEP, preview, and exploded-view images
- `<project>/parts/` with 3MF files for printable parts

Repositories with branch protection must allow the GitHub Actions bot to push,
or the final step must be changed to create a pull request instead.
