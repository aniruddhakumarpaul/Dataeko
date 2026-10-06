# Repository instructions

Use `docs/` as the first source of truth. Read the smallest relevant doc, then use `rg` and exact file reads for code.

Priority:
1. `docs/architecture.md`
2. `docs/routing.md`
3. `docs/image_pipeline.md`
4. `docs/memory.md`
5. `docs/decisions.md`

- Prefer docs + code search over neural/vector retrieval.
- Use `.project_brain` only as fallback.
- Keep changes scoped and update the relevant doc when behavior changes.
- Verify with the narrowest useful test or syntax check.
- If context is missing, inspect code directly and record the decision in `docs/decisions.md`.
