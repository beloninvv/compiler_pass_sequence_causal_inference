#!/usr/bin/env python3
"""
Download a diverse subset of AnghaBench and compile to LLVM bitcode.

Strategy: pick N files from different projects, preferring medium-sized files
(more interesting IR than tiny or huge ones).

Usage:
    python3 src/download_anghabench.py [--num-per-project 2] [--compile]
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
ANGHA_DIR = PROJECT_ROOT / "benchmarks" / "source" / "anghabench"
OUTPUT_DIR = PROJECT_ROOT / "benchmarks" / "compiled"

LLVM_BIN = "/opt/homebrew/opt/llvm@16/bin"
CLANG = f"{LLVM_BIN}/clang"

GITHUB_API = "https://api.github.com/repos/brenocfg/AnghaBench/contents"
GITHUB_RAW = "https://raw.githubusercontent.com/brenocfg/AnghaBench/master"

# Target: files between 500 and 10000 bytes (interesting complexity)
MIN_SIZE = 500
MAX_SIZE = 10000


def github_api_get(path: str) -> list | dict | None:
    """Fetch from GitHub API with rate limit handling."""
    url = f"{GITHUB_API}/{path}" if path else GITHUB_API
    headers = {"Accept": "application/vnd.github.v3+json"}

    # Add token if available
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print(f"  Rate limited. Waiting 60s...")
            time.sleep(60)
            return github_api_get(path)
        elif e.code == 404:
            return None
        raise


def download_raw(path: str, dest: Path) -> bool:
    """Download a raw file from GitHub."""
    url = f"{GITHUB_RAW}/{path}"
    try:
        urllib.request.urlretrieve(url, dest)
        return True
    except Exception as e:
        print(f"  Download failed: {path}: {e}")
        return False


def find_c_files_in_subdir(project: str, subdir: str) -> list[dict]:
    """Find .c files in a project subdirectory."""
    path = f"{project}/{subdir}" if subdir else project
    items = github_api_get(path)
    if not items or not isinstance(items, list):
        return []
    return [i for i in items if i["name"].endswith(".c")
            and MIN_SIZE <= i.get("size", 0) <= MAX_SIZE]


def discover_project_files(project: str, num_files: int) -> list[dict]:
    """Find suitable .c files in a project, searching subdirectories."""
    # First, list top-level contents
    items = github_api_get(project)
    if not items or not isinstance(items, list):
        return []

    # Collect .c files from top level
    c_files = [i for i in items if i["name"].endswith(".c")
               and MIN_SIZE <= i.get("size", 0) <= MAX_SIZE]

    # If not enough, search subdirectories
    if len(c_files) < num_files:
        subdirs = [i["name"] for i in items if i["type"] == "dir"]
        for sd in subdirs[:5]:  # limit API calls
            c_files.extend(find_c_files_in_subdir(project, sd))
            if len(c_files) >= num_files * 3:  # enough to choose from
                break

    # Sort by size (prefer medium-sized) and pick
    c_files.sort(key=lambda f: abs(f["size"] - 3000))  # prefer ~3KB
    return c_files[:num_files]


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
    parser = argparse.ArgumentParser(description="Download AnghaBench subset")
    parser.add_argument("--num-per-project", type=int, default=2,
                        help="Number of files per project (default: 2)")
    parser.add_argument("--compile", action="store_true",
                        help="Also compile to .bc")
    parser.add_argument("--projects-file", type=str, default=None,
                        help="JSON file with project list (skip API discovery)")
    args = parser.parse_args()

    ANGHA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Get project list
    if args.projects_file and Path(args.projects_file).exists():
        with open(args.projects_file) as f:
            projects = json.load(f)
    else:
        print("Discovering projects from GitHub API...")
        items = github_api_get("")
        if not items:
            print("ERROR: Could not fetch repo contents", file=sys.stderr)
            sys.exit(1)
        projects = [i["name"] for i in items if i["type"] == "dir"]
        print(f"Found {len(projects)} projects")

        # Save for reuse
        proj_file = ANGHA_DIR / "projects.json"
        with open(proj_file, "w") as f:
            json.dump(projects, f, indent=2)
        print(f"Saved project list: {proj_file}")

    # Step 2: Download files
    total_downloaded = 0
    total_compiled = 0
    total_failed_compile = 0

    for i, project in enumerate(projects):
        print(f"\n[{i+1}/{len(projects)}] {project}...")
        project_dir = ANGHA_DIR / project
        project_dir.mkdir(exist_ok=True)

        # Check if already downloaded
        existing = list(project_dir.glob("*.c"))
        if len(existing) >= args.num_per_project:
            print(f"  Already have {len(existing)} files, skipping download")
            c_files_local = existing
        else:
            # Discover and download
            files = discover_project_files(project, args.num_per_project)
            if not files:
                print(f"  No suitable files found")
                continue

            c_files_local = []
            for f_info in files:
                # Extract relative path
                rel_path = f_info["path"]  # e.g., "curl/lib/extr_base64.c_..."
                local_name = f_info["name"]
                local_path = project_dir / local_name

                if local_path.exists():
                    c_files_local.append(local_path)
                    continue

                if download_raw(rel_path, local_path):
                    c_files_local.append(local_path)
                    total_downloaded += 1
                    print(f"  Downloaded: {local_name} ({f_info['size']} bytes)")

            time.sleep(0.5)  # Be nice to GitHub API

        # Step 3: Compile if requested
        if args.compile:
            for c_file in c_files_local:
                bc_name = f"anghabench__{project}__{c_file.stem}"
                bc_file = OUTPUT_DIR / f"{bc_name}.bc"

                if bc_file.exists():
                    total_compiled += 1
                    continue

                if compile_c_to_bc(c_file, bc_file):
                    size = bc_file.stat().st_size
                    print(f"  Compiled: {bc_name} ({size:,} bytes)")
                    total_compiled += 1
                else:
                    print(f"  FAIL compile: {c_file.name}")
                    total_failed_compile += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"Downloaded: {total_downloaded} files")
    if args.compile:
        print(f"Compiled: {total_compiled} success, {total_failed_compile} failed")
    print(f"Source dir: {ANGHA_DIR}")
    if args.compile:
        print(f"Output dir: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
