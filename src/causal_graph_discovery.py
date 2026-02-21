#!/usr/bin/env python3
from __future__ import annotations

"""
Causal inference for pass transition graph.
  1. ATE (Average Treatment Effect) for each pass pair
  2. CATE (Conditional ATE) per benchmark
  3. PC-algorithm for causal structure discovery
  4. Positional analysis

Usage:
    python3 causal_graph_discovery.py --input raw_results.json --output-dir ./causal_results
"""

import argparse
import json
import os
from collections import defaultdict
from itertools import combinations

import numpy as np
from scipy import stats


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_results(path: str) -> tuple[list[dict], dict]:
    with open(path) as f:
        data = json.load(f)
    results = [r for r in data["results"] if r["status"] == "success"]
    return results, data["metadata"]


def extract_pass_pairs(sequence: list[str]) -> set[tuple[str, str]]:
    """Extract all consecutive pass pairs from a sequence."""
    return {(sequence[i], sequence[i + 1]) for i in range(len(sequence) - 1)}


# ---------------------------------------------------------------------------
# Method 1: Average Treatment Effect (ATE)
# ---------------------------------------------------------------------------

def compute_ate(results: list[dict], all_passes: list[str],
                alpha: float = 0.05) -> dict:
    """
    For each pass pair (A, B):
      - Treatment group: runs where A immediately precedes B
      - Control group: runs where A does NOT immediately precede B
      - ATE = mean(improvement | treated) - mean(improvement | control)
      - Statistical significance via Welch's t-test + BH FDR correction

    Returns dict of significant edges with ATE and p-values.
    """
    print("Computing ATE for all pass pairs...")

    # Pre-compute: for each run, extract its consecutive pairs
    run_pairs = []
    run_improvements = []
    for r in results:
        pairs = extract_pass_pairs(r["pass_sequence"])
        run_pairs.append(pairs)
        run_improvements.append(r["improvement"])

    improvements = np.array(run_improvements)

    # Collect all candidate pairs
    candidate_pairs = set()
    for pairs in run_pairs:
        candidate_pairs.update(pairs)

    print(f"  Candidate pairs: {len(candidate_pairs)}")

    # Compute ATE and p-value for each pair
    ate_results = {}
    p_values = []
    pair_keys = []

    for src, tgt in sorted(candidate_pairs):
        # Treatment mask: runs containing this pair
        treated_mask = np.array([
            (src, tgt) in pairs for pairs in run_pairs
        ])
        control_mask = ~treated_mask

        n_treated = treated_mask.sum()
        n_control = control_mask.sum()

        if n_treated < 2 or n_control < 2:
            continue

        treated_improvements = improvements[treated_mask]
        control_improvements = improvements[control_mask]

        ate = treated_improvements.mean() - control_improvements.mean()

        # Welch's t-test (unequal variances)
        t_stat, p_value = stats.ttest_ind(
            treated_improvements, control_improvements, equal_var=False
        )

        ate_results[(src, tgt)] = {
            "ate": float(ate),
            "p_value": float(p_value),
            "n_treated": int(n_treated),
            "n_control": int(n_control),
            "mean_treated": float(treated_improvements.mean()),
            "mean_control": float(control_improvements.mean()),
            "std_treated": float(treated_improvements.std()),
            "std_control": float(control_improvements.std()),
        }
        p_values.append(p_value)
        pair_keys.append((src, tgt))

    # Benjamini-Hochberg FDR correction
    if p_values:
        p_adjusted = _benjamini_hochberg(np.array(p_values))
        for i, key in enumerate(pair_keys):
            ate_results[key]["p_adjusted"] = float(p_adjusted[i])

    # Filter significant edges with positive ATE
    significant = {}
    for key, info in ate_results.items():
        if info.get("p_adjusted", 1.0) < alpha and info["ate"] > 0:
            significant[key] = info

    print(f"  Total pairs tested: {len(ate_results)}")
    print(f"  Significant (ATE > 0, p_adj < {alpha}): {len(significant)}")

    return ate_results, significant


