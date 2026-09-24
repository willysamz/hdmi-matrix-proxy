#!/usr/bin/env python3
"""Bump version number in VERSION and pyproject.toml files."""

import sys
from pathlib import Path


def bump_version(version: str, part: str) -> str:
    """Bump version number.
    
    Args:
        version: Current version (e.g., "0.1.0")
        part: Part to bump ("major", "minor", or "patch")
    
    Returns:
        New version string
    """
    major, minor, patch = map(int, version.split("."))
    
    if part == "major":
        major += 1
        minor = 0
        patch = 0
    elif part == "minor":
        minor += 1
        patch = 0
    elif part == "patch":
        patch += 1
    else:
        raise ValueError(f"Invalid part: {part}. Must be 'major', 'minor', or 'patch'")
    
    return f"{major}.{minor}.{patch}"


def main():
    """Main function."""
    if len(sys.argv) != 2 or sys.argv[1] not in ["major", "minor", "patch"]:
        print("Usage: bump_version.py [major|minor|patch]")
        sys.exit(1)
    
    part = sys.argv[1]
    root_dir = Path(__file__).parent.parent
    
    # Read current version
    version_file = root_dir / "VERSION"
    current_version = version_file.read_text().strip()
    
    # Bump version
    new_version = bump_version(current_version, part)
    
    # VALIDATE EVERY FILE BEFORE WRITING ANY OF THEM.
    #
    # Two bugs found 2026-09-24, both of which had already happened:
    #
    #  1. Each file was updated by replacing the version read from VERSION. If a
    #     file had DRIFTED it matched nothing, and the script printed "Updated"
    #     anyway. VERSION said 0.2.0 while pyproject.toml and app/__init__.py
    #     both said 0.1.12, so `bump-minor` reported three successes and changed
    #     one file. A release would then have shipped a version nobody chose.
    #  2. VERSION was written FIRST, so once (1) was made to fail loudly, a
    #     failed bump left VERSION ahead of everything else — corrupting the very
    #     file it exists to manage, and needing a manual fix before a retry.
    #
    # So: resolve every edit in memory, refuse the whole bump if any file does not
    # contain the current version, and only then write. A bump now either fully
    # happens or does not happen at all.
    version_file = root_dir / "VERSION"
    pyproject_file = root_dir / "pyproject.toml"
    init_file = root_dir / "app" / "__init__.py"

    planned: list[tuple[Path, str]] = [(version_file, f"{new_version}\n")]
    for path, needle, label in (
        (pyproject_file, f'version = "{current_version}"', "pyproject.toml"),
        (init_file, f'__version__ = "{current_version}"', "app/__init__.py"),
    ):
        content = path.read_text()
        if needle not in content:
            raise SystemExit(
                f"{label} does not contain {current_version!r} — it has drifted from "
                f"the VERSION file. Reconcile them before bumping; nothing was written."
            )
        planned.append((path, content.replace(needle, needle.replace(current_version, new_version), 1)))

    for path, text in planned:
        path.write_text(text)
    print(f"Updated VERSION, pyproject.toml and app/__init__.py: {current_version} -> {new_version}")


if __name__ == "__main__":
    main()
