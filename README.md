# 🧹 pytomlcleaner

A command-line utility for identifying and optionally removing unused dependencies in your `pyproject.toml` file by statically analyzing your Python codebase. Keep your project dependencies lean and maintainable!

## ✨ Features

* **Static Code Analysis:** Scans your Python source files (`.py`) using the Abstract Syntax Tree (AST) to accurately detect imports.
* **TOML Support:** Correctly parses dependencies specified in `pyproject.toml` (supporting both PEP 621 `[project.dependencies]` and Poetry/Hatch `[tool.*.dependencies]`).
* **Safe Modification:** Uses `tomlkit` to modify the `pyproject.toml` file, preserving existing comments, formatting, and indentation.
* **Python Compatibility:** Supports Python **3.9+**.
* **Standard Library Filtering:** Uses `stdlib-list` to accurately ignore built-in Python modules.

## 📥 Installation

`pytomlcleaner` is available on PyPI.

```bash
pip install pytomlcleaner

```

```bash
uv add pytomlcleaner

```



## 🚀 Usage

To use `pytomlcleaner`, simply run the following command in your terminal:

```bash
pytomlcleaner 
pytomlcleaner --fix
```

