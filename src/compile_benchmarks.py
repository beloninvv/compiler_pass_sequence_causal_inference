#!/usr/bin/env python3
"""
Compile benchmark suites to LLVM bitcode (.bc) files.

Scans benchmark directories, compiles all .c files per program into individual
.bc files, then links them into a single .bc per program using llvm-link.

Usage:
    python3 src/compile_benchmarks.py [--suite SUITE_NAME] [--dry-run]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── Paths ──────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
LLVM_BIN = "/opt/homebrew/opt/llvm@16/bin"
CLANG = f"{LLVM_BIN}/clang"
LLVM_LINK = f"{LLVM_BIN}/llvm-link"

BENCHMARKS_SOURCE = PROJECT_ROOT / "benchmarks" / "source"
LAC_DCC = BENCHMARKS_SOURCE / "lac-dcc-benchmarks"
OUTPUT_DIR = PROJECT_ROOT / "benchmarks" / "compiled"

# ── Compilation flags ──────────────────────────────────────────────────────

BASE_CFLAGS = [
    "-c", "-emit-llvm", "-O0",
    "-Xclang", "-disable-O0-optnone",  # allow opt to optimize later
    "-g0",  # no debug info
    "-w",   # suppress all warnings
]

# Fallback flags for older C code
RELAXED_CFLAGS = [
    "-Wno-implicit-function-declaration",
    "-Wno-int-conversion",
    "-Wno-implicit-int",
    "-std=gnu89",
]


# ── Suite definitions ──────────────────────────────────────────────────────
# Each suite defines how to discover programs and their source files.

@dataclass
class Program:
    """A single benchmark program to compile."""
    name: str           # Output name (e.g., "cbench__bitcount")
    suite: str          # Suite name (e.g., "cBench")
    src_dirs: list      # Directories containing .c files
    include_dirs: list = field(default_factory=list)  # Additional -I paths
    extra_cflags: list = field(default_factory=list)  # Extra compiler flags


def discover_cbench() -> list[Program]:
    """cBench: each subdirectory with src/ is a program."""
    programs = []
    cbench_dir = LAC_DCC / "cBench"
    if not cbench_dir.exists():
        return programs

    skip = {"all__create_work_dirs", "all__delete_work_dirs", "all_compile",
            "all_run__1_dataset", "all_run__20_datasets",
            "automotive_susan_data", "bzip2_data", "consumer_data",
            "consumer_jpeg_data", "consumer_tiff_data"}

    for d in sorted(cbench_dir.iterdir()):
        if not d.is_dir() or d.name in skip:
            continue
        src_dir = d / "src"
        if src_dir.is_dir() and list(src_dir.glob("*.c")):
            programs.append(Program(
                name=f"cbench__{d.name}",
                suite="cBench",
                src_dirs=[src_dir],
                include_dirs=[src_dir],
            ))
    return programs


def discover_mibench() -> list[Program]:
    """MiBench: each subdirectory is a program, .c files at top level."""
    programs = []
    mibench_dir = LAC_DCC / "MiBench"
    if not mibench_dir.exists():
        return programs

    for d in sorted(mibench_dir.iterdir()):
        if not d.is_dir():
            continue
        c_files = list(d.glob("*.c"))
        if c_files:
            programs.append(Program(
                name=f"mibench__{d.name}",
                suite="MiBench",
                src_dirs=[d],
                include_dirs=[d],
            ))
    return programs


def discover_polybench() -> list[Program]:
    """PolyBench: programs are in category/subcategory/ dirs."""
    programs = []
    poly_dir = LAC_DCC / "PolyBench"
    utilities_dir = poly_dir / "utilities"
    if not poly_dir.exists():
        return programs

    categories = ["datamining", "linear-algebra/blas", "linear-algebra/kernels",
                  "linear-algebra/solvers", "medley", "stencils"]

    for cat in categories:
        cat_dir = poly_dir / cat
        if not cat_dir.exists():
            continue
        for d in sorted(cat_dir.iterdir()):
            if not d.is_dir():
                continue
            c_files = list(d.glob("*.c"))
            if c_files:
                cat_short = cat.replace("/", "_").replace("-", "_")
                programs.append(Program(
                    name=f"polybench__{cat_short}__{d.name}",
                    suite="PolyBench",
                    src_dirs=[d],
                    include_dirs=[d, utilities_dir],
                    extra_cflags=["-DPOLYBENCH_USE_C99_PROTO",
                                  "-DMEDIUM_DATASET"],
                ))
    return programs


def discover_flat_suite(suite_name: str, dir_name: Optional[str] = None) -> list[Program]:
    """Generic: each subdirectory is a program with .c files at top level or in src/."""
    programs = []
    suite_dir = LAC_DCC / (dir_name or suite_name)
    if not suite_dir.exists():
        return programs

    for d in sorted(suite_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        # Check for src/ subdirectory first, then top-level
        src_dir = d / "src" if (d / "src").is_dir() else d
        c_files = list(src_dir.glob("*.c"))
        if c_files:
            programs.append(Program(
                name=f"{suite_name.lower()}__{d.name}",
                suite=suite_name,
                src_dirs=[src_dir],
                include_dirs=[src_dir, d],
            ))
    return programs


def discover_mediabench() -> list[Program]:
    """mediabench: programs have deeper nesting (e.g., gsm/toast/)."""
    programs = []
    mb_dir = LAC_DCC / "mediabench"
    if not mb_dir.exists():
        return programs

    for d in sorted(mb_dir.iterdir()):
        if not d.is_dir():
            continue
        # Some have subdirectories with actual source
        for sub in sorted(d.iterdir()):
            if sub.is_dir() and list(sub.glob("*.c")):
                programs.append(Program(
                    name=f"mediabench__{d.name}__{sub.name}",
                    suite="mediabench",
                    src_dirs=[sub],
                    include_dirs=[sub, d],
                ))
        # Also check top-level .c files
        if list(d.glob("*.c")):
            programs.append(Program(
                name=f"mediabench__{d.name}",
                suite="mediabench",
                src_dirs=[d],
                include_dirs=[d],
            ))
    return programs


def discover_tsvc() -> list[Program]:
    """TSVC: each subdirectory is a test program."""
    programs = []
    tsvc_dir = LAC_DCC / "TSVC"
    if not tsvc_dir.exists():
        return programs

    for d in sorted(tsvc_dir.iterdir()):
        if not d.is_dir():
            continue
        c_files = list(d.glob("*.c"))
        if c_files:
            programs.append(Program(
                name=f"tsvc__{d.name}",
                suite="TSVC",
                src_dirs=[d],
                include_dirs=[d, tsvc_dir],  # for dummy.inc
            ))
    return programs


def discover_single_file_suite(suite_name: str,
                               dir_name: Optional[str] = None) -> list[Program]:
    """Suites where .c files at top level are individual programs."""
    programs = []
    suite_dir = LAC_DCC / (dir_name or suite_name)
    if not suite_dir.exists():
        return programs

    for c_file in sorted(suite_dir.glob("*.c")):
        programs.append(Program(
            name=f"{suite_name.lower()}__{c_file.stem}",
            suite=suite_name,
            src_dirs=[suite_dir],
            include_dirs=[suite_dir],
        ))
        # Override: only this one file
        programs[-1]._single_file = c_file
    return programs


# ── Compilation ────────────────────────────────────────────────────────────

def compile_c_to_bc(c_file: Path, bc_file: Path,
                    include_dirs: list[Path], extra_cflags: list[str]) -> bool:
    """Compile a single .c file to .bc. Returns True on success."""
    includes = []
    for d in include_dirs:
        includes.extend(["-I", str(d)])

    cmd = [CLANG] + BASE_CFLAGS + includes + extra_cflags + ["-o", str(bc_file), str(c_file)]

    result = subprocess.run(cmd, capture_output=True, timeout=60)
    if result.returncode == 0:
        return True

    # Retry with relaxed flags
    cmd = [CLANG] + BASE_CFLAGS + RELAXED_CFLAGS + includes + extra_cflags + [
        "-o", str(bc_file), str(c_file)]
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    return result.returncode == 0


def compile_program(prog: Program, output_dir: Path, dry_run: bool = False) -> bool:
    """Compile a program: all .c → .bc, then llvm-link → single .bc."""
    output_bc = output_dir / f"{prog.name}.bc"

    # Collect .c files
    if hasattr(prog, "_single_file"):
        c_files = [prog._single_file]
    else:
        c_files = []
        for src_dir in prog.src_dirs:
            c_files.extend(sorted(src_dir.glob("*.c")))

    if not c_files:
        return False

    if dry_run:
        print(f"  [DRY] {prog.name}: {len(c_files)} .c files")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        bc_files = []
        for c_file in c_files:
            bc_file = Path(tmpdir) / f"{c_file.stem}.bc"
            # Deduplicate: if stem already compiled, add suffix
            if bc_file.exists():
                bc_file = Path(tmpdir) / f"{c_file.stem}_{id(c_file)}.bc"

            if not compile_c_to_bc(c_file, bc_file, prog.include_dirs, prog.extra_cflags):
                print(f"  FAIL: {prog.name} (compile error: {c_file.name})")
                return False
            bc_files.append(bc_file)

        # Link
        if len(bc_files) == 1:
            shutil.copy2(bc_files[0], output_bc)
        else:
            cmd = [LLVM_LINK] + [str(f) for f in bc_files] + ["-o", str(output_bc)]
            result = subprocess.run(cmd, capture_output=True, timeout=120)
            if result.returncode != 0:
                print(f"  FAIL: {prog.name} (link error: {result.stderr.decode()[:200]})")
                return False

    size = output_bc.stat().st_size
    print(f"  OK: {prog.name} ({len(c_files)} files, {size:,} bytes)")
    return True


# ── Main ───────────────────────────────────────────────────────────────────

SUITE_DISCOVERERS = {
    "cBench": discover_cbench,
    "MiBench": discover_mibench,
    "PolyBench": discover_polybench,
    "Prolangs-C": lambda: discover_flat_suite("Prolangs-C"),
    "mediabench": discover_mediabench,
    "Olden": lambda: discover_flat_suite("Olden"),
    "FreeBench": lambda: discover_flat_suite("FreeBench"),
    "TSVC": discover_tsvc,
    "McCat": lambda: discover_flat_suite("McCat"),
    "Ptrdist": lambda: discover_flat_suite("Ptrdist"),
    "Stanford": lambda: discover_flat_suite("Stanford"),
    "SciMark2-C": lambda: discover_flat_suite("SciMark2-C"),
    "DOE_ProxyApps_C": lambda: discover_flat_suite("DOE_ProxyApps_C"),
    "Trimaran": lambda: discover_flat_suite("Trimaran"),
    "VersaBench": lambda: discover_flat_suite("VersaBench"),
    "Shootout": lambda: discover_flat_suite("Shootout"),
    "BenchmarkGame": lambda: discover_flat_suite("BenchmarkGame"),
    "CoyoteBench": lambda: discover_flat_suite("CoyoteBench"),
    "Misc": lambda: discover_flat_suite("Misc"),
    "BitBench": lambda: discover_flat_suite("BitBench"),
    "MallocBench": lambda: discover_flat_suite("MallocBench"),
    "McGill": lambda: discover_flat_suite("McGill"),
    "Dhrystone": lambda: discover_flat_suite("Dhrystone"),
    "Linpack": lambda: discover_flat_suite("Linpack"),
    "nbench": lambda: discover_flat_suite("nbench"),
    "NPB-serial": lambda: discover_flat_suite("NPB-serial"),
    "ASC_Sequoia": lambda: discover_flat_suite("ASC_Sequoia"),
    "ASCI_Purple": lambda: discover_flat_suite("ASCI_Purple"),
}


def main():
    parser = argparse.ArgumentParser(description="Compile benchmarks to LLVM bitcode")
    parser.add_argument("--suite", type=str, default=None,
                        help="Compile only this suite (e.g., 'cBench', 'PolyBench')")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only discover programs, don't compile")
    parser.add_argument("--output-dir", type=str, default=str(OUTPUT_DIR),
                        help=f"Output directory (default: {OUTPUT_DIR})")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Verify LLVM tools exist
    if not Path(CLANG).exists():
        print(f"ERROR: clang not found at {CLANG}", file=sys.stderr)
        sys.exit(1)
    if not Path(LLVM_LINK).exists():
        print(f"ERROR: llvm-link not found at {LLVM_LINK}", file=sys.stderr)
        sys.exit(1)

    # Discover programs
    suites = {args.suite: SUITE_DISCOVERERS[args.suite]} if args.suite else SUITE_DISCOVERERS
    all_programs = []
    for suite_name, discoverer in suites.items():
        programs = discoverer()
        all_programs.extend(programs)
        print(f"{suite_name}: {len(programs)} programs")

    print(f"\nTotal: {len(all_programs)} programs to compile")
    print(f"Output: {output_dir}/\n")

    if args.dry_run:
        for prog in all_programs:
            print(f"  {prog.name} ({len(prog.src_dirs)} src dirs)")
        return

    # Compile
    success = 0
    failed = []

    for prog in all_programs:
        if compile_program(prog, output_dir):
            success += 1
        else:
            failed.append(prog.name)

    # Summary
    print(f"\n{'='*60}")
    print(f"Done: {success} success, {len(failed)} failed out of {len(all_programs)}")
    print(f"Output: {output_dir}/")

    if failed:
        print(f"\nFailed programs:")
        for name in failed:
            print(f"  - {name}")

    # Save manifest
    manifest = {
        "total": len(all_programs),
        "success": success,
        "failed": len(failed),
        "failed_programs": failed,
        "programs": {},
    }
    for bc in sorted(output_dir.glob("*.bc")):
        manifest["programs"][bc.stem] = {
            "file": bc.name,
            "size": bc.stat().st_size,
        }

    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nManifest saved: {manifest_path}")


if __name__ == "__main__":
    main()
