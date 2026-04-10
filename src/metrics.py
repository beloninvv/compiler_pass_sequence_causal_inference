#!/usr/bin/env python3
"""
Подсчёт метрик для LLVM IR.

Основная метрика — число IR-инструкций через llvm-dis → парсинг .ll.
Функция научника: считаем все значимые строки (инструкции + глобалы),
пропускаем пустые строки, комментарии, метки, define/declare, метаданные.
"""

import os
import subprocess
import tempfile


def count_ir_instructions(bc_file_path: str,
                          llvm_bin_path: str = "/opt/homebrew/opt/llvm@16/bin") -> int:
    """
    Подсчитывает количество инструкций в LLVM IR файле.

    Алгоритм: llvm-dis → парсинг .ll → подсчёт всех значимых строк.
    Пропускаются: пустые строки, комментарии (;), метки (:),
    define/declare, метаданные (!, attributes, target).

    Args:
        bc_file_path: Путь к .bc файлу
        llvm_bin_path: Путь к директории с бинарниками LLVM 16

    Returns:
        Количество инструкций, или -1 при ошибке
    """
    try:
        with tempfile.NamedTemporaryFile(suffix='.ll', delete=False) as temp_ll:
            ll_file_path = temp_ll.name

        cmd = [os.path.join(llvm_bin_path, 'llvm-dis'), bc_file_path, '-o', ll_file_path]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"Ошибка llvm-dis для {bc_file_path}: {result.stderr}")
            return -1

        with open(ll_file_path, 'r') as f:
            content = f.read()

        os.unlink(ll_file_path)

        instruction_count = 0
        for line in content.split('\n'):
            line = line.strip()
            if not line or line.startswith(';'):
                continue
            if line.endswith(':'):
                continue
            if line.startswith('define ') or line.startswith('declare '):
                continue
            if line.startswith('!') or line.startswith('attributes ') or line.startswith('target '):
                continue
            instruction_count += 1

        return instruction_count

    except Exception as e:
        print(f"Ошибка при подсчёте инструкций для {bc_file_path}: {e}")
        if os.path.exists(ll_file_path):
            os.unlink(ll_file_path)
        return -1
