#!/usr/bin/env python3
"""
Визуализация каузальных графов и результатов анализа.

Использование:
    python -m src.visualization [--formulation B|V]
"""

import argparse
import logging

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx
import numpy as np
import pandas as pd

from src.config import PROJECT_ROOT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

ANALYSIS_DIR = PROJECT_ROOT / "experiments" / "analysis"
FIGURES_DIR = PROJECT_ROOT / "experiments" / "figures"

# Цвета для категорий проходов
PASS_CATEGORIES = {
    "scalar": [
        "instcombine", "simplifycfg", "reassociate", "sccp", "ipsccp",
        "bdce", "dce", "adce", "dse", "gvn", "gvn-hoist", "gvn-sink",
        "newgvn", "early-cse", "early-cse-memssa", "correlated-propagation",
        "jump-threading", "dfa-jump-threading", "mem2reg", "sroa",
        "instsimplify", "memcpyopt", "sink", "mldst-motion", "slsr",
        "consthoist", "nary-reassociate", "div-rem-pairs", "float2int",
    ],
    "loop": [
        "licm", "loop-simplify", "loop-idiom", "loop-deletion", "indvars",
        "loop-reduce", "loop-unroll", "loop-rotate", "loop-interchange",
        "loop-fusion", "loop-distribute", "loop-load-elim", "loop-sink",
        "loop-unroll-and-jam", "irce", "loop-versioning", "loop-flatten",
        "loop-reroll", "loop-instsimplify", "loop-simplifycfg",
        "loop-predication", "simple-loop-unswitch", "loop-vectorize",
    ],
    "interprocedural": [
        "inline", "always-inline", "partial-inliner", "function-attrs",
        "rpo-function-attrs", "deadargelim", "attributor", "inferattrs",
        "called-value-propagation", "callsite-splitting", "hotcoldsplit",
        "partially-inline-libcalls", "globaldce", "globalopt",
        "elim-avail-extern", "strip-dead-prototypes", "constmerge",
        "mergefunc", "globalsplit", "iroutliner", "global-merge",
    ],
    "cfg": [
        "break-crit-edges", "mergereturn", "lowerswitch", "flattencfg",
        "unreachableblockelim", "tailcallelim", "lower-expect",
        "speculative-execution",
    ],
    "vectorization": [
        "slp-vectorizer", "vector-combine", "load-store-vectorizer",
        "scalarizer",
    ],
    "other": [
        "mergeicmps", "separate-const-offset-from-gep",
        "libcalls-shrinkwrap", "alignment-from-assumptions",
    ],
}

CATEGORY_COLORS = {
    "scalar": "#4C72B0",
    "loop": "#55A868",
    "interprocedural": "#C44E52",
    "cfg": "#8172B2",
    "vectorization": "#CCB974",
    "other": "#999999",
}


def _get_pass_category(pass_name: str) -> str:
    for cat, passes in PASS_CATEGORIES.items():
        if pass_name in passes:
            return cat
    return "other"


def _load_graph(path) -> nx.DiGraph:
    df = pd.read_csv(path)
    G = nx.DiGraph()
    for _, row in df.iterrows():
        G.add_edge(row["source"], row["target"], ate=row["ate"], p_adj=row["p_adj"])
    return G


