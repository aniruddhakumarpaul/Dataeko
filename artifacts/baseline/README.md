# Recorded pre-run metrics

These files are byte-for-byte copies of the metric artifacts present before the
pre-upgrade baseline run. They are historical recorded results, not results from
the new reproduction:

- `recorded_metrics.json` was copied from `artifacts/metrics.json`.
- `recorded_retrieval_metrics.json` was copied from `artifacts/retrieval_metrics.json`.

The baseline reproduction writes fresh results to the original artifact paths and
compares them with these preserved copies. The generated manifest records the
input hashes, environment versions, evaluation outputs, and test result. It does
not include credentials, local paths, or model weights.
