#!/usr/bin/env python3
"""
Generate optimized pass sequences by walking the causal (or correlation) graph.

Strategies:
  1. Greedy - always pick the highest-ATE next edge
  2. Beam Search - maintain top-K partial sequences
  3. Benchmark-targeted - optimize for a specific benchmark
  4. MCTS - Monte Carlo Tree Search with graph-based rollouts

Usage:
    python3 sequence_optimizer.py --graph causal_pass_graph.json --output sequences.json
    python3 sequence_optimizer.py --graph causal_pass_graph.json --strategy beam --beam-width 10
"""

import argparse
import json
import math
import os
import random
from collections import defaultdict


# ---------------------------------------------------------------------------
# Graph loading
# ---------------------------------------------------------------------------

def load_graph(path: str) -> dict:
    """Load graph JSON. Works with both causal and correlation graph formats."""
    with open(path) as f:
        graph = json.load(f)
    return graph


def get_edge_weight(graph: dict, src: str, tgt: str) -> float:
    """Get edge weight (ATE if available, else positive_ratio)."""
    if src not in graph or tgt not in graph[src]:
        return 0.0
    info = graph[src][tgt]
    if "ate" in info:
        return info["ate"]
    return info.get("positive_ratio", 0.0)


def get_all_passes(graph: dict) -> list[str]:
    """Get all unique pass names from graph."""
    passes = set(graph.keys())
    for targets in graph.values():
        passes.update(targets.keys())
    return sorted(passes)


def get_successors(graph: dict, node: str) -> list[tuple[str, float]]:
    """Get successors with weights, sorted by weight descending."""
    if node not in graph:
        return []
    return sorted(
        [(tgt, get_edge_weight(graph, node, tgt)) for tgt in graph[node]],
        key=lambda x: x[1],
        reverse=True,
    )


def score_sequence(graph: dict, seq: list[str]) -> float:
    """Score a sequence by summing edge weights along the path."""
    total = 0.0
    for i in range(len(seq) - 1):
        total += get_edge_weight(graph, seq[i], seq[i + 1])
    return total


def benchmark_coverage(graph: dict, seq: list[str]) -> set[str]:
    """Get set of benchmarks covered by edges in the sequence."""
    benchmarks = set()
    for i in range(len(seq) - 1):
        src, tgt = seq[i], seq[i + 1]
        if src in graph and tgt in graph[src]:
            info = graph[src][tgt]
            for field in ("positive_benchmarks", "significant_benchmarks"):
                if field in info:
                    benchmarks.update(info[field])
    return benchmarks


# ---------------------------------------------------------------------------
# Strategy 1: Greedy
# ---------------------------------------------------------------------------

def greedy_walk(graph: dict, max_len: int = 50,
                allow_repeats: int = 0) -> list[dict]:
    """
    Greedy walk: start from each node, always follow highest-weight edge.
    Returns list of sequences with scores.
    """
    all_passes = get_all_passes(graph)
    sequences = []

    for start in all_passes:
        seq = [start]
        visit_count = defaultdict(int)
        visit_count[start] = 1

        while len(seq) < max_len:
            successors = get_successors(graph, seq[-1])
            # Filter by visit limit
            valid = [
                (tgt, w) for tgt, w in successors
                if visit_count[tgt] <= allow_repeats and w > 0
            ]
            if not valid:
                break
            next_node = valid[0][0]
            seq.append(next_node)
            visit_count[next_node] += 1

        if len(seq) > 1:
            sequences.append({
                "sequence": seq,
                "score": score_sequence(graph, seq),
                "length": len(seq),
                "benchmark_coverage": sorted(benchmark_coverage(graph, seq)),
                "strategy": "greedy",
                "start_node": start,
            })

    sequences.sort(key=lambda x: x["score"], reverse=True)
    return sequences


# ---------------------------------------------------------------------------
# Strategy 2: Beam Search
# ---------------------------------------------------------------------------

def beam_search(graph: dict, beam_width: int = 5, max_len: int = 50,
                allow_repeats: int = 0) -> list[dict]:
    """
    Beam search: maintain top-K partial sequences at each step.
    Score = cumulative edge weight + coverage bonus.
    """
    all_passes = get_all_passes(graph)

    # Initialize beams from all starting nodes
    beams = []
    for start in all_passes:
        beams.append(([start], 0.0, defaultdict(int, {start: 1})))

    # Keep top beam_width * len(all_passes) initially, then narrow
    beams = beams[:beam_width * 10]

    for step in range(max_len - 1):
        candidates = []

        for seq, score, visits in beams:
            current = seq[-1]
            successors = get_successors(graph, current)

            expanded = False
            for tgt, weight in successors:
                if visits[tgt] > allow_repeats or weight <= 0:
                    continue

                new_seq = seq + [tgt]
                new_score = score + weight
                new_visits = defaultdict(int, visits)
                new_visits[tgt] += 1

                # Coverage bonus
                coverage = len(benchmark_coverage(graph, new_seq))
                bonus = coverage * 0.001

                candidates.append((new_seq, new_score + bonus, new_visits))
                expanded = True

            if not expanded:
                # Dead end — keep as final candidate
                candidates.append((seq, score, visits))

        if not candidates:
            break

        # Keep top beam_width candidates
        candidates.sort(key=lambda x: x[1], reverse=True)
        beams = candidates[:beam_width]

        # Check if all beams are stuck
        if all(len(seq) == len(beams[0][0]) for seq, _, _ in beams):
            break

    results = []
    seen = set()
    for seq, score, _ in beams:
        key = tuple(seq)
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "sequence": seq,
            "score": score_sequence(graph, seq),
            "length": len(seq),
            "benchmark_coverage": sorted(benchmark_coverage(graph, seq)),
            "strategy": "beam_search",
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Strategy 3: Benchmark-targeted
# ---------------------------------------------------------------------------

