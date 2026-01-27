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
    
    # Update VERSION file
    version_file.write_text(f"{new_version}\n")
    print(f"Updated VERSION: {current_version} -> {new_version}")
    
    # Update pyproject.toml
    pyproject_file = root_dir / "pyproject.toml"
    pyproject_content = pyproject_file.read_text()
    updated_content = pyproject_content.replace(
        f'version = "{current_version}"',
        f'version = "{new_version}"'
    )
    pyproject_file.write_text(updated_content)
    print(f"Updated pyproject.toml: {current_version} -> {new_version}")
    
    # Update app/__init__.py
    init_file = root_dir / "app" / "__init__.py"
    init_content = init_file.read_text()
    updated_content = init_content.replace(
        f'__version__ = "{current_version}"',
        f'__version__ = "{new_version}"'
    )
    init_file.write_text(updated_content)
    print(f"Updated app/__init__.py: {current_version} -> {new_version}")


if __name__ == "__main__":
    main()
