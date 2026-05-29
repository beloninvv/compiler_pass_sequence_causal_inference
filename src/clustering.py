#!/usr/bin/env python3
"""
Кластеризация программ по IR-фичам.

Pipeline:
  1. Загрузка фичей из benchmarks/features.parquet
  2. Выбор нормализованных фичей (instruction mix + structural)
  3. StandardScaler → PCA (95% дисперсии)
  4. K-means (автовыбор k по silhouette) или HDBSCAN
  5. Визуализация (PCA 2D scatter)

Использование:
    source .venv/bin/activate
    python3 src/clustering.py [--method kmeans|hdbscan] [--k 5]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from config import BENCHMARKS_DIR

FEATURES_PATH = BENCHMARKS_DIR.parent / "features.parquet"
OUTPUT_DIR = BENCHMARKS_DIR.parent

# Фичи для кластеризации: нормализованные (не зависят от размера программы)
CLUSTERING_FEATURES = [
    # Доли по категориям инструкций
    "frac_int_arith", "frac_float_arith", "frac_logic", "frac_memory",
    "frac_comparison", "frac_conversion", "frac_control", "frac_call",
    "frac_phi", "frac_select", "frac_vector", "frac_aggregate",
    # Доли ключевых опкодов внутри категорий
    "frac_load", "frac_store", "frac_alloca", "frac_getelementptr", "frac_br",
    # Структурные характеристики
    "avg_bb_size", "avg_func_size", "avg_bbs_per_func",
    # Ratios
    "load_store_ratio", "int_float_ratio",
]


# ── Подготовка данных ──────────────────────────────────────────────────────

def load_and_prepare(
    features_path: Path = FEATURES_PATH,
) -> tuple[pd.DataFrame, np.ndarray, list[str]]:
    """Загрузить фичи, отобрать, масштабировать."""
    df = pd.read_parquet(features_path)

    X = df[CLUSTERING_FEATURES].copy()

    # Убрать фичи с нулевой дисперсией (например, frac_vector = 0 для всех)
    zero_var = X.columns[X.std() == 0].tolist()
    if zero_var:
        print(f"Dropping {len(zero_var)} zero-variance features: {zero_var}")
        X = X.drop(columns=zero_var)

    feature_names = list(X.columns)

    X_scaled = StandardScaler().fit_transform(X)

    return df, X_scaled, feature_names


def run_pca(
    X_scaled: np.ndarray, variance_threshold: float = 0.95,
) -> tuple[np.ndarray, PCA]:
    """PCA, сохраняя компоненты для variance_threshold дисперсии."""
    cumvar = np.cumsum(PCA().fit(X_scaled).explained_variance_ratio_)
    n_components = int(np.searchsorted(cumvar, variance_threshold) + 1)

    pca = PCA(n_components=n_components)
    X_pca = pca.fit_transform(X_scaled)

    print(f"PCA: {X_scaled.shape[1]} features → {n_components} components "
          f"({pca.explained_variance_ratio_.sum():.1%} variance)")
    return X_pca, pca


# ── Кластеризация ─────────────────────────────────────────────────────────

def find_best_k(
    X: np.ndarray, k_range: range = range(3, 16),
) -> tuple[int, dict[int, float]]:
    """Подобрать k для KMeans по silhouette score."""
    scores: dict[int, float] = {}
    for k in k_range:
        labels = KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(X)
        scores[k] = silhouette_score(X, labels)

    best_k = max(scores, key=scores.get)
    print("\nSilhouette scores:")
    for k, s in sorted(scores.items()):
        marker = " <-- best" if k == best_k else ""
        print(f"  k={k:2d}: {s:.4f}{marker}")

    return best_k, scores


def cluster_kmeans(X: np.ndarray, k: int | None = None) -> tuple[np.ndarray, int]:
    """KMeans кластеризация."""
    if k is None:
        k, _ = find_best_k(X)

    labels = KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(X)
    sil = silhouette_score(X, labels)
    print(f"\nKMeans: k={k}, silhouette={sil:.4f}")
    return labels, k


def cluster_hdbscan(X: np.ndarray, min_cluster_size: int = 15) -> np.ndarray:
    """HDBSCAN кластеризация."""
    labels = HDBSCAN(min_cluster_size=min_cluster_size).fit_predict(X)

    n_clusters = len(set(labels) - {-1})
    n_noise = int((labels == -1).sum())

    if n_clusters >= 2:
        mask = labels != -1
        sil = silhouette_score(X[mask], labels[mask])
        print(f"HDBSCAN: {n_clusters} clusters, {n_noise} noise points, "
              f"silhouette={sil:.4f}")
    else:
        print(f"HDBSCAN: {n_clusters} cluster(s), {n_noise} noise points")

    return labels


# ── Визуализация и отчёт ──────────────────────────────────────────────────

def plot_clusters(
    X_pca: np.ndarray, labels: np.ndarray, method: str, output_path: Path,
) -> None:
    """2D PCA scatter plot по кластерам."""
    fig, ax = plt.subplots(figsize=(10, 7))

    unique_labels = sorted(set(labels))
    cmap = plt.colormaps.get_cmap("tab10").resampled(max(len(unique_labels), 1))

    for label in unique_labels:
        mask = labels == label
        if label == -1:
            ax.scatter(X_pca[mask, 0], X_pca[mask, 1],
                       c="gray", alpha=0.3, s=15, label=f"noise (n={mask.sum()})")
        else:
            ax.scatter(X_pca[mask, 0], X_pca[mask, 1],
                       c=[cmap(label)], alpha=0.6, s=25,
                       label=f"cluster {label} (n={mask.sum()})")

    ax.set_xlabel("PC1")
    ax.set_ylabel("PC2")
    ax.set_title(f"Program clustering ({method})")
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"Plot saved to {output_path}")


def print_cluster_summary(df: pd.DataFrame, labels: np.ndarray) -> None:
    """Сводка по каждому кластеру."""
    df = df.copy()
    df["cluster"] = labels

    print(f"\n{'='*60}")
    print("Cluster summary")
    print(f"{'='*60}")

    for cid in sorted(df["cluster"].unique()):
        members = df[df["cluster"] == cid]
        name = f"Cluster {cid}" if cid != -1 else "Noise"

        print(f"\n{name} ({len(members)} programs):")
        print(f"  total_instructions: median={members['total_instructions'].median():.0f}, "
              f"range=[{members['total_instructions'].min()}, "
              f"{members['total_instructions'].max()}]")

        # Средние доли по категориям
        frac_means = {
            col: members[col].mean()
            for col in CLUSTERING_FEATURES
            if col.startswith("frac_") and col in members.columns
        }
        top = sorted(frac_means.items(), key=lambda x: -x[1])[:5]
        print("  top categories: " + ", ".join(
            f"{n.replace('frac_', '')}={v:.3f}" for n, v in top
        ))

        # Примеры программ
        sample = list(members.index[:5])
        extra = len(members) - len(sample)
        suffix = f", ... (+{extra} more)" if extra > 0 else ""
        print(f"  examples: {', '.join(sample)}{suffix}")


# ── Main ───────────────────────────────────────────────────────────────────

def main(
    method: str = "kmeans",
    k: int | None = None,
    min_cluster_size: int = 15,
) -> pd.DataFrame:
    # 1. Подготовка
    df, X_scaled, feature_names = load_and_prepare()
    print(f"Using {len(feature_names)} features for {len(df)} benchmarks")

    # 2. PCA
    X_pca, pca = run_pca(X_scaled)

    # 3. Кластеризация
    if method == "kmeans":
        labels, k = cluster_kmeans(X_pca, k)
    elif method == "hdbscan":
        labels = cluster_hdbscan(X_pca, min_cluster_size)
    else:
        raise ValueError(f"Unknown method: {method}")

    # 4. Сохранение
    result = pd.DataFrame({"benchmark": df.index, "cluster": labels})
    out_csv = OUTPUT_DIR / "clusters.csv"
    result.to_csv(out_csv, index=False)
    print(f"\nCluster assignments saved to {out_csv}")

    # 5. Визуализация
    plot_path = OUTPUT_DIR / f"clustering_{method}.png"
    plot_clusters(X_pca, labels, method, plot_path)

    # 6. Сводка
    print_cluster_summary(df, labels)

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Cluster benchmarks by IR features",
    )
    parser.add_argument("--method", choices=["kmeans", "hdbscan"], default="kmeans")
    parser.add_argument("--k", type=int, default=None,
                        help="Number of clusters for kmeans (auto if omitted)")
    parser.add_argument("--min-cluster-size", type=int, default=15,
                        help="Min cluster size for HDBSCAN")
    args = parser.parse_args()

    main(method=args.method, k=args.k, min_cluster_size=args.min_cluster_size)
