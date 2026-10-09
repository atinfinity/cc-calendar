"""Whether a newer cc-calendar is on PyPI. The request sends nothing but the installed version
in the User-Agent; turn it off with --no-update-check or CC_CALENDAR_NO_UPDATE_CHECK=1."""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request

from . import __version__

log = logging.getLogger(__name__)
PYPI_URL = "https://pypi.org/pypi/cc-calendar/json"
UPDATE_DOCS = "https://atinfinity.github.io/cc-calendar/getting-started/#update"
CHECK_EVERY_S = 24 * 60 * 60
TIMEOUT_S = 10
ENV_OFF = "CC_CALENDAR_NO_UPDATE_CHECK"


def disabled_by_env() -> bool:
    return os.environ.get(ENV_OFF, "").strip().lower() not in ("", "0", "false", "no")


def release(version: str) -> tuple[int, ...] | None:
    """`1.2.3` as (1, 2, 3); None for pre-releases, dev builds and anything else."""
    if not re.fullmatch(r"\d+(\.\d+)*", version):
        return None
    return tuple(int(p) for p in version.split("."))


def newer(latest: str | None, current: str | None = None) -> str | None:
    """`latest` when it is a later release than `current` (the running version), else None."""
    have, got = release(current or __version__), release(latest or "")
    if have is None or got is None:
        return None
    width = max(len(have), len(got))
    pad = lambda v: v + (0,) * (width - len(v))  # noqa: E731
    return latest if pad(got) > pad(have) else None


def fetch_latest() -> str | None:
    """The latest release on PyPI, or None when PyPI cannot be reached."""
    req = urllib.request.Request(
        PYPI_URL,
        headers={"Accept": "application/json", "User-Agent": f"cc-calendar/{__version__}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:
            version = json.load(res)["info"]["version"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        log.info("update check failed: %s", e)
        return None
    return version if isinstance(version, str) else None
