# Local development environment

## Tested baseline

- Python: 3.12.10, in `.venv` under the repository root.
- Streamlit: 1.65.0; scikit-learn: 1.9.1; NumPy: 2.5.3; pandas: 2.3.3.
- `extra-streamlit-components`: 0.1.81 for refresh-persistent support sessions.
- pytest: 9.1.1.
- Retrieval: BM25 plus TF-IDF, without a model download.
- Generation: deterministic extractive fallback, without a model API.
- Exact baseline dependencies: `requirements-lock.txt`.

The environment is isolated from globally installed Python packages, including any
global sentence-transformers installation. No API key is required for the baseline.
`.env.example` documents optional Ollama variables; the app reads process environment
variables, and does not automatically load a `.env` file.

## Windows

Run from the repository, or invoke the script by its full path:

```powershell
.\run_windows.ps1 -SkipLaunch
```

This installs dependencies, checks their compatibility, trains on the existing
CSV, evaluates retrieval, and runs pytest. Omit `-SkipLaunch` to launch Streamlit.
Use `-SkipInstall` after setup to avoid reinstalling dependencies. Activation is
unnecessary; the launcher always uses `.venv\Scripts\python.exe`.

For individual development commands:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts\train_classifier.py
.\.venv\Scripts\python.exe scripts\evaluate.py
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address=127.0.0.1
```

Launchers bind the development server to loopback. Native process failures stop
the Windows launcher immediately. Shell location is restored on exit.

## macOS/Linux and CI

```bash
bash run_unix.sh --skip-launch
.venv/bin/python -m streamlit run app.py --server.address=127.0.0.1
```

The Unix launcher uses the same lock file and supports `--skip-install`.
GitHub Actions targets Python 3.12 and runs dependency checks, training,
retrieval evaluation, and pytest. Local execution is verified on Windows;
the remote CI result is pending a future push.

## Preserve data and refresh models

The ZIP includes the synthetic fixtures. Routine setup does not rewrite them.
Use `-RegenerateData` / `--regenerate-data` only to deliberately restore synthetic
tickets and the safety challenge file; that generator does not regenerate the KB
or retrieval evaluation file. Do not use regeneration after replacing these
fixtures with real data.

Model weights are ignored by Git. Rerun training after changing data or scikit-learn.
Restart Streamlit after retraining so its cached pipeline reloads. Training writes
a model fitted on the training split; on first boot without weights, the app fits
on all cleaned rows. That existing difference should be considered in future
evaluation improvements.

## Optional enhancements

Install `requirements-full.txt` only when working on sentence-transformer retrieval.
It is outside the locked lightweight baseline and may download model weights on
first use. For Ollama, install/run it separately, pull the desired open-weight model,
and set `USE_OLLAMA` and `OLLAMA_MODEL` as documented in the README. Neither enhanced
path was validated as part of baseline environment setup.

## Updating dependencies

Install deliberate upgrades using `requirements-dev.txt`, rerun training, retrieval
evaluation, and tests, and refresh `requirements-lock.txt` from the isolated
environment only after verification. Record version and metric changes in this doc
and `docs/EVALUATION.md`.

## Verification on 2026-10-06

- `run_windows.ps1 -SkipLaunch -SkipInstall`: training, evaluation, and 6 tests passed.
- Full `run_windows.ps1 -SkipLaunch` invoked from outside the repo: install and all
  checks passed, confirming script-relative paths and no activation dependency.
- `python -m pip check`: no broken requirements.
- PowerShell parser and Python `compileall`: passed.
- Browser check at `http://127.0.0.1:8501`: app renders; duplicate-charge ticket routes
  to Billing and cites KB-004; compromised-account ticket routes to Security/Fraud
  with human review; the cafeteria question abstains. No browser errors were reported.
- Streamlit server emits deprecation notices for existing `use_container_width`
  calls. This is a follow-up compatibility cleanup, not a startup failure.

The model metrics reproduce the bundled rounded benchmark: macro F1 0.8793,
weighted F1 0.946, security challenge safe handling 15/15, zero silent security
to general misroutes, retrieval Hit@3 1.0, and MRR@3 0.9667. Synthetic benchmarks
are not evidence of production accuracy.
