"""Read-only tools exposed to the agents.

Security posture: PR content is attacker-controlled, so no tool can write, execute or
touch the network. The worst a prompt-injected agent can do is read files in the repo
(which it already has the diff of) or emit a bad finding, and bad findings are
filtered by the aggregator.
"""

from __future__ import annotations

import re

from .diff import FileDiff
from .schemas import Finding
from .sources import FileSource, SourceError, safe_relpath

MAX_TOOL_OUTPUT = 8000

TOOL_DEFS = [
    {
        "name": "read_file",
        "description": "Read a file from the repository (head of the PR). Optionally a line range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_repo",
        "description": "Regex search over repository files. Returns path:line:text, max 50 hits.",
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
            "required": ["pattern"],
        },
    },
    {
        "name": "get_static_findings",
        "description": "Static-analysis (ruff/bandit) findings on the PR, optionally for one file.",
        "input_schema": {"type": "object", "properties": {"file": {"type": "string"}}},
    },
    {
        "name": "get_diff_hunk",
        "description": "The diff of one changed file, annotated with new-file line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {"file": {"type": "string"}},
            "required": ["file"],
        },
    },
]

SUBMIT_TOOL = {
    "name": "submit_findings",
    "description": (
        "Submit your final review findings. Call exactly once when done. "
        "Every finding must point at a line number that appears in the annotated diff."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string"},
                        "line": {"type": "integer", "minimum": 1},
                        "severity": {"enum": ["critical", "high", "medium", "low", "info"]},
                        "category": {"enum": ["bug", "security", "performance", "style"]},
                        "message": {"type": "string"},
                        "suggestion": {"type": "string"},
                    },
                    "required": ["file", "line", "severity", "category", "message"],
                },
            }
        },
        "required": ["findings"],
    },
}


class ToolBox:
    definitions = TOOL_DEFS

    def __init__(
        self,
        source: FileSource,
        diffs: list[FileDiff],
        static_findings: list[Finding],
        search_paths: list[str] | None = None,
    ):
        self.source = source
        self.diffs = {d.path: d for d in diffs}
        self.static = static_findings
        self.search_paths = search_paths

    def execute(self, name: str, args: dict) -> str:
        """Run a tool. Errors are returned as text so the model can recover."""
        try:
            handler = getattr(self, f"_t_{name}", None)
            if handler is None:
                return f"error: unknown tool {name!r}"
            out = handler(**args)
        except SourceError as e:
            return f"error: {e}"
        except (TypeError, re.error) as e:
            return f"error: bad arguments: {e}"
        return out if len(out) <= MAX_TOOL_OUTPUT else out[:MAX_TOOL_OUTPUT] + "\n... (truncated)"

    def _t_read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> str:
        lines = self.source.read(path).splitlines()
        end = end_line if end_line else start_line + 399
        end = min(end, len(lines))
        return "\n".join(f"{i:>5} {lines[i - 1]}" for i in range(start_line, end + 1))

    def _t_search_repo(self, pattern: str) -> str:
        if len(pattern) > 200:
            raise SourceError("pattern too long")
        rx = re.compile(pattern)
        paths = self.search_paths if self.search_paths is not None else self.source.list_files()
        hits: list[str] = []
        for p in paths:
            try:
                text = self.source.read(p)
            except SourceError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{p}:{i}:{line.strip()[:160]}")
                    if len(hits) >= 50:
                        return "\n".join(hits)
        return "\n".join(hits) or "no matches"

    def _t_get_static_findings(self, file: str | None = None) -> str:
        rel = safe_relpath(file) if file else None
        sel = [f for f in self.static if rel is None or f.file == rel]
        if not sel:
            return "no static findings"
        return "\n".join(
            f"{f.file}:{f.line} {f.severity.value} {f.category.value} {f.message}" for f in sel
        )

    def _t_get_diff_hunk(self, file: str) -> str:
        d = self.diffs.get(safe_relpath(file))
        if d is None:
            raise SourceError(f"{file} is not changed in this PR")
        return d.annotated()
