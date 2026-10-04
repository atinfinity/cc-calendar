from pathlib import Path

from cc_calendar.cli import claude_dirs


def test_default_dir_is_named_local(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    assert [(d.name, d.path) for d in claude_dirs(["~/.claude"])] == [
        ("local", (home / ".claude").resolve())
    ]


def test_names(tmp_path):
    for p in ["sync/laptop/.claude", "sync/desktop/.claude", "work-config", "other/.claude"]:
        (tmp_path / p).mkdir(parents=True)
    dirs = claude_dirs(
        [
            str(tmp_path / "sync/laptop/.claude"),
            f"desk={tmp_path / 'sync/desktop/.claude'}",
            str(tmp_path / "work-config"),
            f"laptop={tmp_path / 'other/.claude'}",
        ]
    )
    assert [d.name for d in dirs] == ["laptop", "desk", "work-config", "laptop-2"]
    assert dirs[1].path == (tmp_path / "sync/desktop/.claude").resolve()


def test_equals_in_path_is_not_a_name(tmp_path):
    (tmp_path / "a=b").mkdir()
    (d,) = claude_dirs([str(tmp_path / "a=b")])
    assert d.name == "a=b" and d.path == (tmp_path / "a=b").resolve()


def test_skips_missing_and_repeated(tmp_path, capsys):
    (tmp_path / "one").mkdir()
    dirs = claude_dirs(
        [str(tmp_path / "one"), str(tmp_path / "missing"), f"again={tmp_path / 'one'}"]
    )
    assert [d.name for d in dirs] == ["one"]
    err = capsys.readouterr().err
    assert "missing" in err and "given twice" in err


def test_nothing_left(tmp_path):
    assert claude_dirs([str(Path(tmp_path) / "missing")]) == []