def plot_causal_graph(
    graph_path,
    title: str,
    output_path,
    top_n: int = 50,
    min_ate: float = 0.0,
):
    """Визуализация каузального графа (top-N рёбер по ATE)."""
    df = pd.read_csv(graph_path)
    df = df[df["ate"] >= min_ate].nlargest(top_n, "ate")

    if len(df) == 0:
        log.info(f"  Нет рёбер для {title}")
        return

    G = nx.DiGraph()
    for _, row in df.iterrows():
        G.add_edge(row["source"], row["target"], ate=row["ate"])

    # Позиции
    pos = nx.spring_layout(G, k=2.5, iterations=80, seed=42)

    # Цвета узлов
    node_colors = [CATEGORY_COLORS[_get_pass_category(n)] for n in G.nodes()]

    # Толщина рёбер по ATE
    ates = [G[u][v]["ate"] for u, v in G.edges()]
    max_ate = max(ates) if ates else 1
    widths = [1 + 4 * (a / max_ate) for a in ates]

    fig, ax = plt.subplots(figsize=(16, 12))

    nx.draw_networkx_nodes(
        G, pos, ax=ax, node_color=node_colors,
        node_size=600, edgecolors="black", linewidths=0.5,
    )
    nx.draw_networkx_labels(
        G, pos, ax=ax, font_size=7, font_weight="bold",
    )
    nx.draw_networkx_edges(
        G, pos, ax=ax, width=widths, edge_color="#555555",
        arrows=True, arrowsize=15, arrowstyle="-|>",
        connectionstyle="arc3,rad=0.1", alpha=0.7,
    )

    # Легенда
    patches = [
        mpatches.Patch(color=CATEGORY_COLORS[cat], label=cat)
        for cat in CATEGORY_COLORS
    ]
    ax.legend(handles=patches, loc="upper left", fontsize=9, framealpha=0.9)

    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.axis("off")
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    log.info(f"  Сохранено: {output_path}")


