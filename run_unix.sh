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
.venv/bin/python scripts/setup_support_inbox.py
if [[ "$regenerate_data" == 1 ]]; then
    .venv/bin/python scripts/generate_synthetic_data.py
fi
.venv/bin/python scripts/train_classifier.py
.venv/bin/python scripts/evaluate.py
.venv/bin/python -m pytest
if [[ "$skip_launch" == 0 ]]; then
    mail_pid=""
    worker_pid=""
    cleanup() {
        [[ -z "$mail_pid" ]] || kill "$mail_pid" 2>/dev/null || true
        [[ -z "$worker_pid" ]] || kill "$worker_pid" 2>/dev/null || true
    }
    trap cleanup EXIT INT TERM
    if .venv/bin/python -c 'import socket; s=socket.socket(); s.settimeout(1); exit(s.connect_ex(("127.0.0.1",1025)))'; then
        :
    elif .venv/bin/python -c 'from pathlib import Path; import tomllib; p=Path(".streamlit/secrets.toml"); c=tomllib.loads(p.read_text()) if p.exists() else {}; exit(not(c.get("smtp",{}).get("host") in ("127.0.0.1","localhost") and c.get("smtp",{}).get("port")==1025))'; then
        .venv/bin/python scripts/demo_mail_server.py &
        mail_pid=$!
    fi
    .venv/bin/python scripts/send_pending_mail.py --watch &
    worker_pid=$!
    .venv/bin/python -m streamlit run app.py --server.address=127.0.0.1
fi
