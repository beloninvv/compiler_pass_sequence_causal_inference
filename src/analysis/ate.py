#!/usr/bin/env python3
"""
Шаги 1-3 pipeline каузального анализа:
  1. ATE для всех 3916 пар проходов
  2. Benjamini-Hochberg FDR коррекция
  3. Построение каузальных графов (глобальный, per-class, per-cluster)

Обоснование: рандомизированный эксперимент (случайный порядок проходов)
=> ATE является каузальным эффектом без дополнительных поправок на конфаундеры.

Использование:
    python -m src.analysis.ate [--formulation B|V] [--alpha 0.05]
"""

import argparse
import json
import logging
import time
from pathlib import Path

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

# ── Пути ─────────────────────────────────────────────────────────────────────

RESULTS_PATH = PROJECT_ROOT / "experiments" / "results" / "all_results.parquet"
CLASSES_PATH = PROJECT_ROOT / "benchmarks" / "classes.csv"
CLUSTERS_PATH = PROJECT_ROOT / "benchmarks" / "clusters.csv"
OUTPUT_DIR = PROJECT_ROOT / "experiments" / "analysis"

N_PASSES = len(PASSES)
N_PAIRS = N_PASSES * (N_PASSES - 1) // 2  # 3916

MIN_OBS = 20  # минимум наблюдений на группу (treatment/control)


# ── Загрузка данных ──────────────────────────────────────────────────────────


def load_data() -> pd.DataFrame:
    """Загружает результаты эксперимента, классы и кластеры бенчмарков."""
    log.info("Загрузка данных...")
    df = pd.read_parquet(RESULTS_PATH)

    n_total = len(df)
    df = df[df["status"] == "success"].copy()
    log.info(f"  {n_total} прогонов, {len(df)} успешных")

    # Outcome: Y = (baseline_raw - ir_count) / baseline_raw
    df["reduction"] = (df["baseline_raw"] - df["ir_count"]) / df["baseline_raw"]

    # Группировки
    classes = pd.read_csv(CLASSES_PATH)
    clusters = pd.read_csv(CLUSTERS_PATH)
    df = df.merge(classes, on="benchmark", how="left")
    df = df.merge(clusters, on="benchmark", how="left")

    log.info(
        f"  Классы: {sorted(df['domain_class'].unique())} "
        f"| Кластеры: {sorted(df['cluster'].dropna().unique().astype(int))}"
    )
    return df


# ── Матрица позиций ─────────────────────────────────────────────────────────


def build_position_matrix(sequences: np.ndarray) -> np.ndarray:
    """Парсит последовательности и строит матрицу позиций.

    Returns:
        positions: (n_runs, 89) int8.
            Позиция прохода в последовательности (0-based), -1 если отсутствует.
    """
    log.info("Построение матрицы позиций...")
    t0 = time.time()

    pass_to_idx = {p: i for i, p in enumerate(PASSES)}
    n = len(sequences)
    positions = np.full((n, N_PASSES), -1, dtype=np.int8)

    for row in range(n):
        for pos, name in enumerate(json.loads(sequences[row])):
            col = pass_to_idx.get(name)
            if col is not None:
                positions[row, col] = pos

    elapsed = time.time() - t0
    log.info(f"  Матрица {positions.shape}, {elapsed:.1f}с")
    return positions


# ── Вычисление ATE ───────────────────────────────────────────────────────────


def compute_all_ate(
    positions: np.ndarray,
    outcomes: np.ndarray,
    formulation: str = "B",
) -> pd.DataFrame:
    """Вычисляет ATE для всех 3916 пар проходов.

    Args:
        positions: (n_runs, 89) int8
        outcomes: (n_runs,) float64
        formulation: "B" (относительный порядок) или "V" (соседство)

    Returns:
        DataFrame: pass_a, pass_b, ate, t_stat, p_value, n_treatment, n_control
    """
    results = []

    for i in range(N_PASSES):
        for j in range(i + 1, N_PASSES):
            row = _compute_pair_ate(positions, outcomes, i, j, formulation)
            if row is not None:
                results.append(row)

    df = pd.DataFrame(results)
    log.info(f"  Вычислено {len(df)} пар из {N_PAIRS}")
    return df


def _compute_pair_ate(
    positions: np.ndarray,
    outcomes: np.ndarray,
    i: int,
    j: int,
    formulation: str,
) -> dict | None:
    """Вычисляет ATE для одной пары (i, j)."""
    # Оба прохода присутствуют
    both = (positions[:, i] >= 0) & (positions[:, j] >= 0)

    if formulation == "B":
        # Вариант Б: A где-то перед B vs B где-то перед A
        treatment = both & (positions[:, i] < positions[:, j])
        control = both & (positions[:, j] < positions[:, i])
    elif formulation == "V":
        # Вариант В: A непосредственно перед B vs B непосредственно перед A
        treatment = both & (positions[:, j] == positions[:, i] + 1)
        control = both & (positions[:, i] == positions[:, j] + 1)
    else:
        raise ValueError(f"Unknown formulation: {formulation}")

    n_t = treatment.sum()
    n_c = control.sum()

    if n_t < MIN_OBS or n_c < MIN_OBS:
        return None

    y_t = outcomes[treatment]
    y_c = outcomes[control]

    ate = y_t.mean() - y_c.mean()
    t_stat, p_value = stats.ttest_ind(y_t, y_c, equal_var=False)

    return {
        "pass_a": PASSES[i],
        "pass_b": PASSES[j],
        "ate": ate,
        "t_stat": t_stat,
        "p_value": p_value,
        "n_treatment": int(n_t),
        "n_control": int(n_c),
    }


