"""Read-only file sources the agents' tools run against."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
MAX_FILE_BYTES = 512_000


class SourceError(Exception):
    pass


class FileSource(Protocol):
    def read(self, path: str) -> str: ...
    def list_files(self) -> list[str]: ...


def safe_relpath(path: str) -> str:
    """Normalise a model-supplied path. Rejects absolute paths and `..` traversal."""
    norm = path.replace("\\", "/").strip()
    if not norm or norm.startswith("/") or re.match(r"^[A-Za-z]:", norm):
        raise SourceError("absolute paths are not allowed")
    parts = [p for p in norm.split("/") if p not in ("", ".")]
    if ".." in parts:
        raise SourceError("path traversal is not allowed")
    return "/".join(parts)


class LocalSource:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def read(self, path: str) -> str:
        rel = safe_relpath(path)
        full = (self.root / rel).resolve()
        if self.root not in full.parents:  # also catches symlink escapes
            raise SourceError("path escapes the repository")
        if not full.is_file():
            raise SourceError(f"file not found: {rel}")
        if full.stat().st_size > MAX_FILE_BYTES:
            raise SourceError("file too large")
        return full.read_text(encoding="utf-8", errors="replace")

    def list_files(self) -> list[str]:
        out: list[str] = []
        for p in self.root.rglob("*"):
            if p.is_file() and not (set(p.relative_to(self.root).parts) & SKIP_DIRS):
                out.append(p.relative_to(self.root).as_posix())
        return sorted(out)


class DictSource:
    """In-memory source (tests, and webhook mode where only changed files are fetched)."""

    def __init__(self, files: dict[str, str]):
        self.files = files

    def read(self, path: str) -> str:
        rel = safe_relpath(path)
        if rel not in self.files:
            raise SourceError(f"file not found: {rel}")
        return self.files[rel]

    def list_files(self) -> list[str]:
        return sorted(self.files)
