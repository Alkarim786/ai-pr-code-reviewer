"""Unified-diff parser with hunk -> new-file line mapping.

GitHub only accepts inline review comments on lines that appear in the diff
(added or context lines, RIGHT side). `FileDiff.visible_lines` is exactly that set,
which is what the aggregator uses to throw away hallucinated locations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class DiffLine:
    kind: str  # "+", "-" or " "
    old_no: int | None
    new_no: int | None
    text: str


@dataclass
class Hunk:
    old_start: int
    new_start: int
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class FileDiff:
    path: str
    hunks: list[Hunk] = field(default_factory=list)
    is_new: bool = False

    @property
    def added_lines(self) -> set[int]:
        return {ln.new_no for h in self.hunks for ln in h.lines if ln.kind == "+" and ln.new_no}

    @property
    def visible_lines(self) -> set[int]:
        return {ln.new_no for h in self.hunks for ln in h.lines if ln.new_no is not None}

    def annotated(self, max_lines: int = 400) -> str:
        """Diff rendered with new-file line numbers so the model can cite them exactly."""
        out: list[str] = []
        for h in self.hunks:
            out.append(f"@@ new line {h.new_start} @@")
            for ln in h.lines:
                no = f"{ln.new_no:>5}" if ln.new_no is not None else "     "
                out.append(f"{no} {ln.kind} {ln.text}")
                if len(out) >= max_lines:
                    out.append("... (truncated)")
                    return "\n".join(out)
        return "\n".join(out)


def parse_diff(text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    cur: FileDiff | None = None
    hunk: Hunk | None = None
    old_no = new_no = 0
    pending_old: str | None = None
    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            cur, hunk, pending_old = None, None, None
            continue
        if hunk is None and raw.startswith("--- "):
            pending_old = raw[4:].strip()
            continue
        if hunk is None and raw.startswith("+++ "):
            target = raw[4:].strip().split("\t")[0]
            if target == "/dev/null":  # deleted file: nothing to comment on
                cur = None
                continue
            path = target[2:] if target.startswith("b/") else target
            cur = FileDiff(path=path, is_new=pending_old == "/dev/null")
            files.append(cur)
            continue
        m = _HUNK.match(raw)
        if m and cur is not None:
            old_no, new_no = int(m.group(1)), int(m.group(3))
            hunk = Hunk(old_start=old_no, new_start=new_no)
            cur.hunks.append(hunk)
            continue
        if hunk is None or cur is None or raw.startswith("\\"):
            continue
        if raw.startswith("+"):
            hunk.lines.append(DiffLine("+", None, new_no, raw[1:]))
            new_no += 1
        elif raw.startswith("-"):
            hunk.lines.append(DiffLine("-", old_no, None, raw[1:]))
            old_no += 1
        else:
            hunk.lines.append(DiffLine(" ", old_no, new_no, raw[1:]))
            old_no += 1
            new_no += 1
    return files
