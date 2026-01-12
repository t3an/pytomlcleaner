import os
import ast
import re
import tomlkit
from typing import Set, Dict, List, Any
import sys
from pathlib import Path
from importlib.metadata import distribution, PackageNotFoundError

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
    "pillow": ["pil"],
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
            pass
        except Exception as e:
            pass

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
                            # Split and add all top-level and sub-modules
                            parts = alias.name.split(".")
                            for i in range(len(parts)):
                                self.found_imports.add(parts[i].lower())

                    # Handle 'from x.y import z' - focus on module path
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        parts = node.module.split(".")
                        for i in range(len(parts)):
                            self.found_imports.add(parts[i].lower())

                # Fallback regex for edge cases (type checking guards, conditionals)
                matches = re.findall(r"(?:import|from)\s+([a-zA-Z0-9_.]+)", content)
                for match in matches:
                    parts = match.split(".")
                    for i in range(len(parts)):
                        self.found_imports.add(parts[i].lower())

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
        Compares declared dependencies against found imports.
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
            for import_name in possible_imports:
                if import_name.lower() in self.found_imports:
                    found = True
                    break

            if not found:
                unused.append(dep)

        return unused


# --- Legacy Functions for Backward Compatibility ---


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
