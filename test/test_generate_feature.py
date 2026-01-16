"""Test the new --generate feature for auto-populating pyproject.toml"""

import os
import sys
import tempfile
from pathlib import Path

# Add src to path to import the module
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pytomlcleaner.cleaner import discover_used_packages, populate_pyproject_toml


def test_discover_packages_in_sample_project():
    """Test discovering packages from a sample project"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a sample Python file with imports
        sample_dir = Path(tmpdir) / "sample_project"
        sample_dir.mkdir()

        (sample_dir / "main.py").write_text(
            """
import os
import sys
import json
import requests
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Item(BaseModel):
    name: str
    price: float

@app.get("/")
def read_root():
    df = pd.DataFrame()
    response = requests.get("https://example.com")
    return {"message": "Hello"}
"""
        )

        # Discover packages
        packages = discover_used_packages(str(sample_dir))

        print(f"✅ Discovered packages: {packages}")

        # Should find external packages (not stdlib like os, sys, json)
        external_packages = {pkg.lower() for pkg in packages}
        print(f"External packages found: {external_packages}")

        # Should contain packages from imports
        assert any(
            "requests" in pkg.lower() for pkg in packages
        ), "Should find requests"
        assert any("fastapi" in pkg.lower() for pkg in packages), "Should find fastapi"
        assert any("pandas" in pkg.lower() for pkg in packages), "Should find pandas"

        print("✨ Test passed: Package discovery works!\n")


def test_populate_empty_pyproject():
    """Test populating an empty pyproject.toml"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create sample code
        code_dir = tmpdir / "myproject"
        code_dir.mkdir()

        (code_dir / "main.py").write_text(
            """
import requests
import json
from bs4 import BeautifulSoup
"""
        )

        # Path for new pyproject.toml
        pyproject_path = tmpdir / "pyproject.toml"

        # Populate it
        success = populate_pyproject_toml(
            pyproject_path=str(pyproject_path), code_root=str(code_dir), force=False
        )

        assert success, "Should successfully create pyproject.toml"
        assert pyproject_path.exists(), "pyproject.toml should be created"

        # Read and verify content
        content = pyproject_path.read_text()
        print("Generated pyproject.toml:")
        print(content)

        assert "[project]" in content, "Should have [project] section"
        assert "dependencies" in content, "Should have dependencies"

        print("\n✨ Test passed: Empty pyproject.toml creation works!\n")


def test_populate_existing_pyproject():
    """Test that existing pyproject.toml is not overwritten without --force"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create sample code
        code_dir = tmpdir / "myproject"
        code_dir.mkdir()

        (code_dir / "main.py").write_text(
            """
import requests
"""
        )

        # Create existing pyproject.toml with dependencies
        pyproject_path = tmpdir / "pyproject.toml"
        pyproject_path.write_text(
            """
[project]
name = "existing-project"
version = "1.0.0"
dependencies = ["numpy"]
"""
        )

        # Try to populate without force
        success = populate_pyproject_toml(
            pyproject_path=str(pyproject_path), code_root=str(code_dir), force=False
        )

        assert not success, "Should not overwrite without force"

        # Content should be unchanged
        content = pyproject_path.read_text()
        assert "numpy" in content, "Should preserve original content"
        assert "requests" not in content, "Should not add new dependencies"

        print("✨ Test passed: Existing files are protected without --force\n")


def test_populate_with_force():
    """Test that force flag overwrites existing dependencies"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create sample code
        code_dir = tmpdir / "myproject"
        code_dir.mkdir()

        (code_dir / "main.py").write_text(
            """
import requests
from bs4 import BeautifulSoup
"""
        )

        # Create existing pyproject.toml
        pyproject_path = tmpdir / "pyproject.toml"
        pyproject_path.write_text(
            """
[project]
name = "old-project"
dependencies = ["numpy"]
"""
        )

        # Populate with force
        success = populate_pyproject_toml(
            pyproject_path=str(pyproject_path), code_root=str(code_dir), force=True
        )

        assert success, "Should successfully update with force"

        content = pyproject_path.read_text()
        print("Updated pyproject.toml with --force:")
        print(content)

        assert (
            "requests" in content or "beautifulsoup" in content
        ), "Should have new dependencies"

        print("\n✨ Test passed: Force flag overwrites correctly\n")


if __name__ == "__main__":
    print("=" * 60)
    print("Testing pytomlcleaner --generate feature")
    print("=" * 60 + "\n")

    test_discover_packages_in_sample_project()
    test_populate_empty_pyproject()
    test_populate_existing_pyproject()
    test_populate_with_force()

    print("=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)