def plot_comparison_bar(variant_dir, output_path):
    """Столбчатая диаграмма: каузальный vs корреляционный по уровням."""
    comp_path = variant_dir / "comparison_causal_vs_corr.csv"
    if not comp_path.exists():
        return

    df = pd.read_csv(comp_path)

    fig, ax = plt.subplots(figsize=(14, 6))
    x = np.arange(len(df))
    w = 0.35

    bars1 = ax.bar(x - w / 2, df["n_causal"], w, label="Каузальный", color="#4C72B0")
    bars2 = ax.bar(x + w / 2, df["n_correlation"], w, label="Корреляционный", color="#C44E52")

    # Процент ложных корреляций
    for i, row in df.iterrows():
        ax.text(
            i + w / 2, row["n_correlation"] + 30,
            f"{row['false_correlation_rate']:.0%}",
            ha="center", va="bottom", fontsize=8, color="#C44E52", fontweight="bold",
        )

    ax.set_xticks(x)
    ax.set_xticklabels(df["level"], rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("Число рёбер")
    ax.set_title("Каузальный vs корреляционный граф (% — доля ложных корреляций)", fontsize=13)
    ax.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    log.info(f"  Сохранено: {output_path}")


def plot_cate_heatmap(variant_dir, output_path):
    """Хитмэп CATE: рёбра × классы/кластеры."""
    cate_path = variant_dir / "cate_groups.csv"
    if not cate_path.exists():
        return

    df = pd.read_csv(cate_path)

    # Топ-30 рёбер по глобальному ATE
    df = df.nlargest(30, "ate_global")

    cate_cols = [c for c in df.columns if c.startswith("cate_")]
    labels = [f"{row['source']}→{row['target']}" for _, row in df.iterrows()]

    matrix = df[cate_cols].values
    col_labels = [c.replace("cate_", "") for c in cate_cols]

    fig, ax = plt.subplots(figsize=(14, 10))
    vmax = np.nanmax(np.abs(matrix))
    im = ax.imshow(matrix, cmap="RdBu_r", aspect="auto", vmin=-vmax, vmax=vmax)

    ax.set_xticks(range(len(col_labels)))
    ax.set_xticklabels(col_labels, rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=8)

    # Значения в ячейках
    for i in range(len(labels)):
        for j in range(len(col_labels)):
            val = matrix[i, j]
            if not np.isnan(val):
                color = "white" if abs(val) > vmax * 0.6 else "black"
                ax.text(j, i, f"{val:.3f}", ha="center", va="center", fontsize=6, color=color)

    plt.colorbar(im, ax=ax, label="CATE", shrink=0.8)
    ax.set_title("CATE: топ-30 рёбер × классы/кластеры", fontsize=13)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    log.info(f"  Сохранено: {output_path}")


def plot_variant_comparison(output_path):
    """Сравнение числа рёбер: вариант Б vs В."""
    levels = []
    b_edges = []
    v_edges = []

    for name in ["global"] + [f"class_{c}" for c in
        ["crypto", "general", "loop_bench", "multimedia", "numeric",
         "pointer_data", "string_parse", "systems"]] + [f"cluster_{i}" for i in range(6)]:
        b_path = ANALYSIS_DIR / "variant_B" / f"graph_{name}.csv"
        v_path = ANALYSIS_DIR / "variant_V" / f"graph_{name}.csv"
        if b_path.exists() and v_path.exists():
            levels.append(name)
            b_edges.append(len(pd.read_csv(b_path)))
            v_edges.append(len(pd.read_csv(v_path)))

    fig, ax = plt.subplots(figsize=(14, 6))
    x = np.arange(len(levels))
    w = 0.35

    ax.bar(x - w / 2, b_edges, w, label="Вариант Б (относительный порядок)", color="#4C72B0")
    ax.bar(x + w / 2, v_edges, w, label="Вариант В (соседство)", color="#55A868")

    ax.set_xticks(x)
    ax.set_xticklabels(levels, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("Число рёбер")
    ax.set_title("Каузальные графы: вариант Б vs В", fontsize=13)
    ax.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    log.info(f"  Сохранено: {output_path}")


def run_visualization(formulation: str = "B"):
    """Генерирует все визуализации."""
    log.info(f"=== Визуализация: вариант {formulation} ===")

    variant_dir = ANALYSIS_DIR / f"variant_{formulation}"
    fig_dir = FIGURES_DIR / f"variant_{formulation}"
    fig_dir.mkdir(parents=True, exist_ok=True)

    # 1. Глобальный каузальный граф (топ-50)
    log.info("Глобальный каузальный граф...")
    plot_causal_graph(
        variant_dir / "graph_global.csv",
        f"Глобальный каузальный граф (вариант {'Б' if formulation == 'B' else 'В'}, топ-50)",
        fig_dir / "graph_global_top50.png",
        top_n=50,
    )

    # 2. Per-class графы (топ-30)
    for cls in ["crypto", "general", "loop_bench", "multimedia", "numeric",
                "pointer_data", "string_parse", "systems"]:
        path = variant_dir / f"graph_class_{cls}.csv"
        if path.exists() and len(pd.read_csv(path)) > 0:
            log.info(f"Граф class_{cls}...")
            plot_causal_graph(
                path, f"Каузальный граф: {cls} (топ-30)",
                fig_dir / f"graph_class_{cls}.png", top_n=30,
            )

    # 3. Per-cluster графы (топ-30)
    for cid in range(6):
        path = variant_dir / f"graph_cluster_{cid}.csv"
        if path.exists() and len(pd.read_csv(path)) > 0:
            log.info(f"Граф cluster_{cid}...")
            plot_causal_graph(
                path, f"Каузальный граф: кластер {cid} (топ-30)",
                fig_dir / f"graph_cluster_{cid}.png", top_n=30,
            )

    # 4. Сравнение каузальный vs корреляционный
    log.info("Сравнение каузальный vs корреляционный...")
    plot_comparison_bar(variant_dir, fig_dir / "comparison_causal_vs_corr.png")

    # 5. CATE хитмэп
    log.info("CATE хитмэп...")
    plot_cate_heatmap(variant_dir, fig_dir / "cate_heatmap.png")

    # 6. Сравнение Б vs В
    if formulation == "B":
        log.info("Сравнение Б vs В...")
        plot_variant_comparison(FIGURES_DIR / "comparison_B_vs_V.png")

    log.info("=== Визуализация готова ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Визуализация")
    parser.add_argument("--formulation", choices=["B", "V"], default="B")
    args = parser.parse_args()
    run_visualization(args.formulation)
