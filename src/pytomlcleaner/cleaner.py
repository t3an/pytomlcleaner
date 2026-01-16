"""
Core dependency analysis and cleaning module for pytomlcleaner.

MAIN FUNCTIONS:
===============
- discover_used_packages()       → Scan code and return used packages
- populate_pyproject_toml()      → Generate/populate pyproject.toml from code
- find_unused_dependencies()     → Compare declared vs actual dependencies
- remove_unused_dependencies()   → Remove unused from pyproject.toml

WORKFLOW STRATEGY:
==================

For EMPTY pyproject.toml:
  1. discover_used_packages() → scan codebase
  2. populate_pyproject_toml() → create file with dependencies

For EXISTING pyproject.toml:
  1. find_unused_dependencies() → identify unused packages
  2. remove_unused_dependencies() → remove unused with confirmation

See COMPLETE_WORKFLOW.md for detailed examples.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from difflib import SequenceMatcher
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Any, Dict, List, Set, cast

import tomlkit

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

# --- Comprehensive Static Mapping ---
# Maps package names (as they appear in pyproject.toml) to their import names
BASE_MAPPING = {
    # Computer Vision
    "opencv-python": ["cv2"],
    "opencv-contrib-python": ["cv2"],
    # Data Science & ML
    "scikit-learn": ["sklearn"],
    "scikit-image": ["skimage"],
    "tensorboard": ["tensorboard"],
    # Image & Data Processing
    "pillow": ["PIL"],
    "beautifulsoup4": ["bs4"],
    "pyyaml": ["yaml"],
    # Git & Version Control
    "gitpython": ["git"],
    # Environment & Config
    "python-dotenv": ["dotenv"],
    # Web Frameworks & HTTP
    "fastapi": ["fastapi"],
    "uvicorn": ["uvicorn"],
    "uvloop": ["uvloop"],
    "starlette": ["starlette"],
    "httpx": ["httpx"],
    # Utilities
    "python-multipart": ["multipart"],
    "pyjwt": ["jwt"],
    "python-jose": ["jose"],
    "typing-extensions": ["typing_extensions"],
    # DVC (Data Version Control)
    "dvc": ["dvc"],
    # Download utilities
    "gdown": ["gdown"],
}

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


def normalize_name(name: str) -> str:
    """Normalize a name by removing hyphens, underscores, and converting to lowercase."""
    return name.replace("-", "").replace("_", "").lower()


def is_similar(package_name: str, import_name: str, threshold: float = 0.6) -> bool:
    """
    Check if a package name and an import name are similar using sequence matching.

    The comparison is performed on normalized names (lowercased with hyphens and
    underscores removed). Exact matches and simple substring relations are treated
    as similar without consulting the fuzzy matcher.

    For non-trivial cases, :class:`difflib.SequenceMatcher` is used to compute a
    similarity ratio in the range [0.0, 1.0]. The ``threshold`` parameter controls
    how strict this fuzzy comparison is:

    * The default value of ``0.6`` was chosen as a pragmatic balance between
      catching common naming variations (for example, ``"pandas-datareader"``
      vs. ``"pandas_datareader"`` or shortened import names) and avoiding
      spurious matches between unrelated packages and modules.
    * Increasing the threshold (e.g. to ``0.8`` or ``0.9``) makes matching more
      conservative: you will see fewer matches, reducing false positives but
      potentially missing legitimate dependencies that use slightly different
      names.
    * Decreasing the threshold (e.g. to ``0.4`` or ``0.5``) makes matching more
      permissive: you will see more matches, which can help discover loosely
      related names but increases the risk of false positives in dependency
      detection.

    Parameters
    ----------
    package_name:
        The name of the installed/discovered package.
    import_name:
        The name as it appears in an import statement in the codebase.
    threshold:
        Minimum similarity ratio required for the two names to be considered
        a match. Defaults to ``0.6``.
    """
    # Normalize both names for comparison
    norm_pkg = normalize_name(package_name)
    norm_imp = normalize_name(import_name)

    # Check for exact match or substring
    if norm_pkg == norm_imp:
        return True
    if norm_pkg in norm_imp or norm_imp in norm_pkg:
        return True

    # Use sequence matching for fuzzy comparison
    similarity = SequenceMatcher(None, norm_pkg, norm_imp).ratio()
    return similarity >= threshold


# --- Core Dependency Analyzer Class ---


class DependencyAnalyzer:
    """Comprehensive dependency analyzer supporting Python files, shell scripts, and YAML configs."""

    def __init__(self, root_dir: str = "."):
        self.root = Path(root_dir)
        self.found_imports: Set[str] = set()
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Loads [tool.pytomlcleaner] from pyproject.toml for custom mappings and ignore lists."""
        path = self.root / "pyproject.toml"
        if not path.exists():
            return {}
        try:
            # tomllib.load() requires binary mode
            with open(path, "rb") as f:
                data = tomllib.load(f)
            return data.get("tool", {}).get("pytomlcleaner", {})
        except Exception as e:
            print(f"⚠️ Warning: Could not load pytomlcleaner config: {e}")
            return {}

    def get_import_names_for_package(self, package_name: str) -> List[str]:
        """
        Resolves PyPI package name to possible import names.
        Priority order: custom mappings → BASE_MAPPING → installed package metadata → standard normalization
        """
        normalized = package_name.lower().replace("_", "-")

        # Priority 1: User Custom Mappings from [tool.pytomlcleaner]
        custom = self.config.get("custom_mappings", {})
        if normalized in custom:
            custom_imports = custom[normalized]
            # Handle both string and list formats
            return (
                custom_imports if isinstance(custom_imports, list) else [custom_imports]
            )

        # Priority 2: Hardcoded BASE_MAPPING
        if normalized in BASE_MAPPING:
            return BASE_MAPPING[normalized]

        # Priority 3: Dynamic Metadata Lookup (if package is installed)
        try:
            dist = distribution(package_name)
            top_level_file = dist.read_text("top_level.txt")
            if top_level_file:
                return [
                    line.strip() for line in top_level_file.splitlines() if line.strip()
                ]
        except PackageNotFoundError:
            # Package is not installed; fall back to standard normalization below.
            pass
        except Exception as e:
            print(
                f"⚠️ Warning: Error reading metadata for package '{package_name}': {e}"
            )

        # Priority 4: Standard Normalization (replace hyphens with underscores)
        return [package_name.replace("-", "_")]

    def scan_python_files(self) -> None:
        """AST-based scanning of Python files to extract all imports."""
        for py_file in self.root.rglob("*.py"):
            # Skip excluded directories
            if any(excluded in py_file.parts for excluded in EXCLUDE_DIRS):
                continue

            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content, filename=str(py_file))

                for node in ast.walk(tree):
                    # Handle 'import x, y.z'
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            # Extract all parts of the module path
                            parts = alias.name.split(".")
                            for part in parts:
                                if part:  # Skip empty strings
                                    self.found_imports.add(part.lower())

                    # Handle 'from x.y.z import a, b'
                    elif isinstance(node, ast.ImportFrom):
                        # Extract all parts of the module path
                        if node.module:
                            parts = node.module.split(".")
                            for part in parts:
                                if part:  # Skip empty strings
                                    self.found_imports.add(part.lower())

                        # Also extract the imported names themselves
                        for alias in node.names:
                            if alias.name != "*":  # Skip wildcard imports
                                self.found_imports.add(alias.name.lower())

                # Fallback regex for edge cases (type checking guards, conditionals)
                matches = re.findall(r"(?:import|from)\s+([a-zA-Z0-9_.]+)", content)
                for match in matches:
                    parts = match.split(".")
                    for part in parts:
                        if part:  # Skip empty strings
                            self.found_imports.add(part.lower())

            except Exception as e:
                print(f"⚠️ Could not parse {py_file}: {e}")

    def scan_non_python_files(self) -> None:
        """
        Regex scanning for shell scripts, YAML, and Dockerfiles to detect CLI tool usage.
        This helps catch packages used as command-line tools (e.g., gdown, dvc).
        """
        extensions = [".sh", ".yml", ".yaml", "Dockerfile", ".txt"]

        for ext in extensions:
            for file_path in self.root.rglob(f"*{ext}"):
                # Skip excluded directories
                if any(excluded in file_path.parts for excluded in EXCLUDE_DIRS):
                    continue

                try:
                    content = file_path.read_text(encoding="utf-8")

                    # Look for known CLI tools/packages used in scripts
                    # This check is done against BASE_MAPPING and all package names
                    for pkg_name in BASE_MAPPING.keys():
                        # Use word boundary to avoid partial matches
                        if re.search(
                            rf"\b{re.escape(pkg_name.replace('_', '-'))}\b", content
                        ):
                            self.found_imports.add(pkg_name.lower())

                except Exception:
                    # Skip files that can't be read (binary, encoding issues, etc.)
                    continue

    def identify_unused(self, declared_deps: List[str]) -> List[str]:
        """
        Compares declared dependencies against found imports using exact and fuzzy matching.
        Returns list of packages that appear to be unused.
        """
        unused = []
        user_ignores = set(self.config.get("ignore", []))

        for dep in declared_deps:
            dep_lower = dep.lower()

            # Skip user-ignored packages
            if dep_lower in user_ignores:
                continue

            # Skip always-ignored packages
            if dep_lower in IGNORE_PACKAGES:
                continue

            # Get all possible import names for this package
            possible_imports = self.get_import_names_for_package(dep)

            # Check if ANY of the possible import names were found in scanned code
            found = False

            # First, try exact matching
            for import_name in possible_imports:
                if import_name.lower() in self.found_imports:
                    found = True
                    break

            # If not found by exact match, try similarity matching
            if not found:
                for found_import in self.found_imports:
                    # Check similarity with package name
                    if is_similar(dep, found_import):
                        found = True
                        break
                    # Check similarity with each possible import name
                    for import_name in possible_imports:
                        if is_similar(import_name, found_import):
                            found = True
                            break
                    if found:
                        break

            if not found:
                unused.append(dep)

        return unused


