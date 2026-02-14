#!/usr/bin/env bash
set -euo pipefail

python3 -m py_compile src/rex/main.py
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -q

echo "smoke ok"
