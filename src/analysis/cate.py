#!/usr/bin/env python3
"""
Шаг 5: CATE — гетерогенность эффектов.

Для каждого ребра глобального графа собирает ATE в подгруппах:
  - per-class (8 классов)
  - per-cluster (6 кластеров)
  - per-benchmark (517 бенчмарков)

Использование:
    python -m src.analysis.cate [--formulation B|V]
"""

import argparse
import json
import logging
import time

import numpy as np
import pandas as pd
from scipy import stats

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

MIN_OBS = 10  # минимум на группу для CATE per-benchmark


def collect_group_cate(formulation: str) -> pd.DataFrame:
    """Собирает CATE per-class и per-cluster из уже посчитанных ATE-таблиц."""
    variant_dir = OUTPUT_DIR / f"variant_{formulation}"
    global_edges = pd.read_csv(variant_dir / "graph_global.csv")

    # Создаём ключ для join
    edge_keys = set(zip(global_edges["source"], global_edges["target"]))

    result = global_edges[["source", "target", "ate"]].copy()
    result = result.rename(columns={"ate": "ate_global"})

    # Собираем per-class ATE
    for f in sorted(variant_dir.glob("ate_class_*.csv")):
        cls = f.stem.replace("ate_class_", "")
        df = pd.read_csv(f)

        ate_map = {}
        for _, row in df.iterrows():
            a, b, ate = row["pass_a"], row["pass_b"], row["ate"]
            if (a, b) in edge_keys:
                ate_map[(a, b)] = ate
            elif (b, a) in edge_keys:
                ate_map[(b, a)] = -ate

        result[f"cate_{cls}"] = result.apply(
            lambda r: ate_map.get((r["source"], r["target"]), np.nan), axis=1
        )

    # Собираем per-cluster ATE
    for f in sorted(variant_dir.glob("ate_cluster_*.csv")):
        cid = f.stem.replace("ate_cluster_", "")
        df = pd.read_csv(f)

        ate_map = {}
        for _, row in df.iterrows():
            a, b, ate = row["pass_a"], row["pass_b"], row["ate"]
            if (a, b) in edge_keys:
                ate_map[(a, b)] = ate
            elif (b, a) in edge_keys:
                ate_map[(b, a)] = -ate

        result[f"cate_cluster_{cid}"] = result.apply(
            lambda r: ate_map.get((r["source"], r["target"]), np.nan), axis=1
        )

    return result


def compute_benchmark_cate(formulation: str) -> pd.DataFrame:
    """Вычисляет CATE per-benchmark для рёбер глобального графа."""
    variant_dir = OUTPUT_DIR / f"variant_{formulation}"
    global_edges = pd.read_csv(variant_dir / "graph_global.csv")

    log.info("Загрузка данных для per-benchmark CATE...")
    df = pd.read_parquet(RESULTS_PATH)
    df = df[df["status"] == "success"].copy()
    df["reduction"] = (df["baseline_raw"] - df["ir_count"]) / df["baseline_raw"]

    pass_to_idx = {p: i for i, p in enumerate(PASSES)}

    # Для каждого ребра и бенчмарка — ATE
    log.info(f"Вычисление CATE для {len(global_edges)} рёбер × {df['benchmark'].nunique()} бенчмарков...")
    t0 = time.time()

    records = []
    for bench, group in df.groupby("benchmark"):
        sequences = group["sequence"].values
        outcomes = group["reduction"].values

        # Позиции для этого бенчмарка
        n = len(group)
        positions = np.full((n, len(PASSES)), -1, dtype=np.int8)
        for row in range(n):
            for pos, name in enumerate(json.loads(sequences[row])):
                col = pass_to_idx.get(name)
                if col is not None:
                    positions[row, col] = pos

        for _, edge in global_edges.iterrows():
            src, tgt = edge["source"], edge["target"]
            i = pass_to_idx[src]
            j = pass_to_idx[tgt]

            both = (positions[:, i] >= 0) & (positions[:, j] >= 0)

            if formulation == "B":
                treatment = both & (positions[:, i] < positions[:, j])
                control = both & (positions[:, j] < positions[:, i])
            else:
                treatment = both & (positions[:, j] == positions[:, i] + 1)
                control = both & (positions[:, i] == positions[:, j] + 1)

            n_t, n_c = treatment.sum(), control.sum()
            if n_t < MIN_OBS or n_c < MIN_OBS:
                continue

            ate = outcomes[treatment].mean() - outcomes[control].mean()
            records.append({
                "source": src,
                "target": tgt,
                "benchmark": bench,
                "cate": ate,
                "n_treatment": int(n_t),
                "n_control": int(n_c),
            })

    elapsed = time.time() - t0
    log.info(f"  {len(records)} записей, {elapsed:.1f}с")
    return pd.DataFrame(records)


def run_cate(formulation: str = "B"):
    """Собирает все уровни CATE и сохраняет."""
    log.info(f"=== CATE: вариант {formulation} ===")
    variant_dir = OUTPUT_DIR / f"variant_{formulation}"

    # Per-class и per-cluster из готовых файлов
    group_cate = collect_group_cate(formulation)
    group_cate.to_csv(variant_dir / "cate_groups.csv", index=False)
    log.info(f"CATE per-class/per-cluster: {len(group_cate)} рёбер, сохранено в cate_groups.csv")

    # Статистика гетерогенности
    cate_cols = [c for c in group_cate.columns if c.startswith("cate_")]
    for col in cate_cols:
        vals = group_cate[col].dropna()
        n_pos = (vals > 0).sum()
        n_neg = (vals < 0).sum()
        log.info(f"  {col}: {len(vals)} рёбер, {n_pos} положительных, {n_neg} отрицательных")

    # Per-benchmark
    bench_cate = compute_benchmark_cate(formulation)
    bench_cate.to_csv(variant_dir / "cate_benchmarks.csv", index=False)
    log.info(f"CATE per-benchmark: {len(bench_cate)} записей, сохранено в cate_benchmarks.csv")

    log.info("=== CATE готово ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CATE (шаг 5)")
    parser.add_argument("--formulation", choices=["B", "V"], default="B")
    args = parser.parse_args()
    run_cate(args.formulation)
