from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class KBChunk:
    source_id: str
    title: str
    path: str
    text: str


def _parse_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def load_kb(kb_dir: str | Path) -> list[KBChunk]:
    kb_dir = Path(kb_dir)
    chunks: list[KBChunk] = []
    for index, path in enumerate(sorted(kb_dir.glob("*.md")), start=1):
        raw = path.read_text(encoding="utf-8")
        title = _parse_title(raw, path.stem.replace("-", " ").title())
        source_id = f"KB-{index:03d}"

        # Small help-center articles are kept as one chunk to preserve procedural context.
        body = re.sub(r"^#\s+.*$", "", raw, count=1, flags=re.MULTILINE).strip()
        body = re.sub(r"\n{3,}", "\n\n", body)
        chunks.append(
            KBChunk(
                source_id=source_id,
                title=title,
                path=str(path),
                text=body,
            )
        )
    return chunks
