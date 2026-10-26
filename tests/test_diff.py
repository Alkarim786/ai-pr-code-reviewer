from reviewer.diff import parse_diff


def test_parses_files_and_skips_deleted(sample_diff):
    files = parse_diff(sample_diff)
    assert [f.path for f in files] == ["app/x.py", "new.py"]
    assert files[1].is_new and not files[0].is_new


def test_line_mapping(sample_diff):
    x, new = parse_diff(sample_diff)
    assert x.added_lines == {2, 5}
    assert x.visible_lines == {1, 2, 3, 4, 5, 6}
    assert new.added_lines == {1, 2}


def test_annotated_has_new_line_numbers(sample_diff):
    text = parse_diff(sample_diff)[0].annotated()
    assert "    2 + import sys" in text
    assert "@@ new line 1 @@" in text


def test_removed_lines_have_no_new_number():
    diff = "--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,1 @@\n-gone\n keep\n"
    f = parse_diff(diff)[0]
    assert f.visible_lines == {1}


def test_empty_and_garbage():
    assert parse_diff("") == []
    assert parse_diff("hello\nworld") == []
