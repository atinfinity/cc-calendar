import os
import subprocess

import pytest

from cc_calendar import gitinfo
from cc_calendar.gitinfo import resolve_commits, web_url


@pytest.mark.parametrize(
    ("remote", "url"),
    [
        ("git@github.com:acme/web.git", "https://github.com/acme/web"),
        ("ssh://git@github.com/acme/web.git", "https://github.com/acme/web"),
        ("https://github.com/acme/web.git\n", "https://github.com/acme/web"),
        (
            "https://user@gitlab.example.com/group/sub/repo",
            "https://gitlab.example.com/group/sub/repo",
        ),
        ("/srv/git/repo.git", None),
    ],
)
def test_web_url(remote, url):
    assert web_url(remote) == url


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(gitinfo, "_log_cache", {})
    env = dict(os.environ)
    for role in ("AUTHOR", "COMMITTER"):
        env[f"GIT_{role}_NAME"], env[f"GIT_{role}_EMAIL"] = "t", "t@example.com"
        env[f"GIT_{role}_DATE"] = "1700000000 +0000"

    def git(*args):
        cmd = ["git", "-C", str(tmp_path), *args]
        return subprocess.run(cmd, env=env, check=True, capture_output=True, text=True).stdout

    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "Add feature")
    return str(tmp_path), git("rev-parse", "HEAD").strip()


def test_resolve_commits_by_subject_and_sha(repo):
    cwd, sha = repo
    t = 1700000000_000
    commits = [
        # A heredoc message: the tool output has no SHA, so it is matched by subject and time.
        {"cwd": cwd, "sha": None, "subject": "Add feature", "ts": t + 60_000},
        # The same commit seen by its short SHA: a duplicate once resolved.
        {"cwd": cwd, "sha": sha[:7], "subject": None, "ts": t},
        # Same subject, but too far in time.
        {"cwd": cwd, "sha": None, "subject": "Add feature", "ts": t + 86400_000},
        {"cwd": cwd, "sha": None, "subject": "Other", "ts": t},
    ]
    out = [(c["sha"], c["subject"]) for c in resolve_commits(commits)]
    assert out == [(sha, "Add feature"), (None, "Add feature"), (None, "Other")]