def benchmark_targeted(graph: dict, max_len: int = 50) -> dict[str, list[dict]]:
    """
    Build per-benchmark subgraph and find best sequence for each.
    """
    # Collect all benchmarks
    all_benchmarks = set()
    for src, targets in graph.items():
        for tgt, info in targets.items():
            for field in ("positive_benchmarks", "significant_benchmarks"):
                if field in info:
                    all_benchmarks.update(info[field])

    results = {}
    for bench in sorted(all_benchmarks):
        # Build subgraph for this benchmark
        subgraph = {}
        for src, targets in graph.items():
            sub_targets = {}
            for tgt, info in targets.items():
                for field in ("positive_benchmarks", "significant_benchmarks"):
                    if field in info and bench in info[field]:
                        sub_targets[tgt] = info
                        break
            if sub_targets:
                subgraph[src] = sub_targets

        if not subgraph:
            continue

        # Greedy on subgraph
        seqs = greedy_walk(subgraph, max_len=max_len)
        if seqs:
            best = seqs[0]
            best["strategy"] = f"benchmark_targeted:{bench}"
            results[bench] = best

    return results


# ---------------------------------------------------------------------------
# Strategy 4: Monte Carlo Tree Search (MCTS)
# ---------------------------------------------------------------------------

class MCTSNode:
    def __init__(self, pass_name: str, parent=None):
        self.pass_name = pass_name
        self.parent = parent
        self.children = {}
        self.visits = 0
        self.total_reward = 0.0

    @property
    def avg_reward(self):
        return self.total_reward / self.visits if self.visits > 0 else 0

    def ucb1(self, exploration: float = 1.414) -> float:
        if self.visits == 0:
            return float("inf")
        parent_visits = self.parent.visits if self.parent else 1
        return (self.avg_reward +
                exploration * math.sqrt(math.log(parent_visits) / self.visits))


def mcts_search(graph: dict, num_simulations: int = 1000,
                max_len: int = 50, seed: int = 42) -> list[dict]:
    """
    MCTS for pass sequence optimization.
    Uses graph edge weights as rollout policy prior.
    """
    rng = random.Random(seed)
    all_passes = get_all_passes(graph)

    # Root node (virtual)
    root = MCTSNode("__root__")

    for _ in range(num_simulations):
        # Selection + Expansion
        node = root
        sequence = []
        visited = set()

        while True:
            # Get possible next moves
            current = node.pass_name
            if current == "__root__":
                possible = [(p, 0.0) for p in all_passes]
            else:
                possible = [
                    (tgt, w) for tgt, w in get_successors(graph, current)
                    if tgt not in visited and w > 0
                ]

            if not possible or len(sequence) >= max_len:
                break

            # Check for unexplored children
            unexplored = [p for p, _ in possible if p not in node.children]

            if unexplored:
                # Expand: choose a random unexplored child
                # Weighted by edge weight
                weights = []
                for p in unexplored:
                    w = get_edge_weight(graph, current, p) if current != "__root__" else 0.01
                    weights.append(max(w, 0.001))

                total_w = sum(weights)
                r = rng.random() * total_w
                cumulative = 0
                chosen = unexplored[0]
                for p, w in zip(unexplored, weights):
                    cumulative += w
                    if cumulative >= r:
                        chosen = p
                        break

                child = MCTSNode(chosen, parent=node)
                node.children[chosen] = child
                node = child
                sequence.append(chosen)
                visited.add(chosen)
                break
            else:
                # Select: UCB1
                best_child = max(node.children.values(), key=lambda c: c.ucb1())
                node = best_child
                sequence.append(best_child.pass_name)
                visited.add(best_child.pass_name)

        # Rollout: random walk weighted by edge weights
        current = sequence[-1] if sequence else rng.choice(all_passes)
        rollout_seq = list(sequence)

        for _ in range(max_len - len(rollout_seq)):
            successors = get_successors(graph, current)
            valid = [(t, w) for t, w in successors if t not in visited and w > 0]
            if not valid:
                break

            weights = [max(w, 0.001) for _, w in valid]
            total_w = sum(weights)
            r = rng.random() * total_w
            cumulative = 0
            chosen = valid[0][0]
            for (t, _), w in zip(valid, weights):
                cumulative += w
                if cumulative >= r:
                    chosen = t
                    break

            rollout_seq.append(chosen)
            visited.add(chosen)
            current = chosen

        # Backpropagation
        reward = score_sequence(graph, rollout_seq)
        while node is not None:
            node.visits += 1
            node.total_reward += reward
            node = node.parent

    # Extract best sequences from tree
    sequences = _extract_mcts_sequences(root, graph, max_len)
    return sequences