# --- Legacy Functions for Backward Compatibility ---


def get_dependencies(path: str = "pyproject.toml") -> Set[str]:
    """Reads project dependencies from pyproject.toml, targeting PEP 621 and Poetry styles."""
    dependencies: set[str] = set()

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
    """
    Scans all .py files and non-Python files in a directory for imports using AST,
    regex patterns, and shell script analysis. Uses improved DependencyAnalyzer internally.
    """
    analyzer = DependencyAnalyzer(root_dir)

    # Scan Python files via AST
    analyzer.scan_python_files()

    # Scan shell/YAML files for CLI tool usage
    analyzer.scan_non_python_files()

    # Filter out standard library modules and local modules
    final_imports = set()
    for imp in analyzer.found_imports:
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
    Uses the new DependencyAnalyzer for improved accuracy.
    """
    # Create analyzer and run scans
    analyzer = DependencyAnalyzer(code_root)
    analyzer.scan_python_files()
    analyzer.scan_non_python_files()

    # Get declared dependencies
    project_dependencies = get_dependencies(pyproject_path)

    # Identify unused
    unused_deps = analyzer.identify_unused(list(project_dependencies))

    return set(unused_deps)


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
    if "project" in doc:
        project_section = cast(tomlkit.items.Table, doc["project"])
        if "dependencies" in project_section:
            project_deps = cast(tomlkit.items.Array, project_section["dependencies"])
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
    if "tool" in doc:
        tool_section = cast(tomlkit.items.Table, doc["tool"])
        if "poetry" in tool_section:
            poetry_section = cast(tomlkit.items.Table, tool_section["poetry"])
            if "dependencies" in poetry_section:
                poetry_deps = cast(tomlkit.items.Table, poetry_section["dependencies"])
                if isinstance(poetry_deps, tomlkit.items.Table):
                    keys_to_remove = set()
                    for pkg, _ in poetry_deps.items():
                        if pkg.lower() in unused_packages and pkg.lower() != "python":
                            keys_to_remove.add(pkg)

                    for pkg in keys_to_remove:
                        print(f"   -> Removing Poetry dependency: **{pkg}**")
                        # Delete the key in place
                        del poetry_deps[pkg]  # type: ignore

    # 3. Write the modified document back
    try:
        with open(pyproject_path, "w", encoding="utf-8") as f:
            f.write(doc.as_string())
        print(
            f"\n✅ Successfully updated **{pyproject_path}**. Remember to **update your lock file**!"
        )
    except Exception as e:
        print(f"\n❌ Failed to write to {pyproject_path}: {e}")


def discover_used_packages(code_root: str = ".") -> List[str]:
    """
    Discovers all packages actually used in the codebase by scanning for imports.
    Returns a sorted list of package names that should be included in dependencies.
    Excludes standard library, local modules, and ignore packages.
    """
    analyzer = DependencyAnalyzer(code_root)
    analyzer.scan_python_files()
    analyzer.scan_non_python_files()

    # Get all found imports
    found_imports = analyzer.found_imports.copy()

    # Filter out stdlib and local modules
    used_packages = set()
    for imp in found_imports:
        if (
            imp not in STDLIB
            and not is_local_module(imp, code_root)
            and imp not in IGNORE_PACKAGES
        ):
            used_packages.add(imp)

    # Map import names back to package names using reverse mapping
    discovered_packages = set()

    # First, try to resolve each import to a package name
    for imp in used_packages:
        found_package = False

        # Check BASE_MAPPING (reverse lookup)
        for pkg_name, import_names in BASE_MAPPING.items():
            if imp in [i.lower() for i in import_names]:
                discovered_packages.add(pkg_name)
                found_package = True
                break

        if not found_package:
            # Try to find installed package with this import name
            try:
                # Try as-is first
                dist = distribution(imp)
                discovered_packages.add(dist.metadata["Name"].lower())
            except PackageNotFoundError:
                try:
                    # Try with underscores converted to hyphens
                    dist = distribution(imp.replace("_", "-"))
                    discovered_packages.add(dist.metadata["Name"].lower())
                except PackageNotFoundError:
                    # If not found, add the import name itself (user will need to verify)
                    discovered_packages.add(imp)

    return sorted(list(discovered_packages))


def populate_pyproject_toml(
    pyproject_path: str = "pyproject.toml", code_root: str = ".", force: bool = False
) -> bool:
    """
    Discovers used packages and populates pyproject.toml if it's empty or missing.

    Args:
        pyproject_path: Path to pyproject.toml file
        code_root: Root directory to scan for imports
        force: If True, overwrites existing dependencies; if False, only adds to empty files

    Returns:
        True if file was created/updated, False otherwise
    """
    print(f"🔍 Discovering packages used in {code_root}...")

    # Discover packages
    discovered_packages = discover_used_packages(code_root)

    if not discovered_packages:
        print("⚠️ No packages discovered in codebase.")
        return False

    print(f"\n✅ Found **{len(discovered_packages)}** package(s) used in the codebase:")
    for pkg in discovered_packages:
        print(f"   • {pkg}")

    # Check if pyproject.toml exists and is empty/minimal
    pyproject_path_obj = Path(pyproject_path)
    is_empty = False
    doc = tomlkit.document()

    if pyproject_path_obj.exists():
        try:
            with open(pyproject_path, "r", encoding="utf-8") as f:
                doc = tomlkit.load(f)

            # Check if dependencies section exists and has content
            existing_deps = doc.get("project", {}).get("dependencies", []) or doc.get(
                "tool", {}
            ).get("poetry", {}).get("dependencies", {})

            if not existing_deps and not force:
                is_empty = True
                print("\n⚠️ pyproject.toml exists but has no dependencies section.")
            elif existing_deps and not force:
                print(
                    "\n⚠️ pyproject.toml already has dependencies. Use --force to overwrite."
                )
                return False
        except Exception as e:
            print(f"⚠️ Could not read pyproject.toml: {e}")
            if not force:
                return False
    else:
        is_empty = True

    # If file doesn't exist or is empty, create/populate it
    if is_empty or force:
        print("\n📝 Populating pyproject.toml with discovered packages...")

        # Ensure project section exists
        if "project" not in doc:
            doc["project"] = tomlkit.table()

        project_section = cast(tomlkit.items.Table, doc["project"])

        # Set basic project metadata if not present
        if "name" not in project_section:
            project_section["name"] = Path(code_root).name or "my-project"

        if "version" not in project_section:
            project_section["version"] = "0.1.0"

        if "description" not in project_section:
            project_section["description"] = ""

        # Add dependencies
        dependencies = [f"{pkg}" for pkg in discovered_packages]
        project_section["dependencies"] = dependencies

        # Write to file
        try:
            pyproject_path_obj.parent.mkdir(parents=True, exist_ok=True)
            with open(pyproject_path, "w", encoding="utf-8") as f:
                f.write(doc.as_string())
            print(f"\n✅ Successfully created/updated **{pyproject_path}**")
            print(
                f"   Added **{len(discovered_packages)}** dependencies to [project.dependencies]"
            )
            return True
        except Exception as e:
            print(f"\n❌ Failed to write to {pyproject_path}: {e}")
            return False

    return False
