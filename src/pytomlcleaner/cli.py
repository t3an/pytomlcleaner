# pytomlcleaner/cli.py

import argparse
from .cleaner import (
    find_unused_dependencies,
    remove_unused_dependencies,
    DependencyAnalyzer,
)

def main():
    parser = argparse.ArgumentParser(
        description="Find and optionally clean unused dependencies in pyproject.toml with advanced detection (Python files, shell scripts, YAML configs).",
        prog="pytomlcleaner",
    )
    parser.add_argument(
        "--path", 
        default=".", 
        help="Root directory of the Python project to scan (default: current directory)."
    )
    parser.add_argument(
        "--toml", 
        default="pyproject.toml", 
        help="Path to the pyproject.toml file (default: pyproject.toml)."
    )
    parser.add_argument(
        "--fix", 
        action="store_true", 
        help="Remove unused dependencies from pyproject.toml."
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed analysis including what was scanned.",
    )
    
    args = parser.parse_args()
    
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
    print(f"🚨 Found **{len(unused_packages)}** potentially unused package(s) in pyproject.toml:")
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
        confirm = input("Are you sure you want to proceed with removal? (y/N): ").strip().lower()
        
        if confirm == 'y':
            remove_unused_dependencies(args.toml, unused_packages)
        else:
            print("Action cancelled by user. No changes were made.")
    else:
        print("\n💡 To automatically remove these dependencies, run again with: `pytomlcleaner --fix`")
        print(
            "   Use `pytomlcleaner --verbose` to see detailed analysis and configuration options."
        )

if __name__ == "__main__":
    main()