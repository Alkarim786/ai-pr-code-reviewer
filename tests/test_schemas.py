import pytest
from pydantic import ValidationError

from reviewer.schemas import Finding


def test_valid_finding():
    f = Finding(file="a.py", line=3, severity="high", category="bug", message="x")
    assert f.source == "llm"


@pytest.mark.parametrize(
    "patch",
    [{"line": 0}, {"severity": "urgent"}, {"category": "vibes"}, {"message": ""}, {"file": ""}],
)
def test_invalid_findings_rejected(patch):
    base = {"file": "a.py", "line": 3, "severity": "high", "category": "bug", "message": "x"}
    with pytest.raises(ValidationError):
        Finding(**{**base, **patch})
