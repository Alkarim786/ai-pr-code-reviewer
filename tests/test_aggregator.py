from reviewer.aggregator import aggregate, dedupe, format_comment, validate_locations
from reviewer.diff import parse_diff
from reviewer.schemas import Category, Finding, Severity


def F(line, sev=Severity.medium, cat=Category.bug, source="llm", file="app/x.py", **kw):
    return Finding(file=file, line=line, severity=sev, category=cat, message="m", source=source, **kw)


def test_out_of_diff_locations_dropped(sample_diff):
    diffs = parse_diff(sample_diff)
    kept, dropped = validate_locations([F(2), F(99), F(1, file="nope.py")], diffs)
    assert [f.line for f in kept] == [2] and dropped == 2


def test_dedupe_merges_nearby_same_category():
    merged, n = dedupe([F(10, source="static"), F(11, source="llm", suggestion="fix it")])
    assert n == 1 and len(merged) == 1
    m = merged[0]
    assert m.source == "static+llm" and m.suggestion == "fix it"


def test_dedupe_keeps_different_category_or_far_lines():
    merged, n = dedupe([F(10), F(10, cat=Category.security), F(20)])
    assert n == 0 and len(merged) == 3


def test_dedupe_takes_max_severity():
    merged, _ = dedupe([F(5, Severity.low, source="static"), F(5, Severity.high)])
    assert merged[0].severity == Severity.high


def test_ranking_and_cap(sample_diff):
    diffs = parse_diff(sample_diff)
    fs = [
        F(1, Severity.low, Category.bug),
        F(2, Severity.critical, Category.security),
        F(5, Severity.high, Category.performance),
        F(6, Severity.medium, Category.style),
    ]
    res = aggregate(fs, diffs, max_comments=2)
    assert [f.severity for f in res.findings] == [Severity.critical, Severity.high]
    assert res.dropped_over_cap == 2


def test_static_llm_agreement_outranks_same_severity(sample_diff):
    diffs = parse_diff(sample_diff)
    fs = [
        F(1, Severity.high, source="llm"),
        F(5, Severity.high, source="static"),
        F(5, Severity.high, source="llm"),
    ]
    res = aggregate(fs, diffs)
    assert res.findings[0].line == 5 and res.findings[0].source == "static+llm"


def test_format_comment_includes_suggestion():
    text = format_comment(F(1, Severity.high, suggestion="use X"))
    assert "HIGH" in text and "Suggestion:** use X" in text
