#!/usr/bin/env python3
"""
Генерация большого читаемого топ-20 графа содержательного каузального графа
для слайда защиты (presentation2, слайд 8).

Содержательный граф = полный глобальный граф (608 рёбер, variant_B/graph_global.csv)
минус рёбра «раздуватель -> сократитель» (E -> R) минус рёбра с loop-vectorize.
Топ-20 рёбер устойчив к выбору списка сократителей (проверено) и его топ-10
совпадает с таблицей 6 диплома.

Раскладка — круговой spring-layout (как в исходном графе топ-50), узлы по кругу,
направленные рёбра показывают «кто за кем».

Запуск:
    python docs/defense/presentation/make_top20_graph.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
GRAPH_CSV = ROOT / "experiments" / "analysis" / "variant_B" / "graph_global.csv"
IMG_DIR = Path(__file__).resolve().parent / "images"
OUT = IMG_DIR / "graph_global_top20_filtered.png"

EXPANDERS = {
    "loop-vectorize", "loop-unroll", "loop-unroll-and-jam", "slp-vectorizer",
    "inline", "always-inline", "partial-inliner", "break-crit-edges",
    "loop-fusion", "loop-distribute", "loop-versioning", "loop-reroll",
    "simple-loop-unswitch", "irce", "loop-rotate", "callsite-splitting",
    "scalarizer", "lowerswitch", "separate-const-offset-from-gep",
    "loop-interchange", "loop-load-elim", "loop-sink", "hotcoldsplit",
    "iroutliner", "partially-inline-libcalls", "speculative-execution",
    "load-store-vectorizer", "vector-combine", "slsr", "nary-reassociate",
    "consthoist", "flattencfg", "libcalls-shrinkwrap", "lower-expect",
    "globalsplit", "global-merge",
}
REDUCERS = {
    "instcombine", "dse", "simplifycfg", "jump-threading", "dfa-jump-threading",
    "gvn", "newgvn", "early-cse", "early-cse-memssa", "sccp", "ipsccp", "dce",
    "adce", "bdce", "instsimplify", "gvn-hoist", "gvn-sink",
    "correlated-propagation", "mem2reg", "sroa", "licm", "memcpyopt",
}

PASS_CATEGORIES = {
    "scalar": [
        "instcombine", "simplifycfg", "reassociate", "sccp", "ipsccp", "bdce",
        "dce", "adce", "dse", "gvn", "gvn-hoist", "gvn-sink", "newgvn",
        "early-cse", "early-cse-memssa", "correlated-propagation",
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
        "slp-vectorizer", "vector-combine", "load-store-vectorizer", "scalarizer",
    ],
    "other": [
        "mergeicmps", "separate-const-offset-from-gep", "libcalls-shrinkwrap",
        "alignment-from-assumptions",
    ],
}
CATEGORY_COLORS = {
    "scalar": "#4C72B0", "loop": "#55A868", "interprocedural": "#C44E52",
    "cfg": "#8172B2", "vectorization": "#CCB974", "other": "#999999",
}
# белый текст на тёмных заливках, чёрный — на светлых
DARK_FILL = {"scalar", "loop", "interprocedural", "cfg"}
CATEGORY_RU = {
    "scalar": "скалярные", "loop": "циклы", "interprocedural": "межпроцедурные",
    "cfg": "поток управления", "vectorization": "векторизация", "other": "прочие",
}


def category(name):
    for cat, passes in PASS_CATEGORIES.items():
        if name in passes:
            return cat
    return "other"


def main():
    df = pd.read_csv(GRAPH_CSV)
    er = df.apply(lambda r: r["source"] in EXPANDERS and r["target"] in REDUCERS, axis=1)
    sub = df[~er]
    sub = sub[(sub["source"] != "loop-vectorize") & (sub["target"] != "loop-vectorize")]
    top = sub.sort_values("ate", ascending=False).head(20).reset_index(drop=True)

    G = nx.DiGraph()
    for _, r in top.iterrows():
        G.add_edge(r["source"], r["target"], ate=r["ate"])

    # Узлы по кругу: источники и стоки сгруппированы, чтобы рёбра меньше
    # пересекались, а направление «кто за кем» читалось.
    out_deg = {n: G.out_degree(n) for n in G.nodes()}
    in_deg = {n: G.in_degree(n) for n in G.nodes()}
    # сортировка по «роли»: чистые источники -> смешанные -> чистые стоки
    order = sorted(G.nodes(), key=lambda n: (in_deg[n] - out_deg[n], n))
    pos = nx.circular_layout(order)

    node_colors = [CATEGORY_COLORS[category(n)] for n in G.nodes()]
    ates = [G[u][v]["ate"] for u, v in G.edges()]
    mx = max(ates)
    widths = [1.6 + 5.5 * (a / mx) for a in ates]

    fig, ax = plt.subplots(figsize=(15, 11))
    nx.draw_networkx_nodes(
        G, pos, ax=ax, node_color=node_colors,
        node_size=2600, edgecolors="black", linewidths=1.2,
    )
    nx.draw_networkx_edges(
        G, pos, ax=ax, width=widths, edge_color="#555555",
        arrows=True, arrowsize=28, arrowstyle="-|>",
        connectionstyle="arc3,rad=0.1", alpha=0.7,
        node_size=2600, min_source_margin=14, min_target_margin=20,
    )
    nx.draw_networkx_labels(
        G, pos, ax=ax, font_size=18, font_weight="bold", font_family="monospace",
    )

    cats_present = {category(n) for n in G.nodes()}
    patches = [
        mpatches.Patch(color=CATEGORY_COLORS[c], label=CATEGORY_RU[c])
        for c in CATEGORY_COLORS if c in cats_present
    ]
    ax.legend(handles=patches, loc="upper left", fontsize=16, framealpha=0.95)
    ax.margins(0.16)
    ax.axis("off")
    plt.tight_layout(pad=0.2)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"saved: {OUT}  (edges={len(top)}, nodes={G.number_of_nodes()})")


if __name__ == "__main__":
    main()
