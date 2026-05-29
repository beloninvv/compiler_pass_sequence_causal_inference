#!/usr/bin/env python3
"""
Извлечение IR-фичей из .bc файлов для кластеризации программ.

Фичи извлекаются через llvm-dis → парсинг .ll:
- Подсчёт инструкций по опкодам
- Доли инструкций по категориям (instruction mix)
- Структурные характеристики (BB, функции, средние размеры)

Использование:
    source .venv/bin/activate
    python3 src/features.py [--workers 6]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from config import BENCHMARKS_DIR, LLVM_DIS


# ── Опкоды LLVM IR ─────────────────────────────────────────────────────────

LLVM_OPCODES = {
    # Terminator
    "ret", "br", "switch", "indirectbr", "invoke", "callbr",
    "resume", "catchswitch", "catchret", "cleanupret", "unreachable",
    # Unary
    "fneg",
    # Binary
    "add", "fadd", "sub", "fsub", "mul", "fmul",
    "udiv", "sdiv", "fdiv", "urem", "srem", "frem",
    # Bitwise
    "shl", "lshr", "ashr", "and", "or", "xor",
    # Vector
    "extractelement", "insertelement", "shufflevector",
    # Aggregate
    "extractvalue", "insertvalue",
    # Memory
    "alloca", "load", "store", "fence", "cmpxchg", "atomicrmw",
    "getelementptr",
    # Conversion
    "trunc", "zext", "sext", "fptrunc", "fpext",
    "fptoui", "fptosi", "uitofp", "sitofp",
    "ptrtoint", "inttoptr", "bitcast", "addrspacecast",
    # Other
    "icmp", "fcmp", "phi", "select", "freeze",
    "call", "va_arg", "landingpad", "catchpad", "cleanuppad",
}

_CALL_MODIFIERS = {"tail", "musttail", "notail"}

# ── Группировка опкодов по категориям ──────────────────────────────────────

CATEGORIES = {
    "int_arith": {"add", "sub", "mul", "udiv", "sdiv", "urem", "srem"},
    "float_arith": {"fadd", "fsub", "fmul", "fdiv", "frem", "fneg"},
    "logic": {"and", "or", "xor", "shl", "lshr", "ashr"},
    "memory": {"load", "store", "alloca", "getelementptr",
               "fence", "cmpxchg", "atomicrmw"},
    "comparison": {"icmp", "fcmp"},
    "conversion": {"trunc", "zext", "sext", "fptrunc", "fpext",
                   "fptoui", "fptosi", "uitofp", "sitofp",
                   "ptrtoint", "inttoptr", "bitcast", "addrspacecast"},
    "control": {"br", "switch", "ret", "indirectbr", "invoke", "callbr",
                "resume", "catchswitch", "catchret", "cleanupret",
                "unreachable"},
    "call": {"call", "invoke"},
    "phi": {"phi"},
    "select": {"select"},
    "vector": {"extractelement", "insertelement", "shufflevector"},
    "aggregate": {"extractvalue", "insertvalue"},
}


# ── Парсинг .ll ────────────────────────────────────────────────────────────

def _extract_opcode(instruction: str) -> str | None:
    """
    Извлекает опкод из строки инструкции LLVM IR.

    Обрабатывает формы:
        %result = opcode ...
        %result = tail call ...
        store ...
        br ...
    """
    text = instruction.strip()

    # Убираем результат: %name = ...
    eq_pos = text.find(" = ")
    if eq_pos != -1 and text[:eq_pos].lstrip().startswith("%"):
        text = text[eq_pos + 3:].lstrip()

    parts = text.split(None, 2)
    if not parts:
        return None

    if parts[0] in LLVM_OPCODES:
        return parts[0]

    # Модификаторы call: tail/musttail/notail
    if parts[0] in _CALL_MODIFIERS and len(parts) >= 2 and parts[1] in LLVM_OPCODES:
        return parts[1]

    return None


def _parse_ll_file(ll_path: str) -> dict:
    """
    Парсит .ll файл и извлекает сырые данные.

    Returns:
        dict с opcode_counts, num_functions, num_declared,
        num_globals, num_basic_blocks.
    """
    opcode_counts: dict[str, int] = defaultdict(int)
    num_functions = 0
    num_declared = 0
    num_globals = 0
    num_basic_blocks = 0
    in_function = False
    in_multiline = False

    with open(ll_path, "r") as f:
        for line in f:
            stripped = line.strip()

            if not stripped or stripped.startswith(";"):
                continue

            # Function definition → entry BB
            if stripped.startswith("define "):
                num_functions += 1
                in_function = True
                num_basic_blocks += 1
                continue

            if stripped.startswith("declare "):
                num_declared += 1
                continue

            if stripped == "}":
                in_function = False
                continue

            if not in_function:
                if stripped.startswith("@") and "=" in stripped:
                    num_globals += 1
                continue

            # --- внутри функции ---

            # Продолжение switch [ ... ]
            if in_multiline:
                if stripped == "]":
                    in_multiline = False
                continue

            # Метка basic block (не с отступом)
            if not line[0].isspace():
                label_part = stripped.split(";")[0].strip()
                if label_part.endswith(":"):
                    num_basic_blocks += 1
                continue

            # Инструкция (с отступом)
            if stripped and not stripped.startswith(";"):
                opcode = _extract_opcode(stripped)
                if opcode:
                    opcode_counts[opcode] += 1

                if stripped.endswith("["):
                    in_multiline = True

    return {
        "opcode_counts": dict(opcode_counts),
        "num_functions": num_functions,
        "num_declared": num_declared,
        "num_globals": num_globals,
        "num_basic_blocks": num_basic_blocks,
    }


# ── Вычисление фичей ──────────────────────────────────────────────────────

def _compute_features(raw: dict, bc_path: str) -> dict | None:
    """Вычисляет фичи из сырых данных парсинга."""
    oc = raw["opcode_counts"]
    total = sum(oc.values())

    if total == 0:
        return None

    features: dict = {
        "benchmark": Path(bc_path).stem,
        # Масштаб
        "total_instructions": total,
        "num_functions": raw["num_functions"],
        "num_declared_functions": raw["num_declared"],
        "num_globals": raw["num_globals"],
        "num_basic_blocks": raw["num_basic_blocks"],
        # Средние
        "avg_bb_size": total / max(raw["num_basic_blocks"], 1),
        "avg_func_size": total / max(raw["num_functions"], 1),
        "avg_bbs_per_func": raw["num_basic_blocks"] / max(raw["num_functions"], 1),
    }

    # Доли по категориям
    for cat_name, cat_opcodes in CATEGORIES.items():
        cat_count = sum(oc.get(op, 0) for op in cat_opcodes)
        features[f"frac_{cat_name}"] = cat_count / total

    # Отдельные доли для ключевых опкодов
    for op in ("load", "store", "alloca", "getelementptr", "br", "phi"):
        features[f"frac_{op}"] = oc.get(op, 0) / total

    # Ratios
    loads, stores = oc.get("load", 0), oc.get("store", 0)
    features["load_store_ratio"] = loads / max(loads + stores, 1)

    int_a = sum(oc.get(op, 0) for op in CATEGORIES["int_arith"])
    float_a = sum(oc.get(op, 0) for op in CATEGORIES["float_arith"])
    features["int_float_ratio"] = int_a / max(int_a + float_a, 1)

    # Сырые подсчёты по опкодам
    for opcode in sorted(LLVM_OPCODES):
        features[f"op_{opcode}"] = oc.get(opcode, 0)

    return features


# ── Извлечение фичей из .bc ────────────────────────────────────────────────

def extract_features(bc_file_path: str,
                     llvm_dis: str = LLVM_DIS) -> dict | None:
    """
    Извлекает IR-фичи из одного .bc файла.

    Returns:
        Словарь фичей или None при ошибке.
    """
    ll_file_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ll", delete=False) as f:
            ll_file_path = f.name

        result = subprocess.run(
            [llvm_dis, bc_file_path, "-o", ll_file_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"llvm-dis error for {bc_file_path}: {result.stderr}")
            return None

        raw = _parse_ll_file(ll_file_path)
        return _compute_features(raw, bc_file_path)

    except Exception as e:
        print(f"Error extracting features from {bc_file_path}: {e}")
        return None
    finally:
        if ll_file_path and os.path.exists(ll_file_path):
            os.unlink(ll_file_path)


def _worker(args: tuple[str, str]) -> dict | None:
    """Worker для параллельного извлечения."""
    bc_path, llvm_dis = args
    return extract_features(bc_path, llvm_dis)


def extract_all_features(
    benchmarks_dir: Path = BENCHMARKS_DIR,
    llvm_dis: str = LLVM_DIS,
    n_workers: int = 6,
) -> pd.DataFrame:
    """
    Извлекает фичи из всех .bc файлов.

    Returns:
        DataFrame с одной строкой на бенчмарк.
    """
    bc_files = sorted(Path(benchmarks_dir).glob("*.bc"))
    print(f"Extracting features from {len(bc_files)} benchmarks...")

    args = [(str(f), llvm_dis) for f in bc_files]

    with Pool(n_workers) as pool:
        results = pool.map(_worker, args)

    features_list = [r for r in results if r is not None]
    failed = len(bc_files) - len(features_list)
    if failed:
        print(f"Warning: {failed} benchmarks failed feature extraction")

    df = pd.DataFrame(features_list).set_index("benchmark")
    print(f"Extracted {len(df.columns)} features for {len(df)} benchmarks")
    return df


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract IR features from benchmarks")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    df = extract_all_features(n_workers=args.workers)

    out_path = BENCHMARKS_DIR.parent / "features.parquet"
    df.to_parquet(out_path)
    print(f"\nSaved to {out_path}")

    # Сводка
    print(f"\nShape: {df.shape}")
    print(f"\nScale features:")
    for col in ("total_instructions", "num_functions", "num_basic_blocks"):
        print(f"  {col}: min={df[col].min()}, "
              f"median={df[col].median():.0f}, max={df[col].max()}")

    print(f"\nInstruction mix (mean fractions):")
    frac_cols = sorted(c for c in df.columns if c.startswith("frac_"))
    for col in frac_cols:
        mean_val = df[col].mean()
        if mean_val > 0.001:
            print(f"  {col}: {mean_val:.4f}")
