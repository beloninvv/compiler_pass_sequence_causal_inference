# Заметки по реорганизации проекта

## Что было изменено

### 1. Структура папок

**Было:**
```
compiler_pass_sequence_causal_inference/
├── setup_benchmarks.py
├── run_experiment.py
├── ...
├── benchmarks_bc/
├── _benchmarks_repo/
├── 2500iter/
└── 5000iter_variable/
```

**Стало:**
```
compiler_pass_sequence_causal_inference/
├── src/                          # Весь код
├── benchmarks/
│   ├── source/lac-dcc-benchmarks/  # Все benchmark suites
│   └── compiled/                   # .bc файлы
├── experiments/
│   ├── exp1_fixed_length/
│   └── exp2_variable_length/
└── docs/                         # Материалы диплома
```

### 2. Обновлённые пути в коде

**src/setup_benchmarks.py:**
- `_benchmarks_repo/cBench` → `benchmarks/source/lac-dcc-benchmarks/cBench`
- `benchmarks_bc` → `benchmarks/compiled`

**src/run_experiment.py и src/run_experiment_variable.py:**
- Примеры в docstring обновлены на новые пути

### 3. Как запускать скрипты с новыми путями

#### Компиляция бенчмарков
```bash
python3 src/setup_benchmarks.py
```
Автоматически использует:
- Вход: `benchmarks/source/lac-dcc-benchmarks/cBench/`
- Выход: `benchmarks/compiled/`

#### Запуск экспериментов
```bash
# Фиксированная длина
python3 src/run_experiment.py \
    --benchmarks-dir ./benchmarks/compiled \
    --num-iterations 2500 \
    --output experiments/exp1_fixed_length/raw_results.json

# Переменная длина
python3 src/run_experiment_variable.py \
    --benchmarks-dir ./benchmarks/compiled \
    --num-iterations 5000 \
    --min-length 10 \
    --max-length 30 \
    --output experiments/exp2_variable_length/raw_results.json
```

#### Каузальный анализ
```bash
python3 src/causal_graph_discovery.py \
    --input experiments/exp2_variable_length/raw_results_variable.json \
    --output-dir experiments/exp2_variable_length/causal_graph
```

### 4. Где все benchmark suites

Все бенчмарки из оригинального lac-dcc/Benchmarks репозитория сохранены:

```
benchmarks/source/lac-dcc-benchmarks/
├── cBench/           # То, что используем
├── MiBench/
├── PolyBench/
├── SPEC-подобные/
└── ... (всего 35+ наборов)
```

Мы используем только **cBench** (19 программ), но остальные доступны для будущих экспериментов.

### 5. Совместимость

 Весь код обновлён и работает с новой структурой
 Все эксперименты сохранены в `experiments/`
 README.md содержит правильные примеры команд
 Ничего не потеряно — всё перемещено в правильные места

## Проверка работоспособности

```bash
# 1. Проверить, что бенчмарки на месте
ls benchmarks/compiled/*.bc | wc -l
# Должно быть: 19

# 2. Проверить, что скрипты находят бенчмарки
python3 src/run_experiment.py --help

# 3. Проверить, что эксперименты на месте
ls experiments/exp1_fixed_length/raw_results.json
ls experiments/exp2_variable_length/raw_results_variable.json
```
