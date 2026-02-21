#!/usr/bin/env python3
"""Compile cBench benchmarks to LLVM bitcode (.bc) files."""

import os
import subprocess
import sys
from pathlib import Path

LLVM_BIN = "/opt/homebrew/opt/llvm@16/bin"
CLANG = f"{LLVM_BIN}/clang"
LLVM_LINK = f"{LLVM_BIN}/llvm-link"

SCRIPT_DIR = Path(__file__).parent.parent  # Go up from src/ to project root
CBENCH_DIR = SCRIPT_DIR / "benchmarks" / "source" / "lac-dcc-benchmarks" / "cBench"
OUTPUT_DIR = SCRIPT_DIR / "benchmarks" / "compiled"

# Map: cBench directory name -> output name (matching advisor's naming)
BENCH_MAP = {
    "telecom_adpcm_c": "adpcm_c",
    "telecom_adpcm_d": "adpcm_d",
    "automotive_bitcount": "bitcount",
    "security_blowfish_d": "blowfish_d",
    "security_blowfish_e": "blowfish_e",
    "telecom_CRC32": "crc32",
    "network_dijkstra": "dijkstra",
    "consumer_jpeg_c": "jpeg_c",
    "consumer_jpeg_d": "jpeg_d",
    "security_pgp_e": "pgp_e",
    "automotive_qsort1": "qsort1",
    "security_rijndael_d": "rijndael_d",
    "security_rijndael_e": "rijndael_e",
    "office_rsynth": "rsynth",
    "security_sha": "sha",
    "office_stringsearch1": "stringsearch1",
    "automotive_susan_c": "susan_c",
    "automotive_susan_e": "susan_e",
    "automotive_susan_s": "susan_s",
}


def compile_benchmark(bench_dir: str, bench_name: str) -> bool:
    src_dir = CBENCH_DIR / bench_dir / "src"
    if not src_dir.is_dir():
        print(f"  SKIP: {bench_dir} (no src directory)")
        return False

    c_files = sorted(src_dir.glob("*.c"))
    if not c_files:
        print(f"  SKIP: {bench_dir} (no .c files)")
        return False

    # Compile each .c to .bc
    bc_files = []
    for c_file in c_files:
        bc_file = f"/tmp/{c_file.stem}.bc"
        cmd = [
            CLANG, "-c", "-emit-llvm", "-O0",
            "-Xclang", "-disable-O0-optnone",  # allow opt to optimize
            "-w", "-Wno-everything",
            "-Wno-implicit-function-declaration",
            "-Wno-int-conversion",
            "-std=gnu89",
            f"-I{src_dir}",
            "-o", bc_file,
            str(c_file),
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            print(f"  FAIL: {bench_dir} (compile error: {c_file.name})")
            print(f"         {result.stderr.decode()[:200]}")
            return False
        bc_files.append(bc_file)

    # Link into single .bc
    output = OUTPUT_DIR / f"{bench_name}.bc"
    if len(bc_files) == 1:
        subprocess.run(["cp", bc_files[0], str(output)])
    else:
        cmd = [LLVM_LINK] + bc_files + ["-o", str(output)]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            print(f"  FAIL: {bench_dir} (link error)")
            print(f"         {result.stderr.decode()[:200]}")
            return False

    # Cleanup temp files
    for f in bc_files:
        os.unlink(f)

    size = output.stat().st_size
    print(f"  OK: {bench_name}.bc ({size} bytes, {len(c_files)} source files)")
    return True


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    success = 0
    fail = 0

    for bench_dir, bench_name in sorted(BENCH_MAP.items()):
        if compile_benchmark(bench_dir, bench_name):
            success += 1
        else:
            fail += 1

    print(f"\nDone: {success} success, {fail} failed")
    print(f"Output: {OUTPUT_DIR}/")

    for f in sorted(OUTPUT_DIR.glob("*.bc")):
        print(f"  {f.name}: {f.stat().st_size} bytes")


if __name__ == "__main__":
    main()
