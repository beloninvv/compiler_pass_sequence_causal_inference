#!/usr/bin/env python3
"""
Запуск эксперимента: случайные перестановки проходов LLVM на бенчмарках.

Для каждого .bc файла:
  1. Считаем baseline (raw + Oz)
  2. Генерируем 10,000 случайных последовательностей проходов
  3. Для каждой считаем число IR-инструкций
  4. Сохраняем результаты в Parquet (чекпоинт после каждого бенчмарка)

Использование:
    source .venv/bin/activate
    python3 src/experiment.py [--workers 8] [--resume]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from multiprocessing import Pool
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config import (
    BENCHMARKS_DIR, LLVM_BIN, MAX_SEQ_LENGTH, MIN_SEQ_LENGTH,
    NUM_ITERATIONS, OPT, OPT_TIMEOUT, PASSES, RESULTS_DIR, SEED,
)
from metrics import count_ir_instructions


# ── Вспомогательные функции ───────────────────────────────────────────────

def discover_benchmarks(benchmarks_dir: Path) -> list[tuple[str, Path]]:
    """Найти все .bc файлы. Возвращает [(name, path), ...]."""
    bc_files = sorted(benchmarks_dir.glob("*.bc"))
    return [(f.stem, f) for f in bc_files]


def run_opt(input_bc: Path, passes: list[str], output_bc: Path) -> bool:
    """Запустить opt с legacy PM. Возвращает True при успехе."""
    cmd = [OPT, "-enable-new-pm=0"] + [f"-{p}" for p in passes] + [str(input_bc), "-o", str(output_bc)]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=OPT_TIMEOUT)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def compute_baseline_raw(bc_path: Path) -> int:
    """Baseline: число IR-инструкций без оптимизаций."""
    return count_ir_instructions(str(bc_path), LLVM_BIN)


def compute_baseline_oz(bc_path: Path, tmpdir: str) -> int:
    """Baseline: число IR-инструкций после -Oz (new PM)."""
    output = os.path.join(tmpdir, "baseline_oz.bc")
    cmd = [OPT, "-Oz", str(bc_path), "-o", output]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=OPT_TIMEOUT)
        if result.returncode != 0:
            return -1
        return count_ir_instructions(output, LLVM_BIN)
    except subprocess.TimeoutExpired:
        return -1


def generate_sequence(rng: random.Random) -> list[str]:
    """Сгенерировать случайную последовательность проходов."""
    length = rng.randint(MIN_SEQ_LENGTH, MAX_SEQ_LENGTH)
    selected = rng.sample(PASSES, length)
    return selected


# ── Обработка одного бенчмарка ────────────────────────────────────────────

def run_benchmark(args: tuple) -> dict:
    """
    Прогнать все итерации для одного бенчмарка.
    Вызывается из multiprocessing.Pool.

    Args:
        args: (bench_name, bench_path, bench_seed, num_iterations)

    Returns:
        dict с результатами и метаданными
    """
    bench_name, bench_path, bench_seed, num_iterations = args
    bench_path = Path(bench_path)
    rng = random.Random(bench_seed)

    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        # Baselines
        baseline_raw = compute_baseline_raw(bench_path)
        baseline_oz = compute_baseline_oz(bench_path, tmpdir)

        if baseline_raw == -1:
            print(f"  SKIP {bench_name}: не удалось посчитать baseline raw")
            return {"benchmark": bench_name, "status": "skip", "results": []}

        opt_output = os.path.join(tmpdir, "opt_output.bc")

        for i in range(num_iterations):
            sequence = generate_sequence(rng)

            success = run_opt(bench_path, sequence, opt_output)

            if not success:
                results.append({
                    "benchmark": bench_name,
                    "sequence": sequence,
                    "seq_length": len(sequence),
                    "ir_count": -1,
                    "baseline_raw": baseline_raw,
                    "baseline_oz": baseline_oz,
                    "status": "failed",
                })
                continue

            ir_count = count_ir_instructions(opt_output, LLVM_BIN)

            results.append({
                "benchmark": bench_name,
                "sequence": sequence,
                "seq_length": len(sequence),
                "ir_count": ir_count,
                "baseline_raw": baseline_raw,
                "baseline_oz": baseline_oz,
                "status": "success" if ir_count != -1 else "metric_failed",
            })

    return {"benchmark": bench_name, "status": "done", "results": results}


# ── Сохранение результатов ────────────────────────────────────────────────

def save_benchmark_results(results: list[dict], output_path: Path):
    """Сохранить результаты одного бенчмарка в Parquet."""
    if not results:
        return

    df = pd.DataFrame(results)
    # Конвертируем sequence в строку JSON для Parquet
    df["sequence"] = df["sequence"].apply(json.dumps)
    df.to_parquet(output_path, index=False)


def merge_results(checkpoints_dir: Path, output_path: Path):
    """Склеить все чекпоинты в один Parquet."""
    parts = sorted(checkpoints_dir.glob("*.parquet"))
    if not parts:
        print("Нет чекпоинтов для склейки")
        return

    dfs = [pd.read_parquet(p) for p in parts]
    merged = pd.concat(dfs, ignore_index=True)
    merged.to_parquet(output_path, index=False)

    total = len(merged)
    success = (merged["status"] == "success").sum()
    failed = (merged["status"] == "failed").sum()
    print(f"Склеено: {total} прогонов ({success} успешных, {failed} упавших)")


# ── Главная функция ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Запуск эксперимента: случайные перестановки проходов LLVM"
    )
    parser.add_argument("--workers", type=int, default=8,
                        help="Число параллельных процессов (default: 8)")
    parser.add_argument("--resume", action="store_true",
                        help="Пропустить бенчмарки, для которых уже есть чекпоинт")
    parser.add_argument("--benchmarks-dir", type=Path, default=BENCHMARKS_DIR,
                        help="Директория с .bc файлами")
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR,
                        help="Директория для результатов")
    parser.add_argument("--num-iterations", type=int, default=NUM_ITERATIONS,
                        help=f"Число итераций на бенчмарк (default: {NUM_ITERATIONS})")
    parser.add_argument("--limit", type=int, default=None,
                        help="Обработать только первые N бенчмарков (для тестов)")
    args = parser.parse_args()

    # Подготовка директорий
    checkpoints_dir = args.output_dir / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)

    # Находим бенчмарки
    benchmarks = discover_benchmarks(args.benchmarks_dir)
    print(f"Найдено {len(benchmarks)} бенчмарков")

    if args.limit:
        benchmarks = benchmarks[:args.limit]
        print(f"Ограничено до {len(benchmarks)} (--limit)")

    # Пропускаем уже обработанные при --resume
    if args.resume:
        done = {p.stem for p in checkpoints_dir.glob("*.parquet")}
        before = len(benchmarks)
        benchmarks = [(n, p) for n, p in benchmarks if n not in done]
        print(f"Пропущено {before - len(benchmarks)} уже обработанных, осталось {len(benchmarks)}")

    if not benchmarks:
        print("Нечего обрабатывать")
        merge_results(checkpoints_dir, args.output_dir / "all_results.parquet")
        return

    # Генерируем seed для каждого бенчмарка (воспроизводимость)
    master_rng = random.Random(SEED)
    # Создаём словарь seed для ВСЕХ бенчмарков (включая пропущенные),
    # чтобы seed не зависел от порядка обработки
    all_benchmarks = discover_benchmarks(args.benchmarks_dir)
    bench_seeds = {name: master_rng.randint(0, 2**32 - 1) for name, _ in all_benchmarks}

    tasks = [(name, str(path), bench_seeds[name], args.num_iterations)
             for name, path in benchmarks]

    print(f"Запуск: {len(tasks)} бенчмарков × {args.num_iterations} итераций = "
          f"{len(tasks) * args.num_iterations:,} прогонов")
    print(f"Workers: {args.workers}, длина последовательности: [{MIN_SEQ_LENGTH}, {MAX_SEQ_LENGTH}]")
    print()

    start_time = time.time()
    completed = 0

    with Pool(processes=args.workers) as pool:
        for result in pool.imap_unordered(run_benchmark, tasks):
            completed += 1
            bench_name = result["benchmark"]
            elapsed = time.time() - start_time

            if result["status"] == "skip":
                print(f"[{completed}/{len(tasks)}] {bench_name}: SKIP ({elapsed:.0f}s)")
                continue

            # Сохраняем чекпоинт
            checkpoint_path = checkpoints_dir / f"{bench_name}.parquet"
            save_benchmark_results(result["results"], checkpoint_path)

            n_success = sum(1 for r in result["results"] if r["status"] == "success")
            n_failed = sum(1 for r in result["results"] if r["status"] == "failed")
            rate = completed / elapsed if elapsed > 0 else 0
            eta = (len(tasks) - completed) / rate if rate > 0 else 0

            print(f"[{completed}/{len(tasks)}] {bench_name}: "
                  f"{n_success} ok, {n_failed} fail "
                  f"({elapsed:.0f}s, ETA {eta:.0f}s)")

    # Склейка
    total_time = time.time() - start_time
    print(f"\nВсе бенчмарки обработаны за {total_time:.0f}s ({total_time/3600:.1f}h)")

    output_path = args.output_dir / "all_results.parquet"
    merge_results(checkpoints_dir, output_path)
    print(f"Результаты: {output_path}")


if __name__ == "__main__":
    main()
