# Baseline Report: Starting State

- Branch: `stages-2-7`
- Base commit: `c56b5a2` (main)
- Date: 2026-10-25

## 1. Pytest Baseline
```
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/aditya/Desktop/Orchestration engine
configfile: pyproject.toml
testpaths: tests
collecting ... collected 64 items

tests/test_executor.py ..................                                [ 28%]
tests/test_loader.py ..                                                  [ 31%]
tests/test_loader_entrypoint.py .                                        [ 32%]
tests/test_models.py ...                                                 [ 37%]
tests/test_persistence.py .                                              [ 39%]
tests/test_readiness.py .........                                        [ 53%]
tests/test_runner.py ..........                                          [ 68%]
tests/test_scheduler.py ....                                             [ 75%]
tests/test_status.py ...                                                 [ 79%]
tests/test_transitions.py ........                                       [ 92%]
tests/test_validation.py .....                                           [100%]

============================== 64 passed in 3.08s ==============================
```

## 2. Ruff Baseline (16 errors)
```
Found 16 errors.
[*] 13 fixable with the `--fix` option.
```

## 3. Mypy Baseline (45 errors across 11 files)
```
Found 45 errors in 11 files (checked 23 source files)
```

## 4. Build Baseline
```
Building source distribution (uv build backend)...
Building wheel from source distribution (uv build backend)...
Successfully built dist/orchestration_engine-0.1.0.tar.gz
Successfully built dist/orchestration_engine-0.1.0-py3-none-any.whl
```
