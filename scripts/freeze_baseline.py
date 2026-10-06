"""Write an auditable manifest for the unchanged pre-upgrade baseline."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("artifacts/baseline_manifest.json")
DATA_FILES = (
    "data/tickets.csv",
    "data/safety_eval.csv",
    "data/retrieval_eval.csv",
)
TRACKED_INPUTS = (
    "src/triage/classifier.py",
    "src/triage/retrieval.py",
    "src/triage/generation.py",
    "src/triage/constants.py",
    "scripts/train_classifier.py",
    "scripts/evaluate.py",
    "scripts/generate_synthetic_data.py",
)
HISTORICAL_METRICS = {
    "classifier": "artifacts/baseline/recorded_metrics.json",
    "retrieval": "artifacts/baseline/recorded_retrieval_metrics.json",
}
REPRODUCED_METRICS = {
    "classifier": "artifacts/metrics.json",
    "retrieval": "artifacts/retrieval_metrics.json",
}
RELEVANT_PACKAGES = (
    "extra-streamlit-components",
    "numpy",
    "pandas",
    "pytest",
    "requests",
    "scikit-learn",
    "streamlit",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_hashes(root: Path, paths: list[Path]) -> dict[str, str]:
    result = {}
    for path in sorted(paths, key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        result[relative] = sha256_file(path)
    return result


def read_optional_hashes(root: Path, relative_paths: list[str]) -> dict[str, str | None]:
    return {
        relative: sha256_file(root / relative) if (root / relative).is_file() else None
        for relative in relative_paths
    }


def dataset_summary(root: Path) -> dict:
    ticket_path = root / "data/tickets.csv"
    summary = {"row_count": None, "class_distribution": {}}
    if ticket_path.is_file():
        with ticket_path.open(encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source))
        summary["row_count"] = len(rows)
        for row in rows:
            label = row.get("label", "")
            summary["class_distribution"][label] = summary["class_distribution"].get(label, 0) + 1
    summary["class_distribution"] = dict(sorted(summary["class_distribution"].items()))
    for key, relative in (("safety_eval_count", DATA_FILES[1]), ("retrieval_eval_count", DATA_FILES[2])):
        path = root / relative
        if path.is_file():
            with path.open(encoding="utf-8", newline="") as source:
                summary[key] = sum(1 for _ in csv.DictReader(source))
        else:
            summary[key] = None
    return summary


def read_junit_summary(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    totals = {"tests": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        tests = int(suite.attrib.get("tests", 0))
        failures = int(suite.attrib.get("failures", 0))
        errors = int(suite.attrib.get("errors", 0))
        skipped = int(suite.attrib.get("skipped", 0))
        totals["tests"] += tests
        totals["failed"] += failures
        totals["errors"] += errors
        totals["skipped"] += skipped
    totals["passed"] = totals["tests"] - totals["failed"] - totals["errors"] - totals["skipped"]
    return totals


def git_value(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def create_manifest(root: Path, pytest_result: dict[str, int], generated_at: str | None = None) -> dict:
    kb_files = sorted((root / "kb").glob("*.md"), key=lambda path: path.name)
    kb_hashes = file_hashes(root, kb_files)
    kb_digest = hashlib.sha256()
    for relative, digest in kb_hashes.items():
        kb_digest.update(f"{relative}\0{digest}\n".encode("utf-8"))

    requirements_files = sorted(root.glob("requirements*.txt"), key=lambda path: path.name)
    requirement_hashes = file_hashes(root, requirements_files)
    input_paths = [root / relative for relative in (*DATA_FILES, *TRACKED_INPUTS) if (root / relative).is_file()]
    input_hashes = file_hashes(root, input_paths)
    input_hashes.update(read_optional_hashes(root, ["artifacts/metrics.json", "artifacts/retrieval_metrics.json"]))

    class_weights: dict[str, float] = {}
    thresholds: dict[str, float] = {}
    try:
        sys_path = str(root / "src")
        import sys

        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)
        from triage.constants import (  # pylint: disable=import-outside-toplevel
            COST_SENSITIVE_CLASS_WEIGHTS,
            LOW_CONFIDENCE_THRESHOLD,
            RETRIEVAL_MIN_RELEVANCE,
            SECURITY_FORCE_THRESHOLD,
            SECURITY_REVIEW_THRESHOLD,
        )

        class_weights = dict(COST_SENSITIVE_CLASS_WEIGHTS)
        thresholds = {
            "low_confidence": LOW_CONFIDENCE_THRESHOLD,
            "security_force": SECURITY_FORCE_THRESHOLD,
            "security_review": SECURITY_REVIEW_THRESHOLD,
            "legacy_retrieval_min_relevance": RETRIEVAL_MIN_RELEVANCE,
        }
    except ImportError:
        pass

    reproduced_retrieval = root / REPRODUCED_METRICS["retrieval"]
    retrieval_backend = None
    if reproduced_retrieval.is_file():
        retrieval_backend = json.loads(reproduced_retrieval.read_text(encoding="utf-8")).get("retrieval_backend")

    packages = {}
    installed = {dist.metadata["Name"].lower().replace("_", "-"): dist.version
                 for dist in importlib.metadata.distributions() if dist.metadata.get("Name")}
    for name in RELEVANT_PACKAGES:
        packages[name] = installed.get(name.lower())

    status = git_value(root, "status", "--porcelain")
    manifest = {
        "schema_version": 1,
        "generated_at_utc": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_value(root, "rev-parse", "HEAD"),
        "git_branch": git_value(root, "branch", "--show-current"),
        "dirty_worktree": bool(status),
        "python_version": platform.python_version(),
        "dependency_versions": packages,
        "dependency_file_sha256": requirement_hashes,
        "random_seeds": {"training_split": 42, "synthetic_data_generator": 42, "retrieval_evaluation": None},
        "input_file_sha256": input_hashes,
        "recorded_metric_sha256": read_optional_hashes(root, list(HISTORICAL_METRICS.values())),
        "dataset": dataset_summary(root),
        "kb": {"article_count": len(kb_hashes), "file_sha256": kb_hashes, "corpus_sha256": kb_digest.hexdigest()},
        "classifier_implementation": "triage.classifier.build_classifier: word/character TF-IDF + LogisticRegression",
        "class_weights": class_weights,
        "thresholds": thresholds,
        "reproduced_retrieval_backend": retrieval_backend,
        "generator_default": {
            "enabled_by_default": os.getenv("USE_OLLAMA", "0").lower() in {"1", "true", "yes"},
            "ollama_model_default": os.getenv("OLLAMA_MODEL", "qwen3:4b"),
            "mode": "validated Ollama claims when enabled; extractive fallback otherwise",
        },
        "recorded_historical_metrics": HISTORICAL_METRICS,
        "reproduced_metrics": REPRODUCED_METRICS,
        "pytest": pytest_result,
        "reproduction_commands": [
            ".\\.venv\\Scripts\\python.exe -m pip check",
            ".\\.venv\\Scripts\\python.exe scripts\\train_classifier.py",
            ".\\.venv\\Scripts\\python.exe scripts\\evaluate.py",
            ".\\.venv\\Scripts\\python.exe -m pytest --junitxml=<temporary-junit-report>",
        ],
    }
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pytest-junit", required=True, type=Path,
                        help="JUnit XML written by the full pytest run; its path is not stored in the manifest.")
    parser.add_argument("--output", default=str(MANIFEST_PATH), type=Path)
    args = parser.parse_args()
    result = read_junit_summary(args.pytest_junit)
    manifest = create_manifest(ROOT, result)
    output = (ROOT / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {args.output.as_posix()}")


if __name__ == "__main__":
    main()
