# Engineering decisions

## 2026-10-06: Import and local development setup

The connected repository contained only a placeholder README. Imported the supplied
`support-ticket-triage-assistant.zip` into the repository root, preserving its Git
history and remote. The archive did not include the original exercise brief or real
Dataeko data; claims about brief compliance remain unverified.

Use Python 3.12 with a project-local `.venv`. Keep hosting dependencies in
`requirements.txt`, development dependencies in `requirements-dev.txt`, and the
tested lightweight environment in `requirements-lock.txt`. Optional sentence-transformer
and Ollama enhancements are separate from this baseline.

The original launchers called pytest without installing it, depended on shell
activation, and regenerated ticket data on every launch. Windows native process
failures were not explicitly checked. Launchers now use the environment's Python
directly, install the locked development environment, check each command, and
preserve existing fixtures by default. Explicit regeneration remains available.
`-SkipLaunch` / `--skip-launch` prepares and verifies the environment without a server;
`-SkipInstall` / `--skip-install` reuses installed dependencies.

CI uses the same Python version and lock file, evaluates retrieval, and tests the
committed fixtures rather than replacing them. No GitHub publication or deployment
is part of this environment-setup change.

## Follow-up issues observed during verification

- In the cafeteria no-answer example, classification reports human review is not
  required while the abstention message recommends manual handling. Consider a
  pipeline-level review decision that incorporates response abstention.
- Streamlit 1.65.0 reports deprecated `use_container_width` calls. Replace them with
  supported width arguments when updating the UI, with a matching runtime version
  requirement.
- Training and first-boot app fitting use different sample sets (training split
  versus all cleaned rows). Make model provenance explicit before claiming demo
  behavior and evaluation cover the same fitted model.
