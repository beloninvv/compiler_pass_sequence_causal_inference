#!/usr/bin/env python3
"""
Select a diverse subset of AnghaBench files and compile to LLVM bitcode.

Expects the AnghaBench repo cloned at benchmarks/source/anghabench_repo/.
Picks N files per project (preferring medium-sized, ~1-8KB), compiles each
to a separate .bc file.

Usage:
    python3 src/compile_anghabench.py [--num-per-project 2] [--dry-run]
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
ANGHA_REPO = PROJECT_ROOT / "benchmarks" / "source" / "anghabench"
OUTPUT_DIR = PROJECT_ROOT / "benchmarks" / "compiled"

LLVM_BIN = "/opt/homebrew/opt/llvm@16/bin"
CLANG = f"{LLVM_BIN}/clang"

MIN_SIZE = 500
MAX_SIZE = 10000
IDEAL_SIZE = 3000  # prefer files around this size


def find_suitable_files(project_dir: Path, num: int) -> list[Path]:
    """Find .c files of suitable size, preferring medium-sized ones."""
    c_files = []
    for f in project_dir.rglob("*.c"):
        size = f.stat().st_size
        if MIN_SIZE <= size <= MAX_SIZE:
            c_files.append((abs(size - IDEAL_SIZE), f))

    # Sort by distance from ideal size, pick top N
    c_files.sort(key=lambda x: x[0])
    return [f for _, f in c_files[:num]]


def compile_c_to_bc(c_file: Path, bc_file: Path) -> bool:
    """Compile a single AnghaBench .c file to .bc."""
    cmd = [
        CLANG, "-c", "-emit-llvm", "-O0",
        "-Xclang", "-disable-O0-optnone",
        "-g0", "-w",
        "-Wno-implicit-function-declaration",
        "-Wno-int-conversion",
        "-Wno-implicit-int",
        "-std=gnu89",
        "-o", str(bc_file),
        str(c_file),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Compile AnghaBench subset to bitcode")
    parser.add_argument("--num-per-project", type=int, default=2,
                        help="Number of files per project (default: 2)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only list files, don't compile")
    args = parser.parse_args()

    if not ANGHA_REPO.exists():
        print(f"ERROR: AnghaBench repo not found at {ANGHA_REPO}", file=sys.stderr)
        print("Clone it: git clone --depth 1 https://github.com/brenocfg/AnghaBench.git "
              f"{ANGHA_REPO}", file=sys.stderr)
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Discover projects (top-level directories)
    projects = sorted([d for d in ANGHA_REPO.iterdir()
                       if d.is_dir() and not d.name.startswith(".")])

    print(f"Found {len(projects)} projects in AnghaBench")
    print(f"Selecting up to {args.num_per_project} files per project\n")

    total_selected = 0
    total_compiled = 0
    total_failed = 0

    for project_dir in projects:
        project_name = project_dir.name
        files = find_suitable_files(project_dir, args.num_per_project)

        if not files:
            continue

        for c_file in files:
            # Create a clean name: anghabench__project__filename
            clean_stem = c_file.stem.replace(".", "_").replace("-", "_")
            bc_name = f"anghabench__{project_name}__{clean_stem}"
            bc_file = OUTPUT_DIR / f"{bc_name}.bc"

            total_selected += 1

            if args.dry_run:
                print(f"  {bc_name} ({c_file.stat().st_size} bytes)")
                continue

            if bc_file.exists():
                total_compiled += 1
                continue

            if compile_c_to_bc(c_file, bc_file):
                size = bc_file.stat().st_size
                print(f"  OK: {bc_name} ({size:,} bytes)")
                total_compiled += 1
            else:
                print(f"  FAIL: {bc_name}")
                total_failed += 1

    print(f"\n{'='*60}")
    print(f"Selected: {total_selected} files from {len(projects)} projects")
    if not args.dry_run:
        print(f"Compiled: {total_compiled} success, {total_failed} failed")
    print(f"Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
