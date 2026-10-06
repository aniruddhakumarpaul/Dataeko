#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONUTF8=1
skip_launch=0
regenerate_data=0
skip_install=0
for arg in "$@"; do
    case "$arg" in
        --skip-launch) skip_launch=1 ;;
        --regenerate-data) regenerate_data=1 ;;
        --skip-install) skip_install=1 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
fi
if [[ "$skip_install" == 0 ]]; then
    .venv/bin/python -m pip install -r requirements-lock.txt
fi
.venv/bin/python -m pip check
if [[ "$regenerate_data" == 1 ]]; then
    .venv/bin/python scripts/generate_synthetic_data.py
fi
.venv/bin/python scripts/train_classifier.py
.venv/bin/python scripts/evaluate.py
.venv/bin/python -m pytest
if [[ "$skip_launch" == 0 ]]; then
    exec .venv/bin/python -m streamlit run app.py --server.address=127.0.0.1
fi