def _benjamini_hochberg(p_values: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg FDR correction."""
    n = len(p_values)
    sorted_idx = np.argsort(p_values)
    sorted_p = p_values[sorted_idx]

    adjusted = np.zeros(n)
    adjusted[sorted_idx[-1]] = sorted_p[-1]

    for i in range(n - 2, -1, -1):
        adjusted[sorted_idx[i]] = min(
            adjusted[sorted_idx[i + 1]],
            sorted_p[i] * n / (i + 1)
        )

    return np.clip(adjusted, 0, 1)


# ---------------------------------------------------------------------------
# Method 2: Conditional ATE (per benchmark)
# ---------------------------------------------------------------------------

def compute_cate(results: list[dict], alpha: float = 0.05) -> dict:
    """
    Compute ATE separately for each benchmark.
    Returns dict: benchmark -> {(src, tgt): ate_info}
    """
    print("\nComputing CATE (per-benchmark ATE)...")

    benchmarks = sorted(set(r["benchmark"] for r in results))
    cate_results = {}

    for bench in benchmarks:
        bench_results = [r for r in results if r["benchmark"] == bench]

        run_pairs = []
        run_improvements = []
        for r in bench_results:
            pairs = extract_pass_pairs(r["pass_sequence"])
            run_pairs.append(pairs)
            run_improvements.append(r["improvement"])

        improvements = np.array(run_improvements)

        candidate_pairs = set()
        for pairs in run_pairs:
            candidate_pairs.update(pairs)

        bench_ate = {}
        for src, tgt in candidate_pairs:
            treated_mask = np.array([(src, tgt) in pairs for pairs in run_pairs])
            control_mask = ~treated_mask

            n_treated = treated_mask.sum()
            n_control = control_mask.sum()

            if n_treated < 2 or n_control < 2:
                continue

            ate = improvements[treated_mask].mean() - improvements[control_mask].mean()

            # For per-benchmark, use simple t-test
            t_stat, p_value = stats.ttest_ind(
                improvements[treated_mask], improvements[control_mask],
                equal_var=False
            )

            if ate > 0 and p_value < alpha:
                bench_ate[(src, tgt)] = {
                    "ate": float(ate),
                    "p_value": float(p_value),
                    "n_treated": int(n_treated),
                }

        cate_results[bench] = bench_ate
        if bench_ate:
            print(f"  {bench}: {len(bench_ate)} significant pairs")

    return cate_results


# ---------------------------------------------------------------------------
# Method 3: PC-algorithm (simplified)
# ---------------------------------------------------------------------------

def compute_pc_graph(results: list[dict], significant_edges: dict,
                     alpha: float = 0.05) -> dict:
    """
    Simplified PC-algorithm: starting from the ATE-significant edges,
    test whether each edge A->B can be "explained away" by a mediator M.

    If A->B becomes conditionally independent of outcome given M
    (where A->M and M->B are both significant), remove A->B.
    """
    print("\nRunning PC-like causal pruning...")

    # Build adjacency from significant edges
    adjacency = defaultdict(set)
    for (src, tgt) in significant_edges:
        adjacency[src].add(tgt)

    # Pre-compute per-run data
    run_pairs = []
    run_improvements = []
    for r in results:
        pairs = extract_pass_pairs(r["pass_sequence"])
        run_pairs.append(pairs)
        run_improvements.append(r["improvement"])
    improvements = np.array(run_improvements)

    edges_to_remove = set()

    for (src, tgt) in list(significant_edges.keys()):
        # Find potential mediators: nodes M where src->M and M->tgt both significant
        mediators = adjacency[src] & {m for m in adjacency if tgt in adjacency[m]}
        mediators.discard(src)
        mediators.discard(tgt)

        for mediator in mediators:
            # Conditional independence test:
            # Among runs where src->M AND M->tgt are present,
            # does having src->tgt (directly) still matter?
            has_src_tgt = np.array([(src, tgt) in p for p in run_pairs])
            has_src_med = np.array([(src, mediator) in p for p in run_pairs])
            has_med_tgt = np.array([(mediator, tgt) in p for p in run_pairs])

            # Condition on mediator path being present
            cond_mask = has_src_med & has_med_tgt
            if cond_mask.sum() < 10:
                continue

            # Within conditioned set, compare: has direct edge vs not
            cond_has_direct = cond_mask & has_src_tgt
            cond_no_direct = cond_mask & ~has_src_tgt

            if cond_has_direct.sum() < 2 or cond_no_direct.sum() < 2:
                continue

            # Test if direct edge still matters given mediator
            t_stat, p_value = stats.ttest_ind(
                improvements[cond_has_direct],
                improvements[cond_no_direct],
                equal_var=False
            )

            # If not significant -> edge is explained by mediator
            if p_value > alpha:
                edges_to_remove.add((src, tgt))
                break

    # Build pruned graph
    pc_edges = {k: v for k, v in significant_edges.items() if k not in edges_to_remove}

    print(f"  Edges before pruning: {len(significant_edges)}")
    print(f"  Edges removed by PC: {len(edges_to_remove)}")
    print(f"  Edges after pruning: {len(pc_edges)}")

    return pc_edges, edges_to_remove


# ---------------------------------------------------------------------------
# Method 4: Positional Analysis
# ---------------------------------------------------------------------------

def compute_positional_effects(results: list[dict], all_passes: list[str]) -> dict:
    """
    Analyze whether pass effectiveness depends on position in sequence.
    Split each sequence into thirds and compare ATE.
    """
    print("\nComputing positional effects...")

    # For each pass, collect improvements grouped by position (third)
    pass_position_improvements = defaultdict(lambda: {"early": [], "mid": [], "late": []})

    for r in results:
        seq = r["pass_sequence"]
        n = len(seq)
        improvement = r["improvement"]
        third = n // 3

        for i, p in enumerate(seq):
            if i < third:
                pos = "early"
            elif i < 2 * third:
                pos = "mid"
            else:
                pos = "late"
            pass_position_improvements[p][pos].append(improvement)

    # Compute effect: is there a significant difference between early and late?
    positional = {}
    for pass_name in sorted(pass_position_improvements):
        data = pass_position_improvements[pass_name]
        early = np.array(data["early"])
        late = np.array(data["late"])

        if len(early) < 10 or len(late) < 10:
            continue

        t_stat, p_value = stats.ttest_ind(early, late, equal_var=False)
        diff = early.mean() - late.mean()

        positional[pass_name] = {
            "early_mean": float(early.mean()),
            "mid_mean": float(np.array(data["mid"]).mean()) if data["mid"] else None,
            "late_mean": float(late.mean()),
            "early_vs_late_diff": float(diff),
            "p_value": float(p_value),
            "prefers": "early" if diff > 0 else "late",
        }

    sig_positional = {k: v for k, v in positional.items() if v["p_value"] < 0.05}
    print(f"  Passes with significant positional effect: {len(sig_positional)}")
    for p, info in sorted(sig_positional.items(), key=lambda x: abs(x[1]["early_vs_late_diff"]), reverse=True)[:10]:
        print(f"    {p}: prefers {info['prefers']} "
              f"(diff={info['early_vs_late_diff']:.6f}, p={info['p_value']:.4f})")

    return positional


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def build_causal_graph_json(significant_edges: dict, cate: dict,
                            positional: dict) -> dict:
    """Build causal graph in the same format as advisor's graph + extra fields."""
    graph = defaultdict(dict)

    for (src, tgt), info in significant_edges.items():
        # Collect which benchmarks this edge is significant for
        sig_benchmarks = []
        for bench, bench_edges in cate.items():
            if (src, tgt) in bench_edges:
                sig_benchmarks.append(bench)

        graph[src][tgt] = {
            "ate": info["ate"],
            "p_adjusted": info.get("p_adjusted", info["p_value"]),
            "n_treated": info["n_treated"],
            "n_control": info["n_control"],
            "mean_treated": info["mean_treated"],
            "mean_control": info["mean_control"],
            "significant_benchmarks": sorted(sig_benchmarks),
            "positive_ratio": info["mean_treated"],
            "total_occurrences": info["n_treated"],
            "positive_count": info["n_treated"],
            "positive_benchmarks": sorted(sig_benchmarks),
        }

    return dict(graph)


def graph_to_dot(graph: dict, title: str = "CausalPassGraph") -> str:
    """Convert causal graph to DOT format with ATE-based edge weights."""
    lines = [
        f"digraph {title} {{",
        "  rankdir=LR;",
        '  node [shape=box, style=filled, fillcolor=lightblue];',
    ]

    # Collect all ATE values for normalization
    all_ates = []
    for src_targets in graph.values():
        for info in src_targets.values():
            all_ates.append(abs(info["ate"]))

    max_ate = max(all_ates) if all_ates else 1

    for src, targets in graph.items():
        for tgt, info in targets.items():
            ate = info["ate"]
            normalized = abs(ate) / max_ate if max_ate > 0 else 0
            penwidth = max(1.0, normalized * 6.0)

            # Color: green for positive, red for negative
            if ate > 0:
                color = f'"0.33 {min(1.0, normalized * 2):.2f} 0.8"'
            else:
                color = f'"0.0 {min(1.0, normalized * 2):.2f} 0.8"'

            lines.append(
                f'  "{src}" -> "{tgt}" '
                f'[label="ATE={ate:.4f}", penwidth={penwidth:.1f}, '
                f'color={color}];'
            )

    lines.append("}")
    return "\n".join(lines)


def compare_graphs(original_path: str | None, causal_graph: dict):
    """Compare causal graph with original advisor's graph."""
    if original_path is None or not os.path.exists(original_path):
        print("\nNo original graph to compare with.")
        return

    with open(original_path) as f:
        original = json.load(f)

    orig_edges = set()
    for src, targets in original.items():
        for tgt in targets:
            orig_edges.add((src, tgt))

    causal_edges = set()
    for src, targets in causal_graph.items():
        for tgt in targets:
            causal_edges.add((src, tgt))

    common = orig_edges & causal_edges
    only_original = orig_edges - causal_edges
    only_causal = causal_edges - orig_edges

    print(f"\n{'='*60}")
    print("COMPARISON: Original (correlation) vs Causal graph")
    print(f"{'='*60}")
    print(f"Original edges: {len(orig_edges)}")
    print(f"Causal edges:   {len(causal_edges)}")
    print(f"Common:         {len(common)}")
    print(f"Only in original (spurious?): {len(only_original)}")
    print(f"Only in causal (new):         {len(only_causal)}")

    if only_original:
        print(f"\nTop removed edges (likely spurious):")
        for src, tgt in sorted(only_original)[:15]:
            print(f"  {src} -> {tgt}")

    if only_causal:
        print(f"\nNew edges found by causal analysis:")
        for src, tgt in sorted(only_causal)[:15]:
            print(f"  {src} -> {tgt}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Causal inference for pass transition graph"
    )
    parser.add_argument("--input", required=True,
                        help="Path to raw_results.json")
    parser.add_argument("--output-dir", default="./causal_results",
                        help="Output directory")
    parser.add_argument("--alpha", type=float, default=0.05,
                        help="Significance level (default: 0.05)")
    parser.add_argument("--original-graph", default=None,
                        help="Path to original pass_transition_graph.json for comparison")
    args = parser.parse_args()

    results, metadata = load_results(args.input)
    all_passes = metadata["passes"]
    print(f"Loaded {len(results)} results, {len(all_passes)} passes\n")

    # Method 1: ATE
    all_ate, significant_ate = compute_ate(results, all_passes, alpha=args.alpha)

    # Method 2: CATE
    cate = compute_cate(results, alpha=args.alpha)

    # Method 3: PC-algorithm pruning
    pc_edges, removed_edges = compute_pc_graph(results, significant_ate, alpha=args.alpha)

    # Method 4: Positional analysis
    positional = compute_positional_effects(results, all_passes)

    # Build output graph (using PC-pruned edges)
    causal_graph = build_causal_graph_json(pc_edges, cate, positional)

    # Save
    os.makedirs(args.output_dir, exist_ok=True)

    json_path = os.path.join(args.output_dir, "causal_pass_graph.json")
    with open(json_path, "w") as f:
        json.dump(causal_graph, f, indent=2)
    print(f"\nCausal graph saved to {json_path}")

    dot_path = os.path.join(args.output_dir, "causal_pass_graph.dot")
    with open(dot_path, "w") as f:
        f.write(graph_to_dot(causal_graph))
    print(f"DOT saved to {dot_path}")

    # Save full analysis
    analysis_path = os.path.join(args.output_dir, "full_analysis.json")
    analysis = {
        "ate_all": {f"{k[0]}->{k[1]}": v for k, v in all_ate.items()},
        "ate_significant": {f"{k[0]}->{k[1]}": v for k, v in significant_ate.items()},
        "pc_removed": [f"{s}->{t}" for s, t in removed_edges],
        "cate": {bench: {f"{k[0]}->{k[1]}": v for k, v in edges.items()}
                 for bench, edges in cate.items()},
        "positional": positional,
    }
    with open(analysis_path, "w") as f:
        json.dump(analysis, f, indent=2)
    print(f"Full analysis saved to {analysis_path}")

    # Compare with original
    compare_graphs(args.original_graph, causal_graph)


if __name__ == "__main__":
    main()
