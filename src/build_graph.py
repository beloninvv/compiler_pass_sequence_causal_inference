#!/usr/bin/env python3
"""
Build a pass transition graph from raw experiment results.
Produces the same format as the advisor's pass_transition_graph.json and pass_graph.dot.

Usage:
    python3 build_graph.py --input raw_results.json --output-dir ./results
"""

import argparse
import json
import os
from collections import defaultdict


def build_transition_graph(results: list[dict]) -> dict:
    """
    Build transition graph from experiment results.
    For each run with improvement > 0, extract consecutive pass pairs.
    """
    # edge_data[src][tgt] = {"benchmarks": set(), "total": 0, "positive": 0}
    edge_data = defaultdict(lambda: defaultdict(lambda: {
        "benchmarks_positive": set(),
        "benchmarks_total": set(),
        "total": 0,
        "positive": 0,
    }))

    # Count total occurrences (all runs) and positive occurrences
    for run in results:
        if run["status"] != "success":
            continue

        seq = run["pass_sequence"]
        bench = run["benchmark"]
        is_positive = run["improvement"] is not None and run["improvement"] > 0

        for i in range(len(seq) - 1):
            src, tgt = seq[i], seq[i + 1]
            edge_data[src][tgt]["total"] += 1
            edge_data[src][tgt]["benchmarks_total"].add(bench)

            if is_positive:
                edge_data[src][tgt]["positive"] += 1
                edge_data[src][tgt]["benchmarks_positive"].add(bench)

    # Convert to the same format as advisor's JSON
    # Only include edges that appeared in at least one positive run
    graph = {}
    all_benchmarks = set(r["benchmark"] for r in results if r["status"] == "success")
    num_benchmarks = len(all_benchmarks)

    for src in sorted(edge_data.keys()):
        targets = {}
        for tgt in sorted(edge_data[src].keys()):
            info = edge_data[src][tgt]
            if info["positive"] == 0:
                continue

            positive_ratio = info["positive"] / info["total"] if info["total"] > 0 else 0
            targets[tgt] = {
                "positive_ratio": positive_ratio,
                "occurence_ratio": len(info["benchmarks_positive"]) / num_benchmarks,
                "total_occurrences": info["total"],
                "positive_count": info["positive"],
                "positive_benchmarks": sorted(info["benchmarks_positive"]),
            }

        if targets:
            graph[src] = targets

    return graph


def graph_to_dot(graph: dict) -> str:
    """Convert transition graph to DOT format."""
    lines = [
        "digraph PassGraph {",
        '  rankdir=LR;',
        '  node [shape=box, style=filled, fillcolor=lightblue];',
    ]

    for src, targets in graph.items():
        for tgt, info in targets.items():
            ratio = info["positive_ratio"]
            penwidth = max(1.0, ratio * 6.0)
            lines.append(
                f'  "{src}" -> "{tgt}" '
                f'[label="{ratio*100:.1f}%", penwidth={penwidth:.1f}];'
            )

    lines.append("}")
    return "\n".join(lines)


def print_stats(graph: dict, results: list[dict]):
    """Print summary statistics about the graph."""
    all_passes = set()
    total_edges = 0
    for src, targets in graph.items():
        all_passes.add(src)
        for tgt in targets:
            all_passes.add(tgt)
            total_edges += 1

    total_runs = sum(1 for r in results if r["status"] == "success")
    positive_runs = sum(1 for r in results
                        if r["status"] == "success"
                        and r["improvement"] is not None
                        and r["improvement"] > 0)

    all_benchmarks = set(r["benchmark"] for r in results if r["status"] == "success")

    print(f"Total successful runs: {total_runs}")
    print(f"Positive runs (beat -Oz): {positive_runs} ({100*positive_runs/total_runs:.1f}%)")
    print(f"Benchmarks: {len(all_benchmarks)}")
    print(f"Unique passes in graph: {len(all_passes)}")
    print(f"Edges (positive transitions): {total_edges}")
    print(f"Max possible edges: {len(all_passes) * (len(all_passes) - 1)}")
    print(f"Graph density: {total_edges / (len(all_passes) * (len(all_passes) - 1)) * 100:.1f}%")


def main():
    parser = argparse.ArgumentParser(
        description="Build pass transition graph from experiment results"
    )
    parser.add_argument("--input", required=True,
                        help="Path to raw_results.json")
    parser.add_argument("--output-dir", default=".",
                        help="Output directory (default: current dir)")
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    results = data["results"]
    print(f"Loaded {len(results)} results from {args.input}\n")

    graph = build_transition_graph(results)

    print_stats(graph, results)

    # Save JSON
    os.makedirs(args.output_dir, exist_ok=True)
    json_path = os.path.join(args.output_dir, "pass_transition_graph.json")
    with open(json_path, "w") as f:
        json.dump(graph, f, indent=2)
    print(f"\nGraph saved to {json_path}")

    # Save DOT
    dot_path = os.path.join(args.output_dir, "pass_graph.dot")
    with open(dot_path, "w") as f:
        f.write(graph_to_dot(graph))
    print(f"DOT saved to {dot_path}")


if __name__ == "__main__":
    main()
