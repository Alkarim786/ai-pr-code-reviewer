"""The eval set itself must be self-consistent, or its numbers mean nothing."""

from eval.cases import CASES
from eval.run_eval import match
from reviewer.diff import parse_diff
from reviewer.schemas import Finding


def test_every_label_is_on_an_added_line_and_markers_stripped():
    for case in CASES:
        diff, files, expected = case.build()
        fd = parse_diff(diff)[0]
        for e in expected:
            assert e["line"] in fd.added_lines, case.name
        assert "#@:" not in files[case.path]
        assert "#@:" not in diff


def test_scripted_markers_resolve():
    for case in CASES:
        _, _, expected = case.build()
        for s in case.script:
            if s.marker is not None and s.line is None:
                assert s.marker < len(expected), case.name


def test_set_shape():
    labelled = [c for c in CASES if c.build()[2]]
    assert len(CASES) == 28 and len(labelled) == 18
    assert sum(len(c.build()[2]) for c in CASES) == 19


def test_matching_is_one_to_one_with_tolerance():
    exp = [{"file": "a.py", "line": 10, "category": "bug"}]

    def f(line, cat="bug"):
        return Finding(file="a.py", line=line, severity="low", category=cat, message="m")

    tps, fps, fns = match([f(12), f(10)], exp)
    assert len(tps) == 1 and len(fps) == 1 and not fns
    tps, fps, fns = match([f(13), f(10, "security")], exp)
    assert not tps and len(fps) == 2 and len(fns) == 1
