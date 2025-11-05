import os
import ast
import re
import tomlkit
from typing import Set
import sys
from pathlib import Path

# --- Conditional Import for TOML Parsing (supporting Python 3.9+) ---
if sys.version_info >= (3, 11):
    import tomllib
else:
    # Use tomli for Python 3.10 and 3.9
    try:
        import tomli as tomllib
    except ImportError:
        # This error handling is critical if the dependency is missing
        print(
            "Error: For Python < 3.11, the 'tomli' package must be installed. Check your pyproject.toml dependencies."
        )
        raise

# External dependency for filtering standard library modules
try:
    from stdlib_list import stdlib_list

    # Note: Use the highest supported version for the most accurate list
    STDLIB = set(stdlib_list(f"{sys.version_info.major}.{sys.version_info.minor}"))
except ImportError:
    print(
        "Warning: stdlib-list not installed. Standard library filtering will be less accurate."
    )
    STDLIB = set()

# --- Configuration/Helpers ---
# CRITICAL: Packages that are external runners, tools, build systems, or the package itself.
# These should NEVER be removed, even if not explicitly imported in the source code.
IGNORE_PACKAGES = {
    # Self-Exclusion
    "pytomlcleaner",
    # Testing Tools
    "pytest",
    "tox",
    # Formatting, Linting, & Static Analysis Tools
    "black",
    "ruff",
    "mypy",
    "pylint",
    "flake8",
    "isort",
    # Build & Packaging Tools
    "poetry",  # Used for project management and configuration
    "setuptools",  # Core build system dependency
    "wheel",  # Core build dependency
    "build",  # Standard Python package building
    "twine",  # Used for uploading to PyPI
    # General Development Utilities
    "pre-commit",  # Used for managing Git hooks
    "virtualenv",
    "pip",
}

EXCLUDE_DIRS = [
    "venv",
    ".venv",
    ".git",
    "__pycache__",
    "dist",
    "build",
    ".mypy_cache",
    "node_modules",
    "htmlcov",
]


def is_local_module(import_name: str, base_dir: str) -> bool:
    """Checks if an import name likely refers to a local file/directory within the project."""
    parts = import_name.split(".")
    top_level_name = parts[0]

    # Check for package directory (must contain __init__.py)
    package_path = Path(base_dir) / top_level_name
    if package_path.is_dir() and (package_path / "__init__.py").exists():
        return True

    # Check for single module file
    if (Path(base_dir) / f"{top_level_name}.py").exists():
        return True

    return False


# --- Core Logic Functions ---


def get_dependencies(path: str = "pyproject.toml") -> Set[str]:
    """Reads project dependencies from pyproject.toml, targeting PEP 621 and Poetry styles."""
    dependencies = set()

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        print(f"Error: {path} not found.")
        return dependencies

    # 1. PEP 621 (project.dependencies)
    project_deps_list = data.get("project", {}).get("dependencies", [])
    for dep in project_deps_list:
        # Get package name, ignoring version specs and markers
        package_name = (
            dep.split(";")[0]
            .split("<")[0]
            .split(">")[0]
            .split("=")[0]
            .split("~")[0]
            .split("!")[0]
            .strip()
        )
        dependencies.add(package_name.lower())

    # 2. Poetry Dependencies (tool.poetry.dependencies)
    poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    for pkg in poetry_deps:
        if pkg.lower() not in ["python"]:
            dependencies.add(pkg.lower())

    return dependencies


