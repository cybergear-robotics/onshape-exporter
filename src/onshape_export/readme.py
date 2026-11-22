from __future__ import annotations

from pathlib import Path


START = "<!-- onshape-export:start -->"
END = "<!-- onshape-export:end -->"


def update_readme(
    readme: Path,
    preview_path: str,
    bom_markdown: str,
    onshape_url: str,
    step_path: str,
    parts_path: str,
    exploded_views: list[tuple[str, str]] | None = None,
) -> None:
    lines = [
        START,
        "## CAD Model",
        "",
        f"![Onshape assembly]({preview_path})",
        "",
        f"- [Onshape document]({onshape_url})",
        f"- [Complete assembly as STEP]({step_path})",
        f"- [3MF files for printable parts]({parts_path})",
    ]
    if exploded_views:
        lines.extend(["", "### Exploded Views"])
        for name, path in exploded_views:
            lines.extend(["", f"#### {name}", "", f"![{name}]({path})"])
    bom_lines = bom_markdown.strip().splitlines()
    if bom_lines and bom_lines[0].strip() == "# Bill of Materials":
        bom_lines = bom_lines[1:]
    while bom_lines and not bom_lines[0].strip():
        bom_lines.pop(0)
    lines.extend(["", "## Bill of Materials", "", *bom_lines])
    lines.append(END)
    block = "\n".join(lines)
    current = readme.read_text(encoding="utf-8") if readme.exists() else "# Onshape Backup\n"
    if START in current and END in current:
        before, rest = current.split(START, 1)
        _, after = rest.split(END, 1)
        current = before.rstrip() + "\n\n" + block + after
    else:
        current = current.rstrip() + "\n\n" + block + "\n"
    readme.write_text(current, encoding="utf-8")