# ── BH-FDR коррекция ────────────────────────────────────────────────────────


def apply_bh_fdr(p_values: np.ndarray, alpha: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg FDR коррекция.

    Returns:
        p_adj: скорректированные p-values
        significant: boolean mask
    """
    n = len(p_values)
    sorted_idx = np.argsort(p_values)
    sorted_p = p_values[sorted_idx]

    # BH: p_adj_i = p_i * n / rank_i
    rank = np.arange(1, n + 1, dtype=np.float64)
    adjusted = sorted_p * n / rank

    # Монотонность: cumulative minimum справа налево
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    adjusted = np.minimum(adjusted, 1.0)

    # Обратно в исходный порядок
    p_adj = np.empty(n)
    p_adj[sorted_idx] = adjusted

    return p_adj, p_adj < alpha


# ── Построение графа ────────────────────────────────────────────────────────


def build_graph_edges(df: pd.DataFrame, min_ate: float = 0.0) -> pd.DataFrame:
    """Строит направленные рёбра из значимых ATE.

    Ребро A → B если ATE(A,B) > 0 (A перед B лучше).
    Ребро B → A если ATE(A,B) < 0 (B перед A лучше).

    Args:
        min_ate: минимальный |ATE| для включения ребра в граф.
    """
    sig = df[df["significant"] & (df["ate"].abs() >= min_ate)]
    if len(sig) == 0:
        return pd.DataFrame(columns=["source", "target", "ate", "p_adj"])

    edges = []
    for _, row in sig.iterrows():
        if row["ate"] > 0:
            src, tgt, ate = row["pass_a"], row["pass_b"], row["ate"]
        else:
            src, tgt, ate = row["pass_b"], row["pass_a"], -row["ate"]
        edges.append({
            "source": src,
            "target": tgt,
            "ate": ate,
            "p_adj": row["p_adj"],
        })

    return pd.DataFrame(edges)


# ── Pipeline для одной группы ────────────────────────────────────────────────


def analyze_group(
    positions: np.ndarray,
    outcomes: np.ndarray,
    mask: np.ndarray | None,
    formulation: str,
    alpha: float,
    min_ate: float,
    label: str,
    output_dir: Path,
) -> pd.DataFrame:
    """Полный pipeline (шаги 1-3) для одной группы."""
    if mask is not None:
        pos = positions[mask]
        y = outcomes[mask]
        n_runs = mask.sum()
    else:
        pos = positions
        y = outcomes
        n_runs = len(outcomes)

    log.info(f"[{label}] {n_runs} прогонов")

    # Шаг 1: ATE
    t0 = time.time()
    results = compute_all_ate(pos, y, formulation)

    if len(results) == 0:
        log.info(f"  [{label}] Нет пар с достаточным числом наблюдений")
        return results

    # Шаг 2: BH-FDR
    p_adj, significant = apply_bh_fdr(results["p_value"].values, alpha)
    results["p_adj"] = p_adj
    results["significant"] = significant

    n_sig = significant.sum()
    elapsed = time.time() - t0
    log.info(f"  [{label}] {len(results)} пар, {n_sig} значимых, {elapsed:.1f}с")

    # Сохраняем таблицу ATE
    results.to_csv(output_dir / f"ate_{label}.csv", index=False)

    # Шаг 3: Граф
    edges = build_graph_edges(results, min_ate=min_ate)
    edges.to_csv(output_dir / f"graph_{label}.csv", index=False)
    log.info(f"  [{label}] Граф: {len(edges)} рёбер (min_ate={min_ate})")

    return results


# ── Основной pipeline ────────────────────────────────────────────────────────


def run_analysis(formulation: str = "B", alpha: float = 0.05, min_ate: float = 0.005):
    """Запуск полного pipeline: ATE + FDR + графы для всех уровней."""
    log.info(f"=== Каузальный анализ: вариант {formulation}, alpha={alpha}, min_ate={min_ate} ===")

    df = load_data()
    positions = build_position_matrix(df["sequence"].values)
    outcomes = df["reduction"].values.astype(np.float64)

    output_dir = OUTPUT_DIR / f"variant_{formulation}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Глобальный граф ──
    global_results = analyze_group(
        positions, outcomes, None, formulation, alpha, min_ate, "global", output_dir
    )

    # ── Per-class графы ──
    for cls in sorted(df["domain_class"].unique()):
        mask = (df["domain_class"] == cls).values
        analyze_group(
            positions, outcomes, mask, formulation, alpha, min_ate, f"class_{cls}", output_dir
        )

    # ── Per-cluster графы ──
    for cid in sorted(df["cluster"].dropna().unique().astype(int)):
        mask = (df["cluster"] == cid).values
        analyze_group(
            positions, outcomes, mask, formulation, alpha, min_ate, f"cluster_{cid}", output_dir
        )

    log.info("=== Готово ===")
    return global_results


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ATE pipeline (шаги 1-3)")
    parser.add_argument(
        "--formulation", choices=["B", "V"], default="B",
        help="Формулировка treatment: B=относительный порядок, V=соседство",
    )
    parser.add_argument(
        "--alpha", type=float, default=0.05,
        help="Уровень значимости для FDR (default: 0.05)",
    )
    parser.add_argument(
        "--min-ate", type=float, default=0.005,
        help="Минимальный |ATE| для включения ребра в граф (default: 0.005)",
    )
    args = parser.parse_args()

    run_analysis(formulation=args.formulation, alpha=args.alpha, min_ate=args.min_ate)