def get_all_imports(root_dir: str = ".") -> Set[str]:
    """Scans all .py files in a directory for top-level import names using AST."""
    used_imports = set()

    for root, dirs, files in os.walk(root_dir):
        # Filter directories to exclude
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                        tree = ast.parse(content, filename=filepath)
                except Exception as e:
                    print(f"Warning: Could not parse {filepath}: {e}")
                    continue

                for node in ast.walk(tree):
                    # Handle 'import requests'
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            used_imports.add(alias.name.split(".")[0].lower())

                    # Handle 'from requests import get'
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            used_imports.add(node.module.split(".")[0].lower())

                # Heuristic check for string-based/guarded imports (e.g., in type checking or docstrings)
                matches = re.findall(r"(?:import|from)\s+([a-zA-Z0-9_.]+)", content)
                for match in matches:
                    used_imports.add(match.split(".")[0].lower())

    # Filter out standard library modules and local modules
    final_imports = set()
    for imp in used_imports:
        if imp not in STDLIB and not is_local_module(imp, root_dir):
            final_imports.add(imp)

    # Handle known package name/import name mismatches (e.g., Pillow is imported as PIL)
    if "pil" in final_imports:
        final_imports.add("pillow")

    return final_imports


def find_unused_dependencies(
    code_root: str = ".", pyproject_path: str = "pyproject.toml"
) -> Set[str]:
    """
    Compares dependencies to actual imports and returns unused packages,
    EXCLUDING those defined in IGNORE_PACKAGES.
    """

    project_dependencies = get_dependencies(pyproject_path)
    used_imports = get_all_imports(code_root)

    # 1. Calculate the raw difference: dependencies not found in imports
    unused_deps = project_dependencies - used_imports

    # 2. CRITICAL FILTER: Subtract the manually ignored packages
    final_unused_deps = unused_deps - IGNORE_PACKAGES

    # 3. Optional: Print a note about the packages we skipped removing
    ignored_but_unused = unused_deps.intersection(IGNORE_PACKAGES)
    if ignored_but_unused:
        print(
            f"\n💡 Note: Skipping removal of utility packages: {', '.join(sorted(ignored_but_unused))}"
        )

    return final_unused_deps


def remove_unused_dependencies(pyproject_path: str, unused_packages: Set[str]) -> None:
    """
    Removes the specified unused packages from the pyproject.toml file
    by modifying the TOML structure in place to better preserve formatting.
    """
    try:
        with open(pyproject_path, "r", encoding="utf-8") as f:
            doc = tomlkit.load(f)
    except FileNotFoundError:
        print(f"Error: {pyproject_path} not found.")
        return

    # 1. Handle PEP 621 'project.dependencies' (Array of Strings)
    if "project" in doc and "dependencies" in doc["project"]:
        project_deps = doc["project"]["dependencies"]
        if isinstance(project_deps, tomlkit.items.Array):
            # Iterate backwards to safely delete items from the list/array
            for i in range(len(project_deps) - 1, -1, -1):
                dep_item = project_deps[i]
                dep_str = str(dep_item)
                # Logic to extract package name from dependency string
                package_name = (
                    dep_str.split(";")[0]
                    .split("<")[0]
                    .split(">")[0]
                    .split("=")[0]
                    .split("~")[0]
                    .split("!")[0]
                    .strip()
                    .lower()
                )

                if package_name in unused_packages:
                    print(f"   -> Removing standard dependency: **{dep_item}**")
                    # Delete the item in place
                    del project_deps[i]

    # 2. Handle Poetry/Tool-specific dependencies (Table of key-value pairs)
    if (
        "tool" in doc
        and "poetry" in doc["tool"]
        and "dependencies" in doc["tool"]["poetry"]
    ):
        poetry_deps = doc["tool"]["poetry"]["dependencies"]
        if isinstance(poetry_deps, tomlkit.items.Table):
            keys_to_remove = set()
            for pkg, _ in poetry_deps.items():
                if pkg.lower() in unused_packages and pkg.lower() != "python":
                    keys_to_remove.add(pkg)

            for pkg in keys_to_remove:
                print(f"   -> Removing Poetry dependency: **{pkg}**")
                # Delete the key in place
                del poetry_deps[pkg]

    # 3. Write the modified document back
    try:
        with open(pyproject_path, "w", encoding="utf-8") as f:
            f.write(doc.as_string())
        print(
            f"\n✅ Successfully updated **{pyproject_path}**. Remember to **update your lock file**!"
        )
    except Exception as e:
        print(f"\n❌ Failed to write to {pyproject_path}: {e}")
