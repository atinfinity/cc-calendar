import pytest

from cc_calendar.gitinfo import web_url


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
