#!/usr/bin/env python3
"""
Шаг 6: Корреляционный граф для срав��ения с каузальным.

Корреляционный граф строится по литературному подходу:
  - "Выигрышные" последовательности: ir_count < baseline_oz
  - Ребро A→B есл�� переход A→B встречается в выигрышных последовательностях
    чаще, чем о��идается при случайном порядке
  - Тест: chi-squared на частоту биграмм

Сравн��ние: сколько корреляционных рёбер являются "ложными"
(присутствуют в корреляционном графе, но отсутствуют в каузальном).

Использование:
    python -m src.analysis.correlation [--formulation B|V]
"""

import argparse
import json
import logging
import time

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

from src.config import PASSES, PROJECT_ROOT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

OUTPUT_DIR = PROJECT_ROOT / "experiments" / "analysis"
RESULTS_PATH = PROJECT_ROOT / "experiments" / "results" / "all_results.parquet"
CLASSES_PATH = PROJECT_ROOT / "benchmarks" / "classes.csv"
CLUSTERS_PATH = PROJECT_ROOT / "benchmarks" / "clusters.csv"

N_PASSES = len(PASSES)


def load_data() -> pd.DataFrame:
    """Загружает данные с группировками."""
    df = pd.read_parquet(RESULTS_PATH)
    df = df[df["status"] == "success"].copy()
    df["winning"] = df["ir_count"] < df["baseline_oz"]

    classes = pd.read_csv(CLASSES_PATH)
    clusters = pd.read_csv(CLUSTERS_PATH)
    df = df.merge(classes, on="benchmark", how="left")
    df = df.merge(clusters, on="benchmark", how="left")
    return df


def build_correlation_graph(
    sequences: np.ndarray,
    winning: np.ndarray,
    alpha: float = 0.05,
) -> pd.DataFrame:
    """Строит корреляционный граф из биг��амм выигрышных последовательностей.

    Для каждой упорядоченной пары (A, B):
      - Считаем долю выигрышных среди последовательностей, где A→B — биграмма
      - Считаем долю выигрышных среди всех остальных
      - Chi-squared тест
    """
    pass_to_idx = {p: i for i, p in enumerate(PASSES)}

    # Считаем биграммы для каждого прогона
    # pair_key (i, j) → lists of winning flags
    from collections import defaultdict

    has_bigram = defaultdict(list)  # (i,j) → list of (has_bigram_bool, winning_bool)
    no_bigram = defaultdict(list)

    n = len(sequences)
    for row in range(n):
        seq = json.loads(sequences[row])
        w = winning[row]
        # Собираем би��раммы этого прогона
        bigrams_in_run = set()
        for k in range(len(seq) - 1):
            a_idx = pass_to_idx.get(seq[k])
            b_idx = pass_to_idx.get(seq[k + 1])
            if a_idx is not None and b_idx is not None:
                bigrams_in_run.add((a_idx, b_idx))

        for pair in bigrams_in_run:
            has_bigram[pair].append(w)

    # Общая доля выигрышных
    total_wins = winning.sum()
    total_n = len(winning)
    base_rate = total_wins / total_n

    results = []
    for i in range(N_PASSES):
        for j in range(N_PASSES):
            if i == j:
                continue
            key = (i, j)
            wins_with = has_bigram.get(key, [])
            n_with = len(wins_with)
            if n_with < 20:
                continue

            wins_with_count = sum(wins_with)
            rate_with = wins_with_count / n_with
            n_without = total_n - n_with
            wins_without = total_wins - wins_with_count

            # Chi-squared 2x2: bigram present/absent × winning/losing
            table = np.array([
                [wins_with_count, n_with - wins_with_count],
                [wins_without, n_without - wins_without],
            ])
            if table.min() < 5:
                continue

            chi2, p_value = sp_stats.chi2_contingency(table, correction=False)[:2]

            results.append({
                "pass_a": PASSES[i],
                "pass_b": PASSES[j],
                "rate_with_bigram": rate_with,
                "rate_without_bigram": wins_without / max(n_without, 1),
                "n_with_bigram": n_with,
                "chi2": chi2,
                "p_value": p_value,
            })

    df = pd.DataFrame(results)
    if len(df) == 0:
        return df

    # BH-FDR
    n_tests = len(df)
    sorted_idx = np.argsort(df["p_value"].values)
    sorted_p = df["p_value"].values[sorted_idx]
    rank = np.arange(1, n_tests + 1, dtype=np.float64)
    adjusted = np.minimum.accumulate((sorted_p * n_tests / rank)[::-1])[::-1]
    adjusted = np.minimum(adjusted, 1.0)
    p_adj = np.empty(n_tests)
    p_adj[sorted_idx] = adjusted
    df["p_adj"] = p_adj
    df["significant"] = p_adj < alpha

    # Оставляем только рёбра где бигр��мма ассоциирована с выигрышем
    df["positive"] = df["rate_with_bigram"] > df["rate_without_bigram"]
    edges = df[df["significant"] & df["positive"]].copy()

    return edges


