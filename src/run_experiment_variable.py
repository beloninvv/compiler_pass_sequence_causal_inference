#!/usr/bin/env python3
"""
Run random VARIABLE-LENGTH permutations of LLVM passes on benchmarks.
Compares against -Oz baseline.

Usage:
    python3 src/run_experiment_variable.py --benchmarks-dir ./benchmarks/compiled \\
        --num-iterations 5000 --min-length 10 --max-length 30
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple


# Oz passes for old pass manager (legacy PM)
OZ_PASSES_OLDPM = [
    "-enable-new-pm=0", "-bdce", "-ipsccp", "-correlated-propagation",
    "-mem2reg", "-sroa", "-instsimplify", "-constmerge", "-function-attrs",
    "-deadargelim", "-globaldce", "-elim-avail-extern", "-mergefunc",
    "-instcombine", "-simplifycfg", "-tailcallelim", "-reassociate",
    "-memcpyopt", "-sccp", "-dce", "-adce", "-dse", "-jump-threading",
    "-loop-idiom", "-loop-deletion", "-gvn", "-gvn-hoist", "-gvn-sink",
    "-newgvn", "-early-cse", "-mergereturn",
    "-globalopt", "-strip-dead-prototypes", "-Oz", "-indvars",
]

EXTENDED = [
    "-mergeicmps", "-loweratomic", "-separate-const-offset-from-gep",
    "-libcalls-shrinkwrap", "-winehprepare", "-flattencfg",
    "-indvars", "-loop-reduce", "-loop-unroll", "-loop-rotate",
    "-partial-inliner", "-lower-expect",
    "-alignment-from-assumptions", "-strip", "-strip-dead-prototypes",
    "-elim-avail-extern", "-rpo-function-attrs", "-attributor",
    "-inferattrs", "-ipsccp", "-globalopt",
    "-called-value-propagation", "-instnamer", "-forceattrs",
]

# Deduplicated, preserving order. Remove -enable-new-pm=0 and -Oz from shuffled set.
_ALL_RAW = list(dict.fromkeys(OZ_PASSES_OLDPM + EXTENDED))
FIXED_FLAGS = ["-enable-new-pm=0"]
NON_SHUFFLE = {"-enable-new-pm=0", "-Oz"}
SHUFFLEABLE_PASSES = [p for p in _ALL_RAW if p not in NON_SHUFFLE]


def get_file_size(path: str) -> int:
    return os.path.getsize(path)


def run_opt(opt_path: str, input_bc: str, passes: List[str], output_bc: str,
            timeout: int = 30) -> bool:
    """Run opt with given passes. Returns True on success."""
    cmd = [opt_path] + passes + [input_bc, "-o", output_bc]
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=timeout
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def get_baseline_size(opt_path: str, input_bc: str, tmpdir: str) -> Optional[int]:
    """Get code size after -Oz optimization (using new PM, since -Oz requires it)."""
    output = os.path.join(tmpdir, "baseline.bc")
    if run_opt(opt_path, input_bc, ["-Oz"], output):
        return get_file_size(output)
    return None


def run_single_permutation(opt_path: str, input_bc: str, pass_sequence: List[str],
                           tmpdir: str) -> Optional[int]:
    """Run a single permutation of passes. Returns optimized size or None on failure."""
    output = os.path.join(tmpdir, "experiment.bc")
    full_passes = FIXED_FLAGS + pass_sequence
    if run_opt(opt_path, input_bc, full_passes, output):
        return get_file_size(output)
    return None


def discover_benchmarks(benchmarks_dir: str) -> List[Tuple[str, str]]:
    """Find all .bc files in benchmarks dir. Returns [(name, path), ...]."""
    bc_files = sorted(Path(benchmarks_dir).glob("*.bc"))
    return [(f.stem, str(f)) for f in bc_files]


def generate_variable_sequence(min_length: int, max_length: int) -> List[str]:
    """Generate a random subsequence of passes with variable length."""
    length = random.randint(min_length, max_length)
    # Sample without replacement, then shuffle
    selected = random.sample(SHUFFLEABLE_PASSES, length)
    random.shuffle(selected)
    return selected


def run_experiment(opt_path: str, benchmarks_dir: str, num_iterations: int,
                   output_path: str, min_length: int, max_length: int, seed: int = 42):
    random.seed(seed)

    benchmarks = discover_benchmarks(benchmarks_dir)
    if not benchmarks:
        print("No .bc files found in {}".format(benchmarks_dir), file=sys.stderr)
        sys.exit(1)

    print("Found {} benchmarks: {}".format(len(benchmarks), [b[0] for b in benchmarks]))
    print("Shuffleable passes: {}".format(len(SHUFFLEABLE_PASSES)))
    print("Sequence length: {}-{} passes".format(min_length, max_length))
    print("Iterations per benchmark: {}".format(num_iterations))
    print("Total runs: {}".format(len(benchmarks) * num_iterations))
    print()

    results = []
    baselines = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        # Compute baselines
        print("Computing baselines (-Oz)...")
        for name, path in benchmarks:
            size = get_baseline_size(opt_path, path, tmpdir)
            if size is None:
                print("  WARNING: baseline failed for {}, skipping".format(name))
                continue
            baselines[name] = size
            print("  {}: {} bytes".format(name, size))

        benchmarks = [(n, p) for n, p in benchmarks if n in baselines]
        print("\n{} benchmarks with valid baselines.\n".format(len(benchmarks)))

        # Run permutations
        total_runs = len(benchmarks) * num_iterations
        run_count = 0
        positive_count = 0
        start_time = time.time()

        for bench_name, bench_path in benchmarks:
            baseline_size = baselines[bench_name]
            bench_positive = 0

            for i in range(num_iterations):
                run_count += 1
                # Generate random variable-length sequence
                sequence = generate_variable_sequence(min_length, max_length)

                opt_size = run_single_permutation(opt_path, bench_path, sequence, tmpdir)

                if opt_size is None:
                    # opt crashed — record as failed
                    results.append({
                        "benchmark": bench_name,
                        "pass_sequence": [p.lstrip("-") for p in sequence],
                        "sequence_length": len(sequence),
                        "optimized_size": None,
                        "baseline_oz_size": baseline_size,
                        "improvement": None,
                        "status": "failed",
                    })
                    continue

                improvement = (baseline_size - opt_size) / baseline_size if baseline_size > 0 else 0.0

                results.append({
                    "benchmark": bench_name,
                    "pass_sequence": [p.lstrip("-") for p in sequence],
                    "sequence_length": len(sequence),
                    "optimized_size": opt_size,
                    "baseline_oz_size": baseline_size,
                    "improvement": improvement,
                    "status": "success",
                })

                if improvement > 0:
                    positive_count += 1
                    bench_positive += 1

                # Progress
                if run_count % 100 == 0:
                    elapsed = time.time() - start_time
                    rate = run_count / elapsed
                    eta = (total_runs - run_count) / rate if rate > 0 else 0
                    print("  [{}/{}] {:.1f} runs/sec, ETA {:.0f}s, {} positive so far".format(
                        run_count, total_runs, rate, eta, positive_count))

            print("  {}: {}/{} positive ({:.1f}%)".format(
                bench_name, bench_positive, num_iterations,
                100 * bench_positive / num_iterations))

    # Save results
    output_data = {
        "metadata": {
            "num_iterations": num_iterations,
            "num_passes": len(SHUFFLEABLE_PASSES),
            "passes": [p.lstrip("-") for p in SHUFFLEABLE_PASSES],
            "min_length": min_length,
            "max_length": max_length,
            "benchmarks": [b[0] for b in benchmarks],
            "baseline_sizes": baselines,
            "seed": seed,
            "opt_path": opt_path,
            "timestamp": datetime.now().isoformat(),
            "total_runs": len(results),
            "successful_runs": sum(1 for r in results if r["status"] == "success"),
            "positive_runs": positive_count,
        },
        "results": results,
    }

    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    print("\nDone! {} results saved to {}".format(len(results), output_path))
    print("Positive (beat -Oz): {}/{} ({:.1f}%)".format(
        positive_count, len(results),
        100 * positive_count / len(results)))


def main():
    parser = argparse.ArgumentParser(
        description="Run random VARIABLE-LENGTH pass permutation experiment"
    )
    parser.add_argument("--benchmarks-dir", required=True,
                        help="Directory containing .bc benchmark files")
    parser.add_argument("--num-iterations", type=int, default=5000,
                        help="Number of random sequences per benchmark (default: 5000)")
    parser.add_argument("--min-length", type=int, default=10,
                        help="Minimum sequence length (default: 10)")
    parser.add_argument("--max-length", type=int, default=30,
                        help="Maximum sequence length (default: 30)")
    parser.add_argument("--output", default="raw_results_variable.json",
                        help="Output JSON file (default: raw_results_variable.json)")
    parser.add_argument("--opt-path", default="/opt/homebrew/opt/llvm@16/bin/opt",
                        help="Path to opt binary")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (default: 42)")
    args = parser.parse_args()

    # Verify opt exists
    if not os.path.isfile(args.opt_path):
        print("opt not found at {}".format(args.opt_path), file=sys.stderr)
        sys.exit(1)

    # Validate lengths
    if args.min_length < 1 or args.max_length > len(SHUFFLEABLE_PASSES):
        print("Invalid length range: [{}, {}]".format(args.min_length, args.max_length),
              file=sys.stderr)
        sys.exit(1)
    if args.min_length > args.max_length:
        print("min_length must be <= max_length", file=sys.stderr)
        sys.exit(1)

    run_experiment(
        opt_path=args.opt_path,
        benchmarks_dir=args.benchmarks_dir,
        num_iterations=args.num_iterations,
        output_path=args.output,
        min_length=args.min_length,
        max_length=args.max_length,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
