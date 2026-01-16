# pytomlcleaner/cli.py
"""
Command-line interface for pytomlcleaner.

RECOMMENDED WORKFLOW:
=====================

1. IF pyproject.toml is EMPTY or MISSING:
   $ pytomlcleaner --generate          # Generate from code
   $ vi pyproject.toml                 # Add version specifiers
   $ pytomlcleaner --verbose           # Verify (optional)
   $ pytomlcleaner --fix               # Remove false positives

2. IF pyproject.toml EXISTS and HAS DEPENDENCIES:
   $ pytomlcleaner --verbose           # Analyze/find unused
   $ pytomlcleaner --fix               # Remove unused packages

USAGE EXAMPLES:
===============

Generate new file:
  pytomlcleaner --generate

Analyze current state:
  pytomlcleaner                       # Find unused packages
  pytomlcleaner --verbose             # Detailed analysis

Clean up:
  pytomlcleaner --fix                 # Remove unused (with confirmation)

For more details, see COMPLETE_WORKFLOW.md
"""

import argparse
from .cleaner import (
    find_unused_dependencies,
    remove_unused_dependencies,
    DependencyAnalyzer,
    populate_pyproject_toml,
)


def main():
    parser = argparse.ArgumentParser(
        description="Find and optionally clean unused dependencies in pyproject.toml with advanced detection (Python files, shell scripts, YAML configs). Can also discover and populate pyproject.toml.",
        prog="pytomlcleaner",
    )
    parser.add_argument(
        "--path",
        default=".",
        help="Root directory of the Python project to scan (default: current directory).",
    )
    parser.add_argument(
        "--toml",
        default="pyproject.toml",
        help="Path to the pyproject.toml file (default: pyproject.toml).",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Remove unused dependencies from pyproject.toml.",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Discover packages used in codebase and populate pyproject.toml if empty.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force overwrite dependencies when using --generate (use with caution).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed analysis including what was scanned.",
    )

    args = parser.parse_args()

    # Handle --generate mode
    if args.generate:
        print(f"🔎 Generating pyproject.toml from codebase in **{args.path}**...\n")
        success = populate_pyproject_toml(
            pyproject_path=args.toml, code_root=args.path, force=args.force
        )
        if success:
            print(f"💡 Next steps:")
            print(f"   1. Review the generated {args.toml}")
            print(f"   2. Add version specifiers if needed (e.g., 'package>=1.0.0')")
            print(f"   3. Run 'pytomlcleaner --fix' to remove any unused dependencies")
        return

    print(f"Scanning code in **{args.path}** and dependencies in **{args.toml}**...")

    if args.verbose:
        print("📊 Analysis includes:")
        print("  • Python files (AST-based import detection)")
        print("  • Shell scripts (.sh)")
        print("  • YAML/Docker configs (.yml, .yaml, Dockerfile)")
        print("  • Package name mismatches (via BASE_MAPPING + installed metadata)")
        print()

    # 1. Find unused packages
    unused_packages = find_unused_dependencies(args.path, args.toml)

    if not unused_packages:
        print("\n✨ No potentially unused packages found in pyproject.toml.")
        return

    print("\n---")
    print(
        f"🚨 Found **{len(unused_packages)}** potentially unused package(s) in pyproject.toml:"
    )
    for pkg in sorted(unused_packages):
        print(f"- **{pkg}**")
    print("---")

    if args.verbose:
        print("\n📝 To keep packages that appear unused:")
        print("   1. Add to [tool.pytomlcleaner] ignore list in pyproject.toml:")
        print("      [tool.pytomlcleaner]")
        print('      ignore = ["package-name"]')
        print("   2. Or add custom import mappings for non-standard imports:")
        print("      [tool.pytomlcleaner]")
        print('      custom_mappings = { "package-name" = ["import_name"] }')
        print()

    # 2. Apply fix if requested
    if args.fix:
        print("🗑️ Attempting to remove unused dependencies from pyproject.toml...")

        # Confirmation step
        confirm = (
            input("Are you sure you want to proceed with removal? (y/N): ")
            .strip()
            .lower()
        )

        if confirm == "y":
            remove_unused_dependencies(args.toml, unused_packages)
        else:
            print("Action cancelled by user. No changes were made.")
    else:
        print(
            "\n💡 To automatically remove these dependencies, run again with: `pytomlcleaner --fix`"
        )
        print(
            "   Use `pytomlcleaner --verbose` to see detailed analysis and configuration options."
        )


if __name__ == "__main__":
    main()