def _extract_mcts_sequences(root: MCTSNode, graph: dict,
                            max_len: int) -> list[dict]:
    """Extract top sequences from MCTS tree by following most-visited paths."""
    results = []

    for start_name, start_node in sorted(root.children.items(),
                                          key=lambda x: x[1].visits,
                                          reverse=True)[:10]:
        seq = [start_name]
        node = start_node

        while node.children and len(seq) < max_len:
            best = max(node.children.values(), key=lambda c: c.visits)
            seq.append(best.pass_name)
            node = best

        if len(seq) > 1:
            results.append({
                "sequence": seq,
                "score": score_sequence(graph, seq),
                "length": len(seq),
                "benchmark_coverage": sorted(benchmark_coverage(graph, seq)),
                "strategy": "mcts",
                "root_visits": start_node.visits,
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate optimized pass sequences from graph"
    )
    parser.add_argument("--graph", required=True,
                        help="Path to pass graph JSON (causal or correlation)")
    parser.add_argument("--strategy", default="all",
                        choices=["greedy", "beam", "targeted", "mcts", "all"],
                        help="Optimization strategy (default: all)")
    parser.add_argument("--beam-width", type=int, default=10,
                        help="Beam width for beam search (default: 10)")
    parser.add_argument("--max-len", type=int, default=50,
                        help="Maximum sequence length (default: 50)")
    parser.add_argument("--mcts-simulations", type=int, default=2000,
                        help="Number of MCTS simulations (default: 2000)")
    parser.add_argument("--output", default="optimized_sequences.json",
                        help="Output JSON file")
    parser.add_argument("--top-k", type=int, default=10,
                        help="Show top K sequences per strategy")
    args = parser.parse_args()

    graph = load_graph(args.graph)
    all_passes = get_all_passes(graph)
    total_edges = sum(len(t) for t in graph.values())
    print(f"Loaded graph: {len(all_passes)} passes, {total_edges} edges\n")

    all_results = {}

    strategies = (["greedy", "beam", "targeted", "mcts"]
                  if args.strategy == "all" else [args.strategy])

    for strategy in strategies:
        print(f"{'='*60}")
        print(f"Strategy: {strategy}")
        print(f"{'='*60}")

        if strategy == "greedy":
            seqs = greedy_walk(graph, max_len=args.max_len)
            all_results["greedy"] = seqs[:args.top_k]

        elif strategy == "beam":
            seqs = beam_search(graph, beam_width=args.beam_width,
                              max_len=args.max_len)
            all_results["beam_search"] = seqs[:args.top_k]

        elif strategy == "targeted":
            targeted = benchmark_targeted(graph, max_len=args.max_len)
            all_results["benchmark_targeted"] = targeted

        elif strategy == "mcts":
            seqs = mcts_search(graph, num_simulations=args.mcts_simulations,
                              max_len=args.max_len)
            all_results["mcts"] = seqs[:args.top_k]

        # Print top results
        if strategy == "targeted":
            for bench, info in sorted(targeted.items()):
                print(f"\n  {bench}: score={info['score']:.6f}, len={info['length']}")
                print(f"    {' -> '.join(info['sequence'][:8])}...")
        else:
            key = "beam_search" if strategy == "beam" else strategy
            for i, seq_info in enumerate(all_results.get(key, [])[:5]):
                print(f"\n  #{i+1}: score={seq_info['score']:.6f}, "
                      f"len={seq_info['length']}, "
                      f"coverage={len(seq_info['benchmark_coverage'])} benchmarks")
                print(f"    {' -> '.join(seq_info['sequence'][:10])}...")

        print()

    # Save
    with open(args.output, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nAll sequences saved to {args.output}")

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY: Best sequence per strategy")
    print(f"{'='*60}")
    for strategy, data in all_results.items():
        if strategy == "benchmark_targeted":
            avg_score = sum(v["score"] for v in data.values()) / len(data) if data else 0
            print(f"  {strategy}: {len(data)} benchmark-specific sequences, avg score={avg_score:.6f}")
        elif data:
            best = data[0]
            print(f"  {strategy}: score={best['score']:.6f}, len={best['length']}, "
                  f"coverage={len(best['benchmark_coverage'])}")


if __name__ == "__main__":
    main()
