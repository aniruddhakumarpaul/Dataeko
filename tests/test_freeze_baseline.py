import hashlib
import json
from pathlib import Path

from scripts.freeze_baseline import create_manifest, dataset_summary, sha256_file


ROOT = Path(__file__).resolve().parents[1]


def test_sha256_is_stable_for_same_content(tmp_path):
    path = tmp_path / "input.bin"
    path.write_bytes(b"baseline\n")
    expected = hashlib.sha256(b"baseline\n").hexdigest()
    assert sha256_file(path) == expected
    assert sha256_file(path) == sha256_file(path)


def test_dataset_summary_reports_current_class_counts():
    summary = dataset_summary(ROOT)
    assert summary["row_count"] == 500
    assert sum(summary["class_distribution"].values()) == summary["row_count"]
    assert summary["safety_eval_count"] == 20
    assert summary["retrieval_eval_count"] == 15


def test_manifest_has_required_keys_and_contains_no_absolute_workspace_path():
    result = {"tests": 3, "passed": 3, "failed": 0, "errors": 0, "skipped": 0}
    manifest = create_manifest(ROOT, result, generated_at="2026-01-01T00:00:00+00:00")
    encoded = json.dumps(manifest)
    assert {
        "schema_version", "generated_at_utc", "git_commit", "git_branch", "dirty_worktree",
        "python_version", "dependency_file_sha256", "random_seeds", "input_file_sha256",
        "recorded_metric_sha256",
        "dataset", "kb", "classifier_implementation", "class_weights", "thresholds",
        "reproduced_retrieval_backend", "generator_default", "recorded_historical_metrics",
        "reproduced_metrics", "pytest", "reproduction_commands",
    } <= manifest.keys()
    assert str(ROOT) not in encoded
