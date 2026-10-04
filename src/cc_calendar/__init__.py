"""cc-calendar: a Google Calendar-style weekly view of Claude Code sessions."""

from importlib.metadata import PackageNotFoundError, version

# The version lives in pyproject.toml only.
try:
    __version__ = version("cc-calendar")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0+unknown"
