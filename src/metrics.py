#!/usr/bin/env python3
"""
Подсчёт метрик для LLVM IR.

Основная метрика — число IR-инструкций через llvm-dis → парсинг .ll.
Считаем только инструкции внутри тел функций (строки с отступом),
исключая метки (начало basic block).
"""

import os
import subprocess
import tempfile


def count_ir_instructions(bc_file_path: str,
                          llvm_bin_path: str = "/opt/homebrew/opt/llvm@16/bin") -> int:
    """
    Подсчитывает количество IR-инструкций в .bc файле.

    Алгоритм: llvm-dis → парсинг .ll → подсчёт строк с отступом внутри
    тел функций. В текстовом представлении LLVM IR инструкции всегда
    имеют отступ, а метки (entry points basic blocks) — нет.

    Args:
        bc_file_path: Путь к .bc файлу
        llvm_bin_path: Путь к директории с бинарниками LLVM 16

    Returns:
        Количество инструкций, или -1 при ошибке
    """
    ll_file_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.ll', delete=False) as temp_ll:
            ll_file_path = temp_ll.name

        cmd = [os.path.join(llvm_bin_path, 'llvm-dis'), bc_file_path, '-o', ll_file_path]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"Ошибка llvm-dis для {bc_file_path}: {result.stderr}")
            return -1

        instruction_count = 0
        in_function = False
        in_multiline = False  # продолжение switch [ ... ]

        with open(ll_file_path, 'r') as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith('define '):
                    in_function = True
                    continue
                if stripped == '}':
                    in_function = False
                    continue
                if not in_function:
                    continue
                if in_multiline:
                    if stripped == ']':
                        in_multiline = False
                    continue
                # Внутри функции: инструкции имеют отступ, метки — нет
                if line[0] in (' ', '\t') and stripped and not stripped.startswith(';'):
                    instruction_count += 1
                    # switch с [ в конце — начало многострочной конструкции
                    if stripped.endswith('['):
                        in_multiline = True

        return instruction_count

    except Exception as e:
        print(f"Ошибка при подсчёте инструкций для {bc_file_path}: {e}")
        return -1
    finally:
        if ll_file_path and os.path.exists(ll_file_path):
            os.unlink(ll_file_path)