def compare_graphs(variant_dir: str, corr_edges: pd.DataFrame, level: str):
    """Сравнивает каузальный и корреляционный графы."""
    causal_path = variant_dir / f"graph_{level}.csv"
    if not causal_path.exists():
        return None

    causal = pd.read_csv(causal_path)
    causal_set = set(zip(causal["source"], causal["target"]))
    corr_set = set(zip(corr_edges["pass_a"], corr_edges["pass_b"]))

    both = causal_set & corr_set
    only_causal = causal_set - corr_set
    only_corr = corr_set - causal_set

    return {
        "level": level,
        "n_causal": len(causal_set),
        "n_correlation": len(corr_set),
        "n_both": len(both),
        "n_only_causal": len(only_causal),
        "n_only_correlation": len(only_corr),
        "false_correlation_rate": len(only_corr) / max(len(corr_set), 1),
    }


def run_correlation(formulation: str = "B", alpha: float = 0.05):
    """Строит корреляционные графы и сравнивает с каузальными."""
    log.info(f"=== Корреляционный граф: вариант {formulation} ===")

    df = load_data()
    variant_dir = OUTPUT_DIR / f"variant_{formulation}"

    comparisons = []

    # Глобальный
    log.info("Корреляционный граф: global...")
    t0 = time.time()
    corr_global = build_correlation_graph(
        df["sequence"].values, df["winning"].values, alpha
    )
    log.info(f"  {len(corr_global)} рёбер, {time.time() - t0:.1f}с")
    corr_global.to_csv(variant_dir / "corr_global.csv", index=False)

    comp = compare_graphs(variant_dir, corr_global, "global")
    if comp:
        comparisons.append(comp)

    # Per-class
    for cls in sorted(df["domain_class"].unique()):
        mask = df["domain_class"] == cls
        log.info(f"Корреляционный граф: class_{cls}...")
        corr = build_correlation_graph(
            df.loc[mask, "sequence"].values,
            df.loc[mask, "winning"].values,
            alpha,
        )
        log.info(f"  {len(corr)} рёбер")
        corr.to_csv(variant_dir / f"corr_class_{cls}.csv", index=False)

        comp = compare_graphs(variant_dir, corr, f"class_{cls}")
        if comp:
            comparisons.append(comp)

    # Per-cluster
    for cid in sorted(df["cluster"].dropna().unique().astype(int)):
        mask = df["cluster"] == cid
        log.info(f"Корреляционный граф: cluster_{cid}...")
        corr = build_correlation_graph(
            df.loc[mask, "sequence"].values,
            df.loc[mask, "winning"].values,
            alpha,
        )
        log.info(f"  {len(corr)} рёбер")
        corr.to_csv(variant_dir / f"corr_cluster_{cid}.csv", index=False)

        comp = compare_graphs(variant_dir, corr, f"cluster_{cid}")
        if comp:
            comparisons.append(comp)

    # Сводка сравнения
    comp_df = pd.DataFrame(comparisons)
    comp_df.to_csv(variant_dir / "comparison_causal_vs_corr.csv", index=False)

    log.info("\nСравнение каузальный vs корреляционный:")
    for _, row in comp_df.iterrows():
        log.info(
            f"  {row['level']}: каузальный={row['n_causal']}, "
            f"корреляционный={row['n_correlation']}, "
            f"ложных корреляций={row['false_correlation_rate']:.1%}"
        )

    log.info("=== Корреляционный граф готово ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Корреляционный граф (шаг 6)")
    parser.add_argument("--formulation", choices=["B", "V"], default="B")
    args = parser.parse_args()
    run_correlation(args.formulation)
