#!/usr/bin/env python3
"""
Конфигурация проекта: пути LLVM, список проходов, параметры эксперимента.
"""

from pathlib import Path

# ── Пути ──────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
LLVM_BIN = "/opt/homebrew/opt/llvm@16/bin"
OPT = f"{LLVM_BIN}/opt"
LLVM_DIS = f"{LLVM_BIN}/llvm-dis"

BENCHMARKS_DIR = PROJECT_ROOT / "benchmarks" / "compiled"
RESULTS_DIR = PROJECT_ROOT / "experiments" / "results"

# ── Параметры эксперимента ────────────────────────────────────────────────

NUM_ITERATIONS = 10_000       # прогонов на бенчмарк
MIN_SEQ_LENGTH = 10           # минимальная длина последовательности
MAX_SEQ_LENGTH = 40           # максимальная длина последовательности
SEED = 42                     # для воспроизводимости
OPT_TIMEOUT = 60              # таймаут opt в секундах

# ── Перемешиваемые проходы (89 штук) ─────────────────────────────────────
# Все проверены в legacy PM LLVM 16.
# -enable-new-pm=0 добавляется отдельно как фиксированный флаг.

PASSES = [
    # Из -Oz (33):
    "bdce", "ipsccp", "correlated-propagation", "mem2reg", "sroa",
    "instsimplify", "constmerge", "function-attrs", "deadargelim",
    "globaldce", "elim-avail-extern", "mergefunc", "instcombine",
    "simplifycfg", "tailcallelim", "reassociate", "memcpyopt", "sccp",
    "dce", "adce", "dse", "jump-threading", "loop-idiom", "loop-deletion",
    "gvn", "gvn-hoist", "gvn-sink", "newgvn", "early-cse", "mergereturn",
    "globalopt", "strip-dead-prototypes", "indvars",

    # Расширение от научника (14):
    "mergeicmps", "separate-const-offset-from-gep", "libcalls-shrinkwrap",
    "flattencfg", "loop-reduce", "loop-unroll", "loop-rotate",
    "partial-inliner", "lower-expect", "alignment-from-assumptions",
    "rpo-function-attrs", "attributor", "inferattrs",
    "called-value-propagation",

    # Добавленные — базовые (4):
    "licm", "loop-simplify", "div-rem-pairs", "float2int",

    # Добавленные — инлайнинг, векторизация, скалярные (23):
    "inline", "sink", "loop-vectorize", "slp-vectorizer",
    "callsite-splitting", "dfa-jump-threading", "consthoist",
    "mldst-motion", "slsr", "loop-interchange", "loop-fusion",
    "loop-distribute", "loop-load-elim", "loop-sink",
    "loop-unroll-and-jam", "hotcoldsplit", "irce", "nary-reassociate",
    "scalarizer", "vector-combine", "always-inline", "globalsplit",
    "lowerswitch",

    # Добавленные — loop-оптимизации и вспомогательные (15):
    "early-cse-memssa", "simple-loop-unswitch", "loop-versioning",
    "loop-flatten", "loop-reroll", "loop-instsimplify", "loop-simplifycfg",
    "loop-predication", "speculative-execution",
    "partially-inline-libcalls", "load-store-vectorizer", "iroutliner",
    "global-merge", "break-crit-edges", "unreachableblockelim",
]

assert len(PASSES) == 89, f"Ожидалось 89 проходов, получено {len(PASSES)}"
