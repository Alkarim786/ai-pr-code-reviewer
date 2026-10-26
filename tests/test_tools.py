import pytest

from reviewer.diff import parse_diff
from reviewer.sources import DictSource, LocalSource, SourceError, safe_relpath
from reviewer.tools import ToolBox


@pytest.fixture
def box(sample_diff):
    src = DictSource({"app/x.py": "import os\nTODO = 1\nsecret = 2\n", "b.py": "TODO = 2\n"})
    return ToolBox(src, parse_diff(sample_diff), [])


def test_read_file_with_line_numbers(box):
    out = box.execute("read_file", {"path": "app/x.py", "start_line": 2, "end_line": 3})
    assert out.splitlines() == ["    2 TODO = 1", "    3 secret = 2"]


@pytest.mark.parametrize("bad", ["../etc/passwd", "/etc/passwd", "C:\\Windows\\win.ini", "a/../../x"])
def test_path_traversal_rejected(box, bad):
    assert box.execute("read_file", {"path": bad}).startswith("error:")


def test_symlink_escape_blocked(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    root = tmp_path / "repo"
    root.mkdir()
    try:
        (root / "link.txt").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not permitted on this platform")
    with pytest.raises(SourceError):
        LocalSource(root).read("link.txt")


def test_search_repo(box):
    out = box.execute("search_repo", {"pattern": r"TODO\s*="})
    assert "app/x.py:2:TODO = 1" in out and "b.py:1:TODO = 2" in out


def test_search_repo_bad_regex_and_long_pattern(box):
    assert box.execute("search_repo", {"pattern": "("}).startswith("error:")
    assert box.execute("search_repo", {"pattern": "a" * 500}).startswith("error:")


def test_unknown_tool_and_bad_args(box):
    assert "unknown tool" in box.execute("rm_rf", {})
    assert box.execute("read_file", {"nope": 1}).startswith("error:")


def test_diff_hunk_only_for_changed_files(box):
    assert "import sys" in box.execute("get_diff_hunk", {"file": "app/x.py"})
    assert "not changed" in box.execute("get_diff_hunk", {"file": "b.py"})


def test_output_truncated():
    src = DictSource({"big.py": "x\n" * 20000})
    out = ToolBox(src, [], []).execute("read_file", {"path": "big.py", "end_line": 20000})
    assert out.endswith("(truncated)")


def test_safe_relpath_normalises():
    assert safe_relpath("./a//b/./c.py") == "a/b/c.py"
